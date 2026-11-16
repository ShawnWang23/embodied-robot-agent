# FastAPI 接口参考

## 1. 启动

```powershell
# 离线规则规划器
uv run robot-agent-api

# SiliconFlow
$env:ROBOT_AGENT_PLANNER = "siliconflow"
uv run robot-agent-api
```

服务固定绑定 `http://127.0.0.1:8000`。Swagger UI 位于 `/docs`，机器可读规范见
`artifacts/phase8/openapi.json`。

环境变量：

| 名称 | 默认值 | 说明 |
|---|---|---|
| `ROBOT_AGENT_PLANNER` | `rule` | `rule`、`openai`、`siliconflow` |
| `ROBOT_AGENT_LOCATIONS` | `config/locations.json` | 语义地点目录 |
| `ROBOT_AGENT_TASK_DB` | `data/api_tasks.db` | 任务、步骤和事件 |
| `ROBOT_AGENT_CHECKPOINT_DB` | `data/checkpoints.db` | LangGraph checkpoint |

## 2. 端点

| 方法 | 路径 | 成功状态 | 作用 |
|---|---|---:|---|
| GET | `/health` | 200 | 健康状态与本次启动隔离任务数 |
| POST | `/tasks` | 202 | 异步提交自然语言任务 |
| GET | `/tasks/{thread_id}` | 200 | 查询 Agent、任务步骤和感知结论 |
| POST | `/tasks/{thread_id}/pause` | 200 | 取消当前动作并暂停 |
| POST | `/tasks/{thread_id}/cancel` | 200 | 取消任务 |
| POST | `/tasks/{thread_id}/human-help` | 200 | 请求人工接管 |
| POST | `/tasks/{thread_id}/resume` | 200 | 从暂停或人工接管状态恢复 |
| GET | `/tasks/{thread_id}/events` | 200 | 读取审计事件 |
| GET | `/tasks/{thread_id}/checkpoints` | 200 | 读取 newest-first checkpoint 历史 |

## 3. 请求示例

提交任务：

```powershell
$body = @{
  thread_id = "inspection-001"
  instruction = "去实验室门口检查是否有人，然后返回起点"
} | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/tasks `
  -Method Post -ContentType application/json -Body $body
```

请求人工接管：

```json
{"reason": "走廊出现临时障碍物"}
```

安全恢复：

```json
{
  "robot_state_confirmed": true,
  "environment_confirmed": true
}
```

对于 `waiting_for_human`，任意确认项为 `false` 都返回 409。两个字段表示操作者已经实际检查
定位、底盘/急停、周边人员和环境障碍，不应由自动脚本无条件填写。

## 4. 错误语义

- 404：thread 或 task 不存在。
- 409：状态转换非法、单机器人忙碌、确认条件不满足或重复活跃 thread。
- 422：请求体不符合 Pydantic schema。
- 500：未处理的服务端错误；应结合事件与服务日志排查。

## 5. 部署边界

当前 API 默认使用 `FakeRobotAdapter`。ROS2/Nav2 已通过独立 WSL 集成脚本验证，但尚未把
ROS adapter 作为 API 的运行时配置注入。服务没有认证、TLS、限流或分布式机器人租约，只能
在本机单进程、单 worker 使用，不能直接暴露到局域网或公网。

