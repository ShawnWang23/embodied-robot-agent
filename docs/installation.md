# 安装与环境复现

本文档对应 2026-11-10 的已验证环境。项目采用 Windows Python 控制面与 WSL2 ROS2
运行面分离的方式，核心模块在没有 ROS2 的 Windows 环境也能开发和测试。

## 1. 已验证版本

| 组件 | 已验证版本 |
|---|---|
| Windows Python | 3.12.15 |
| uv | 0.12.23 |
| Ubuntu | 24.04.5 LTS（WSL2） |
| ROS2 | Jazzy |
| Gazebo Harmonic | 8.15.0 |
| Pydantic | 2.14.3 |
| FastAPI | 0.162.2 |
| OpenCV | 4.11.0 |
| Ultralytics | 8.4.208 |
| PyTorch | 2.15.0+cpu |

## 2. Windows Python 环境

在项目根目录执行：

```powershell
uv sync --extra dev --extra llm --extra perception
uv pip check
uv run pytest -q
```

`uv.lock` 固定完整依赖解析。三个 extra 的用途：

- `dev`：pytest、异步测试和 FastAPI TestClient。
- `llm`：OpenAI Python SDK，同时供 SiliconFlow 的 OpenAI 兼容接口使用。
- `perception`：CPU PyTorch、OpenCV 与 Ultralytics。

## 3. API Key

项目只从环境变量读取密钥，不读取仓库内 `.env`。推荐写入 Windows 用户环境：

```powershell
$secureKey = Read-Host "SILICONFLOW_API_KEY" -AsSecureString
$plainKey = [Net.NetworkCredential]::new('', $secureKey).Password
[Environment]::SetEnvironmentVariable("SILICONFLOW_API_KEY", $plainKey, "User")
[Environment]::SetEnvironmentVariable(
  "SILICONFLOW_MODEL",
  "deepseek-ai/DeepSeek-V4-Flash",
  "User"
)
Remove-Variable plainKey, secureKey
```

重新打开终端后才会自动继承新的用户变量。不要把真实密钥填入 `.env.example`、命令历史、
日志、SQLite 或截图。

## 4. WSL2、ROS2 与感知环境

当前机器已经配置完成。新环境中先检查脚本内容，再按需执行：

```powershell
wsl -d Ubuntu-24.04 -- bash -lc `
  'cd <WSL_PROJECT_PATH> && sudo bash scripts/bootstrap_wsl_user.sh robotagent'
wsl -d Ubuntu-24.04 -- bash -lc `
  'cd <WSL_PROJECT_PATH> && bash scripts/setup_perception_wsl.sh'
```

脚本依赖 ROS2 Jazzy、Nav2、TurtleBot3 Gazebo 包、`cv_bridge` 和可用的软件渲染环境。
感知 Python 环境默认位于 `~/.venvs/robot-agent-perception`，与 Windows `.venv`
分开，避免 ROS2 系统 Python 与 PyTorch 包互相污染。

## 5. 验证顺序

```powershell
# 纯 Python
uv run pytest -q

# ROS2/Nav2 Agent
wsl -d Ubuntu-24.04 -- bash -lc `
  'cd <WSL_PROJECT_PATH> && bash scripts/validate_agent_wsl.sh'

# ROS2 camera + YOLO + Agent
wsl -d Ubuntu-24.04 -- bash -lc `
  'cd <WSL_PROJECT_PATH> && bash scripts/validate_perception_wsl.sh'

# 40 次可靠性基准
uv run python scripts/run_phase7_evaluation.py --repetitions 4
```

## 6. 常见问题

- Windows 无法导入 `rclpy`：这是预期行为；ROS2 adapter 只在已 source Jazzy 的 WSL 中构造。
- 相机无图像：检查 `/camera/image_raw`、QoS endpoint 和 Ogre2 软件渲染设置。
- Nav2 定位不稳定：本项目受控验证使用已知出生点和 Phase 2 文档记录的仿真隔离配置。
- API 启动时报缺少 LLM 密钥：默认使用 `rule` planner；只有切换到 `openai` 或
  `siliconflow` 才需要相应密钥。
- 不要把仿真专用的 `collision_monitor.source_timeout=0` 用于真机。

