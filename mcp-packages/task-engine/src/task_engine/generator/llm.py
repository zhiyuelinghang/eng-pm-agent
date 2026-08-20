"""基于大模型的任务流生成，规则解析作为降级路径。

走 OpenAI 兼容的 /chat/completions 接口，因此对接 OpenAI、通义、DeepSeek、
本地 vLLM 等都无需改代码——只换 base_url 与 model。

核心原则：**模型不可用绝不阻断用户**。任何异常都退回规则生成，用户拿到的始终是一个
可编辑的合理流程，只是 origin 字段会如实标明它来自规则而非模型。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..domain.models import Assignee, IntervalUnit, RunMode, Site, StepSpec, TaskFlow, Trigger
from .rules import build_rule_based_flow

MAX_STEPS = 10
MIN_STEPS = 2


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """模型配置。全部可由环境变量提供，便于 MCP 部署时注入。"""

    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    timeout_seconds: float = 30.0

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @classmethod
    def from_env(cls) -> LLMConfig:
        return cls(
            api_key=os.getenv("TASK_ENGINE_AI_KEY", ""),
            base_url=os.getenv("TASK_ENGINE_AI_BASE_URL", "https://api.openai.com/v1"),
            model=os.getenv("TASK_ENGINE_AI_MODEL", "gpt-4o-mini"),
            timeout_seconds=float(os.getenv("TASK_ENGINE_AI_TIMEOUT", "30")),
        )


PROMPT = """你是工程项目的任务流设计助手。把用户的需求转换成一个可执行、可追溯的任务流。

用户需求：{requirement}

{context_block}

只返回一个 JSON 对象，不要包裹 Markdown 代码块。字段定义：
- title: 任务流标题，不超过 30 字
- summary: 一句话说明这个流程要解决什么
- category: 从 safety/quality/document/risk/monitoring/general 中选一个
- priority: 从 low/normal/high/urgent 中选一个
- run_mode: "once" 表示只执行一次，"recurring" 表示周期重复
- first_at: 首次执行时刻，格式 "YYYY-MM-DD HH:MM"
- interval_value: 正整数，仅 recurring 时有意义
- interval_unit: hour/day/week/month 之一，仅 recurring 时有意义
- steps: {min_steps} 到 {max_steps} 个节点的数组，每个节点包含：
  - name: 节点名称，动宾结构，不超过 15 字
  - assignee_ref: 责任人标识，必须来自下方人员列表的 ref；无法确定时用 null
  - due_offset_days: 该节点相对上一节点的工期天数，正整数
  - deliverable: 该节点的交付物或依据
  - requires_attachment: 布尔值，该节点是否必须上传证明材料

