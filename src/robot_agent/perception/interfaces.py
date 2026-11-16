"""Ports separating ROS image capture from object-detection inference."""

from __future__ import annotations

from abc import ABC, abstractmethod

from robot_agent.perception.models import CapturedFrame, DetectionResult


class CameraSource(ABC):
    @abstractmethod
    async def capture(self, *, timeout_seconds: float) -> CapturedFrame:
        """Return the latest available frame or raise on timeout."""


class ObjectDetector(ABC):
    @abstractmethod
    async def detect(
        self,
        frame: CapturedFrame,
        *,
        targets: list[str],
        confidence_threshold: float,
    ) -> DetectionResult:
        """Detect requested target classes in a captured frame."""

