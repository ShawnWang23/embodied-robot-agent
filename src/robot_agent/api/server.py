"""FastAPI application for persistent Agent task control."""

from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status

from robot_agent.adapters.fake_robot import FakeRobotAdapter
from robot_agent.agent.graph import AgentRunner, build_agent_graph
from robot_agent.agent.locations import LocationCatalog
from robot_agent.agent.memory import open_sqlite_checkpointer
from robot_agent.agent.planner import (
    OpenAIPlanner,
    RuleBasedPlanner,
    SiliconFlowPlanner,
)
from robot_agent.agent.replanning import (
    ExecutionBudget,
    PerceptionFallbackReplanner,
)
from robot_agent.agent.tools import ToolRegistry
from robot_agent.api.models import (
    AgentTaskView,
    CheckpointHistoryView,
    HumanTakeoverRequest,
    ResumeTaskRequest,
    SubmitTaskRequest,
    TaskAccepted,
    TaskEventsView,
)
from robot_agent.api.runtime import AgentRuntime
from robot_agent.core.exceptions import InvalidTaskStateError, TaskNotFoundError
from robot_agent.mission.manager import MissionManager
from robot_agent.storage.sqlite import SQLiteTaskRepository

RuntimeBuilder = Callable[[Any], AgentRuntime]


def build_default_runtime(checkpointer: Any) -> AgentRuntime:
    locations = LocationCatalog.from_json(
        os.getenv("ROBOT_AGENT_LOCATIONS", "config/locations.json")
    )
    tools = ToolRegistry(locations)
    planner_name = os.getenv("ROBOT_AGENT_PLANNER", "rule").strip().lower()
    if planner_name == "openai":
        planner = OpenAIPlanner(locations, tools)
    elif planner_name == "siliconflow":
        planner = SiliconFlowPlanner(locations, tools)
    elif planner_name == "rule":
        planner = RuleBasedPlanner(locations)
    else:
        raise ValueError(
            "ROBOT_AGENT_PLANNER must be one of: rule, openai, siliconflow"
        )
    manager = MissionManager(
        SQLiteTaskRepository(
            os.getenv("ROBOT_AGENT_TASK_DB", "data/api_tasks.db")
        ),
        FakeRobotAdapter(delay_seconds=0.05),
    )
    runner = AgentRunner(
        build_agent_graph(
            planner,
            tools,
            manager,
            checkpointer=checkpointer,
            replanner=PerceptionFallbackReplanner(
                os.getenv(
                    "ROBOT_AGENT_REPLAN_LOCATION",
                    "corridor_observation",
                )
            ),
            budget=ExecutionBudget(
                max_replans=int(os.getenv("ROBOT_AGENT_MAX_REPLANS", "1")),
                max_total_steps=int(
                    os.getenv("ROBOT_AGENT_MAX_TOTAL_STEPS", "12")
                ),
            ),
        )
    )
    return AgentRuntime(runner, manager)


def create_app(
    *,
    checkpoint_path: str | Path | None = None,
    runtime_builder: RuntimeBuilder = build_default_runtime,
) -> FastAPI:
    resolved_checkpoint = Path(
        checkpoint_path
        or os.getenv("ROBOT_AGENT_CHECKPOINT_DB", "data/checkpoints.db")
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with open_sqlite_checkpointer(resolved_checkpoint) as checkpointer:
            runtime = runtime_builder(checkpointer)
            app.state.runtime = runtime
            reconciled_tasks = runtime.manager.reconcile_interrupted_tasks()
            for task in reconciled_tasks:
                thread_id = task.context.get("agent_thread_id")
                if isinstance(thread_id, str) and thread_id:
                    await runtime.runner.update_task_state(thread_id, task)
            app.state.reconciled_tasks = reconciled_tasks
            try:
                yield
            finally:
                await runtime.shutdown()

    app = FastAPI(
        title="Robot Agent API",
        version="0.1.0",
        lifespan=lifespan,
    )

    def runtime(request: Request) -> AgentRuntime:
        return request.app.state.runtime

    @app.get("/health")
    async def health(request: Request) -> dict[str, object]:
        return {
            "status": "ok",
            "reconciled_tasks": len(request.app.state.reconciled_tasks),
        }

    @app.post(
        "/tasks",
        response_model=TaskAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def submit_task(payload: SubmitTaskRequest, request: Request) -> TaskAccepted:
        try:
            thread_id = runtime(request).submit(
                payload.instruction,
                thread_id=payload.thread_id,
            )
        except InvalidTaskStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return TaskAccepted(thread_id=thread_id, status="accepted")

    @app.get("/tasks/{thread_id}", response_model=AgentTaskView)
    async def get_task(thread_id: str, request: Request) -> AgentTaskView:
        try:
            return await runtime(request).view(thread_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/tasks/{thread_id}/pause", response_model=AgentTaskView)
    async def pause_task(thread_id: str, request: Request) -> AgentTaskView:
        await _control(runtime(request).pause(thread_id))
        return await runtime(request).view(thread_id)

    @app.post("/tasks/{thread_id}/cancel", response_model=AgentTaskView)
    async def cancel_task(thread_id: str, request: Request) -> AgentTaskView:
        await _control(runtime(request).cancel(thread_id))
        return await runtime(request).view(thread_id)

    @app.post("/tasks/{thread_id}/human-help", response_model=AgentTaskView)
    async def request_human_help(
        thread_id: str,
        payload: HumanTakeoverRequest,
        request: Request,
    ) -> AgentTaskView:
        await _control(runtime(request).request_human(thread_id, payload.reason))
        return await runtime(request).view(thread_id)

    @app.post("/tasks/{thread_id}/resume", response_model=AgentTaskView)
    async def resume_task(
        thread_id: str,
        payload: ResumeTaskRequest,
        request: Request,
    ) -> AgentTaskView:
        await _control(
            runtime(request).resume(
                thread_id,
                robot_state_confirmed=payload.robot_state_confirmed,
                environment_confirmed=payload.environment_confirmed,
            )
        )
        return await runtime(request).view(thread_id)

    @app.get("/tasks/{thread_id}/events", response_model=TaskEventsView)
    async def get_events(thread_id: str, request: Request) -> TaskEventsView:
        events = await _control(runtime(request).events(thread_id))
        return TaskEventsView(thread_id=thread_id, events=events)

    @app.get("/tasks/{thread_id}/checkpoints", response_model=CheckpointHistoryView)
    async def get_checkpoints(
        thread_id: str,
        request: Request,
    ) -> CheckpointHistoryView:
        checkpoints = await runtime(request).runner.get_history(thread_id)
        if not checkpoints:
            raise HTTPException(status_code=404, detail="Agent thread was not found")
        return CheckpointHistoryView(thread_id=thread_id, checkpoints=checkpoints)

    return app


async def _control(operation: Any) -> Any:
    try:
        return await operation
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (InvalidTaskStateError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "robot_agent.api.server:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )

