# Phase 6：持久化 Checkpoint、重启恢复与 FastAPI

记录日期：2026-11-10

## 1. 阶段结论

Phase 6 已完成。服务现在可接收长程自然语言任务、持久化任务进度和 LangGraph 状态，
并在进程重启后安全恢复控制面。恢复策略不会猜测机器人仍在原位，也不会直接重放中断动作：
所有意外中断任务先进入 `waiting_for_human`，必须由操作者同时确认机器人状态和现场环境。

```text
POST /tasks
  → plan
  → validate
  → create_task（先写 tasks.db 和 task_id checkpoint）
  → execute
  → completed / failed / waiting_for_human
```

## 2. 两类持久化数据

| 数据库 | 内容 | 所有者 |
|---|---|---|
| `data/api_tasks.db` | Task、TaskStep、结果、失败历史、审计事件 | `SQLiteTaskRepository` |
| `data/checkpoints.db` | LangGraph thread 最新状态与历史 checkpoint | `AsyncSqliteSaver` |

任务的 `context.agent_thread_id` 将两个数据库关联。FastAPI 的 lifespan 在服务启动时创建并
迁移 checkpointer，在服务退出时等待后台任务取消并关闭 SQLite 连接。序列化启用
`LANGGRAPH_STRICT_MSGPACK=true`。

## 3. 重启恢复规则

启动时 `reconcile_interrupted_tasks()` 扫描残留的 `RUNNING` 任务：

1. 当前 `RUNNING` 步骤转换回 `PENDING`，保留尝试次数和中断错误。
2. 任务转换为 `WAITING_FOR_HUMAN`，记录 `process_interrupted` 与
   `human_help_requested` 事件。
3. 使用 `agent_thread_id` 把隔离状态同步回 LangGraph checkpoint。
4. 拒绝普通 `execute_task()`；只有恢复端点提供双确认后才重新执行该步骤。

恢复请求：

```json
{
  "robot_state_confirmed": true,
  "environment_confirmed": true
}
```

任意字段为 `false` 都返回 HTTP 409。操作者应实际确认定位、急停/底盘状态、周边人员、
障碍物以及目标环境后再提交，不能把这两个字段当作自动化绕过开关。

## 4. API

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/health` | 服务状态和本次启动隔离的任务数 |
| `POST` | `/tasks` | 异步提交自然语言任务，返回 `thread_id` |
| `GET` | `/tasks/{thread_id}` | 读取 Agent 状态、任务步骤和感知结论 |
| `POST` | `/tasks/{thread_id}/pause` | 安全取消当前动作并暂停 |
| `POST` | `/tasks/{thread_id}/cancel` | 取消当前和剩余步骤 |
| `POST` | `/tasks/{thread_id}/human-help` | 停止自主执行并请求人工接管 |
| `POST` | `/tasks/{thread_id}/resume` | 双确认后从人工接管状态恢复 |
| `GET` | `/tasks/{thread_id}/events` | 读取任务审计事件 |
| `GET` | `/tasks/{thread_id}/checkpoints` | 读取 newest-first checkpoint 历史 |

运行：

```powershell
uv sync --extra dev
uv run robot-agent-api
```

OpenAPI 页面位于 `http://127.0.0.1:8000/docs`。默认使用离线规则规划器；使用硅基流动：

```powershell
uv sync --extra dev --extra llm
$env:ROBOT_AGENT_PLANNER = "siliconflow"
uv run robot-agent-api
```

服务会从用户环境变量读取 `SILICONFLOW_API_KEY`，不会把密钥写入项目或数据库。

## 5. 实际测试

- Windows 全量测试：49 passed。
- 关闭并重新打开 `AsyncSqliteSaver` 后，thread 的完成状态、task ID、上下文和历史仍可读。
- 模拟数据库残留 `RUNNING`：新 MissionManager 自动隔离，当前步骤恢复为 `PENDING`。
- FastAPI 执行、事件、checkpoint 历史和跨 app 重开读取通过。
- FastAPI 执行中退出：新 app 报告 1 个已隔离任务并同步 `waiting_for_human` checkpoint。
- 人工接管与重启恢复均验证：缺少环境确认返回 409，双确认后任务完成。
- 重复提交同一个活跃 `thread_id` 返回 409。
- 真实启动 Uvicorn 并选择 SiliconFlow planner：在线生成实验室门口、会议室、起点三步计划，
  API 最终为 `completed`，持久化 9 条事件和 7 个 checkpoint；随后服务正常关闭。

## 6. 边界与安全

- 服务当前只支持一个 API 进程和一个机器人执行器，没有分布式锁；不要用多 worker 启动。
- Uvicorn 固定绑定 `127.0.0.1`，当前没有认证、TLS 和用户权限模型，不能直接暴露网络。
- SQLite 适合当前单机原型；多机器人或多进程阶段应引入具备事务锁和租约的任务协调层。
- `FakeRobotAdapter` API 验收不等同于真机安全验收。Nav2/相机真实仿真边界沿用 Phase 2/5 记录。
- 本阶段未把 Nav2 与 RGB Gazebo 两套启动流程强行合并；受控导航和真实相机感知分别已有
  实测闭环，统一世界与传感器启动仍需后续专门仿真加固。

实现采用 LangGraph 官方异步 SQLite saver 的生命周期模式，以及 FastAPI 官方推荐的
lifespan 共享资源模式：

- [LangGraph SQLite checkpoint README](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-sqlite/README.md)
- [FastAPI lifespan events](https://fastapi.tiangolo.com/advanced/events/)
