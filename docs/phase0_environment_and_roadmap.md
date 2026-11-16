# Phase 0：环境检查与开发路线图

检查日期：2026-11-07（Asia/Shanghai）

## 1. 实测环境

| 检查项 | 实测结果 | 结论 |
|---|---|---|
| 主机系统 | Windows 11 家庭中文版，64 位，build 26300 | 不是 ROS 2 Jazzy 的目标 Ubuntu 环境 |
| CPU / 内存 | Intel Core Ultra 9 285H，16 逻辑处理器，63.5 GB RAM | 足够进行开发和本地仿真 |
| GPU | Intel Arc 140T，Windows 驱动 32.0.101.8826 | 可尝试 WSLg 图形加速；YOLO 加速能力需进入 WSL 后实测 |
| 默认 Python | CPython 3.10.8 | 不符合项目目标版本 |
| 可用 Python | uv 管理的 CPython 3.12.15 | Phase 1 使用此解释器 |
| SQLite | 3.53.1（Python 3.12 内置） | 可用 |
| uv | 0.12.23 | 可用于隔离项目依赖 |
| Git | 已安装；当前目录是无提交的新仓库 | 可用 |
| WSL | WSL 2.5.9，Linux kernel 6.6.87.2 | WSL 组件已具备 |
| Linux 发行版 | 未发现已注册发行版 | 缺少 Ubuntu 24.04 |
| ROS2 / Gazebo / RViz2 | Windows PATH 中均未发现 | 当前不能运行机器人仿真 |
| 现有项目文件 | 检查时除 `.git` 外为空 | 可以从最小骨架开始，不存在需保护的旧模块 |

## 2. 兼容性判断

ROS 2 Jazzy、Gazebo Harmonic 和 Ubuntu 24.04 是官方匹配组合。当前 Windows 主机不适合直接承担这套 ROS2 环境；最合理方案是：

1. Phase 1 在 Windows 使用 Python 3.12 开发与测试纯 Python 核心。
2. 用户确认后安装 WSL2 的 Ubuntu 24.04，并在 Linux 文件系统内建立 ROS2 工作副本。
3. 在 Ubuntu 中安装 ROS 2 Jazzy、Nav2、TurtleBot3、Gazebo Harmonic 和 `ros_gz`。
4. 使用 WSLg 运行 Gazebo/RViz；进入 Ubuntu 后先用 `glxinfo`、`gz sim` 实测渲染稳定性。
5. 如果 WSLg 的 3D 仿真不稳定，再迁移到 Ubuntu 双系统或独立 Ubuntu 主机；核心 Python 模块无需改写。

不要在当前阶段安装 ROS2 的 Windows 版本，也不要把 ROS2 包混入 Windows 的 Python 虚拟环境。

官方依据：

- [Gazebo：ROS 2 Jazzy 与 Gazebo Harmonic 兼容组合](https://gazebosim.org/docs/harmonic/ros_installation/)
- [Microsoft：WSL2 Linux GUI 与 vGPU 前提](https://learn.microsoft.com/windows/wsl/tutorials/gui-apps)

## 3. 缺少的依赖

Phase 1 当前需要的项目级依赖：Pydantic 2、pytest、pytest-asyncio。它们由 `uv` 安装到项目 `.venv`，不修改系统 Python。

Phase 2 前仍缺少：

- WSL2 Ubuntu 24.04 发行版。
- ROS 2 Jazzy Desktop。
- Gazebo Harmonic 与 ROS/Gazebo bridge。
- Nav2、TurtleBot3 仿真包、colcon 和 rosdep。
- WSL 内的图形渲染验证。

视觉阶段再决定 PyTorch 对 Intel GPU 的实际加速路径。第一版允许 CPU 推理，不能预先假设 CUDA 可用。

## 4. 最终目录设计

采用 `src` 布局，避免从仓库根目录意外导入未安装源码。目录会随阶段逐步创建：

```text
robot_agent/
├── src/robot_agent/
│   ├── agent/          # Phase 3: LangGraph、规划、工具、记忆
│   ├── core/           # 跨层模型、接口、异常、日志
│   ├── mission/        # Mission Manager、FSM、恢复策略
│   ├── adapters/       # Fake 与 ROS2 机器人适配器
│   ├── perception/     # Phase 5: 相机和检测器
│   ├── api/            # Phase 6: FastAPI
│   ├── storage/        # SQLite 仓库和持久化
│   └── cli.py
├── ros2_ws/src/        # Phase 2: ROS2 packages
├── config/
├── data/               # 本地运行数据，不提交数据库
├── docs/
├── scripts/
├── tests/
├── pyproject.toml
├── .env.example
└── README.md
```

调整理由：新增 `src/` 与 `storage/`。前者提升打包和测试可靠性；后者避免把 SQLite 细节塞进 Mission Manager。

## 5. 十周路线图

| 周 | 阶段 | 可验收交付物 |
|---|---|---|
| 1 | Phase 0 + Phase 1a | 环境报告；模型、接口、Fake adapter、SQLite、最小 CLI 闭环 |
| 2 | Phase 1b | 暂停/恢复/取消、超时、异常日志、状态转换测试、CLI 完整验收 |
| 3 | Phase 2a | Ubuntu/ROS2 环境验证；Topic/Service/Action 教学示例；TurtleBot3 仿真启动 |
| 4 | Phase 2b | ROS2RobotAdapter、Nav2 多目标、反馈、取消和超时集成测试 |
| 5 | Phase 3 | LangGraph 状态图、结构化规划、工具注册与参数校验、checkpointer |
| 6 | Phase 4a | 上层 FSM、错误分类、有限重试、导航恢复策略 |
| 7 | Phase 4b | 备用观察点、动态重规划、人工接管与故障注入测试 |
| 8 | Phase 5 | 相机订阅、OpenCV、预训练 YOLO、结构化感知结果与条件分支 |
| 9 | Phase 6 | 多地点编排、重启恢复前状态复核、FastAPI、持久化上下文 |
| 10 | Phase 7 + 8 | 30–50 次可重复测试、指标汇总、文档、架构图和演示材料 |

路线图按每周约 10–15 小时设计。仿真环境问题可能使第 3–4 周顺延，但不应污染纯 Python 核心。

## 6. Phase 1 范围与验收

Phase 1 的完整目标是独立于 ROS2 的可靠任务管理核心，已分两个增量交付：

- 定义任务、步骤、状态和适配器接口。
- 创建并查询任务。
- 使用 FakeRobotAdapter 顺序执行多步骤任务。
- 成功或失败后持久化状态。
- CLI 可见每一步结果。
- pytest 覆盖成功和失败主路径。
- 支持协作式暂停、恢复和取消。
- 每一步具有独立超时，拒绝无限等待。
- FSM 统一校验任务与步骤状态转换。
- SQLite 持久化结构化生命周期和异常事件。
- 同一时间只允许一个任务使用机器人。

本增量验收命令：

```powershell
uv run pytest
uv run robot-agent demo --database data/tasks.db
uv run robot-agent control-demo --database data/tasks.db
```

2026-11-07 Phase 1a 实测：`uv run pytest -q` 为 `4 passed`；CLI 完成 5 个模拟步骤并将任务标记为 `completed`。

2026-11-09 Phase 1b 实测：支持暂停、恢复、取消、单步超时、互斥执行和事件审计；`uv run pytest -q` 为 `10 passed`。

Phase 1 核心范围已完成。跨进程任务控制、程序重启恢复和更复杂的 SQLite 报表查询分别留到 FastAPI、长程任务和测试评估阶段。

