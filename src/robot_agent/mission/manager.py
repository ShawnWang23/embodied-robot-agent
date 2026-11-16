"""Orchestrate validated tasks without depending on a concrete robot."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, field

from robot_agent.core.exceptions import InvalidTaskStateError, TaskNotFoundError
from robot_agent.core.interfaces import RobotAdapter
from robot_agent.core.models import (
    EventLevel,
    EventType,
    RobotActionResult,
    StepFailure,
    StepStatus,
    Task,
    TaskEvent,
    TaskStatus,
    TaskStep,
    TaskStepSpec,
    utc_now,
)
from robot_agent.mission.fsm import transition_step, transition_task
from robot_agent.mission.recovery import (
    RecoveryAction,
    RecoveryDecision,
    RecoveryPolicy,
)
from robot_agent.storage.sqlite import SQLiteTaskRepository

logger = logging.getLogger(__name__)


@dataclass
class _ExecutionControl:
    pause_requested: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_requested: asyncio.Event = field(default_factory=asyncio.Event)
    settled: asyncio.Event = field(default_factory=asyncio.Event)


class MissionManager:
    """Create, query, and sequentially execute multi-step tasks."""

    def __init__(
        self,
        repository: SQLiteTaskRepository,
        robot: RobotAdapter,
        *,
        recovery_policy: RecoveryPolicy | None = None,
        feedback_poll_interval: float = 0.5,
    ) -> None:
        if feedback_poll_interval <= 0:
            raise ValueError("feedback_poll_interval must be positive")
        self._repository = repository
        self._robot = robot
        self._recovery = recovery_policy or RecoveryPolicy()
        self._feedback_poll_interval = feedback_poll_interval
        self._active_task_id: str | None = None
        self._controls: dict[str, _ExecutionControl] = {}

    @property
    def active_task_id(self) -> str | None:
        """Return the task currently holding the single-robot execution slot."""

        return self._active_task_id

    def create_task(
        self,
        description: str,
        step_specs: Sequence[TaskStepSpec],
        *,
        context: dict[str, object] | None = None,
    ) -> Task:
        steps = [
            TaskStep(position=index, **spec.model_dump())
            for index, spec in enumerate(step_specs)
        ]
        task = Task(description=description, steps=steps, context=context or {})
        self._repository.save(task)
        self._record_event(
            task,
            EventType.TASK_CREATED,
            f"Task created with {len(task.steps)} steps",
            payload={"step_count": len(task.steps)},
        )
        logger.info("Created task %s with %d steps", task.id, len(task.steps))
        return task

    def get_task(self, task_id: str) -> Task:
        task = self._repository.get(task_id)
        if task is None:
            raise TaskNotFoundError(f"Task '{task_id}' was not found")
        return task

    def get_events(self, task_id: str) -> list[TaskEvent]:
        self.get_task(task_id)
        return self._repository.list_events(task_id)

    async def execute_task(
        self,
        task_id: str,
        *,
        _human_state_confirmed: bool = False,
    ) -> Task:
        task = self.get_task(task_id)
        if task.status not in {
            TaskStatus.PENDING,
            TaskStatus.PAUSED,
            TaskStatus.WAITING_FOR_HUMAN,
        }:
            raise InvalidTaskStateError(
                f"Task '{task.id}' cannot start from state '{task.status.value}'"
            )
        if (
            task.status is TaskStatus.WAITING_FOR_HUMAN
            and not _human_state_confirmed
        ):
            raise InvalidTaskStateError(
                "Use resume_after_human and confirm robot state before resuming"
            )
        if self._active_task_id is not None:
            raise InvalidTaskStateError(
                f"Task '{self._active_task_id}' is already using the robot"
            )

        was_resumed = task.status in {
            TaskStatus.PAUSED,
            TaskStatus.WAITING_FOR_HUMAN,
        }
        transition_task(task, TaskStatus.RUNNING)
        task.human_intervention_required = False
        task.human_intervention_reason = None
        control = _ExecutionControl()
        self._active_task_id = task.id
        self._controls[task.id] = control
        self._touch_and_save(task)
        self._record_event(
            task,
            EventType.TASK_RESUMED if was_resumed else EventType.TASK_STARTED,
            "Task resumed" if was_resumed else "Task execution started",
        )

        try:
            for index in range(task.current_step_index, len(task.steps)):
                step = task.steps[index]
                if step.status is StepStatus.COMPLETED:
                    continue
                if step.status is not StepStatus.PENDING:
                    raise InvalidTaskStateError(
                        f"Step {index} cannot execute from '{step.status.value}'"
                    )

                while step.status is StepStatus.PENDING:
                    self._start_step_attempt(task, step)
                    result = await self._execute_safely(task, step)
                    step.finished_at = utc_now()

                    if control.cancel_requested.is_set():
                        self._settle_cancel_request(task, step, result)
                        return task

                    if control.pause_requested.is_set():
                        self._settle_pause_request(task, step, result)
                        return task

                    if result.success:
                        self._complete_step(task, step, result)
                        break

                    decision = self._record_and_decide_failure(task, step, result)
                    if decision.action is RecoveryAction.RETRY:
                        self._schedule_retry(task, step, result, decision.reason)
                        continue
                    if decision.action is RecoveryAction.USE_FALLBACK:
                        if self._apply_fallback(task, step, result, decision.reason):
                            continue
                        result = RobotActionResult(
                            success=False,
                            message="Configured fallback metadata is invalid",
                            error_code="invalid_parameters",
                        )
                    if decision.action is RecoveryAction.REQUEST_HUMAN:
                        self._request_human_help(task, step, result, decision.reason)
                        return task

                    self._fail_task_at_step(task, step, result)
                    return task

            task.current_step_index = len(task.steps)
            transition_task(task, TaskStatus.COMPLETED)
            self._touch_and_save(task)
            self._record_event(task, EventType.TASK_COMPLETED, "Task completed")
            logger.info("Task %s completed", task.id)
            return task
        finally:
            control.settled.set()
            self._controls.pop(task.id, None)
            if self._active_task_id == task.id:
                self._active_task_id = None

    async def resume_task(self, task_id: str) -> Task:
        task = self.get_task(task_id)
        if task.status is not TaskStatus.PAUSED:
            raise InvalidTaskStateError(
                f"Task '{task.id}' cannot resume from state '{task.status.value}'"
            )
        return await self.execute_task(task_id)

    async def resume_after_human(
        self,
        task_id: str,
        *,
        robot_state_confirmed: bool,
        environment_confirmed: bool,
    ) -> Task:
        """Resume only after a human explicitly confirms the robot is safe."""

        task = self.get_task(task_id)
        if task.status is not TaskStatus.WAITING_FOR_HUMAN:
            raise InvalidTaskStateError(
                f"Task '{task.id}' is not waiting for human intervention"
            )
        if not robot_state_confirmed:
            raise InvalidTaskStateError(
                "Robot state must be confirmed before autonomous execution resumes"
            )
        if not environment_confirmed:
            raise InvalidTaskStateError(
                "Environment state must be confirmed before autonomous execution resumes"
            )
        self._record_event(
            task,
            EventType.HUMAN_HELP_ACKNOWLEDGED,
            "Human intervention completed; robot and environment were confirmed",
            payload={
                "robot_state_confirmed": True,
                "environment_confirmed": True,
            },
        )
        return await self.execute_task(task_id, _human_state_confirmed=True)

    async def request_human_takeover(self, task_id: str, reason: str) -> Task:
        """Stop autonomous execution and explicitly hand control to a human."""

        if not reason.strip():
            raise ValueError("human takeover reason cannot be empty")
        task = self.get_task(task_id)
        if task.status is TaskStatus.WAITING_FOR_HUMAN:
            return task
        if task.status is TaskStatus.RUNNING:
            await self.pause_task(task_id)
            task = self.get_task(task_id)
        if task.status is not TaskStatus.PAUSED:
            raise InvalidTaskStateError(
                f"Task '{task.id}' cannot request human takeover from "
                f"'{task.status.value}'"
            )
        transition_task(task, TaskStatus.WAITING_FOR_HUMAN)
        task.human_intervention_required = True
        task.human_intervention_reason = reason.strip()
        self._touch_and_save(task)
        self._record_event(
            task,
            EventType.HUMAN_HELP_REQUESTED,
            f"Human takeover requested: {reason.strip()}",
            level=EventLevel.WARNING,
        )
        return task

    def reconcile_interrupted_tasks(self) -> list[Task]:
        """Quarantine tasks left RUNNING by a previous process."""

        reconciled: list[Task] = []
        for task in self._repository.list_tasks(statuses={TaskStatus.RUNNING}):
            if task.current_step_index < len(task.steps):
                step = task.steps[task.current_step_index]
                if step.status is StepStatus.RUNNING:
                    transition_step(step, StepStatus.PENDING)
                    step.finished_at = utc_now()
                    step.error = "Execution was interrupted by process restart"
            transition_task(task, TaskStatus.WAITING_FOR_HUMAN)
            task.human_intervention_required = True
            task.human_intervention_reason = (
                "Process restarted while task was running; robot and environment "
                "state must be confirmed"
            )
            self._touch_and_save(task)
            self._record_event(
                task,
                EventType.PROCESS_INTERRUPTED,
                task.human_intervention_reason,
                level=EventLevel.WARNING,
                payload={"current_step_index": task.current_step_index},
            )
            self._record_event(
                task,
                EventType.HUMAN_HELP_REQUESTED,
                "Recovery confirmation required after process restart",
                level=EventLevel.WARNING,
            )
            reconciled.append(task)
        return reconciled

    async def pause_task(self, task_id: str) -> Task:
        task = self.get_task(task_id)
        if task.status is not TaskStatus.RUNNING:
            raise InvalidTaskStateError(
                f"Task '{task.id}' cannot pause from state '{task.status.value}'"
            )
        control = self._require_active_control(task_id)
        control.pause_requested.set()
        self._record_event(task, EventType.PAUSE_REQUESTED, "Pause requested")
        await self._request_robot_cancel(task)
        await control.settled.wait()
        return self.get_task(task_id)

    async def cancel_task(self, task_id: str) -> Task:
        task = self.get_task(task_id)
        if task.status in {
            TaskStatus.PENDING,
            TaskStatus.PAUSED,
            TaskStatus.WAITING_FOR_HUMAN,
        }:
            self._record_event(task, EventType.CANCEL_REQUESTED, "Cancel requested")
            self._cancel_remaining_steps(task)
            transition_task(task, TaskStatus.CANCELLED)
            self._touch_and_save(task)
            self._record_event(task, EventType.TASK_CANCELLED, "Task cancelled")
            return task

        if task.status is not TaskStatus.RUNNING:
            raise InvalidTaskStateError(
                f"Task '{task.id}' cannot cancel from state '{task.status.value}'"
            )

        control = self._require_active_control(task_id)
        control.cancel_requested.set()
        self._record_event(task, EventType.CANCEL_REQUESTED, "Cancel requested")
        await self._request_robot_cancel(task)
        await control.settled.wait()
        return self.get_task(task_id)

    async def _execute_safely(
        self,
        task: Task,
        step: TaskStep,
    ) -> RobotActionResult:
        monitor = asyncio.create_task(self._monitor_feedback(task, step))
        try:
            return await asyncio.wait_for(
                self._robot.execute(step),
                timeout=step.timeout_seconds,
            )
        except TimeoutError:
            cancellation_error: str | None = None
            try:
                await self._robot.cancel_current_action()
            except Exception as exc:
                cancellation_error = str(exc)
                logger.exception("Robot adapter cancellation failed after timeout")
            return RobotActionResult(
                success=False,
                message=f"Action timed out after {step.timeout_seconds:g} seconds",
                data={"cancellation_error": cancellation_error}
                if cancellation_error
                else {},
                error_code="timeout",
            )
        except Exception as exc:  # Adapter exceptions become explicit task failures.
            logger.exception("Robot adapter raised while executing %s", step.action)
            return RobotActionResult(
                success=False,
                message=f"Robot adapter error: {exc}",
                error_code="adapter_error",
            )
        finally:
            monitor.cancel()
            with suppress(asyncio.CancelledError):
                await monitor

    async def _monitor_feedback(self, task: Task, step: TaskStep) -> None:
        last_feedback: dict[str, object] = {}
        while True:
            await asyncio.sleep(self._feedback_poll_interval)
            try:
                feedback = self._robot.get_execution_feedback()
            except Exception:
                logger.exception("Robot feedback polling failed")
                continue
            if feedback and feedback != last_feedback:
                last_feedback = dict(feedback)
                self._record_event(
                    task,
                    EventType.NAVIGATION_FEEDBACK,
                    f"Feedback received for step {step.position}",
                    payload={
                        "step_id": step.id,
                        "position": step.position,
                        "attempt": step.attempt_count,
                        "feedback": feedback,
                    },
                )

    def _start_step_attempt(self, task: Task, step: TaskStep) -> None:
        task.current_step_index = step.position
        transition_step(step, StepStatus.RUNNING)
        step.attempt_count += 1
        step.started_at = utc_now()
        step.finished_at = None
        step.result = None
        step.error = None
        self._touch_and_save(task)
        self._record_event(
            task,
            EventType.STEP_STARTED,
            f"Step {step.position} '{step.action}' attempt {step.attempt_count} started",
            payload={
                "step_id": step.id,
                "position": step.position,
                "action": step.action,
                "attempt": step.attempt_count,
                "timeout_seconds": step.timeout_seconds,
            },
        )
        logger.info(
            "Executing task %s step %d attempt %d: %s",
            task.id,
            step.position,
            step.attempt_count,
            step.action,
        )

    def _record_and_decide_failure(
        self,
        task: Task,
        step: TaskStep,
        result: RobotActionResult,
    ) -> RecoveryDecision:
        category = self._recovery.classify(result)
        task.failure_count += 1
        step.failure_history.append(
            StepFailure(
                attempt=step.attempt_count,
                category=category.value,
                message=result.message,
                error_code=result.error_code,
            )
        )
        decision = self._recovery.decide(
            step,
            result,
            task_failure_count=task.failure_count,
        )
        self._touch_and_save(task)
        self._record_event(
            task,
            EventType.FAILURE_CLASSIFIED,
            f"Step {step.position} failure classified as {category.value}",
            level=EventLevel.WARNING,
            payload={
                "step_id": step.id,
                "position": step.position,
                "attempt": step.attempt_count,
                "error_code": result.error_code,
                "category": category.value,
                "recovery_action": decision.action.value,
                "reason": decision.reason,
            },
        )
        self._record_event(
            task,
            EventType.STEP_TIMED_OUT
            if result.error_code == "timeout"
            else EventType.STEP_FAILED,
            f"Step {step.position} attempt {step.attempt_count} failed: {result.message}",
            level=EventLevel.WARNING,
            payload={
                "step_id": step.id,
                "position": step.position,
                "attempt": step.attempt_count,
                "error_code": result.error_code,
                "will_recover": decision.action
                in {
                    RecoveryAction.RETRY,
                    RecoveryAction.USE_FALLBACK,
                    RecoveryAction.REQUEST_HUMAN,
                },
            },
        )
        return decision

    def _schedule_retry(
        self,
        task: Task,
        step: TaskStep,
        result: RobotActionResult,
        reason: str,
    ) -> None:
        step.result = result.data
        step.error = result.message
        transition_step(step, StepStatus.PENDING)
        self._touch_and_save(task)
        self._record_event(
            task,
            EventType.STEP_RETRY_SCHEDULED,
            f"Step {step.position} will be retried: {reason}",
            level=EventLevel.WARNING,
            payload={"step_id": step.id, "attempt": step.attempt_count},
        )

    def _apply_fallback(
        self,
        task: Task,
        step: TaskStep,
        result: RobotActionResult,
        reason: str,
    ) -> bool:
        fallback = step.metadata.get("fallback_navigation")
        if not isinstance(fallback, dict):
            return False
        location = fallback.get("location")
        parameters = fallback.get("parameters")
        if not isinstance(location, str) or not isinstance(parameters, dict):
            return False
        original_location = step.metadata.get("location")
        step.result = result.data
        step.error = result.message
        step.parameters = dict(parameters)
        step.metadata["original_location"] = original_location
        step.metadata["location"] = location
        step.metadata["fallback_used"] = True
        transition_step(step, StepStatus.PENDING)
        self._touch_and_save(task)
        self._record_event(
            task,
            EventType.STEP_FALLBACK_APPLIED,
            f"Step {step.position} switched to fallback location '{location}'",
            level=EventLevel.WARNING,
            payload={
                "step_id": step.id,
                "from": original_location,
                "to": location,
                "reason": reason,
            },
        )
        return True

    def _request_human_help(
        self,
        task: Task,
        step: TaskStep,
        result: RobotActionResult,
        reason: str,
    ) -> None:
        step.result = result.data
        step.error = result.message
        transition_step(step, StepStatus.PENDING)
        transition_task(task, TaskStatus.WAITING_FOR_HUMAN)
        task.human_intervention_required = True
        task.human_intervention_reason = reason
        task.error = None
        self._touch_and_save(task)
        self._record_event(
            task,
            EventType.HUMAN_HELP_REQUESTED,
            f"Autonomous execution stopped: {reason}",
            level=EventLevel.WARNING,
            payload={
                "step_id": step.id,
                "position": step.position,
                "attempt": step.attempt_count,
                "last_error": result.message,
            },
        )

    def _complete_step(
        self,
        task: Task,
        step: TaskStep,
        result: RobotActionResult,
    ) -> None:
        step.result = result.data
        transition_step(step, StepStatus.COMPLETED)
        task.current_step_index = step.position + 1
        self._touch_and_save(task)
        self._record_event(
            task,
            EventType.STEP_COMPLETED,
            f"Step {step.position} '{step.action}' completed",
            payload={"step_id": step.id, "position": step.position},
        )

    def _fail_task_at_step(
        self,
        task: Task,
        step: TaskStep,
        result: RobotActionResult,
    ) -> None:
        step.result = result.data
        step.error = result.message
        transition_step(step, StepStatus.FAILED)
        transition_task(task, TaskStatus.FAILED)
        task.error = f"Step {step.position} '{step.action}' failed: {result.message}"
        self._touch_and_save(task)
        event_type = (
            EventType.STEP_TIMED_OUT
            if result.error_code == "timeout"
            else EventType.STEP_FAILED
        )
        self._record_event(
            task,
            event_type,
            task.error,
            level=EventLevel.ERROR,
            payload={
                "step_id": step.id,
                "position": step.position,
                "error_code": result.error_code,
            },
        )
        self._record_event(
            task,
            EventType.TASK_FAILED,
            task.error,
            level=EventLevel.ERROR,
        )
        logger.error("Task %s failed: %s", task.id, task.error)

    def _settle_pause_request(
        self,
        task: Task,
        step: TaskStep,
        result: RobotActionResult,
    ) -> None:
        if result.success:
            self._complete_step(task, step, result)
            if task.current_step_index == len(task.steps):
                transition_task(task, TaskStatus.COMPLETED)
                self._touch_and_save(task)
                self._record_event(task, EventType.TASK_COMPLETED, "Task completed")
                return
        else:
            transition_step(step, StepStatus.PENDING)
            step.started_at = None
            step.finished_at = None
            step.result = None
            step.error = None
            self._record_event(
                task,
                EventType.STEP_INTERRUPTED,
                f"Step {step.position} interrupted for pause and will be retried",
                level=EventLevel.WARNING,
                payload={"step_id": step.id, "position": step.position},
            )

        transition_task(task, TaskStatus.PAUSED)
        self._touch_and_save(task)
        self._record_event(task, EventType.TASK_PAUSED, "Task paused")
        logger.info("Task %s paused", task.id)

    def _settle_cancel_request(
        self,
        task: Task,
        step: TaskStep,
        result: RobotActionResult,
    ) -> None:
        if result.success:
            self._complete_step(task, step, result)
            if task.current_step_index == len(task.steps):
                transition_task(task, TaskStatus.COMPLETED)
                self._touch_and_save(task)
                self._record_event(task, EventType.TASK_COMPLETED, "Task completed")
                return
        else:
            transition_step(step, StepStatus.CANCELLED)
            step.error = "Cancelled by request"
            self._record_event(
                task,
                EventType.STEP_CANCELLED,
                f"Step {step.position} '{step.action}' cancelled",
                level=EventLevel.WARNING,
                payload={"step_id": step.id, "position": step.position},
            )
        self._cancel_remaining_steps(task)
        transition_task(task, TaskStatus.CANCELLED)
        task.error = None
        self._touch_and_save(task)
        self._record_event(task, EventType.TASK_CANCELLED, "Task cancelled")
        logger.info("Task %s cancelled", task.id)

    async def _request_robot_cancel(self, task: Task) -> None:
        try:
            await self._robot.cancel_current_action()
        except Exception as exc:
            logger.exception("Robot adapter rejected a control request")
            self._record_event(
                task,
                EventType.CONTROL_REQUEST_FAILED,
                f"Robot adapter cancellation request failed: {exc}",
                level=EventLevel.WARNING,
            )

    def _cancel_remaining_steps(self, task: Task) -> None:
        for step in task.steps:
            if step.status is StepStatus.PENDING:
                transition_step(step, StepStatus.CANCELLED)

    def _require_active_control(self, task_id: str) -> _ExecutionControl:
        control = self._controls.get(task_id)
        if control is None or self._active_task_id != task_id:
            raise InvalidTaskStateError(
                f"Task '{task_id}' is marked running but has no active executor"
            )
        return control

    def _record_event(
        self,
        task: Task,
        event_type: EventType,
        message: str,
        *,
        level: EventLevel = EventLevel.INFO,
        payload: dict[str, object] | None = None,
    ) -> TaskEvent:
        return self._repository.add_event(
            TaskEvent(
                task_id=task.id,
                event_type=event_type,
                level=level,
                message=message,
                payload=payload or {},
            )
        )

    def _touch_and_save(self, task: Task) -> None:
        task.updated_at = utc_now()
        self._repository.save(task)

