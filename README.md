# 室内机器人长程任务执行 Agent

这是一个分阶段开发的 ROS2 + LLM 室内机器人 Agent。当前已完成 Phase 1 的任务管理核心、
Phase 2 的受控仿真集成、Phase 3 Agent 集成、Phase 4 闭环异常恢复、Phase 5
多模态感知、持久化任务服务、可靠性评估、Phase 8 最终交付和受预算约束的闭环重规划：

`FastAPI -> LangGraph -> 结构化计划 -> Tool Registry -> MissionManager -> Nav2 / YOLO -> 结果审查 -> 重规划`

OpenAI 与 SiliconFlow 在线规划器均已实现，其中 SiliconFlow 已通过导航、未知地点拒绝和
视觉工具规划三类真实在线调用验收。API 默认使用离线规则规划器，也可通过环境变量切换。

## 当前能力

- 使用 Pydantic 2 校验 `Task`、`TaskStep` 和执行结果。
- 通过 `RobotAdapter` 抽象隔离任务系统和机器人实现。
- 使用 `FakeRobotAdapter` 可重复地模拟成功和失败。
- 使用 SQLite 保存任务快照。
- 使用 `MissionManager` 执行、暂停、恢复和取消多步骤任务。
- 对每个步骤执行超时保护，且不会无限等待。
- 使用显式 FSM 拒绝非法状态转换。
- 使用 SQLite 保存结构化生命周期和错误事件。
- 提供 CLI 演示和 pytest 测试。
- 使用统一的 `RobotAdapter` 在 Fake 和 ROS2 实现间切换。
- 使用 Nav2 `NavigateToPose` 发送目标、读取反馈和结果。
- 订阅 `/odom` 获取机器人状态。
- 支持主动取消 Nav2 goal，并在任务超时时取消运动。
- 在目标进入 Nav2 前校验字段、数值、坐标系和地图边界。
- 使用 LangGraph 显式编排规划、校验和执行节点。
- 使用 Pydantic 区分允许的计划 action，拒绝未知工具和额外参数。
- 使用地点目录把自然语言地点确定性映射到地图坐标。
- 使用独立 SQLite 数据库保存任务快照/事件和 LangGraph thread checkpoint。
- 对超时、不可达、路径阻挡、工具失败和感知失败执行有上限的恢复策略。
- 只使用地点目录中显式配置的备用观察点，不让 LLM 临时生成恢复坐标。
- 连续失败达到上限时进入 `waiting_for_human`，停止自主执行。
- 人工处理或进程重启后，必须同时确认机器人状态和现场环境，才能恢复任务。
- 将导航反馈、失败分类、重试和人工接管事件持久化到 SQLite。
- 使用 `cv_bridge` 从 TurtleBot3 Waffle Pi 的 ROS2 相机话题获取 BGR 图像。
- 使用 CPU 版 PyTorch 和预训练 `yolo26n.pt` 输出结构化目标检测结果。
- 通过 CapabilityRouterAdapter 解耦导航与感知执行。
- LangGraph 根据检测结果进入 `objects_detected` 或 `clear` 条件分支。
- 检测目标缺失时可从显式备用观察点生成局部计划，并重新经过 Tool Registry 校验。
- 使用最大重规划次数和总步骤数双重预算，防止 Agent 无限循环。
- 提供 FastAPI 提交、查询、暂停、取消、接管、恢复、事件和 checkpoint 历史接口。
- API 重启时自动隔离意外中断的运行任务，不会盲目重放当前机器人动作。
- 提供 10 类、每类 3–5 次的标准可靠性测试集，保存逐次 JSONL 与可复算指标报告。
- 提供完整安装、API、ROS2 节点、工作流/FSM、测试报告和可重复生成的演示视频。
- 在同一 Gazebo Waffle 实例中完成 Nav2、1920×1080 Camera、YOLO 和一次局部重规划的统一验收。
- 使用 GitHub Actions 执行 Ruff、54 项 pytest 和 80% 核心模块分支覆盖率门禁。

## 快速开始（Windows PowerShell）

