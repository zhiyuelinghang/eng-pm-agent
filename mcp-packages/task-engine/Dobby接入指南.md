# Dobby 任务引擎接入指南

本文件说明当前平台接入规则。引擎概念、状态、工具和构建入口见
[任务引擎 README](README.md)；接口参数和实现以链接的源码为准。

## 调用与职责

| 入口 | 当前调用方式 | 负责的事情 |
|---|---|---|
| 任务页面、任务办理接口 | 平台后端通过 Python 库调用引擎 | 校验登录、项目、人员、工点和材料，再执行布置与流转 |
| AI 草稿生成 | 平台指定任务助手调用已分配的 MCP | 整理需求，生成结构化草稿，缺项留空 |
| 定时执行 | 后端生命周期循环调用 `tick` | 到期创建任务、标记逾期，并驱动宿主自动动作 |
| 群消息与企业微信通知 | 宿主动作及通知适配器 | 校验目标范围、落库并投递，引擎保留执行状态和审计 |

引擎管理任务流、实例、触发计划和节点状态；平台管理用户、项目、WBS、权限、
资料和消息。项目关联写入 `scope`，人员与工点必须从当前项目解析。

## 存储与事务

[task_engine_gateway.py](../../backend/app/task_engine_gateway.py) 使用平台现有 PostgreSQL
连接和独立 `task_engine` schema。平台 MCP 通过 `dobby_task_engine_store` 能力获得
`TASK_ENGINE_DATABASE_URL` 和 `TASK_ENGINE_SCHEMA`，与后端使用同一份任务数据。

该专用能力只允许 `task-engine` 包申请。连接只存在于服务器进程环境，不进入模型上下文
或浏览器；它是受信本地程序的直接数据库访问，不具有普通数据库交互工具的逐表白名单隔离。
能力约束和环境注入见 [清单校验](../../AgentScope/agentscope/app/mcp_registry/_models.py)
与 [MCP 管理器](../../AgentScope/agentscope/app/mcp_registry/_manager.py)。

平台模式不使用 `TASK_ENGINE_DB`，也不允许缺少 PostgreSQL 时自动回退 SQLite。
独立 SQLite 实现只用于引擎独立运行和隔离测试，不能按单文件数据库方式备份平台任务。

需要与业务写入保持原子性时，使用接入层的 `transaction_engine(db, engine)` 参与当前
事务，不修改共享单例的连接。数据库结构变更由管理员审阅并人工执行
[数据库更新目录](../../数据库更新) 中对应 SQL；启动和请求处理不执行结构升级。

## 草稿生成与模型

管理员在平台设置中指定已启用、配置固定模型并分配任务引擎 MCP 的任务助手。
入口通过 [task_assistant_generation.py](../../backend/app/task_assistant_generation.py)
建立绑定当前用户和项目的会话；要求助手调用 `generate_task_flow`，使用 `save=false`
生成草稿，不布置任务、不登记计划。

平台核对真实工具调用与 AI 来源，同时校验人员、工点和生成会话绑定；不得把助手文字
直接当作已生成成功的任务流。工具名兼容裸名称和
`mcp__task-engine__generate_task_flow`，结果通过
[task_draft_adapter.py](../../backend/app/task_draft_adapter.py) 转成页面草稿。
用户补齐并确认草稿后，由平台发布流程执行。

任务助手对话模型由管理端维护；MCP 内部的 `FlowGenerator` 仍读取
`TASK_ENGINE_AI_KEY`、`TASK_ENGINE_AI_BASE_URL`、`TASK_ENGINE_AI_MODEL`。
当前 MCP 管理器优先注入同名环境变量，未提供时兼容读取宿主的
`AI_API_KEY`、`AI_BASE_URL`、`AI_MODEL`。这项兼容只描述现有 MCP 实现，
不代表平台后端另有一套绕过任务助手的生成入口。

生成器未配置、调用失败或结果不合法时明确报错，不能静默套模板或宣称完成。
显式模板创建使用独立的 `create_flow_from_template`。

## 人工办理与自动节点

- 人工任务布置前校验节点责任人、工点和确认人；岗位名称不能替代具体用户。
- 用户请求必须传真实登录用户作为 `actor`。引擎的空 `actor` 是系统调用语义，
  不能用于绕开用户操作权限。
- 节点必须按顺序办理；完成、跳过、受阻和解除受阻遵守节点责任人约束，验收与退回
  遵守确认人约束。
- 附件只是引擎保存的引用，平台负责文件归属、访问权限和有效性。退回后的
  `reopened` 节点需要新材料时，页面应提示并阻止复用旧材料。
- `automated` 节点的具体动作保存在 `scope["step_actions"]`。群消息动作由
  [task_action_gateway.py](../../backend/app/task_action_gateway.py) 执行；
  纯自动流程不要求虚构人工负责人和验收节点。

## 前端状态映射

转换集中在 [task_engine_gateway.py](../../backend/app/task_engine_gateway.py)，
不要在各个路由复制转换代码。任务 ID 是字符串，应完整传递。

| 引擎任务状态 | 平台 API 状态 |
|---|---|
| `pending` | `pending` |
| `running` | `processing` |
| `blocked` | `need_more_info` |
| `review` | `pending_confirm` |
| `done` | `completed` |
| `cancelled` | `cancelled` |
| `overdue` | `overdue` |

节点的 `waiting/active/done/skipped/blocked` 分别转换为
`pending/processing/completed/completed/blocked`，同时透传 `reopened` 等办理字段。
登记执行计划时可能尚未生成任务实例，页面应显示计划登记结果，不能假定立即出现待办。

## 调度、通知与排查

[main.py](../../backend/app/main.py) 在后端运行期间持续推进引擎，默认间隔由
[config.py](../../backend/app/config.py) 定义，配置项为
`TASK_ENGINE_TICK_INTERVAL_SECONDS`。不需要另设 cron 或在任务列表查询时扫描逾期。

任务触发、逾期等结果通过宿主通知队列投递；群消息自动动作和企业微信适配不能绕过
平台的项目、成员及目标频道校验。处理故障时检查：

- 生成失败：任务助手职责、模型、MCP 分配和 MCP 内部生成器配置。
- 无法布置或办理：缺少的责任要素、登录操作人、当前节点及新材料要求。
- 计划未触发：后端循环、计划是否暂停、`next_fire_at`、次数和截止日期。
- 数据不一致：后端和 MCP 的 PostgreSQL 地址与 schema，不检查 SQLite 文件路径。

验证入口保留在 [引擎测试](tests)、
[平台接入测试](../../backend/tests/test_task_engine_integration.py) 和
[任务助手 MCP 草稿测试](../../backend/tests/test_task_assistant_mcp_draft.py)。
验证结果以当前代码实际运行所得为准。
