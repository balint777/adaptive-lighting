from __future__ import annotations
from typing import Any
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from .const import DOMAIN

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="Adaptive Lighting", data=user_input)
        return self.async_show_form(step_id="user", data_schema=self._schema())

    @callback
    def _schema(self):
        import voluptuous as vol
        return vol.Schema({
            vol.Optional("night_start", default="22:00"): str,
            vol.Optional("night_end", default="06:30"): str,
            vol.Optional("exclude_entities"): selector.selector({"entity": {"domain": "light", "multiple": True}}),
        })

    async def async_step_import(self, user_input: dict[str, Any] | None = None):
        return await self.async_step_user(user_input)

class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init", 
            data_schema=self._schema(),
            description_placeholders={
                "title": "Configure Adaptive Lighting Settings"
            }
        )

    @callback
    def _schema(self):
        import voluptuous as vol
        from homeassistant.helpers import selector
        o = self.config_entry.options
        return vol.Schema({
            vol.Optional("night_start", default=o.get("night_start", "22:00")): str,
            vol.Optional("night_end", default=o.get("night_end", "06:30")): str,
            vol.Optional("exclude_entities", default=o.get("exclude_entities", [])): selector.selector({"entity": {"domain": "light", "multiple": True}}),
        })