```powershell
uv sync --extra dev
uv run pytest
# 一键执行同步、测试/覆盖率、Agent 演示或 API
.\scripts\quickstart.ps1 -Mode test
.\scripts\quickstart.ps1 -Mode agent
uv run robot-agent demo --database data/tasks.db
uv run robot-agent control-demo --database data/tasks.db
uv run robot-agent agent-demo "去实验室门口，然后返回起点" --planner rule
# 在线硅基流动：--planner siliconflow
uv run python scripts/validate_recovery.py
# WSL 首次安装视觉环境：bash scripts/setup_perception_wsl.sh
# 真实相机 + YOLO + Agent：bash scripts/validate_perception_wsl.sh
# 本地持久化 API：http://127.0.0.1:8000/docs
uv run robot-agent-api
# Phase 7 默认运行 40 次（10 场景 × 4 次）
uv run python scripts/run_phase7_evaluation.py --repetitions 4
# 生成 OpenAPI 与 32.5 秒无旁白演示视频
uv run python scripts/export_openapi.py
uv run python scripts/create_demo_video.py
# WSL：同一机器人实例完成导航、视觉与闭环重规划
wsl -d Ubuntu-24.04 -- bash -lc \
  'cd <WSL_PROJECT_PATH> && bash scripts/validate_unified_sim_wsl.sh'
```

提交一个任务（另开 PowerShell）：

```powershell
$body = @{ instruction = "去实验室门口检查是否有人" } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/tasks `
  -Method Post -ContentType application/json -Body $body
```

API 默认 `ROBOT_AGENT_PLANNER=rule`。使用硅基流动时先安装 LLM extra，再设置
`ROBOT_AGENT_PLANNER=siliconflow`；密钥只从用户环境变量 `SILICONFLOW_API_KEY` 读取。

也可不使用已安装的命令入口：

```powershell
uv run python -m robot_agent.cli demo --database data/tasks.db
```

查询某次演示输出的任务 ID：

```powershell
uv run robot-agent show <TASK_ID> --database data/tasks.db
```

## 当前边界

- 当前仍是单个 API 服务进程、单机器人执行器；不支持多个 API 进程同时抢占机器人。
- API 仅绑定 `127.0.0.1`，尚无认证；不要直接暴露到局域网或公网。
- 暂停会停止当前动作，并在恢复后重新执行被中断步骤。动作必须设计为可安全重试。
- SQLite 当前保存完整 JSON 快照，便于教学和调试；需要复杂报表时再规范化表结构。
- FakeRobotAdapter 的结果不代表真实机器人或仿真运行结果。
- 当前 WSL 默认 AMCL/SLAM 和 collision monitor observation source 仍有兼容问题；
  统一仿真验收使用已知出生点和仅限仿真的临时安全隔离参数。详见 Phase 2 文档。
- 临时测试配置中的 `collision_monitor.source_timeout=0` 严禁用于真机。
- 统一仿真成功不等于真机安全认证；硬件边界仍需急停、碰撞监测与现场测试。

## 文档

- [Phase 0 环境与路线图](docs/phase0_environment_and_roadmap.md)
- [Phase 2 ROS2 与 Nav2 集成](docs/phase2_ros2_nav2.md)
- [Phase 3 LangGraph Agent](docs/phase3_agent.md)
- [Phase 4 闭环执行与异常恢复](docs/phase4_recovery.md)
- [Phase 5 ROS2 相机与 YOLO 感知](docs/phase5_perception.md)
- [Phase 6 持久化 Checkpoint 与 FastAPI](docs/phase6_persistence_api.md)
- [Phase 7 测试与可靠性评估](docs/phase7_reliability.md)
- [安装与环境复现](docs/installation.md)
- [FastAPI 接口参考](docs/api_reference.md)
- [ROS2 节点说明](docs/ros2_nodes.md)
- [系统图、Agent 工作流与 FSM](docs/diagrams.md)
- [最终测试报告](docs/test_report.md)
- [演示指南](docs/demo_guide.md)
- [Phase 8 最终交付清单](docs/final_delivery.md)
- [Phase 9 闭环重规划与统一仿真](docs/phase9_closed_loop.md)
- [当前架构](docs/architecture.md)
- [开发进度](docs/progress.md)

