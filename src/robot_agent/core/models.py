"""Validated domain models used by the mission layer and robot adapters."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


class TaskStatus(StrEnum):
    """Lifecycle states for a complete task."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_FOR_HUMAN = "waiting_for_human"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(StrEnum):
    """Lifecycle states for one task step."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EventLevel(StrEnum):
    """Severity attached to a persisted mission event."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class EventType(StrEnum):
    """Stable event names for audit logs and later API consumers."""

    TASK_CREATED = "task_created"
    TASK_STARTED = "task_started"
    TASK_RESUMED = "task_resumed"
    PAUSE_REQUESTED = "pause_requested"
    TASK_PAUSED = "task_paused"
    CANCEL_REQUESTED = "cancel_requested"
    CONTROL_REQUEST_FAILED = "control_request_failed"
    TASK_CANCELLED = "task_cancelled"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_INTERRUPTED = "step_interrupted"
    STEP_CANCELLED = "step_cancelled"
    STEP_FAILED = "step_failed"
    STEP_TIMED_OUT = "step_timed_out"
    FAILURE_CLASSIFIED = "failure_classified"
    STEP_RETRY_SCHEDULED = "step_retry_scheduled"
    STEP_FALLBACK_APPLIED = "step_fallback_applied"
    NAVIGATION_FEEDBACK = "navigation_feedback"
    HUMAN_HELP_REQUESTED = "human_help_requested"
    HUMAN_HELP_ACKNOWLEDGED = "human_help_acknowledged"
    PROCESS_INTERRUPTED = "process_interrupted"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"


class TaskStepSpec(BaseModel):
    """User-facing input for creating one step."""

    action: str = Field(min_length=1, max_length=100)
    parameters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=30.0, gt=0, le=3_600)


class StepFailure(BaseModel):
    """One persisted, classified failure from a step attempt."""

    attempt: int = Field(ge=1)
    category: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2_000)
    error_code: str | None = Field(default=None, max_length=100)
    occurred_at: datetime = Field(default_factory=utc_now)


class TaskStep(TaskStepSpec):
    """A persisted, executable step with runtime state."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    position: int = Field(ge=0)
    status: StepStatus = StepStatus.PENDING
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempt_count: int = Field(default=0, ge=0)
    failure_history: list[StepFailure] = Field(default_factory=list)


class Task(BaseModel):
    """A multi-step mission and its current execution snapshot."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    description: str = Field(min_length=1, max_length=2_000)
    steps: list[TaskStep] = Field(min_length=1)
    status: TaskStatus = TaskStatus.PENDING
    current_step_index: int = Field(default=0, ge=0)
    error: str | None = None
    failure_count: int = Field(default=0, ge=0)
    human_intervention_required: bool = False
    human_intervention_reason: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class RobotActionResult(BaseModel):
    """Normalized result returned by every robot adapter action."""

    success: bool
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None


class TaskEvent(BaseModel):
    """One immutable lifecycle or error record for a task."""

    id: int | None = None
    task_id: str
    event_type: EventType
    level: EventLevel = EventLevel.INFO
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

