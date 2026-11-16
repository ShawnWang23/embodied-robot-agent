# 项目演示指南

## 1. 已生成视频

`artifacts/phase8/robot_agent_demo.mp4` 是约 30 秒、1280×720、无旁白的交付演示。视频读取：

- Phase 5 保存的真实 ROS2 相机图像；
- Phase 6 FastAPI + SiliconFlow 持久化任务快照；
- Phase 7 有效 40 次实验汇总。

它不会合成机器人运动画面，也不会把 FakeRobot 指标描述成 Gazebo 或真机结果。
`robot_agent_demo_preview.jpg` 是从 MP4 解码抽帧生成的视觉联系表，用于快速检查布局和内容。

重新生成：

```powershell
uv run python scripts/create_demo_video.py
```

新版视频读取 `artifacts/unified/result.json` 与 `artifacts/unified/camera.jpg`，增加同栈相机画面、7 步执行 trace 和感知触发重规划的分屏证据；生成结果为 1280×720、20 FPS、44 秒。

统一仿真证据可通过以下命令重新生成：

```bash
bash scripts/validate_unified_sim_wsl.sh
```

## 2. 现场演示顺序（约 5–8 分钟）

1. 打开 README，解释四层架构和安全边界。
2. 运行 `uv run pytest -q`，展示 54 项回归与覆盖率门禁。
3. 启动 `uv run robot-agent-api`，打开 `http://127.0.0.1:8000/docs`。
4. 提交多地点任务，轮询任务、事件和 checkpoint。
5. 展示人工接管与双确认恢复请求。
6. 运行 Phase 7 30 次快速基准或打开已保存 40 次报告。
7. 在环境允许时运行 Nav2 与 perception WSL 验收脚本。

## 3. 录制真实 Gazebo UI 的建议

当前自动交付视频主要展示架构和真实持久化产物。若需要答辩用 Gazebo UI 视频，建议使用
OBS 录制交互式 Gazebo/RViz，同时在另一窗口显示 API 任务状态。画面中应明确标注
“Gazebo simulation”，不要写成 real robot。建议镜头：

- TurtleBot3 出生点与目标点；
- Nav2 goal 发送、反馈与完成；
- `/camera/image_raw` 和检测结果；
- 临时障碍/失败注入后的重试或人工接管；
- 返回起点和最终任务报告。

