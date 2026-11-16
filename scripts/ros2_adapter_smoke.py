"""Exercise ROS2RobotAdapter against a running TurtleBot3 Nav2 simulation."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from robot_agent.adapters.ros2_robot import MapBounds, ROS2RobotAdapter
from robot_agent.core.models import EventType, TaskStatus, TaskStep, TaskStepSpec
from robot_agent.mission.manager import MissionManager
from robot_agent.storage.sqlite import SQLiteTaskRepository


async def wait_for_status(adapter: ROS2RobotAdapter) -> dict[str, object]:
    for _ in range(100):
        result = adapter.get_robot_status()
        if result.success:
            return result.data
        await asyncio.sleep(0.1)
    raise RuntimeError("adapter did not receive odometry within 10 seconds")


async def wait_until_stopped(adapter: ROS2RobotAdapter) -> dict[str, object]:
    for _ in range(50):
        result = adapter.get_robot_status()
        if result.success and (
            abs(float(result.data["linear_velocity"])) < 0.01
            and abs(float(result.data["angular_velocity"])) < 0.01
        ):
            return result.data
        await asyncio.sleep(0.1)
    raise RuntimeError("robot did not stop within 5 seconds after timeout cancellation")


async def run() -> None:
    feedback_samples: list[dict[str, object]] = []
    adapter = ROS2RobotAdapter(
        map_bounds=MapBounds(min_x=-3.0, max_x=3.0, min_y=-2.0, max_y=2.0),
        feedback_handler=feedback_samples.append,
    )
    try:
        initial_status = await wait_for_status(adapter)
        results = []
        for position, x in enumerate((-1.2, -2.0)):
            step = TaskStep(
                position=position,
                action="navigate_to",
                parameters={"x": x, "y": -0.5, "yaw": 0.0},
                timeout_seconds=45.0,
            )
            result = await asyncio.wait_for(adapter.execute(step), timeout=45.0)
            if not result.success:
                raise RuntimeError(f"navigation goal {position} failed: {result}")
            results.append(result.model_dump(mode="json"))

        cancel_step = TaskStep(
            position=2,
            action="navigate_to",
            parameters={"x": 1.0, "y": -0.5, "yaw": 0.0},
            timeout_seconds=45.0,
        )
        cancel_execution = asyncio.create_task(adapter.execute(cancel_step))
        for _ in range(100):
            if adapter.latest_feedback:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.5)
        cancellation_requested = await adapter.cancel_current_action()
        cancelled_result = await asyncio.wait_for(cancel_execution, timeout=10.0)
        if not cancellation_requested or cancelled_result.error_code != "cancelled":
            raise RuntimeError(
                "active navigation did not settle as cancelled: "
                f"requested={cancellation_requested}, result={cancelled_result}"
            )

        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = SQLiteTaskRepository(
                Path(temporary_directory) / "timeout-test.db"
            )
            manager = MissionManager(repository, adapter)
            timeout_task = manager.create_task(
                "Real Nav2 timeout integration check",
                [
                    TaskStepSpec(
                        action="navigate_to",
                        parameters={"x": 1.0, "y": -0.5, "yaw": 0.0},
                        timeout_seconds=0.5,
                    )
                ],
            )
            settled_timeout_task = await manager.execute_task(timeout_task.id)
            timeout_events = manager.get_events(timeout_task.id)
            if settled_timeout_task.status is not TaskStatus.FAILED or not any(
                event.event_type is EventType.STEP_TIMED_OUT
                for event in timeout_events
            ):
                raise RuntimeError(
                    "MissionManager did not persist the real navigation timeout"
                )
            timeout_summary = {
                "task_status": settled_timeout_task.status.value,
                "step_status": settled_timeout_task.steps[0].status.value,
                "step_error": settled_timeout_task.steps[0].error,
                "events": [event.event_type.value for event in timeout_events],
            }

        final_status = await wait_until_stopped(adapter)
        print(
            json.dumps(
                {
                    "initial_status": initial_status,
                    "successful_goals": results,
                    "feedback_sample_count": len(feedback_samples),
                    "cancel_result": cancelled_result.model_dump(mode="json"),
                    "timeout_result": timeout_summary,
                    "final_status": final_status,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        adapter.close()


if __name__ == "__main__":
    asyncio.run(run())

