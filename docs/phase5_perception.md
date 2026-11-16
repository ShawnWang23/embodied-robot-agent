# Phase 5：ROS2 相机、YOLO 与多模态感知

记录日期：2026-11-10

## 1. 阶段结论

Phase 5 已完成。系统可以从 TurtleBot3 Waffle Pi 的 Gazebo RGB 相机获取真实 ROS2
`sensor_msgs/Image`，通过 `cv_bridge` 转成 OpenCV BGR 图像，使用 CPU 版 PyTorch 和
预训练 `yolo26n.pt` 推理，并把检测结果作为结构化数据传回 MissionManager 和 LangGraph。

```text
/camera/image_raw
      ↓ cv_bridge
CapturedFrame + ImageMetadata
      ↓ Ultralytics YOLO
DetectionResult
      ↓ target_presence
LangGraph: objects_detected / clear
```

Ultralytics 官方当前接口接受 OpenCV BGR `numpy.ndarray`，并通过 `result.boxes` 提供
坐标、类别与置信度；本项目按该接口实现。参见
[Ultralytics Predict 文档](https://docs.ultralytics.com/modes/predict)和
[Object Detection 文档](https://docs.ultralytics.com/tasks/detect)。

## 2. 模块说明

- `perception/models.py`：图像元数据、边界框、检测项和检测结果。
- `perception/interfaces.py`：CameraSource 与 ObjectDetector 接口。
- `perception/camera.py`：FakeCameraSource 和 ROS2CameraSource。
- `perception/detector.py`：FakeObjectDetector 和 UltralyticsYOLODetector。
- `perception/adapter.py`：PerceptionAdapter 与 CapabilityRouterAdapter。
- `agent/models.py`：启用 `capture_image`、`detect_objects` 计划步骤。
- `agent/tools.py`：将视觉计划编译成经过 Pydantic 校验的任务步骤。
- `agent/graph.py`：检测结果条件分支。
- `scripts/setup_perception_wsl.sh`：隔离的 WSL 视觉环境。
- `scripts/validate_perception_wsl.sh`：真实相机、模型与 Agent 验收。

原始像素只保存在进程内的 `CapturedFrame`，不会写入 Task JSON 或 SQLite。任务记录只保存
图像尺寸、来源、时间、检测框、类别和置信度，避免数据库被大图像占满。

## 3. 结构化检测结果

```json
{
  "requested_targets": ["person", "chair"],
  "confidence_threshold": 0.25,
  "detections": [],
  "target_presence": {
    "person": false,
    "chair": false
  },
  "inference_milliseconds": 1531.7
}
```

边界框使用像素坐标 `x1, y1, x2, y2`，Pydantic 会拒绝负坐标和倒置的最大/最小值。
Detector 只保留用户请求的类别以及达到阈值的检测项。

## 4. Agent 条件分支

RuleBasedPlanner 和在线 Planner 现在可以生成：

```text
navigate_to → capture_image → detect_objects
```

MissionManager 完成后，LangGraph 检查所有 `detect_objects` 结果：

- 任一目标存在：`perception_outcome = objects_detected`
- 所有目标均不存在：`perception_outcome = clear`
- 没有视觉步骤：不设置 perception_outcome

这一步只根据经过验证的结构化布尔值路由，不要求 LLM 解释原始像素。

## 5. WSL 依赖环境

ROS2 系统 Python 已包含 `cv_bridge` 和 OpenCV，但没有 PyTorch/Ultralytics。视觉依赖安装在
独立环境 `~/.venvs/robot-agent-perception`，并使用 `--system-site-packages` 访问
ROS2 Python 包。

```bash
bash scripts/setup_perception_wsl.sh
```

实测兼容组合：

- NumPy 1.26.4
- OpenCV 4.11.0
- PyTorch 2.15.0+cpu
- TorchVision 0.29.2+cpu
- Ultralytics 8.4.208

NumPy 固定在 1.26.4 是因为 ROS2 环境中的 SciPy 1.11.4 要求 `<1.28`。安装后
`pip check` 输出 `No broken requirements found`。Ultralytics 官方安装说明见
[Install Ultralytics](https://docs.ultralytics.com/quickstart)。

## 6. WSL/Gazebo 问题与修复

实际调试发现三个环境问题：

1. Nav2 的 `tb3_simulation_launch.py` 使用深度传感器模型，不发布 RGB 图像。
2. WSL D3D12 无法为 RGB 传感器创建无界面 Ogre2 EGL 上下文。
3. `ros_gz_image` 使用 reliable QoS，固定 sensor-data best-effort 订阅在当前 Cyclone DDS
   环境中没有收到回调。

验收脚本改为：

- 运行 TurtleBot3 Waffle Pi 的 SDF RGB 相机模型；
- 使用 `gz sim --headless-rendering`；
- 仅在视觉验收进程中使用 `llvmpipe` 软件渲染；
- ROS2CameraSource 使用 `ReliabilityPolicy.BEST_AVAILABLE` 协商 QoS。

没有修改 `/opt/ros` 中的系统文件，也没有把软件渲染设置写入全局 ROS2 配置。

## 7. 运行与实测结果

```powershell
wsl -d Ubuntu-24.04 -- bash -lc `
  'cd <WSL_PROJECT_PATH> && bash scripts/validate_perception_wsl.sh'
```

实际结果：

- ROS2 相机帧：640×480、BGR8，成功保存到 `artifacts/phase5_camera.jpg`。
- 仿真画面 person/chair 检测：0 个；这与实际空场景一致。
- 首次 CPU 推理约 1.5 秒。
- 官方 `bus.jpg` 阳性对照：检出 4 个 person，最高置信度约 0.872。
- 真实相机 Agent 请求“检查前方是否有人”：任务 completed，进入 `clear` 分支。
- SiliconFlow 在线请求“去实验室门口拍照并检查是否有人”：生成并执行
  `navigate_to → capture_image → detect_objects(person)` 结构化计划。
- Windows pytest：43 passed。

## 8. 当前边界

- 使用预训练通用模型，没有训练室内专用数据集。
- 仿真相机画面没有真实人物或椅子，所以真实相机验收使用空场景，另以官方图片作阳性对照。
- 本阶段分别验证了真实 Nav2 链路和真实 RGB 感知链路；尚未在同一个 Gazebo 启动文件中
  同时运行 Nav2 与 RGB 相机。
- 当前分支只返回 `objects_detected` / `clear`，更复杂的“椅子是否阻挡通道”需要深度、
  几何或分割信息，不能仅凭二维检测框宣称完成。
