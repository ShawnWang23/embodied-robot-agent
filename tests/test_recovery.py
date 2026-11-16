from __future__ import annotations

from pathlib import Path

import pytest

from robot_agent.adapters.fake_robot import FakeRobotAdapter
from robot_agent.agent.locations import LocationCatalog
from robot_agent.agent.models import NavigateToPlanStep, TaskPlan
from robot_agent.agent.tools import ToolRegistry
from robot_agent.core.exceptions import InvalidTaskStateError
from robot_agent.core.models import (
    EventType,
    RobotActionResult,
    StepStatus,
    TaskStatus,
    TaskStepSpec,
)
from robot_agent.mission.manager import MissionManager
from robot_agent.mission.recovery import RecoveryConfig, RecoveryPolicy
from robot_agent.storage.sqlite import SQLiteTaskRepository


def result(
    success: bool,
    message: str,
    error_code: str | None = None,
) -> RobotActionResult:
    return RobotActionResult(
        success=success,
        message=message,
        error_code=error_code,
    )


def build_manager(
    database_path: Path,
    scripted_results: dict[str, list[RobotActionResult]],
    *,
    config: RecoveryConfig | None = None,
    delay_seconds: float = 0.0,
) -> tuple[MissionManager, FakeRobotAdapter]:
    robot = FakeRobotAdapter(
        delay_seconds=delay_seconds,
        scripted_results=scripted_results,
    )
    manager = MissionManager(
        SQLiteTaskRepository(database_path),
        robot,
        recovery_policy=RecoveryPolicy(config),
        feedback_poll_interval=0.005,
    )
    return manager, robot


@pytest.mark.parametrize("error_code", ["navigation_aborted", "path_blocked"])
@pytest.mark.asyncio
async def test_unreachable_or_blocked_goal_uses_explicit_fallback(
    tmp_path: Path,
    error_code: str,
) -> None:
    locations = LocationCatalog.from_json(Path("config/locations.json"))
    tools = ToolRegistry(locations)
    steps = tools.compile_plan(
        TaskPlan(
            objective="try the laboratory, then observe from the corridor",
            steps=[
                NavigateToPlanStep(
                    action="navigate_to",
                    location="laboratory_door",
                    reason="requested inspection point",
                )
            ],
        )
    )
    manager, robot = build_manager(
        tmp_path / f"{error_code}.db",
        {
            "navigate_to": [
                result(False, "route unavailable", error_code),
                result(True, "fallback reached"),
            ]
        },
    )
    task = manager.create_task("fallback test", steps)

    completed = await manager.execute_task(task.id)
    events = manager.get_events(task.id)

    assert completed.status is TaskStatus.COMPLETED
    assert completed.steps[0].attempt_count == 2
    assert robot.executed_steps[0].metadata["location"] == "laboratory_door"
    assert robot.executed_steps[1].metadata["location"] == "corridor_observation"
    assert robot.executed_steps[1].parameters == {
        "x": -1.5,
        "y": 0.5,
        "yaw": 0.0,
    }
    assert any(
        event.event_type is EventType.STEP_FALLBACK_APPLIED for event in events
    )


@pytest.mark.asyncio
async def test_tool_failure_retries_then_succeeds(tmp_path: Path) -> None:
    manager, robot = build_manager(
        tmp_path / "tool.db",
        {
            "get_robot_status": [
                result(False, "temporary service failure", "tool_error"),
                result(True, "status available"),
            ]
        },
    )
    task = manager.create_task(
        "read status",
        [TaskStepSpec(action="get_robot_status")],
    )

    completed = await manager.execute_task(task.id)

    assert completed.status is TaskStatus.COMPLETED
    assert completed.steps[0].attempt_count == 2
    assert robot.executed_actions == ["get_robot_status", "get_robot_status"]


@pytest.mark.asyncio
async def test_invalid_parameters_fail_without_retry(tmp_path: Path) -> None:
    manager, robot = build_manager(
        tmp_path / "invalid.db",
        {
            "navigate_to": [
                result(False, "coordinate schema rejected", "invalid_parameters")
            ]
        },
    )
    task = manager.create_task(
        "invalid goal",
        [TaskStepSpec(action="navigate_to")],
    )

    failed = await manager.execute_task(task.id)

    assert failed.status is TaskStatus.FAILED
    assert failed.steps[0].status is StepStatus.FAILED
    assert failed.steps[0].attempt_count == 1
    assert robot.executed_actions == ["navigate_to"]


