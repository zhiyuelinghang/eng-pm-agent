# Dobby 接入指南

面向 Dobby 后端开发人员。所有代码可直接使用，接口签名与字段名已对照 `eng-pm-agent` 仓库实际代码逐一核对。

---

## 一、方案概要

**任务模块整体交给引擎。** Dobby 后端 `api.py:3342-3490` 的任务路由改成引擎的薄封装，`Task` / `TaskStatusHistory` 表不再写入（保留只读，供历史任务查询）。

**前端界面基本不动**——接口路径、请求体、响应结构全部保持现状，兼容层负责把引擎模型转成前端认识的形状。唯一需要新增的界面元素是**工点选择器**（见 §7.2）。

### 为什么是这个方案

Dobby 原有的任务实现有几处硬伤：

1. **定时触发从未落地** — 前端 `AiWorkPlatformView.vue:2200` 让用户配了 `run_mode` / `trigger_date` / `trigger_interval_*` / `cc`，提交时（`:2562`）却被压成一句话塞进 `trigger_reason`。`Task` 模型（`models.py:406-428`）里没有任何触发字段，全库也搜不到调度器。**用户配的"每周五执行"永远不会触发。**
2. **逾期判定是被动的** — 只在有人调 `list_tasks` 时顺带扫一遍，没人打开页面就永远不标记。
3. **节点流转没有顺序约束** — `update_task_step` 可以直接完成任意 `step_index`，等于"没整改先归档"。
4. **责任制不完整** — 节点的 `owner_user_id` 可以为空，任务照样能流转；`confirmer_user_id` 有字段但无语义，谁都能验收；工点信息散落在 `wbs_item_id` 里，没有强制。

引擎把这四点都解决了，且经过 249 项单元测试 + 147 项对抗性测试验证。

### 责任制：接入时最需要注意的变化

引擎强制每项待办能回答六个问题，其中三项在布置前是**硬约束**：

| # | 问题 | 引擎字段 | Dobby 对应 | 强制 |
|---|---|---|---|---|
| 1 | 谁负责 | `Step.assignee`（具体人） | `workflow_steps[].owner_user_id` | ✅ 布置前必填 |
| 2 | 要做什么 | `Step.name` / `instruction` | `workflow_steps[].name` | ✅ |
| 3 | 截止时间 | `Step.due_at` | `workflow_steps[].due_at` | 自动计算 |
| 4 | 关联哪个工点 | `Task.site` | `wbs_item_id` → WBS 条目 | ✅ 布置前必填 |
| 5 | 提交什么材料 | `Step.deliverable` + `requires_attachment` | `workflow_steps[].material` | 可强制留证 |
| 6 | 完成后由谁确认 | `Task.confirmer`（仅此人可验收） | `confirmer_user_id` | ✅ 布置前必填 |

**责任人不接受抽象角色。** `Assignee(ref="")` 会直接抛错——「安全员」「资料员」这类岗位到人的解析属于 Dobby 的组织架构职责，必须在调用引擎之前完成。

缺失时的错误信息是明确的，可直接透传给用户：

```
以下节点尚未指定责任人，无法布置：第 2 个「派单整改」
任务未指定确认人，无法布置——完成后需要有人验收
任务未关联工点，无法布置
只有确认人 王工 可以验收该任务
```

### 调用方式：后端用库，AI 侧用 MCP

```
                    ┌─→ FastAPI 路由 ──(库调用)──┐
用户点界面 ─────────┤                            ├─→ task_engine ─→ SQLite
                    │                            │
AI 对话 ─→ 智能体 ──┴─→ MCP server ──(库调用)────┘
```

`server.py` 内部也是 `from task_engine.engine import TaskEngine`——**同一个库，两层皮**，操作同一个数据库。

后端不走 MCP 的原因：MCP 的 stdio 是单管道一问一答，天然串行。Dobby 若开 4 个 uvicorn worker，要么各起一个子进程（4 份内存，没省事），要么所有请求排队（吞吐卡死）。而库调用是微秒级函数调用，引擎的 SQLite 是 WAL 模式，多进程并发已验证安全。

MCP 保留给 AI 侧——让模型自己决定调哪个工具，正是 MCP 的设计目的；那条路径上毫秒级开销和串行都无所谓。

> **唯一的坑**：两边必须配**同一个 `TASK_ENGINE_DB` 路径**，否则会变成两个互不相干的库。

---

## 二、前端契约（兼容层必须精确对齐）

这是接入的核心约束。前端只有一个转换点 `mapTask`（`stores/app.ts:360`），后端返回的 JSON 必须能被它正确消费。

```ts
// stores/app.ts:129 — 后端返回的形状
type ApiTask = {
  id: number; project_id: number; title: string
  task_type: 'risk_alert' | 'material_missing' | 'daily_confirm' | 'draft_review' | 'fill_platform'
  risk_level: 'critical' | 'high' | 'medium' | 'low'
  assignee_user_id?: number; confirmer_user_id?: number
  due_at?: string; wbs_item_id?: number; risk_source_id?: number
  trigger_reason?: string; required_materials: string[]
  workflow_steps?: Task['workflowSteps']
  status: string; created_at: string
}

// stores/app.ts:187 — 状态映射
const uiTaskStatus = (status: string) =>
  ({ completed: 'done', pending_confirm: 'waiting_confirm' }[status] ?? status)

// stores/app.ts:189 — id 转换
const id = (value?: number | string | null) => value == null ? '' : String(value)
```

**三个关键点：**

1. **`id` 用 `String(value)` 转换** — 引擎的 `task_a1b2c3d4` 字符串 id 能安全通过，前端 `Task.id` 本身就是 `string`。TypeScript 声明写的是 `number`，但运行时不校验，**无需改前端**。
2. **状态必须返回后端枚举** — 返回 `completed` / `pending_confirm`，前端会自行转成 `done` / `waiting_confirm`。若直接返回引擎的 `done` / `review`，前端映射表匹配不到会原样透出，导致状态显示异常。
3. **`workflow_steps` 的节点状态**只能是 `pending` / `processing` / `completed` / `blocked`。
4. **`workflow_steps[].reopened`** — 新增字段，标记该节点被退回重做。前端据此提示「需重新提交材料」，而非让用户点完成时才被拒绝。

### 状态映射表

| 引擎 | 返回给前端 | 前端显示 |
|---|---|---|
| `pending` | `pending` | 待处理 |
| `running` | `processing` | 进行中 |
| `blocked` | `need_more_info` | 待补充 |
| `review` | `pending_confirm` | 待确认 |
| `done` | `completed` | 已完成 |
| `cancelled` | `cancelled` | 已取消 |
| `overdue` | `overdue` | 已逾期 |

