"""
Minimal but accurate stubs for the Home Assistant classes used by this integration.

These are NOT mocks — they implement just enough of the real HA API surface to
let our code run correctly under plain Python without a full HA installation.
Each stub matches the constructor signature and attribute names the integration
actually uses.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConfigEntryAuthFailed(Exception):
    pass


class ConfigEntryNotReady(Exception):
    pass


class HomeAssistantError(Exception):
    """Base exception for HA errors; supports translatable messages."""

    def __init__(self, *args, translation_domain=None, translation_key=None,
                 translation_placeholders=None, **kwargs):
        super().__init__(*args)
        self.translation_domain = translation_domain
        self.translation_key = translation_key
        self.translation_placeholders = translation_placeholders or {}


class UpdateFailed(Exception):
    pass


# ---------------------------------------------------------------------------
# homeassistant.core
# ---------------------------------------------------------------------------


class HomeAssistant:
    def __init__(self) -> None:
        self.config_entries = ConfigEntriesStub()
        self.data: dict = {}

    def async_create_task(self, coro):
        return asyncio.get_event_loop().create_task(coro)


class ConfigEntriesStub:
    def __init__(self) -> None:
        self._entries: dict[str, Any] = {}

    def async_get_entry(self, entry_id: str):
        return self._entries.get(entry_id)

    def async_update_entry(self, entry, *, data=None, options=None):
        if data is not None:
            object.__setattr__(entry, "data", data)
        if options is not None:
            object.__setattr__(entry, "options", options)

    async def async_forward_entry_setups(self, entry, platforms):
        pass  # platform setup tested separately

    async def async_unload_platforms(self, entry, platforms):
        return True

    async def async_reload(self, entry_id):
        pass


# ---------------------------------------------------------------------------
# homeassistant.config_entries
# ---------------------------------------------------------------------------


class ConfigEntry:
    """Minimal config entry — covers all attributes the integration accesses."""

    def __init__(
        self,
        entry_id: str = "test_entry_id",
        data: dict | None = None,
        options: dict | None = None,
    ) -> None:
        self.entry_id = entry_id
        self.data: dict = data or {}
        self.options: dict = options or {}
        self.runtime_data: Any = None
        self.context: dict = {"entry_id": entry_id}
        self._unload_listeners: list = []

    def async_on_unload(self, func):
        self._unload_listeners.append(func)
        return func


class OptionsFlow:
    """Stub OptionsFlow base class."""

    def async_show_form(self, *, step_id: str, data_schema=None, errors=None) -> dict:
        return {"type": "form", "step_id": step_id, "errors": errors or {}}

    def async_create_entry(self, *, title: str = "", data: dict) -> dict:
        return {"type": "create_entry", "title": title, "data": data}

    def async_abort(self, *, reason: str) -> dict:
        return {"type": "abort", "reason": reason}


class ConfigFlow:
    """Stub ConfigFlow base class with the methods our flow calls."""

    VERSION = 1
    _flow_id: str = "test_flow"

    def __init_subclass__(cls, domain: str = "", **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Wrap the subclass __init__ so that even if it doesn't call
        # super().__init__(), the flow still gets hass, context, and the
        # standard flow helper methods injected automatically.
        original_init = cls.__dict__.get("__init__")

        def patched_init(self, *args, **kw):
            # Inject HA flow infrastructure BEFORE the subclass init runs
            self.hass = HomeAssistant()
            self.context: dict = {"entry_id": "test_entry_id"}
            if original_init:
                original_init(self, *args, **kw)

        cls.__init__ = patched_init

    async def async_set_unique_id(self, unique_id: str) -> None:
        self._unique_id = unique_id

    def _abort_if_unique_id_configured(self) -> None:
        pass  # never abort in tests unless overridden

    def async_create_entry(self, *, title: str, data: dict) -> dict:
        return {"type": "create_entry", "title": title, "data": data}

    def async_show_form(self, *, step_id: str, data_schema=None, errors=None) -> dict:
        return {"type": "form", "step_id": step_id, "errors": errors or {}}

    def async_abort(self, *, reason: str) -> dict:
        return {"type": "abort", "reason": reason}


# ---------------------------------------------------------------------------
# homeassistant.helpers.update_coordinator
# ---------------------------------------------------------------------------


class DataUpdateCoordinator:
    """Minimal coordinator stub matching the constructor signature our code uses."""

    def __class_getitem__(cls, item):
        return cls  # support DataUpdateCoordinator[T]

    def __init__(
        self,
        hass: HomeAssistant,
        logger,
        *,
        name: str,
        update_interval: timedelta,
        config_entry=None,
    ) -> None:
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data: Any = None
        self.last_update_success: bool = True
        self.last_exception: Exception | None = None
        self._listeners: list = []

    async def async_config_entry_first_refresh(self) -> None:
        self.data = await self._async_update_data()

    async def _async_update_data(self) -> Any:
        raise NotImplementedError

    def async_add_listener(self, listener) -> callable:
        self._listeners.append(listener)

        def remove():
            self._listeners.remove(listener)

        return remove

    async def async_request_refresh(self) -> None:
        """Stub: trigger a refresh (no-op in tests unless overridden)."""
        pass

    def _call_listeners(self):
        for listener in self._listeners:
            listener()


class CoordinatorEntity:
    def __class_getitem__(cls, item):
        return cls

    """Stub CoordinatorEntity — our entities inherit from this."""

    # Defaults — subclasses override these as class attributes.
    # Do NOT set them as instance attrs in __init__; that would shadow
    # class-level overrides (e.g. _attr_entity_category = EntityCategory.DIAGNOSTIC).
    _attr_unique_id: str | None = None
    _attr_name: str | None = None
    _attr_has_entity_name: bool = False
    _attr_entity_category = None
    _attr_entity_registry_enabled_default: bool = True
    _attr_native_unit_of_measurement: str | None = None
    _attr_device_class = None
    _attr_state_class = None

    def __init__(self, coordinator: DataUpdateCoordinator) -> None:
        self.coordinator = coordinator

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def device_info(self):
        return None


# ---------------------------------------------------------------------------
# homeassistant.helpers.entity
# ---------------------------------------------------------------------------


class DeviceInfo(dict):
    """DeviceInfo is a TypedDict in real HA; dict subclass is sufficient here."""

    pass


# ---------------------------------------------------------------------------
# homeassistant.helpers.device_registry
# ---------------------------------------------------------------------------


class DeviceEntryType:
    SERVICE = "service"


class DeviceEntry:
    def __init__(self, id: str, identifiers: set, config_entry_id: str) -> None:
        self.id = id
        self.identifiers = identifiers
        self.config_entry_id = config_entry_id


class DeviceRegistry:
    def __init__(self) -> None:
        self._devices: dict[str, DeviceEntry] = {}
        self._by_config_entry: dict[str, list[DeviceEntry]] = {}
        self._created: list[dict] = []  # log of all create calls
        self._removed: list[str] = []  # log of removed device IDs

    def async_get_or_create(
        self,
        *,
        config_entry_id,
        identifiers,
        name,
        manufacturer=None,
        model=None,
        configuration_url=None,
        via_device=None,
        entry_type=None,
    ) -> DeviceEntry:
        key = frozenset(identifiers)
        # Return existing if already registered
        for dev in self._devices.values():
            if frozenset(dev.identifiers) == key:
                return dev
        dev_id = f"dev_{len(self._devices)}"
        entry = DeviceEntry(dev_id, identifiers, config_entry_id)
        self._devices[dev_id] = entry
        self._by_config_entry.setdefault(config_entry_id, []).append(entry)
        self._created.append({"name": name, "identifiers": identifiers})
        return entry

    def async_remove_device(self, device_id: str) -> None:
        dev = self._devices.pop(device_id, None)
        if dev:
            self._removed.append(device_id)
            self._by_config_entry.get(dev.config_entry_id, []).remove(dev)

    def async_entries_for_config_entry(self, config_entry_id: str) -> list[DeviceEntry]:
        return list(self._by_config_entry.get(config_entry_id, []))


_DEVICE_REGISTRY: DeviceRegistry | None = None


def async_get(hass) -> DeviceRegistry:
    global _DEVICE_REGISTRY
    if _DEVICE_REGISTRY is None:
        _DEVICE_REGISTRY = DeviceRegistry()
    return _DEVICE_REGISTRY


def async_entries_for_config_entry(
    registry: DeviceRegistry, entry_id: str
) -> list[DeviceEntry]:
    return registry.async_entries_for_config_entry(entry_id)


def reset_registry() -> None:
    global _DEVICE_REGISTRY
    _DEVICE_REGISTRY = None


# ---------------------------------------------------------------------------
# homeassistant.helpers.entity_registry
# ---------------------------------------------------------------------------


class EntityEntry:
    def __init__(self, entity_id: str, unique_id: str, config_entry_id: str) -> None:
        self.entity_id = entity_id
        self.unique_id = unique_id
        self.config_entry_id = config_entry_id


class EntityRegistry:
    def __init__(self) -> None:
        self._entities: dict[str, EntityEntry] = {}  # keyed by entity_id
        self._by_config_entry: dict[str, list[EntityEntry]] = {}
        self._removed: list[str] = []  # log of removed entity_ids

    def async_get_or_create(
        self, *, config_entry_id: str, platform: str, unique_id: str, **kwargs
    ) -> EntityEntry:
        for ent in self._entities.values():
            if ent.unique_id == unique_id and ent.config_entry_id == config_entry_id:
                return ent
        entity_id = f"{platform}.{unique_id.replace(' ', '_')}"
        entry = EntityEntry(entity_id, unique_id, config_entry_id)
        self._entities[entity_id] = entry
        self._by_config_entry.setdefault(config_entry_id, []).append(entry)
        return entry

    def async_remove(self, entity_id: str) -> None:
        ent = self._entities.pop(entity_id, None)
        if ent:
            self._removed.append(entity_id)
            entries = self._by_config_entry.get(ent.config_entry_id, [])
            if ent in entries:
                entries.remove(ent)

    def async_update_entity(
        self,
        entity_id: str,
        *,
        new_entity_id: str | None = None,
        new_unique_id: str | None = None,
        **kwargs,
    ) -> None:
        """Stub for HA's entity registry update — supports entity_id and unique_id rename."""
        ent = self._entities.get(entity_id)
        if ent is None:
            return
        if new_entity_id and new_entity_id != entity_id:
            self._entities.pop(entity_id)
            ent.entity_id = new_entity_id
            self._entities[new_entity_id] = ent
        if new_unique_id:
            ent.unique_id = new_unique_id

    def async_entries_for_config_entry(self, config_entry_id: str) -> list[EntityEntry]:
        return list(self._by_config_entry.get(config_entry_id, []))

    def _add(
        self, config_entry_id: str, unique_id: str, platform: str = "sensor"
    ) -> EntityEntry:
        """Test helper: register an entity directly."""
        entity_id = f"{platform}.{unique_id}"
        entry = EntityEntry(entity_id, unique_id, config_entry_id)
        self._entities[entity_id] = entry
        self._by_config_entry.setdefault(config_entry_id, []).append(entry)
        return entry


