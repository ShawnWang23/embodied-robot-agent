# 最终测试报告

测试日期：2026-11-10

## 1. 自动化测试

```powershell
uv run pytest -q
```

2026-11-16 最新结果：`54 passed`。核心模块分支覆盖率 `87.56%`，CI 门禁为 `80%`。覆盖：

- 任务创建、执行、暂停、恢复、取消和单机器人互斥。
- FSM 非法转换、超时、失败分类、有限重试和备用地点。
- Pydantic 计划 schema、未知地点/工具拒绝和两类 LLM 客户端协议。
- ROS2 adapter 参数、地图边界和缺失运行时行为。
- 相机、检测结果结构、感知分支和 YOLO 输出规范化。
- SQLite task/event、AsyncSqliteSaver、API 重启恢复和双确认。
- 10 场景可靠性基准、指标分母、JSONL 往返和禁止覆盖旧报告。

`uv pip check`：85 个已安装包兼容。

## 2. Phase 7 标准基准

有效 run：`20261110T133038290474Z`，40 条原始记录，0 个 evaluation error。

| 指标 | 结果 |
|---|---:|
| Expectation Pass Rate | 100.00% |
| Task Success Rate | 80.00% |
| Average Completion Time | 0.146341 s |
| Recovery Success Rate | 80.00% |
| Tool Calling Success Rate | 71.43% |
| Human Intervention Rate | 30.00% |
| Synthetic Perception Precision / Recall | 93.75% / 93.75% |

完整分子、分母和场景拆分见 `docs/phase7_reliability.md` 与对应 artifact。

## 3. 真实 WSL/ROS2/Gazebo 验收

- LangGraph → MissionManager → ROS2RobotAdapter → Nav2：两个导航目标成功。
- Nav2 两步 `number_of_recoveries=0`，每步一次完成。
- `/camera/image_raw`：640×480、BGR8。
- YOLO26n CPU 空仿真帧：person/chair 未检出。
- Ultralytics 阳性对照：4 个 person，最高置信度约 0.872。
- Camera → YOLO → MissionManager → LangGraph：任务 completed，`clear` 分支。
- 验收退出后无 ROS2/Nav2/Gazebo 残留进程。

### 统一导航、视觉与重规划栈（2026-11-16）

- 同一 Gazebo Waffle 实例同时提供 Nav2、`/odom` 和 1920×1080 `/camera/image_raw`。
- 初始 4 步任务未检测到 person 后，Agent 生成并重新校验 3 步备用观察计划。
- 共执行 7 步、2 个任务；3 个 Nav2 Goal 均一次成功，Nav2 recovery 为 0。
- YOLO 两次推理完成，最终 `completed`、`goal_satisfied=true`、`replan_count=1`。
- 结构化结果保存在 `artifacts/unified/result.json`，相机帧保存在 `artifacts/unified/camera.jpg`。

## 4. 在线 LLM 验收

- SiliconFlow 结构化三地点计划：`laboratory_door → meeting_room → start`。
- FastAPI → SiliconFlow → FakeRobot：completed，9 条事件、7 个 checkpoint。
- 未知地点和不合法计划在 RobotAdapter 前被拒绝。
- 密钥只存在于 Windows 用户环境，仓库扫描未发现 `sk-...` 格式密钥。

## 5. 不能从这些结果得出的结论

- 40 次 FakeRobot 运行不等于 40 次 Gazebo 物理实验。
- 两张视觉正/负对照不足以声明 YOLO 的真实数据集 Precision/Recall。
- Gazebo 成功不等于真机安全认证。
- 当前 API 没有认证、多进程锁、真实 ROS runtime 注入或生产部署加固。