| 引擎节点 | 返回给前端 |
|---|---|
| `waiting` | `pending` |
| `active` | `processing` |
| `done` / `skipped` | `completed` |
| `blocked` | `blocked` |

---

## 三、安装与配置

### 3.1 安装

```bash
# 放进 Dobby 仓库
cp -r /Volumes/Media1/Code/Task mcp-packages/task-engine

# 后端安装为依赖
cd backend && pip install -e ../mcp-packages/task-engine
```

引擎只依赖 `httpx`（Dobby 已有），领域层与存储层纯标准库。要求 **Python ≥ 3.13**。

### 3.2 配置

`backend/app/config.py`：

```python
class Settings(BaseSettings):
    # ... 现有配置不变

    # 任务引擎
    task_engine_db: str = "data/task_engine.db"
    task_engine_tz: str = "Asia/Shanghai"
```

`.env`：

```bash
TASK_ENGINE_DB=data/task_engine.db
TASK_ENGINE_TZ=Asia/Shanghai
```

引擎的 AI 生成直接复用 Dobby 现有的 `ai_api_key` / `ai_base_url` / `ai_model`，不用另配。

---

## 四、兼容层

新建 `backend/app/task_engine_gateway.py`。这是整个接入的核心文件——所有引擎与 Dobby 之间的转换都收在这里，不散落到路由中。