_ENTITY_REGISTRY: EntityRegistry | None = None


def er_async_get(hass) -> EntityRegistry:
    global _ENTITY_REGISTRY
    if _ENTITY_REGISTRY is None:
        _ENTITY_REGISTRY = EntityRegistry()
    return _ENTITY_REGISTRY


def er_async_entries_for_config_entry(
    registry: EntityRegistry, entry_id: str
) -> list[EntityEntry]:
    return registry.async_entries_for_config_entry(entry_id)


def reset_entity_registry() -> None:
    global _ENTITY_REGISTRY
    _ENTITY_REGISTRY = None


# ---------------------------------------------------------------------------
# homeassistant.components.sensor
# ---------------------------------------------------------------------------


class SensorEntity:
    """Platform base — does NOT inherit CoordinatorEntity.
    Integration classes do class Foo(CoordinatorEntity, SensorEntity) so
    having SensorEntity also inherit CoordinatorEntity creates an MRO conflict."""

    @property
    def native_value(self):
        return None

    @property
    def extra_state_attributes(self):
        return {}


class SensorStateClass:
    MEASUREMENT = "measurement"
    TOTAL = "total"
    TOTAL_INCREASING = "total_increasing"


class SensorDeviceClass:
    DATA_SIZE = "data_size"
    TIMESTAMP = "timestamp"


