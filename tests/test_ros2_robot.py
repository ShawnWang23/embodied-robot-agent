from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

import robot_agent.adapters.ros2_robot as ros2_robot_module
from robot_agent.adapters.ros2_robot import (
    MapBounds,
    NavigateToParameters,
    ROS2RobotAdapter,
)


def test_navigate_to_parameters_validate_safe_shape() -> None:
    parameters = NavigateToParameters.model_validate({"x": 1, "y": -2.5})

    assert parameters.x == 1.0
    assert parameters.y == -2.5
    assert parameters.yaw == 0.0
    assert parameters.frame_id == "map"


@pytest.mark.parametrize(
    "parameters",
    [
        {"x": math.nan, "y": 0.0},
        {"x": 0.0, "y": math.inf},
        {"x": 0.0, "y": 0.0, "yaw": math.pi + 0.01},
        {"x": 0.0, "y": 0.0, "frame_id": "odom"},
        {"x": 0.0, "y": 0.0, "speed": 10.0},
    ],
)
def test_navigate_to_parameters_reject_unsafe_values(
    parameters: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        NavigateToParameters.model_validate(parameters)


def test_map_bounds_contains_edges_but_not_outside() -> None:
    bounds = MapBounds(min_x=-2.0, max_x=2.0, min_y=-1.0, max_y=1.0)

    assert bounds.contains(-2.0, 1.0)
    assert not bounds.contains(2.01, 0.0)


def test_adapter_reports_missing_ros_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ros2_robot_module,
        "_ROS2_IMPORT_ERROR",
        ModuleNotFoundError("rclpy"),
    )

    with pytest.raises(RuntimeError, match="sourced ROS 2 environment"):
        ROS2RobotAdapter(
            map_bounds=MapBounds(min_x=-1, max_x=1, min_y=-1, max_y=1)
        )

