# 任务引擎（task-engine）

任务引擎负责结构化任务流、定时触发、节点流转、验收和审计，以 Python 库和 STDIO MCP
两种方式提供能力。Dobby 的接入边界见 [Dobby 接入指南](Dobby接入指南.md)。

## 核心概念与规则

| 概念 | 用途 |
|---|---|
| 任务流 `TaskFlow` | 可复用的流程模板，包含节点、触发规则与宿主上下文 |
| 触发计划 `Schedule` | 按规则创建任务实例，支持暂停、恢复和取消 |
| 任务实例 `TaskInstance` | 某次执行的流程快照；修改模板不会改写已派发任务 |
| 节点 `Step` | 顺序执行的办理环节，保留责任人、材料及操作记录 |

人工流程在布置或登记计划前，必须明确具体责任人、工点和确认人。岗位到人员的解析、
项目成员资格和文件访问权限由宿主平台校验；模板和待确认草稿可以保留缺项。
每个人工节点还应说明要做什么、截止时间和交付材料。

- 同一任务按节点顺序流转，不能跨越当前节点办理；已完成节点的责任归属不能改写。
- 要求留证的节点必须提交材料；退回重做时保留旧材料用于审计，但必须补交新材料。
- 验收与退回由指定确认人执行。引擎不负责登录鉴权，宿主必须传入真实操作人。
- `list_tasks(assignee=...)` 查询当前由该人员办理的任务；尚未轮到的节点不会提前成为待办。
- 已完成、已取消的任务不能继续流转；逾期任务仍可以办理。
- 自动节点用 `automated` 标记，具体动作保存在 `TaskFlow.scope["step_actions"]`，
  由宿主执行。纯自动流程按自动节点规则校验，不能套用人工流程的缺项判断。

任务状态为 `pending → running → review → done`，另有 `blocked`、`overdue`、
`cancelled`。节点状态为 `waiting → active → done`，另有 `skipped`、`blocked`。
状态转换以 [领域状态机](src/task_engine/domain/flow.py) 为准。

## 生成与模板

`generate_task_flow` 只接受 AI 生成结果。未配置模型、请求失败或结果不合法时明确报错，
不会静默改用规则模板。需要固定流程时，显式调用 `create_flow_from_template`。

内置模板包括隐患整改、条件核查、资料补全、风险处置、报告审核、周期巡检和通用流程。
模板定义集中在 [templates.py](src/task_engine/generator/templates.py)，无需在说明中另存副本。

Dobby 通过管理中心指定的任务助手调用已分配的任务引擎生成草稿。生成不等于发布：
用户补齐并确认草稿后，平台才布置任务或登记执行计划。

## 定时触发

引擎由外部调用 `tick` 推进：创建到期任务、扫描逾期任务。Dobby 已在后端
[服务生命周期](../../backend/app/main.py) 中运行循环，间隔由
`TASK_ENGINE_TICK_INTERVAL_SECONDS` 配置，无需另设 cron。

触发规则支持分钟、小时、天、周、月间隔，以及每日、工作日、指定星期和每月日期的
日历规则；可设截止日期和次数上限。具体参数见
[Trigger](src/task_engine/domain/models.py) 和 [触发计算](src/task_engine/domain/trigger.py)。

- 重复推进同一个触发点不会重复创建任务，数据库的 `(schedule_id, fire_at)` 约束保证幂等。
- 按月触发锚定原始日期，月末缩短后后续月份会恢复原日期。
- 停机恢复时只处理一个已到期触发点，再跳到未来，避免集中补发全部历史任务。
- 时间使用带时区的值，默认时区为 `Asia/Shanghai`；触发精度受宿主推进间隔影响。

## 存储与模型配置

Dobby 后端与平台 MCP 共用 PostgreSQL 的 `task_engine` schema。平台缺少 PostgreSQL
配置时直接报错，不回退 SQLite。`TASK_ENGINE_DB` 仅供独立运行或隔离测试使用。

| 配置 | 用途 |
|---|---|
| `TASK_ENGINE_DATABASE_URL` | 平台 MCP 的 PostgreSQL 连接；由受信能力注入，不写入发行包 |
| `TASK_ENGINE_SCHEMA` | 任务引擎 schema，默认 `task_engine` |
| `TASK_ENGINE_TZ` | 触发和任务时间的时区 |
| `TASK_ENGINE_AI_KEY` | MCP 内部生成器的模型密钥；缺少时 AI 生成报错 |
| `TASK_ENGINE_AI_BASE_URL` | MCP 内部生成器的 OpenAI 兼容接口地址 |
| `TASK_ENGINE_AI_MODEL` | MCP 内部生成器使用的模型标识 |
| `TASK_ENGINE_DB` | 独立运行或测试时显式提供的 SQLite 路径 |

任务助手的对话模型在管理端配置；MCP 内部生成器仍读取上述 `TASK_ENGINE_AI_*`
参数。两层配置的实际注入方式见 [接入指南](Dobby接入指南.md)，不能仅凭助手模型可用
就判断 MCP 生成器已经配置成功。

## MCP 工具

| 用途 | 工具 |
|---|---|
| 生成与模板 | `generate_task_flow`、`list_templates`、`create_flow_from_template`、`list_flows` |
| 布置与计划 | `dispatch_task`、`create_schedule`、`list_schedules`、`pause_schedule`、`cancel_schedule`、`tick` |
| 查询 | `list_tasks`、`get_task` |
| 办理 | `complete_step`、`forward_step`、`skip_step`、`block_step`、`unblock_step`、`add_note` |
| 闭环 | `accept_task`、`reject_task`、`cancel_task` |

完整参数以 [tools.json](tools.json) 为准。工具包提供的能力不等于任意智能体均可调用，
Dobby 任务助手的草稿生成权限由平台进一步限制。

## 构建与验证

以下命令在仓库根目录执行，使用项目内嵌 Python：

```powershell
.\python-3.13.14\python.exe scripts\build_task_engine_mcp_package.py
.\python-3.13.14\python.exe scripts\pytest_entry.py --prepend mcp-packages/task-engine/src -- mcp-packages/task-engine/tests -q
```

包的上传与升级遵循 [MCP 包上传与运行说明](../../docs/MCP包上传与运行说明.md)。
平台接入测试见 [test_task_engine_integration.py](../../backend/tests/test_task_engine_integration.py)，
草稿生成测试见 [test_task_assistant_generation.py](../../backend/tests/test_task_assistant_generation.py)。

领域模型、触发和状态机位于 `src/task_engine/domain/`；存储实现位于 `store/`；
模型生成与模板位于 `generator/`；`engine.py` 为服务入口，`tools.py` 与
`server.py` 提供 MCP 协议。宿主业务差异放在平台接入层，避免侵入领域模型。
