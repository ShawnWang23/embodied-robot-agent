"""Run LangGraph through real ROS2 camera capture and pretrained YOLO."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from robot_agent.adapters.fake_robot import FakeRobotAdapter
from robot_agent.agent.graph import AgentRunner, build_agent_graph
from robot_agent.agent.locations import LocationCatalog
from robot_agent.agent.planner import RuleBasedPlanner
from robot_agent.agent.tools import ToolRegistry
from robot_agent.mission.manager import MissionManager
from robot_agent.perception.adapter import CapabilityRouterAdapter, PerceptionAdapter
from robot_agent.perception.camera import ROS2CameraSource
from robot_agent.perception.detector import UltralyticsYOLODetector
from robot_agent.storage.sqlite import SQLiteTaskRepository


async def run(model_path: Path) -> dict[str, object]:
    locations = LocationCatalog.from_json(Path("config/locations.json"))
    tools = ToolRegistry(locations)
    detector = UltralyticsYOLODetector(str(model_path), device="cpu")
    with ROS2CameraSource(topic="/camera/image_raw") as camera:
        perception = PerceptionAdapter(camera, detector)
        router = CapabilityRouterAdapter(FakeRobotAdapter(), perception)
        with tempfile.TemporaryDirectory(prefix="robot-agent-phase5-") as temp:
            manager = MissionManager(
                SQLiteTaskRepository(Path(temp) / "agent.db"),
                router,
            )
            runner = AgentRunner(
                build_agent_graph(
                    RuleBasedPlanner(locations),
                    tools,
                    manager,
                )
            )
            result = await runner.run(
                "检查前方是否有人",
                thread_id="phase5-real-perception",
            )
    if result.status != "completed":
        raise RuntimeError(f"Agent perception task failed: {result.errors}")
    if result.perception_outcome not in {"objects_detected", "clear"}:
        raise RuntimeError("Agent did not take a perception outcome branch")
    return result.model_dump(mode="json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        type=Path,
        default=Path.home() / ".cache/robot-agent/models/yolo26n.pt",
    )
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.model)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
