"""Scheduler that drives lights from timeline nodes."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ATTR_SUPPORTED_COLOR_MODES,
    ATTR_TRANSITION,
    DOMAIN as LIGHT_DOMAIN,
    brightness_supported,
    color_supported,
    color_temp_supported,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_OFF,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Context,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.color import color_temperature_to_rgb

from .const import CONF_INTERVAL, CONF_LIGHTS, CONF_ONLY_WHEN_ON, DEFAULT_INTERVAL, DEFAULT_RESUME_TRANSITION
from .interpolation import Node, plan, seconds_to_next_node, segment_easings, target_at
from .scheduling import resolve_nodes, solar_events


def _seconds_of_day() -> float:
    now = dt_util.now()
    return now.hour * 3600 + now.minute * 60 + now.second + now.microsecond / 1e6


@dataclass
class ManualOverride:
    deadline: float
    destination: Node
    ease: str
    curve: str
    started: float | None = None
    nodes: list[Node] | None = None
    following: float | None = None


def _state_node(state) -> Node:
    attrs = state.attributes
    node = {"t": 0, "b": attrs.get(ATTR_BRIGHTNESS, 255) / 2.55 if state.state == STATE_ON else 0, "mode": "none"}
    mode = attrs.get("color_mode")
    if attrs.get(ATTR_COLOR_TEMP_KELVIN) and (mode == "color_temp" or not attrs.get(ATTR_RGB_COLOR)):
        node.update(mode="ct", k=attrs[ATTR_COLOR_TEMP_KELVIN])
    elif attrs.get(ATTR_RGB_COLOR):
        node.update(mode="rgb", rgb=list(attrs[ATTR_RGB_COLOR]))
    return node


class TimelineEngine:
    """Stores timelines and applies them to lights on a schedule."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, store: Store, data: dict
    ) -> None:
        """Initialize the engine."""
        self.hass = hass
        self.entry = entry
        self._store = store
        self.enabled: bool = data.get("enabled", True)
        self.schedules: dict[str, dict[str, Any]] = data.get("schedules", {})
        self._unsub_timer: CALLBACK_TYPE | None = None
        self._unsub_state: CALLBACK_TYPE | None = None
        self._last: dict[str, tuple[str, dict[str, Any]]] = {}
        self._contexts: dict[str, str] = {}
        self._own_contexts: dict[str, deque[str]] = {}
        self._overrides: dict[str, ManualOverride] = {}
        self._day = None
        self._solar_key = None
        self._solar_events: dict[str, int | None] = {}

    @property
    def lights(self) -> list[str]:
        """Lights shown in the editor: configured subset, or all lights."""
        return self.entry.options.get(CONF_LIGHTS) or sorted(
            self.hass.states.async_entity_ids(LIGHT_DOMAIN)
        )

    def _active(self) -> dict[str, list[Node]]:
        lights = set(self.lights)
        now = dt_util.now()
        config = self.hass.config
        key = (now.date(), config.latitude, config.longitude, config.elevation, config.time_zone)
        if key != self._solar_key:
            self._solar_events = solar_events(self.hass, now.date())
            self._solar_key = key
        active = {}
        for entity_id, sched in self.schedules.items():
            if entity_id in lights and sched.get("enabled", True):
                nodes = resolve_nodes(sched, self._solar_events, now.weekday())
                if nodes:
                    active[entity_id] = nodes
        return active

    async def async_update_schedules(self, schedules: dict[str, dict]) -> None:
        """Replace all timelines, persist and re-apply."""
        self.schedules = schedules
        self._overrides.clear()
        await self._async_save()
        self.async_start()

    async def async_set_enabled(self, enabled: bool) -> None:
        """Globally enable or pause the timeline."""
        self.enabled = enabled
        self._overrides.clear()
        await self._async_save()
        self.async_start()

    async def _async_save(self) -> None:
        await self._store.async_save(
            {"enabled": self.enabled, "schedules": self.schedules}
        )

    @callback
    def async_start(self) -> None:
        """(Re)start the scheduling loop."""
        self.async_stop()
        self._last.clear()
        self._unsub_state = async_track_state_change_event(
            self.hass, self.lights, self._async_state_changed
        )
        self._async_tick()

    @callback
    def async_stop(self) -> None:
        """Stop the scheduling loop."""
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None

    @callback
    def _async_tick(self, _now: datetime | None = None) -> None:
        today = dt_util.now().date()
        if today != self._day:
            self._last.clear()
            self._day = today
        sec = _seconds_of_day()
        active = self._active()
        # Wake at the regular interval, or exactly at the next node if sooner.
        delay = min(float(self.entry.options.get(CONF_INTERVAL, DEFAULT_INTERVAL)), 86400 - sec + 0.05)
        for nodes in active.values():
            delay = min(delay, seconds_to_next_node(nodes, sec) + 0.05)
        timestamp = dt_util.now().timestamp()
        for entity_id, override in list(self._overrides.items()):
            if override.started is not None or override.deadline <= timestamp:
                if entity_id not in active:
                    self._overrides.pop(entity_id)
                else:
                    delay = min(delay, 1)
            else:
                delay = min(delay, max(0.5, override.deadline - timestamp + 0.05))
        delay = max(delay, 0.5)

        if self.enabled:
            for entity_id, nodes in active.items():
                self._async_apply(entity_id, nodes, sec, min(delay, max(0, 86400 - sec - 0.05)))
        self._unsub_timer = async_call_later(self.hass, delay, self._async_tick)

    @callback
    def _async_state_changed(self, event: Event[EventStateChangedData]) -> None:
        """Hold externally changed light states until the next scheduled node."""
        entity_id = event.data["entity_id"]
        old, new = event.data["old_state"], event.data["new_state"]
        if (
            not self.enabled
            or old is None
            or new is None
            or old.state in (STATE_UNAVAILABLE, STATE_UNKNOWN)
            or new.state not in (STATE_ON, STATE_OFF)
        ):
            return
        contexts = self._own_contexts.get(entity_id, ())
        if new.context.id in contexts or new.context.parent_id in contexts:
            return
        properties = (ATTR_BRIGHTNESS, ATTR_COLOR_TEMP_KELVIN, ATTR_RGB_COLOR, "hs_color", "xy_color", "color_mode")
        if old.state == new.state and all(old.attributes.get(key) == new.attributes.get(key) for key in properties):
            return
        if override := self._next_event(entity_id, dt_util.now()):
            self._overrides[entity_id] = override
            self._last.pop(entity_id, None)

    def _next_event(self, entity_id: str, now: datetime) -> ManualOverride | None:
        schedule = self.schedules.get(entity_id)
        if not schedule or not schedule.get("enabled", True) or entity_id not in self.lights:
            return None
        for offset in range(8):
            day = now.date() + timedelta(days=offset)
            nodes = resolve_nodes(schedule, solar_events(self.hass, day), day.weekday())
            for index, node in enumerate(nodes):
                instant = now.replace(year=day.year, month=day.month, day=day.day, hour=node["t"] // 3600, minute=node["t"] % 3600 // 60, second=node["t"] % 60, microsecond=0)
                if instant.timestamp() > now.timestamp():
                    predecessor = nodes[index - 1]
                    incoming = segment_easings(predecessor, node)[1]
                    return ManualOverride(instant.timestamp(), node, incoming, predecessor.get("curve", "linear"))
        return None

    @callback
    def _async_apply(
        self, entity_id: str, nodes: list[Node], sec: float, lookahead: float
    ) -> None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        if self.entry.options.get(CONF_ONLY_WHEN_ON) and state.state != STATE_ON:
            return

        override = self._overrides.get(entity_id)
        now = dt_util.now().timestamp()
        if override and override.following is not None and now >= override.following:
            self._overrides.pop(entity_id)
            override = None
        if override and now < override.deadline:
            return
        if override and override.started is None:
            goal = target_at([override.destination], 0, self.schedules[entity_id].get("fade_to_warm", False))
            start = {**_state_node(state), "ease": override.ease, "curve": override.curve}
            end = {"t": DEFAULT_RESUME_TRANSITION, "b": goal.brightness, "mode": "none"}
            if goal.kelvin is not None:
                end.update(mode="ct", k=goal.kelvin)
            elif goal.rgb is not None:
                end.update(mode="rgb", rgb=list(goal.rgb))
            if start["mode"] == "none":
                start.update({key: value for key, value in end.items() if key in ("mode", "k", "rgb")})
            override.nodes = [start, end]
            override.started = now
            if following := self._next_event(entity_id, dt_util.now()):
                override.following = following.deadline
        if override and override.nodes is not None and override.started is not None:
            elapsed = now - override.started
            if elapsed < DEFAULT_RESUME_TRANSITION:
                transition = min(1.0, DEFAULT_RESUME_TRANSITION - elapsed)
                if override.following is not None:
                    transition = min(transition, max(0, override.following - now))
                target = target_at(override.nodes, min(DEFAULT_RESUME_TRANSITION, elapsed + transition))
            else:
                self._overrides.pop(entity_id)
                target = target_at(override.nodes, DEFAULT_RESUME_TRANSITION)
                transition = 0
        else:
            target, transition = plan(nodes, sec, lookahead, self.schedules[entity_id].get("fade_to_warm", False))
        data: dict[str, Any] = {}
        if target.brightness < 0.5:
            service = SERVICE_TURN_OFF
        else:
            service = SERVICE_TURN_ON
            modes = state.attributes.get(ATTR_SUPPORTED_COLOR_MODES) or []
            if brightness_supported(modes):
                data[ATTR_BRIGHTNESS] = max(1, round(target.brightness * 2.55))
            if target.kelvin:
                minimum = state.attributes.get("min_color_temp_kelvin", 1000)
                maximum = state.attributes.get("max_color_temp_kelvin", 12000)
                if color_temp_supported(modes):
                    data[ATTR_COLOR_TEMP_KELVIN] = min(maximum, max(minimum, target.kelvin))
                elif color_supported(modes):
                    data[ATTR_RGB_COLOR] = tuple(
                        round(c) for c in color_temperature_to_rgb(target.kelvin)
                    )
            elif target.rgb and color_supported(modes):
                data[ATTR_RGB_COLOR] = target.rgb

        if self._last.get(entity_id) == (service, data):
            return
        self._last[entity_id] = (service, data)

        context = Context()
        self._contexts[entity_id] = context.id
        self._own_contexts.setdefault(entity_id, deque(maxlen=256)).append(context.id)
        call = {ATTR_ENTITY_ID: entity_id, **data}
        if transition > 0:
            call[ATTR_TRANSITION] = round(transition, 1)
        self.hass.async_create_task(
            self.hass.services.async_call(
                LIGHT_DOMAIN, service, call, context=context
            )
        )
