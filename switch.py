from __future__ import annotations
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    controller = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AdaptiveSwitch(controller)])

class AdaptiveSwitch(SwitchEntity):
    _attr_name = "Adaptive Lighting"
    _attr_icon = "mdi:theme-light-dark"

    def __init__(self, controller) -> None:
        self._controller = controller
        self._attr_is_on = True

    async def async_turn_on(self, **kwargs):
        self._controller.set_enabled(True)
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self._controller.set_enabled(False)
        self._attr_is_on = False
        self.async_write_ha_state()
