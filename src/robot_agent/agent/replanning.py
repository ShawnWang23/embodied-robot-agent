"""Bounded closed-loop review and replanning policies."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from robot_agent.agent.models import (
    CaptureImagePlanStep,
    DetectObjectsPlanStep,
    NavigateToPlanStep,
    TaskPlan,
)
from robot_agent.core.models import Task


class ExecutionBudget(BaseModel):
    """Hard limits that prevent an Agent from replanning forever."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_replans: int = Field(default=1, ge=0, le=10)
    max_total_steps: int = Field(default=12, ge=1, le=100)


class ReplanDecision(BaseModel):
    """Outcome of reviewing one completed mission against the user goal."""

    model_config = ConfigDict(extra="forbid")

    goal_satisfied: bool
    reason: str = Field(min_length=1, max_length=1_000)
    plan: TaskPlan | None = None

    @model_validator(mode="after")
    def require_plan_for_continuation(self) -> "ReplanDecision":
        if self.goal_satisfied and self.plan is not None:
            raise ValueError("A satisfied goal cannot request another plan")
        return self


class ReplanPolicy(Protocol):
    async def review(
        self,
        user_request: str,
        task: Task,
        *,
        replan_count: int,
    ) -> ReplanDecision:
        """Decide whether observations require another validated mission."""


class NoReplanPolicy:
    """Compatibility policy for callers that want a single execution pass."""

    async def review(
        self,
        user_request: str,
        task: Task,
        *,
        replan_count: int,
    ) -> ReplanDecision:
        del user_request, task, replan_count
        return ReplanDecision(
            goal_satisfied=True,
            reason="Single-pass execution completed",
        )


class PerceptionFallbackReplanner:
    """Re-observe from a configured semantic location when a target is absent.

    The policy never invents coordinates. Its follow-up plan goes through the
    same ToolRegistry and location-catalog validation as the initial LLM plan.
    """

    def __init__(self, fallback_location: str = "corridor_observation") -> None:
        self._fallback_location = fallback_location

    async def review(
        self,
        user_request: str,
        task: Task,
        *,
        replan_count: int,
    ) -> ReplanDecision:
        detections = [
            step
            for step in task.steps
            if step.action == "detect_objects" and isinstance(step.result, dict)
        ]
        if not detections:
            return ReplanDecision(
                goal_satisfied=True,
                reason="The mission required no visual target verification",
            )

        target_presence: dict[str, bool] = {}
        targets: list[str] = []
        for step in detections:
            raw_presence = step.result.get("target_presence", {})
            if isinstance(raw_presence, dict):
                target_presence.update(
                    {
                        str(name): bool(present)
                        for name, present in raw_presence.items()
                    }
                )
            raw_targets = step.parameters.get("targets", [])
            if isinstance(raw_targets, list):
                targets.extend(str(target) for target in raw_targets)

        if any(target_presence.values()):
            return ReplanDecision(
                goal_satisfied=True,
                reason="At least one requested target was detected",
            )
        if replan_count > 0:
            return ReplanDecision(
                goal_satisfied=True,
                reason="The target remained absent after a second observation point",
            )

        unique_targets = list(dict.fromkeys(targets))
        if not unique_targets:
            return ReplanDecision(
                goal_satisfied=True,
                reason="The detector returned no target list to re-observe",
            )

        return ReplanDecision(
            goal_satisfied=False,
            reason=(
                "Requested targets were absent at the first viewpoint; "
                "move to the configured observation point and inspect again"
            ),
            plan=TaskPlan(
                objective=f"Re-observe for: {user_request}",
                steps=[
                    NavigateToPlanStep(
                        action="navigate_to",
                        location=self._fallback_location,
                        reason="Use the configured alternate observation point",
                    ),
                    CaptureImagePlanStep(
                        action="capture_image",
                        reason="Capture a fresh frame after changing viewpoint",
                    ),
                    DetectObjectsPlanStep(
                        action="detect_objects",
                        targets=unique_targets,
                        reason="Verify the requested targets from the new viewpoint",
                    ),
                ],
                unsupported_requirements=[],
            ),
        )

