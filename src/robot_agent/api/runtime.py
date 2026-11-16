"""In-process Agent runtime shared by FastAPI endpoints."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from robot_agent.agent.graph import AgentRunner
from robot_agent.api.models import AgentTaskView
from robot_agent.core.exceptions import InvalidTaskStateError, TaskNotFoundError
from robot_agent.core.models import Task
from robot_agent.mission.manager import MissionManager


class AgentRuntime:
    """Own background graph runs while MissionManager remains authoritative."""

    def __init__(self, runner: AgentRunner, manager: MissionManager) -> None:
        self.runner = runner
        self.manager = manager
        self._runs: dict[str, asyncio.Task[Any]] = {}
        self._background_errors: dict[str, str] = {}

    def submit(self, instruction: str, *, thread_id: str | None = None) -> str:
        resolved = thread_id or str(uuid4())
        active_thread = next(
            (
                active_id
                for active_id, run in self._runs.items()
                if not run.done()
            ),
            None,
        )
        if active_thread is not None:
            if active_thread == resolved:
                raise InvalidTaskStateError(f"Thread '{resolved}' is already running")
            raise InvalidTaskStateError(
                f"Thread '{active_thread}' is already using the single-robot runtime"
            )
        if self.manager.active_task_id is not None:
            raise InvalidTaskStateError(
                f"Task '{self.manager.active_task_id}' is already using the robot"
            )
        run = asyncio.create_task(
            self.runner.run(instruction, thread_id=resolved),
            name=f"agent-{resolved}",
        )
        self._runs[resolved] = run
        run.add_done_callback(lambda completed: self._capture_error(resolved, completed))
        return resolved

    async def view(self, thread_id: str) -> AgentTaskView:
        state = await self.runner.get_state(thread_id)
        active = self._runs.get(thread_id)
        if not state:
            if active is not None and not active.done():
                return AgentTaskView(thread_id=thread_id, agent_status="planning")
            raise TaskNotFoundError(f"Agent thread '{thread_id}' was not found")

        task: Task | None = None
        task_id = state.get("task_id")
        if task_id:
            task = self.manager.get_task(task_id)
        errors = list(state.get("errors", []))
        background_error = self._background_errors.get(thread_id)
        if background_error:
            errors.append(background_error)
        perception_outcome = state.get("perception_outcome")
        if perception_outcome is None and task is not None:
            perception_outcome = _perception_outcome(task)
        return AgentTaskView(
            thread_id=thread_id,
            agent_status=(
                state["status"]
                if state.get("status") == "failed"
                else task.status.value
                if task is not None
                else state["status"]
            ),
            task=task.model_dump(mode="json") if task is not None else None,
            errors=errors,
            perception_outcome=perception_outcome,
            goal_satisfied=state.get("goal_satisfied"),
            completion_reason=state.get("completion_reason"),
            replan_count=state.get("replan_count", 0),
            executed_step_count=state.get("executed_step_count", 0),
            task_history=state.get("task_history", []),
        )

    async def pause(self, thread_id: str) -> Task:
        task = await self._require_task(thread_id)
        settled = await self.manager.pause_task(task.id)
        await self.runner.update_task_state(thread_id, settled)
        return settled

    async def cancel(self, thread_id: str) -> Task:
        task = await self._require_task(thread_id)
        settled = await self.manager.cancel_task(task.id)
        await self.runner.update_task_state(thread_id, settled)
        return settled

    async def request_human(self, thread_id: str, reason: str) -> Task:
        task = await self._require_task(thread_id)
        settled = await self.manager.request_human_takeover(task.id, reason)
        await self.runner.update_task_state(thread_id, settled)
        return settled

    async def resume(
        self,
        thread_id: str,
        *,
        robot_state_confirmed: bool,
        environment_confirmed: bool,
    ) -> Task:
        task = await self._require_task(thread_id)
        if task.status.value == "paused":
            settled = await self.manager.resume_task(task.id)
        else:
            settled = await self.manager.resume_after_human(
                task.id,
                robot_state_confirmed=robot_state_confirmed,
                environment_confirmed=environment_confirmed,
            )
        await self.runner.update_task_state(thread_id, settled)
        return settled

    async def events(self, thread_id: str) -> list[dict[str, Any]]:
        task = await self._require_task(thread_id)
        return [event.model_dump(mode="json") for event in self.manager.get_events(task.id)]

    async def shutdown(self) -> None:
        active = [run for run in self._runs.values() if not run.done()]
        for run in active:
            run.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)

    async def _require_task(self, thread_id: str) -> Task:
        state = await self.runner.get_state(thread_id)
        task_id = state.get("task_id") if state else None
        if task_id is None:
            raise InvalidTaskStateError(
                f"Thread '{thread_id}' has not created an executable task yet"
            )
        return self.manager.get_task(task_id)

    def _capture_error(self, thread_id: str, completed: asyncio.Task[Any]) -> None:
        if completed.cancelled():
            return
        exception = completed.exception()
        if exception is not None:
            self._background_errors[thread_id] = str(exception)


def _perception_outcome(task: Task) -> str | None:
    results = [
        step.result
        for step in task.steps
        if step.action == "detect_objects" and isinstance(step.result, dict)
    ]
    if not results:
        return None
    detected = any(
        any(result.get("target_presence", {}).values()) for result in results
    )
    return "objects_detected" if detected else "clear"

