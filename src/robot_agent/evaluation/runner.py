"""Ten-scenario deterministic reliability benchmark runner."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from robot_agent.adapters.fake_robot import FakeRobotAdapter
from robot_agent.agent.graph import AgentRunner, build_agent_graph
from robot_agent.agent.locations import LocationCatalog
from robot_agent.agent.models import NavigateToPlanStep, TaskPlan
from robot_agent.agent.tools import ToolRegistry
from robot_agent.core.exceptions import PlanningError
from robot_agent.core.models import (
    RobotActionResult,
    StepStatus,
    Task,
    TaskStatus,
    TaskStepSpec,
    utc_now,
)
from robot_agent.evaluation.models import EvaluationRecord, ScenarioName
from robot_agent.mission.fsm import transition_step, transition_task
from robot_agent.mission.manager import MissionManager
from robot_agent.storage.sqlite import SQLiteTaskRepository

SCENARIOS: tuple[ScenarioName, ...] = (
    "normal_inspection",
    "temporary_obstacle",
    "navigation_failure",
    "target_absent",
    "perception_failure",
    "llm_output_error",
    "tool_call_failure",
    "process_interruption",
    "human_pause",
    "multi_location_long_task",
)


@dataclass
class _ScenarioOutcome:
    actual_status: str
    expected_status: str
    task: Task | None = None
    recovery_attempted: bool = False
    human_intervention: bool = False
    ground_truth: list[bool] = field(default_factory=list)
    predictions: list[bool] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class EvaluationRunner:
    """Run 30–50 real executions against deterministic fault fixtures."""

    def __init__(
        self,
        task_database: str | Path,
        *,
        run_id: str,
        locations_path: str | Path = "config/locations.json",
    ) -> None:
        self.task_database = Path(task_database)
        self.task_database.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.locations = LocationCatalog.from_json(locations_path)
        self.tools = ToolRegistry(self.locations)

    async def run(self, *, repetitions_per_scenario: int = 4) -> list[EvaluationRecord]:
        if not 3 <= repetitions_per_scenario <= 5:
            raise ValueError(
                "repetitions_per_scenario must be 3–5 so the standard suite has "
                "30–50 runs"
            )
        records: list[EvaluationRecord] = []
        for iteration in range(1, repetitions_per_scenario + 1):
            for scenario in SCENARIOS:
                records.append(await self._run_one(scenario, iteration))
        return records

    async def _run_one(
        self,
        scenario: ScenarioName,
        iteration: int,
    ) -> EvaluationRecord:
        started_at = datetime.now(timezone.utc)
        started = perf_counter()
        try:
            method = getattr(self, f"_scenario_{scenario}")
            outcome: _ScenarioOutcome = await method(iteration)
            duration = perf_counter() - started
            return self._record(scenario, iteration, started_at, duration, outcome)
        except Exception as exc:  # Keep all 30–50 raw outcomes for diagnosis.
            return EvaluationRecord(
                run_id=self.run_id,
                scenario=scenario,
                iteration=iteration,
                started_at=started_at,
                duration_seconds=perf_counter() - started,
                expected_status="scenario completed without harness error",
                actual_status="evaluation_error",
                expectation_met=False,
                task_success=False,
                recovery_attempted=False,
                recovery_success=None,
                human_intervention=False,
                tool_calls_attempted=0,
                tool_calls_succeeded=0,
                notes=[f"{type(exc).__name__}: {exc}"],
            )

    def _record(
        self,
        scenario: ScenarioName,
        iteration: int,
        started_at: datetime,
        duration: float,
        outcome: _ScenarioOutcome,
    ) -> EvaluationRecord:
        if len(outcome.ground_truth) != len(outcome.predictions):
            raise ValueError("perception labels and predictions must have equal length")
        task = outcome.task
        attempts = sum(step.attempt_count for step in task.steps) if task else 0
        succeeded = (
            sum(step.status is StepStatus.COMPLETED for step in task.steps)
            if task
            else 0
        )
        true_positives = sum(
            truth and prediction
            for truth, prediction in zip(outcome.ground_truth, outcome.predictions)
        )
        false_positives = sum(
            not truth and prediction
            for truth, prediction in zip(outcome.ground_truth, outcome.predictions)
        )
        false_negatives = sum(
            truth and not prediction
            for truth, prediction in zip(outcome.ground_truth, outcome.predictions)
        )
        true_negatives = sum(
            not truth and not prediction
            for truth, prediction in zip(outcome.ground_truth, outcome.predictions)
        )
        task_success = outcome.actual_status == TaskStatus.COMPLETED.value
        return EvaluationRecord(
            run_id=self.run_id,
            scenario=scenario,
            iteration=iteration,
            started_at=started_at,
            duration_seconds=duration,
            expected_status=outcome.expected_status,
            actual_status=outcome.actual_status,
            expectation_met=outcome.actual_status == outcome.expected_status,
            task_success=task_success,
            recovery_attempted=outcome.recovery_attempted,
            recovery_success=(task_success if outcome.recovery_attempted else None),
            human_intervention=outcome.human_intervention,
            tool_calls_attempted=attempts,
            tool_calls_succeeded=succeeded,
            true_positives=true_positives,
            false_positives=false_positives,
            false_negatives=false_negatives,
            true_negatives=true_negatives,
            task_id=task.id if task else None,
            notes=outcome.notes,
        )

    async def _scenario_normal_inspection(self, iteration: int) -> _ScenarioOutcome:
        prediction = True
        robot = FakeRobotAdapter(
            scripted_results={
                "detect_objects": [self._success(presence={"person": prediction})]
            }
        )
        manager = self._manager(robot)
        task = manager.create_task(
            "Normal inspection",
            [
                self._navigation("laboratory_door"),
                TaskStepSpec(action="capture_image"),
                TaskStepSpec(action="detect_objects"),
                self._navigation("start"),
            ],
        )
        settled = await manager.execute_task(task.id)
        return _ScenarioOutcome(
            actual_status=settled.status.value,
            expected_status=TaskStatus.COMPLETED.value,
            task=settled,
            ground_truth=[True],
            predictions=[prediction],
        )

    async def _scenario_temporary_obstacle(self, iteration: int) -> _ScenarioOutcome:
        step = self.tools.compile_plan(
            TaskPlan(
                objective="Observe from a safe fallback if temporarily blocked",
                steps=[
                    NavigateToPlanStep(
                        action="navigate_to",
                        location="laboratory_door",
                        reason="standard obstacle scenario",
                    )
                ],
            )
        )[0]
        robot = FakeRobotAdapter(
            scripted_results={
                "navigate_to": [
                    self._failure("path temporarily blocked", "path_blocked"),
                    self._success(),
                ]
            }
        )
        manager = self._manager(robot)
        task = manager.create_task("Temporary obstacle", [step])
        settled = await manager.execute_task(task.id)
        return _ScenarioOutcome(
            actual_status=settled.status.value,
            expected_status=TaskStatus.COMPLETED.value,
            task=settled,
            recovery_attempted=True,
            notes=["Explicit corridor fallback is expected after the first failure."],
        )

    async def _scenario_navigation_failure(self, iteration: int) -> _ScenarioOutcome:
        robot = FakeRobotAdapter(
            scripted_results={
                "navigate_to": [
                    self._failure("goal remains unreachable", "goal_unreachable")
                ]
                * 3
            }
        )
        manager = self._manager(robot)
        task = manager.create_task(
            "Unrecoverable navigation failure",
            [TaskStepSpec(action="navigate_to")],
        )
        settled = await manager.execute_task(task.id)
        return _ScenarioOutcome(
            actual_status=settled.status.value,
            expected_status=TaskStatus.WAITING_FOR_HUMAN.value,
            task=settled,
            recovery_attempted=True,
            human_intervention=True,
        )

    async def _scenario_target_absent(self, iteration: int) -> _ScenarioOutcome:
        prediction = iteration == 2  # One deliberate false positive in four runs.
        robot = FakeRobotAdapter(
            scripted_results={
                "detect_objects": [self._success(presence={"person": prediction})]
            }
        )
        manager = self._manager(robot)
        task = manager.create_task(
            "Target does not exist",
            [self._navigation("meeting_room"), TaskStepSpec(action="detect_objects")],
        )
        settled = await manager.execute_task(task.id)
        return _ScenarioOutcome(
            actual_status=settled.status.value,
            expected_status=TaskStatus.COMPLETED.value,
            task=settled,
            ground_truth=[False],
            predictions=[prediction],
            notes=["Iteration 2 injects the suite's synthetic false positive."],
        )

    async def _scenario_perception_failure(self, iteration: int) -> _ScenarioOutcome:
        robot = FakeRobotAdapter(
            scripted_results={
                "detect_objects": [
                    self._failure("camera frame unavailable", "detection_failed"),
                    self._success(presence={"chair": True}),
                ]
            }
        )
        manager = self._manager(robot)
        task = manager.create_task(
            "Transient perception failure",
            [TaskStepSpec(action="detect_objects")],
        )
        settled = await manager.execute_task(task.id)
        return _ScenarioOutcome(
            actual_status=settled.status.value,
            expected_status=TaskStatus.COMPLETED.value,
            task=settled,
            recovery_attempted=True,
            ground_truth=[True],
            predictions=[True],
        )

    async def _scenario_llm_output_error(self, iteration: int) -> _ScenarioOutcome:
        class MalformedOutputPlanner:
            async def plan(self, user_request: str) -> TaskPlan:
                raise PlanningError("malformed structured output rejected")

        manager = self._manager(FakeRobotAdapter())
        runner = AgentRunner(
            build_agent_graph(MalformedOutputPlanner(), self.tools, manager)
        )
        result = await runner.run(
            "unsafe malformed planner output",
            thread_id=f"{self.run_id}-invalid-{iteration}",
        )
        return _ScenarioOutcome(
            actual_status=result.status,
            expected_status=TaskStatus.FAILED.value,
            notes=["Planner error must be rejected before task or tool creation."],
        )

    async def _scenario_tool_call_failure(self, iteration: int) -> _ScenarioOutcome:
        robot = FakeRobotAdapter(
            scripted_results={
                "get_robot_status": [
                    self._failure("temporary service failure", "tool_error"),
                    self._success(),
                ]
            }
        )
        manager = self._manager(robot)
        task = manager.create_task(
            "Transient tool failure",
            [TaskStepSpec(action="get_robot_status")],
        )
        settled = await manager.execute_task(task.id)
        return _ScenarioOutcome(
            actual_status=settled.status.value,
            expected_status=TaskStatus.COMPLETED.value,
            task=settled,
            recovery_attempted=True,
        )

    async def _scenario_process_interruption(self, iteration: int) -> _ScenarioOutcome:
        repository = SQLiteTaskRepository(self.task_database)
        original = MissionManager(repository, FakeRobotAdapter())
        task = original.create_task(
            "Process interrupted while navigating",
            [self._navigation("laboratory_door")],
        )
        interrupted = original.get_task(task.id)
        transition_task(interrupted, TaskStatus.RUNNING)
        transition_step(interrupted.steps[0], StepStatus.RUNNING)
        interrupted.steps[0].attempt_count = 1
        interrupted.steps[0].started_at = utc_now()
        repository.save(interrupted)

        restarted = self._manager(FakeRobotAdapter())
        reconciled = restarted.reconcile_interrupted_tasks()
        if [item.id for item in reconciled] != [task.id]:
            raise RuntimeError("interrupted task was not uniquely reconciled")
        settled = await restarted.resume_after_human(
            task.id,
            robot_state_confirmed=True,
            environment_confirmed=True,
        )
        return _ScenarioOutcome(
            actual_status=settled.status.value,
            expected_status=TaskStatus.COMPLETED.value,
            task=settled,
            recovery_attempted=True,
            human_intervention=True,
            notes=["Resume occurred only after robot and environment confirmation."],
        )

    async def _scenario_human_pause(self, iteration: int) -> _ScenarioOutcome:
        robot = FakeRobotAdapter(delay_seconds=0.05)
        manager = self._manager(robot)
        task = manager.create_task(
            "Human pause and resume",
            [self._navigation("meeting_room")],
        )
        execution = asyncio.create_task(manager.execute_task(task.id))
        for _ in range(200):
            if robot.is_executing:
                break
            await asyncio.sleep(0.001)
        else:
            raise RuntimeError("robot did not start before pause deadline")
        paused = await manager.pause_task(task.id)
        await execution
        if paused.status is not TaskStatus.PAUSED:
            raise RuntimeError("pause request did not reach PAUSED")
        settled = await manager.resume_task(task.id)
        return _ScenarioOutcome(
            actual_status=settled.status.value,
            expected_status=TaskStatus.COMPLETED.value,
            task=settled,
            human_intervention=True,
        )

    async def _scenario_multi_location_long_task(
        self,
        iteration: int,
    ) -> _ScenarioOutcome:
        person_prediction = True
        chair_prediction = iteration != 3  # One deliberate false negative.
        robot = FakeRobotAdapter(
            scripted_results={
                "detect_objects": [
                    self._success(presence={"person": person_prediction}),
                    self._success(presence={"chair": chair_prediction}),
                ]
            }
        )
        manager = self._manager(robot)
        task = manager.create_task(
            "Multi-location long inspection",
            [
                self._navigation("laboratory_door"),
                TaskStepSpec(action="capture_image"),
                TaskStepSpec(action="detect_objects"),
                self._navigation("meeting_room"),
                TaskStepSpec(action="capture_image"),
                TaskStepSpec(action="detect_objects"),
                TaskStepSpec(action="get_robot_status"),
                self._navigation("corridor_observation"),
                self._navigation("start"),
            ],
        )
        settled = await manager.execute_task(task.id)
        return _ScenarioOutcome(
            actual_status=settled.status.value,
            expected_status=TaskStatus.COMPLETED.value,
            task=settled,
            ground_truth=[True, True],
            predictions=[person_prediction, chair_prediction],
            notes=["Iteration 3 injects the suite's synthetic false negative."],
        )

    def _manager(self, robot: FakeRobotAdapter) -> MissionManager:
        return MissionManager(
            SQLiteTaskRepository(self.task_database),
            robot,
            feedback_poll_interval=0.001,
        )

    def _navigation(self, location_name: str) -> TaskStepSpec:
        location = self.locations.resolve(location_name)
        return TaskStepSpec(
            action="navigate_to",
            parameters={"x": location.x, "y": location.y, "yaw": location.yaw},
            metadata={"location": location.name},
        )

    @staticmethod
    def _success(*, presence: dict[str, bool] | None = None) -> RobotActionResult:
        data: dict[str, Any] = {}
        if presence is not None:
            data["target_presence"] = presence
        return RobotActionResult(success=True, message="injected success", data=data)

    @staticmethod
    def _failure(message: str, error_code: str) -> RobotActionResult:
        return RobotActionResult(
            success=False,
            message=message,
            error_code=error_code,
        )
