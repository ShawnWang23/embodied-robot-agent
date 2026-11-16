# Phase 3：LangGraph Agent 与结构化任务规划

记录日期：2026-11-10

## 1. 当前状态

Phase 3 的本地和仿真闭环已经完成：

```text
自然语言请求
  → Planner
  → Pydantic TaskPlan
  → ToolRegistry 校验与位置解析
  → LangGraph 条件路由
  → MissionManager
  → RobotAdapter
  → Nav2 / TurtleBot3
```

SiliconFlow 已完成真实在线调用验收；OpenAI 路径未配置密钥，因此只完成了
OpenAI Python SDK 2.54.0 的接口签名校验和假客户端测试
`responses.parse(..., text_format=TaskPlan, store=False)` 的调用参数。

## 2. 核心模块

- `agent/models.py`：Planner 唯一允许输出的 `TaskPlan` 结构。
- `agent/locations.py`：地点别名到地图坐标的确定性映射。
- `agent/tools.py`：Tool Registry 和工具参数模型。
- `agent/planner.py`：离线规则规划器和可选 OpenAI Structured Outputs 规划器。
- `agent/state.py`：LangGraph 节点间传递的可序列化状态。
- `agent/graph.py`：规划、校验、执行和错误路由。
- `config/locations.json`：当前仿真地图允许使用的语义地点。

## 3. 计划模型与安全边界

Planner 只能生成两种当前可执行步骤：

- `navigate_to(location, reason, timeout_seconds)`
- `get_robot_status(reason, timeout_seconds)`

下列工具名称和参数模型已经预留，但在对应阶段完成前不可执行：

- Phase 4：`cancel_task`、`request_human_help`、`report_result`
- Phase 5：`capture_image`、`detect_objects`（已在 Phase 5 激活）

如果用户请求需要未实现能力，Planner 必须把它写入 `unsupported_requirements`。
Tool Registry 会拒绝整份计划，不允许 Agent 悄悄跳过步骤后继续控制机器人。

其他安全约束：

- Planner 不输出坐标、速度或 `cmd_vel`。
- 地点必须精确匹配 `locations.json` 中的名称或别名，不使用模糊坐标猜测。
- Tool Registry 才能把语义地点编译成 `TaskStepSpec`。
- Pydantic 模型禁止额外字段和未注册 action。
- MissionManager 继续负责超时、取消、SQLite 状态和单机器人互斥。
- LangGraph 没有无限 agent loop，节点和条件边是显式定义的。

## 4. Planner

### RuleBasedPlanner

这是透明、可重复的离线测试实现，不是 LLM。它按文本中的地点顺序生成计划，并识别
中英文地点别名。含有检查、拍照、人物或椅子检测等要求时，返回未支持能力并停止执行。

### OpenAIPlanner

在线规划器使用 OpenAI Responses API 的 Pydantic Structured Outputs：

```python
response = await client.responses.parse(
    model=model,
    input=[system_message, user_message],
    text_format=TaskPlan,
    store=False,
)
```

即使 API 已经按 schema 解析，结果仍会经过 Tool Registry 和地点目录的第二次确定性校验。

### SiliconFlowPlanner

硅基流动使用 OpenAI 兼容的 Chat Completions 接口，而不是 OpenAI Responses API：

```python
completion = await client.chat.completions.parse(
    model=model,
    messages=[system_message, user_message],
    response_format=TaskPlan,
)
```

默认基址是 `https://api.siliconflow.cn/v1`，默认模型是
`deepseek-ai/DeepSeek-V4-Flash`，均可通过环境变量覆盖。密钥只从
`SILICONFLOW_API_KEY` 读取，不写入配置文件、日志或数据库。

## 5. LangGraph 状态图

```text
START
  ↓
plan ──失败──→ END
  ↓
validate ──失败──→ END
  ↓
execute
  ↓
END
```

CLI 和单元测试默认使用 `InMemorySaver`，每个请求都有 `thread_id`。Phase 6 的 FastAPI
运行时已经改用 `AsyncSqliteSaver`，checkpoint 可跨进程重启恢复。