设计要求：
1. 节点按真实流转顺序排列，必须包含执行、复核、闭环三类环节
2. 涉及现场作业、整改、验收的节点，requires_attachment 设为 true
3. 责任人只能使用人员列表中存在的 ref，不确定时填 null，绝不编造
4. 当前时间是 {now}，first_at 必须晚于此刻
"""


class FlowGenerator:
    """任务流生成器：模型优先，规则兜底。"""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig.from_env()

    def generate(
        self,
        requirement: str,
        *,
        now: datetime,
        assignees: list[Assignee] | None = None,
        confirmer: Assignee | None = None,
        site: Site | None = None,
        watchers: list[Assignee] | None = None,
        context: dict[str, Any] | None = None,
    ) -> TaskFlow:
        """由自然语言需求生成任务流。

        永不抛错：模型失败时静默降级到规则生成，并在 origin_note 中说明原因。
        """
        if not requirement or len(requirement.strip()) < 4:
            raise ValueError("需求描述太短，至少需要 4 个字")

        fallback = build_rule_based_flow(
            requirement, now=now, assignees=assignees,
            confirmer=confirmer, site=site, watchers=watchers,
        )
        if not self.config.enabled:
            return fallback

        try:
            raw = self._call_model(requirement, now=now, assignees=assignees, context=context)
            return self._to_flow(
                raw, requirement=requirement, now=now,
                assignees=assignees, confirmer=confirmer, site=site,
                watchers=watchers, fallback=fallback,
            )
        except Exception as exc:
            reason = str(exc)[:150]
            return TaskFlow(
                title=fallback.title,
                steps=fallback.steps,
                summary=fallback.summary,
                category=fallback.category,
                priority=fallback.priority,
                trigger=fallback.trigger,
                site=fallback.site,
                confirmer=fallback.confirmer,
                watchers=fallback.watchers,
                tags=fallback.tags,
                origin="rules",
                origin_note=f"{fallback.origin_note}（模型暂不可用：{reason}）",
                scope=fallback.scope,
            )

    def _call_model(
        self,
        requirement: str,
        *,
        now: datetime,
        assignees: list[Assignee] | None,
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        import httpx  # 延迟导入：纯规则模式下无需安装

        people = assignees or []
        context_lines = []
        if people:
            roster = "\n".join(f"  - ref={p.ref}, 姓名={p.display_name}" for p in people)
            context_lines.append(f"可指派的人员：\n{roster}")
        if context:
            context_lines.append(f"项目上下文：{json.dumps(context, ensure_ascii=False)}")
        context_block = "\n\n".join(context_lines) if context_lines else "（无额外上下文，责任人一律填 null）"

        prompt = PROMPT.format(
            requirement=requirement.strip(),
            context_block=context_block,
            now=now.strftime("%Y-%m-%d %H:%M"),
            min_steps=MIN_STEPS,
            max_steps=MAX_STEPS,
        )

        response = httpx.post(
            f"{self.config.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.config.api_key}"},
            json={
                "model": self.config.model,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "你负责把工程任务需求转换为结构化任务流，只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return extract_json(content)

    def _to_flow(
        self,
        raw: dict[str, Any],
        *,
        requirement: str,
        now: datetime,
        assignees: list[Assignee] | None,
        confirmer: Assignee | None,
        site: Site | None,
        watchers: list[Assignee] | None,
        fallback: TaskFlow,
    ) -> TaskFlow:
        """把模型输出转成领域对象，逐字段校验。

        模型可能返回任何东西——越界的枚举、编造的人员 id、过去的时间。这里全部
        夹回合法范围，宁可用 fallback 的值也不放行脏数据。
        """
        by_ref = {p.ref: p for p in (assignees or [])}

        steps_raw = raw.get("steps")
        if not isinstance(steps_raw, list) or len(steps_raw) < MIN_STEPS:
            raise ValueError("模型返回的节点数量不足")

        steps: list[StepSpec] = []
        for item in steps_raw[:MAX_STEPS]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            # 只接受确实存在的人员，杜绝模型编造
            ref = item.get("assignee_ref")
            assignee = by_ref.get(str(ref)) if ref else None
            steps.append(
                StepSpec(
                    name=name[:40],
                    assignee=assignee,
                    due_offset_days=_clamp_int(item.get("due_offset_days"), 1, 1, 365),
                    deliverable=str(item.get("deliverable") or "")[:100],
                    requires_attachment=bool(item.get("requires_attachment")),
                ),
            )

        if len(steps) < MIN_STEPS:
            raise ValueError("模型返回的有效节点不足")

        return TaskFlow(
            title=str(raw.get("title") or fallback.title)[:60],
            steps=tuple(steps),
            summary=str(raw.get("summary") or requirement)[:200],
            category=_pick(
                raw.get("category"),
                {"safety", "quality", "document", "risk", "monitoring", "general"},
                fallback.category,
            ),
            priority=_pick(raw.get("priority"), {"low", "normal", "high", "urgent"}, "normal"),
            trigger=_parse_trigger(raw, now=now, fallback=fallback.trigger),
            site=site,
            confirmer=confirmer,
            watchers=tuple(watchers or ()),
            origin="ai",
            origin_note=f"由模型（{self.config.model}）根据需求生成 {len(steps)} 个节点，可继续调整",
        )


def extract_json(content: str) -> dict[str, Any]:
    """从模型输出中抠出 JSON 对象。

    即便要求了 json_object，有些模型仍会包一层 ```json 代码块或加前后缀说明。
    """
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]

    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("模型未返回 JSON 对象")
    return parsed


def _parse_trigger(raw: dict[str, Any], *, now: datetime, fallback: Trigger) -> Trigger:
    """解析触发规则，非法值一律退回规则解析的结果。"""
    mode_raw = str(raw.get("run_mode") or "").lower()
    if mode_raw not in {"once", "recurring"}:
        return fallback

    first_at = _parse_datetime(raw.get("first_at"), tzinfo=now.tzinfo)
    # 模型给出过去的时间是常见错误，直接退回 fallback 的时刻
    if first_at is None or first_at <= now:
        first_at = fallback.first_at

    if mode_raw == "once":
        return Trigger(run_mode=RunMode.ONCE, first_at=first_at, timezone=fallback.timezone)

    unit_raw = str(raw.get("interval_unit") or "").lower()
    unit = IntervalUnit(unit_raw) if unit_raw in {u.value for u in IntervalUnit} else fallback.interval_unit
    return Trigger(
        run_mode=RunMode.RECURRING,
        first_at=first_at,
        interval_value=_clamp_int(raw.get("interval_value"), fallback.interval_value, 1, 365),
        interval_unit=unit,
        timezone=fallback.timezone,
    )


def _parse_datetime(value: Any, *, tzinfo: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text[: len(fmt) + 2], fmt)
            return parsed.replace(tzinfo=tzinfo)
        except ValueError:
            continue
    return None


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(number, high))


def _pick(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or "").lower()
    return text if text in allowed else default
