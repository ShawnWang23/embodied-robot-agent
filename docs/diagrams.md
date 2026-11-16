# 系统图、Agent 工作流与 FSM

## 1. 分层系统架构

```mermaid
flowchart TB
    User[User / API Client] --> API[CLI or FastAPI]
    API --> Planner[Rule / OpenAI / SiliconFlow Planner]
    Planner --> Schema[Pydantic TaskPlan]
    Schema --> Registry[ToolRegistry + LocationCatalog]
    Registry --> Graph[LangGraph]
    Graph --> Mission[MissionManager]
    Mission --> FSM[Task and Step FSM]
    Mission --> Recovery[Bounded RecoveryPolicy]
    Mission --> Tasks[(tasks.db + events)]
    Graph --> Checkpoints[(checkpoints.db)]
    Mission --> Router[RobotAdapter / CapabilityRouterAdapter]
    Router --> Nav[ROS2RobotAdapter → Nav2]
    Router --> Vision[Camera → YOLO]
    Nav --> Feedback[Navigation feedback]
    Vision --> Feedback
    Feedback --> Mission
    Mission --> Human[Pause / Human confirmation]
```

## 2. Agent 工作流

```mermaid
flowchart LR
    Start([START]) --> Plan[plan]
    Plan -->|planner error| Failed([FAILED / END])
    Plan --> Validate[validate]
    Validate -->|unknown tool/location/schema| Failed
    Validate --> Create[create_task]
    Create --> Execute[execute]
    Execute -->|failed / paused / cancelled / waiting| End([END])
    Execute -->|no perception| Complete[complete]
    Execute -->|target found| Detected[objects_detected]
    Execute -->|target absent| Clear[clear]
    Complete --> End
    Detected --> End
    Clear --> End
```

`create_task` 在机器人动作前写入任务 ID 和 `agent_thread_id`，确保中断后能关联任务数据库与
checkpoint。LLM 输出必须先通过 Pydantic、地点目录和 Tool Registry，不能直接调用底盘。

## 3. Task FSM

```mermaid
stateDiagram-v2
    [*] --> PENDING
    PENDING --> RUNNING: execute
    PENDING --> CANCELLED: cancel
    RUNNING --> COMPLETED: all steps succeed
    RUNNING --> FAILED: unsafe/non-retryable failure
    RUNNING --> PAUSED: pause current action
    RUNNING --> CANCELLED: cancel current action
    RUNNING --> WAITING_FOR_HUMAN: recovery exhausted
    PAUSED --> RUNNING: resume
    PAUSED --> WAITING_FOR_HUMAN: human takeover
    PAUSED --> CANCELLED: cancel
    WAITING_FOR_HUMAN --> RUNNING: robot + environment confirmed
    WAITING_FOR_HUMAN --> CANCELLED: cancel
```

## 4. Step FSM 与恢复

```mermaid
stateDiagram-v2
    [*] --> PENDING
    PENDING --> RUNNING: start attempt
    RUNNING --> COMPLETED: success
    RUNNING --> PENDING: retry / pause / process restart
    RUNNING --> FAILED: non-retryable failure
    RUNNING --> CANCELLED: task cancel
    PENDING --> CANCELLED: cancel remaining steps
```

```mermaid
flowchart TD
    Result[RobotActionResult failure] --> Classify[FailureCategory]
    Classify --> Invalid{Safe to retry?}
    Invalid -->|No| Fail[Fail task]
    Invalid -->|Yes| Budget{Attempt and task budget remain?}
    Budget -->|No| Human[WAITING_FOR_HUMAN]
    Budget -->|Yes, explicit fallback| Fallback[Use configured fallback]
    Budget -->|Yes| Retry[Retry same step]
```

## 5. 重启恢复时序

```mermaid
sequenceDiagram
    participant Old as Old API process
    participant DB as tasks.db
    participant New as New API process
    participant CP as checkpoints.db
    participant H as Human
    Old->>DB: save RUNNING task + RUNNING step
    Note over Old: process stops
    New->>DB: reconcile RUNNING tasks
    New->>DB: task=WAITING_FOR_HUMAN, step=PENDING
    New->>CP: synchronize quarantined state
    New-->>H: request robot/environment inspection
    H->>New: both confirmations=true
    New->>DB: resume pending step
```