```python
"""任务引擎接入层。

职责边界：
  引擎持有  —— 任务实体、节点流转、触发计划、审计轨迹
  Dobby 持有 —— 项目、人员、WBS、风险源

两者通过 TaskInstance.scope 关联。scope 在登记时写入，触发时原样带回，
引擎不解释其内容，因此换一个宿主系统也无需改引擎。

责任制：引擎要求每项待办能追到具体的人、具体的工点、具体的验收责任。
Dobby 的 WBS 条目在这里充当「工点」，project_member 充当「责任人」与「确认人」。
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from task_engine.domain.models import (
    Assignee, IntervalUnit, RunMode, Site, StepSpec, TaskFlow, TaskInstance, Trigger,
)
from task_engine.engine import TaskEngine
from task_engine.generator.llm import FlowGenerator, LLMConfig

from .config import get_settings
from .models import ProjectMember, User, WbsItem

# ── 枚举映射 ──────────────────────────────────────────────
# 前端 uiTaskStatus 只认后端枚举，所以这里必须转成 Dobby 的说法，
# 不能直接把引擎枚举透出去。

ENGINE_TO_DOBBY_STATE = {
    "pending": "pending",
    "running": "processing",
    "blocked": "need_more_info",
    "review": "pending_confirm",
    "done": "completed",
    "cancelled": "cancelled",
    "overdue": "overdue",
}

DOBBY_TO_ENGINE_STATE = {v: k for k, v in ENGINE_TO_DOBBY_STATE.items()}

ENGINE_TO_DOBBY_STEP = {
    "waiting": "pending",
    "active": "processing",
    "done": "completed",
    "skipped": "completed",
    "blocked": "blocked",
}

RISK_TO_PRIORITY = {
    "critical": "urgent", "high": "high", "medium": "normal", "low": "low",
}
PRIORITY_TO_RISK = {v: k for k, v in RISK_TO_PRIORITY.items()}


# ── 单例 ──────────────────────────────────────────────────

@lru_cache
def get_engine() -> TaskEngine:
    """全局单例。SQLite 连接跨请求复用，WAL 模式支持并发。"""
    settings = get_settings()
    return TaskEngine(settings.task_engine_db, timezone=settings.task_engine_tz)


@lru_cache
def get_generator() -> FlowGenerator:
    """复用 Dobby 已有的模型配置。"""
    settings = get_settings()
    return FlowGenerator(LLMConfig(
        api_key=settings.ai_api_key,
        base_url=settings.ai_base_url,
        model=settings.ai_model,
    ))


def engine_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().task_engine_tz)


# ── 责任制解析：把 Dobby 的 id 换成引擎要的具体人与工点 ────

def resolve_person(db: Session, user_id: int | str | None, project_id: int) -> Assignee | None:
    """把用户 id 解析成具体的人。

    引擎不接受抽象角色——这里必须查出真名。查不到就返回 None，
    让上层的责任制校验去报错，而不是塞一个假名字蒙混过关。
    """
    if not user_id:
        return None
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None

    row = db.execute(
        select(User)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project_id, User.id == uid)
    ).scalar_one_or_none()

    if row is None:
        return None
    return Assignee(ref=str(uid), display_name=row.real_name or f"用户{uid}")


def resolve_site(db: Session, wbs_item_id: int | str | None) -> Site | None:
    """把 WBS 条目解析成工点。

    Dobby 的 WBS 条目天然就是「工点/部位」——它有编号（wbs_code）、
    名称和层级，正好对应引擎的 Site。
    """
    if not wbs_item_id:
        return None
    try:
        wid = int(wbs_item_id)
    except (TypeError, ValueError):
        return None

    item = db.get(WbsItem, wid)
    if item is None:
        return None
    return Site(ref=str(wid), name=item.name, code=item.wbs_code or "")


def member_names(db: Session, project_id: int) -> dict[str, str]:
    """{user_id: 姓名}，用于批量补全显示名。"""
    rows = db.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
    ).all()
    return {str(m.user_id): u.real_name for m, u in rows}


# ── 引擎 → 前端 ───────────────────────────────────────────

def to_api_task(task: TaskInstance) -> dict[str, Any]:
    """转成前端 mapTask 能消费的形状。

    字段名与 stores/app.ts:129 的 ApiTask 逐一对应，多一个少一个都可能出问题。
    """
    scope = task.scope or {}
    current = task.current_step

    return {
        "id": task.id,                              # 字符串 id，前端 String() 后正常
        "project_id": scope.get("project_id"),
        "title": task.title,
        "task_type": scope.get("task_type", "risk_alert"),
        "risk_level": PRIORITY_TO_RISK.get(task.priority, "medium"),
        # 前端用 responsibleId 显示"当前该谁办"，所以给当前节点责任人而非发起人
        "assignee_user_id": _to_int(current.assignee.ref) if current and current.assignee else None,
        # 确认人现在是引擎的一等字段，不再从 scope 里取
        "confirmer_user_id": _to_int(task.confirmer.ref) if task.confirmer else None,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        # 工点即 WBS 条目，前端用 linkedWbsIds 展示
        "wbs_item_id": _to_int(task.site.ref) if task.site else None,
        "risk_source_id": scope.get("risk_source_id"),
        "trigger_reason": task.trigger_note,
        # 前端用它算 missingCount
        "required_materials": [s.deliverable for s in task.steps if s.deliverable],
        "workflow_steps": [to_api_step(s, task) for s in task.steps],
        "status": ENGINE_TO_DOBBY_STATE.get(str(task.state), "pending"),
        "created_at": task.created_at.isoformat() if task.created_at else "",
    }


def to_api_step(step, task: TaskInstance) -> dict[str, Any]:
    """转成前端 workflowSteps 元素。

    order / next_step 是 1-based，与前端展示一致；引擎的 seq 是 0-based。
    reopened 是退回重做的标记——前端据此提示"需重新提交材料"，
    避免用户点完成时才被引擎拒绝。
    """
    return {
        "name": step.name,
        "owner": step.assignee.display_name if step.assignee else "",
        "owner_user_id": step.assignee.ref if step.assignee else None,
        "due_at": step.due_at.strftime("%Y-%m-%d") if step.due_at else None,
        "order": step.seq + 1,
        "next_step": step.seq + 2 if step.seq + 1 < len(task.steps) else None,
        "status": ENGINE_TO_DOBBY_STEP.get(str(step.state), "pending"),
        "note": step.comment,
        "material": step.deliverable,
        # 被退回重做——前端应提示该节点需重新提交材料
        "reopened": step.reopened,
    }


def to_api_history(task: TaskInstance) -> list[dict[str, Any]]:
    """转成 get_task 返回的 history 数组。

    对应原 TaskStatusHistory 的形状，前端任务历史时间线直接可用。
    """
    return [
        {
            "id": act.id,
            "task_id": task.id,
            "from_status": act.detail.get("from"),
            "to_status": act.detail.get("to"),
            "note": act.summary,
            "changed_by": _to_int(act.actor),
            "created_at": act.at.isoformat() if act.at else "",
        }
        for act in task.activities
    ]


# ── 前端 → 引擎 ───────────────────────────────────────────

def build_flow(db: Session, project_id: int, payload) -> TaskFlow:
    """把前端提交的任务表单转成引擎的任务流定义。

    责任制三要素（责任人 / 工点 / 确认人）在这里被解析成引擎认识的对象。
    解析不出来时留空，由引擎的 require_dispatchable() 统一报错——
    这样错误信息集中在一处，措辞也一致。
    """
    names = member_names(db, project_id)

    return TaskFlow(
        title=payload.title,
        steps=build_steps(payload.workflow_steps, names),
        summary=payload.trigger_reason or "",
        category=payload.task_type,
        priority=RISK_TO_PRIORITY.get(payload.risk_level, "normal"),
        trigger=build_trigger(payload),
        site=resolve_site(db, payload.wbs_item_id),
        confirmer=resolve_person(db, payload.confirmer_user_id, project_id),
        watchers=parse_cc(payload.cc),
        scope={
            "project_id": project_id,
            "task_type": payload.task_type,
            "risk_source_id": payload.risk_source_id,
        },
    )


def build_steps(workflow_steps: list[dict], names: dict[str, str]) -> tuple[StepSpec, ...]:
    """Dobby 的 workflow_steps → 引擎的 StepSpec。

    关键转换：Dobby 用绝对日期 due_at，引擎用相对天数 due_offset_days。
    因为同一个流程会被反复触发——8/14 那次和 8/21 那次的截止日必须不同，
    绝对日期在模板层面没有意义。这里按相邻节点的日期差还原出工期。
    """
    specs: list[StepSpec] = []
    previous_date: datetime | None = None

    for index, step in enumerate(workflow_steps or []):
        owner_id = str(step.get("owner_user_id") or "").strip()
        offset = 1
        raw_due = step.get("due_at")
        if raw_due:
            try:
                current = datetime.strptime(raw_due[:10], "%Y-%m-%d")
                if previous_date:
                    offset = max(1, (current - previous_date).days)
                previous_date = current
            except ValueError:
                pass

        material = (step.get("material") or "").strip()
        specs.append(StepSpec(
            name=(step.get("name") or f"节点 {index + 1}").strip(),
            # owner_id 为空时留 None，让引擎统一报"尚未指定责任人"
            assignee=Assignee(
                ref=owner_id,
                display_name=step.get("owner") or names.get(owner_id, ""),
            ) if owner_id else None,
            due_offset_days=offset,
            deliverable=material,
            # 有交付物要求的节点强制留痕——工程场景的可追溯性要求
            requires_attachment=bool(material),
        ))

    return tuple(specs) or (StepSpec(name="执行任务"),)


def build_trigger(payload) -> Trigger:
    """前端的触发配置 → 引擎的 Trigger。

    前端把日期与时间拆成两个字段（trigger_date + trigger_time），这里合并。
    """
    tz = engine_tz()
    raw_date = payload.trigger_date or datetime.now(tz).strftime("%Y-%m-%d")
    raw_time = payload.trigger_time or "09:00"

    try:
        first_at = datetime.strptime(f"{raw_date} {raw_time}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    except ValueError:
        first_at = datetime.now(tz)

    if payload.run_mode == "scheduled":
        return Trigger(
            run_mode=RunMode.RECURRING,
            first_at=first_at,
            interval_value=max(1, payload.trigger_interval_value or 1),
            interval_unit=IntervalUnit(payload.trigger_interval_unit or "week"),
            timezone=str(tz),
        )
    return Trigger(run_mode=RunMode.ONCE, first_at=first_at, timezone=str(tz))


def parse_cc(cc: str | None) -> tuple[Assignee, ...]:
    """抄送人：前端传的是逗号分隔的姓名字符串，中英文逗号都要认。

    抄送人不参与流转，只是知会，所以用姓名本身作 ref 即可，
    不必强求解析到用户 id。
    """
    if not cc:
        return ()
    return tuple(
        Assignee(ref=name.strip(), display_name=name.strip())
        for name in cc.replace("，", ",").split(",") if name.strip()
    )


def _to_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
```

---

## 五、改写路由

`backend/app/api.py` 的 8 个任务路由逐一改写。**路径、请求体、响应结构全部不变。**

### 5.1 请求体扩展

`schemas.py` 的 `TaskInput` 增加触发字段（前端早就在收集，只是之前没地方接）：

