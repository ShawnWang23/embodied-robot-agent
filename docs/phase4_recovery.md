# Phase 4：闭环任务执行与异常恢复

记录日期：2026-11-10

## 1. 阶段结论

Phase 4 已完成。MissionManager 现在会监控执行结果与导航反馈，对失败进行确定性分类，
再选择有限重试、显式备用地点、人工接管或立即失败。恢复逻辑不由 LLM 自由生成，且每个
步骤和整项任务都有硬上限。

```text
RobotAdapter result / feedback
          ↓
   FailureCategory
          ↓
    RecoveryPolicy
      ├─ retry（有限次数）
      ├─ use_fallback（仅配置中的地点）
      ├─ request_human（停止自主执行）
      └─ fail（不可安全恢复）
```

## 2. 核心模块

- `mission/recovery.py`：失败分类、恢复动作和硬限制。
- `mission/manager.py`：多次尝试、反馈采样、备用点切换和人工接管状态。
- `core/models.py`：尝试次数、失败历史、人工接管字段和审计事件。
- `agent/locations.py`：校验备用地点引用和有限坐标。
- `agent/tools.py`：将受信任的备用地点编译到任务元数据。
- `adapters/fake_robot.py`：按顺序注入成功或失败结果，保证测试可重复。
- `config/recovery.json`：步骤尝试上限和整单失败上限。
- `scripts/validate_recovery.py`：七类故障的一次性验收脚本。

## 3. 恢复策略

| 故障类型 | 自动处理 | 上限耗尽后 |
|---|---|---|
| 导航超时 | 重试 | 请求人工接管 |
| 目标不可达 | 优先使用显式备用点，否则重试 | 请求人工接管 |
| 路径被阻挡 | 优先使用显式备用点，否则重试 | 请求人工接管 |
| 工具调用失败 | 重试 | 请求人工接管 |
| 视觉检测失败 | 重试 | 请求人工接管 |
| 非法参数 | 不重试 | 任务失败 |
| 未知错误或意外取消 | 不重试 | 任务失败 |

默认配置为每个步骤最多 3 次尝试、整单最多 5 次失败。恢复动作均经过事件日志记录。

当前地点目录只为 `laboratory_door` 声明了 `corridor_observation` 备用点。备用点来自
`config/locations.json`，不是 LLM 生成的坐标。切换后仍会经过 ROS2 adapter 的坐标、
地图边界和 Nav2 目标校验。

## 4. 状态机与人工接管

```text
PENDING ──→ RUNNING ──→ COMPLETED
                 ├────→ FAILED
                 ├────→ PAUSED ──→ RUNNING
                 ├────→ CANCELLED
                 └────→ WAITING_FOR_HUMAN ──→ RUNNING
```

步骤重试使用 `RUNNING → PENDING → RUNNING`。进入 `WAITING_FOR_HUMAN` 后执行器释放机器人，
不会继续发送动作。恢复必须调用：

```python
await manager.resume_after_human(
    task_id,
    robot_state_confirmed=True,
    environment_confirmed=True,
)
```

直接调用 `execute_task`，或缺少任意一项确认，都会被拒绝。Phase 6 已增加 FastAPI
接管与恢复入口。

## 5. 反馈与审计

MissionManager 通过 `RobotAdapter.get_execution_feedback()` 轮询非阻塞反馈。ROS2 adapter
返回 Nav2 的当前位置、剩余距离、预计剩余时间和内部恢复次数。变化后的快照写入
`navigation_feedback` 事件。

每次失败还会保存：

- 尝试编号和原始错误码；
- 归一化失败类别；
- 恢复动作和原因；
- 备用点切换前后的语义地点；
- 是否已请求或确认人工接管。

## 6. 运行方式

Windows 故障注入验收：

```powershell
uv run python scripts/validate_recovery.py
uv run pytest -q
```

ROS2/Nav2 成功路径回归：

```powershell
wsl -d Ubuntu-24.04 -- bash -lc `
  'cd <WSL_PROJECT_PATH> && bash scripts/validate_agent_wsl.sh'
```

## 7. 实际验收结果

- Windows pytest：35 passed。
- 导航超时：3 次尝试后进入 `waiting_for_human`。
- 目标不可达：切换到 `corridor_observation`，第 2 次尝试成功。
- 路径阻挡：切换到 `corridor_observation`，第 2 次尝试成功。
- 工具失败：第 2 次尝试成功。
- LLM 非法 action：Pydantic 在进入 MissionManager 前拒绝；机器人执行 0 次。
- adapter 非法参数：不重试，执行 1 次后失败。
- 视觉检测失败：第 2 次尝试成功。此项使用模拟 adapter；真实视觉将在 Phase 5 接入。
- 连续工具失败：3 次后进入 `waiting_for_human`。
- 人工恢复：未确认状态时拒绝；确认后可继续并完成。
- ROS2/Nav2 回归：两个真实仿真导航目标均成功，失败计数为 0。

## 8. 当前边界

- 故障注入使用确定性的 FakeRobotAdapter；没有把它描述成真机或 Gazebo 障碍物实验。
- Gazebo/Nav2 已回归成功路径，Phase 2 记录的 AMCL/SLAM 与 collision monitor 限制仍存在。
- 视觉失败目前只能模拟；Phase 5 接入相机和检测器后再做真实感知恢复验收。
- 动态重规划当前是受配置约束的备用地点切换，不调用 LLM 临时创造路线或坐标。
- Phase 6 已实现 FastAPI 控制接口；独立可视化 Web UI 仍未实现。
