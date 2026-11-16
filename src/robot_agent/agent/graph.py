"""LangGraph workflow that validates every plan before robot execution."""

from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from robot_agent.agent.models import AgentRunResult, TaskPlan
from robot_agent.agent.planner import TaskPlanner
from robot_agent.agent.replanning import (
    ExecutionBudget,
    NoReplanPolicy,
    ReplanPolicy,
)
from robot_agent.agent.state import AgentState
from robot_agent.agent.tools import ToolRegistry
from robot_agent.core.exceptions import PlanningError, PlanValidationError
from robot_agent.core.models import Task, TaskStatus, TaskStepSpec
from robot_agent.mission.manager import MissionManager


def build_agent_graph(
    planner: TaskPlanner,
    tools: ToolRegistry,
    mission_manager: MissionManager,
    *,
    checkpointer: Any | None = None,
    replanner: ReplanPolicy | None = None,
    budget: ExecutionBudget | None = None,
) -> Any:
    """Build a validated execution graph with bounded closed-loop replanning."""

    resolved_replanner = replanner or NoReplanPolicy()
    resolved_budget = budget or ExecutionBudget()

    async def plan_node(state: AgentState) -> dict[str, object]:
        try:
            plan = await planner.plan(state["user_request"])
            return {
                "status": "validating",
                "plan": plan.model_dump(mode="json"),
                "errors": [],
            }
        except (PlanningError, ValidationError, ValueError) as exc:
            return {"status": "failed", "errors": [str(exc)]}

    def validate_node(state: AgentState) -> dict[str, object]:
        try:
            plan = TaskPlan.model_validate(state["plan"])
            steps = tools.compile_plan(plan)
            projected_steps = state.get("executed_step_count", 0) + len(steps)
            if projected_steps > resolved_budget.max_total_steps:
                raise PlanValidationError(
                    "Execution step budget exceeded: "
                    f"{projected_steps} > {resolved_budget.max_total_steps}"
                )
            return {
                "status": "executing",
                "executable_steps": [step.model_dump(mode="json") for step in steps],
                "errors": [],
            }
        except (PlanValidationError, ValidationError, ValueError) as exc:
            return {"status": "failed", "errors": [str(exc)]}

    def create_task_node(state: AgentState) -> dict[str, object]:
        plan = TaskPlan.model_validate(state["plan"])
        steps = [
            TaskStepSpec.model_validate(raw_step)
            for raw_step in state["executable_steps"]
        ]
        task = mission_manager.create_task(
            plan.objective,
            steps,
            context={"agent_thread_id": state["thread_id"]},
        )
        return {
            "status": "executing",
            "task_id": task.id,
            "task": task.model_dump(mode="json"),
        }

    async def execute_node(state: AgentState) -> dict[str, object]:
        task = mission_manager.get_task(state["task_id"])
        if task.status is TaskStatus.PENDING:
            settled = await mission_manager.execute_task(task.id)
        else:
            settled = task
        task_payload = settled.model_dump(mode="json")
        execution_values: dict[str, object] = {
            "task": task_payload,
            "task_history": [*state.get("task_history", []), task_payload],
            "executed_step_count": state.get("executed_step_count", 0)
            + len(settled.steps),
        }
        if settled.status is TaskStatus.COMPLETED:
            return {
                **execution_values,
                "status": "completed",
                "errors": [],
            }
        if settled.status is TaskStatus.PAUSED:
            return {
                **execution_values,
                "status": "paused",
                "errors": [],
            }
        if settled.status is TaskStatus.CANCELLED:
            return {
                **execution_values,
                "status": "cancelled",
                "errors": [],
            }
        if settled.status is TaskStatus.WAITING_FOR_HUMAN:
            return {
                **execution_values,
                "status": "waiting_for_human",
                "errors": [],
            }
        return {
            **execution_values,
            "status": "failed",
            "errors": [settled.error or "Mission execution failed"],
        }

    async def review_node(state: AgentState) -> dict[str, object]:
        task = Task.model_validate(state["task"])
        decision = await resolved_replanner.review(
            state["user_request"],
            task,
            replan_count=state.get("replan_count", 0),
        )
        if decision.plan is None:
            if decision.goal_satisfied:
                return {
                    "status": "completed",
                    "goal_satisfied": True,
                    "completion_reason": decision.reason,
                }
            return {
                "status": "failed",
                "goal_satisfied": False,
                "completion_reason": decision.reason,
                "errors": [decision.reason],
            }

        next_replan_count = state.get("replan_count", 0) + 1
        if next_replan_count > resolved_budget.max_replans:
            message = (
                "Replan budget exhausted before the goal was satisfied: "
                f"{next_replan_count} > {resolved_budget.max_replans}"
            )
            return {
                "status": "failed",
                "goal_satisfied": False,
                "completion_reason": message,
                "errors": [message],
            }
        return {
            "status": "validating",
            "plan": decision.plan.model_dump(mode="json"),
            "goal_satisfied": False,
            "completion_reason": decision.reason,
            "replan_count": next_replan_count,
            "errors": [],
        }

    def objects_detected_node(state: AgentState) -> dict[str, object]:
        return {"status": "completed", "perception_outcome": "objects_detected"}

    def clear_node(state: AgentState) -> dict[str, object]:
        return {"status": "completed", "perception_outcome": "clear"}

    def complete_node(state: AgentState) -> dict[str, object]:
        return {"status": "completed"}

    def route_after_stage(state: AgentState) -> Literal["continue", "stop"]:
        return "stop" if state.get("status") == "failed" else "continue"

    def route_after_execute(
        state: AgentState,
    ) -> Literal["review", "stop"]:
        if state.get("status") in {
            "failed",
            "waiting_for_human",
            "paused",
            "cancelled",
        }:
            return "stop"
        return "review"

    def route_after_review(
        state: AgentState,
    ) -> Literal["replan", "detected", "clear", "complete", "stop"]:
        if state.get("status") == "failed":
            return "stop"
        if state.get("status") == "validating":
            return "replan"
        task = state.get("task") or {}
        steps = task.get("steps", []) if isinstance(task, dict) else []
        detection_results = [
            step.get("result", {})
            for step in steps
            if isinstance(step, dict) and step.get("action") == "detect_objects"
        ]
        if not detection_results:
            return "complete"
        detected = any(
            any(result.get("target_presence", {}).values())
            for result in detection_results
            if isinstance(result, dict)
        )
        return "detected" if detected else "clear"

    builder = StateGraph(AgentState)
    builder.add_node("plan", plan_node)
    builder.add_node("validate", validate_node)
    builder.add_node("create_task", create_task_node)
    builder.add_node("execute", execute_node)
    builder.add_node("review", review_node)
    builder.add_node("objects_detected", objects_detected_node)
    builder.add_node("clear", clear_node)
    builder.add_node("complete", complete_node)
    builder.add_edge(START, "plan")
    builder.add_conditional_edges(
        "plan",
        route_after_stage,
        {"continue": "validate", "stop": END},
    )
    builder.add_conditional_edges(
        "validate",
        route_after_stage,
        {"continue": "create_task", "stop": END},
    )
    builder.add_edge("create_task", "execute")
    builder.add_conditional_edges(
        "execute",
        route_after_execute,
        {"review": "review", "stop": END},
    )
    builder.add_conditional_edges(
        "review",
        route_after_review,
        {
            "replan": "validate",
            "detected": "objects_detected",
            "clear": "clear",
            "complete": "complete",
            "stop": END,
        },
    )
    builder.add_edge("objects_detected", END)
    builder.add_edge("clear", END)
    builder.add_edge("complete", END)
    return builder.compile(checkpointer=checkpointer or InMemorySaver())


