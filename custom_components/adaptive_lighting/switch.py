from __future__ import annotations
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    controller = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AdaptiveSwitch(controller, entry.entry_id)])

class AdaptiveSwitch(RestoreEntity, SwitchEntity):
    _attr_name = "Adaptive Lighting"
    _attr_icon = "mdi:theme-light-dark"
    _attr_should_poll = False

    def __init__(self, controller, entry_id: str) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry_id}_adaptive_lighting"

    @property
    def is_on(self) -> bool:
        return self._controller.is_enabled()

    async def async_added_to_hass(self) -> None:
        """Restore the user's enabled/disabled choice after restart."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in {STATE_ON, STATE_OFF}:
            self._controller.set_enabled(last_state.state == STATE_ON)

    async def async_turn_on(self, **kwargs):
        self._controller.set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self._controller.set_enabled(False)
        self.async_write_ha_state()
