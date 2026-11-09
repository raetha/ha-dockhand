"""The container State and Health sensors: enum states and attributes."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorDeviceClass

from custom_components.dockhand.sensor import (
    CONTAINER_HEALTH_STATES,
    CONTAINER_STATES,
    DockhandContainerHealthSensor,
    DockhandContainerStateSensor,
)

BASE = {"id": "c1", "name": "web", "image": "nginx:1.27", "labels": {}}


def _sensor(cls, container: dict):
    coord = MagicMock()
    coord.data = {"environments": {1: {"containers": [container]}}}
    coord.last_update_success = True
    return cls(coord, "entry", 1, "local", "http://dh.test:3000", container)


def test_state_and_health_are_enums():
    state = _sensor(DockhandContainerStateSensor, {**BASE, "state": "running"})
    health = _sensor(DockhandContainerHealthSensor, {**BASE, "health": "healthy"})
    assert state.device_class is SensorDeviceClass.ENUM
    assert state.options == CONTAINER_STATES
    assert health.device_class is SensorDeviceClass.ENUM
    assert health.options == CONTAINER_HEALTH_STATES
    assert state.native_value == "running"
    assert health.native_value == "healthy"


@pytest.mark.parametrize(
    ("cls", "field"),
    [
        (DockhandContainerStateSensor, "state"),
        (DockhandContainerHealthSensor, "health"),
    ],
)
def test_a_value_docker_doesnt_define_reads_as_unknown(cls, field: str):
    assert _sensor(cls, {**BASE, field: "hibernating"}).native_value is None


def test_state_attributes_for_an_exited_container():
    sensor = _sensor(
        DockhandContainerStateSensor,
        {
            **BASE,
            "state": "exited",
            "exitCode": 137,
            "restartCount": 0,
            "labels": {"org.opencontainers.image.version": "1.27.3"},
        },
    )
    attrs = sensor.extra_state_attributes
    assert attrs["exit_code"] == 137
    assert attrs["image_version"] == "1.27.3"
    assert attrs["restart_count"] is None


def test_state_attributes_while_restarting():
    sensor = _sensor(
        DockhandContainerStateSensor,
        {**BASE, "state": "restarting", "restartCount": 4, "exitCode": 1},
    )
    attrs = sensor.extra_state_attributes
    assert attrs["restart_count"] == 4
    assert attrs["exit_code"] is None
    assert attrs["image_version"] is None
