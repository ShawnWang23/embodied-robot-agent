from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

import robot_agent.perception.camera as camera_module
from robot_agent.adapters.fake_robot import FakeRobotAdapter
from robot_agent.agent.graph import AgentRunner, build_agent_graph
from robot_agent.agent.locations import LocationCatalog
from robot_agent.agent.planner import RuleBasedPlanner
from robot_agent.agent.tools import ToolRegistry
from robot_agent.core.models import StepStatus, TaskStep
from robot_agent.mission.manager import MissionManager
from robot_agent.perception.adapter import CapabilityRouterAdapter, PerceptionAdapter
from robot_agent.perception.camera import FakeCameraSource, ROS2CameraSource
from robot_agent.perception.detector import FakeObjectDetector, UltralyticsYOLODetector
from robot_agent.perception.models import BoundingBox, ObjectDetection
from robot_agent.storage.sqlite import SQLiteTaskRepository


def detection(label: str, confidence: float = 0.9) -> ObjectDetection:
    return ObjectDetection(
        class_id=0,
        label=label,
        confidence=confidence,
        bounding_box=BoundingBox(x1=10, y1=20, x2=110, y2=220),
    )


def task_step(action: str, parameters: dict[str, object]) -> TaskStep:
    return TaskStep(action=action, parameters=parameters, position=0)


def test_bounding_box_rejects_reversed_coordinates() -> None:
    with pytest.raises(ValidationError, match="maximums"):
        BoundingBox(x1=100, y1=0, x2=10, y2=20)


@pytest.mark.asyncio
async def test_fake_detector_filters_targets_and_confidence() -> None:
    camera = FakeCameraSource(object())
    frame = await camera.capture(timeout_seconds=1)
    detector = FakeObjectDetector(
        [detection("person", 0.95), detection("chair", 0.2)]
    )

    result = await detector.detect(
        frame,
        targets=["person", "chair"],
        confidence_threshold=0.5,
    )

    assert [item.label for item in result.detections] == ["person"]
    assert result.target_presence == {"person": True, "chair": False}


@pytest.mark.asyncio
async def test_perception_adapter_captures_then_detects_structured_result() -> None:
    camera = FakeCameraSource(object(), width=320, height=240)
    detector = FakeObjectDetector([detection("chair")])
    adapter = PerceptionAdapter(camera, detector)

    captured = await adapter.execute(
        task_step("capture_image", {"camera": "front"})
    )
    detected = await adapter.execute(
        task_step(
            "detect_objects",
            {"targets": ["chair"], "confidence_threshold": 0.25},
        )
    )

    assert captured.success is True
    assert captured.data["frame"]["width"] == 320
    assert detected.success is True
    assert detected.data["target_presence"] == {"chair": True}
    assert detected.data["detections"][0]["label"] == "chair"
    assert camera.capture_count == 1
    assert detector.detect_count == 1


@pytest.mark.asyncio
async def test_detection_without_capture_gets_fresh_frame_automatically() -> None:
    camera = FakeCameraSource(object())
    detector = FakeObjectDetector([])
    adapter = PerceptionAdapter(camera, detector)

    result = await adapter.execute(
        task_step(
            "detect_objects",
            {"targets": ["person"], "confidence_threshold": 0.25},
        )
    )

    assert result.success is True
    assert result.data["target_presence"] == {"person": False}
    assert camera.capture_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("detections", "expected_outcome"),
    [([detection("person")], "objects_detected"), ([], "clear")],
)
async def test_langgraph_branches_on_detection_result(
    tmp_path: Path,
    detections: list[ObjectDetection],
    expected_outcome: str,
) -> None:
    locations = LocationCatalog.from_json(Path("config/locations.json"))
    tools = ToolRegistry(locations)
    robot = FakeRobotAdapter()
    perception = PerceptionAdapter(
        FakeCameraSource(object()),
        FakeObjectDetector(detections),
    )
    router = CapabilityRouterAdapter(robot, perception)
    manager = MissionManager(SQLiteTaskRepository(tmp_path / "agent.db"), router)
    runner = AgentRunner(
        build_agent_graph(RuleBasedPlanner(locations), tools, manager)
    )

    result = await runner.run("去实验室门口检查是否有人")

    assert result.status == "completed"
    assert result.perception_outcome == expected_outcome
    assert robot.executed_actions == ["navigate_to"]
    assert result.task is not None
    assert [step["action"] for step in result.task["steps"]] == [
        "navigate_to",
        "capture_image",
        "detect_objects",
    ]
    assert all(
        step["status"] == StepStatus.COMPLETED.value
        for step in result.task["steps"]
    )


@pytest.mark.asyncio
async def test_ultralytics_detector_normalizes_model_output() -> None:
    class FakeTensor:
        def __init__(self, values: list[object]) -> None:
            self._values = values

        def cpu(self) -> "FakeTensor":
            return self

        def tolist(self) -> list[object]:
            return self._values

    class FakeBoxes:
        xyxy = FakeTensor([[1.0, 2.0, 30.0, 40.0]])
        conf = FakeTensor([0.88])
        cls = FakeTensor([0.0])

    class FakeResult:
        boxes = FakeBoxes()

    class FakeModel:
        names = {0: "person", 1: "chair"}

        def __init__(self) -> None:
            self.arguments: dict[str, object] = {}

        def predict(self, **kwargs: object) -> list[FakeResult]:
            self.arguments = kwargs
            return [FakeResult()]

    model = FakeModel()
    detector = UltralyticsYOLODetector(
        "test.pt",
        model=model,
        device="cpu",
    )
    frame = await FakeCameraSource(object()).capture(timeout_seconds=1)

    result = await detector.detect(
        frame,
        targets=["person"],
        confidence_threshold=0.5,
    )

    assert result.target_presence == {"person": True}
    assert result.detections[0].confidence == pytest.approx(0.88)
    assert model.arguments["classes"] == [0]
    assert model.arguments["verbose"] is False


def test_ros2_camera_reports_missing_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        camera_module,
        "_ROS2_CAMERA_IMPORT_ERROR",
        ModuleNotFoundError("rclpy"),
    )
    with pytest.raises(RuntimeError, match="cv_bridge"):
        ROS2CameraSource()
