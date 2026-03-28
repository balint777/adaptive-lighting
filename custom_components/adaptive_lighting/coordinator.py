from __future__ import annotations
import asyncio
import contextlib
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Dict, List, Set

from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import DEFAULT_NIGHT_START, DEFAULT_NIGHT_END
from .util import clamp, lerp, parse_time_str, in_window, cct_to_rgb, is_in_transition_period

SUPPORTED_COLOR_KEYS = {"supported_color_modes", "color_mode", "color_modes"}
RGB_LIKE_MODES = {"hs", "rgb", "rgbw", "rgbww", "xy"}
MANUAL_HOLD_SECONDS = 2 * 60 * 60
AUTOMATION_GRACE_SECONDS = 1
LIGHT_DOMAIN = "light"
TARGET_CACHE_TTL_SECONDS = 30
MAX_CONCURRENT_LIGHT_UPDATES = 6
TRACKING_STALE_SECONDS = 24 * 60 * 60
SERVICE_ERROR_LOG_INTERVAL_SECONDS = 5 * 60
CONFIG_WARNING_LOG_INTERVAL_SECONDS = 5 * 60
SERVICE_CALL_TIMEOUT_SECONDS = 15

_LOGGER = logging.getLogger(__name__)

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
        return 1 # seconds
    
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
        self._manual_hold_entities: Dict[str, float] = {}  # Entities with manual adjustments (entity_id -> timestamp)
        self._last_automation_change: Dict[str, float] = {}  # Track our own changes
        self._pending_tasks: Dict[str, asyncio.Task] = {}  # Track pending operations per entity
        self._cancelled_entities: Set[str] = set()  # Entities that should stop processing
        self._enabled = True
        self._target_cache: Dict[str, str] = {}
        self._target_cache_expires_at = 0.0
        self._apply_semaphore = asyncio.Semaphore(MAX_CONCURRENT_LIGHT_UPDATES)
        self._apply_all_lock = asyncio.Lock()
        self._last_service_error_log_at: Dict[str, float] = {}
        self._last_config_warning_log_at = 0.0

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def is_enabled(self) -> bool:
        return self._enabled

    def update_settings(self, new_settings: Settings) -> None:
        """Update settings without restarting the controller."""
        old_interval = self.settings.interval
        old_excludes = set(self.settings.exclude_entities)
        self.settings = new_settings
        if old_excludes != set(new_settings.exclude_entities):
            self._invalidate_targets_cache()
        
        # If interval changed, restart the timer
        if old_interval != new_settings.interval and self._unsub:
            self._unsub()
            interval = timedelta(seconds=self.settings.interval)
            self._unsub = async_track_time_interval(self.hass, self._apply_all, interval)

    def start(self):
        self.stop()
        self._invalidate_targets_cache()
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
        for task in self._pending_tasks.values():
            task.cancel()
        self._pending_tasks.clear()
        self._cancelled_entities.clear()
        self._invalidate_targets_cache()

    async def _apply_all(self, _now=None):
        if not self._enabled:
            return
        if self._apply_all_lock.locked():
            # Skip if previous cycle is still running.
            return

        async with self._apply_all_lock:
            try:
                await self._run_apply_all()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("Unexpected error in periodic adaptive update cycle")

    async def _run_apply_all(self) -> None:
        """Execute one periodic adaptive cycle."""
        # Determine targets
        targets = self._get_targets_cached()
        # Determine target CT/brightness from sun/time
        brightness, k = self._compute_targets()
        
        # Clear expired manual holds (older than 2 hours)
        self._clear_expired_holds()
        self._clear_stale_tracking()

        updates: list[asyncio.Task] = []
        for ent_id, mode in targets.items():
            if not self._is_entity_eligible_for_periodic_update(ent_id):
                continue

            task = self._track_entity_task(
                ent_id, self._apply_light_settings_limited(ent_id, mode, brightness, k)
            )
            updates.append(task)

        if updates:
            results = await asyncio.gather(*updates, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                    _LOGGER.debug("Periodic update task failed: %s", result, exc_info=result)

    def _is_entity_eligible_for_periodic_update(self, ent_id: str) -> bool:
        """Return whether an entity should receive periodic adaptive updates."""
        state = self.hass.states.get(ent_id)
        if not state or not self._is_state_on(state):
            return False

        # Self-heal stale cancellation flag if an "on" event was missed.
        if ent_id in self._cancelled_entities:
            self._cancelled_entities.discard(ent_id)

        if ent_id in self._manual_hold_entities:
            return False
        if ent_id in self._pending_tasks:
            return False
        return True

    async def _apply_light_settings_limited(self, ent_id: str, mode: str, brightness: int, k: int) -> None:
        """Limit concurrent light updates to avoid service-call bursts."""
        async with self._apply_semaphore:
            await self._apply_light_settings(ent_id, mode, brightness, k)

    async def _apply_light_settings(self, ent_id: str, mode: str, brightness: int, k: int) -> None:
        """Apply brightness and color settings to a specific light entity."""
        # Check if cancelled before starting
        if ent_id in self._cancelled_entities:
            return
        
        # Check light state before applying settings
        state = self.hass.states.get(ent_id)
        if not state or not self._is_state_on(state):
            return

        # Record timestamp before making changes
        self._last_automation_change[ent_id] = time.time()
            
        # Apply brightness first (blocking to ensure it completes before we can be cancelled)
        if not await self._safe_turn_on(
            ent_id,
            {
                "transition": self.settings.transition,
                "brightness_pct": brightness,
            },
        ):
            return
        
        # if supported_color_modes == ColorMode.WHITE:
        # return

        # Wait for transition to complete
        await asyncio.sleep(self.settings.transition)
        
        
        # Prepare color data based on mode
        if mode == "ct":
            color_data = {"color_temp_kelvin": k}
        elif mode == "rgb":
            r, g, b = cct_to_rgb(k)
            color_data = {"rgb_color": [r, g, b]}
        else:
            # Brightness-only light: skip color update.
            return
        
        # Check cancellation and light state before applying color
        if ent_id in self._cancelled_entities:
            return

        state = self.hass.states.get(ent_id)
        if not state or not self._is_state_on(state):
            return

        # Apply color/temperature (blocking to ensure it completes)
        await self._safe_turn_on(
            ent_id,
            {
                "transition": self.settings.transition,
                **color_data,
            },
        )
        
        # Record that we made this change
        self._last_automation_change[ent_id] = time.time()

    @callback
    def _handle_light_turn_on(self, event: Event) -> None:
        """Handle state change events for manual hold detection and turn-on control."""
        try:
            if not self._enabled:
                return

            event_data = event.data
            entity_id = event_data.get("entity_id")
            old_state = event_data.get("old_state")
            new_state = event_data.get("new_state")

            if not entity_id or not entity_id.startswith("light.") or not new_state:
                return

            new_state_value = getattr(new_state, "state", None)
            if not isinstance(new_state_value, str):
                return

            old_state_value = getattr(old_state, "state", None) if old_state is not None else None

            # Check if this light is a valid target
            targets = self._get_targets_cached()
            if entity_id not in targets:
                # Light capabilities can change at runtime; refresh once to avoid stale misses.
                self._invalidate_targets_cache()
                targets = self._get_targets_cached()
                if entity_id not in targets:
                    return

            # Handle turn-off events - cancel any pending operations
            if new_state_value == "off" and old_state_value == "on":
                self._handle_turn_off(entity_id)
                return

            # Handle turn-on events
            if new_state_value == "on" and old_state_value != "on":
                self._handle_turn_on(entity_id, targets[entity_id])
                return

            # Handle manual adjustments (only for lights that are on)
            if new_state_value == "on" and old_state_value == "on":
                self._handle_manual_adjustment(entity_id, old_state, new_state)
        except Exception:
            _LOGGER.debug("Ignoring malformed light state-change event", exc_info=True)

    # --------------------------- helpers ----------------------------------
    def _clear_expired_holds(self) -> None:
        """Remove stale manual holds to avoid permanent lockout."""
        current_time = time.monotonic()
        expired = [
            ent_id
            for ent_id, ts in self._manual_hold_entities.items()
            if current_time - ts > MANUAL_HOLD_SECONDS
        ]
        for ent_id in expired:
            self._manual_hold_entities.pop(ent_id, None)

    def _clear_stale_tracking(self) -> None:
        """Prune stale automation timestamps for entities not updated recently."""
        now = time.time()
        existing_lights = {state.entity_id for state in self.hass.states.async_all("light")}

        for ent_id in tuple(self._manual_hold_entities):
            if ent_id not in existing_lights:
                self._manual_hold_entities.pop(ent_id, None)

        stale = [
            ent_id
            for ent_id, ts in self._last_automation_change.items()
            if now - ts > TRACKING_STALE_SECONDS or ent_id not in existing_lights
        ]
        for ent_id in stale:
            self._last_automation_change.pop(ent_id, None)

        stale_service_logs = [
            ent_id
            for ent_id, ts in self._last_service_error_log_at.items()
            if now - ts > TRACKING_STALE_SECONDS or ent_id not in existing_lights
        ]
        for ent_id in stale_service_logs:
            self._last_service_error_log_at.pop(ent_id, None)

        self._cancelled_entities.intersection_update(existing_lights)

    def _get_targets_cached(self) -> Dict[str, str]:
        """Return cached light targets, refreshing periodically."""
        now = time.monotonic()
        if now >= self._target_cache_expires_at:
            self._target_cache = self._discover_targets()
            self._target_cache_expires_at = now + TARGET_CACHE_TTL_SECONDS
        return dict(self._target_cache)

    def _invalidate_targets_cache(self) -> None:
        """Invalidate target cache so next read performs discovery."""
        self._target_cache_expires_at = 0.0

    def _cancel_pending_task(self, entity_id: str) -> None:
        """Cancel and forget a pending task for an entity."""
        task = self._pending_tasks.pop(entity_id, None)
        if task is not None:
            task.cancel()

    def _track_entity_task(self, entity_id: str, coro) -> asyncio.Task:
        """Create and track an entity task with uniform cleanup/exception handling."""
        existing = self._pending_tasks.get(entity_id)
        if existing is not None and not existing.done():
            existing.cancel()

        task = self.hass.async_create_task(coro)
        self._pending_tasks[entity_id] = task

        def cleanup(done_task: asyncio.Task) -> None:
            # Only clear mapping when this exact task is still the active one.
            # A newer task may have replaced it for the same entity.
            if self._pending_tasks.get(entity_id) is done_task:
                self._pending_tasks.pop(entity_id, None)
            with contextlib.suppress(asyncio.CancelledError):
                exc = done_task.exception()
                if exc is not None:
                    _LOGGER.debug("Adaptive task failed for %s: %s", entity_id, exc)

        task.add_done_callback(cleanup)
        return task

    def _cancel_entity_processing(self, entity_id: str) -> None:
        """Cancel all pending processing for the entity."""
        self._cancelled_entities.add(entity_id)
        self._cancel_pending_task(entity_id)

    def _handle_turn_off(self, entity_id: str) -> None:
        """Handle entity turn-off transitions."""
        self._cancel_entity_processing(entity_id)
        self._manual_hold_entities.pop(entity_id, None)

    def _handle_turn_on(self, entity_id: str, mode: str) -> None:
        """Handle entity turn-on transitions."""
        self._cancelled_entities.discard(entity_id)
        self._manual_hold_entities.pop(entity_id, None)
        self._cancel_pending_task(entity_id)

        b_pct, k = self._compute_targets()
        self._track_entity_task(entity_id, self._apply_light_settings(entity_id, mode, b_pct, k))

    def _handle_manual_adjustment(self, entity_id: str, old_state, new_state) -> None:
        """Track manual user adjustments and hold adaptive updates temporarily."""
        # Ignore updates while we still have an in-flight automation task for this entity.
        if entity_id in self._pending_tasks:
            return

        last_automation = self._last_automation_change.get(entity_id, 0)
        # last_changed only updates when state changes (on/off). For brightness/color
        # adjustments we must use last_updated to detect attribute-only manual changes.
        last_updated = getattr(new_state, "last_updated", None)
        if last_updated is None or not hasattr(last_updated, "timestamp"):
            return
        state_updated = last_updated.timestamp()
        if state_updated <= last_automation + AUTOMATION_GRACE_SECONDS:
            return

        old_attrs = self._state_attributes(old_state)
        new_attrs = self._state_attributes(new_state)
        if (
            old_attrs.get("brightness") != new_attrs.get("brightness")
            or old_attrs.get("color_temp") != new_attrs.get("color_temp")
            or old_attrs.get("color_temp_kelvin") != new_attrs.get("color_temp_kelvin")
            or old_attrs.get("rgb_color") != new_attrs.get("rgb_color")
        ):
            self._manual_hold_entities[entity_id] = time.monotonic()

    @staticmethod
    def _is_state_on(state) -> bool:
        """Safely determine whether a Home Assistant state object is 'on'."""
        return getattr(state, "state", None) == "on"

    @staticmethod
    def _state_attributes(state) -> dict:
        """Safely read state attributes as a dict."""
        attrs = getattr(state, "attributes", None)
        return attrs if isinstance(attrs, dict) else {}

    def _safe_parse_time(self, value: str, fallback: str, field_name: str):
        """Parse a time string with fallback and throttled warning on invalid value."""
        try:
            return parse_time_str(value)
        except (TypeError, ValueError):
            now = time.time()
            if now - self._last_config_warning_log_at >= CONFIG_WARNING_LOG_INTERVAL_SECONDS:
                self._last_config_warning_log_at = now
                _LOGGER.warning(
                    "Adaptive Lighting received invalid %s value '%s'; falling back to '%s'",
                    field_name,
                    value,
                    fallback,
                )
            return parse_time_str(fallback)

    async def _safe_turn_on(self, ent_id: str, service_data: dict) -> bool:
        """Call light.turn_on safely and report failures without breaking loop."""
        try:
            await asyncio.wait_for(
                self.hass.services.async_call(
                    LIGHT_DOMAIN,
                    "turn_on",
                    {
                        "entity_id": ent_id,
                        **service_data,
                    },
                    blocking=True,
                ),
                timeout=SERVICE_CALL_TIMEOUT_SECONDS,
            )
            self._last_service_error_log_at.pop(ent_id, None)
            return True
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            now = time.time()
            last_logged = self._last_service_error_log_at.get(ent_id, 0.0)
            if now - last_logged >= SERVICE_ERROR_LOG_INTERVAL_SECONDS:
                self._last_service_error_log_at[ent_id] = now
                _LOGGER.warning(
                    "Adaptive Lighting timed out while updating %s (throttled log, retrying automatically)",
                    ent_id,
                )
            _LOGGER.debug("Service call timed out for %s with payload %s", ent_id, service_data)
            return False
        except Exception as err:
            now = time.time()
            last_logged = self._last_service_error_log_at.get(ent_id, 0.0)
            if now - last_logged >= SERVICE_ERROR_LOG_INTERVAL_SECONDS:
                self._last_service_error_log_at[ent_id] = now
                _LOGGER.warning(
                    "Adaptive Lighting failed to update %s (throttled log, retrying automatically): %s",
                    ent_id,
                    err,
                )
            _LOGGER.debug("Service call failed for %s with payload %s", ent_id, service_data, exc_info=True)
            return False

    @staticmethod
    def _normalize_modes(color_modes: object) -> Set[str]:
        """Normalize color_modes from integrations to a set of mode strings."""
        if isinstance(color_modes, set):
            return color_modes
        if isinstance(color_modes, (list, tuple)):
            try:
                return set(color_modes)
            except TypeError:
                return set()
        if isinstance(color_modes, str):
            return {color_modes}
        return set()

    @staticmethod
    def _classify_light_mode(attrs: dict, modes: Set[str]) -> str | None:
        """Return light mode to control or None if unsupported."""
        has_brightness = (
            "brightness" in attrs
            or "brightness" in modes
            or any(m in modes for m in ("color_temp", *RGB_LIKE_MODES, "white"))
        )
        if not has_brightness:
            return None

        supports_ct = (
            "color_temp" in modes
            or "color_temp" in attrs
            or "color_temp_kelvin" in attrs
            or "min_color_temp_kelvin" in attrs
            or "max_color_temp_kelvin" in attrs
        )
        if supports_ct:
            return "ct"

        if any(m in modes for m in RGB_LIKE_MODES):
            return "rgb"

        return "brightness"

    def _discover_targets(self) -> Dict[str, str]:
        # Return mapping entity_id -> mode ("ct" or "rgb")
        out: Dict[str, str] = {}
        excluded = {
            ent_id for ent_id in self.settings.exclude_entities if isinstance(ent_id, str)
        }

        def allowed(ent_id: str) -> bool:
            if ent_id in excluded:
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
            modes = self._normalize_modes(color_modes)

            mode = self._classify_light_mode(attrs, modes)
            if mode is not None:
                out[ent_id] = mode
        return out

    def _compute_targets(self):
        now = dt_util.now().time()
        wind_down_target = self._safe_parse_time(
            self.settings.wind_down_target,
            DEFAULT_NIGHT_START,
            "wind_down_target",
        )
        wake_up = self._safe_parse_time(
            self.settings.wake_up,
            DEFAULT_NIGHT_END,
            "wake_up",
        )
        
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
            try:
                elev = float(sun.attributes.get("elevation", -6.0))
            except (TypeError, ValueError):
                elev = -6.0
            if not math.isfinite(elev):
                elev = -6.0

        tk = clamp((elev + 6.0) / (60.0 + 6.0), 0.0, 1.0)
        k = int(round(clamp(lerp(2200, 6500, tk), 2200, 6500)))

        b = int(round(clamp(b, self.settings.sleep_b, 100)))

        return (b, k)
