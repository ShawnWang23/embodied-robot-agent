from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from robot_agent.adapters.fake_robot import FakeRobotAdapter
from robot_agent.agent.graph import AgentRunner, build_agent_graph
from robot_agent.agent.locations import LocationCatalog
from robot_agent.agent.planner import RuleBasedPlanner
from robot_agent.agent.tools import ToolRegistry
from robot_agent.api.runtime import AgentRuntime
from robot_agent.api.server import create_app
from robot_agent.mission.manager import MissionManager
from robot_agent.storage.sqlite import SQLiteTaskRepository


def runtime_builder(task_database: Path, *, delay_seconds: float = 0.0):
    def build(checkpointer: object) -> AgentRuntime:
        locations = LocationCatalog.from_json(Path("config/locations.json"))
        manager = MissionManager(
            SQLiteTaskRepository(task_database),
            FakeRobotAdapter(delay_seconds=delay_seconds),
        )
        runner = AgentRunner(
            build_agent_graph(
                RuleBasedPlanner(locations),
                ToolRegistry(locations),
                manager,
                checkpointer=checkpointer,
            )
        )
        return AgentRuntime(runner, manager)

    return build


def wait_for_status(
    client: TestClient,
    thread_id: str,
    expected: set[str],
    *,
    timeout: float = 3.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/tasks/{thread_id}")
        if response.status_code == 200:
            last = response.json()
            if last["agent_status"] in expected:
                return last
        time.sleep(0.01)
    raise AssertionError(f"Thread did not reach {expected}; last response: {last}")


def test_api_executes_and_reads_persistent_task(tmp_path: Path) -> None:
    task_database = tmp_path / "tasks.db"
    checkpoint_database = tmp_path / "checkpoints.db"
    builder = runtime_builder(task_database)

    with TestClient(
        create_app(
            checkpoint_path=checkpoint_database,
            runtime_builder=builder,
        )
    ) as client:
        health = client.get("/health")
        assert health.json() == {"status": "ok", "reconciled_tasks": 0}

        accepted = client.post(
            "/tasks",
            json={
                "thread_id": "api-persistent-thread",
                "instruction": "去实验室门口检查是否有人",
            },
        )
        assert accepted.status_code == 202
        settled = wait_for_status(
            client,
            "api-persistent-thread",
            {"completed"},
        )
        assert settled["perception_outcome"] == "clear"
        assert settled["task"]["context"]["agent_thread_id"] == (
            "api-persistent-thread"
        )

        events = client.get("/tasks/api-persistent-thread/events")
        checkpoints = client.get("/tasks/api-persistent-thread/checkpoints")
        assert events.status_code == 200
        assert any(
            event["event_type"] == "task_completed"
            for event in events.json()["events"]
        )
        assert checkpoints.status_code == 200
        assert len(checkpoints.json()["checkpoints"]) >= 5

    with TestClient(
        create_app(
            checkpoint_path=checkpoint_database,
            runtime_builder=builder,
        )
    ) as restarted_client:
        restored = restarted_client.get("/tasks/api-persistent-thread")
        assert restored.status_code == 200
        assert restored.json()["agent_status"] == "completed"


def test_api_human_takeover_requires_safe_resume_confirmation(tmp_path: Path) -> None:
    app = create_app(
        checkpoint_path=tmp_path / "checkpoints.db",
        runtime_builder=runtime_builder(
            tmp_path / "tasks.db",
            delay_seconds=0.3,
        ),
    )

    with TestClient(app) as client:
        accepted = client.post(
            "/tasks",
            json={
                "thread_id": "takeover-thread",
                "instruction": "去实验室门口",
            },
        )
        assert accepted.status_code == 202
        wait_for_status(client, "takeover-thread", {"running"})

        takeover = client.post(
            "/tasks/takeover-thread/human-help",
            json={"reason": "走廊出现临时障碍物"},
        )
        assert takeover.status_code == 200
        assert takeover.json()["agent_status"] == "waiting_for_human"

        unsafe_resume = client.post(
            "/tasks/takeover-thread/resume",
            json={
                "robot_state_confirmed": True,
                "environment_confirmed": False,
            },
        )
        assert unsafe_resume.status_code == 409
        assert "Environment state" in unsafe_resume.json()["detail"]

        safe_resume = client.post(
            "/tasks/takeover-thread/resume",
            json={
                "robot_state_confirmed": True,
                "environment_confirmed": True,
            },
        )
        assert safe_resume.status_code == 200
        assert safe_resume.json()["agent_status"] == "completed"


def test_api_restart_reconciles_interrupted_execution(tmp_path: Path) -> None:
    task_database = tmp_path / "tasks.db"
    checkpoint_database = tmp_path / "checkpoints.db"
    slow_app = create_app(
        checkpoint_path=checkpoint_database,
        runtime_builder=runtime_builder(task_database, delay_seconds=2.0),
    )

    with TestClient(slow_app) as client:
        accepted = client.post(
            "/tasks",
            json={
                "thread_id": "restart-thread",
                "instruction": "去实验室门口",
            },
        )
        assert accepted.status_code == 202
        wait_for_status(client, "restart-thread", {"running"})

    restarted_app = create_app(
        checkpoint_path=checkpoint_database,
        runtime_builder=runtime_builder(task_database),
    )
    with TestClient(restarted_app) as client:
        health = client.get("/health")
        assert health.json() == {"status": "ok", "reconciled_tasks": 1}

        recovered = client.get("/tasks/restart-thread")
        assert recovered.status_code == 200
        assert recovered.json()["agent_status"] == "waiting_for_human"
        assert recovered.json()["task"]["steps"][0]["status"] == "pending"

        checkpoint = client.get("/tasks/restart-thread/checkpoints").json()
        assert checkpoint["checkpoints"][0]["status"] == "waiting_for_human"

        rejected = client.post(
            "/tasks/restart-thread/resume",
            json={
                "robot_state_confirmed": True,
                "environment_confirmed": False,
            },
        )
        assert rejected.status_code == 409

        resumed = client.post(
            "/tasks/restart-thread/resume",
            json={
                "robot_state_confirmed": True,
                "environment_confirmed": True,
            },
        )
        assert resumed.status_code == 200
        assert resumed.json()["agent_status"] == "completed"


def test_api_rejects_unknown_thread_and_duplicate_active_thread(tmp_path: Path) -> None:
    app = create_app(
        checkpoint_path=tmp_path / "checkpoints.db",
        runtime_builder=runtime_builder(
            tmp_path / "tasks.db",
            delay_seconds=0.3,
        ),
    )

    with TestClient(app) as client:
        assert client.get("/tasks/missing").status_code == 404
        first = client.post(
            "/tasks",
            json={"thread_id": "duplicate", "instruction": "去会议室"},
        )
        second = client.post(
            "/tasks",
            json={"thread_id": "duplicate", "instruction": "返回起点"},
        )
        concurrent = client.post(
            "/tasks",
            json={"thread_id": "another", "instruction": "返回起点"},
        )
        assert first.status_code == 202
        assert second.status_code == 409
        assert concurrent.status_code == 409
        wait_for_status(client, "duplicate", {"running"})
        cancelled = client.post("/tasks/duplicate/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["agent_status"] == "cancelled"
