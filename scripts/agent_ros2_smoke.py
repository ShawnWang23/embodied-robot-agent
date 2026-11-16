"""Run a natural-language LangGraph mission on a live TurtleBot3 simulation."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from robot_agent.adapters.ros2_robot import MapBounds, ROS2RobotAdapter
from robot_agent.agent.graph import AgentRunner, build_agent_graph
from robot_agent.agent.locations import LocationCatalog
from robot_agent.agent.planner import RuleBasedPlanner
from robot_agent.agent.tools import ToolRegistry
from robot_agent.mission.manager import MissionManager
from robot_agent.storage.sqlite import SQLiteTaskRepository


async def run() -> None:
    locations = LocationCatalog.from_json("config/locations.json")
    tools = ToolRegistry(locations)
    planner = RuleBasedPlanner(locations)
    robot = ROS2RobotAdapter(
        map_bounds=MapBounds(min_x=-3.0, max_x=3.0, min_y=-2.0, max_y=2.0)
    )
    try:
        with tempfile.TemporaryDirectory() as temporary_directory:
            manager = MissionManager(
                SQLiteTaskRepository(Path(temporary_directory) / "agent.db"),
                robot,
            )
            runner = AgentRunner(build_agent_graph(planner, tools, manager))
            result = await runner.run(
                "请先去实验室门口，然后返回起点",
                thread_id="phase3-ros2-smoke",
            )
            if result.status != "completed" or result.task is None:
                raise RuntimeError(f"LangGraph mission failed: {result}")
            locations_in_plan = [
                step.location
                for step in result.plan.steps
                if hasattr(step, "location")
            ] if result.plan else []
            if locations_in_plan != ["laboratory_door", "start"]:
                raise RuntimeError(f"Unexpected plan order: {locations_in_plan}")
            print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    finally:
        robot.close()


if __name__ == "__main__":
    asyncio.run(run())

