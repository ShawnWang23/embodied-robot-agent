# Phase 7：测试和可靠性评估

记录日期：2026-11-10

## A. 本阶段完成了什么

Phase 7 已建立并实际运行标准测试集。核心交付物：

- `evaluation/models.py`：逐次执行记录、场景汇总与总指标的 Pydantic 模型。
- `evaluation/runner.py`：10 类标准场景，强制每类运行 3–5 次，总量始终为 30–50 次。
- `evaluation/report.py`：指标公式、聚合、JSONL/JSON/Markdown 输出和重新加载校验。
- `scripts/run_phase7_evaluation.py`：一次性执行命令，使用唯一 run ID，避免覆盖旧实验。
- `tests/test_evaluation.py`：30 次标准套件、指标分母和报告往返读取测试。
- `artifacts/phase7/20261110T133038290474Z/`：本阶段有效的 40 次原始实验与报告。

第一次正式运行在 40 次执行完成后遇到报告目录生命周期错误：`tasks.db` 已创建目录，旧报告器
却要求目录不存在，因此没有生成 JSONL。该次运行被明确标记为 incomplete，不纳入任何指标。
修复为“目录可以存在，但已有报告文件禁止覆盖”后，从头重新运行了完整 40 次。

## B. 系统架构

```text
Scenario fixture
  ├─ FakeRobotAdapter scripted result
  ├─ malformed planner
  ├─ persisted RUNNING task
  └─ human pause request
          ↓
现有 Agent / MissionManager / FSM / RecoveryPolicy / SQLite
          ↓
EvaluationRecord（每次运行一行 JSONL）
          ↓
EvaluationSummary + Markdown report
```

评估器没有复制 MissionManager 逻辑，而是通过生产代码的公共接口执行任务。这样测试到的是
实际状态转换、重试计数、事件和 SQLite 行为，而不是单独写的一套“看起来正确”的模拟逻辑。

## C. 关键设计与指标解释

### 标准场景

| 场景 | 预期终态 | 核心验证 |
|---|---|---|
| 正常巡检 | `completed` | 导航、拍照、检测、返回 |
| 临时障碍物 | `completed` | 明确备用观察点 |
| 导航失败 | `waiting_for_human` | 三次失败后停止自主执行 |
| 目标不存在 | `completed` | 阴性检测也能继续任务 |
| 视觉识别失败 | `completed` | 一次失败后有限重试成功 |
| LLM 输出错误 | `failed` | 进入工具层前拒绝 |
| 工具调用失败 | `completed` | 瞬态失败后重试成功 |
| 程序中断 | `completed` | 重启隔离、双确认、恢复 |
| 人工暂停 | `completed` | 当前动作取消后恢复 |
| 多地点长程任务 | `completed` | 九步骤顺序执行 |

Task Success Rate 不是测试通过率。导航失败场景正确进入 `waiting_for_human`，LLM 错误场景
正确进入 `failed`，因此它们会降低 Task Success Rate，但属于安全设计成功。为避免误读，报告
额外提供 Expectation Pass Rate。

指标定义：

- Task Success Rate = `completed` 运行数 / 全部运行数。
- Average Completion Time = 场景开始到终态的实测墙钟时间算术平均值。
- Recovery Success Rate = 故障注入后最终完成数 / 启动恢复策略的运行数。
- Tool Calling Success Rate = 成功步骤尝试数 / 全部步骤尝试数；失败重试和中断保留在分母。
- Human Intervention Rate = 暂停、请求人工或重启后要求确认的运行数 / 全部运行数。
- Precision = TP / (TP + FP)，Recall = TP / (TP + FN)。

## D. 运行方式

默认执行 10 场景 × 4 次：

```powershell
uv sync --extra dev --extra llm --extra perception
uv run python scripts/run_phase7_evaluation.py --repetitions 4
```

允许 `--repetitions 3`、`4` 或 `5`，分别生成 30、40 或 50 次记录。每次都会在
`artifacts/phase7/<UTC_RUN_ID>/` 新建：

