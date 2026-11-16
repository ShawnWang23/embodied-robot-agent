"""Deterministic tool registry between planner output and mission steps."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from robot_agent.agent.locations import LocationCatalog
from robot_agent.agent.models import (
    CaptureImagePlanStep,
    DetectObjectsPlanStep,
    GetRobotStatusPlanStep,
    NavigateToPlanStep,
    PlanStep,
    TaskPlan,
)
from robot_agent.core.exceptions import PlanValidationError
from robot_agent.core.models import TaskStepSpec

Compiler = Callable[[PlanStep], TaskStepSpec]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    compiler: Compiler


class CaptureImageArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    camera: str = "front"


class DetectObjectsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    targets: list[str] = Field(min_length=1, max_length=20)
    confidence_threshold: float = Field(default=0.25, ge=0, le=1)


class CancelTaskArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500)


class RequestHumanHelpArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500)


class ReportResultArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=2_000)


@dataclass(frozen=True)
class ReservedToolDefinition:
    name: Literal[
        "capture_image",
        "detect_objects",
        "cancel_task",
        "request_human_help",
        "report_result",
    ]
    arguments_model: type[BaseModel]
    available_in_phase: int


class ToolRegistry:
    """Compile only registered, validated plan actions into robot steps."""

    def __init__(self, locations: LocationCatalog) -> None:
        self._locations = locations
        self._tools: dict[str, ToolDefinition] = {
            "navigate_to": ToolDefinition(
                name="navigate_to",
                description="Navigate to one exact name from the location catalog.",
                compiler=self._compile_navigation,
            ),
            "get_robot_status": ToolDefinition(
                name="get_robot_status",
                description="Read the robot's latest deterministic status.",
                compiler=self._compile_status,
            ),
            "capture_image": ToolDefinition(
                name="capture_image",
                description="Capture one frame from the front camera.",
                compiler=self._compile_capture,
            ),
            "detect_objects": ToolDefinition(
                name="detect_objects",
                description=(
                    "Detect requested pretrained object classes in the latest frame."
                ),
                compiler=self._compile_detection,
            ),
        }
        self._reserved_tools = (
            ReservedToolDefinition("cancel_task", CancelTaskArguments, 4),
            ReservedToolDefinition("request_human_help", RequestHumanHelpArguments, 4),
            ReservedToolDefinition("report_result", ReportResultArguments, 4),
        )

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    @property
    def reserved_tool_names(self) -> tuple[str, ...]:
        return tuple(tool.name for tool in self._reserved_tools)

    def planner_description(self) -> str:
        return "\n".join(
            f"- {tool.name}: {tool.description}" for tool in self._tools.values()
        )

    def unavailable_description(self) -> str:
        return "\n".join(
            f"- {tool.name}: reserved for Phase {tool.available_in_phase}"
            for tool in self._reserved_tools
        )

    def compile_plan(self, plan: TaskPlan) -> list[TaskStepSpec]:
        if plan.unsupported_requirements:
            details = "; ".join(plan.unsupported_requirements)
            raise PlanValidationError(f"Plan requires unavailable capabilities: {details}")
        if not plan.steps:
            raise PlanValidationError("Plan must contain at least one executable step")

        compiled: list[TaskStepSpec] = []
        for step in plan.steps:
            definition = self._tools.get(step.action)
            if definition is None:
                raise PlanValidationError(f"Tool '{step.action}' is not registered")
            compiled.append(definition.compiler(step))
        return compiled

    def _compile_navigation(self, step: PlanStep) -> TaskStepSpec:
        if not isinstance(step, NavigateToPlanStep):
            raise PlanValidationError("navigate_to received the wrong argument schema")
        location = self._locations.resolve(step.location)
        fallback = self._locations.fallback_for(location)
        metadata: dict[str, object] = {"location": location.name}
        if fallback is not None:
            metadata["fallback_navigation"] = {
                "location": fallback.name,
                "parameters": {
                    "x": fallback.x,
                    "y": fallback.y,
                    "yaw": fallback.yaw,
                },
            }
        return TaskStepSpec(
            action="navigate_to",
            parameters={"x": location.x, "y": location.y, "yaw": location.yaw},
            metadata=metadata,
            timeout_seconds=step.timeout_seconds,
        )

    @staticmethod
    def _compile_status(step: PlanStep) -> TaskStepSpec:
        if not isinstance(step, GetRobotStatusPlanStep):
            raise PlanValidationError("get_robot_status received the wrong argument schema")
        return TaskStepSpec(
            action="get_robot_status",
            parameters={},
            timeout_seconds=step.timeout_seconds,
        )

    @staticmethod
    def _compile_capture(step: PlanStep) -> TaskStepSpec:
        if not isinstance(step, CaptureImagePlanStep):
            raise PlanValidationError("capture_image received the wrong argument schema")
        arguments = CaptureImageArguments(camera=step.camera)
        return TaskStepSpec(
            action="capture_image",
            parameters=arguments.model_dump(),
            timeout_seconds=step.timeout_seconds,
        )

    @staticmethod
    def _compile_detection(step: PlanStep) -> TaskStepSpec:
        if not isinstance(step, DetectObjectsPlanStep):
            raise PlanValidationError(
                "detect_objects received the wrong argument schema"
            )
        arguments = DetectObjectsArguments(
            targets=step.targets,
            confidence_threshold=step.confidence_threshold,
        )
        return TaskStepSpec(
            action="detect_objects",
            parameters=arguments.model_dump(),
            timeout_seconds=step.timeout_seconds,
        )

