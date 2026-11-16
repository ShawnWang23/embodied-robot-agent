"""Validated high-level plans and agent execution results."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class NavigateToPlanStep(BaseModel):
    """A semantic navigation request; coordinates are resolved later."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["navigate_to"]
    location: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=500)
    timeout_seconds: float = Field(default=60.0, gt=0, le=600)


class GetRobotStatusPlanStep(BaseModel):
    """Request a deterministic robot-state read."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["get_robot_status"]
    reason: str = Field(min_length=1, max_length=500)
    timeout_seconds: float = Field(default=10.0, gt=0, le=60)


class CaptureImagePlanStep(BaseModel):
    """Capture one frame from the validated front camera."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["capture_image"]
    camera: Literal["front"] = "front"
    reason: str = Field(min_length=1, max_length=500)
    timeout_seconds: float = Field(default=10.0, gt=0, le=60)


class DetectObjectsPlanStep(BaseModel):
    """Detect a bounded list of pretrained object classes."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["detect_objects"]
    targets: list[str] = Field(min_length=1, max_length=20)
    confidence_threshold: float = Field(default=0.25, ge=0, le=1)
    reason: str = Field(min_length=1, max_length=500)
    timeout_seconds: float = Field(default=30.0, gt=0, le=120)


PlanStep = Annotated[
    NavigateToPlanStep
    | GetRobotStatusPlanStep
    | CaptureImagePlanStep
    | DetectObjectsPlanStep,
    Field(discriminator="action"),
]


class TaskPlan(BaseModel):
    """Structured planner output that is never executed without validation."""

    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1, max_length=2_000)
    steps: list[PlanStep] = Field(max_length=20)
    unsupported_requirements: list[str] = Field(default_factory=list, max_length=20)


class AgentRunResult(BaseModel):
    """Stable result returned by the LangGraph facade."""

    model_config = ConfigDict(extra="forbid")

    thread_id: str
    status: Literal[
        "completed",
        "waiting_for_human",
        "paused",
        "cancelled",
        "failed",
    ]
    plan: TaskPlan | None = None
    task: dict[str, object] | None = None
    errors: list[str] = Field(default_factory=list)
    perception_outcome: Literal["objects_detected", "clear"] | None = None
    goal_satisfied: bool | None = None
    completion_reason: str | None = None
    replan_count: int = Field(default=0, ge=0)
    executed_step_count: int = Field(default=0, ge=0)
    task_history: list[dict[str, object]] = Field(default_factory=list)

