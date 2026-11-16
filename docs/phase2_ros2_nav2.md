# Phase 2：ROS2、TurtleBot3 与 Nav2 集成

记录日期：2026-11-09

## 1. 已验证环境

| 组件 | 实测版本或状态 |
| --- | --- |
| Windows / WSL | WSL2 2.5.9，内核 6.6.87.2 |
| Ubuntu | 24.04.5 LTS，systemd 已启用 |
| Python | 3.12.3 |
| ROS 2 | Jazzy Desktop 0.11.0 |
| RMW | Cyclone DDS，显式使用 127.0.0.1 做本机仿真发现 |
| Gazebo | Harmonic，`gz sim` 8.15.0 |
| Nav2 | Jazzy 1.3.13 |
| TurtleBot3 Gazebo | Jazzy 2.3.7 |
| 图形加速 | Mesa D3D12，Intel Arc 140T，OpenGL 4.6；自动回归采用 headless |

WSL 使用镜像网络、DNS tunneling 和自动代理。ROS2 本机仿真配置位于
`config/cyclonedds_localhost.xml` 和 `config/use_ros2_localhost.sh`。该配置只允许
回环接口发现节点，适合单机仿真，不适合直接连接局域网真机。

示例 WSL 用户是 `robotagent`。如果需要交互式使用 `sudo`，请本人在终端中设置密码，
不要把密码写入脚本或仓库：

```powershell
wsl -d Ubuntu-24.04 -u root -- passwd robotagent
```

## 2. 新增架构

```text
MissionManager
    │ TaskStep(action="navigate_to")
    ▼
RobotAdapter 接口
    ├── FakeRobotAdapter       # Windows 单元测试、确定性模拟
    └── ROS2RobotAdapter       # WSL / ROS2
            ├── NavigateToPose Action Client
            ├── /odom Subscriber
            ├── Nav2 feedback snapshot
            └── cancel_goal_async
```

`MissionManager` 不导入 ROS2。它仍然只认识统一的 `RobotAdapter`，所以任务状态机、
SQLite 和超时逻辑没有因为接入 Nav2 而耦合到 `rclpy`。

`ROS2RobotAdapter` 的重要设计：

- `NavigateToParameters` 禁止多余字段，只接受有限的 `x`、`y`、`yaw` 和 `map` 坐标系。
- `MapBounds` 在目标发送给 Nav2 之前做地图边界检查。
- ROS 回调由独立的 `SingleThreadedExecutor` 线程处理，asyncio 任务只等待 ROS future，
  避免阻塞任务管理器。
- 保存距离、预计剩余时间、恢复次数和当前位置等反馈。
- 取消覆盖“目标正在发送但还未返回 goal handle”的竞态窗口。
- 如果 MissionManager 的步骤超时，适配器先取消 Nav2 goal，任务再记录为失败。
- Windows 未安装 ROS2 时仍可导入模块并测试参数模型；真正构造适配器会给出明确错误。

## 3. 运行方式

### Windows 单元测试

```powershell
cd <WINDOWS_PROJECT_PATH>
uv sync --extra dev
uv run pytest -q
```

### WSL 环境和仿真验证

```powershell
wsl -d Ubuntu-24.04 -- bash -lc `
  'cd <WSL_PROJECT_PATH> && bash scripts/validate_ros2_wsl.sh'

wsl -d Ubuntu-24.04 -- bash -lc `
  'cd <WSL_PROJECT_PATH> && bash scripts/validate_turtlebot3_sim_wsl.sh'

wsl -d Ubuntu-24.04 -- bash -lc `
  'cd <WSL_PROJECT_PATH> && bash scripts/validate_nav2_wsl.sh'

wsl -d Ubuntu-24.04 -- bash -lc `
  'cd <WSL_PROJECT_PATH> && bash scripts/validate_ros2_adapter_wsl.sh'
```

WSL 项目虚拟环境默认位于 `~/robot_agent_venv`，创建方式是：

```bash
python3 -m venv --system-site-packages "${HOME}/robot_agent_venv"
"${HOME}/robot_agent_venv/bin/python" -m pip install -e <WSL_PROJECT_PATH>
```

