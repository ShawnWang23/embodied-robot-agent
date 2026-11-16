"""Ports that keep mission logic independent from ROS2 and simulation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from robot_agent.core.models import RobotActionResult, TaskStep


class RobotAdapter(ABC):
    """Minimal robot capability contract for the first Phase 1 increment."""

    @abstractmethod
    async def execute(self, step: TaskStep) -> RobotActionResult:
        """Execute one validated task step and return a normalized result."""

    @abstractmethod
    async def cancel_current_action(self) -> bool:
        """Request cancellation of the active action; report whether one existed."""

    def get_execution_feedback(self) -> dict[str, Any]:
        """Return the latest non-blocking execution feedback, when available."""

        return {}

