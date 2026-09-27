"""Focused regression tests for multi-fabric and power-intent races.

These tests use small Home Assistant API stubs so they can run in the source
checkout without installing Home Assistant itself.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import time
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]


class FakeState:
    """Minimal Home Assistant state."""

    def __init__(self, entity_id: str, state: str, attributes: dict | None = None):
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes or {}
        self.last_updated = datetime.now(timezone.utc)


class FakeStates:
    def __init__(self, *states: FakeState):
        self._states = {state.entity_id: state for state in states}

    def get(self, entity_id: str):
        return self._states.get(entity_id)

    def async_all(self, domain: str | None = None):
        if domain is None:
            return list(self._states.values())
        prefix = f"{domain}."
        return [
            state for entity_id, state in self._states.items()
            if entity_id.startswith(prefix)
        ]


class FakeRegistry:
    def __init__(self, entries: dict | None = None):
        self.entries = entries or {}

    def async_get(self, entity_id: str):
        return self.entries.get(entity_id)


class FakeServices:
    def has_service(self, _domain: str, _service: str) -> bool:
        return True

    async def async_call(self, *_args, **_kwargs) -> None:
        return None


class FakeBus:
    def async_listen(self, *_args, **_kwargs):
        return lambda: None


class FakeHass:
    def __init__(self, *states: FakeState, registry: FakeRegistry | None = None):
        self.states = FakeStates(*states)
        self.entity_registry = registry or FakeRegistry()
        self.device_registry = FakeRegistry()
        self.services = FakeServices()
        self.bus = FakeBus()
        self.data = {}
        self.is_stopping = False

    def async_create_task(self, coroutine):
        return asyncio.create_task(coroutine)


class FakeStore:
    """In-memory stand-in for homeassistant.helpers.storage.Store."""

    saved: dict[str, dict] = {}

    def __init__(self, _hass, _version: int, key: str, **_kwargs):
        self.key = key

    @classmethod
    def __class_getitem__(cls, _item):
        return cls

    async def async_load(self):
        return self.saved.get(self.key)

    def async_delay_save(self, data_func, _delay: float = 0) -> None:
        self.saved[self.key] = data_func()


def _install_homeassistant_stubs() -> None:
    """Install only the HA surfaces imported by coordinator/native."""
    homeassistant = types.ModuleType("homeassistant")
    homeassistant.__path__ = []
    core = types.ModuleType("homeassistant.core")
    const = types.ModuleType("homeassistant.const")
    helpers = types.ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    components = types.ModuleType("homeassistant.components")
    components.__path__ = []
    switch_component = types.ModuleType("homeassistant.components.switch")
    config_entries = types.ModuleType("homeassistant.config_entries")
    event = types.ModuleType("homeassistant.helpers.event")
    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    restore_state = types.ModuleType("homeassistant.helpers.restore_state")
    storage = types.ModuleType("homeassistant.helpers.storage")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    device_registry = types.ModuleType("homeassistant.helpers.device_registry")
    util = types.ModuleType("homeassistant.util")
    util.__path__ = []
    dt = types.ModuleType("homeassistant.util.dt")

    class Context:
        def __init__(self, id: str | None = None):
            self.id = id or uuid4().hex

    class Event:
        def __init__(self, data: dict, context: Context | None = None):
            self.data = data
            self.context = context or Context()

    class SwitchEntity:
        async def async_added_to_hass(self) -> None:
            return None

        def async_write_ha_state(self) -> None:
            return None

    class RestoreEntity:
        async def async_added_to_hass(self) -> None:
            await super().async_added_to_hass()

        async def async_get_last_state(self):
            return getattr(self, "_restored_state", None)

    core.Context = Context
    core.Event = Event
    core.HomeAssistant = object
    core.callback = lambda function: function
    const.EVENT_CALL_SERVICE = "call_service"
    const.EVENT_STATE_CHANGED = "state_changed"
    const.STATE_OFF = "off"
    const.STATE_ON = "on"
    switch_component.SwitchEntity = SwitchEntity
    config_entries.ConfigEntry = object
    event.async_track_time_interval = lambda *_args, **_kwargs: lambda: None
    entity_platform.AddEntitiesCallback = object
    restore_state.RestoreEntity = RestoreEntity
    storage.Store = FakeStore
    entity_registry.async_get = lambda hass: hass.entity_registry
    device_registry.async_get = lambda hass: hass.device_registry
    dt.now = lambda: datetime.now(timezone.utc)
    util.dt = dt
    helpers.entity_registry = entity_registry
    helpers.device_registry = device_registry

    modules = {
        "homeassistant": homeassistant,
        "homeassistant.core": core,
        "homeassistant.const": const,
        "homeassistant.components": components,
        "homeassistant.components.switch": switch_component,
        "homeassistant.config_entries": config_entries,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.event": event,
        "homeassistant.helpers.entity_platform": entity_platform,
        "homeassistant.helpers.restore_state": restore_state,
        "homeassistant.helpers.storage": storage,
        "homeassistant.helpers.entity_registry": entity_registry,
        "homeassistant.helpers.device_registry": device_registry,
        "homeassistant.util": util,
        "homeassistant.util.dt": dt,
    }
    sys.modules.update(modules)

    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(ROOT / "custom_components")]
    adaptive_lighting = types.ModuleType("custom_components.adaptive_lighting")
    adaptive_lighting.__path__ = [
        str(ROOT / "custom_components" / "adaptive_lighting")
    ]
    sys.modules["custom_components"] = custom_components
    sys.modules["custom_components.adaptive_lighting"] = adaptive_lighting


_install_homeassistant_stubs()
coordinator = importlib.import_module(
    "custom_components.adaptive_lighting.coordinator"
)
native = importlib.import_module("custom_components.adaptive_lighting.native")
switch = importlib.import_module("custom_components.adaptive_lighting.switch")
Event = sys.modules["homeassistant.core"].Event


class ReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        FakeStore.saved.clear()

    @staticmethod
    def _light(
        entity_id: str = "light.bulb",
        *,
        state: str = "on",
        brightness: int = 128,
        kelvin: int = 3000,
        extra: dict | None = None,
    ) -> FakeState:
        attributes = {
            "brightness": brightness,
            "color_temp_kelvin": kelvin,
            "supported_color_modes": {"color_temp"},
        }
        attributes.update(extra or {})
        return FakeState(entity_id, state, attributes)

    async def test_native_unavailable_never_uses_power_changing_fallback(self):
        light = self._light()
        controller = coordinator.AdaptiveController(FakeHass(light), coordinator.Settings())
        controller._native_lights.resolve = Mock(
            return_value=native.NativeResolution(
                native.NativeResolutionStatus.UNAVAILABLE,
                integration="matter",
            )
        )
        controller._safe_turn_on = AsyncMock(return_value=True)

        await controller._apply_light_settings("light.bulb", "ct", 25, 2700)

        controller._safe_turn_on.assert_not_awaited()

    async def test_non_native_light_retains_generic_fallback(self):
        light = self._light()
        controller = coordinator.AdaptiveController(FakeHass(light), coordinator.Settings())
        controller._native_lights.resolve = Mock(
            return_value=native.NativeResolution(
                native.NativeResolutionStatus.NOT_NATIVE
            )
        )
        controller._safe_turn_on = AsyncMock(return_value=True)

        await controller._apply_light_settings(
            "light.bulb", "brightness", 25, 2700
        )

        controller._safe_turn_on.assert_awaited_once()

    async def test_group_entities_are_not_write_targets(self):
        member = self._light("light.member")
        attribute_group = self._light(
            "light.attribute_group",
            extra={"entity_id": ["light.member"]},
        )
        registry_group = self._light("light.registry_group")
        registry = FakeRegistry(
            {
                "light.registry_group": types.SimpleNamespace(platform="group"),
            }
        )
        controller = coordinator.AdaptiveController(
            FakeHass(member, attribute_group, registry_group, registry=registry),
            coordinator.Settings(),
        )

        self.assertEqual(controller._discover_targets(), {"light.member": "ct"})

    async def test_availability_recovery_does_not_release_manual_hold(self):
        light = self._light()
        controller = coordinator.AdaptiveController(FakeHass(light), coordinator.Settings())
        controller._target_cache = {"light.bulb": "ct"}
        controller._target_cache_expires_at = time.monotonic() + 60
        controller._manual_hold_entities["light.bulb"] = time.time() + 600
        unavailable = self._light(state="unavailable")
        handle_turn_on = Mock()

        with patch.object(controller, "_handle_turn_on", handle_turn_on):
            controller._handle_light_turn_on(
                Event(
                    {
                        "entity_id": "light.bulb",
                        "old_state": unavailable,
                        "new_state": light,
                    }
                )
            )

        handle_turn_on.assert_not_called()
        self.assertIn("light.bulb", controller._manual_hold_entities)

    async def test_real_off_on_transition_still_releases_hold(self):
        light = self._light()
        controller = coordinator.AdaptiveController(FakeHass(light), coordinator.Settings())
        controller._target_cache = {"light.bulb": "ct"}
        controller._target_cache_expires_at = time.monotonic() + 60
        off = self._light(state="off")
        handle_turn_on = Mock()

        with patch.object(controller, "_handle_turn_on", handle_turn_on):
            controller._handle_light_turn_on(
                Event(
                    {
                        "entity_id": "light.bulb",
                        "old_state": off,
                        "new_state": light,
                    }
                )
            )

        handle_turn_on.assert_called_once_with("light.bulb", "ct")

    async def test_guarded_native_turn_on_bypasses_confirmation_delay(self):
        light = self._light()
        controller = coordinator.AdaptiveController(FakeHass(light), coordinator.Settings())
        controller._last_turn_off_request["light.bulb"] = time.monotonic()
        controller._cancelled_entities.add("light.bulb")
        target = Mock(integration="matter")
        controller._native_lights.resolve = Mock(
            return_value=native.NativeResolution(
                native.NativeResolutionStatus.TARGET,
                target=target,
                integration="matter",
            )
        )
        controller._compute_targets = Mock(return_value=(1, 2200))
        controller._apply_native_light_settings = AsyncMock()

        controller._handle_turn_on("light.bulb", "ct")
        await asyncio.sleep(0)

        controller._apply_native_light_settings.assert_awaited_once_with(
            "light.bulb",
            "ct",
            1,
            2200,
            1,
            target,
        )
        self.assertNotIn("light.bulb", controller._cancelled_entities)

    async def test_guarded_generic_turn_on_keeps_confirmation_delay(self):
        light = self._light()
        controller = coordinator.AdaptiveController(FakeHass(light), coordinator.Settings())
        controller._last_turn_off_request["light.bulb"] = time.monotonic()
        controller._native_lights.resolve = Mock(
            return_value=native.NativeResolution(
                native.NativeResolutionStatus.NOT_NATIVE
            )
        )
        controller._confirm_guarded_turn_on = AsyncMock()

        controller._handle_turn_on("light.bulb", "ct")
        await asyncio.sleep(0)

        controller._confirm_guarded_turn_on.assert_awaited_once_with(
            "light.bulb", "ct"
        )

    async def test_stable_foreign_fabric_write_creates_hold(self):
        light = self._light(brightness=3, kelvin=2200)
        hass = FakeHass(light)
        controller = coordinator.AdaptiveController(hass, coordinator.Settings())
        controller._begin_native_expectation("light.bulb", "ct", 1, 2200, 0)
        expected = controller._native_expected_states["light.bulb"]
        expected.settle_after = time.monotonic() - 1

        old = self._light(brightness=3, kelvin=2200)
        foreign = self._light(brightness=255, kelvin=6500)
        hass.states._states["light.bulb"] = foreign
        controller._handle_manual_adjustment("light.bulb", old, foreign)
        controller._cancel_native_reconciliation("light.bulb")
        expected.last_report_at = time.monotonic() - coordinator.NATIVE_RECONCILE_SECONDS

        await controller._reconcile_native_feedback(
            "light.bulb", expected.generation
        )

        self.assertIn("light.bulb", controller._manual_hold_entities)

    async def test_matching_delayed_native_report_does_not_create_hold(self):
        light = self._light(brightness=3, kelvin=2200)
        controller = coordinator.AdaptiveController(FakeHass(light), coordinator.Settings())
        controller._begin_native_expectation("light.bulb", "ct", 1, 2200, 0)
        old = self._light(brightness=200, kelvin=5000)

        controller._handle_manual_adjustment("light.bulb", old, light)

        self.assertNotIn("light.bulb", controller._manual_hold_entities)
        self.assertFalse(
            controller._native_expected_states["light.bulb"].divergence_seen
        )

    async def test_old_report_cannot_create_hold_before_generation_is_confirmed(self):
        old_value = self._light(brightness=255, kelvin=6500)
        hass = FakeHass(old_value)
        controller = coordinator.AdaptiveController(hass, coordinator.Settings())
        controller._begin_native_expectation("light.bulb", "ct", 1, 2200, 0)
        expected = controller._native_expected_states["light.bulb"]
        self.assertFalse(expected.confirmed)

        intermediate = self._light(brightness=128, kelvin=4000)
        hass.states._states["light.bulb"] = intermediate
        controller._handle_manual_adjustment(
            "light.bulb", old_value, intermediate
        )

        self.assertFalse(expected.divergence_seen)
        self.assertNotIn("light.bulb", controller._manual_hold_entities)
        self.assertNotIn("light.bulb", controller._native_reconcile_tasks)

    async def test_manual_holds_survive_restart_with_expiry(self):
        light = self._light()
        registry = FakeRegistry(
            {"light.bulb": types.SimpleNamespace(platform="matter")}
        )
        first = coordinator.AdaptiveController(
            FakeHass(light, registry=registry), coordinator.Settings(), "entry"
        )
        first._set_manual_hold("light.bulb")

        second = coordinator.AdaptiveController(
            FakeHass(light, registry=registry), coordinator.Settings(), "entry"
        )
        await second._async_restore_manual_holds()

        self.assertGreater(
            second._manual_hold_entities["light.bulb"], time.time()
        )

    async def test_switch_restores_disabled_state(self):
        controller = Mock()
        controller.is_enabled.return_value = True
        entity = switch.AdaptiveSwitch(controller, "entry")
        entity._restored_state = types.SimpleNamespace(state="off")

        await entity.async_added_to_hass()

        controller.set_enabled.assert_called_once_with(False)

    async def test_native_resolution_distinguishes_unavailable_from_non_native(self):
        native_entry = types.SimpleNamespace(platform="matter", device_id="device")
        other_entry = types.SimpleNamespace(platform="hue", device_id="device")
        registry = FakeRegistry(
            {"light.native": native_entry, "light.other": other_entry}
        )
        controller = native.NativeLightController(FakeHass(registry=registry))
        controller._resolve_matter = Mock(return_value=None)

        unavailable = controller.resolve("light.native", mode="ct")
        not_native = controller.resolve("light.other", mode="ct")

        self.assertEqual(
            unavailable.status, native.NativeResolutionStatus.UNAVAILABLE
        )
        self.assertEqual(
            not_native.status, native.NativeResolutionStatus.NOT_NATIVE
        )


if __name__ == "__main__":
    unittest.main()
