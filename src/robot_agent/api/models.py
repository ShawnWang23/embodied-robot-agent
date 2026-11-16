"""Validated HTTP request and response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SubmitTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(min_length=1, max_length=2_000)
    thread_id: str | None = Field(default=None, min_length=1, max_length=200)


class HumanTakeoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class ResumeTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    robot_state_confirmed: bool
    environment_confirmed: bool


class TaskAccepted(BaseModel):
    thread_id: str
    status: str


class AgentTaskView(BaseModel):
    thread_id: str
    agent_status: str
    task: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)
    perception_outcome: str | None = None
    goal_satisfied: bool | None = None
    completion_reason: str | None = None
    replan_count: int = 0
    executed_step_count: int = 0
    task_history: list[dict[str, Any]] = Field(default_factory=list)


class TaskEventsView(BaseModel):
    thread_id: str
    events: list[dict[str, Any]]


class CheckpointHistoryView(BaseModel):
    thread_id: str
    checkpoints: list[dict[str, Any]]

