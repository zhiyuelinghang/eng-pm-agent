# 任务引擎 (task-engine)

通用任务引擎，以 **MCP Server** 形式交付。把一句自然语言需求转换成多级流转的任务流，支持定时与周期自动布置、节点流转、转办、逾期判定与完整留痕。

引擎与具体业务系统解耦——领域逻辑不依赖任何宿主产品，换一个工程或项目管理系统也能接入。

## 为什么需要它

多数项目管理系统能存任务、能改状态，但**「到点自动布置任务」这件事往往是缺失的**：界面上让用户配了「每周五执行」，提交时这个配置却被拼成一句人类可读的文本存进备注字段，没有任何调度器会读它。用户以为设好了定时，实际上永远不会触发。

这个引擎补的就是这一段，并顺带把流转、留痕、逾期判定一起做成产品无关的通用能力。

## 能力

| 能力 | 说明 |
|---|---|
| **责任制强约束** | 每项待办必须落到具体的人、具体的工点、具体的验收责任，缺一不可布置 |
| **自然语言生成** | 「每周五检查基坑监测数据」→ 结构化任务流 + 周期触发规则 |
| **定时/周期触发** | 到点自动布置任务，支持 时/天/周/月 间隔、次数上限、截止日期 |
| **多级流转** | 节点依次流转，完成、跳过、受阻、转办，全部留痕 |
| **主动逾期判定** | 不依赖任何人打开列表页，`tick` 时主动扫描标记 |
| **验收闭环** | 全节点完成 → 待验收 → 仅指定确认人可通过或退回 |
| **完整审计轨迹** | 每次状态变化都记入历史，可完整回溯 |
| **模型可选** | 未配模型时降级为规则解析，用户始终拿到可用结果 |

## 责任制：每项任务必须回答的六个问题

工程管理的提醒与待办不能只发给「安全员」「资料员」这类抽象角色——出了事追不到人，
任务也无从判断该谁办。引擎在模型层面强制了这一点：

| # | 问题 | 对应字段 | 强制程度 |
|---|---|---|---|
| 1 | 谁负责 | `Step.assignee`（具体人，非岗位） | 布置前必填 |
| 2 | 要做什么 | `Step.name` + `instruction` | 必填 |
| 3 | 截止时间 | `Step.due_at`，逾期主动标记 | 自动计算 |
| 4 | 关联哪个工点 | `Task.site` | 布置前必填 |
| 5 | 需要提交什么材料 | `Step.deliverable` + `requires_attachment` | 可强制留证 |
| 6 | 完成后由谁确认 | `Task.confirmer`，仅此人可验收 | 布置前必填 |

`Assignee` 不接受空标识——岗位到人的解析属于宿主系统的组织架构职责，必须在进入引擎
之前完成。模板阶段可以留空以便复用，但一旦要变成真实待办，三要素必须齐备：

```
以下节点尚未指定责任人，无法布置：第 2 个「派单整改」
任务未指定确认人，无法布置——完成后需要有人验收
任务未关联工点，无法布置
只有确认人 王工 可以验收该任务
```

## 快速开始

```bash
python3.13 -m venv .venv
.venv/bin/pip install -e .

# 生成任务流（无需配置模型）
task-engine generate "每周五检查基坑监测数据，异常时由监测员复核并归档"

# 查看内置模板
task-engine templates
```

### 端到端演示

```bash
export PYTHONPATH=src
P() { .venv/bin/python -m task_engine.cli --db demo.db "$@"; }

# 1. 生成任务流（自动识别「每周五」→ 周期触发）
P generate "每周五检查基坑监测数据，异常时由监测员复核，负责人确认后归档"
FLOW=$(P --json flows | python3 -c "import sys,json;print(json.load(sys.stdin)['flows'][0]['id'])")

# 2. 登记触发计划
P schedule "$FLOW" --at "2026-08-14 09:00" --mode recurring --every 1 --unit week

# 3. 推进引擎
P tick --now "2026-08-13 09:00"   # 未到点 → 触发 0 个任务
P tick --now "2026-08-14 09:00"   # 到点   → 触发 1 个任务
P tick --now "2026-08-14 09:00"   # 重复   → 触发 0 个（幂等）
P tick --now "2026-08-21 09:00"   # 下周   → 触发 1 个

# 4. 办理
TASK=$(P --json tasks | python3 -c "import sys,json;print(json.load(sys.stdin)['tasks'][0]['id'])")
P complete "$TASK" 0 --actor u1 --comment "已采集" --attach data.xlsx
P forward "$TASK" 1 u2 --name "李四"      # 转办
P accept "$TASK" --actor boss             # 验收
```

## 作为 MCP Server 接入

### Claude Code

```bash
claude mcp add task-engine -- python3 /path/to/task-engine/server.py
```

或写进 `.mcp.json`：