```python
from typing import Literal

class TaskInput(BaseModel):
    # ── 现有字段不变 ──
    title: str
    task_type: str
    risk_level: str = "low"
    assignee_user_id: int | None = None
    confirmer_user_id: int | None = None
    due_at: str | None = None
    wbs_item_id: int | None = None
    risk_source_id: int | None = None
    trigger_reason: str | None = None
    required_materials: list[str] = Field(default_factory=list)
    workflow_steps: list[dict[str, Any]] = Field(default_factory=list)

    # ── 新增：触发配置 ──
    run_mode: Literal["single", "scheduled"] = "single"
    trigger_date: str | None = None                    # YYYY-MM-DD
    trigger_time: str = "09:00"                        # HH:MM
    trigger_interval_value: int = 1
    trigger_interval_unit: Literal["hour", "day", "week", "month"] = "week"
    cc: str | None = None                              # 逗号分隔的姓名
```

### 5.2 创建任务

```python
from task_engine.domain.flow import TransitionError

from .task_engine_gateway import build_flow, get_engine, to_api_task


@router.post("/projects/{project_id}/tasks")
def create_task(
    project_id: int,
    payload: TaskInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """创建任务。

    single —— 立即布置，任务马上出现在责任人的待办里
    scheduled —— 登记触发计划，到点由 tick 自动布置

    两种情况都会校验责任制三要素（每个节点的责任人、工点、确认人），
    缺失时返回 422 并说明缺什么。
    """
    project_or_404(db, project_id)
    engine = get_engine()
    flow = build_flow(db, project_id, payload)

    if payload.run_mode == "scheduled":
        try:
            # 提前校验：定时任务到点自动布置，若那时才发现缺责任人，
            # 失败会静默发生在后台 tick 里，没人看得到
            flow.require_dispatchable()
            plan = engine.schedule(flow)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        audit(db, user, "登记定时任务",
              f"任务流「{flow.title}」：{flow.trigger.describe()}",
              project_id, "task_schedule", 0)
        db.commit()
        return ok({
            "schedule_id": plan.id,
            "flow_id": flow.id,
            "title": flow.title,
            "trigger_description": flow.trigger.describe(),
            "next_fire_at": plan.next_fire_at.isoformat() if plan.next_fire_at else None,
        }, f"定时任务已登记：{flow.trigger.describe()}")

    try:
        task = engine.dispatch(
            flow, actor=str(user.id), trigger_note=payload.trigger_reason or "手动布置",
        )
    except ValueError as exc:
        # 责任制校验失败——消息已是给人看的中文，直接透传
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    audit(db, user, "创建任务", f"创建任务「{task.title}」", project_id, "task", 0)
    db.commit()
    return ok(to_api_task(task), "任务已创建")
```

**责任制校验失败时前端会收到 422**，`detail` 是可直接展示的中文：

```
以下节点尚未指定责任人，无法布置：第 2 个「派单整改」
任务未指定确认人，无法布置——完成后需要有人验收
任务未关联工点，无法布置
```

前端 `createManualTask` 已有 `error.response?.data?.detail` 的处理（`:2570`），无需改动即可正确显示。

> **注意**：`scheduled` 返回的是计划信息而非任务——因为此刻还没有任务。前端 `createManualTask` 成功后会跳到"我的任务"页，届时列表里看不到新任务是正常的，建议在前端提示语里区分（见 §7）。

### 5.3 任务列表

```python
@router.get("/projects/{project_id}/tasks")
def list_tasks(
    project_id: int,
    status_filter: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    """任务列表。

    与原实现的区别：逾期判定不再依赖这个接口顺带扫描——引擎的 tick 会主动标记，
    没人打开页面也照样生效。这里只负责读。
    """
    project_or_404(db, project_id)
    engine = get_engine()

    state = DOBBY_TO_ENGINE_STATE.get(status_filter) if status_filter else None
    tasks = engine.list_tasks(state=state, limit=200)
    tasks = [t for t in tasks if t.scope.get("project_id") == project_id]

    return ok([to_api_task(t) for t in tasks])
```

### 5.4 任务详情

```python
@router.get("/tasks/{task_id}")
def get_task(
    task_id: str,                       # 由 int 改为 str —— 引擎 id 是 task_xxx
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    engine = get_engine()
    task = engine.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    data = to_api_task(task)
    data["history"] = to_api_history(task)
    return ok(data)
```

### 5.5 状态流转

```python
@router.post("/tasks/{task_id}/transition")
def transition_task(
    task_id: str,
    payload: TaskTransitionInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """状态流转。

    引擎的状态由节点推导，不能随意设置——只有验收/退回/取消是真正的"状态操作"。
    其余状态变化应通过 complete_step 等节点操作自然发生。

    验收与退回会校验操作人是否为任务指定的确认人（actor 传当前登录用户 id）。
    """
    engine = get_engine()
    target = DOBBY_TO_ENGINE_STATE.get(payload.status, payload.status)

    try:
        if target == "done":
            task = engine.accept(task_id, actor=str(user.id), note=payload.note or "")
        elif target == "cancelled":
            task = engine.cancel_task(task_id, actor=str(user.id), reason=payload.note or "")
        elif target == "running":
            task = engine.reject(task_id, actor=str(user.id), reason=payload.note or "")
        else:
            raise HTTPException(
                status_code=422,
                detail=f"状态 {payload.status} 不能直接设置，请通过节点操作推进",
            )
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在") from None
    except TransitionError as exc:
        # 含"只有确认人 X 可以验收该任务"，消息已是给人看的中文，直接透传
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    audit(db, user, "任务状态流转", f"任务「{task.title}」变更为 {task.state}",
          task.scope.get("project_id"), "task", 0)
    db.commit()
    return ok(to_api_task(task), "任务状态已更新")
```

> **注意**：`actor` 必须传真实的登录用户 id。引擎不做身份认证——它无法验证 `actor` 的真实性，那是 Dobby 的职责。若传空字符串，引擎会视为系统调用并放行验收。

### 5.6 节点操作

