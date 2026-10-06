"""Scheduler that drives lights from timeline nodes."""

from __future__ import annotations

from datetime import datetime
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
    STATE_UNAVAILABLE,
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

from .const import CONF_INTERVAL, CONF_LIGHTS, CONF_ONLY_WHEN_ON, DEFAULT_INTERVAL
from .interpolation import Node, plan, seconds_to_next_node


def _seconds_of_day() -> float:
    now = dt_util.now()
    return now.hour * 3600 + now.minute * 60 + now.second + now.microsecond / 1e6


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

    @property
    def lights(self) -> list[str]:
        """Lights shown in the editor: configured subset, or all lights."""
        return self.entry.options.get(CONF_LIGHTS) or sorted(
            self.hass.states.async_entity_ids(LIGHT_DOMAIN)
        )

    def _active(self) -> dict[str, list[Node]]:
        lights = set(self.lights)
        return {
            entity_id: sched["nodes"]
            for entity_id, sched in self.schedules.items()
            if entity_id in lights and sched.get("enabled", True) and sched["nodes"]
        }

    async def async_update_schedules(self, schedules: dict[str, dict]) -> None:
        """Replace all timelines, persist and re-apply."""
        self.schedules = schedules
        await self._async_save()
        self.async_start()

    async def async_set_enabled(self, enabled: bool) -> None:
        """Globally enable or pause the timeline."""
        self.enabled = enabled
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
            self.hass, list(self._active()), self._async_state_changed
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
        sec = _seconds_of_day()
        active = self._active()
        # Wake at the regular interval, or exactly at the next node if sooner.
        delay = float(self.entry.options.get(CONF_INTERVAL, DEFAULT_INTERVAL))
        for nodes in active.values():
            delay = min(delay, seconds_to_next_node(nodes, sec) + 0.05)
        delay = max(delay, 0.5)

        if self.enabled:
            for entity_id, nodes in active.items():
                self._async_apply(entity_id, nodes, sec, delay)
        self._unsub_timer = async_call_later(self.hass, delay, self._async_tick)

    @callback
    def _async_state_changed(self, event: Event[EventStateChangedData]) -> None:
        """Apply the timeline right away when a light is turned on by someone else."""
        entity_id = event.data["entity_id"]
        old, new = event.data["old_state"], event.data["new_state"]
        if (
            not self.enabled
            or new is None
            or new.state != STATE_ON
            or (old is not None and old.state == STATE_ON)
            or new.context.id == self._contexts.get(entity_id)
        ):
            return
        if nodes := self._active().get(entity_id):
            self._last.pop(entity_id, None)
            self._async_apply(entity_id, nodes, _seconds_of_day(), 0)

    @callback
    def _async_apply(
        self, entity_id: str, nodes: list[Node], sec: float, lookahead: float
    ) -> None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state == STATE_UNAVAILABLE:
            return
        if self.entry.options.get(CONF_ONLY_WHEN_ON) and state.state != STATE_ON:
            return

        target, transition = plan(nodes, sec, lookahead)
        data: dict[str, Any] = {}
        if target.brightness < 0.5:
            service = SERVICE_TURN_OFF
        else:
            service = SERVICE_TURN_ON
            modes = state.attributes.get(ATTR_SUPPORTED_COLOR_MODES) or []
            if brightness_supported(modes):
                data[ATTR_BRIGHTNESS] = max(1, round(target.brightness * 2.55))
            if target.kelvin and color_temp_supported(modes):
                data[ATTR_COLOR_TEMP_KELVIN] = target.kelvin
            elif target.kelvin and color_supported(modes):
                data[ATTR_RGB_COLOR] = tuple(
                    round(c) for c in color_temperature_to_rgb(target.kelvin)
                )
            elif target.rgb and color_supported(modes):
                data[ATTR_RGB_COLOR] = target.rgb

        # Only send when the target changed, so manual tweaks survive flat sections.
        if self._last.get(entity_id) == (service, data):
            return
        self._last[entity_id] = (service, data)

        context = Context()
        self._contexts[entity_id] = context.id
        call = {ATTR_ENTITY_ID: entity_id, **data}
        if transition > 0:
            call[ATTR_TRANSITION] = round(transition, 1)
        self.hass.async_create_task(
            self.hass.services.async_call(
                LIGHT_DOMAIN, service, call, context=context
            )
        )
