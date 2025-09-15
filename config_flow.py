from __future__ import annotations
from typing import Any
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from .const import DOMAIN

class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="Adaptive Lighting", data=user_input)
        return self.async_show_form(step_id="user", data_schema=self._schema())

    @callback
    def _schema(self):
        import voluptuous as vol
        return vol.Schema({
            vol.Optional("interval", default=30): int,
            vol.Optional("transition", default=2): int,
            vol.Optional("min_k", default=2200): int,
            vol.Optional("max_k", default=6500): int,
            vol.Optional("min_b", default=10): int,
            vol.Optional("max_b", default=90): int,
            vol.Optional("only_when_on", default=True): bool,
            vol.Optional("manual_hold_s", default=900): int,
            vol.Optional("night_start", default="22:00"): str,
            vol.Optional("night_end", default="06:30"): str,
            vol.Optional("sleep_kelvin", default=2200): int,
            vol.Optional("sleep_brightness", default=20): int,
            vol.Optional("auto_discover", default=True): bool,
            vol.Optional("include_areas"): selector.selector({"area": {"multiple": True}}),
            vol.Optional("include_entities"): selector.selector({"entity": {"domain": "light", "multiple": True}}),
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
        return self.async_show_form(step_id="init", data_schema=self._schema())

    @callback
    def _schema(self):
        import voluptuous as vol
        from homeassistant.helpers import selector
        o = self.config_entry.options
        return vol.Schema({
            vol.Optional("interval", default=o.get("interval", 30)): int,
            vol.Optional("transition", default=o.get("transition", 2)): int,
            vol.Optional("min_k", default=o.get("min_k", 2200)): int,
            vol.Optional("max_k", default=o.get("max_k", 6500)): int,
            vol.Optional("min_b", default=o.get("min_b", 10)): int,
            vol.Optional("max_b", default=o.get("max_b", 90)): int,
            vol.Optional("only_when_on", default=o.get("only_when_on", True)): bool,
            vol.Optional("manual_hold_s", default=o.get("manual_hold_s", 900)): int,
            vol.Optional("night_start", default=o.get("night_start", "22:00")): str,
            vol.Optional("night_end", default=o.get("night_end", "06:30")): str,
            vol.Optional("sleep_kelvin", default=o.get("sleep_kelvin", 2200)): int,
            vol.Optional("sleep_brightness", default=o.get("sleep_brightness", 20)): int,
            vol.Optional("auto_discover", default=o.get("auto_discover", True)): bool,
            vol.Optional("include_areas", default=o.get("include_areas", [])): selector.selector({"area": {"multiple": True}}),
            vol.Optional("include_entities", default=o.get("include_entities", [])): selector.selector({"entity": {"domain": "light", "multiple": True}}),
            vol.Optional("exclude_entities", default=o.get("exclude_entities", [])): selector.selector({"entity": {"domain": "light", "multiple": True}}),
        })

async def async_get_options_flow(config_entry):
    return OptionsFlowHandler(config_entry)
