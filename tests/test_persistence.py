from __future__ import annotations

from pathlib import Path

import pytest

from robot_agent.adapters.fake_robot import FakeRobotAdapter
from robot_agent.agent.graph import AgentRunner, build_agent_graph
from robot_agent.agent.locations import LocationCatalog
from robot_agent.agent.memory import open_sqlite_checkpointer
from robot_agent.agent.planner import RuleBasedPlanner
from robot_agent.agent.tools import ToolRegistry
from robot_agent.core.exceptions import InvalidTaskStateError
from robot_agent.core.models import EventType, StepStatus, TaskStatus, TaskStepSpec
from robot_agent.mission.fsm import transition_step, transition_task
from robot_agent.mission.manager import MissionManager
from robot_agent.storage.sqlite import SQLiteTaskRepository


def build_runner(
    task_database: Path,
    checkpointer: object,
) -> tuple[AgentRunner, MissionManager]:
    locations = LocationCatalog.from_json(Path("config/locations.json"))
    manager = MissionManager(
        SQLiteTaskRepository(task_database),
        FakeRobotAdapter(),
    )
    graph = build_agent_graph(
        RuleBasedPlanner(locations),
        ToolRegistry(locations),
        manager,
        checkpointer=checkpointer,
    )
    return AgentRunner(graph), manager


async def test_sqlite_checkpoint_survives_process_reopen(tmp_path: Path) -> None:
    task_database = tmp_path / "tasks.db"
    checkpoint_database = tmp_path / "checkpoints.db"

    async with open_sqlite_checkpointer(checkpoint_database) as checkpointer:
        runner, _ = build_runner(task_database, checkpointer)
        result = await runner.run(
            "请先去实验室门口，然后去会议室，最后返回起点",
            thread_id="persistent-thread",
        )
        assert result.status == "completed"
        original_task_id = result.task["id"]

    async with open_sqlite_checkpointer(checkpoint_database) as checkpointer:
        restored_runner, restored_manager = build_runner(task_database, checkpointer)
        restored = await restored_runner.get_state("persistent-thread")
        history = await restored_runner.get_history("persistent-thread")

        assert restored["status"] == "completed"
        assert restored["task_id"] == original_task_id
        assert restored["task"]["context"]["agent_thread_id"] == "persistent-thread"
        assert restored_manager.get_task(original_task_id).status is TaskStatus.COMPLETED
        assert len(history) >= 5


async def test_restart_quarantines_running_task_until_double_confirmation(
    tmp_path: Path,
) -> None:
    repository = SQLiteTaskRepository(tmp_path / "tasks.db")
    original_manager = MissionManager(repository, FakeRobotAdapter())
    created = original_manager.create_task(
        "Interrupted navigation",
        [TaskStepSpec(action="navigate_to", parameters={"location": "start"})],
        context={"agent_thread_id": "restart-thread"},
    )

    interrupted = original_manager.get_task(created.id)
    transition_task(interrupted, TaskStatus.RUNNING)
    transition_step(interrupted.steps[0], StepStatus.RUNNING)
    interrupted.steps[0].attempt_count = 1
    repository.save(interrupted)

    restarted_manager = MissionManager(repository, FakeRobotAdapter())
    reconciled = restarted_manager.reconcile_interrupted_tasks()
    recovered = restarted_manager.get_task(created.id)

    assert [task.id for task in reconciled] == [created.id]
    assert recovered.status is TaskStatus.WAITING_FOR_HUMAN
    assert recovered.steps[0].status is StepStatus.PENDING
    assert recovered.human_intervention_required is True
    event_types = [event.event_type for event in restarted_manager.get_events(created.id)]
    assert EventType.PROCESS_INTERRUPTED in event_types
    assert EventType.HUMAN_HELP_REQUESTED in event_types

    with pytest.raises(InvalidTaskStateError, match="resume_after_human"):
        await restarted_manager.execute_task(created.id)

    with pytest.raises(InvalidTaskStateError, match="Environment state"):
        await restarted_manager.resume_after_human(
            created.id,
            robot_state_confirmed=True,
            environment_confirmed=False,
        )

    completed = await restarted_manager.resume_after_human(
        created.id,
        robot_state_confirmed=True,
        environment_confirmed=True,
    )
    assert completed.status is TaskStatus.COMPLETED
    assert completed.steps[0].attempt_count == 2