# ---------------------------------------------------------------------------
# homeassistant.components.binary_sensor
# ---------------------------------------------------------------------------


class BinarySensorEntity:
    @property
    def is_on(self) -> bool | None:
        return None


class BinarySensorDeviceClass:
    CONNECTIVITY = "connectivity"
    PLUG = "plug"


# ---------------------------------------------------------------------------
# homeassistant.components.switch
# ---------------------------------------------------------------------------


class SwitchEntity:
    @property
    def is_on(self) -> bool | None:
        return None


# ---------------------------------------------------------------------------
# homeassistant.components.button
# ---------------------------------------------------------------------------


class ButtonEntity:
    async def async_press(self) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# homeassistant.const
# ---------------------------------------------------------------------------


class EntityCategory:
    DIAGNOSTIC = "diagnostic"
    CONFIG = "config"


class UnitOfInformation:
    BYTES = "B"
    KILOBYTES = "kB"
    MEGABYTES = "MB"
    GIGABYTES = "GB"
    KIBIBYTES = "KiB"
    MEBIBYTES = "MiB"
    GIBIBYTES = "GiB"


# ---------------------------------------------------------------------------
# homeassistant.data_entry_flow
# ---------------------------------------------------------------------------

FlowResult = dict


# ---------------------------------------------------------------------------
# homeassistant.helpers.aiohttp_client
# ---------------------------------------------------------------------------


