"""Light Timeline: schedule light brightness and color along a daily timeline."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from . import websocket
from .const import (
    DOMAIN,
    PANEL_COMPONENT,
    PANEL_URL,
    STATIC_URL,
    STORAGE_KEY,
    STORAGE_VERSION,
    VERSION,
)
from .engine import TimelineEngine

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = [Platform.SWITCH]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the websocket API and serve the panel files."""
    websocket.async_register(hass)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(Path(__file__).parent / "frontend"), False)]
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Light Timeline from a config entry."""
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    engine = TimelineEngine(hass, entry, store, await store.async_load() or {})
    entry.runtime_data = engine
    hass.data[DOMAIN] = engine

    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL,
        webcomponent_name=PANEL_COMPONENT,
        module_url=f"{STATIC_URL}/{PANEL_COMPONENT}.js?v={VERSION}",
        sidebar_title="Light Timeline",
        sidebar_icon="mdi:chart-timeline-variant",
        require_admin=True,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    @callback
    def _start(_hass: HomeAssistant) -> None:
        engine.async_start()

    entry.async_on_unload(async_at_started(hass, _start))
    entry.async_on_unload(engine.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    frontend.async_remove_panel(hass, PANEL_URL)
    hass.data.pop(DOMAIN, None)
    return True
