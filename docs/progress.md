# 开发进度

## 2026-11-16

- [x] Agent 新增执行结果审查、感知驱动局部重规划与任务历史。
- [x] 新增最大重规划次数和总步骤数双重执行预算。
- [x] 同一 Gazebo Waffle 实例完成 Nav2 + 1920×1080 Camera + YOLO + Replan 统一验收。
- [x] 统一任务执行 7 步、3 个 Nav2 Goal 均一次成功，最终 `goal_satisfied=true`。
- [x] 新增 GitHub Actions、MIT License、Ruff、coverage XML 与 80% 覆盖率门禁。
- [x] 最新回归：54 passed，核心模块分支覆盖率 87.56%。
- [x] 新版 44 秒演示视频加入真实相机、执行 trace 与重规划证据。

## 2026-11-07

- [x] Phase 0 环境检查。
- [x] 确认 Windows/WSL/ROS2/Gazebo 状态。
- [x] 设计分层目录和十周路线图。
- [x] Phase 1a：任务模型、适配器接口、Fake adapter、SQLite repository。
- [x] Phase 1a：创建/执行/查询最小闭环和 CLI。
- [x] Phase 1a：成功、失败和持久化测试。
- [x] 实测 `uv run pytest -q`：4 passed；CLI 五步骤任务：completed。
- [x] Phase 1b：暂停、恢复、取消和单步超时。
- [x] Phase 1b：严格状态转换表与结构化事件日志。

## 2026-11-09

- [x] `RobotAdapter` 增加当前动作取消契约。
- [x] 单机器人互斥执行，拒绝并发任务争用机器人。
- [x] CLI 增加 `control-demo` 和 `show`。
- [x] 实测 `uv run pytest -q`：10 passed。
- [x] 安装并验证 WSL2 Ubuntu 24.04、ROS2 Jazzy、Gazebo Harmonic、Nav2、TurtleBot3。
- [x] 修复 WSL 网络、Cyclone DDS 本机发现和 Intel D3D12 图形加速配置。
- [x] 实测 ROS2 Topic talker/listener、Gazebo `/odom` 和退出进程清理。
- [x] 新增 `ROS2RobotAdapter`：Nav2 Action、反馈、里程计状态和取消。
- [x] 新增目标字段、有限数、坐标系和地图边界校验。
- [x] 真实仿真集成：两个目标成功、主动取消成功、超时事件持久化、最终速度为零。
- [x] 实测 `uv run pytest -q`：18 passed。
- [ ] 环境加固：解决默认 AMCL/SLAM 不输出和 collision monitor 收不到 observation source。
- [x] Phase 2 受控仿真验收完成；真机安全验收不在本阶段范围内。

## 2026-11-10

