"""Capture one ROS2 camera frame and run real pretrained YOLO inference."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import cv2
import ultralytics

from robot_agent.perception.camera import ROS2CameraSource
from robot_agent.perception.detector import UltralyticsYOLODetector
from robot_agent.perception.models import CapturedFrame, ImageMetadata


async def run(output_path: Path, model_path: Path) -> dict[str, object]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    detector = UltralyticsYOLODetector(str(model_path), device="cpu")

    with ROS2CameraSource(topic="/camera/image_raw") as camera:
        frame = await camera.capture(timeout_seconds=30)
    if not cv2.imwrite(str(output_path), frame.image):
        raise RuntimeError(f"Failed to save camera frame to {output_path}")
    camera_result = await detector.detect(
        frame,
        targets=["person", "chair"],
        confidence_threshold=0.25,
    )

    reference_path = Path(ultralytics.__file__).parent / "assets" / "bus.jpg"
    reference_image = cv2.imread(str(reference_path))
    if reference_image is None:
        raise RuntimeError(f"Ultralytics reference image missing: {reference_path}")
    reference_frame = CapturedFrame(
        metadata=ImageMetadata(
            source=str(reference_path),
            width=int(reference_image.shape[1]),
            height=int(reference_image.shape[0]),
        ),
        image=reference_image,
    )
    reference_result = await detector.detect(
        reference_frame,
        targets=["person"],
        confidence_threshold=0.25,
    )
    if not reference_result.target_presence["person"]:
        raise RuntimeError("YOLO failed to detect a person in its reference image")

    return {
        "camera": {
            "frame": frame.metadata.model_dump(mode="json"),
            "saved_to": str(output_path.resolve()),
            "detections": camera_result.model_dump(mode="json"),
        },
        "reference_positive_control": reference_result.model_dump(mode="json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/phase5_camera.jpg"),
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=Path.home() / ".cache/robot-agent/models/yolo26n.pt",
    )
    args = parser.parse_args()
    report = asyncio.run(run(args.output, args.model))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