- `records.jsonl`：每次执行的不可省略原始记录。
- `summary.json`：带指标定义、分子和分母的结构化汇总。
- `report.md`：便于阅读的报告。
- `tasks.db`：该次运行的任务和事件数据库（被 Git 忽略）。

回归命令：

```powershell
uv run pytest -q
wsl -d Ubuntu-24.04 -- bash -lc `
  'cd <WSL_PROJECT_PATH> && bash scripts/validate_agent_wsl.sh'
wsl -d Ubuntu-24.04 -- bash -lc `
  'cd <WSL_PROJECT_PATH> && bash scripts/validate_perception_wsl.sh'
```

## E. 实际测试结果

有效 run ID：`20261110T133038290474Z`

| 指标 | 实测结果 | 分子 / 分母 |
|---|---:|---:|
| Expectation Pass Rate | 100.00% | 40 / 40 |
| Task Success Rate | 80.00% | 32 / 40 |
| Average Completion Time | 0.146341 s | 40 次墙钟均值 |
| P95 Completion Time | 0.302976 s | 第 38 个有序样本 |
| Recovery Success Rate | 80.00% | 16 / 20 |
| Tool Calling Success Rate | 71.43% | 80 / 112 |
| Human Intervention Rate | 30.00% | 12 / 40 |
| Perception Precision | 93.75% | 15 / (15 + 1) |
| Perception Recall | 93.75% | 15 / (15 + 1) |

原始记录复核：40 行，0 个 expectation failure，0 个 evaluation error。

真实仿真回归没有混入上述 40 次分母：

- WSL ROS2/Nav2：自然语言两地点计划 `laboratory_door → start`，两个 Nav2 goal 均成功，
  每个步骤一次完成，`number_of_recoveries=0`。
- WSL ROS2 RGB：TurtleBot3 Waffle Pi 相机再次取得 640×480 BGR8 图像。
- YOLO26 CPU：空仿真画面没有 person/chair；官方阳性对照检出 4 个 person，最高置信度
  约 0.872；真实相机 → Agent 最终进入 `clear`。
- Windows 全量 pytest：52 passed；`uv pip check` 无依赖冲突。
- 仿真脚本退出后无 ROS2/Nav2/Gazebo 残留进程。

### 结果边界

40 次标准套件是 `FakeRobotAdapter` 的确定性软件级故障注入，不是 40 次 Gazebo 物理实验，
也不是真机安全测试。93.75% Precision/Recall 来自套件中明确注入的合成标注混淆矩阵，用于
验证指标计算与错误传播；它不是 YOLO 在真实数据集上的精度声明。现有两张真实图像只适合做
正/负 smoke control，不足以计算有统计意义的 YOLO Precision/Recall。

## F. 我的学习任务

本阶段最值得掌握的知识点：

1. 为什么“任务未完成”不一定等于“测试失败”，以及 Expectation Pass Rate 的作用。
2. 指标必须明确分子、分母和适用样本，不能只记录百分比。
3. 故障注入为什么要调用生产接口，而不是复制一套简化状态机。
4. JSONL 原始记录、聚合 JSON 和人类报告为什么应该分层保存。
5. 软件基准、Gazebo 仿真、真实数据集评测和真机安全测试之间的证据边界。

自测问题：

- 导航连续失败后进入 `waiting_for_human`，Task Success 与 Expectation Pass 各是多少？
- 为什么失败的第一次工具调用必须保留在 Tool Calling Success Rate 分母？
- 如果 TP=15、FP=1、FN=1，Precision 和 Recall 如何计算？
- 为什么两张图片不能支撑“YOLO Precision=某个百分比”的真实模型结论？
- 如何从 `records.jsonl` 独立复算 Recovery Success Rate？

## G. 下一阶段

Phase 8 已在用户确认后完成：代码、安装说明、接口文档、架构/工作流/FSM、ROS2 节点说明、
完整测试报告、OpenAPI 和演示视频均已整理。详见 `docs/final_delivery.md`。

