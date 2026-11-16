"""Fake and Ultralytics YOLO object detectors."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from typing import Any

from robot_agent.perception.interfaces import ObjectDetector
from robot_agent.perception.models import (
    BoundingBox,
    CapturedFrame,
    DetectionResult,
    ObjectDetection,
)


class FakeObjectDetector(ObjectDetector):
    """Return deterministic detections for Agent and recovery tests."""

    def __init__(
        self,
        detections: Sequence[ObjectDetection] = (),
        *,
        failure: Exception | None = None,
    ) -> None:
        self._detections = list(detections)
        self._failure = failure
        self.detect_count = 0

    async def detect(
        self,
        frame: CapturedFrame,
        *,
        targets: list[str],
        confidence_threshold: float,
    ) -> DetectionResult:
        self.detect_count += 1
        if self._failure is not None:
            raise self._failure
        normalized_targets = {target.casefold(): target for target in targets}
        detections = [
            item
            for item in self._detections
            if item.confidence >= confidence_threshold
            and (not targets or item.label.casefold() in normalized_targets)
        ]
        present_labels = {item.label.casefold() for item in detections}
        return DetectionResult(
            frame=frame.metadata,
            model_name="fake-detector",
            requested_targets=targets,
            confidence_threshold=confidence_threshold,
            detections=detections,
            target_presence={
                target: target.casefold() in present_labels for target in targets
            },
            inference_milliseconds=0.0,
        )


class UltralyticsYOLODetector(ObjectDetector):
    """Run a pretrained Ultralytics detector on OpenCV BGR frames."""

    def __init__(
        self,
        model_name: str = "yolo26n.pt",
        *,
        device: str = "cpu",
        model: Any | None = None,
    ) -> None:
        if model is None:
            try:
                from ultralytics import YOLO
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "Install the perception dependencies before using YOLO"
                ) from exc
            model = YOLO(model_name)
        self._model = model
        self._model_name = model_name
        self._device = device

    async def detect(
        self,
        frame: CapturedFrame,
        *,
        targets: list[str],
        confidence_threshold: float,
    ) -> DetectionResult:
        if not 0 <= confidence_threshold <= 1:
            raise ValueError("confidence_threshold must be between 0 and 1")
        return await asyncio.to_thread(
            self._detect_sync,
            frame,
            targets,
            confidence_threshold,
        )

    def _detect_sync(
        self,
        frame: CapturedFrame,
        targets: list[str],
        confidence_threshold: float,
    ) -> DetectionResult:
        started = time.perf_counter()
        names = self._normalized_names()
        requested = {target.casefold(): target for target in targets}
        class_ids = [
            class_id
            for class_id, label in names.items()
            if not targets or label.casefold() in requested
        ]
        if targets and not class_ids:
            available = ", ".join(sorted(names.values()))
            raise ValueError(
                f"None of the requested targets are supported by the model. "
                f"Available classes: {available}"
            )

        results = self._model.predict(
            source=frame.image,
            conf=confidence_threshold,
            classes=class_ids or None,
            device=self._device,
            verbose=False,
        )
        if not results:
            raise RuntimeError("YOLO returned no result for the image")
        result = results[0]
        detections: list[ObjectDetection] = []
        boxes = result.boxes
        if boxes is not None:
            coordinates = boxes.xyxy.cpu().tolist()
            confidences = boxes.conf.cpu().tolist()
            classes = boxes.cls.cpu().tolist()
            for xyxy, confidence, raw_class_id in zip(
                coordinates,
                confidences,
                classes,
                strict=True,
            ):
                class_id = int(raw_class_id)
                label = names[class_id]
                detections.append(
                    ObjectDetection(
                        class_id=class_id,
                        label=label,
                        confidence=float(confidence),
                        bounding_box=BoundingBox(
                            x1=float(xyxy[0]),
                            y1=float(xyxy[1]),
                            x2=float(xyxy[2]),
                            y2=float(xyxy[3]),
                        ),
                    )
                )

        present_labels = {item.label.casefold() for item in detections}
        elapsed_ms = (time.perf_counter() - started) * 1_000
        return DetectionResult(
            frame=frame.metadata,
            model_name=self._model_name,
            requested_targets=targets,
            confidence_threshold=confidence_threshold,
            detections=detections,
            target_presence={
                target: target.casefold() in present_labels for target in targets
            },
            inference_milliseconds=elapsed_ms,
        )

    def _normalized_names(self) -> dict[int, str]:
        raw_names = self._model.names
        if isinstance(raw_names, dict):
            return {int(key): str(value) for key, value in raw_names.items()}
        return {index: str(value) for index, value in enumerate(raw_names)}

