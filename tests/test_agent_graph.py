from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from robot_agent.adapters.fake_robot import FakeRobotAdapter
from robot_agent.agent.graph import AgentRunner, build_agent_graph
from robot_agent.agent.locations import LocationCatalog
from robot_agent.agent.models import NavigateToPlanStep, TaskPlan
from robot_agent.agent.planner import RuleBasedPlanner
from robot_agent.agent.replanning import (
    ExecutionBudget,
    PerceptionFallbackReplanner,
)
from robot_agent.agent.tools import ToolRegistry
from robot_agent.core.exceptions import PlanValidationError
from robot_agent.core.models import RobotActionResult, TaskStatus
from robot_agent.mission.manager import MissionManager
from robot_agent.storage.sqlite import SQLiteTaskRepository


@pytest.fixture
def locations() -> LocationCatalog:
    return LocationCatalog.from_json(Path("config/locations.json"))


def build_runner(
    tmp_path: Path,
    locations: LocationCatalog,
) -> tuple[AgentRunner, FakeRobotAdapter]:
    robot = FakeRobotAdapter()
    manager = MissionManager(SQLiteTaskRepository(tmp_path / "agent.db"), robot)
    tools = ToolRegistry(locations)
    graph = build_agent_graph(RuleBasedPlanner(locations), tools, manager)
    return AgentRunner(graph), robot


def test_location_catalog_resolves_alias_but_rejects_unknown(
    locations: LocationCatalog,
) -> None:
    assert locations.resolve("实验室门口").name == "laboratory_door"

    with pytest.raises(PlanValidationError, match="Unknown location"):
        locations.resolve("invented_room")


def test_plan_schema_rejects_unregistered_action() -> None:
    with pytest.raises(ValidationError):
        TaskPlan.model_validate(
            {
                "objective": "move unsafely",
                "steps": [
                    {
                        "action": "publish_cmd_vel",
                        "reason": "shortcut",
                        "timeout_seconds": 10,
                    }
                ],
                "unsupported_requirements": [],
            }
        )


def test_registry_reserves_future_tools(locations: LocationCatalog) -> None:
    registry = ToolRegistry(locations)

    assert registry.tool_names == (
        "navigate_to",
        "get_robot_status",
        "capture_image",
        "detect_objects",
    )
    assert registry.reserved_tool_names == (
        "cancel_task",
        "request_human_help",
        "report_result",
    )


async def test_graph_plans_validates_and_executes_locations_in_order(
    tmp_path: Path,
    locations: LocationCatalog,
) -> None:
    runner, robot = build_runner(tmp_path, locations)

    result = await runner.run(
        "请先去实验室门口，然后去会议室，最后返回起点",
        thread_id="successful-mission",
    )

    assert result.status == "completed"
    assert result.task is not None
    assert result.task["status"] == TaskStatus.COMPLETED.value
    assert robot.executed_actions == ["navigate_to", "navigate_to", "navigate_to"]
    assert result.plan is not None
    assert [step.location for step in result.plan.steps] == [
        "laboratory_door",
        "meeting_room",
        "start",
    ]
    checkpoint = await runner.get_state("successful-mission")
    assert checkpoint["status"] == "completed"
    assert checkpoint["task"]["id"] == result.task["id"]


async def test_graph_plans_and_executes_perception_actions(
    tmp_path: Path,
    locations: LocationCatalog,
) -> None:
    runner, robot = build_runner(tmp_path, locations)

    result = await runner.run("去实验室门口检查是否有人")

    assert result.status == "completed"
    assert result.perception_outcome == "clear"
    assert robot.executed_actions == [
        "navigate_to",
        "capture_image",
        "detect_objects",
    ]


async def test_rule_planner_can_request_robot_status(
    tmp_path: Path,
    locations: LocationCatalog,
) -> None:
    runner, robot = build_runner(tmp_path, locations)

    result = await runner.run("机器人现在状态如何？")

    assert result.status == "completed"
    assert robot.executed_actions == ["get_robot_status"]


async def test_graph_replans_from_perception_and_revalidates_follow_up(
    tmp_path: Path,
    locations: LocationCatalog,
) -> None:
    robot = FakeRobotAdapter(
        scripted_results={
            "detect_objects": [
                RobotActionResult(
                    success=True,
                    message="target absent",
                    data={"target_presence": {"person": False}},
                ),
                RobotActionResult(
                    success=True,
                    message="target found from fallback",
                    data={"target_presence": {"person": True}},
                ),
            ]
        }
    )
    manager = MissionManager(SQLiteTaskRepository(tmp_path / "closed-loop.db"), robot)
    tools = ToolRegistry(locations)
    runner = AgentRunner(
        build_agent_graph(
            RuleBasedPlanner(locations),
            tools,
            manager,
            replanner=PerceptionFallbackReplanner(),
            budget=ExecutionBudget(max_replans=1, max_total_steps=6),
        )
    )

    result = await runner.run("去实验室门口检查是否有人")

    assert result.status == "completed"
    assert result.goal_satisfied is True
    assert result.replan_count == 1
    assert result.executed_step_count == 6
    assert len(result.task_history) == 2
    assert result.perception_outcome == "objects_detected"
    assert robot.executed_actions == [
        "navigate_to",
        "capture_image",
        "detect_objects",
        "navigate_to",
        "capture_image",
        "detect_objects",
    ]


