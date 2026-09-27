from __future__ import annotations
import logging

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_EXCLUDE_ENTITIES,
    CONF_NIGHT_END,
    CONF_NIGHT_START,
    DEFAULT_NIGHT_END,
    DEFAULT_NIGHT_START,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import AdaptiveController, Settings

_LOGGER = logging.getLogger(__name__)


def _settings_from_entry(entry: ConfigEntry) -> Settings:
    """Build controller settings from entry options/data."""
    return Settings(
        wind_down_target=entry.options.get(
            CONF_NIGHT_START, entry.data.get(CONF_NIGHT_START, DEFAULT_NIGHT_START)
        ),
        wake_up=entry.options.get(
            CONF_NIGHT_END, entry.data.get(CONF_NIGHT_END, DEFAULT_NIGHT_END)
        ),
        exclude_entities=entry.options.get(
            CONF_EXCLUDE_ENTITIES, entry.data.get(CONF_EXCLUDE_ENTITIES, [])
        ),
    )

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data:
        _LOGGER.error(
            "Ignoring duplicate Adaptive Lighting config entry %s; remove the "
            "extra entry because only one global controller is supported",
            entry.entry_id,
        )
        return True

    controller = AdaptiveController(
        hass,
        _settings_from_entry(entry),
        entry.entry_id,
    )
    # Reserve the singleton slot before the first await so concurrently restored
    # duplicate entries cannot both start global controllers.
    domain_data[entry.entry_id] = controller

    try:
        await controller.async_start()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        _LOGGER.exception("Failed to set up Adaptive Lighting")
        controller.stop()
        domain_data.pop(entry.entry_id, None)
        raise
    
    # Set up options update listener
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    
    return True

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update settings when options are changed."""
    controller: AdaptiveController = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if controller:
        controller.update_settings(_settings_from_entry(entry))

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    domain_data = hass.data.get(DOMAIN, {})
    controller: AdaptiveController = domain_data.pop(entry.entry_id, None)
    if controller:
        controller.stop()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not domain_data:
        hass.data.pop(DOMAIN, None)
    return unload_ok
