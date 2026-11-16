# ROS2 节点与接口说明

本项目没有创建独立的 `ament_python` ROS2 package，而是在 Python adapter 构造时创建轻量
`rclpy` Node。这样 Windows 领域模型保持可导入，ROS2 依赖只存在于 WSL 集成边界。

## 1. ROS2RobotAdapter

默认节点名：`robot_agent_adapter_<8位随机ID>`

| 类型 | 名称 | ROS 类型 | 用途 |
|---|---|---|---|
| Action Client | `/navigate_to_pose` | `nav2_msgs/action/NavigateToPose` | 发送地图坐标目标、接收反馈和结果 |
| Subscription | `/odom` | `nav_msgs/msg/Odometry` | 获取位置、速度和状态 |

关键行为：

- `NavigateToParameters` 拒绝额外字段、NaN/Inf、非法 yaw 和非 `map` frame。
- `MapBounds` 在目标进入 Nav2 前检查地图边界。
- ROS callback 在独立 `SingleThreadedExecutor` 线程运行，asyncio 不阻塞 ROS spin。
- Nav2 feedback 被规范化为当前位姿、剩余距离、预计时间和内部恢复次数。
- 超时、任务取消或 Python coroutine 取消时，主动取消当前 Nav2 goal。

## 2. ROS2CameraSource

默认节点名：`robot_agent_camera_<8位随机ID>`

| 类型 | 名称 | ROS 类型 | 用途 |
|---|---|---|---|
| Subscription | `/camera/image_raw` | `sensor_msgs/msg/Image` | 获取 TurtleBot3 RGB 图像 |

图像通过 `cv_bridge.imgmsg_to_cv2(..., desired_encoding="bgr8")` 转为 OpenCV 格式。订阅使用
`BEST_AVAILABLE` reliability、depth 5，并对首次图像设置明确超时。

## 3. 能力路由

```text
CapabilityRouterAdapter
  ├─ navigate_to / get_robot_status → ROS2RobotAdapter
  └─ capture_image / detect_objects → PerceptionAdapter
                                      ├─ ROS2CameraSource
                                      └─ UltralyticsYOLODetector
```

原始像素不进入 Task SQLite；任务只保存 frame metadata、检测框、置信度和
`target_presence`，避免数据库膨胀。

## 4. 启动与验证

```powershell
wsl -d Ubuntu-24.04 -- bash -lc `
  'cd <WSL_PROJECT_PATH> && bash scripts/validate_agent_wsl.sh'
wsl -d Ubuntu-24.04 -- bash -lc `
  'cd <WSL_PROJECT_PATH> && bash scripts/validate_perception_wsl.sh'
```

当前 Nav2 和 RGB 感知分别通过真实 Gazebo/ROS2 链路验收，但没有统一为同一个 Gazebo launch
文件。Phase 2 记录的 AMCL/SLAM 与 collision monitor 仿真限制仍适用。

