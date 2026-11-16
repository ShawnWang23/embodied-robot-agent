# Phase 8 最终交付清单

## 1. 代码

- Agent：`src/robot_agent/agent/`
- Mission/FSM/Recovery：`src/robot_agent/mission/`
- Fake/ROS2 adapter：`src/robot_agent/adapters/`
- Camera/YOLO：`src/robot_agent/perception/`
- FastAPI：`src/robot_agent/api/`
- SQLite：`src/robot_agent/storage/`
- Reliability evaluation：`src/robot_agent/evaluation/`
- 自动化测试：`tests/`

## 2. 文档

| 交付项 | 文件 |
|---|---|
| 总入口与快速开始 | `README.md` |
| 安装与环境 | `docs/installation.md` |
| 系统架构 | `docs/architecture.md` |
| 架构/工作流/FSM 图 | `docs/diagrams.md` |
| FastAPI 接口 | `docs/api_reference.md` |
| ROS2 节点与接口 | `docs/ros2_nodes.md` |
| 最终测试报告 | `docs/test_report.md` |
| Phase 7 原始评估说明 | `docs/phase7_reliability.md` |
| 演示与录制指南 | `docs/demo_guide.md` |
| 分阶段开发记录 | `docs/phase0...phase7...`、`docs/progress.md` |

## 3. 机器可读与媒体产物

- `artifacts/phase8/openapi.json`
- `artifacts/phase8/robot_agent_demo.mp4`
- `artifacts/phase8/robot_agent_demo_preview.jpg`
- `artifacts/unified/result.json`
- `artifacts/unified/camera.jpg`
- `artifacts/phase5_camera.jpg`
- `artifacts/phase7/20261110T133038290474Z/records.jsonl`
- `artifacts/phase7/20261110T133038290474Z/summary.json`
- `artifacts/phase7/20261110T133038290474Z/report.md`

## 4. 验收状态

- 54 项 pytest 通过，核心模块分支覆盖率 87.56%。
- 40 次标准可靠性场景完成并保存原始记录。
- ROS2/Nav2、ROS2 camera/YOLO、SiliconFlow 和 FastAPI 分别完成真实链路验收。
- Nav2、Camera、YOLO 与受限重规划已在同一 Gazebo Waffle 实例中完成统一验收。
- 依赖检查、密钥扫描和残留进程检查通过。

## 5. 已知边界

- API 默认 runtime 仍是 FakeRobotAdapter；ROS2 runtime 通过独立脚本接入。
- 没有真实机器人测试、生产认证、API 鉴权、多租户或多机器人调度。
- Perception Precision/Recall 是合成标注的指标链验证，不是公开数据集模型评测。
- 本地 Git 历史、CI、License 与发布材料已补齐；远程仓库地址取决于发布账号。