```python
@router.post("/tasks/{task_id}/steps/{step_index}")
def update_task_step(
    task_id: str,
    step_index: int,
    payload: TaskStepUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """更新节点状态。

    与原实现的关键区别：引擎强制按顺序办理。前序节点未完成时提交靠后的节点会被
    拒绝，错误信息会指明当前该办哪个——这保证了"先整改后归档"不被绕过。
    """
    engine = get_engine()

    try:
        if payload.status == "completed":
            task = engine.complete_step(
                task_id, step_index,
                actor=str(user.id),
                comment=payload.note or "",
                attachments=getattr(payload, "attachments", None) or [],
            )
        elif payload.status == "blocked":
            task = engine.block_step(
                task_id, step_index, actor=str(user.id), reason=payload.note or "",
            )
        elif payload.status == "processing":
            task = engine.unblock_step(
                task_id, step_index, actor=str(user.id), note=payload.note or "",
            )
        else:
            raise HTTPException(status_code=422, detail=f"不支持的步骤状态：{payload.status}")
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在") from None
    except TransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    audit(db, user, "更新任务步骤", f"任务「{task.title}」步骤 {step_index + 1} → {payload.status}",
          task.scope.get("project_id"), "task", 0)
    db.commit()
    return ok(to_api_task(task), "任务步骤已更新")
```

`TaskStepUpdate` 建议加上附件字段：

```python
class TaskStepUpdate(BaseModel):
    status: str = "completed"
    note: str | None = None
    attachments: list[str] = Field(default_factory=list)   # 新增
```

### 5.7 转办

```python
@router.post("/tasks/{task_id}/reassign")
def reassign_task(
    task_id: str,
    payload: TaskReassignInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """转办当前节点。

    引擎的语义：可转办当前节点（本人干不了，换人接手）与未来节点（提前排班），
    但已完成的节点不可改派——历史责任归属是审计轨迹的基础。
    """
    engine = get_engine()
    task = engine.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    project_id = task.scope.get("project_id")
    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == payload.assignee_user_id,
        )
    )
    if not member:
        raise HTTPException(status_code=422, detail="转交人不属于当前项目")

    current = task.current_step
    if current is None:
        raise HTTPException(status_code=409, detail="任务没有待办节点")

    target_user = db.get(User, payload.assignee_user_id)
    try:
        task = engine.forward_step(
            task_id, current.seq,
            to=Assignee(
                ref=str(payload.assignee_user_id),
                display_name=target_user.real_name if target_user else "",
            ),
            actor=str(user.id),
            note=payload.note or "",
        )
    except TransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    audit(db, user, "转交任务", f"任务「{task.title}」转交给用户 {payload.assignee_user_id}",
          project_id, "task", 0)
    db.commit()
    return ok(to_api_task(task), "任务已转交")
```

### 5.8 处理说明

```python
@router.post("/tasks/{task_id}/notes")
def add_task_note(
    task_id: str,
    payload: TaskNoteInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    engine = get_engine()
    try:
        task = engine.add_note(task_id, note=payload.note, actor=str(user.id))
    except KeyError:
        raise HTTPException(status_code=404, detail="任务不存在") from None
    except TransitionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    audit(db, user, "记录任务处置", f"任务「{task.title}」新增处理说明",
          task.scope.get("project_id"), "task", 0)
    db.commit()
    return ok({"task_id": task.id}, "任务处理说明已记录")
```

### 5.9 AI 生成任务流

```python
@router.post("/projects/{project_id}/tasks/generate-flow")
def generate_task_flow(
    project_id: int,
    payload: TaskFlowGenerateInput,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    """自然语言 → 任务流。

    返回结构与前端 GeneratedTaskFlow（AiWorkPlatformView.vue:1036）完全一致，
    前端 applyGeneratedTaskFlow 直接可用。

    引擎的 generate 永不抛错：模型不可用时自动降级为规则解析，
    返回的 generated_by 字段会如实标明来源。
    """
    project = project_or_404(db, project_id)
    engine, generator = get_engine(), get_generator()

    rows = db.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
    ).all()
    assignees = [Assignee(ref=str(m.user_id), display_name=u.real_name) for m, u in rows]

    wbs = db.scalars(select(WbsItem).where(WbsItem.project_id == project_id)).all()
    risks = db.scalars(
        select(RiskSource).where(
            RiskSource.project_id == project_id, RiskSource.status == "active",
        )
    ).all()

    flow = generator.generate(
        payload.requirement,
        now=engine.now(),
        assignees=assignees,
        # 生成阶段工点与确认人通常还没定，留空由用户在界面上选
        context={
            "project": {"id": project.id, "name": project.project_name},
            "wbs_items": [{"id": w.id, "code": w.wbs_code, "name": w.name} for w in wbs],
            "risk_sources": [{"id": r.id, "name": r.name, "level": r.level} for r in risks],
        },
    )

    trigger = flow.trigger
    first_at = trigger.first_at or engine.now()
    return ok({
        "title": flow.title,
        "task_type": flow.category if flow.category in {
            "risk_alert", "material_missing", "daily_confirm", "draft_review", "fill_platform",
        } else "risk_alert",
        "risk_level": PRIORITY_TO_RISK.get(flow.priority, "medium"),
        "assignee_user_id": _to_int(flow.steps[0].assignee.ref) if flow.steps[0].assignee else None,
        "confirmer_user_id": None,
        "wbs_item_id": None,
        "risk_source_id": None,
        "run_mode": "scheduled" if trigger.is_recurring else "single",
        "trigger_date": first_at.strftime("%Y-%m-%d"),
        "trigger_time": first_at.strftime("%H:%M"),
        "trigger_rule": trigger.describe(),
        "trigger_interval_value": trigger.interval_value,
        "trigger_interval_unit": str(trigger.interval_unit),
        "cc": "，".join(w.display_name for w in flow.watchers),
        "steps": [
            {
                "name": s.name,
                "owner_user_id": _to_int(s.assignee.ref) if s.assignee else None,
                "due_at": None,          # 前端按 due_offset_days 自行计算
                "material": s.deliverable,
            }
            for s in flow.steps
        ],
        "generated_by": "ai" if flow.origin == "ai" else "rules",
        "generation_note": flow.origin_note,
    }, "任务流已生成")
```

---

## 六、责任制带来的新查询能力

工点与确认人成为一等字段后，多了两个原来做不到的查询。两者都建了索引，不需要全表扫描。

```python
@router.get("/projects/{project_id}/tasks/pending-my-review")
def pending_my_review(
    project_id: int,
    engine: TaskEngine = Depends(get_engine),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """待我验收——我是确认人，且任务已全部完成。

    这是原实现没有的能力：以前 confirmer_user_id 只是个字段，没有语义，
    没人能据此查出「哪些任务在等我点头」。
    """
    tasks = engine.list_tasks(confirmer=str(user.id), state="review", limit=50)
    tasks = [t for t in tasks if t.scope.get("project_id") == project_id]
    return ok([to_api_task(t) for t in tasks])


@router.get("/projects/{project_id}/wbs/{wbs_item_id}/tasks")
def tasks_by_site(
    project_id: int,
    wbs_item_id: int,
    open_only: bool = True,
    engine: TaskEngine = Depends(get_engine),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    """某个工点上的任务——「3号楼地下室还有哪些活没完」。"""
    tasks = engine.list_tasks(site=str(wbs_item_id), open_only=open_only, limit=100)
    tasks = [t for t in tasks if t.scope.get("project_id") == project_id]
    return ok([to_api_task(t) for t in tasks])
```

