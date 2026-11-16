"""Validated records and aggregate metrics for Phase 7 evaluations."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ScenarioName = Literal[
    "normal_inspection",
    "temporary_obstacle",
    "navigation_failure",
    "target_absent",
    "perception_failure",
    "llm_output_error",
    "tool_call_failure",
    "process_interruption",
    "human_pause",
    "multi_location_long_task",
]


class EvaluationRecord(BaseModel):
    """One measured execution of one standard scenario."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    scenario: ScenarioName
    iteration: int = Field(ge=1)
    started_at: datetime
    duration_seconds: float = Field(ge=0)
    expected_status: str
    actual_status: str
    expectation_met: bool
    task_success: bool
    recovery_attempted: bool
    recovery_success: bool | None = None
    human_intervention: bool
    tool_calls_attempted: int = Field(ge=0)
    tool_calls_succeeded: int = Field(ge=0)
    true_positives: int = Field(default=0, ge=0)
    false_positives: int = Field(default=0, ge=0)
    false_negatives: int = Field(default=0, ge=0)
    true_negatives: int = Field(default=0, ge=0)
    task_id: str | None = None
    notes: list[str] = Field(default_factory=list)


class ScenarioSummary(BaseModel):
    """Compact aggregate for a named scenario."""

    scenario: ScenarioName
    runs: int = Field(ge=1)
    expectation_pass_rate: float = Field(ge=0, le=1)
    task_success_rate: float = Field(ge=0, le=1)
    average_completion_time_seconds: float = Field(ge=0)


class EvaluationSummary(BaseModel):
    """Required project metrics plus definitions and scenario-level results."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    generated_at: datetime
    benchmark_kind: Literal["deterministic_software_fault_injection"]
    total_runs: int = Field(ge=1)
    scenario_count: int = Field(ge=1)
    repetitions_per_scenario: int = Field(ge=1)
    expectation_pass_rate: float = Field(ge=0, le=1)
    task_success_rate: float = Field(ge=0, le=1)
    average_completion_time_seconds: float = Field(ge=0)
    p95_completion_time_seconds: float = Field(ge=0)
    recovery_success_rate: float | None = Field(default=None, ge=0, le=1)
    tool_calling_success_rate: float | None = Field(default=None, ge=0, le=1)
    human_intervention_rate: float = Field(ge=0, le=1)
    perception_precision: float | None = Field(default=None, ge=0, le=1)
    perception_recall: float | None = Field(default=None, ge=0, le=1)
    totals: dict[str, int]
    metric_definitions: dict[str, str]
    scenarios: list[ScenarioSummary]

