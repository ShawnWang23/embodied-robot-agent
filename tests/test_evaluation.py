from __future__ import annotations

from pathlib import Path

import pytest

from robot_agent.evaluation.report import (
    load_records,
    summarize_records,
    write_evaluation_artifacts,
)
from robot_agent.evaluation.runner import SCENARIOS, EvaluationRunner


async def test_standard_suite_runs_30_scenarios_and_calculates_metrics(
    tmp_path: Path,
) -> None:
    runner = EvaluationRunner(tmp_path / "tasks.db", run_id="test-run")

    records = await runner.run(repetitions_per_scenario=3)
    summary = summarize_records(
        records,
        run_id="test-run",
        repetitions_per_scenario=3,
    )

    assert len(records) == 30
    assert {record.scenario for record in records} == set(SCENARIOS)
    assert summary.total_runs == 30
    assert summary.scenario_count == 10
    assert summary.expectation_pass_rate == 1.0
    assert summary.task_success_rate == pytest.approx(0.8)
    assert summary.recovery_success_rate == pytest.approx(0.8)
    assert summary.human_intervention_rate == pytest.approx(0.3)
    assert summary.tool_calling_success_rate == pytest.approx(60 / 84)
    assert summary.totals["true_positives"] == 11
    assert summary.totals["false_positives"] == 1
    assert summary.totals["false_negatives"] == 1
    assert summary.totals["true_negatives"] == 2
    assert summary.perception_precision == pytest.approx(11 / 12)
    assert summary.perception_recall == pytest.approx(11 / 12)


async def test_evaluation_artifacts_round_trip_raw_records(tmp_path: Path) -> None:
    runner = EvaluationRunner(tmp_path / "tasks.db", run_id="artifact-test")
    records = await runner.run(repetitions_per_scenario=3)
    summary = summarize_records(
        records,
        run_id="artifact-test",
        repetitions_per_scenario=3,
    )

    paths = write_evaluation_artifacts(tmp_path / "result", records, summary)
    restored = load_records(paths["records"])

    assert restored == records
    assert paths["summary"].is_file()
    assert "Interpretation boundary" in paths["report"].read_text(encoding="utf-8")
    with pytest.raises(FileExistsError, match="already exist"):
        write_evaluation_artifacts(tmp_path / "result", records, summary)


async def test_evaluation_rejects_nonstandard_run_count(tmp_path: Path) -> None:
    runner = EvaluationRunner(tmp_path / "tasks.db", run_id="bad-count")

    with pytest.raises(ValueError, match="30–50"):
        await runner.run(repetitions_per_scenario=2)