建议在 WBS 详情页挂上第二个接口——工点与任务的关联从此是双向可查的。

---

## 七、驱动定时触发

引擎是拉模式，需要外部定期调用 `tick`。**推荐挂在 FastAPI 的 lifespan 里**：

```python
# backend/app/main.py
import asyncio
import contextlib
import logging

from .task_engine_gateway import get_engine

logger = logging.getLogger(__name__)
TICK_INTERVAL_SECONDS = 300


async def _tick_loop() -> None:
    """每 5 分钟推进一次引擎：触发到期计划 + 扫描逾期。

    tick 是幂等的（同一计划的同一触发时刻只创建一次任务，由数据库主键保证），
    所以异常只需记录，下一轮自然重试，不必补偿。
    """
    engine = get_engine()
    while True:
        try:
            # tick 是同步的 SQLite 操作，放线程池避免阻塞事件循环
            report = await asyncio.to_thread(engine.tick)
            if report.created_count or report.overdue_task_ids:
                logger.info("任务引擎：%s", report.describe())
            for failure in (f for f in report.fired if not f.ok):
                logger.warning("触发失败 %s：%s", failure.schedule_id, failure.error)
        except Exception:
            logger.exception("任务引擎 tick 失败")
        await asyncio.sleep(TICK_INTERVAL_SECONDS)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # ... 现有启动逻辑

    tick_task = asyncio.create_task(_tick_loop())
    yield
    tick_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await tick_task
```

**多 worker 部署时无需额外处理** —— 每个 worker 都跑 tick 也不会重复创建任务，幂等由 `fire_log` 表的 `(schedule_id, fire_at)` 主键在数据库层保证（已验证 4 进程并发只创建 1 个任务）。

**tick 频率的含义**：触发精度受此限制。5 分钟一次意味着"9:00 触发"实际发生在 9:00~9:05 之间，工程场景足够。tick 本身开销很小（200 任务的库单次 < 10ms），需要分钟级精度就调到 60 秒。

---

## 八、前端改动

三处：一处透传字段，一处新增选择器，一处提示语。

### 8.1 必改：透传触发字段

`AiWorkPlatformView.vue:2557` 的 `createManualTask`：

```ts
await store.createTask({
  title: form.title,
  task_type: form.task_type,
  risk_level: 'medium',
  assignee_user_id: taskFlowSteps.value[0]?.owner_user_id,
  due_at: taskFlowSteps.value[taskFlowSteps.value.length - 1]?.due_at,
  trigger_reason: triggerParts.join(' · '),
  required_materials: requiredMaterials,
  workflow_steps,
  // ↓ 新增：把用户已经填好的触发配置真正传给后端
  run_mode: form.run_mode,
  trigger_date: form.trigger_date,
  trigger_time: form.trigger_time,
  trigger_interval_value: form.trigger_interval_value,
  trigger_interval_unit: form.trigger_interval_unit,
  cc: form.cc,
  // ↓ 新增：责任制要求的工点与确认人
  wbs_item_id: form.wbs_item_id,
  confirmer_user_id: form.confirmer_user_id,
})
```

`stores/app.ts:489` 的 `createTask` payload 类型同步扩展：

```ts
async function createTask(payload: {
  title: string
  task_type: Task['type']
  risk_level?: Task['riskLevel']
  assignee_user_id?: string
  confirmer_user_id?: string
  due_at?: string
  risk_source_id?: string
  wbs_item_id?: string
  trigger_reason?: string
  required_materials?: string[]
  workflow_steps?: Task['workflowSteps']
  // 新增
  run_mode?: 'single' | 'scheduled'
  trigger_date?: string
  trigger_time?: string
  trigger_interval_value?: number
  trigger_interval_unit?: 'hour' | 'day' | 'week' | 'month'
  cc?: string
}) { /* 函数体不变 */ }
```

`confirmer_user_id` 与 `wbs_item_id` 本来就在类型里，只是之前没有界面元素去填。

### 8.2 必改：新增工点与确认人选择器

**这是唯一需要动界面的地方。** 当前任务流编辑器（`task-flow-global-settings`，`:667`）只有触发方式、间隔、抄送三项，没有工点与确认人的入口——但引擎现在要求这两项必填。

在 `task-flow-trigger-grid`（`:672`）里补两个字段：

```vue
<div class="task-flow-trigger-grid">
  <!-- 现有：执行方式、执行时间、触发间隔、抄送人 -->

  <!-- 新增：工点 -->
  <label class="form-field">
    关联工点
    <select v-model="taskCreateForm.wbs_item_id" required>
      <option value="">请选择工点</option>
      <option v-for="item in store.wbsItems" :key="item.id" :value="item.id">
        {{ item.code }} {{ item.name }}
      </option>
    </select>
  </label>

  <!-- 新增：确认人 -->
  <label class="form-field">
    确认人
    <select v-model="taskCreateForm.confirmer_user_id" required>
      <option value="">请选择确认人</option>
      <option v-for="member in store.members" :key="member.id" :value="member.id">
        {{ member.name }} · {{ member.title }}
      </option>
    </select>
  </label>
</div>
```

`taskCreateForm`（`:2200`）加上这两个字段：

```ts
const taskCreateForm = ref({
  title: taskTemplateTopic.value,
  task_type: 'risk_alert' as Task['type'],
  run_mode: 'single' as 'single' | 'scheduled',
  trigger_date: todayDateString(),
  trigger_time: '09:00',
  trigger_interval_value: 1,
  trigger_interval_unit: 'week' as TriggerIntervalUnit,
  cc: '项目经理',
  // 新增
  wbs_item_id: '',
  confirmer_user_id: '',
})
```

`resetTaskFlowCreator()`（`:2552`）里同步重置这两项。

**节点责任人已有选择器**（`:707` 的 `step.owner_user_id`），但默认值是空的"待指定"。建议把提交按钮的禁用条件加严，让用户在点击前就知道还差什么：

```vue
<button
  type="submit"
  class="modal-primary"
  :disabled="!taskCreateForm.title
    || taskFlowSteps.length < 2
    || !taskCreateForm.wbs_item_id
    || !taskCreateForm.confirmer_user_id
    || taskFlowSteps.some(step => !step.owner_user_id)"
>
  创建任务流
</button>
```