- [x] 引入 LangGraph 1.2.20 和内存 checkpointer。
- [x] 新增 Pydantic `TaskPlan`、可执行 action 白名单和条件路由。
- [x] 新增语义地点目录，拒绝未知地点和坐标幻觉。
- [x] 新增 Tool Registry；`navigate_to`、`get_robot_status` 可执行。
- [x] 为 Phase 4/5 工具定义参数模型并标记为不可用。
- [x] 实现离线 RuleBasedPlanner 和可选 OpenAI Structured Outputs planner。
- [x] LangGraph → MissionManager → ROS2RobotAdapter → Nav2 真实仿真两目标成功。
- [x] OpenAI Python SDK 2.54.0 接口签名和假客户端调用测试通过。
- [x] 新增 SiliconFlow Chat Completions Structured Outputs 兼容层。
- [x] 新增三场景在线 planner 验收脚本，后两类会断言 RobotAdapter 未执行。
- [x] 实测 `uv run pytest -q`：27 passed。
- [ ] OpenAI 在线规划验收：当前环境没有 `OPENAI_API_KEY`，未执行真实 API 请求。
- [x] SiliconFlow 在线规划验收：正常三地点任务 completed，执行顺序正确。
- [x] SiliconFlow 安全验收：未知地点和未支持视觉能力均在 RobotAdapter 前拒绝。
- [x] Phase 3 最终验收完成。
- [x] Phase 4：新增确定性失败分类与有上限的恢复策略。
- [x] Phase 4：导航不可达和路径阻挡可切换到显式备用观察点。
- [x] Phase 4：连续失败进入 `waiting_for_human`，恢复前强制确认机器人状态。
- [x] Phase 4：导航反馈、失败历史、重试和接管事件持久化。
- [x] Phase 4：七类主动故障注入验收通过。
- [x] Phase 4 回归：Windows `35 passed`；ROS2/Nav2 两目标真实仿真成功。
- [x] 修复 SQLite 事务完成后未显式关闭连接导致的 Windows 临时文件锁。
- [x] Phase 4 最终验收完成。
- [x] Phase 5：新增 CameraSource、ObjectDetector 和结构化感知模型。
- [x] Phase 5：实现 ROS2 `/camera/image_raw` 订阅与 `cv_bridge` BGR 转换。
- [x] Phase 5：实现 Ultralytics YOLO26 CPU 推理、类别过滤和置信度阈值。
- [x] Phase 5：启用 `capture_image`、`detect_objects` Tool Calling。
- [x] Phase 5：新增 CapabilityRouterAdapter，导航与视觉 adapter 解耦。
- [x] Phase 5：LangGraph 新增 `objects_detected` / `clear` 条件分支。
- [x] Phase 5：修复 WSL Ogre2 RGB 传感器的软件渲染和 ROS2 QoS 协商问题。
- [x] Phase 5：真实 TurtleBot3 相机 640×480 图像采集和 YOLO 推理通过。
- [x] Phase 5：YOLO 官方阳性对照图检出 4 个 person，最高置信度约 0.872。
- [x] Phase 5：真实相机 → YOLO → MissionManager → LangGraph `clear` 分支通过。
- [x] Phase 5：SiliconFlow 在线视觉计划生成通过。
- [x] Phase 5 最终验收完成：43 passed、WSL `pip check` 无冲突、无残留仿真进程。
- [x] Phase 6：LangGraph 图拆分为 `plan → validate → create_task → execute`，先持久化任务 ID 再执行。
- [x] Phase 6：使用独立 `tasks.db` 与 `checkpoints.db` 保存任务事件和 Agent thread 状态。
- [x] Phase 6：FastAPI lifecycle 统一创建、迁移和关闭 `AsyncSqliteSaver`。
- [x] Phase 6：新增任务提交、查询、暂停、取消、人工接管、恢复、事件和 checkpoint 历史接口。
- [x] Phase 6：进程中断任务自动转为 `waiting_for_human`，运行步骤退回 `pending`。
- [x] Phase 6：恢复前强制确认机器人状态和现场环境，禁止盲目重放。
- [x] Phase 6：API 可通过 `ROBOT_AGENT_PLANNER` 选择 rule、OpenAI 或 SiliconFlow planner。
- [x] Phase 6 最终回归：Windows `49 passed`，SQLite 关闭重开与 API 重启恢复均通过。
- [x] Phase 6 在线验收：FastAPI → SiliconFlow → 三地点计划 → FakeRobot 执行 completed，9 条事件、7 个 checkpoint。
- [x] Phase 7：建立 10 类标准场景和强制 30–50 次的可重复评估运行器。
- [x] Phase 7：逐次保存状态、耗时、恢复、人工接管、工具尝试和感知混淆矩阵。
- [x] Phase 7：生成 JSONL 原始记录、JSON 汇总和 Markdown 报告，指标可独立复算。
- [x] Phase 7：正式完成 40 次软件级故障注入；40/40 预期行为通过，0 个评估器错误。
- [x] Phase 7：Task Success 80%、平均 0.146341 s、Recovery Success 80%、Tool Calling Success 71.43%。
- [x] Phase 7：Human Intervention 30%、合成标注 Precision/Recall 均为 93.75%。
- [x] Phase 7：真实 WSL Nav2 两目标回归完成，两个 goal 成功且 Nav2 recovery 均为 0。
- [x] Phase 7：真实 ROS2 RGB 640×480 与 YOLO 回归完成，阳性对照检出 4 人，Agent `clear` 分支完成。
- [x] Phase 7 最终验收：Windows `52 passed`、依赖无冲突、密钥扫描干净、无 ROS/Gazebo 残留进程。
- [x] Phase 8：完成安装、FastAPI、ROS2 节点、系统图/工作流/FSM 和最终测试文档。
- [x] Phase 8：导出 OpenAPI 3.1.0，覆盖 9 条 API path。
- [x] Phase 8：根据真实 Phase 5/6/7 产物生成 1280×720、32.5 秒 MP4 演示视频。
- [x] Phase 8：视频 650 帧可解码，视觉联系表人工抽查无空帧和中文乱码。