@pytest.mark.asyncio
async def test_perception_failure_has_bounded_retry(tmp_path: Path) -> None:
    manager, robot = build_manager(
        tmp_path / "perception.db",
        {
            "detect_objects": [
                result(False, "camera frame unavailable", "detection_failed"),
                result(True, "objects detected"),
            ]
        },
    )
    task = manager.create_task(
        "detect chairs",
        [TaskStepSpec(action="detect_objects")],
    )

    completed = await manager.execute_task(task.id)

    assert completed.status is TaskStatus.COMPLETED
    assert completed.steps[0].attempt_count == 2
    assert robot.executed_actions == ["detect_objects", "detect_objects"]


@pytest.mark.asyncio
async def test_repeated_failures_stop_and_require_confirmed_human_resume(
    tmp_path: Path,
) -> None:
    manager, robot = build_manager(
        tmp_path / "human.db",
        {
            "navigate_to": [
                result(False, "service down", "tool_error"),
                result(False, "service down", "tool_error"),
                result(False, "service down", "tool_error"),
                result(True, "human cleared the fault"),
            ]
        },
    )
    task = manager.create_task(
        "requires intervention",
        [TaskStepSpec(action="navigate_to")],
    )

    waiting = await manager.execute_task(task.id)

    assert waiting.status is TaskStatus.WAITING_FOR_HUMAN
    assert waiting.human_intervention_required is True
    assert waiting.steps[0].attempt_count == 3
    with pytest.raises(InvalidTaskStateError, match="resume_after_human"):
        await manager.execute_task(task.id)
    with pytest.raises(InvalidTaskStateError, match="Robot state must be confirmed"):
        await manager.resume_after_human(
            task.id,
            robot_state_confirmed=False,
            environment_confirmed=True,
        )

    completed = await manager.resume_after_human(
        task.id,
        robot_state_confirmed=True,
        environment_confirmed=True,
    )
    events = manager.get_events(task.id)

    assert completed.status is TaskStatus.COMPLETED
    assert robot.executed_actions == ["navigate_to"] * 4
    assert any(
        event.event_type is EventType.HUMAN_HELP_REQUESTED for event in events
    )
    assert any(
        event.event_type is EventType.HUMAN_HELP_ACKNOWLEDGED for event in events
    )


@pytest.mark.asyncio
async def test_total_failure_limit_stops_cross_step_recovery(tmp_path: Path) -> None:
    manager, _ = build_manager(
        tmp_path / "total-limit.db",
        {
            "first": [
                result(False, "temporary", "tool_error"),
                result(True, "recovered"),
            ],
            "second": [result(False, "temporary", "tool_error")],
        },
        config=RecoveryConfig(max_attempts_per_step=3, max_failures_per_task=2),
    )
    task = manager.create_task(
        "bounded total failures",
        [TaskStepSpec(action="first"), TaskStepSpec(action="second")],
    )

    waiting = await manager.execute_task(task.id)

    assert waiting.status is TaskStatus.WAITING_FOR_HUMAN
    assert waiting.failure_count == 2
    assert waiting.current_step_index == 1


@pytest.mark.asyncio
async def test_execution_feedback_is_persisted(tmp_path: Path) -> None:
    class FeedbackRobot(FakeRobotAdapter):
        def get_execution_feedback(self) -> dict[str, object]:
            return {"distance_remaining": 0.75, "number_of_recoveries": 1}

    robot = FeedbackRobot(delay_seconds=0.03)
    manager = MissionManager(
        SQLiteTaskRepository(tmp_path / "feedback.db"),
        robot,
        feedback_poll_interval=0.005,
    )
    task = manager.create_task(
        "monitor navigation",
        [TaskStepSpec(action="navigate_to")],
    )

    completed = await manager.execute_task(task.id)
    events = manager.get_events(task.id)

    assert completed.status is TaskStatus.COMPLETED
    feedback_events = [
        event for event in events if event.event_type is EventType.NAVIGATION_FEEDBACK
    ]
    assert len(feedback_events) == 1
    assert feedback_events[0].payload["feedback"]["distance_remaining"] == 0.75