即便不加这个前端校验，后端也会返回 422 并说明缺什么——只是让用户少跑一趟。

### 8.3 建议改：区分定时任务的提示语

定时任务登记后不会立即产生任务，但当前代码统一跳转到"我的任务"，用户会困惑于列表里没有新任务：

```ts
if (form.run_mode === 'scheduled') {
  message.success(`定时任务已登记：${taskTriggerSummary.value}，到点自动布置`)
  resetTaskFlowCreator()
} else {
  message.success('任务流已创建并进入我的任务。')
  taskManagementTab.value = 'mine'
  resetTaskFlowCreator()
}
```

### 8.4 建议改：退回重做的提示与拦截

引擎在节点被退回重做时会返回 `reopened: true`，前端应据此提前提示，而不是等用户点完成才被拒绝。

**第一步**：`types/index.ts` 的 `workflowSteps` 元素类型加字段：

```ts
workflowSteps: Array<{
  name: string
  owner?: string
  owner_user_id?: string
  due_at?: string
  order?: number
  next_step?: number
  status: 'pending' | 'processing' | 'completed' | 'blocked'
  note?: string
  material?: string
  phase?: string
  closure?: string
  // 新增：被退回重做的标记
  reopened?: boolean
}>
```

`stores/app.ts:360` 的 `mapTask` 用展开运算符 `{ ...step, status: step.status || 'pending' }` 拷贝节点，`reopened` 会自动透传，无需改映射代码。

**第二步**：处置抽屉（`task-disposition-drawer`，`:732`）里，当前节点若 `reopened` 且要求留证，提示用户并禁用提交直到重新上传：

```vue
<!-- 任务流程列表里，当前被退回的节点加提示 -->
<li v-for="(step, index) in selectedTask.workflowSteps" :class="step.status">
  ...
  <small v-if="step.reopened" class="task-disposition-reopen-hint">
    ⚠ 该节点被退回，需重新提交材料
  </small>
</li>
```

```ts
// 提交按钮的禁用条件：被退回的留证节点，必须有新附件才能推进
const needsFreshEvidence = computed(() => {
  const step = selectedTask.value?.workflowSteps
    .find(s => s.status === 'processing' && s.reopened)
  return !!step && !taskDispositionFiles.value.length
})
```

```vue
<button
  type="button"
  class="task-disposition-submit"
  :disabled="taskDispositionSubmitting || needsFreshEvidence"
  @click="submitTaskDisposition"
>
  {{ needsFreshEvidence ? '需重新上传材料' : '回复并推进' }}
</button>
```

即便不做前端拦截，后端也会在提交时返回 409「节点「X」被退回重做，需要重新提交证明材料」——前端 `error.response?.data?.detail` 能拿到这条中文提示直接展示。上述改动只是让用户少跑一趟。

---

## 九、旧数据处理

**新旧并存，旧数据只读。**

- 旧 `tasks` / `task_status_history` 表保留，不再写入
- 新任务全部走引擎
- 「历史任务」页需要同时展示两边的数据

历史任务的合并查询：

```python
@router.get("/projects/{project_id}/tasks/archive")
def list_archived_tasks(
    project_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, Any]:
    """历史任务：引擎的已闭环任务 + 旧表的遗留数据。

    旧数据以 legacy_ 前缀区分，避免与引擎 id 混淆。
    """
    engine = get_engine()

    closed = [
        t for t in engine.list_tasks(limit=500)
        if t.scope.get("project_id") == project_id
        and str(t.state) in ("done", "cancelled")
    ]
    result = [to_api_task(t) for t in closed]

    legacy = db.scalars(
        select(Task).where(
            Task.project_id == project_id,
            Task.status.in_(["completed", "cancelled"]),
        )
    ).all()
    for row in legacy:
        item = serialize(row)
        item["id"] = f"legacy_{row.id}"
        result.append(item)

    result.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return ok(result)
```

若某天要清理，旧表可直接 drop——引擎不依赖它。

---

## 十、接入清单

按序推进，每步可独立验证。

- [ ] **1** 安装引擎，确认 `from task_engine.engine import TaskEngine` 可导入
- [ ] **2** `config.py` 加 `task_engine_db` / `task_engine_tz`
- [ ] **3** 新建 `task_engine_gateway.py`（§4 整个文件）
- [ ] **4** `schemas.py` 扩展 `TaskInput` 与 `TaskStepUpdate`
- [ ] **5** 改写 8 个任务路由（§5）
- [ ] **6** 新增「待我验收」与「按工点查」两个接口（§6）
- [ ] **7** `main.py` 挂 tick 循环
- [ ] **8** 前端：透传触发字段 + **新增工点与确认人选择器**（§8.1、§8.2）
- [ ] **9** 历史任务页兼容旧数据
- [ ] **10** **验证 A**：不选工点直接提交，应收到 422「任务未关联工点，无法布置」
- [ ] **11** **验证 B**：建一个「每 5 分钟」的定时任务，观察 10 分钟内是否恰好产生 2 个任务
- [ ] **12** **验证 C**：用非确认人账号验收，应收到 409「只有确认人 X 可以验收该任务」

验证 A 检验责任制约束是否生效，B 检验触发与幂等，C 检验验收权限。三项都过，说明链路打通。

### 分步验证

```bash
# 步骤 1-3 后：确认引擎可用
python3.13 -c "
from app.task_engine_gateway import get_engine
e = get_engine()
print('引擎就绪，当前任务数：', len(e.list_tasks()))
"

# 步骤 5 后：确认接口形状兼容
curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/projects/1/tasks | python3 -m json.tool

# 步骤 7 后：确认 tick 在跑
tail -f logs/app.log | grep 任务引擎
```

---

## 十一、注意事项

### 11.0 责任制是硬约束，会拒绝不完整的任务

这是相对原实现最大的行为变化。原来节点的 `owner_user_id` 可以为空、任务照样能流转；现在布置前会校验三项，缺任何一项直接拒绝：

| 缺失 | 错误信息 |
|---|---|
| 节点责任人 | `以下节点尚未指定责任人，无法布置：第 2 个「派单整改」` |
| 确认人 | `任务未指定确认人，无法布置——完成后需要有人验收` |
| 工点 | `任务未关联工点，无法布置` |
| 非确认人验收 | `只有确认人 王工 可以验收该任务` |

