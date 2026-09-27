"""Power-neutral protocol commands for supported light integrations."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

MATTER_DOMAIN = "matter"
ZHA_DOMAIN = "zha"
ZHA_CLUSTER_COMMAND_SERVICE = "issue_zigbee_cluster_command"

LEVEL_CONTROL_CLUSTER_ID = 0x0008
COLOR_CONTROL_CLUSTER_ID = 0x0300
MOVE_TO_LEVEL_COMMAND_ID = 0x00
MOVE_TO_COLOR_TEMPERATURE_COMMAND_ID = 0x0A

EXECUTE_IF_OFF_MASK = 0x01
DO_NOT_EXECUTE_IF_OFF = 0x00
MAX_LEVEL = 254
MAX_TRANSITION_TENTHS = 65534
MAX_COLOR_TEMPERATURE_MIREDS = 65279

_LOGGER = logging.getLogger(__name__)


class NativeLightTarget(Protocol):
    """A light endpoint that supports power-neutral protocol commands."""

    integration: str

    async def async_set_brightness(
        self, brightness_pct: int, transition_seconds: float
    ) -> None:
        """Change brightness without changing the On/Off state."""

    async def async_set_color_temperature(
        self, kelvin: int, transition_seconds: float
    ) -> None:
        """Change color temperature without changing the On/Off state."""


class NativeResolutionStatus(Enum):
    """Outcome of resolving a light's power-neutral protocol target."""

    NOT_NATIVE = "not_native"
    TARGET = "target"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class NativeResolution:
    """Typed native resolution result used to keep fallback behavior safe."""

    status: NativeResolutionStatus
    target: NativeLightTarget | None = None
    integration: str | None = None

    @property
    def is_native(self) -> bool:
        """Return whether the entity belongs to a native-capable integration."""
        return self.status is not NativeResolutionStatus.NOT_NATIVE


def _transition_tenths(transition_seconds: float) -> int:
    """Convert seconds to a bounded protocol transition value."""
    return max(
        0,
        min(MAX_TRANSITION_TENTHS, round(float(transition_seconds) * 10)),
    )


def _color_temperature_mireds(kelvin: int) -> int:
    """Convert Kelvin to a bounded Matter/Zigbee mired value."""
    return min(
        MAX_COLOR_TEMPERATURE_MIREDS,
        max(1, round(1_000_000 / max(1, int(kelvin)))),
    )


def _level_from_brightness_pct(
    brightness_pct: int, minimum: int = 1, maximum: int = MAX_LEVEL
) -> int:
    """Map a Home Assistant brightness percentage to a protocol level."""
    minimum = max(1, min(MAX_LEVEL, int(minimum)))
    maximum = max(minimum, min(MAX_LEVEL, int(maximum)))
    ha_brightness = max(1, min(255, round(float(brightness_pct) * 255 / 100)))
    return round(minimum + (ha_brightness / 255) * (maximum - minimum))


@dataclass(frozen=True)
class MatterLightTarget:
    """A Matter light endpoint accessed through HA's Matter client."""

    matter_client: Any
    node_id: int
    endpoint_id: int
    clusters: Any
    minimum_level: int = 1
    maximum_level: int = MAX_LEVEL
    integration: str = MATTER_DOMAIN

    async def async_set_brightness(
        self, brightness_pct: int, transition_seconds: float
    ) -> None:
        """Send MoveToLevel, explicitly preserving the power state."""
        command = self.clusters.LevelControl.Commands.MoveToLevel(
            level=_level_from_brightness_pct(
                brightness_pct, self.minimum_level, self.maximum_level
            ),
            transitionTime=_transition_tenths(transition_seconds),
            optionsMask=EXECUTE_IF_OFF_MASK,
            optionsOverride=DO_NOT_EXECUTE_IF_OFF,
        )
        await self.matter_client.send_device_command(
            node_id=self.node_id,
            endpoint_id=self.endpoint_id,
            command=command,
        )

    async def async_set_color_temperature(
        self, kelvin: int, transition_seconds: float
    ) -> None:
        """Send MoveToColorTemperature, explicitly preserving power state."""
        command = self.clusters.ColorControl.Commands.MoveToColorTemperature(
            colorTemperatureMireds=_color_temperature_mireds(kelvin),
            transitionTime=_transition_tenths(transition_seconds),
            optionsMask=EXECUTE_IF_OFF_MASK,
            optionsOverride=DO_NOT_EXECUTE_IF_OFF,
        )
        await self.matter_client.send_device_command(
            node_id=self.node_id,
            endpoint_id=self.endpoint_id,
            command=command,
        )


