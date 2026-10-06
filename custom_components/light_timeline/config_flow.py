"""Config flow for Light Timeline."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import CONF_INTERVAL, CONF_LIGHTS, CONF_ONLY_WHEN_ON, DEFAULT_INTERVAL, DOMAIN

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_LIGHTS, default=[]): EntitySelector(
            EntitySelectorConfig(domain="light", multiple=True)
        ),
        vol.Optional(CONF_INTERVAL, default=DEFAULT_INTERVAL): NumberSelector(
            NumberSelectorConfig(
                min=1, max=300, step=1, unit_of_measurement="s", mode=NumberSelectorMode.BOX
            )
        ),
        vol.Optional(CONF_ONLY_WHEN_ON, default=False): BooleanSelector(),
    }
)


class LightTimelineConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Light Timeline."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the single entry; lights are chosen in options."""
        return self.async_create_entry(title="Light Timeline", data={})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return LightTimelineOptionsFlow()


class LightTimelineOptionsFlow(OptionsFlow):
    """Choose lights and scheduling behavior."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )
