# Phase 7 Reliability Evaluation

Run ID: `20261110T133038290474Z`  
Generated: `2026-11-10T13:30:44.148957+00:00`  
Benchmark: `deterministic_software_fault_injection`

## Required metrics

| Metric | Result |
|---|---:|
| Expectation Pass Rate | 100.00% |
| Task Success Rate | 80.00% |
| Average Completion Time | 0.146341 s |
| P95 Completion Time | 0.302976 s |
| Recovery Success Rate | 80.00% |
| Tool Calling Success Rate | 71.43% |
| Human Intervention Rate | 30.00% |
| Perception Precision | 93.75% |
| Perception Recall | 93.75% |

## Scenario results

| Scenario | Runs | Expected outcome pass | Task success | Mean time (s) |
|---|---:|---:|---:|---:|
| normal_inspection | 4 | 100.00% | 100.00% | 0.168804 |
| temporary_obstacle | 4 | 100.00% | 100.00% | 0.125398 |
| navigation_failure | 4 | 100.00% | 0.00% | 0.187757 |
| target_absent | 4 | 100.00% | 100.00% | 0.106394 |
| perception_failure | 4 | 100.00% | 100.00% | 0.133455 |
| llm_output_error | 4 | 100.00% | 0.00% | 0.004719 |
| tool_call_failure | 4 | 100.00% | 100.00% | 0.127778 |
| process_interruption | 4 | 100.00% | 100.00% | 0.115283 |
| human_pause | 4 | 100.00% | 100.00% | 0.185145 |
| multi_location_long_task | 4 | 100.00% | 100.00% | 0.308681 |

## Interpretation boundary

This is a deterministic software-level fault-injection benchmark using FakeRobotAdapter and synthetic labeled perception outcomes. It validates Agent, FSM, retry, persistence, metric, and reporting behavior. It is not a Gazebo physics benchmark, a real-robot safety test, or a YOLO dataset accuracy claim.

## Metric definitions

- **expectation_pass_rate**: Runs whose terminal status matched the scenario's declared expectation / all runs. This is the benchmark correctness metric.
- **task_success_rate**: Runs ending completed / all runs.
- **average_completion_time_seconds**: Arithmetic mean wall-clock duration from scenario start to terminal result.
- **recovery_success_rate**: Fault-injected runs ending completed / runs that attempted automatic or restart recovery.
- **tool_calling_success_rate**: Successful step attempts / all step attempts; retries and interrupted calls remain in the denominator.
- **human_intervention_rate**: Runs that paused for, requested, or required human confirmation / all runs.
- **perception_precision**: TP / (TP + FP) over synthetic labeled detections.
- **perception_recall**: TP / (TP + FN) over synthetic labeled detections.