@dataclass(frozen=True)
class ZhaLightTarget:
    """A Zigbee endpoint accessed through ZHA's cluster-command service."""

    hass: HomeAssistant
    ieee: str
    endpoint_id: int
    integration: str = ZHA_DOMAIN

    async def async_set_brightness(
        self, brightness_pct: int, transition_seconds: float
    ) -> None:
        """Send ZCL MoveToLevel, explicitly preserving the power state."""
        await self._async_cluster_command(
            cluster_id=LEVEL_CONTROL_CLUSTER_ID,
            command=MOVE_TO_LEVEL_COMMAND_ID,
            params={
                "level": _level_from_brightness_pct(brightness_pct),
                "transition_time": _transition_tenths(transition_seconds),
                "options_mask": EXECUTE_IF_OFF_MASK,
                "options_override": DO_NOT_EXECUTE_IF_OFF,
            },
        )

    async def async_set_color_temperature(
        self, kelvin: int, transition_seconds: float
    ) -> None:
        """Send ZCL MoveToColorTemp, explicitly preserving the power state."""
        await self._async_cluster_command(
            cluster_id=COLOR_CONTROL_CLUSTER_ID,
            command=MOVE_TO_COLOR_TEMPERATURE_COMMAND_ID,
            params={
                "color_temp_mireds": _color_temperature_mireds(kelvin),
                "transition_time": _transition_tenths(transition_seconds),
                "options_mask": EXECUTE_IF_OFF_MASK,
                "options_override": DO_NOT_EXECUTE_IF_OFF,
            },
        )

    async def _async_cluster_command(
        self, cluster_id: int, command: int, params: dict[str, int]
    ) -> None:
        """Issue a named-parameter ZCL server command through ZHA."""
        await self.hass.services.async_call(
            ZHA_DOMAIN,
            ZHA_CLUSTER_COMMAND_SERVICE,
            {
                "ieee": self.ieee,
                "endpoint_id": self.endpoint_id,
                "cluster_id": cluster_id,
                "cluster_type": "in",
                "command": command,
                "command_type": "server",
                "params": params,
            },
            blocking=True,
        )