def async_get_clientsession(hass, verify_ssl=True) -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# homeassistant.helpers.entity_platform
# ---------------------------------------------------------------------------

AddEntitiesCallback = callable


# ---------------------------------------------------------------------------
# homeassistant.util.dt
# ---------------------------------------------------------------------------


class dt_util_module:
    @staticmethod
    def utc_from_timestamp(ts: float):
        import datetime

        return datetime.datetime.utcfromtimestamp(ts).replace(tzinfo=datetime.UTC)

    @staticmethod
    def parse_datetime(value: str):
        """Parse an ISO 8601 string to a datetime. Returns None for non-strings."""
        import datetime

        if not isinstance(value, str):
            return None
        try:
            # Handle Z suffix
            s = value.rstrip("Z")
            if "T" in s:
                return datetime.datetime.fromisoformat(s).replace(tzinfo=datetime.UTC)
            return None
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def as_utc(dt):
        """Return dt with UTC timezone attached."""
        import datetime

        if dt is None:
            return None
        return dt.replace(tzinfo=datetime.UTC)


dt_util = dt_util_module()


# ---------------------------------------------------------------------------
# Install stubs into sys.modules so our integration imports resolve correctly
# ---------------------------------------------------------------------------


def install() -> None:
    """Call once before importing any integration module."""

    def _mod(name: str, **attrs) -> MagicMock:
        m = MagicMock()
        m.__name__ = name
        for k, v in attrs.items():
            setattr(m, k, v)
        return m

    # Core
    ha_core = _mod("homeassistant.core", HomeAssistant=HomeAssistant)
    ha_exc = _mod(
        "homeassistant.exceptions",
        ConfigEntryAuthFailed=ConfigEntryAuthFailed,
        ConfigEntryNotReady=ConfigEntryNotReady,
        HomeAssistantError=HomeAssistantError,
    )

    # config_entries module — needs ConfigFlow and OptionsFlow as real classes
    # so our DockhandConfigFlow(config_entries.ConfigFlow, domain=DOMAIN) works
    ha_ce = _mod(
        "homeassistant.config_entries",
        ConfigEntry=ConfigEntry,
        ConfigFlow=ConfigFlow,
        OptionsFlow=OptionsFlow,
    )

    ha_flow = _mod("homeassistant.data_entry_flow", FlowResult=FlowResult)

    # helpers
    ha_dr_mod = sys.modules.get("homeassistant.helpers.device_registry") or _mod(
        "homeassistant.helpers.device_registry"
    )
    ha_dr_mod.async_get = async_get
    ha_dr_mod.async_entries_for_config_entry = async_entries_for_config_entry
    ha_dr_mod.DeviceRegistry = DeviceRegistry
    ha_dr_mod.DeviceEntry = DeviceEntry
    ha_dr_mod.DeviceEntryType = DeviceEntryType

    ha_er_mod = sys.modules.get("homeassistant.helpers.entity_registry") or _mod(
        "homeassistant.helpers.entity_registry"
    )
    ha_er_mod.async_get = er_async_get
    ha_er_mod.async_entries_for_config_entry = er_async_entries_for_config_entry
    ha_er_mod.EntityRegistry = EntityRegistry
    ha_er_mod.EntityEntry = EntityEntry

    ha_entity = _mod("homeassistant.helpers.entity", DeviceInfo=DeviceInfo)
    ha_coord = _mod(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=DataUpdateCoordinator,
        CoordinatorEntity=CoordinatorEntity,
        UpdateFailed=UpdateFailed,
    )
    ha_aiohttp = _mod(
        "homeassistant.helpers.aiohttp_client",
        async_get_clientsession=async_get_clientsession,
    )
    ha_ep = _mod(
        "homeassistant.helpers.entity_platform", AddEntitiesCallback=AddEntitiesCallback
    )
    ha_helpers = _mod(
        "homeassistant.helpers", device_registry=ha_dr_mod, entity_registry=ha_er_mod
    )

    # components
    ha_sensor = _mod(
        "homeassistant.components.sensor",
        SensorEntity=SensorEntity,
        SensorStateClass=SensorStateClass,
        SensorDeviceClass=SensorDeviceClass,
    )
    ha_bs = _mod(
        "homeassistant.components.binary_sensor",
        BinarySensorEntity=BinarySensorEntity,
        BinarySensorDeviceClass=BinarySensorDeviceClass,
    )
    ha_switch = _mod("homeassistant.components.switch", SwitchEntity=SwitchEntity)
    ha_button = _mod("homeassistant.components.button", ButtonEntity=ButtonEntity)

    ha_const = _mod("homeassistant.const", EntityCategory=EntityCategory, UnitOfInformation=UnitOfInformation)
    ha_dt = _mod(
        "homeassistant.util.dt",
        utc_from_timestamp=dt_util.utc_from_timestamp,
        parse_datetime=dt_util.parse_datetime,
        as_utc=dt_util.as_utc,
    )

    # homeassistant top-level (for `from homeassistant import config_entries`)
    ha_top = _mod("homeassistant", config_entries=ha_ce)

    mods = {
        "homeassistant": ha_top,
        "homeassistant.core": ha_core,
        "homeassistant.exceptions": ha_exc,
        "homeassistant.config_entries": ha_ce,
        "homeassistant.data_entry_flow": ha_flow,
        "homeassistant.helpers": ha_helpers,
        "homeassistant.helpers.device_registry": ha_dr_mod,
        "homeassistant.helpers.entity_registry": ha_er_mod,
        "homeassistant.helpers.entity": ha_entity,
        "homeassistant.helpers.update_coordinator": ha_coord,
        "homeassistant.helpers.aiohttp_client": ha_aiohttp,
        "homeassistant.helpers.entity_platform": ha_ep,
        "homeassistant.components.sensor": ha_sensor,
        "homeassistant.components.binary_sensor": ha_bs,
        "homeassistant.components.switch": ha_switch,
        "homeassistant.components.button": ha_button,
        "homeassistant.const": ha_const,
        "homeassistant.util": _mod("homeassistant.util"),
        "homeassistant.util.dt": ha_dt,
        "voluptuous": _mod(
            "voluptuous",
            Schema=MagicMock(return_value=MagicMock()),
            Required=lambda k, **kw: k,
            Optional=lambda k, **kw: k,
        ),
        "aiohttp": _mod("aiohttp", ClientSession=MagicMock),
    }
    for name, mod in mods.items():
        if name not in sys.modules:
            sys.modules[name] = mod
