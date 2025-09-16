from __future__ import annotations
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .const import DOMAIN, PLATFORMS
from .coordinator import AdaptiveController, Settings

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    s = Settings(
        night_start=entry.options.get("night_start", entry.data.get("night_start", "22:00")),
        night_end=entry.options.get("night_end", entry.data.get("night_end", "06:30")),
        exclude_entities=entry.options.get("exclude_entities", entry.data.get("exclude_entities", [])),
    )

    controller = AdaptiveController(hass, s)
    controller.start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = controller
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Set up options update listener
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    
    return True

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update settings when options are changed."""
    controller: AdaptiveController = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if controller:
        # Create new settings object
        s = Settings(
            night_start=entry.options.get("night_start", entry.data.get("night_start", "22:00")),
            night_end=entry.options.get("night_end", entry.data.get("night_end", "06:30")),
            exclude_entities=entry.options.get("exclude_entities", entry.data.get("exclude_entities", [])),
        )
        # Update settings without full restart
        controller.update_settings(s)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    controller: AdaptiveController = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if controller:
        controller.stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
