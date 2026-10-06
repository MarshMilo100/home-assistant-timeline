"""Switch to pause or resume all timelines."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the switch."""
    async_add_entities([TimelineSwitch(entry)])


class TimelineSwitch(SwitchEntity):
    """Turns the timeline scheduler on or off."""

    _attr_has_entity_name = True
    _attr_translation_key = "schedule"
    _attr_icon = "mdi:chart-timeline-variant"

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the switch."""
        self._engine = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_schedule"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Light Timeline",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def is_on(self) -> bool:
        """Return whether the scheduler is active."""
        return self._engine.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Resume the scheduler."""
        await self._engine.async_set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Pause the scheduler."""
        await self._engine.async_set_enabled(False)
        self.async_write_ha_state()
