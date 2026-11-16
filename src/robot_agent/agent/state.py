"""Serializable state passed between LangGraph nodes."""

from __future__ import annotations

from typing import Literal, TypedDict


class AgentState(TypedDict, total=False):
    thread_id: str
    user_request: str
    status: Literal[
        "planning",
        "validating",
        "executing",
        "waiting_for_human",
        "paused",
        "cancelled",
        "completed",
        "failed",
    ]
    plan: dict[str, object]
    executable_steps: list[dict[str, object]]
    task: dict[str, object]
    task_id: str
    task_history: list[dict[str, object]]
    errors: list[str]
    perception_outcome: Literal["objects_detected", "clear"]
    goal_satisfied: bool
    completion_reason: str
    replan_count: int
    executed_step_count: int