```json
{
  "mcpServers": {
    "task-engine": {
      "command": "python3",
      "args": ["/path/to/task-engine/server.py"],
      "env": {
        "TASK_ENGINE_DB": "/path/to/task_engine.db",
        "TASK_ENGINE_TZ": "Asia/Shanghai"
      }
    }
  }
}
```

接入后可直接用自然语言驱动：

> 「每周一给张三派一个现场巡检任务，抄送项目经理」
> 「我现在有哪些待办任务？」
> 「把第二个节点转给李四，他更熟悉现场」

### 驱动定时触发

引擎是**拉模式**——不常驻进程，由外部定期调用 `tick`。这让引擎可随时重启，触发时机对调用方完全透明。

```bash
# crontab：每 5 分钟推进一次
*/5 * * * * cd /path/to/task-engine && PYTHONPATH=src python3 -m task_engine.cli tick
```

`tick` 是幂等的，调用频率高于触发间隔也不会重复创建任务。

## 配置

全部通过环境变量，均为可选：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `TASK_ENGINE_DB` | `task_engine.db` | SQLite 数据库路径 |
| `TASK_ENGINE_TZ` | `Asia/Shanghai` | 时区 |
| `TASK_ENGINE_AI_KEY` | 空 | 模型 API Key，**留空则使用规则生成** |
| `TASK_ENGINE_AI_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容接口地址 |
| `TASK_ENGINE_AI_MODEL` | `gpt-4o-mini` | 模型名 |
| `TASK_ENGINE_AI_TIMEOUT` | `30` | 超时秒数 |

走 OpenAI 兼容接口，因此 OpenAI、通义、DeepSeek、本地 vLLM 都只需改 `BASE_URL` 与 `MODEL`。

**模型不可用绝不阻断用户**：未配 key、调用超时、返回脏数据，都会静默降级到规则生成，用户拿到的始终是一个可编辑的合理流程，只是 `origin` 字段会如实标明来源。

## MCP 工具

**生成** — `generate_task_flow`、`list_templates`、`create_flow_from_template`、`list_flows`
**布置与调度** — `dispatch_task`、`create_schedule`、`list_schedules`、`pause_schedule`、`cancel_schedule`、`tick`
**查询** — `list_tasks`、`get_task`
**办理** — `complete_step`、`forward_step`、`skip_step`、`block_step`、`unblock_step`、`add_note`
**闭环** — `accept_task`、`reject_task`、`cancel_task`

`list_tasks` 传 `assignee` 时返回「此人当前负责」的任务——即他所在节点正处于活跃状态的任务，这正是「我的任务」的语义。节点完成后任务会自动从上一个人的列表移到下一个人的列表。

## 内置模板

隐患整改、条件核查、资料补全、风险处置、报告审核、周期巡检、通用流程。

每个模板都包含**执行 → 复核 → 归档**三类环节，涉及现场作业的节点强制要求上传证明材料——工程场景的可追溯性要求任何处理都得有人复核、有材料留痕。

## 架构

```
src/task_engine/
├── domain/          # 纯领域逻辑，不依赖 MCP / DB / HTTP
│   ├── models.py    # TaskFlow / TaskInstance / Step / Trigger / Schedule
│   ├── trigger.py   # 触发时间计算（纯函数）
│   └── flow.py      # 状态机与节点推进
├── store/           # SQLite 持久化
├── generator/       # 模板 / 规则解析 / 模型生成
├── engine.py        # 服务门面：用例编排
├── tools.py         # MCP 工具实现
├── serialize.py     # 领域对象 → JSON
└── cli.py           # 命令行入口
server.py            # MCP stdio 入口
```

**分层铁律**：`domain/` 不 import 任何 MCP、SQLite、HTTP。这是「换个产品也能用」的前提——宿主差异全部收在外层。

### 两个关键设计

**触发时间锚定首次执行时刻，而非逐次迭代。** 1月31日按月重复，得到的是 2/28、3/31、4/30，而不是 2/28、3/28、4/28。逐次迭代会让日期逐月漂移，一年后偏出好几天。

**触发幂等由数据库主键保证。** `fire_log` 表以 `(schedule_id, fire_at)` 为主键，重复 `tick` 会撞主键冲突而非重复建任务。重复布置任务会直接骚扰到真实的人，这个不变量必须硬保证。

## 测试

```bash
.venv/bin/python -m pytest tests/ -q
```

覆盖领域逻辑、存储往返、调度幂等、生成降级，以及通过**真实子进程**驱动的 MCP 协议契约测试。

重点覆盖的边界：月末溢出（1/31 + 1月 = 2/28）、长时间停机后不补跑历史触发、模型编造人员被丢弃、规则解析扛住畸形输入。

## 状态模型

**任务状态**：`pending` → `running` → `review` → `done`，旁支 `blocked`（受阻）、`overdue`（逾期）、`cancelled`（取消）。

**节点状态**：`waiting` → `active` → `done`，旁支 `skipped`（跳过）、`blocked`（受阻）。

任务状态由节点状态推导，不各自独立维护——调用方推进节点，整体状态自动跟随。
