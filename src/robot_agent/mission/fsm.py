"""Deterministic lifecycle transition rules for tasks and task steps."""

from __future__ import annotations

from robot_agent.core.exceptions import InvalidTaskStateError
from robot_agent.core.models import StepStatus, Task, TaskStatus, TaskStep

TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.PAUSED,
            TaskStatus.WAITING_FOR_HUMAN,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.PAUSED: frozenset(
        {
            TaskStatus.RUNNING,
            TaskStatus.WAITING_FOR_HUMAN,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.WAITING_FOR_HUMAN: frozenset(
        {TaskStatus.RUNNING, TaskStatus.CANCELLED}
    ),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

STEP_TRANSITIONS: dict[StepStatus, frozenset[StepStatus]] = {
    StepStatus.PENDING: frozenset({StepStatus.RUNNING, StepStatus.CANCELLED}),
    StepStatus.RUNNING: frozenset(
        {
            StepStatus.PENDING,
            StepStatus.COMPLETED,
            StepStatus.FAILED,
            StepStatus.CANCELLED,
        }
    ),
    StepStatus.COMPLETED: frozenset(),
    StepStatus.FAILED: frozenset(),
    StepStatus.CANCELLED: frozenset(),
}


def transition_task(task: Task, target: TaskStatus) -> None:
    """Validate and apply one task transition."""

    if target not in TASK_TRANSITIONS[task.status]:
        raise InvalidTaskStateError(
            f"Task '{task.id}' cannot transition from "
            f"'{task.status.value}' to '{target.value}'"
        )
    task.status = target


def transition_step(step: TaskStep, target: StepStatus) -> None:
    """Validate and apply one step transition."""

    if target not in STEP_TRANSITIONS[step.status]:
        raise InvalidTaskStateError(
            f"Step '{step.id}' cannot transition from "
            f"'{step.status.value}' to '{target.value}'"
        )
    step.status = target