`--system-site-packages` 用于让虚拟环境复用 apt 安装的 `rclpy`，Pydantic 和本项目仍由
虚拟环境自己的 pip 管理。

## 4. 实际测试结果

以下不是模拟输出，而是本机实际运行结果：

- `validate_ros2_wsl.sh`：Cyclone DDS talker/listener 成功发现，收到 6 条 `/chatter` 消息。
- `validate_turtlebot3_sim_wsl.sh`：Gazebo 启动，存在 `/cmd_vel`、`/odom`、`/scan`、
  `/tf`，成功读取真实 `/odom` 样本；退出后仿真进程清理完成。
- `validate_nav2_wsl.sh`：Nav2 lifecycle、静态地图和 action server 就绪；
  `NavigateToPose` 返回 `SUCCEEDED`，机器人从 `x≈-2.000` 移动到 `x≈-1.748`。
- `validate_ros2_adapter_wsl.sh` 最后一次运行：
  - 两个连续目标均返回成功；
  - 收到 581 条反馈样本；
  - 第三个远目标被主动取消，返回 `error_code="cancelled"`；
  - MissionManager 的 0.5 秒真实导航超时产生 `step_timed_out` 和 `task_failed`；
  - 取消后最终里程计线速度和角速度均为 0；
  - 测试退出后没有残留 Gazebo、Nav2 或静态 TF 进程。
- Windows `uv run pytest -q`：18 passed。

## 5. 已知问题和测试隔离

当前 Jazzy 二进制栈在这台机器的 WSL mirrored networking + Cyclone DDS 组合下还有三项
未通过，不能把受控冒烟测试描述成默认 Nav2 全栈成功：

1. 默认静态地图 + AMCL 能进入 active，也收到 `/initialpose`，但不发布 `/amcl_pose`
   或 `map → odom`。
2. `slam_toolbox` 能进入 active 并订阅 `/scan`，但不发布第一张 `/map`。
3. `collision_monitor` 报 observation source 无效并把最终 `/cmd_vel` 置零；同时命令行、
   local costmap 和独立 TF 查询均能收到同一 `/scan` 与 TF，问题缩小到该节点内部订阅。
4. 官方 `turtlebot3_world.launch.py` 会无条件启动 Gazebo GUI；当前 Mesa D3D12 组合下 GUI/
   相机渲染线程可能段错误。因此自动测试使用 Nav2 提供的 `headless:=True` TurtleBot3
   启动方式。服务端仿真和 GPU 加速检测不受此 GUI 限制影响。

因此两个 Nav2 验证脚本使用了明确标注的测试接缝：

- 用静态 `map → odom` 表达 Gazebo 已知出生点 `(-2, -0.5)`，只验证规划、控制和 action。
- 临时 Nav2 参数副本把 collision monitor 的 `source_timeout` 设为 `0.0`，防止这个已知
  订阅故障阻断速度链。

这些改动只存在于 `mktemp` 测试目录，退出即删除，官方参数没有被改动。`source_timeout=0`
会关闭传感器失效即停保护，**严禁用于真机、共享环境或任何安全验收**。默认碰撞监控和
AMCL/SLAM 仍是后续环境加固项。

## 6. 文件说明

- `src/robot_agent/adapters/ros2_robot.py`：Nav2 Action Client、状态读取、反馈和取消。
- `tests/test_ros2_robot.py`：导航参数、地图边界和无 ROS 环境行为测试。
- `scripts/ros2_adapter_smoke.py`：两个成功目标、主动取消和 MissionManager 超时场景。
- `scripts/validate_ros2_adapter_wsl.sh`：启动/激活仿真栈并运行真实适配器测试。
- `scripts/validate_nav2_wsl.sh`：独立的 Nav2 action 冒烟测试和链路诊断。
- `scripts/validate_ros2_wsl.sh`：DDS Topic 通信验证。
- `scripts/validate_turtlebot3_sim_wsl.sh`：Gazebo、传感器和进程清理验证。
- `config/use_ros2_localhost.sh`：本机仿真环境入口。