## 6. 运行命令

### 离线 Agent 演示

```powershell
uv sync --extra dev
uv run robot-agent agent-demo `
  "请先去实验室门口，然后去会议室，最后返回起点" `
  --planner rule `
  --database data/phase3_demo.db
```

### 真实 ROS2 仿真闭环

```powershell
wsl -d Ubuntu-24.04 -- bash -lc `
  'cd <WSL_PROJECT_PATH> && bash scripts/validate_agent_wsl.sh'
```

### 可选 OpenAI 在线规划器

先在私人 PowerShell 会话设置密钥，不要把密钥写入仓库或聊天：

```powershell
$secureKey = Read-Host "OPENAI_API_KEY" -AsSecureString
$env:OPENAI_API_KEY = [Net.NetworkCredential]::new('', $secureKey).Password
$env:OPENAI_MODEL = "gpt-6-astra"
uv sync --extra dev --extra llm
uv run robot-agent agent-demo "去实验室门口，然后返回起点" --planner openai
```

### 可选硅基流动在线规划器

建议在私人 PowerShell 会话中安全设置密钥，不要把密钥写入仓库、日志或数据库：

```powershell
$secureKey = Read-Host "New SILICONFLOW_API_KEY" -AsSecureString
$plainKey = [Net.NetworkCredential]::new('', $secureKey).Password
[Environment]::SetEnvironmentVariable("SILICONFLOW_API_KEY", $plainKey, "User")
[Environment]::SetEnvironmentVariable(
  "SILICONFLOW_MODEL",
  "deepseek-ai/DeepSeek-V4-Flash",
  "User"
)
Remove-Variable plainKey, secureKey
```

完全退出并重新启动 Codex 后运行：

```powershell
uv sync --extra dev --extra llm
uv run python scripts/validate_llm_planner.py --provider siliconflow
```

验收脚本依次检查正常多地点计划、虚构地点拒绝和未实现视觉能力拒绝，并确保后两类
请求没有到达 RobotAdapter。

## 7. 实际测试结果

- Windows pytest：27 passed。
- 离线 CLI：中文三地点请求生成 3 个步骤，任务 completed。
- 非法 action `publish_cmd_vel`：Pydantic 拒绝。
- Planner 虚构 `invented_room`：Tool Registry 拒绝，RobotAdapter 未执行。
- Phase 3 当时请求“检查是否有人”会因视觉能力尚未实现而整单拒绝；该限制已在
  Phase 5 解除。
- LangGraph checkpoint：成功读取相同 thread 的 completed 状态和任务 ID。
- ROS2 仿真：自然语言“两地点”计划生成、坐标解析、两个 Nav2 goal 均成功。
- 仿真退出后：无 Gazebo、Nav2、TF 残留进程。
- OpenAI SDK 2.54.0：确认 `AsyncOpenAI.responses.parse` 支持当前使用的
  `text_format`、`store`、`model` 和 `input` 参数。
- SiliconFlow 假客户端：确认使用 Chat Completions `response_format=TaskPlan`，没有误用
  OpenAI Responses API。
- OpenAI 在线 API：未测试，原因是当前环境没有 API Key。
- SiliconFlow 在线 API：三类真实请求全部通过验收。正常请求按
  `laboratory_door → meeting_room → start` 顺序完成 3 个动作；虚构地点请求失败且执行
  0 个机器人动作；视觉感知请求以 `capture_image`、`detect_objects` 未支持而失败且执行
  0 个机器人动作。
- SiliconFlow 密钥仅配置在 Windows 用户环境变量中，未写入项目文件。

## 8. Phase 3 结论

Phase 3 验收完成。系统已经具备结构化 LLM 规划、确定性安全校验、LangGraph 编排、
MissionManager 执行和 ROS2/Nav2 仿真闭环。后续 Phase 4–6 已分别补齐恢复、感知和
持久化 FastAPI 服务。

