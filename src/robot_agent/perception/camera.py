"""Fake and ROS2 camera sources."""

from __future__ import annotations

import asyncio
import threading
from typing import Any
from uuid import uuid4

from robot_agent.perception.interfaces import CameraSource
from robot_agent.perception.models import CapturedFrame, ImageMetadata

try:
    import rclpy
    from cv_bridge import CvBridge
    from rclpy.context import Context
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import Image
except ModuleNotFoundError as exc:
    _ROS2_CAMERA_IMPORT_ERROR: ModuleNotFoundError | None = exc
else:
    _ROS2_CAMERA_IMPORT_ERROR = None


class FakeCameraSource(CameraSource):
    """Return deterministic in-memory frames for tests."""

    def __init__(
        self,
        image: Any,
        *,
        width: int = 640,
        height: int = 480,
        source: str = "fake/front",
    ) -> None:
        self._image = image
        self._width = width
        self._height = height
        self._source = source
        self.capture_count = 0

    async def capture(self, *, timeout_seconds: float) -> CapturedFrame:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.capture_count += 1
        return CapturedFrame(
            metadata=ImageMetadata(
                source=self._source,
                width=self._width,
                height=self._height,
            ),
            image=self._image,
        )


class ROS2CameraSource(CameraSource):
    """Subscribe to a ROS2 Image topic and expose the latest BGR frame."""

    def __init__(
        self,
        *,
        topic: str = "/camera/image_raw",
        node_name: str | None = None,
    ) -> None:
        if _ROS2_CAMERA_IMPORT_ERROR is not None:
            raise RuntimeError(
                "ROS2CameraSource requires sourced ROS2, sensor_msgs and cv_bridge"
            ) from _ROS2_CAMERA_IMPORT_ERROR
        if not topic.startswith("/"):
            raise ValueError("camera topic must be an absolute ROS2 topic")

        self._topic = topic
        self._bridge = CvBridge()
        self._lock = threading.Lock()
        self._frame_ready = threading.Event()
        self._latest: CapturedFrame | None = None
        self._callback_error: str | None = None
        self._closed = False

        self._context = Context()
        rclpy.init(context=self._context)
        resolved_name = node_name or f"robot_agent_camera_{uuid4().hex[:8]}"
        self._node = Node(resolved_name, context=self._context)
        self._subscription = self._node.create_subscription(
            Image,
            topic,
            self._on_image,
            QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_AVAILABLE),
        )
        self._executor = SingleThreadedExecutor(context=self._context)
        self._executor.add_node(self._node)

    async def capture(self, *, timeout_seconds: float) -> CapturedFrame:
        if self._closed:
            raise RuntimeError("ROS2 camera source is closed")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        while not self._frame_ready.is_set():
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(
                    f"No image received from {self._topic} within "
                    f"{timeout_seconds:g} seconds"
                )
            await asyncio.to_thread(
                self._executor.spin_once,
                timeout_sec=min(0.1, remaining),
            )
        with self._lock:
            if self._callback_error is not None:
                raise RuntimeError(self._callback_error)
            if self._latest is None:
                raise RuntimeError("camera signaled a frame without image data")
            return CapturedFrame(
                metadata=self._latest.metadata,
                image=self._latest.image.copy(),
            )

    def _on_image(self, message: Any) -> None:
        try:
            image = self._bridge.imgmsg_to_cv2(message, desired_encoding="bgr8")
            metadata = ImageMetadata(
                source=self._topic,
                width=int(message.width),
                height=int(message.height),
                encoding="bgr8",
            )
            frame = CapturedFrame(metadata=metadata, image=image)
            with self._lock:
                self._latest = frame
                self._callback_error = None
        except Exception as exc:
            with self._lock:
                self._callback_error = f"cv_bridge conversion failed: {exc}"
        finally:
            self._frame_ready.set()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(timeout_sec=2.0)
        self._executor.remove_node(self._node)
        self._node.destroy_node()
        self._context.try_shutdown()

    def __enter__(self) -> "ROS2CameraSource":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
