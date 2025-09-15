from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from datetime import timedelta, time
from typing import Dict, List, Optional, Set

from homeassistant.core import HomeAssistant, callback
from homeassistant.const import ATTR_SUPPORTED_FEATURES
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers import entity_registry, area_registry
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_ELEVATION,
    CONF_INTERVAL,
    CONF_TRANSITION,
    CONF_MIN_K,
    CONF_MAX_K,
    CONF_MIN_B,
    CONF_MAX_B,
    CONF_ONLY_WHEN_ON,
    CONF_MANUAL_HOLD_S,
    CONF_NIGHT_START,
    CONF_NIGHT_END,
    CONF_SLEEP_K,
    CONF_SLEEP_B,
    CONF_INCLUDE_AREAS,
    CONF_EXCLUDE_ENTITIES,
    CONF_INCLUDE_ENTITIES,
    CONF_AUTO_DISCOVER,
    DEFAULT_INTERVAL,
    DEFAULT_TRANSITION,
    DEFAULT_MIN_K,
    DEFAULT_MAX_K,
    DEFAULT_MIN_B,
    DEFAULT_MAX_B,
    DEFAULT_ONLY_WHEN_ON,
    DEFAULT_MANUAL_HOLD_S,
    DEFAULT_NIGHT_START,
    DEFAULT_NIGHT_END,
    DEFAULT_SLEEP_K,
    DEFAULT_SLEEP_B,
)
from .util import clamp, lerp, parse_time_str, in_window, cct_to_rgb

SUPPORTED_COLOR_KEYS = {"supported_color_modes", "color_mode", "color_modes"}

@dataclass
class Settings:
    interval: int = DEFAULT_INTERVAL
    transition: int = DEFAULT_TRANSITION
    min_k: int = DEFAULT_MIN_K
    max_k: int = DEFAULT_MAX_K
    min_b: int = DEFAULT_MIN_B
    max_b: int = DEFAULT_MAX_B
    only_when_on: bool = DEFAULT_ONLY_WHEN_ON
    manual_hold_s: int = DEFAULT_MANUAL_HOLD_S
    night_start: str = DEFAULT_NIGHT_START
    night_end: str = DEFAULT_NIGHT_END
    sleep_k: int = DEFAULT_SLEEP_K
    sleep_b: int = DEFAULT_SLEEP_B
    auto_discover: bool = True
    include_areas: List[str] = field(default_factory=list)
    include_entities: List[str] = field(default_factory=list)
    exclude_entities: List[str] = field(default_factory=list)


