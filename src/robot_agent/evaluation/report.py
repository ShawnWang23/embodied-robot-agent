"""Aggregate raw records and write machine- and human-readable reports."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from robot_agent.evaluation.models import (
    EvaluationRecord,
    EvaluationSummary,
    ScenarioSummary,
)

METRIC_DEFINITIONS = {
    "expectation_pass_rate": (
        "Runs whose terminal status matched the scenario's declared expectation / "
        "all runs. This is the benchmark correctness metric."
    ),
    "task_success_rate": "Runs ending completed / all runs.",
    "average_completion_time_seconds": (
        "Arithmetic mean wall-clock duration from scenario start to terminal result."
    ),
    "recovery_success_rate": (
        "Fault-injected runs ending completed / runs that attempted automatic or "
        "restart recovery."
    ),
    "tool_calling_success_rate": (
        "Successful step attempts / all step attempts; retries and interrupted calls "
        "remain in the denominator."
    ),
    "human_intervention_rate": (
        "Runs that paused for, requested, or required human confirmation / all runs."
    ),
    "perception_precision": "TP / (TP + FP) over synthetic labeled detections.",
    "perception_recall": "TP / (TP + FN) over synthetic labeled detections.",
}


def summarize_records(
    records: list[EvaluationRecord],
    *,
    run_id: str,
    repetitions_per_scenario: int,
) -> EvaluationSummary:
    """Calculate the required metrics from immutable raw records."""

    if not records:
        raise ValueError("at least one evaluation record is required")

    total = len(records)
    durations = sorted(record.duration_seconds for record in records)
    p95_index = max(0, math.ceil(0.95 * total) - 1)
    recovery_records = [record for record in records if record.recovery_attempted]
    attempted = sum(record.tool_calls_attempted for record in records)
    succeeded = sum(record.tool_calls_succeeded for record in records)
    true_positives = sum(record.true_positives for record in records)
    false_positives = sum(record.false_positives for record in records)
    false_negatives = sum(record.false_negatives for record in records)
    true_negatives = sum(record.true_negatives for record in records)

    grouped: dict[str, list[EvaluationRecord]] = defaultdict(list)
    for record in records:
        grouped[record.scenario].append(record)
    scenarios = [
        ScenarioSummary(
            scenario=name,
            runs=len(items),
            expectation_pass_rate=sum(item.expectation_met for item in items)
            / len(items),
            task_success_rate=sum(item.task_success for item in items) / len(items),
            average_completion_time_seconds=(
                sum(item.duration_seconds for item in items) / len(items)
            ),
        )
        for name, items in grouped.items()
    ]

    return EvaluationSummary(
        run_id=run_id,
        generated_at=datetime.now(timezone.utc),
        benchmark_kind="deterministic_software_fault_injection",
        total_runs=total,
        scenario_count=len(grouped),
        repetitions_per_scenario=repetitions_per_scenario,
        expectation_pass_rate=sum(record.expectation_met for record in records) / total,
        task_success_rate=sum(record.task_success for record in records) / total,
        average_completion_time_seconds=sum(durations) / total,
        p95_completion_time_seconds=durations[p95_index],
        recovery_success_rate=(
            sum(record.recovery_success is True for record in recovery_records)
            / len(recovery_records)
            if recovery_records
            else None
        ),
        tool_calling_success_rate=(succeeded / attempted if attempted else None),
        human_intervention_rate=(
            sum(record.human_intervention for record in records) / total
        ),
        perception_precision=(
            true_positives / (true_positives + false_positives)
            if true_positives + false_positives
            else None
        ),
        perception_recall=(
            true_positives / (true_positives + false_negatives)
            if true_positives + false_negatives
            else None
        ),
        totals={
            "expectations_met": sum(record.expectation_met for record in records),
            "tasks_completed": sum(record.task_success for record in records),
            "recovery_runs": len(recovery_records),
            "recoveries_succeeded": sum(
                record.recovery_success is True for record in recovery_records
            ),
            "human_intervention_runs": sum(
                record.human_intervention for record in records
            ),
            "tool_calls_attempted": attempted,
            "tool_calls_succeeded": succeeded,
            "true_positives": true_positives,
            "false_positives": false_positives,
            "false_negatives": false_negatives,
            "true_negatives": true_negatives,
        },
        metric_definitions=METRIC_DEFINITIONS,
        scenarios=scenarios,
    )


def write_evaluation_artifacts(
    output_directory: str | Path,
    records: list[EvaluationRecord],
    summary: EvaluationSummary,
) -> dict[str, Path]:
    """Write raw JSONL, validated summary JSON, and a Markdown report."""

    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    raw_path = output / "records.jsonl"
    summary_path = output / "summary.json"
    report_path = output / "report.md"
    existing = [path for path in (raw_path, summary_path, report_path) if path.exists()]
    if existing:
        names = ", ".join(path.name for path in existing)
        raise FileExistsError(f"evaluation artifacts already exist: {names}")

    raw_path.write_text(
        "".join(record.model_dump_json() + "\n" for record in records),
        encoding="utf-8",
    )
    summary_path.write_text(
        summary.model_dump_json(indent=2),
        encoding="utf-8",
    )
    report_path.write_text(_markdown_report(summary), encoding="utf-8")
    return {"records": raw_path, "summary": summary_path, "report": report_path}


def _markdown_report(summary: EvaluationSummary) -> str:
    def percentage(value: float | None) -> str:
        return "N/A" if value is None else f"{value * 100:.2f}%"

    lines = [
        "# Phase 7 Reliability Evaluation",
        "",
        f"Run ID: `{summary.run_id}`  ",
        f"Generated: `{summary.generated_at.isoformat()}`  ",
        f"Benchmark: `{summary.benchmark_kind}`",
        "",
        "## Required metrics",
        "",
        "| Metric | Result |",
        "|---|---:|",
        f"| Expectation Pass Rate | {percentage(summary.expectation_pass_rate)} |",
        f"| Task Success Rate | {percentage(summary.task_success_rate)} |",
        (
            "| Average Completion Time | "
            f"{summary.average_completion_time_seconds:.6f} s |"
        ),
        f"| P95 Completion Time | {summary.p95_completion_time_seconds:.6f} s |",
        f"| Recovery Success Rate | {percentage(summary.recovery_success_rate)} |",
        (
            "| Tool Calling Success Rate | "
            f"{percentage(summary.tool_calling_success_rate)} |"
        ),
        (
            "| Human Intervention Rate | "
            f"{percentage(summary.human_intervention_rate)} |"
        ),
        f"| Perception Precision | {percentage(summary.perception_precision)} |",
        f"| Perception Recall | {percentage(summary.perception_recall)} |",
        "",
        "## Scenario results",
        "",
        "| Scenario | Runs | Expected outcome pass | Task success | Mean time (s) |",
        "|---|---:|---:|---:|---:|",
    ]
    for scenario in summary.scenarios:
        lines.append(
            f"| {scenario.scenario} | {scenario.runs} | "
            f"{percentage(scenario.expectation_pass_rate)} | "
            f"{percentage(scenario.task_success_rate)} | "
            f"{scenario.average_completion_time_seconds:.6f} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "This is a deterministic software-level fault-injection benchmark using "
            "FakeRobotAdapter and synthetic labeled perception outcomes. It validates "
            "Agent, FSM, retry, persistence, metric, and reporting behavior. It is not "
            "a Gazebo physics benchmark, a real-robot safety test, or a YOLO dataset "
            "accuracy claim.",
            "",
            "## Metric definitions",
            "",
        ]
    )
    lines.extend(
        f"- **{name}**: {definition}"
        for name, definition in summary.metric_definitions.items()
    )
    lines.append("")
    return "\n".join(lines)


def load_records(path: str | Path) -> list[EvaluationRecord]:
    """Load raw JSONL again so reports can be independently recalculated."""

    return [
        EvaluationRecord.model_validate(json.loads(line))
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
