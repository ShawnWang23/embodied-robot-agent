import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from robot_agent.adapters.fake_robot import FakeRobotAdapter
from robot_agent.core.exceptions import InvalidTaskStateError
from robot_agent.core.models import EventType, StepStatus, TaskStatus, TaskStepSpec
from robot_agent.mission.manager import MissionManager
from robot_agent.storage.sqlite import SQLiteTaskRepository


def build_manager(
    database_path: Path,
    *,
    failures: dict[str, str] | None = None,
    delay_seconds: float = 0.0,
) -> tuple[MissionManager, FakeRobotAdapter]:
    robot = FakeRobotAdapter(
        delay_seconds=delay_seconds,
        failures=failures,
    )
    repository = SQLiteTaskRepository(database_path)
    return MissionManager(repository, robot), robot


async def wait_until_executing(robot: FakeRobotAdapter) -> None:
    for _ in range(100):
        if robot.is_executing:
            return
        await asyncio.sleep(0.005)
    pytest.fail("Fake robot did not start executing in time")


def test_create_and_query_task(tmp_path: Path) -> None:
    manager, _ = build_manager(tmp_path / "tasks.db")

    created = manager.create_task(
        "Go to the lab",
        [TaskStepSpec(action="navigate_to", parameters={"location": "lab"})],
    )
    loaded = manager.get_task(created.id)

    assert loaded == created
    assert loaded.status is TaskStatus.PENDING
    assert loaded.steps[0].status is StepStatus.PENDING


@pytest.mark.asyncio
async def test_execute_multi_step_task_successfully(tmp_path: Path) -> None:
    manager, robot = build_manager(tmp_path / "tasks.db")
    created = manager.create_task(
        "Inspect the lab and return",
        [
            TaskStepSpec(action="navigate_to", parameters={"location": "lab"}),
            TaskStepSpec(action="inspect", parameters={"target": "person"}),
            TaskStepSpec(action="navigate_to", parameters={"location": "start"}),
        ],
    )

    completed = await manager.execute_task(created.id)
    reloaded = manager.get_task(created.id)

    assert completed.status is TaskStatus.COMPLETED
    assert completed.current_step_index == 3
    assert all(step.status is StepStatus.COMPLETED for step in completed.steps)
    assert robot.executed_actions == ["navigate_to", "inspect", "navigate_to"]
    assert reloaded == completed


@pytest.mark.asyncio
async def test_failure_stops_remaining_steps_and_is_persisted(tmp_path: Path) -> None:
    manager, robot = build_manager(
        tmp_path / "tasks.db",
        failures={"inspect": "camera unavailable"},
    )
    created = manager.create_task(
        "Inspect and return",
        [
            TaskStepSpec(action="navigate_to"),
            TaskStepSpec(action="inspect"),
            TaskStepSpec(action="navigate_home"),
        ],
    )

    failed = await manager.execute_task(created.id)
    reloaded = manager.get_task(created.id)

    assert failed.status is TaskStatus.FAILED
    assert failed.steps[0].status is StepStatus.COMPLETED
    assert failed.steps[1].status is StepStatus.FAILED
    assert failed.steps[1].error == "camera unavailable"
    assert failed.steps[2].status is StepStatus.PENDING
    assert robot.executed_actions == ["navigate_to", "inspect"]
    assert reloaded == failed


def test_invalid_empty_action_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TaskStepSpec(action="")


@pytest.mark.asyncio
async def test_pause_then_resume_retries_interrupted_step(tmp_path: Path) -> None:
    manager, robot = build_manager(
        tmp_path / "tasks.db",
        delay_seconds=0.05,
    )
    created = manager.create_task(
        "Pauseable inspection",
        [
            TaskStepSpec(action="navigate_to"),
            TaskStepSpec(action="inspect"),
        ],
    )

    execution = asyncio.create_task(manager.execute_task(created.id))
    await wait_until_executing(robot)
    paused = await manager.pause_task(created.id)
    execution_result = await execution

    assert paused.status is TaskStatus.PAUSED
    assert execution_result.status is TaskStatus.PAUSED
    assert paused.current_step_index == 0
    assert paused.steps[0].status is StepStatus.PENDING

    completed = await manager.resume_task(created.id)
    event_types = [event.event_type for event in manager.get_events(created.id)]

    assert completed.status is TaskStatus.COMPLETED
    assert robot.executed_actions == ["navigate_to", "navigate_to", "inspect"]
    assert EventType.PAUSE_REQUESTED in event_types
    assert EventType.STEP_INTERRUPTED in event_types
    assert EventType.TASK_PAUSED in event_types
    assert EventType.TASK_RESUMED in event_types


