"""Run the Phase 7 standard reliability suite and persist every raw result."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from robot_agent.evaluation.report import summarize_records, write_evaluation_artifacts
from robot_agent.evaluation.runner import EvaluationRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run 30–50 deterministic robot-Agent reliability scenarios."
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/phase7"),
        help="Parent directory; a unique timestamped run directory is created.",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=4,
        choices=range(3, 6),
        metavar="{3,4,5}",
        help="Repetitions of each of 10 scenarios (default: 4 = 40 runs).",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> dict[str, object]:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_directory = args.output_root / run_id
    run_directory.parent.mkdir(parents=True, exist_ok=True)
    runner = EvaluationRunner(
        run_directory / "tasks.db",
        run_id=run_id,
    )
    records = await runner.run(repetitions_per_scenario=args.repetitions)
    summary = summarize_records(
        records,
        run_id=run_id,
        repetitions_per_scenario=args.repetitions,
    )
    paths = write_evaluation_artifacts(run_directory, records, summary)
    return {
        "run_id": run_id,
        "total_runs": summary.total_runs,
        "expectation_pass_rate": summary.expectation_pass_rate,
        "task_success_rate": summary.task_success_rate,
        "recovery_success_rate": summary.recovery_success_rate,
        "tool_calling_success_rate": summary.tool_calling_success_rate,
        "human_intervention_rate": summary.human_intervention_rate,
        "perception_precision": summary.perception_precision,
        "perception_recall": summary.perception_recall,
        "artifacts": {name: str(path) for name, path in paths.items()},
    }


def main() -> None:
    report = asyncio.run(run(parse_args()))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

