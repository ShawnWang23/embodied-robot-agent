"""Inject Phase 4 failures and verify each bounded recovery outcome."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from pathlib import Path

from pydantic import ValidationError

from robot_agent.adapters.fake_robot import FakeRobotAdapter
from robot_agent.agent.locations import LocationCatalog
from robot_agent.agent.models import TaskPlan
from robot_agent.agent.tools import ToolRegistry
from robot_agent.core.models import RobotActionResult, TaskStatus, TaskStepSpec
from robot_agent.mission.manager import MissionManager
from robot_agent.storage.sqlite import SQLiteTaskRepository


def failed(message: str, code: str) -> RobotActionResult:
    return RobotActionResult(success=False, message=message, error_code=code)


def succeeded(message: str = "recovered") -> RobotActionResult:
    return RobotActionResult(success=True, message=message)


async def run_case(
    root: Path,
    name: str,
    action: str,
    results: list[RobotActionResult],
    *,
    step: TaskStepSpec | None = None,
) -> dict[str, object]:
    robot = FakeRobotAdapter(scripted_results={action: results})
    manager = MissionManager(SQLiteTaskRepository(root / f"{name}.db"), robot)
    task = manager.create_task(name, [step or TaskStepSpec(action=action)])
    settled = await manager.execute_task(task.id)
    return {
        "status": settled.status.value,
        "attempts": settled.steps[0].attempt_count,
        "failures": settled.failure_count,
        "final_location": settled.steps[0].metadata.get("location"),
        "human_required": settled.human_intervention_required,
    }


async def main() -> None:
    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory(prefix="robot-agent-recovery-") as temp:
        root = Path(temp)
        locations = LocationCatalog.from_json(Path("config/locations.json"))
        tools = ToolRegistry(locations)
        fallback_step = tools.compile_plan(
            TaskPlan.model_validate(
                {
                    "objective": "visit laboratory door",
                    "steps": [
                        {
                            "action": "navigate_to",
                            "location": "laboratory_door",
                            "reason": "fault injection",
                        }
                    ],
                }
            )
        )[0]

        report = {
            "navigation_timeout": await run_case(
                root,
                "navigation_timeout",
                "navigate_to",
                [failed("timeout", "timeout")] * 3,
            ),
            "goal_unreachable": await run_case(
                root,
                "goal_unreachable",
                "navigate_to",
                [failed("unreachable", "navigation_aborted"), succeeded()],
                step=fallback_step,
            ),
            "path_blocked": await run_case(
                root,
                "path_blocked",
                "navigate_to",
                [failed("blocked", "path_blocked"), succeeded()],
                step=fallback_step,
            ),
            "tool_failure": await run_case(
                root,
                "tool_failure",
                "get_robot_status",
                [failed("temporary tool failure", "tool_error"), succeeded()],
            ),
            "perception_failure": await run_case(
                root,
                "perception_failure",
                "detect_objects",
                [failed("no frame", "detection_failed"), succeeded()],
            ),
            "repeated_failure": await run_case(
                root,
                "repeated_failure",
                "navigate_to",
                [failed("service down", "tool_error")] * 3,
            ),
        }

        invalid_robot = await run_case(
            root,
            "invalid_robot_parameters",
            "navigate_to",
            [failed("schema rejected", "invalid_parameters")],
        )
        try:
            TaskPlan.model_validate(
                {
                    "objective": "unsafe motion",
                    "steps": [
                        {
                            "action": "publish_cmd_vel",
                            "reason": "invalid LLM output",
                        }
                    ],
                }
            )
        except ValidationError:
            llm_rejected = True
        else:
            llm_rejected = False
        report["invalid_parameters"] = {
            **invalid_robot,
            "invalid_llm_plan_rejected": llm_rejected,
        }

        assert report["navigation_timeout"]["status"] == (
            TaskStatus.WAITING_FOR_HUMAN.value
        )
        assert report["goal_unreachable"]["final_location"] == (
            "corridor_observation"
        )
        assert report["path_blocked"]["status"] == TaskStatus.COMPLETED.value
        assert report["tool_failure"]["status"] == TaskStatus.COMPLETED.value
        assert report["perception_failure"]["status"] == TaskStatus.COMPLETED.value
        assert report["repeated_failure"]["human_required"] is True
        assert report["invalid_parameters"]["attempts"] == 1
        assert report["invalid_parameters"]["invalid_llm_plan_rejected"] is True

        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