**「安全员」这类岗位不能作为责任人。** `Assignee(ref="")` 会抛错，岗位到人的解析必须在调用引擎前完成——那是 Dobby 组织架构的职责。若你们有「按岗位自动派单」的需求，应在 `resolve_person()` 里查出该岗位当前的具体人员再传给引擎。

**模板阶段可以留空。** `create_flow_from_template` 不校验，只有 `dispatch` 和 `create_schedule` 才强制——这样模板才能跨工点、跨人员复用。生成结果里的 `missing_requirements` 会列出还缺什么。

### 11.1 引擎 id 是字符串

引擎的 id 形如 `task_a1b2c3d4e5f6`，不是自增整数。

前端 `id()` 用 `String(value)` 转换（`stores/app.ts:189`），字符串能安全通过，**无需改前端**。但后端路由的类型注解要从 `task_id: int` 改成 `task_id: str`，否则 FastAPI 会在参数校验阶段直接 422。

### 11.2 逾期判定不再依赖列表接口

原实现在 `list_tasks` 里顺带扫描逾期，没人打开页面就永远不标记。引擎的 tick 会主动扫描，因此列表接口只负责读——**不要再往里加扫描逻辑**，否则会与 tick 重复。

### 11.3 顺序约束会改变现有行为

原 `update_task_step` 可以完成任意 `step_index`。引擎强制按顺序，跨越会返回 409：

```
当前应处理节点「执行巡检」（第 1 个），不能跨越到「巡检归档」
```

如果现有前端有"批量完成所有节点"之类的操作，需要改成逐个按序调用。

### 11.4 附件是引用而非文件

引擎的 `attachments` 存的是字符串引用（文件名或 URL），不做文件操作，也不校验有效性——它无法访问文件系统。

建议流程：前端先调 Dobby 现有的 `uploadAttachment` 上传，拿到附件 id 后作为字符串传给引擎。

### 11.5 时区

引擎内部统一用 aware datetime。传入 naive datetime 会自动挂上配置的时区，但**建议显式带 tzinfo**，避免部署到 UTC 服务器时出现 8 小时偏差。

### 11.6 停机恢复不补跑

停机期间错过的触发会被跳过，不会补发。例如停机 200 天的每日任务，重启后只触发 1 次然后对齐到下一周期。

这是有意设计——补发 200 条历史通知只会骚扰责任人。若某些场景确实需要补跑，应在业务层单独处理。

### 11.7 数据库备份

单文件 SQLite，WAL 模式。备份用：

```bash
sqlite3 data/task_engine.db ".backup data/task_engine_backup.db"
```

直接复制文件需同时复制 `-wal` 和 `-shm`。规模参考：200 任务约 1.2 MB，查询 < 5ms。

### 11.8 模型不可用不阻断

引擎的 AI 生成失败时静默降级为规则解析，返回的 `generated_by` 会标明 `rules`。规则解析能识别「每周五」「每3天」「每两周」「每隔一天」「每半个月」等常见中文表述并自动选配模板。

**不配模型也能用**，模型主要在节点拆分和人员指派上更贴合具体需求。

### 11.9 退回重做必须重新提交材料

这是相对原实现的一个行为变化：确认人以「材料不合格」退回后，责任人**不重传新材料就无法完成**该节点。

引擎在节点退回时保留旧附件（审计轨迹不可抹去），但通过 `reopened` 标记强制重做时提交新材料——否则「照片不清晰，重拍」的退回形同虚设。兼容层已把 `reopened` 透传给前端（§8.4），前端可据此提前提示。

首次提交时沿用已上传的附件仍被允许，只有退回重做才强制新材料，语义精确。

---

## 十二、排查

**导入失败** — 确认 Python ≥ 3.13（引擎用了 `StrEnum`、`match`），且已 `pip install -e`。

**接口返回 422「无法布置」** — 责任制三要素没齐。检查 `build_flow()` 里 `resolve_person()` / `resolve_site()` 是否真的查到了人和 WBS 条目——查不到会返回 `None`，然后被引擎拒绝。常见原因是该用户不在项目的 `project_member` 里。

**接口返回 422（参数校验）** — 路由的 `task_id` 类型注解还是 `int`，改成 `str`。

**验收返回 409「只有确认人 X 可以」** — 传给引擎的 `actor` 不是确认人的 id。确认 `actor=str(user.id)` 用的是当前登录用户，且该用户确实是任务的 `confirmer`。

**完成节点返回 409「需要重新提交证明材料」** — 该节点被退回重做，旧附件不再顶用。检查前端是否透传了 `reopened` 标记（§8.4）并提示用户重新上传；如果业务上确实允许沿用旧材料，应在接入层对退回场景做显式豁免，而不是绕过引擎校验。

**前端状态显示异常** — 兼容层返回了引擎枚举而非 Dobby 枚举。检查 `ENGINE_TO_DOBBY_STATE` 是否被正确应用——前端 `uiTaskStatus` 只认 `completed` / `pending_confirm`。

**定时任务不触发** —
1. 看日志有无「任务引擎：...」输出，确认 tick 在跑
2. `engine.get_schedule(id)` 查 `active` / `paused` / `next_fire_at`
3. `next_fire_at` 为 `None` 表示计划已走完（一次性已触发，或达到 `max_fires` / `until`）

**任务列表为空** — 检查 `scope["project_id"]` 类型。登记时传的是 int，过滤时也要用 int 比较，`1 != "1"`。

**按工点查不到任务** — `site` 参数应传 WBS 条目 id 的字符串形式（`str(wbs_item_id)`），与 `resolve_site()` 写入的 `ref` 保持一致。

**MCP 与后端数据不一致** — 两边配的 `TASK_ENGINE_DB` 不是同一个路径。

---

## 十三、参考

| 文件 | 内容 |
|---|---|
| `README.md` | 引擎总览与架构 |
| `功能手册.md` | 完整功能说明与测试剧本 |
| `鲁棒性测试报告.md` | 147 项对抗性测试结果与已知边界 |
| `tools.json` | 21 个 MCP 工具的完整 schema |
| `src/task_engine/domain/models.py` | 领域模型，含 `Assignee` / `Site` / `TaskFlow` 的约束定义 |
| `src/task_engine/engine.py` | 服务门面，所有用例的入口 |
| `src/task_engine/serialize.py` | 领域对象 → JSON |

**质量状况**：249 项单元与协议契约测试、147 项对抗性测试，全部通过。已验证：责任制三要素强制、验收权限限定到人、月末不漂移、停机不补跑、并发安全、SQL 注入无效、200 任务下查询 < 5ms。