"""Mission-compatible adapters for camera capture and detection."""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from robot_agent.core.interfaces import RobotAdapter
from robot_agent.core.models import RobotActionResult, TaskStep
from robot_agent.perception.interfaces import CameraSource, ObjectDetector
from robot_agent.perception.models import CapturedFrame


class CaptureImageParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera: str = Field(default="front", pattern="^front$")


class DetectObjectsParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targets: list[str] = Field(min_length=1, max_length=20)
    confidence_threshold: float = Field(default=0.25, ge=0, le=1)


class PerceptionAdapter(RobotAdapter):
    """Expose capture_image and detect_objects as validated mission actions."""

    def __init__(self, camera: CameraSource, detector: ObjectDetector) -> None:
        self._camera = camera
        self._detector = detector
        self._latest_frame: CapturedFrame | None = None
        self._active_task: asyncio.Task[Any] | None = None

    async def execute(self, step: TaskStep) -> RobotActionResult:
        self._active_task = asyncio.current_task()
        try:
            if step.action == "capture_image":
                return await self._capture(step)
            if step.action == "detect_objects":
                return await self._detect(step)
            return RobotActionResult(
                success=False,
                message=f"Unsupported perception action '{step.action}'",
                error_code="unsupported_action",
            )
        except asyncio.CancelledError:
            return RobotActionResult(
                success=False,
                message="Perception action cancelled by request",
                error_code="cancelled",
            )
        finally:
            self._active_task = None

    async def _capture(self, step: TaskStep) -> RobotActionResult:
        try:
            CaptureImageParameters.model_validate(step.parameters)
            frame = await self._camera.capture(
                timeout_seconds=step.timeout_seconds,
            )
            self._latest_frame = frame
            return RobotActionResult(
                success=True,
                message="Camera frame captured",
                data={"frame": frame.metadata.model_dump(mode="json")},
            )
        except (ValidationError, ValueError) as exc:
            return RobotActionResult(
                success=False,
                message=f"Invalid capture_image parameters: {exc}",
                error_code="invalid_parameters",
            )
        except TimeoutError as exc:
            return RobotActionResult(
                success=False,
                message=str(exc),
                error_code="camera_unavailable",
            )
        except Exception as exc:
            return RobotActionResult(
                success=False,
                message=f"Camera capture failed: {exc}",
                error_code="camera_unavailable",
            )

    async def _detect(self, step: TaskStep) -> RobotActionResult:
        try:
            parameters = DetectObjectsParameters.model_validate(step.parameters)
            if self._latest_frame is None:
                self._latest_frame = await self._camera.capture(
                    timeout_seconds=step.timeout_seconds,
                )
            result = await self._detector.detect(
                self._latest_frame,
                targets=parameters.targets,
                confidence_threshold=parameters.confidence_threshold,
            )
            return RobotActionResult(
                success=True,
                message=f"Detected {len(result.detections)} matching objects",
                data=result.model_dump(mode="json"),
            )
        except (ValidationError, ValueError) as exc:
            return RobotActionResult(
                success=False,
                message=f"Invalid detect_objects request: {exc}",
                error_code="invalid_parameters",
            )
        except TimeoutError as exc:
            return RobotActionResult(
                success=False,
                message=str(exc),
                error_code="camera_unavailable",
            )
        except Exception as exc:
            return RobotActionResult(
                success=False,
                message=f"Object detection failed: {exc}",
                error_code="detection_failed",
            )

    async def cancel_current_action(self) -> bool:
        if self._active_task is None or self._active_task.done():
            return False
        self._active_task.cancel()
        return True


class CapabilityRouterAdapter(RobotAdapter):
    """Route mission actions without coupling navigation and perception."""

    _PERCEPTION_ACTIONS = frozenset({"capture_image", "detect_objects"})

    def __init__(
        self,
        robot: RobotAdapter,
        perception: PerceptionAdapter,
    ) -> None:
        self._robot = robot
        self._perception = perception
        self._active: RobotAdapter | None = None

    async def execute(self, step: TaskStep) -> RobotActionResult:
        adapter: RobotAdapter = (
            self._perception
            if step.action in self._PERCEPTION_ACTIONS
            else self._robot
        )
        self._active = adapter
        try:
            return await adapter.execute(step)
        finally:
            self._active = None

    async def cancel_current_action(self) -> bool:
        if self._active is None:
            return False
        return await self._active.cancel_current_action()

    def get_execution_feedback(self) -> dict[str, Any]:
        if self._active is None:
            return {}
        return self._active.get_execution_feedback()
