"""Run three online planner acceptance cases without starting a real robot."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from robot_agent.adapters.fake_robot import FakeRobotAdapter
from robot_agent.agent.graph import AgentRunner, build_agent_graph
from robot_agent.agent.locations import LocationCatalog
from robot_agent.agent.planner import OpenAIPlanner, SiliconFlowPlanner
from robot_agent.agent.tools import ToolRegistry
from robot_agent.mission.manager import MissionManager
from robot_agent.storage.sqlite import SQLiteTaskRepository


async def run(provider: str) -> None:
    locations = LocationCatalog.from_json("config/locations.json")
    tools = ToolRegistry(locations)
    planner = (
        SiliconFlowPlanner(locations, tools)
        if provider == "siliconflow"
        else OpenAIPlanner(locations, tools)
    )
    robot = FakeRobotAdapter()

    with tempfile.TemporaryDirectory() as temporary_directory:
        manager = MissionManager(
            SQLiteTaskRepository(Path(temporary_directory) / "llm-acceptance.db"),
            robot,
        )
        runner = AgentRunner(build_agent_graph(planner, tools, manager))

        normal = await runner.run(
            "请先去实验室门口，然后去会议室，最后返回起点",
            thread_id=f"{provider}-normal",
        )
        if normal.status != "completed":
            raise RuntimeError(f"normal planning case failed: {normal}")
        normal_locations = [
            step.location
            for step in normal.plan.steps
            if hasattr(step, "location")
        ] if normal.plan else []
        if normal_locations != ["laboratory_door", "meeting_room", "start"]:
            raise RuntimeError(f"unexpected normal plan: {normal_locations}")

        executed_after_normal = len(robot.executed_actions)
        unknown = await runner.run(
            "请去地图上不存在的月球实验室",
            thread_id=f"{provider}-unknown",
        )
        if unknown.status != "failed":
            raise RuntimeError(f"unknown location was not rejected: {unknown}")
        if len(robot.executed_actions) != executed_after_normal:
            raise RuntimeError("unknown location reached RobotAdapter")

        perception = await runner.run(
            "去实验室门口拍照并检查是否有人",
            thread_id=f"{provider}-perception",
        )
        if perception.status != "completed":
            raise RuntimeError(f"perception planning case failed: {perception}")
        perception_actions = robot.executed_actions[executed_after_normal:]
        if perception_actions != [
            "navigate_to",
            "capture_image",
            "detect_objects",
        ]:
            raise RuntimeError(
                f"unexpected perception actions: {perception_actions}"
            )

        print(
            json.dumps(
                {
                    "provider": provider,
                    "normal": normal.model_dump(mode="json"),
                    "unknown": unknown.model_dump(mode="json"),
                    "perception": perception.model_dump(mode="json"),
                    "robot_actions_executed": robot.executed_actions,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("openai", "siliconflow"), required=True)
    args = parser.parse_args()
    asyncio.run(run(args.provider))


if __name__ == "__main__":
    main()

