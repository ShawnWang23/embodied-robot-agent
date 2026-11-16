"""Command-line entry points for mission and agent demos."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from robot_agent.adapters.fake_robot import FakeRobotAdapter
from robot_agent.agent.graph import AgentRunner, build_agent_graph
from robot_agent.agent.locations import LocationCatalog
from robot_agent.agent.models import AgentRunResult
from robot_agent.agent.planner import (
    OpenAIPlanner,
    RuleBasedPlanner,
    SiliconFlowPlanner,
)
from robot_agent.agent.replanning import (
    ExecutionBudget,
    PerceptionFallbackReplanner,
)
from robot_agent.agent.tools import ToolRegistry
from robot_agent.core.logging_config import configure_logging
from robot_agent.core.models import Task, TaskEvent, TaskStepSpec
from robot_agent.mission.manager import MissionManager
from robot_agent.mission.recovery import RecoveryConfig, RecoveryPolicy
from robot_agent.storage.sqlite import SQLiteTaskRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Robot Agent development CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="Run a deterministic multi-step demo")
    demo.add_argument(
        "--database",
        type=Path,
        default=Path("data/tasks.db"),
        help="SQLite database path",
    )

    control_demo = subparsers.add_parser(
        "control-demo",
        help="Demonstrate cooperative pause and resume",
    )
    control_demo.add_argument(
        "--database",
        type=Path,
        default=Path("data/tasks.db"),
        help="SQLite database path",
    )

    show = subparsers.add_parser("show", help="Show one persisted task and its events")
    show.add_argument("task_id", help="Task UUID printed by a demo command")
    show.add_argument(
        "--database",
        type=Path,
        default=Path("data/tasks.db"),
        help="SQLite database path",
    )

    agent_demo = subparsers.add_parser(
        "agent-demo",
        help="Plan and execute a natural-language request through LangGraph",
    )
    agent_demo.add_argument("request", help="Natural-language robot request")
    agent_demo.add_argument(
        "--planner",
        choices=("rule", "openai", "siliconflow"),
        default="rule",
        help="Use the offline, OpenAI, or SiliconFlow structured planner",
    )
    agent_demo.add_argument(
        "--max-replans",
        type=int,
        default=1,
        help="Maximum number of observation-driven replans",
    )
    agent_demo.add_argument(
        "--max-total-steps",
        type=int,
        default=12,
        help="Maximum steps across the initial plan and all replans",
    )
    agent_demo.add_argument(
        "--locations",
        type=Path,
        default=Path("config/locations.json"),
        help="Semantic location catalog",
    )
    agent_demo.add_argument(
        "--database",
        type=Path,
        default=Path("data/agent_tasks.db"),
        help="SQLite database path",
    )
    agent_demo.add_argument(
        "--recovery-config",
        type=Path,
        default=Path("config/recovery.json"),
        help="Bounded retry and human-intervention policy",
    )
    return parser


async def run_demo(database_path: Path) -> Task:
    repository = SQLiteTaskRepository(database_path)
    robot = FakeRobotAdapter(delay_seconds=0.05)
    manager = MissionManager(repository, robot)

    task = manager.create_task(
        "Inspect two indoor locations and return to the start",
        [
            TaskStepSpec(
                action="navigate_to",
                parameters={"location": "laboratory_door"},
            ),
            TaskStepSpec(
                action="inspect",
                parameters={"target": "person"},
            ),
            TaskStepSpec(
                action="navigate_to",
                parameters={"location": "meeting_room"},
            ),
            TaskStepSpec(
                action="inspect",
                parameters={"target": "chair"},
            ),
            TaskStepSpec(
                action="navigate_to",
                parameters={"location": "start"},
            ),
        ],
    )
    return await manager.execute_task(task.id)


async def run_control_demo(database_path: Path) -> tuple[Task, list[TaskEvent]]:
    repository = SQLiteTaskRepository(database_path)
    robot = FakeRobotAdapter(delay_seconds=0.2)
    manager = MissionManager(repository, robot)
    task = manager.create_task(
        "Pause, resume, and finish a simulated inspection",
        [
            TaskStepSpec(
                action="navigate_to",
                parameters={"location": "laboratory_door"},
            ),
            TaskStepSpec(
                action="inspect",
                parameters={"target": "person"},
            ),
        ],
    )

    execution = asyncio.create_task(manager.execute_task(task.id))
    while not robot.is_executing:
        await asyncio.sleep(0.005)
    paused = await manager.pause_task(task.id)
    await execution
    print("After pause:")
    print_task_summary(paused)

    completed = await manager.resume_task(task.id)
    return completed, manager.get_events(task.id)


async def run_agent_demo(
    request: str,
    database_path: Path,
    locations_path: Path,
    planner_name: str,
    recovery_config_path: Path,
    max_replans: int = 1,
    max_total_steps: int = 12,
) -> AgentRunResult:
    locations = LocationCatalog.from_json(locations_path)
    tools = ToolRegistry(locations)
    if planner_name == "openai":
        planner = OpenAIPlanner(locations, tools)
    elif planner_name == "siliconflow":
        planner = SiliconFlowPlanner(locations, tools)
    else:
        planner = RuleBasedPlanner(locations)
    manager = MissionManager(
        SQLiteTaskRepository(database_path),
        FakeRobotAdapter(delay_seconds=0.02),
        recovery_policy=RecoveryPolicy(
            RecoveryConfig.from_json(recovery_config_path)
        ),
    )
    runner = AgentRunner(
        build_agent_graph(
            planner,
            tools,
            manager,
            replanner=PerceptionFallbackReplanner(),
            budget=ExecutionBudget(
                max_replans=max_replans,
                max_total_steps=max_total_steps,
            ),
        )
    )
    return await runner.run(request)


def print_task_summary(task: Task) -> None:
    print(f"Task ID: {task.id}")
    print(f"Task status: {task.status.value}")
    for step in task.steps:
        print(
            f"  [{step.position}] {step.action:<12} "
            f"status={step.status.value:<9} result={step.result} error={step.error}"
        )


def print_events(events: list[TaskEvent]) -> None:
    print("Events:")
    for event in events:
        print(
            f"  #{event.id} {event.created_at.isoformat()} "
            f"{event.level.value:<7} {event.event_type.value:<20} {event.message}"
        )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    configure_logging()
    args = build_parser().parse_args()
    if args.command == "demo":
        task = asyncio.run(run_demo(args.database))
        print_task_summary(task)
    elif args.command == "control-demo":
        task, events = asyncio.run(run_control_demo(args.database))
        print("After resume:")
        print_task_summary(task)
        print_events(events)
    elif args.command == "show":
        repository = SQLiteTaskRepository(args.database)
        manager = MissionManager(repository, FakeRobotAdapter())
        print_task_summary(manager.get_task(args.task_id))
        print_events(manager.get_events(args.task_id))
    elif args.command == "agent-demo":
        result = asyncio.run(
            run_agent_demo(
                args.request,
                args.database,
                args.locations,
                args.planner,
                args.recovery_config,
                args.max_replans,
                args.max_total_steps,
            )
        )
        print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()

