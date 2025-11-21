from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from datetime import timedelta, time
from typing import Dict, List, Optional, Set

from homeassistant.core import HomeAssistant, callback, Event
from homeassistant.const import ATTR_SUPPORTED_FEATURES, EVENT_STATE_CHANGED
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers import entity_registry, area_registry
from homeassistant.util import dt as dt_util

from .const import (
    CONF_NIGHT_START,
    CONF_NIGHT_END,
    CONF_EXCLUDE_ENTITIES,
    DEFAULT_NIGHT_START,
    DEFAULT_NIGHT_END
)
from .util import clamp, lerp, parse_time_str, in_window, cct_to_rgb, is_in_transition_period

SUPPORTED_COLOR_KEYS = {"supported_color_modes", "color_mode", "color_modes"}

@dataclass
class Settings:
    wind_down_target: str = DEFAULT_NIGHT_START
    wake_up: str = DEFAULT_NIGHT_END
    exclude_entities: List[str] = field(default_factory=list)

    # Hardcoded values (not configurable by user)
    @property
    def interval(self) -> int:
        return 120 # seconds
    
    @property
    def transition(self) -> int:
        return 2 # seconds
    
    @property
    def sleep_b(self) -> int:
        return 1 # 1% brightness during sleep
    
    @property
    def sleep_k(self) -> int:
        return 2200 # warm color temperature during sleep



