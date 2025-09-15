from __future__ import annotations
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
        self._manual_hold_until: Dict[str, float] = {}
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
        # Apply
        data_ct = {"transition": self.settings.transition, "brightness_pct": b_pct}
        data_rgb = {"transition": self.settings.transition, "brightness_pct": b_pct}
        data_ct["color_temp_kelvin"] = k
        r, g, b = cct_to_rgb(k)
        data_rgb["rgb_color"] = [r, g, b]

        for ent_id, mode in targets.items():
            state = self.hass.states.get(ent_id)
            if not state:
                continue
            if self.settings.only_when_on and state.state != "on":
                continue

            # Manual hold check: if user touched the light (brightness/ct) recently, skip
            last_changed = state.last_changed.timestamp() if state.last_changed else 0
            hold_until = self._manual_hold_until.get(ent_id, 0)
            if last_changed and (last_changed > hold_until):
                # set new hold window
                self._manual_hold_until[ent_id] = last_changed + self.settings.manual_hold_s
                continue

            # Apply service call
            payload = data_ct if mode == "ct" else data_rgb
            await self.hass.services.async_call(
                "light",
                "turn_on",
                {"entity_id": ent_id, **payload},
                blocking=False,
            )

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

        for ent_id, state in self.hass.states.async_all("light"):
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
