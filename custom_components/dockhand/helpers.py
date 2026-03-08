"""helpers.py — shared URL builders and DeviceInfo factories.

Kept in a dedicated module so that __init__.py, sensor.py, binary_sensor.py,
switch.py, and button.py can all import from here without any circular
dependencies.  Platform modules (sensor.py etc.) are loaded lazily by HA and
must never be imported by __init__.py or by each other.
"""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


# --------------------------------------------------------------------------- #
# Section URL helpers
# Dockhand uses flat paths — no hash routing, no per-object deep links.
# All links land on the relevant section list; the user selects env/object there.
# Pattern: {base_url}/{section}
# --------------------------------------------------------------------------- #

def _section_url(base_url: str, section: str) -> str | None:
    """Return a Dockhand section URL, or None if base_url is not configured."""
    return f"{base_url.rstrip('/')}/{section}" if base_url else None


def _container_url(base_url: str) -> str | None:
    return _section_url(base_url, "containers")


def _stack_url(base_url: str) -> str | None:
    return _section_url(base_url, "stacks")


def _network_url(base_url: str) -> str | None:
    return _section_url(base_url, "networks")


def _volume_url(base_url: str) -> str | None:
    return _section_url(base_url, "volumes")


def _image_url(base_url: str) -> str | None:
    return _section_url(base_url, "images")


def _env_url(base_url: str) -> str | None:
    return _section_url(base_url, "environments")


def _schedules_url(base_url: str) -> str | None:
    return _section_url(base_url, "settings/schedules")


# --------------------------------------------------------------------------- #
# Device info helpers
# model field shows as the "Type" badge in the HA device list.
# --------------------------------------------------------------------------- #

def _env_device(env_id: int, env_name: str, base_url: str,
                stats: dict | None = None) -> DeviceInfo:
    info: dict[str, Any] = {
        "identifiers": {(DOMAIN, f"env_{env_id}")},
        "name": env_name,
        "manufacturer": "Dockhand",
        "model": "Environment",
        "configuration_url": _env_url(base_url),
        "entry_type": DeviceEntryType.SERVICE,
    }
    if stats:
        conn = stats.get("connectionType")
        if conn:
            info["hw_version"] = conn
    return DeviceInfo(**info)


def _container_group_device(env_id: int, env_name: str, base_url: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"env_{env_id}_Containers")},
        name=f"{env_name} – Containers",
        manufacturer="Dockhand",
        model="Environment",
        configuration_url=_container_url(base_url),
        via_device=(DOMAIN, f"env_{env_id}"),
        entry_type=DeviceEntryType.SERVICE,
    )


def _stack_group_device(env_id: int, env_name: str, base_url: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"env_{env_id}_Stacks")},
        name=f"{env_name} – Stacks",
        manufacturer="Dockhand",
        model="Environment",
        configuration_url=_stack_url(base_url),
        via_device=(DOMAIN, f"env_{env_id}"),
        entry_type=DeviceEntryType.SERVICE,
    )


def _network_group_device(env_id: int, env_name: str, base_url: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"env_{env_id}_Networks")},
        name=f"{env_name} – Networks",
        manufacturer="Dockhand",
        model="Environment",
        configuration_url=_network_url(base_url),
        via_device=(DOMAIN, f"env_{env_id}"),
        entry_type=DeviceEntryType.SERVICE,
    )


def _volume_group_device(env_id: int, env_name: str, base_url: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"env_{env_id}_Volumes")},
        name=f"{env_name} – Volumes",
        manufacturer="Dockhand",
        model="Environment",
        configuration_url=_volume_url(base_url),
        via_device=(DOMAIN, f"env_{env_id}"),
        entry_type=DeviceEntryType.SERVICE,
    )


def _container_device(container_id: str, container_name: str,
                      env_id: int, env_name: str, base_url: str,
                      stack_name: str | None = None) -> DeviceInfo:
    """Device info for a container.

    If stack_name is provided the container is compose-managed and is parented
    to the stack device.  Freestanding containers (no compose project label)
    are parented to the env Containers group device instead.
    """
    if stack_name:
        parent: tuple = (DOMAIN, f"stack_{env_id}_{stack_name}")
    else:
        parent = (DOMAIN, f"env_{env_id}_Containers")
    return DeviceInfo(
        identifiers={(DOMAIN, f"container_{container_id}")},
        name=f"{env_name} – {container_name}",
        manufacturer="Dockhand",
        model="Container",
        configuration_url=_container_url(base_url),
        via_device=parent,
        entry_type=DeviceEntryType.SERVICE,
    )


def _stack_device(stack_name: str, env_id: int, env_name: str, base_url: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"stack_{env_id}_{stack_name}")},
        name=f"{env_name} – {stack_name}",
        manufacturer="Dockhand",
        model="Stack",
        configuration_url=_stack_url(base_url),
        via_device=(DOMAIN, f"env_{env_id}_Stacks"),
        entry_type=DeviceEntryType.SERVICE,
    )


def _network_device(network_id: str, network_name: str,
                    env_id: int, env_name: str, base_url: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"network_{network_id}")},
        name=f"{env_name} – {network_name}",
        manufacturer="Dockhand",
        model="Network",
        configuration_url=_network_url(base_url),
        via_device=(DOMAIN, f"env_{env_id}_Networks"),
        entry_type=DeviceEntryType.SERVICE,
    )


def _volume_device(volume_name: str, env_id: int, env_name: str, base_url: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"volume_{env_id}_{volume_name}")},
        name=f"{env_name} – {volume_name}",
        manufacturer="Dockhand",
        model="Volume",
        configuration_url=_volume_url(base_url),
        via_device=(DOMAIN, f"env_{env_id}_Volumes"),
        entry_type=DeviceEntryType.SERVICE,
    )


def _image_group_device(env_id: int, env_name: str, base_url: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"env_{env_id}_Images")},
        name=f"{env_name} – Images",
        manufacturer="Dockhand",
        model="Environment",
        configuration_url=_image_url(base_url),
        via_device=(DOMAIN, f"env_{env_id}"),
        entry_type=DeviceEntryType.SERVICE,
    )


# --------------------------------------------------------------------------- #
# Container helpers
# --------------------------------------------------------------------------- #

def _image_display_name(image: dict) -> str:
    """Return a human-readable name for an image.

    Prefer the first repoTag (e.g. 'traefik:latest'). Fall back to the
    short 12-char hex ID for untagged/intermediate images.
    API field confirmed camelCase: repoTags, id (with sha256: prefix).
    """
    tags = [t for t in (image.get("repoTags") or []) if t and t != "<none>:<none>"]
    if tags:
        return tags[0]
    raw_id = image.get("id") or ""
    return raw_id.split(":")[-1][:12] if raw_id else "unknown"


def _container_has_healthcheck(container: dict) -> bool:
    """Return True only when the container has a configured health check.

    Docker sets health to 'none' for containers without a HEALTHCHECK
    instruction. We skip entity creation in that case so the HA device
    doesn't show a permanently-unknown Health sensor.
    """
    h = container.get("health")
    return bool(h) and h not in ("none", "unknown")
