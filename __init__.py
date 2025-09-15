from __future__ import annotations
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .const import DOMAIN, PLATFORMS
from .coordinator import AdaptiveController, Settings

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    s = Settings(
        interval=entry.options.get("interval", entry.data.get("interval", 30)),
        transition=entry.options.get("transition", entry.data.get("transition", 2)),
        min_k=entry.options.get("min_k", entry.data.get("min_k", 2200)),
        max_k=entry.options.get("max_k", entry.data.get("max_k", 6500)),
        min_b=entry.options.get("min_b", entry.data.get("min_b", 10)),
        max_b=entry.options.get("max_b", entry.data.get("max_b", 90)),
        only_when_on=entry.options.get("only_when_on", entry.data.get("only_when_on", True)),
        manual_hold_s=entry.options.get("manual_hold_s", entry.data.get("manual_hold_s", 900)),
        night_start=entry.options.get("night_start", entry.data.get("night_start", "22:00")),
        night_end=entry.options.get("night_end", entry.data.get("night_end", "06:30")),
        sleep_k=entry.options.get("sleep_kelvin", entry.data.get("sleep_kelvin", 2200)),
        sleep_b=entry.options.get("sleep_brightness", entry.data.get("sleep_brightness", 20)),
        auto_discover=entry.options.get("auto_discover", entry.data.get("auto_discover", True)),
        include_areas=entry.options.get("include_areas", entry.data.get("include_areas", [])),
        include_entities=entry.options.get("include_entities", entry.data.get("include_entities", [])),
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
    """Reload config entry when options are updated."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    controller: AdaptiveController = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if controller:
        controller.stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
