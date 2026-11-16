"""ROS 2 / Nav2 implementation of the robot capability port.

The module remains importable on Windows so the domain package can still be
tested there. Constructing :class:`ROS2RobotAdapter` requires a sourced ROS 2
Jazzy environment with ``rclpy`` and ``nav2_msgs`` available.
"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
from collections.abc import Callable
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from robot_agent.core.interfaces import RobotAdapter
from robot_agent.core.models import RobotActionResult, TaskStep

logger = logging.getLogger(__name__)

try:
    import rclpy
    from action_msgs.msg import GoalStatus
    from geometry_msgs.msg import PoseStamped
    from nav2_msgs.action import NavigateToPose
    from nav_msgs.msg import Odometry
    from rclpy.action import ActionClient
    from rclpy.context import Context
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
except ModuleNotFoundError as exc:  # Expected in the Windows-only test runtime.
    _ROS2_IMPORT_ERROR: ModuleNotFoundError | None = exc
else:
    _ROS2_IMPORT_ERROR = None


class NavigateToParameters(BaseModel):
    """Validated parameters accepted by the ``navigate_to`` robot skill."""

    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    yaw: float = Field(default=0.0, ge=-math.pi, le=math.pi)
    frame_id: Literal["map"] = "map"

    @field_validator("x", "y", "yaw")
    @classmethod
    def require_finite_number(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("navigation coordinates must be finite")
        return value


class MapBounds(BaseModel):
    """Axis-aligned map boundary used before a goal reaches Nav2."""

    model_config = ConfigDict(frozen=True)

    min_x: float
    max_x: float
    min_y: float
    max_y: float

    @field_validator("min_x", "max_x", "min_y", "max_y")
    @classmethod
    def require_finite_bound(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("map bounds must be finite")
        return value

    def contains(self, x: float, y: float) -> bool:
        return self.min_x <= x <= self.max_x and self.min_y <= y <= self.max_y


FeedbackHandler = Callable[[dict[str, Any]], None]


class ROS2RobotAdapter(RobotAdapter):
    """Send validated goals to Nav2 while keeping ROS callbacks off asyncio."""

    def __init__(
        self,
        *,
        map_bounds: MapBounds,
        action_server_timeout: float = 10.0,
        feedback_handler: FeedbackHandler | None = None,
        node_name: str | None = None,
    ) -> None:
        if _ROS2_IMPORT_ERROR is not None:
            raise RuntimeError(
                "ROS2RobotAdapter requires a sourced ROS 2 environment"
            ) from _ROS2_IMPORT_ERROR
        if map_bounds.min_x >= map_bounds.max_x or map_bounds.min_y >= map_bounds.max_y:
            raise ValueError("map bounds minimums must be smaller than maximums")
        if action_server_timeout <= 0:
            raise ValueError("action_server_timeout must be positive")

        self._map_bounds = map_bounds
        self._action_server_timeout = action_server_timeout
        self._feedback_handler = feedback_handler
        self._execution_lock = asyncio.Lock()
        self._state_lock = threading.Lock()
        self._cancel_requested = threading.Event()
        self._is_executing = False
        self._goal_handle: Any | None = None
        self._latest_feedback: dict[str, Any] = {}
        self._latest_status: dict[str, Any] | None = None
        self._closed = False

        self._context = Context()
        rclpy.init(context=self._context)
        resolved_name = node_name or f"robot_agent_adapter_{uuid4().hex[:8]}"
        self._node = Node(resolved_name, context=self._context)
        self._action_client = ActionClient(
            self._node,
            NavigateToPose,
            "/navigate_to_pose",
        )
        self._odom_subscription = self._node.create_subscription(
            Odometry,
            "/odom",
            self._on_odometry,
            qos_profile_sensor_data,
        )
        self._executor = SingleThreadedExecutor(context=self._context)
        self._executor.add_node(self._node)
        self._spin_thread = threading.Thread(
            target=self._executor.spin,
            name=f"{resolved_name}-executor",
            daemon=True,
        )
        self._spin_thread.start()

    @property
    def latest_feedback(self) -> dict[str, Any]:
        """Return a copy of the most recent Nav2 feedback snapshot."""

        with self._state_lock:
            return dict(self._latest_feedback)

    async def execute(self, step: TaskStep) -> RobotActionResult:
        if self._closed:
            return RobotActionResult(
                success=False,
                message="ROS2 adapter is closed",
                error_code="adapter_closed",
            )

        async with self._execution_lock:
            if step.action == "get_robot_status":
                return self.get_robot_status()
            if step.action != "navigate_to":
                return RobotActionResult(
                    success=False,
                    message=f"Unsupported ROS2 action '{step.action}'",
                    error_code="unsupported_action",
                )

            self._cancel_requested.clear()
            with self._state_lock:
                self._is_executing = True
                self._latest_feedback = {}
            try:
                parameters = NavigateToParameters.model_validate(step.parameters)
                if not self._map_bounds.contains(parameters.x, parameters.y):
                    return RobotActionResult(
                        success=False,
                        message=(
                            f"Goal ({parameters.x:g}, {parameters.y:g}) is outside "
                            "the configured map boundary"
                        ),
                        error_code="goal_out_of_bounds",
                    )
                return await self._navigate_to(parameters)
            except ValidationError as exc:
                return RobotActionResult(
                    success=False,
                    message=f"Invalid navigate_to parameters: {exc}",
                    error_code="invalid_parameters",
                )
            except asyncio.CancelledError:
                await asyncio.shield(self._cancel_active_goal())
                raise
            except Exception as exc:
                logger.exception("ROS2 navigation request failed")
                return RobotActionResult(
                    success=False,
                    message=f"ROS2 navigation error: {exc}",
                    error_code="navigation_error",
                )
            finally:
                with self._state_lock:
                    self._is_executing = False
                    self._goal_handle = None

    def get_robot_status(self) -> RobotActionResult:
        """Return the latest odometry sample without blocking the executor."""

        with self._state_lock:
            status = dict(self._latest_status) if self._latest_status else None
        if status is None:
            return RobotActionResult(
                success=False,
                message="No odometry has been received yet",
                error_code="status_unavailable",
            )
        return RobotActionResult(
            success=True,
            message="Robot status available",
            data=status,
        )

    def get_execution_feedback(self) -> dict[str, Any]:
        """Expose the latest Nav2 feedback through the adapter port."""

        return self.latest_feedback

    async def cancel_current_action(self) -> bool:
        """Cancel the active Nav2 goal, including the goal-acceptance race."""

        with self._state_lock:
            is_executing = self._is_executing
        if not is_executing:
            return False
        self._cancel_requested.set()
        await self._cancel_active_goal()
        return True

    async def _navigate_to(
        self,
        parameters: NavigateToParameters,
    ) -> RobotActionResult:
        server_ready = await asyncio.to_thread(
            self._action_client.wait_for_server,
            timeout_sec=self._action_server_timeout,
        )
        if not server_ready:
            return RobotActionResult(
                success=False,
                message="Nav2 NavigateToPose action server is unavailable",
                error_code="action_server_unavailable",
            )

        goal = NavigateToPose.Goal()
        goal.pose = PoseStamped()
        goal.pose.header.frame_id = parameters.frame_id
        goal.pose.header.stamp = self._node.get_clock().now().to_msg()
        goal.pose.pose.position.x = parameters.x
        goal.pose.pose.position.y = parameters.y
        goal.pose.pose.orientation.z = math.sin(parameters.yaw / 2.0)
        goal.pose.pose.orientation.w = math.cos(parameters.yaw / 2.0)

        send_future = self._action_client.send_goal_async(
            goal,
            feedback_callback=self._on_navigation_feedback,
        )
        goal_handle = await self._await_ros_future(send_future)
        if not goal_handle.accepted:
            return RobotActionResult(
                success=False,
                message="Nav2 rejected the navigation goal",
                error_code="goal_rejected",
            )

        with self._state_lock:
            self._goal_handle = goal_handle
        if self._cancel_requested.is_set():
            await self._cancel_active_goal()

        wrapped_result = await self._await_ros_future(goal_handle.get_result_async())
        feedback = self.latest_feedback
        result_data = {
            "goal": parameters.model_dump(),
            "feedback": feedback,
            "nav2_error_code": int(wrapped_result.result.error_code),
            "nav2_error_msg": wrapped_result.result.error_msg,
        }
        if wrapped_result.status == GoalStatus.STATUS_SUCCEEDED:
            return RobotActionResult(
                success=True,
                message="Navigation goal succeeded",
                data=result_data,
            )
        if wrapped_result.status == GoalStatus.STATUS_CANCELED:
            return RobotActionResult(
                success=False,
                message="Navigation goal was cancelled",
                data=result_data,
                error_code="cancelled",
            )
        return RobotActionResult(
            success=False,
            message=wrapped_result.result.error_msg or "Navigation goal aborted",
            data=result_data,
            error_code="navigation_aborted",
        )

    async def _cancel_active_goal(self) -> None:
        with self._state_lock:
            goal_handle = self._goal_handle
        if goal_handle is None:
            return
        cancel_response = await self._await_ros_future(
            goal_handle.cancel_goal_async(),
            timeout=5.0,
        )
        if not cancel_response.goals_canceling:
            logger.warning("Nav2 did not accept the goal cancellation request")

    async def _await_ros_future(self, future: Any, *, timeout: float | None = None) -> Any:
        async def wait_until_done() -> Any:
            while not future.done():
                await asyncio.sleep(0.01)
            exception = future.exception()
            if exception is not None:
                raise exception
            return future.result()

        if timeout is None:
            return await wait_until_done()
        return await asyncio.wait_for(wait_until_done(), timeout=timeout)

    def _on_navigation_feedback(self, feedback_message: Any) -> None:
        feedback = feedback_message.feedback
        pose = feedback.current_pose.pose
        snapshot = {
            "current_pose": {
                "x": pose.position.x,
                "y": pose.position.y,
                "orientation_z": pose.orientation.z,
                "orientation_w": pose.orientation.w,
            },
            "navigation_time_seconds": (
                feedback.navigation_time.sec
                + feedback.navigation_time.nanosec / 1_000_000_000
            ),
            "estimated_time_remaining_seconds": (
                feedback.estimated_time_remaining.sec
                + feedback.estimated_time_remaining.nanosec / 1_000_000_000
            ),
            "number_of_recoveries": int(feedback.number_of_recoveries),
            "distance_remaining": float(feedback.distance_remaining),
        }
        with self._state_lock:
            self._latest_feedback = snapshot
        if self._feedback_handler is not None:
            try:
                self._feedback_handler(dict(snapshot))
            except Exception:
                logger.exception("Navigation feedback handler raised an exception")

    def _on_odometry(self, message: Any) -> None:
        pose = message.pose.pose
        twist = message.twist.twist
        status = {
            "frame_id": message.header.frame_id,
            "child_frame_id": message.child_frame_id,
            "position": {"x": pose.position.x, "y": pose.position.y},
            "orientation": {"z": pose.orientation.z, "w": pose.orientation.w},
            "linear_velocity": twist.linear.x,
            "angular_velocity": twist.angular.z,
        }
        with self._state_lock:
            self._latest_status = status

    def close(self) -> None:
        """Release the ROS node, executor thread, and private context."""

        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(timeout_sec=2.0)
        self._executor.remove_node(self._node)
        self._node.destroy_node()
        self._context.try_shutdown()
        self._spin_thread.join(timeout=2.0)

    def __enter__(self) -> "ROS2RobotAdapter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