@pytest.mark.asyncio
async def test_cancel_running_task_stops_current_and_future_steps(
    tmp_path: Path,
) -> None:
    manager, robot = build_manager(
        tmp_path / "tasks.db",
        delay_seconds=0.1,
    )
    created = manager.create_task(
        "Cancelable inspection",
        [
            TaskStepSpec(action="navigate_to"),
            TaskStepSpec(action="inspect"),
        ],
    )

    execution = asyncio.create_task(manager.execute_task(created.id))
    await wait_until_executing(robot)
    cancelled = await manager.cancel_task(created.id)
    execution_result = await execution

    assert cancelled.status is TaskStatus.CANCELLED
    assert execution_result.status is TaskStatus.CANCELLED
    assert all(step.status is StepStatus.CANCELLED for step in cancelled.steps)
    assert robot.executed_actions == ["navigate_to"]


@pytest.mark.asyncio
async def test_cancel_pending_task_without_using_robot(tmp_path: Path) -> None:
    manager, robot = build_manager(tmp_path / "tasks.db")
    created = manager.create_task(
        "Never started",
        [TaskStepSpec(action="navigate_to")],
    )

    cancelled = await manager.cancel_task(created.id)

    assert cancelled.status is TaskStatus.CANCELLED
    assert cancelled.steps[0].status is StepStatus.CANCELLED
    assert robot.executed_actions == []


@pytest.mark.asyncio
async def test_step_timeout_retries_then_requests_human(tmp_path: Path) -> None:
    manager, _ = build_manager(
        tmp_path / "tasks.db",
        delay_seconds=0.1,
    )
    created = manager.create_task(
        "Timeout example",
        [TaskStepSpec(action="navigate_to", timeout_seconds=0.01)],
    )

    waiting = await manager.execute_task(created.id)
    events = manager.get_events(created.id)

    assert waiting.status is TaskStatus.WAITING_FOR_HUMAN
    assert waiting.steps[0].status is StepStatus.PENDING
    assert waiting.steps[0].attempt_count == 3
    assert len(waiting.steps[0].failure_history) == 3
    assert "timed out" in (waiting.steps[0].error or "")
    assert any(event.event_type is EventType.STEP_TIMED_OUT for event in events)
    assert any(event.event_type is EventType.HUMAN_HELP_REQUESTED for event in events)


@pytest.mark.asyncio
async def test_completed_task_cannot_execute_again(tmp_path: Path) -> None:
    manager, _ = build_manager(tmp_path / "tasks.db")
    created = manager.create_task(
        "Run once",
        [TaskStepSpec(action="inspect")],
    )
    await manager.execute_task(created.id)

    with pytest.raises(InvalidTaskStateError):
        await manager.execute_task(created.id)


@pytest.mark.asyncio
async def test_only_one_task_can_use_robot_at_a_time(tmp_path: Path) -> None:
    manager, robot = build_manager(
        tmp_path / "tasks.db",
        delay_seconds=0.1,
    )
    first = manager.create_task(
        "First task",
        [TaskStepSpec(action="navigate_to")],
    )
    second = manager.create_task(
        "Second task",
        [TaskStepSpec(action="inspect")],
    )

    first_execution = asyncio.create_task(manager.execute_task(first.id))
    await wait_until_executing(robot)

    with pytest.raises(InvalidTaskStateError, match="already using the robot"):
        await manager.execute_task(second.id)

    await manager.cancel_task(first.id)
    await first_execution

    assert manager.get_task(second.id).status is TaskStatus.PENDING

