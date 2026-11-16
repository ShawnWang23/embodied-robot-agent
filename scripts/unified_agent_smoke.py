"""Run navigation, camera, YOLO and closed-loop replanning in one ROS2 world."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

import cv2

from robot_agent.adapters.ros2_robot import MapBounds, ROS2RobotAdapter
from robot_agent.agent.graph import AgentRunner, build_agent_graph
from robot_agent.agent.locations import LocationCatalog
from robot_agent.agent.planner import RuleBasedPlanner
from robot_agent.agent.replanning import (
    ExecutionBudget,
    PerceptionFallbackReplanner,
)
from robot_agent.agent.tools import ToolRegistry
from robot_agent.mission.manager import MissionManager
from robot_agent.perception.adapter import CapabilityRouterAdapter, PerceptionAdapter
from robot_agent.perception.camera import ROS2CameraSource
from robot_agent.perception.detector import UltralyticsYOLODetector
from robot_agent.storage.sqlite import SQLiteTaskRepository


async def run(args: argparse.Namespace) -> dict[str, object]:
    locations = LocationCatalog.from_json(args.locations)
    tools = ToolRegistry(locations)
    detector = UltralyticsYOLODetector(str(args.model), device="cpu")
    with ROS2CameraSource(topic=args.camera_topic) as camera:
        preview = await camera.capture(timeout_seconds=30.0)
        args.camera_output.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(args.camera_output), preview.image):
            raise RuntimeError("Could not save the unified simulation frame")

        robot = ROS2RobotAdapter(
            map_bounds=MapBounds(min_x=-3.0, max_x=3.0, min_y=-2.0, max_y=2.0)
        )
        try:
            router = CapabilityRouterAdapter(
                robot,
                PerceptionAdapter(camera, detector),
            )
            with tempfile.TemporaryDirectory(prefix="robot-agent-unified-") as temp:
                manager = MissionManager(
                    SQLiteTaskRepository(Path(temp) / "tasks.db"),
                    router,
                )
                runner = AgentRunner(
                    build_agent_graph(
                        RuleBasedPlanner(locations),
                        tools,
                        manager,
                        replanner=PerceptionFallbackReplanner(),
                        budget=ExecutionBudget(
                            max_replans=1,
                            max_total_steps=12,
                        ),
                    )
                )
                result = await runner.run(
                    "去实验室门口检查是否有人，然后返回起点",
                    thread_id="unified-nav-perception-smoke",
                )
        finally:
            robot.close()

    if result.status != "completed" or result.goal_satisfied is not True:
        raise RuntimeError(f"Unified closed-loop mission failed: {result}")
    if result.executed_step_count < 4:
        raise RuntimeError("Unified mission did not execute the expected capabilities")

    payload = result.model_dump(mode="json")
    args.result_output.parent.mkdir(parents=True, exist_ok=True)
    args.result_output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        type=Path,
        default=Path.home() / ".cache/robot-agent/models/yolo26n.pt",
    )
    parser.add_argument(
        "--locations",
        type=Path,
        default=Path("config/locations.json"),
    )
    parser.add_argument("--camera-topic", default="/camera/image_raw")
    parser.add_argument(
        "--camera-output",
        type=Path,
        default=Path("artifacts/unified/camera.jpg"),
    )
    parser.add_argument(
        "--result-output",
        type=Path,
        default=Path("artifacts/unified/result.json"),
    )
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