class AdaptiveController:
    def __init__(self, hass: HomeAssistant, settings: Settings):
        self.hass = hass
        self.settings = settings
        self._unsub = None
        self._manual_hold_entities: Set[str] = set()  # Entities with manual adjustments
        self._last_turn_on: Dict[str, float] = {}  # Track when entities were turned on
        self._last_automation_change: Dict[str, float] = {}  # Track our own changes
        self._enabled = True

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def is_enabled(self) -> bool:
        return self._enabled

    def start(self):
        self.stop()
        interval = timedelta(seconds=self.settings.interval)
        self._unsub = async_track_time_interval(self.hass, self._apply_all, interval)

    def stop(self):
        if self._unsub:
            self._unsub()
            self._unsub = None

    @callback
    async def _apply_all(self, _now=None):
        if not self._enabled:
            return
        # Determine targets
        targets = self._discover_targets()
        # Determine target CT/brightness from sun/time
        b_pct, k = self._compute_targets()

        for ent_id, mode in targets.items():
            state = self.hass.states.get(ent_id)
            if not state:
                continue
            if self.settings.only_when_on and state.state != "on":
                continue

            # Track when light was turned on
            is_new_turn_on = False
            if state.state == "on":
                state_changed = state.last_changed.timestamp() if state.last_changed else 0
                last_turn_on = self._last_turn_on.get(ent_id, 0)
                
                # If this is a new turn-on event, clear manual hold and update turn-on time
                if state_changed > last_turn_on:
                    self._last_turn_on[ent_id] = state_changed
                    # Clear manual hold when light is turned on
                    self._manual_hold_entities.discard(ent_id)
                    is_new_turn_on = True

            # Manual hold check: detect if user manually adjusted the light
            last_changed = state.last_changed.timestamp() if state.last_changed else 0
            last_turn_on = self._last_turn_on.get(ent_id, 0)
            last_automation = self._last_automation_change.get(ent_id, 0)
            
            # If the light changed after turn-on and it wasn't from our automation, it's manual
            if (last_changed > last_turn_on and 
                last_changed > last_automation and 
                last_changed > 0):
                self._manual_hold_entities.add(ent_id)
            
            # Skip if entity is in manual hold (but not for new turn-on events)
            if ent_id in self._manual_hold_entities and not is_new_turn_on:
                continue

            # Apply light settings using the helper method
            await self._apply_light_settings(ent_id, mode, b_pct, k)

    async def _apply_light_settings(self, ent_id: str, mode: str, b_pct: int, k: int) -> None:
        """Apply brightness and color settings to a specific light entity."""
        # Prepare separate brightness and color data
        data_brightness = {"transition": self.settings.transition, "brightness_pct": b_pct}
        data_ct_color = {"transition": self.settings.transition, "color_temp_kelvin": k}
        r, g, b = cct_to_rgb(k)
        data_rgb_color = {"transition": self.settings.transition, "rgb_color": [r, g, b]}

        # Apply brightness first
        await self.hass.services.async_call(
            "light",
            "turn_on",
            {"entity_id": ent_id, **data_brightness},
            blocking=False,
        )
        
        # Wait 200ms before applying color
        await asyncio.sleep(0.2)
        
        # Apply color/temperature
        color_payload = data_ct_color if mode == "ct" else data_rgb_color
        await self.hass.services.async_call(
            "light",
            "turn_on",
            {"entity_id": ent_id, **color_payload},
            blocking=False,
        )
        
        # Record that we made this change
        import time
        self._last_automation_change[ent_id] = time.time()

    # --------------------------- helpers ----------------------------------
    def _discover_targets(self) -> Dict[str, str]:
        # Return mapping entity_id -> mode ("ct" or "rgb")
        out: Dict[str, str] = {}
        ent_reg = entity_registry.async_get(self.hass)
        area_reg = area_registry.async_get(self.hass)

        def allowed(ent_id: str) -> bool:
            if self.settings.include_entities and ent_id not in self.settings.include_entities:
                return False
            if ent_id in self.settings.exclude_entities:
                return False
            if self.settings.include_areas:
                entry = ent_reg.async_get(ent_id)
                if not entry or not entry.area_id:
                    return False
                area = area_reg.async_get_area(entry.area_id)
                if not area or area.name not in self.settings.include_areas:
                    return False
            return True

        for state in self.hass.states.async_all("light"):
            ent_id = state.entity_id
            if not allowed(ent_id):
                continue
            attrs = state.attributes or {}
            color_modes = None
            for key in SUPPORTED_COLOR_KEYS:
                if key in attrs:
                    color_modes = attrs.get(key)
                    break
            # Normalize
            if isinstance(color_modes, set):
                modes = color_modes
            elif isinstance(color_modes, list):
                modes = set(color_modes)
            else:
                modes = set()

            has_brightness = "brightness" in attrs or "brightness" in modes
            supports_ct = "color_temp" in modes or "color_temp" in attrs
            supports_rgb = any(m in modes for m in ("hs", "rgb"))

            if not has_brightness:
                continue
            if supports_ct:
                out[ent_id] = "ct"
            elif supports_rgb:
                out[ent_id] = "rgb"
        return out

    def _compute_targets(self):
        # Sleep window override
        now = dt_util.now().time()
        if in_window(now, parse_time_str(self.settings.night_start), parse_time_str(self.settings.night_end)):
            return (self.settings.sleep_b, self.settings.sleep_k)

        sun = self.hass.states.get("sun.sun")
        elev = -6.0
        if sun:
            elev = float(sun.attributes.get(ATTR_ELEVATION, -6.0))
        t = clamp((elev + 6.0) / (60.0 + 6.0), 0.0, 1.0)
        b = int(round(lerp(self.settings.min_b, self.settings.max_b, t)))
        k = int(round(lerp(self.settings.min_k, self.settings.max_k, t)))
        return (b, k)
