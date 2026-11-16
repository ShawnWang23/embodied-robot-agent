"""Deterministic, bounded recovery decisions for mission failures."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from robot_agent.core.models import RobotActionResult, TaskStep


class FailureCategory(StrEnum):
    """Stable failure classes used by the recovery state machine."""

    TIMEOUT = "timeout"
    GOAL_UNREACHABLE = "goal_unreachable"
    PATH_BLOCKED = "path_blocked"
    TOOL_FAILURE = "tool_failure"
    INVALID_PARAMETERS = "invalid_parameters"
    PERCEPTION_FAILURE = "perception_failure"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class RecoveryAction(StrEnum):
    """Actions the mission layer may take after one failed attempt."""

    RETRY = "retry"
    USE_FALLBACK = "use_fallback"
    REQUEST_HUMAN = "request_human"
    FAIL = "fail"


class RecoveryConfig(BaseModel):
    """Hard limits that prevent recovery from becoming an infinite loop."""

    model_config = ConfigDict(frozen=True)

    max_attempts_per_step: int = Field(default=3, ge=1, le=10)
    max_failures_per_task: int = Field(default=5, ge=1, le=50)

    @classmethod
    def from_json(cls, path: str | Path) -> "RecoveryConfig":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))


class RecoveryDecision(BaseModel):
    """Auditable output of the deterministic recovery policy."""

    model_config = ConfigDict(frozen=True)

    category: FailureCategory
    action: RecoveryAction
    reason: str


class RecoveryPolicy:
    """Classify adapter errors and choose a bounded deterministic response."""

    _CATEGORY_BY_ERROR_CODE: dict[str, FailureCategory] = {
        "timeout": FailureCategory.TIMEOUT,
        "goal_rejected": FailureCategory.GOAL_UNREACHABLE,
        "navigation_aborted": FailureCategory.GOAL_UNREACHABLE,
        "goal_unreachable": FailureCategory.GOAL_UNREACHABLE,
        "path_blocked": FailureCategory.PATH_BLOCKED,
        "obstacle_blocked": FailureCategory.PATH_BLOCKED,
        "adapter_error": FailureCategory.TOOL_FAILURE,
        "adapter_closed": FailureCategory.TOOL_FAILURE,
        "action_server_unavailable": FailureCategory.TOOL_FAILURE,
        "navigation_error": FailureCategory.TOOL_FAILURE,
        "status_unavailable": FailureCategory.TOOL_FAILURE,
        "tool_error": FailureCategory.TOOL_FAILURE,
        "invalid_parameters": FailureCategory.INVALID_PARAMETERS,
        "goal_out_of_bounds": FailureCategory.INVALID_PARAMETERS,
        "perception_failed": FailureCategory.PERCEPTION_FAILURE,
        "camera_unavailable": FailureCategory.PERCEPTION_FAILURE,
        "detection_failed": FailureCategory.PERCEPTION_FAILURE,
        "cancelled": FailureCategory.CANCELLED,
    }

    _RETRYABLE = {
        FailureCategory.TIMEOUT,
        FailureCategory.TOOL_FAILURE,
        FailureCategory.PERCEPTION_FAILURE,
        FailureCategory.GOAL_UNREACHABLE,
        FailureCategory.PATH_BLOCKED,
    }

    def __init__(self, config: RecoveryConfig | None = None) -> None:
        self.config = config or RecoveryConfig()

    def classify(self, result: RobotActionResult) -> FailureCategory:
        if result.error_code is None:
            return FailureCategory.UNKNOWN
        return self._CATEGORY_BY_ERROR_CODE.get(
            result.error_code,
            FailureCategory.UNKNOWN,
        )

    def decide(
        self,
        step: TaskStep,
        result: RobotActionResult,
        *,
        task_failure_count: int,
    ) -> RecoveryDecision:
        category = self.classify(result)

        if category in {
            FailureCategory.INVALID_PARAMETERS,
            FailureCategory.CANCELLED,
            FailureCategory.UNKNOWN,
        }:
            return RecoveryDecision(
                category=category,
                action=RecoveryAction.FAIL,
                reason=f"{category.value} is not safe to retry automatically",
            )

        if task_failure_count >= self.config.max_failures_per_task:
            return RecoveryDecision(
                category=category,
                action=RecoveryAction.REQUEST_HUMAN,
                reason=(
                    "mission reached the configured total failure limit "
                    f"({self.config.max_failures_per_task})"
                ),
            )

        fallback = step.metadata.get("fallback_navigation")
        fallback_used = bool(step.metadata.get("fallback_used"))
        if (
            category
            in {FailureCategory.GOAL_UNREACHABLE, FailureCategory.PATH_BLOCKED}
            and isinstance(fallback, dict)
            and not fallback_used
        ):
            return RecoveryDecision(
                category=category,
                action=RecoveryAction.USE_FALLBACK,
                reason="an explicit fallback location is configured",
            )

        if (
            category in self._RETRYABLE
            and step.attempt_count < self.config.max_attempts_per_step
        ):
            return RecoveryDecision(
                category=category,
                action=RecoveryAction.RETRY,
                reason=(
                    f"attempt {step.attempt_count} of "
                    f"{self.config.max_attempts_per_step} failed"
                ),
            )

        return RecoveryDecision(
            category=category,
            action=RecoveryAction.REQUEST_HUMAN,
            reason=(
                "automatic recovery attempts are exhausted; autonomous execution "
                "must stop"
            ),
        )