class AdaptiveController:
    def __init__(self, hass: HomeAssistant, settings: Settings):
        self.hass = hass
        self.settings = settings
        self._unsub = None
        self._event_unsub = None  # For event tracking
        self._manual_hold_entities: Set[str] = set()  # Entities with manual adjustments
        self._last_automation_change: Dict[str, float] = {}  # Track our own changes
        self._pending_tasks: Dict[str, asyncio.Task] = {}  # Track pending operations per entity
        self._enabled = True

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def is_enabled(self) -> bool:
        return self._enabled

    def update_settings(self, new_settings: Settings) -> None:
        """Update settings without restarting the controller."""
        old_interval = self.settings.interval
        self.settings = new_settings
        
        # If interval changed, restart the timer
        if old_interval != new_settings.interval:
            if self._unsub:
                self._unsub()
                interval = timedelta(seconds=self.settings.interval)
                self._unsub = async_track_time_interval(self.hass, self._apply_all, interval)

    def start(self):
        self.stop()
        interval = timedelta(seconds=self.settings.interval)
        self._unsub = async_track_time_interval(self.hass, self._apply_all, interval)
        
        # Set up event listener for state change events
        self._event_unsub = self.hass.bus.async_listen(
            EVENT_STATE_CHANGED, self._handle_light_turn_on
        )

    def stop(self):
        if self._unsub:
            self._unsub()
            self._unsub = None
        if self._event_unsub:
            self._event_unsub()
            self._event_unsub = None

    @callback
    async def _apply_all(self, _now=None):
        if not self._enabled:
            return
        # Determine targets
        targets = self._discover_targets()
        # Determine target CT/brightness from sun/time
        brightness, k = self._compute_targets()

        for ent_id, mode in targets.items():
            state = self.hass.states.get(ent_id)
            if not state:
                continue
            if state.state != "on":
                continue

            # Skip if entity is in manual hold
            if ent_id in self._manual_hold_entities:
                continue

            # Apply light settings for periodic updates (not turn-on events)
            await self._apply_light_settings(ent_id, mode, brightness, k)

    async def _apply_light_settings(self, ent_id: str, mode: str, brightness: int, k: int) -> None:
        """Apply brightness and color settings to a specific light entity."""
        # Prepare separate brightness and color data
        data_brightness = {"transition": self.settings.transition, "brightness_pct": brightness}
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
        
        # Wait transition before applying color
        await asyncio.sleep(self.settings.transition)
        
        # Check if light is still on before applying color
        state = self.hass.states.get(ent_id)
        if not state or state.state != "on":
            # Light was turned off during transition, don't apply color
            return
        
        # Apply color/temperature
        color_payload = data_ct_color if mode == "ct" else data_rgb_color
        await self.hass.services.async_call(
            "light",
            "turn_on",
            {"entity_id": ent_id, **color_payload},
            blocking=False,
        )
        
        # Record that we made this change
        self._last_automation_change[ent_id] = time.time()

    @callback
    async def _handle_light_turn_on(self, event: Event) -> None:
        """Handle state change events for manual hold detection and turn-on control."""
        if not self._enabled:
            return

        # Check if this is a light event
        event_data = event.data
        entity_id = event_data.get("entity_id")
        old_state = event_data.get("old_state")
        new_state = event_data.get("new_state")

        if not entity_id or not entity_id.startswith("light."):
            return

        if not new_state:
            return

        # Check if this light is a valid target
        targets = self._discover_targets()
        if entity_id not in targets:
            return
        
        # Handle turn-off events - cancel any pending operations
        if new_state.state == "off" and old_state and old_state.state == "on":
            if entity_id in self._pending_tasks:
                self._pending_tasks[entity_id].cancel()
                del self._pending_tasks[entity_id]
            return

        # Handle turn-on events
        if new_state.state == "on" and (not old_state or old_state.state != "on"):
            # Light was turned on - clear manual hold and cancel any pending tasks
            self._manual_hold_entities.discard(entity_id)
            
            # Cancel any pending task for this entity
            if entity_id in self._pending_tasks:
                self._pending_tasks[entity_id].cancel()
                del self._pending_tasks[entity_id]

            # Get current adaptive settings and apply immediately
            b_pct, k = self._compute_targets()
            mode = targets[entity_id]
            
            # Create and track the task
            task = asyncio.create_task(self._apply_light_settings(entity_id, mode, b_pct, k))
            self._pending_tasks[entity_id] = task
            
            # Clean up task when done
            def cleanup(_):
                if entity_id in self._pending_tasks:
                    del self._pending_tasks[entity_id]
            task.add_done_callback(cleanup)
            return

        # Handle manual adjustments (only for lights that are on)
        if new_state.state == "on" and old_state and old_state.state == "on":
            # Check if this was a manual change (not from our automation)
            last_automation = self._last_automation_change.get(entity_id, 0)
            state_changed = new_state.last_changed.timestamp() if new_state.last_changed else 0
            
            # If the change happened after our last automation change, it's likely manual
            if state_changed > last_automation + 1:  # 1 second grace period
                # Check if brightness or color actually changed
                old_attrs = old_state.attributes or {}
                new_attrs = new_state.attributes or {}
                
                brightness_changed = old_attrs.get("brightness") != new_attrs.get("brightness")
                color_temp_changed = old_attrs.get("color_temp") != new_attrs.get("color_temp")
                rgb_color_changed = old_attrs.get("rgb_color") != new_attrs.get("rgb_color")
                
                if brightness_changed or color_temp_changed or rgb_color_changed:
                    # This looks like a manual adjustment - add to manual hold
                    self._manual_hold_entities.add(entity_id)

    # --------------------------- helpers ----------------------------------
    def _discover_targets(self) -> Dict[str, str]:
        # Return mapping entity_id -> mode ("ct" or "rgb")
        out: Dict[str, str] = {}
        ent_reg = entity_registry.async_get(self.hass)
        area_reg = area_registry.async_get(self.hass)

        def allowed(ent_id: str) -> bool:
            if ent_id in self.settings.exclude_entities:
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
        now = dt_util.now().time()
        wind_down_target = parse_time_str(self.settings.wind_down_target)
        wake_up = parse_time_str(self.settings.wake_up)
        
        # Sleep window override
        if in_window(now, wind_down_target, wake_up):
            return (self.settings.sleep_b, self.settings.sleep_k)
        
        # Check if we're in a transition period
        is_transition, wind_down, progress = is_in_transition_period(now, wind_down_target, wake_up)

        if is_transition:
            if wind_down:
                # Gradually transition from 100% to Sleep Brightness
                b = int(round(lerp(100, self.settings.sleep_b, progress)))
            else:
                # Gradually brighten from Sleep Brightness to 100% over 1 hour after wake_up
                b = int(round(lerp(self.settings.sleep_b, 100, progress)))
        else:
            b = 100
        
        # Sun color temperature calculation
        sun = self.hass.states.get("sun.sun")
        elev = -6.0
        if sun:
            elev = float(sun.attributes.get("elevation", -6.0))

        tk = clamp((elev + 6.0) / (60.0 + 6.0), 0.0, 1.0)
        k = int(round(lerp(2200, 6500, tk)))

        return (b, k)
