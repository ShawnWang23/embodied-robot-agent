"""Deterministic in-process robot adapter for development and tests."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from robot_agent.core.interfaces import RobotAdapter
from robot_agent.core.models import RobotActionResult, TaskStep


class FakeRobotAdapter(RobotAdapter):
    """Simulate actions without ROS2, hardware, or nondeterministic behavior."""

    def __init__(
        self,
        *,
        delay_seconds: float = 0.0,
        failures: dict[str, str] | None = None,
        scripted_results: dict[str, Sequence[RobotActionResult]] | None = None,
    ) -> None:
        self._delay_seconds = delay_seconds
        self._failures = failures or {}
        self._scripted_results = {
            action: list(results)
            for action, results in (scripted_results or {}).items()
        }
        self._cancel_event = asyncio.Event()
        self._is_executing = False
        self.executed_actions: list[str] = []
        self.executed_steps: list[TaskStep] = []

    @property
    def is_executing(self) -> bool:
        """Expose deterministic execution state for demos and tests."""

        return self._is_executing

    async def execute(self, step: TaskStep) -> RobotActionResult:
        self._cancel_event = asyncio.Event()
        self._is_executing = True
        self.executed_actions.append(step.action)
        self.executed_steps.append(step.model_copy(deep=True))
        try:
            if self._delay_seconds > 0:
                try:
                    await asyncio.wait_for(
                        self._cancel_event.wait(),
                        timeout=self._delay_seconds,
                    )
                except TimeoutError:
                    pass
                else:
                    return RobotActionResult(
                        success=False,
                        message="Fake action cancelled by request",
                        error_code="cancelled",
                    )

            scripted = self._scripted_results.get(step.action)
            if scripted:
                return scripted.pop(0)

            if step.action in self._failures:
                return RobotActionResult(
                    success=False,
                    message=self._failures[step.action],
                    error_code="action_failed",
                )

            return RobotActionResult(
                success=True,
                message=f"Fake action '{step.action}' completed",
                data={"action": step.action, "parameters": step.parameters},
            )
        finally:
            self._is_executing = False

    async def cancel_current_action(self) -> bool:
        if not self._is_executing:
            return False
        self._cancel_event.set()
        return True

