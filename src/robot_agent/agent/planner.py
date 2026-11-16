"""Pluggable task planners for deterministic tests and OpenAI Structured Outputs."""

from __future__ import annotations

import os
from typing import Any, Protocol

from robot_agent.agent.locations import LocationCatalog
from robot_agent.agent.models import (
    CaptureImagePlanStep,
    DetectObjectsPlanStep,
    GetRobotStatusPlanStep,
    NavigateToPlanStep,
    TaskPlan,
)
from robot_agent.agent.tools import ToolRegistry
from robot_agent.core.exceptions import PlanningError


class TaskPlanner(Protocol):
    async def plan(self, user_request: str) -> TaskPlan:
        """Convert one natural-language request into a structured plan."""


class RuleBasedPlanner:
    """Small transparent planner used for offline development and tests."""

    _CAPTURE_TERMS = (
        "检查",
        "观察",
        "拍照",
        "识别",
        "有人",
        "椅子",
        "inspect",
        "detect",
        "camera",
        "person",
        "chair",
    )
    _TARGET_TERMS = {
        "person": ("是否有人", "有人", "人员", "person", "people"),
        "chair": ("椅子", "chair", "chairs"),
    }
    _STATUS_TERMS = ("状态", "位置", "status", "where are you")

    def __init__(self, locations: LocationCatalog) -> None:
        self._locations = locations

    async def plan(self, user_request: str) -> TaskPlan:
        normalized = user_request.casefold()
        matches: list[tuple[int, str]] = []
        for location in self._locations.locations:
            positions = [
                normalized.find(candidate.casefold())
                for candidate in [location.name, *location.aliases]
                if candidate.casefold() in normalized
            ]
            if positions:
                matches.append((min(positions), location.name))
        matches.sort()

        asks_for_status = any(term in normalized for term in self._STATUS_TERMS)
        asks_for_perception = any(
            term in normalized for term in self._CAPTURE_TERMS
        )
        if not matches and not asks_for_perception and not asks_for_status:
            raise PlanningError("No known location was found in the request")

        steps = []
        segments: list[tuple[str | None, str]] = []
        if matches:
            for index, (position, location_name) in enumerate(matches):
                end = matches[index + 1][0] if index + 1 < len(matches) else len(normalized)
                segments.append((location_name, normalized[position:end]))
        else:
            segments.append((None, normalized))

        for location_name, segment in segments:
            if location_name is not None:
                steps.append(
                    NavigateToPlanStep(
                        action="navigate_to",
                        location=location_name,
                        reason=f"The user requested visiting {location_name}",
                        timeout_seconds=60.0,
                    )
                )
            targets = [
                target
                for target, terms in self._TARGET_TERMS.items()
                if any(term in segment for term in terms)
            ]
            segment_requests_perception = any(
                term in segment for term in self._CAPTURE_TERMS
            )
            if segment_requests_perception:
                steps.append(
                    CaptureImagePlanStep(
                        action="capture_image",
                        reason="The user requested visual inspection",
                    )
                )
            if targets:
                steps.append(
                    DetectObjectsPlanStep(
                        action="detect_objects",
                        targets=targets,
                        reason="Detect the objects requested by the user",
                    )
                )
        if asks_for_status:
            steps.append(
                GetRobotStatusPlanStep(
                    action="get_robot_status",
                    reason="The user requested the robot's current status",
                    timeout_seconds=10.0,
                )
            )
        return TaskPlan(
            objective=user_request,
            steps=steps,
            unsupported_requirements=[],
        )


class OpenAIPlanner:
    """OpenAI Responses API planner using a native Pydantic output schema."""

    def __init__(
        self,
        locations: LocationCatalog,
        tools: ToolRegistry,
        *,
        model: str | None = None,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        if client is None:
            try:
                from openai import AsyncOpenAI
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "Install the LLM extra with 'uv sync --extra llm'"
                ) from exc

            resolved_key = api_key or os.getenv("OPENAI_API_KEY")
            if not resolved_key:
                raise RuntimeError("OPENAI_API_KEY is not configured")
            client = AsyncOpenAI(api_key=resolved_key)
        self._client = client
        self._model = model or os.getenv("OPENAI_MODEL", "gpt-6-astra")
        self._system_prompt = _build_system_prompt(locations, tools)

    async def plan(self, user_request: str) -> TaskPlan:
        response = await self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_request},
            ],
            text_format=TaskPlan,
            store=False,
        )
        if response.status != "completed":
            raise PlanningError(f"OpenAI response ended with status '{response.status}'")
        if response.output_parsed is None:
            raise PlanningError("OpenAI returned no structured plan")
        return response.output_parsed


class SiliconFlowPlanner:
    """SiliconFlow planner using its OpenAI-compatible Chat Completions API."""

    def __init__(
        self,
        locations: LocationCatalog,
        tools: ToolRegistry,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any | None = None,
    ) -> None:
        if client is None:
            try:
                from openai import AsyncOpenAI
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "Install the LLM extra with 'uv sync --extra llm'"
                ) from exc

            resolved_key = api_key or os.getenv("SILICONFLOW_API_KEY")
            if not resolved_key:
                raise RuntimeError("SILICONFLOW_API_KEY is not configured")
            client = AsyncOpenAI(
                api_key=resolved_key,
                base_url=base_url
                or os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
            )
        self._client = client
        self._model = model or os.getenv(
            "SILICONFLOW_MODEL",
            "deepseek-ai/DeepSeek-V4-Flash",
        )
        self._system_prompt = _build_system_prompt(locations, tools)

    async def plan(self, user_request: str) -> TaskPlan:
        completion = await self._client.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_request},
            ],
            response_format=TaskPlan,
        )
        if not completion.choices:
            raise PlanningError("SiliconFlow returned no completion choices")
        choice = completion.choices[0]
        if choice.finish_reason != "stop":
            raise PlanningError(
                f"SiliconFlow completion ended with reason '{choice.finish_reason}'"
            )
        if choice.message.parsed is None:
            raise PlanningError("SiliconFlow returned no structured plan")
        return choice.message.parsed


def _build_system_prompt(
    locations: LocationCatalog,
    tools: ToolRegistry,
) -> str:
    return f"""You plan safe indoor robot missions.
Return a complete TaskPlan and nothing outside its schema.
Never generate coordinates, velocities, shell commands, or unregistered tools.
Use only these tools:
{tools.planner_description()}

These tool names are reserved but not implemented yet. If the request needs
one of them, list that requirement in unsupported_requirements:
{tools.unavailable_description()}

Use only canonical location names from this catalog:
{locations.planner_description()}

If any requested capability cannot be completed with those tools, list it in
unsupported_requirements. Do not silently omit an unsupported requirement.
Only list an unsupported capability when the user explicitly requires it.
Do not infer report_result, human intervention, or cancellation from an ordinary
navigation or inspection request.
Preserve the user's requested visit order. Keep plans to at most 20 steps.
"""