class NativeLightController:
    """Detect and resolve integrations with power-neutral command support."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._announced: set[tuple[str, str]] = set()
        self._resolution_warnings: set[tuple[str, str]] = set()
        self._known_native_integrations: dict[str, str] = {}

    def resolve(
        self, entity_id: str, *, mode: str
    ) -> NativeResolution:
        """Resolve a target and distinguish non-native from unsafe fallback cases."""
        entry = er.async_get(self.hass).async_get(entity_id)
        if entry is None:
            integration = self._known_native_integrations.get(entity_id)
            if integration is not None:
                self._warn_unavailable(
                    entity_id,
                    integration,
                    "the entity registry entry is temporarily unavailable",
                )
                return NativeResolution(
                    NativeResolutionStatus.UNAVAILABLE,
                    integration=integration,
                )
            return NativeResolution(NativeResolutionStatus.NOT_NATIVE)

        integration = getattr(entry, "platform", None)
        if integration not in {MATTER_DOMAIN, ZHA_DOMAIN}:
            self._known_native_integrations.pop(entity_id, None)
            return NativeResolution(NativeResolutionStatus.NOT_NATIVE)
        self._known_native_integrations[entity_id] = integration

        # RGB-only Matter/ZHA entities cannot safely use light.turn_on as a
        # fallback because that service may change their On/Off state. Native
        # color commands can be added later, but until then fail closed.
        if mode not in {"ct", "brightness"}:
            self._warn_unavailable(
                entity_id,
                integration,
                "the entity requires an unsupported native color command",
            )
            return NativeResolution(
                NativeResolutionStatus.UNAVAILABLE,
                integration=integration,
            )

        try:
            if integration == MATTER_DOMAIN:
                target = self._resolve_matter(
                    entry,
                    require_color_temperature=mode == "ct",
                )
            else:
                target = self._resolve_zha(entry)
        except Exception as err:
            self._warn_unavailable(entity_id, integration, str(err))
            _LOGGER.debug(
                "Native %s target resolution failed for %s",
                integration,
                entity_id,
                exc_info=True,
            )
            return NativeResolution(
                NativeResolutionStatus.UNAVAILABLE,
                integration=integration,
            )

        if target is None:
            self._warn_unavailable(
                entity_id,
                integration,
                "the endpoint or required cluster is not currently available",
            )
            return NativeResolution(
                NativeResolutionStatus.UNAVAILABLE,
                integration=integration,
            )

        announce_key = (entity_id, integration)
        if announce_key not in self._announced:
            self._announced.add(announce_key)
            _LOGGER.info(
                "Using power-neutral native %s commands for %s",
                integration,
                entity_id,
            )
        return NativeResolution(
            NativeResolutionStatus.TARGET,
            target=target,
            integration=integration,
        )

    def _warn_unavailable(
        self, entity_id: str, integration: str, reason: str
    ) -> None:
        """Log a native-resolution failure once without suggesting unsafe fallback."""
        warning_key = (entity_id, integration)
        if warning_key in self._resolution_warnings:
            return
        self._resolution_warnings.add(warning_key)
        _LOGGER.warning(
            "Could not initialize power-neutral native %s control for %s; "
            "skipping adaptive updates until it becomes available: %s",
            integration,
            entity_id,
            reason,
        )

    def _resolve_matter(
        self, entry: Any, require_color_temperature: bool
    ) -> MatterLightTarget | None:
        """Resolve the Matter client, node, and exact light endpoint."""
        if not entry.device_id:
            return None

        # Lazy imports keep Matter optional for Home Assistant installations
        # which do not load the Matter integration.
        from chip.clusters import Objects as clusters
        from homeassistant.components.matter.helpers import (
            get_device_id,
            get_matter,
            get_node_from_device_entry,
        )

        device = dr.async_get(self.hass).async_get(entry.device_id)
        if device is None:
            return None

        matter = get_matter(self.hass)
        matter_client = matter.matter_client
        node = get_node_from_device_entry(self.hass, device)
        server_info = matter_client.server_info
        if node is None or server_info is None:
            return None

        unique_id = str(entry.unique_id)
        for endpoint in node.endpoints.values():
            node_device_id = get_device_id(server_info, endpoint)
            expected_prefix = f"{node_device_id}-{endpoint.endpoint_id}-"
            if not unique_id.startswith(expected_prefix):
                continue

            level_control = endpoint.get_cluster(clusters.LevelControl)
            color_control = endpoint.get_cluster(clusters.ColorControl)
            if level_control is None:
                return None
            if require_color_temperature and color_control is None:
                return None

            minimum_level = getattr(level_control, "minLevel", None) or 1
            maximum_level = getattr(level_control, "maxLevel", None) or MAX_LEVEL
            if not isinstance(minimum_level, int):
                minimum_level = 1
            if not isinstance(maximum_level, int):
                maximum_level = MAX_LEVEL

            return MatterLightTarget(
                matter_client=matter_client,
                node_id=node.node_id,
                endpoint_id=endpoint.endpoint_id,
                clusters=clusters,
                minimum_level=minimum_level,
                maximum_level=maximum_level,
            )

        return None

    def _resolve_zha(self, entry: Any) -> ZhaLightTarget | None:
        """Resolve a ZHA device IEEE address and entity endpoint."""
        if not entry.device_id or not self.hass.services.has_service(
            ZHA_DOMAIN, ZHA_CLUSTER_COMMAND_SERVICE
        ):
            return None

        device = dr.async_get(self.hass).async_get(entry.device_id)
        if device is None:
            return None

        ieee = next(
            (
                str(identifier)
                for domain, identifier in device.identifiers
                if domain == ZHA_DOMAIN
            ),
            None,
        )
        if ieee is None:
            return None

        match = re.match(
            rf"^{re.escape(ieee)}[-:](\d+)(?:[-:]|$)",
            str(entry.unique_id),
            re.IGNORECASE,
        )
        if match is None:
            return None

        return ZhaLightTarget(
            hass=self.hass,
            ieee=ieee,
            endpoint_id=int(match.group(1)),
        )
