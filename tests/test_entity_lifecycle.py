"""Entity classes must be able to follow an entity_id rename in place.

From HA 2026.11, an entity whose own (non-HA) class defines
async_added_to_hass, async_will_remove_from_hass or
async_prepare_to_add_to_hass is removed and re-added on an entity_id rename
unless that class, or a subclass of it, also defines
async_entity_id_changed; the re-add fallback for custom integrations ends in
2027.11. This mirrors HA's own check (_entity_class_requires_readd in
homeassistant/helpers/entity.py) over every entity class here, so a new
lifecycle hook can't quietly opt an entity out.
"""

import importlib
import inspect

from homeassistant.helpers.entity import Entity

_ADD_REMOVE_METHODS = (
    "async_prepare_to_add_to_hass",
    "async_added_to_hass",
    "async_will_remove_from_hass",
)
_PLATFORMS = (
    "binary_sensor",
    "button",
    "event",
    "number",
    "select",
    "sensor",
    "switch",
    "update",
)


def _requires_readd(entity_class: type) -> bool:
    mro = [
        c for c in entity_class.__mro__ if not c.__module__.startswith("homeassistant.")
    ]
    hook_owners = [c for c in mro if "async_entity_id_changed" in c.__dict__]
    return any(
        any(m in c.__dict__ for m in _ADD_REMOVE_METHODS)
        and not any(issubclass(owner, c) for owner in hook_owners)
        for c in mro
    )


def _entity_classes():
    for platform in _PLATFORMS:
        module = importlib.import_module(f"custom_components.dockhand.{platform}")
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, Entity) and cls.__module__ == module.__name__:
                yield cls


def test_every_entity_class_renames_in_place():
    classes = list(_entity_classes())
    assert classes
    offenders = [c.__name__ for c in classes if _requires_readd(c)]
    assert offenders == []


def test_memory_limit_number_hook_calls_super():
    from unittest.mock import patch

    from custom_components.dockhand.number import DockhandContainerMemoryLimitNumber

    entity = DockhandContainerMemoryLimitNumber.__new__(
        DockhandContainerMemoryLimitNumber
    )
    base = DockhandContainerMemoryLimitNumber.__mro__[1]
    with patch.object(base, "async_entity_id_changed", create=True) as parent:
        entity.async_entity_id_changed("number.old")
    parent.assert_called_once_with("number.old")


def test_update_and_event_hooks_call_super():
    from unittest.mock import patch

    from custom_components.dockhand.binary_sensor import (
        DockhandLiveUpdatesBinarySensor,
    )
    from custom_components.dockhand.event import DockhandContainerEventEntity
    from custom_components.dockhand.update import ContainerUpdateEntity

    for cls in (
        ContainerUpdateEntity,
        DockhandContainerEventEntity,
        DockhandLiveUpdatesBinarySensor,
    ):
        entity = cls.__new__(cls)
        base = cls.__mro__[1]
        with patch.object(base, "async_entity_id_changed", create=True) as parent:
            entity.async_entity_id_changed("x.old")
        parent.assert_called_once_with("x.old")
