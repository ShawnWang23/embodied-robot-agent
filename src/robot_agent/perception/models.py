"""Validated perception inputs and outputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from robot_agent.core.models import utc_now


class ImageMetadata(BaseModel):
    """Serializable description of one captured image frame."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    frame_id: str = Field(default_factory=lambda: str(uuid4()))
    source: str = Field(min_length=1, max_length=200)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    encoding: str = Field(default="bgr8", min_length=1, max_length=50)
    captured_at: datetime = Field(default_factory=utc_now)


@dataclass(frozen=True)
class CapturedFrame:
    """Runtime image plus metadata; raw pixels are never persisted in a Task."""

    metadata: ImageMetadata
    image: Any


class BoundingBox(BaseModel):
    """Pixel-space XYXY bounding box."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    x1: float = Field(ge=0)
    y1: float = Field(ge=0)
    x2: float = Field(ge=0)
    y2: float = Field(ge=0)

    @model_validator(mode="after")
    def require_ordered_corners(self) -> "BoundingBox":
        if self.x2 < self.x1 or self.y2 < self.y1:
            raise ValueError("bounding box maximums must not be below minimums")
        return self


class ObjectDetection(BaseModel):
    """One normalized YOLO detection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    class_id: int = Field(ge=0)
    label: str = Field(min_length=1, max_length=200)
    confidence: float = Field(ge=0, le=1)
    bounding_box: BoundingBox


class DetectionResult(BaseModel):
    """Structured result returned to the mission and Agent layers."""

    model_config = ConfigDict(extra="forbid")

    frame: ImageMetadata
    model_name: str = Field(min_length=1, max_length=500)
    requested_targets: list[str] = Field(default_factory=list, max_length=50)
    confidence_threshold: float = Field(ge=0, le=1)
    detections: list[ObjectDetection] = Field(default_factory=list)
    target_presence: dict[str, bool] = Field(default_factory=dict)
    inference_milliseconds: float = Field(ge=0)

