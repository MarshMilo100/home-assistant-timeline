"""Websocket API used by the timeline panel."""

from __future__ import annotations

from operator import itemgetter
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .engine import TimelineEngine
from .interpolation import CURVES, DAY, EASINGS

NODE_SCHEMA = vol.Schema(
    {
        vol.Required("t"): vol.All(vol.Coerce(int), vol.Range(0, DAY - 1)),
        vol.Required("b"): vol.All(vol.Coerce(float), vol.Range(0, 100)),
        vol.Optional("mode", default="none"): vol.In(["none", "ct", "rgb"]),
        vol.Optional("k", default=2700): vol.All(
            vol.Coerce(int), vol.Range(1000, 12000)
        ),
        vol.Optional("rgb", default=[255, 255, 255]): vol.All(
            [vol.All(vol.Coerce(int), vol.Range(0, 255))], vol.Length(3, 3)
        ),
        vol.Optional("ease", default="linear"): vol.In(list(EASINGS)),
        vol.Optional("curve", default="linear"): vol.In(list(CURVES)),
    }
)

SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Optional("enabled", default=True): bool,
        vol.Optional("fade_to_warm", default=False): bool,
        vol.Required("nodes"): vol.All([NODE_SCHEMA], vol.Length(max=1000)),
    }
)


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register websocket commands."""
    websocket_api.async_register_command(hass, ws_get)
    websocket_api.async_register_command(hass, ws_save)


def _engine(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> TimelineEngine | None:
    engine = hass.data.get(DOMAIN)
    if engine is None:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Light Timeline is not set up"
        )
    return engine


@websocket_api.websocket_command({vol.Required("type"): "light_timeline/get"})
@callback
def ws_get(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Return the editable lights and their timelines."""
    if (engine := _engine(hass, connection, msg)) is None:
        return
    connection.send_result(
        msg["id"], {"lights": engine.lights, "schedules": engine.schedules}
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "light_timeline/save",
        vol.Required("schedules"): {cv.entity_id: SCHEDULE_SCHEMA},
    }
)
@websocket_api.async_response
async def ws_save(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> None:
    """Store timelines."""
    if (engine := _engine(hass, connection, msg)) is None:
        return
    schedules: dict[str, Any] = {
        entity_id: {**sched, "nodes": sorted(sched["nodes"], key=itemgetter("t"))}
        for entity_id, sched in msg["schedules"].items()
    }
    await engine.async_update_schedules(schedules)
    connection.send_result(msg["id"])