class AgentRunner:
    """Typed facade around the compiled LangGraph application."""

    def __init__(self, graph: Any) -> None:
        self._graph = graph

    async def run(
        self,
        user_request: str,
        *,
        thread_id: str | None = None,
    ) -> AgentRunResult:
        resolved_thread_id = thread_id or str(uuid4())
        final_state = await self._graph.ainvoke(
            {
                "user_request": user_request,
                "thread_id": resolved_thread_id,
                "status": "planning",
                "errors": [],
                "task_history": [],
                "replan_count": 0,
                "executed_step_count": 0,
            },
            config={"configurable": {"thread_id": resolved_thread_id}},
        )
        plan = (
            TaskPlan.model_validate(final_state["plan"])
            if final_state.get("plan") is not None
            else None
        )
        return AgentRunResult(
            thread_id=resolved_thread_id,
            status=final_state["status"],
            plan=plan,
            task=final_state.get("task"),
            errors=final_state.get("errors", []),
            perception_outcome=final_state.get("perception_outcome"),
            goal_satisfied=final_state.get("goal_satisfied"),
            completion_reason=final_state.get("completion_reason"),
            replan_count=final_state.get("replan_count", 0),
            executed_step_count=final_state.get("executed_step_count", 0),
            task_history=final_state.get("task_history", []),
        )

    async def get_state(self, thread_id: str) -> AgentState:
        """Read the latest checkpoint for one agent thread."""

        snapshot = await self._graph.aget_state(
            config={"configurable": {"thread_id": thread_id}}
        )
        return snapshot.values

    async def update_task_state(self, thread_id: str, task: Task) -> None:
        """Persist a task changed by an external control endpoint."""

        status = task.status.value
        perception_outcome = _perception_outcome(task)
        values: dict[str, object] = {
            "status": status,
            "task_id": task.id,
            "task": task.model_dump(mode="json"),
            "errors": [task.error] if task.error else [],
        }
        if perception_outcome is not None:
            values["perception_outcome"] = perception_outcome
        as_node = (
            perception_outcome
            if task.status is TaskStatus.COMPLETED
            and perception_outcome is not None
            else "complete"
            if task.status is TaskStatus.COMPLETED
            else "execute"
        )
        await self._graph.aupdate_state(
            config={"configurable": {"thread_id": thread_id}},
            values=values,
            as_node=as_node,
        )

    async def get_history(self, thread_id: str) -> list[AgentState]:
        """Return newest-first checkpoint values for one thread."""

        return [
            snapshot.values
            async for snapshot in self._graph.aget_state_history(
                config={"configurable": {"thread_id": thread_id}}
            )
        ]


def _perception_outcome(task: Task) -> Literal["objects_detected", "clear"] | None:
    results = [
        step.result
        for step in task.steps
        if step.action == "detect_objects" and isinstance(step.result, dict)
    ]
    if not results:
        return None
    detected = any(
        any(result.get("target_presence", {}).values()) for result in results
    )
    return "objects_detected" if detected else "clear"