async def test_graph_stops_when_replan_budget_is_exhausted(
    tmp_path: Path,
    locations: LocationCatalog,
) -> None:
    robot = FakeRobotAdapter(
        scripted_results={
            "detect_objects": [
                RobotActionResult(
                    success=True,
                    message="target absent",
                    data={"target_presence": {"person": False}},
                )
            ]
        }
    )
    manager = MissionManager(SQLiteTaskRepository(tmp_path / "budget.db"), robot)
    runner = AgentRunner(
        build_agent_graph(
            RuleBasedPlanner(locations),
            ToolRegistry(locations),
            manager,
            replanner=PerceptionFallbackReplanner(),
            budget=ExecutionBudget(max_replans=0, max_total_steps=6),
        )
    )

    result = await runner.run("去实验室门口检查是否有人")

    assert result.status == "failed"
    assert result.goal_satisfied is False
    assert "Replan budget exhausted" in result.errors[0]
    assert result.executed_step_count == 3
    assert len(result.task_history) == 1


async def test_graph_rejects_unknown_location_before_execution(
    tmp_path: Path,
    locations: LocationCatalog,
) -> None:
    class UnknownLocationPlanner:
        async def plan(self, user_request: str) -> TaskPlan:
            return TaskPlan(
                objective=user_request,
                steps=[
                    NavigateToPlanStep(
                        action="navigate_to",
                        location="invented_room",
                        reason="test planner hallucination",
                    )
                ],
                unsupported_requirements=[],
            )

    robot = FakeRobotAdapter()
    manager = MissionManager(SQLiteTaskRepository(tmp_path / "unknown.db"), robot)
    tools = ToolRegistry(locations)
    runner = AgentRunner(build_agent_graph(UnknownLocationPlanner(), tools, manager))

    result = await runner.run("go somewhere imaginary")

    assert result.status == "failed"
    assert "Unknown location 'invented_room'" in result.errors[0]
    assert robot.executed_actions == []


async def test_openai_planner_uses_native_structured_output_schema(
    locations: LocationCatalog,
) -> None:
    from robot_agent.agent.planner import OpenAIPlanner

    expected_plan = TaskPlan(
        objective="go to the lab door",
        steps=[
            NavigateToPlanStep(
                action="navigate_to",
                location="laboratory_door",
                reason="requested destination",
            )
        ],
        unsupported_requirements=[],
    )

    class FakeResponses:
        def __init__(self) -> None:
            self.arguments: dict[str, object] = {}

        async def parse(self, **kwargs: object) -> object:
            self.arguments = kwargs
            return type(
                "Response",
                (),
                {"status": "completed", "output_parsed": expected_plan},
            )()

    class FakeClient:
        def __init__(self) -> None:
            self.responses = FakeResponses()

    client = FakeClient()
    tools = ToolRegistry(locations)
    planner = OpenAIPlanner(locations, tools, client=client, model="test-model")

    plan = await planner.plan("go to the lab door")

    assert plan == expected_plan
    assert client.responses.arguments["text_format"] is TaskPlan
    assert client.responses.arguments["store"] is False


async def test_siliconflow_planner_uses_chat_structured_output_schema(
    locations: LocationCatalog,
) -> None:
    from robot_agent.agent.planner import SiliconFlowPlanner

    expected_plan = TaskPlan(
        objective="go to the lab door",
        steps=[
            NavigateToPlanStep(
                action="navigate_to",
                location="laboratory_door",
                reason="requested destination",
            )
        ],
        unsupported_requirements=[],
    )

    class FakeCompletions:
        def __init__(self) -> None:
            self.arguments: dict[str, object] = {}

        async def parse(self, **kwargs: object) -> object:
            self.arguments = kwargs
            message = type("Message", (), {"parsed": expected_plan})()
            choice = type(
                "Choice",
                (),
                {"finish_reason": "stop", "message": message},
            )()
            return type("Completion", (), {"choices": [choice]})()

    class FakeChat:
        def __init__(self) -> None:
            self.completions = FakeCompletions()

    class FakeClient:
        def __init__(self) -> None:
            self.chat = FakeChat()

    client = FakeClient()
    tools = ToolRegistry(locations)
    planner = SiliconFlowPlanner(
        locations,
        tools,
        client=client,
        model="test-model",
    )

    plan = await planner.plan("go to the lab door")

    assert plan == expected_plan
    assert client.chat.completions.arguments["response_format"] is TaskPlan
    assert client.chat.completions.arguments["model"] == "test-model"

