"""Resolve daily timeline nodes against local calendar and solar events."""

from datetime import date, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.util import dt as dt_util

from .interpolation import DAY, Node

WEEKDAYS = list(range(7))


def solar_events(hass: HomeAssistant, day: date) -> dict[str, int | None]:
    events = {}
    for event in ("sunrise", "sunset"):
        instant = get_astral_event_date(hass, event, day)
        local = dt_util.as_local(instant) if instant else None
        events[event] = local.hour * 3600 + local.minute * 60 + local.second if local else None
    return events


def calendar(hass: HomeAssistant) -> list[dict[str, Any]]:
    today = dt_util.now().date()
    return [
        {"date": day.isoformat(), "weekday": day.weekday(), "events": solar_events(hass, day)}
        for day in (today + timedelta(days=offset) for offset in range(7))
    ]


def resolve_nodes(schedule: dict, events: dict[str, int | None], weekday: int) -> list[Node]:
    if weekday not in schedule.get("days", WEEKDAYS):
        return []
    resolved = {}
    for node in schedule["nodes"]:
        if weekday not in node.get("days", WEEKDAYS):
            continue
        anchor = node.get("anchor", "time")
        seconds = node["t"] if anchor == "time" else events.get(anchor)
        if seconds is None:
            continue
        seconds = (seconds + (node.get("offset", 0) if anchor != "time" else 0)) % DAY
        resolved[seconds] = {**node, "t": seconds}
    return [resolved[seconds] for seconds in sorted(resolved)]