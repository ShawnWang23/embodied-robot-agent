# Phase 9：闭环重规划、统一仿真与工程发布

## 1. 闭环 Agent

Agent 工作流由一次性 `plan → validate → create_task → execute` 扩展为：

```text
plan → validate → create_task → execute → review
                    ↑                    │
                    └──── bounded replan ┘
```

`PerceptionFallbackReplanner` 读取已执行任务中的结构化 `target_presence`。首次未检出目标时，生成“前往配置中的备用观察点 → 获取新图像 → 再次检测”的局部计划。该计划不能直接执行，必须重新经过 Pydantic schema、Tool Registry 和 LocationCatalog 校验。

`ExecutionBudget` 同时限制 `max_replans` 和 `max_total_steps`。超出预算时 Agent 以失败终态停止，不会无限规划或执行。

## 2. 同一 ROS2/Gazebo 栈验收

入口：

```bash
bash scripts/validate_unified_sim_wsl.sh
```

脚本在一个 Gazebo sandbox world 中启动：

- 一个带 RGB 相机的 TurtleBot3 Waffle；
- robot_state_publisher、ROS/Gazebo topic bridge；
- Nav2 localization、planner、controller、BT navigator；
- `ROS2RobotAdapter` 与 `ROS2CameraSource`；
- CPU YOLO detector、CapabilityRouterAdapter 和闭环 LangGraph。

2026-11-16 实测结果：

- 初始任务：实验室观察点导航 → 拍照 → person 检测 → 返回起点；
- 首次 `person=false` 后触发 1 次局部重规划；
- 后续任务：走廊观察点导航 → 重新拍照 → 再次检测；
- 共执行 7 个步骤、2 个持久化任务；
- 3 个 Nav2 Goal 均在第 1 次尝试成功，`number_of_recoveries=0`；
- 相机图像为 1920×1080 BGR8；
- YOLO 冷启动推理约 2138 ms，第二次推理约 106 ms；
- 最终状态 `completed`、`goal_satisfied=true`、`replan_count=1`。

证据文件：

- `artifacts/unified/result.json`
- `artifacts/unified/camera.jpg`
- `artifacts/phase8/robot_agent_demo.mp4`

## 3. 工程质量

- GitHub Actions：锁定依赖安装、Ruff、pytest、分支覆盖率与 coverage XML artifact。
- 当前回归：54 项 pytest 通过。
- 核心模块分支覆盖率：87.56%，CI 门禁为 80%。
- ROS2 adapter、ROS2 camera 与 CLI 依赖外部运行时，未计入通用 Linux CI 覆盖率；由 WSL 集成脚本单独验收。
- 提供 Windows PowerShell 与 Bash 一键入口：`scripts/quickstart.ps1`、`scripts/quickstart.sh`。

## 4. 指标边界

- 40 次 Phase 7 结果是确定性软件故障注入，不是 40 次 Gazebo 或真机实验。
- 93.75% 感知 Precision/Recall 是合成标注下的指标链验证，不是公开数据集模型精度。
- 本阶段新增的 7 步结果是真实同栈 Gazebo/ROS2 集成验收，但仍不代表真机安全认证。

