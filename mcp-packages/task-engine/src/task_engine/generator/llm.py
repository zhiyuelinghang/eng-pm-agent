"""基于大模型的任务流生成。

走 OpenAI 兼容的 /chat/completions 接口，因此对接 OpenAI、通义、DeepSeek、
本地 vLLM 等都无需改代码——只换 base_url 与 model。

模型配置、请求或响应有问题时直接抛出明确错误，不生成任何替代结果。规则模板由独立的
模板入口负责，不能伪装成 AI 生成结果。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..domain.models import Assignee, IntervalUnit, RunMode, Site, StepSpec, TaskFlow, Trigger

MAX_STEPS = 10
MIN_STEPS = 2
TASK_MESSAGE_AGENT_ID = "dobby-task-engine"
TASK_MESSAGE_AGENT_NAME = "Dobby"


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """模型配置。全部可由环境变量提供，便于 MCP 部署时注入。"""

    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @classmethod
    def from_env(cls) -> LLMConfig:
        return cls(
            api_key=os.getenv("TASK_ENGINE_AI_KEY", ""),
            base_url=os.getenv("TASK_ENGINE_AI_BASE_URL", "https://api.openai.com/v1"),
            model=os.getenv("TASK_ENGINE_AI_MODEL", "gpt-4o-mini"),
        )


class AIFlowGenerationError(RuntimeError):
    """AI 任务流生成失败；调用方必须把错误原样暴露，禁止静默降级。"""


PROMPT = """你是工程项目的任务流设计助手。把用户的需求转换成一个可执行、可追溯的任务流。

用户需求：{requirement}

{context_block}

只返回一个 JSON 对象，不要包裹 Markdown 代码块。字段定义：
- title: 任务流标题，不超过 30 字
- summary: 一句话说明这个流程要解决什么
- category: 从 safety/quality/document/risk/monitoring/general/automation 中选一个
- priority: 从 low/normal/high/urgent 中选一个
- run_mode: "once" 表示只执行一次，"recurring" 表示周期重复
- first_at: 首次执行时刻，格式 "YYYY-MM-DD HH:MM"
- interval_value: 正整数，仅 recurring 时有意义
- interval_unit: hour/day/week/month 之一，仅 recurring 时有意义
- steps: 1 到 {max_steps} 个节点的数组，每个节点包含：
  - name: 节点名称，动宾结构，不超过 15 字
  - node_type: "manual" 或 "project_chat_message"
  - node_type 为 manual 时还必须包含：
    - assignee_ref: 责任人标识，必须来自下方人员列表的 ref；无法确定时用 null
    - due_offset_days: 该节点相对上一节点的工期天数，正整数
    - deliverable: 该节点的交付物或依据
    - requires_attachment: 布尔值，该节点是否必须上传证明材料
  - node_type 为 project_chat_message 时还必须包含 action：
    - type: 固定为 "project_chat_message"
    - channel_ref: 目标群聊标识，必须来自项目上下文 chat_channels 的 ref
    - mention_mode: "none"、"all" 或 "users"
    - mentioned_user_refs: mention_mode 为 users 时填写用户 ref 数组，否则必须是空数组
    - content: 实际发送的群消息正文

设计要求：
1. 用户要求由系统或 Dobby 在群聊中发送、发布、通知或提醒时，必须生成 project_chat_message 自动节点，不能用 manual 人工处理代替
2. 单次群聊提醒只生成 1 个自动消息节点，不得额外添加准备、检查送达、人工确认或闭环节点
3. 用户说“我”“提醒我”“艾特我”或“@我”时，指的是项目上下文 current_user，mentioned_user_refs 只能填写 current_user.ref，不能从人员列表猜其他人
4. 用户说“大家”“全体成员”时使用 mention_mode=all；没有提及要求时使用 none
5. 用户没有给出可识别的群聊名称，只说“群里”“群聊”或“项目群”时，必须选择 chat_channels 中 channel_type=project 的群聊
6. 用户明确给出群聊名称时，必须按 title 在 chat_channels 中匹配对应项目群或私密群；即使存在项目群也不能替换用户明确指定的群聊。找不到对应群聊时把 channel_ref 设为 null，让调用方明确报错，绝不能偷偷改用项目群
7. 发送方由平台统一固定为 Dobby，不属于模型可选择字段；不得输出或编造发送智能体标识
8. 只有真实的人工工程流程才使用 manual 节点，此时至少 {min_steps} 个节点，并按实际流转需要设计执行、复核和闭环环节
9. 涉及现场作业、整改、验收的人工节点，requires_attachment 设为 true
10. 人工节点责任人只能使用人员列表中存在的 ref，不确定时填 null，绝不编造
11. 当前时间是 {now}，first_at 必须晚于此刻
"""


class FlowGenerator:
    """只使用模型生成任务流；任何失败均显式报错。"""

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
        """由自然语言需求生成任务流，不提供规则降级。"""
        if not requirement or len(requirement.strip()) < 4:
            raise ValueError("需求描述太短，至少需要 4 个字")
        if not self.config.enabled:
            raise AIFlowGenerationError("Dobby AI 生成失败：未配置模型 API Key")

        try:
            raw = self._call_model(requirement, now=now, assignees=assignees, context=context)
        except Exception as exc:
            reason = str(exc).strip()[:300] or type(exc).__name__
            raise AIFlowGenerationError(
                f"Dobby AI 请求或响应解析失败（{type(exc).__name__}）：{reason}",
            ) from exc

        try:
            return self._to_flow(
                raw, requirement=requirement, now=now,
                assignees=assignees, confirmer=confirmer, site=site,
                watchers=watchers, context=context,
            )
        except Exception as exc:
            raise AIFlowGenerationError(f"Dobby AI 返回的任务流不合法：{exc}") from exc

    async def generate_async(
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
        """异步生成任务流，由调用方通过取消任务决定何时停止。"""
        if not requirement or len(requirement.strip()) < 4:
            raise ValueError("需求描述太短，至少需要 4 个字")
        if not self.config.enabled:
            raise AIFlowGenerationError("Dobby AI 生成失败：未配置模型 API Key")

        # 保持 MCP 服务在未启用 AI 时零网络运行时依赖；仅实际异步生成时加载。
        import asyncio

        try:
            raw = await self._call_model_async(
                requirement,
                now=now,
                assignees=assignees,
                context=context,
            )
        except asyncio.CancelledError:
            # 用户主动停止时必须让取消信号原样向上传递，不能包装成“生成失败”。
            raise
        except Exception as exc:
            reason = str(exc).strip()[:300] or type(exc).__name__
            raise AIFlowGenerationError(
                f"Dobby AI 请求或响应解析失败（{type(exc).__name__}）：{reason}",
            ) from exc

        try:
            return self._to_flow(
                raw,
                requirement=requirement,
                now=now,
                assignees=assignees,
                confirmer=confirmer,
                site=site,
                watchers=watchers,
                context=context,
            )
        except Exception as exc:
            raise AIFlowGenerationError(f"Dobby AI 返回的任务流不合法：{exc}") from exc

    def _call_model(
        self,
        requirement: str,
        *,
        now: datetime,
        assignees: list[Assignee] | None,
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        import httpx  # 延迟导入：未使用 AI 生成能力时无需加载网络依赖

        request = self._model_request(
            requirement,
            now=now,
            assignees=assignees,
            context=context,
        )
        # 生成耗时由模型决定，不设置固定截止时间；同步调用由进程中断负责停止。
        response = httpx.post(**request, timeout=None)
        return self._parse_model_response(response)

    async def _call_model_async(
        self,
        requirement: str,
        *,
        now: datetime,
        assignees: list[Assignee] | None,
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        import httpx  # 延迟导入：未使用 AI 生成能力时无需加载网络依赖

        request = self._model_request(
            requirement,
            now=now,
            assignees=assignees,
            context=context,
        )
        # 不使用固定超时。取消外层 asyncio.Task 会立即关闭正在等待的模型请求。
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(**request)
        return self._parse_model_response(response)

    def _model_request(
        self,
        requirement: str,
        *,
        now: datetime,
        assignees: list[Assignee] | None,
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:

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

        return {
            "url": f"{self.config.base_url.rstrip('/')}/chat/completions",
            "headers": {"Authorization": f"Bearer {self.config.api_key}"},
            "json": {
                "model": self.config.model,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "你负责把工程任务需求转换为结构化任务流，只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
            },
        }

    @staticmethod
    def _parse_model_response(response: Any) -> dict[str, Any]:
        import httpx

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            response_detail = " ".join(response.text.strip().split())[:500]
            raise RuntimeError(
                f"模型接口返回 HTTP {response.status_code}"
                f"：{response_detail or response.reason_phrase}",
            ) from exc

        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("模型响应缺少 choices[0].message.content") from exc
        if not isinstance(content, str) or not content.strip():
            raise ValueError("模型响应内容为空")
        return extract_json(content)

    def _to_flow(
        self,
        raw: dict[str, Any],
        *,
        requirement: str = "",
        now: datetime,
        assignees: list[Assignee] | None,
        confirmer: Assignee | None,
        site: Site | None,
        watchers: list[Assignee] | None,
        context: dict[str, Any] | None = None,
    ) -> TaskFlow:
        """把模型输出转成领域对象；非法字段直接拒绝，不静默替换。"""
        by_ref = {p.ref: p for p in (assignees or [])}

        steps_raw = raw.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            raise ValueError("模型返回的节点数量不足")
        if len(steps_raw) > MAX_STEPS:
            raise ValueError(f"模型返回的节点数量超过 {MAX_STEPS} 个")

        steps: list[StepSpec] = []
        step_actions: dict[str, dict[str, Any]] = {}
        for index, item in enumerate(steps_raw, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"第 {index} 个节点不是 JSON 对象")
            name = _required_text(item, "name", label=f"第 {index} 个节点名称", max_length=40)
            node_type = _required_choice(
                item,
                "node_type",
                label=f"第 {index} 个节点类型",
                allowed={"manual", "project_chat_message"},
            )
            if node_type == "project_chat_message":
                action = _parse_project_chat_action(
                    item,
                    index=index,
                    context=context,
                    requirement=requirement,
                )
                step_actions[str(index - 1)] = action
                steps.append(
                    StepSpec(
                        name=name,
                        due_offset_days=0,
                        instruction=action["content"],
                        automated=True,
                    ),
                )
                continue

            ref = item.get("assignee_ref")
            assignee = None
            if ref not in (None, ""):
                assignee = by_ref.get(str(ref))
                if assignee is None:
                    raise ValueError(f"第 {index} 个节点引用了不存在的责任人：{ref}")
            steps.append(
                StepSpec(
                    name=name,
                    assignee=assignee,
                    due_offset_days=_required_int(
                        item,
                        "due_offset_days",
                        label=f"第 {index} 个节点工期",
                        low=1,
                        high=365,
                    ),
                    deliverable=_required_text(
                        item,
                        "deliverable",
                        label=f"第 {index} 个节点交付物",
                        max_length=100,
                    ),
                    requires_attachment=_required_bool(
                        item,
                        "requires_attachment",
                        label=f"第 {index} 个节点附件要求",
                    ),
                ),
            )

        manual_steps = [step for step in steps if not step.automated]
        if manual_steps and len(steps) < MIN_STEPS:
            raise ValueError("人工任务流的节点数量不足")

        pure_automation = bool(steps) and len(step_actions) == len(steps)
        scope: dict[str, Any] = {}
        if step_actions:
            scope["step_actions"] = step_actions
        if pure_automation:
            scope["execution_kind"] = "automation"
            if len(step_actions) == 1:
                scope["action"] = next(iter(step_actions.values()))

        return TaskFlow(
            title=_required_text(raw, "title", label="任务流标题", max_length=60),
            steps=tuple(steps),
            summary=_required_text(raw, "summary", label="任务流摘要", max_length=200),
            category=(
                "automation"
                if pure_automation
                else _required_choice(
                    raw,
                    "category",
                    label="任务流分类",
                    allowed={
                        "safety",
                        "quality",
                        "document",
                        "risk",
                        "monitoring",
                        "general",
                        "automation",
                    },
                )
            ),
            priority=_required_choice(
                raw,
                "priority",
                label="任务流优先级",
                allowed={"low", "normal", "high", "urgent"},
            ),
            trigger=_parse_trigger(raw, now=now),
            site=site,
            confirmer=confirmer,
            watchers=tuple(watchers or ()),
            origin="ai",
            origin_note=f"由模型（{self.config.model}）根据需求生成 {len(steps)} 个节点，可继续调整",
            scope=scope,
        )


def _parse_project_chat_action(
    step: dict[str, Any],
    *,
    index: int,
    context: dict[str, Any] | None,
    requirement: str = "",
) -> dict[str, Any]:
    """把模型选择的群聊动作解析为宿主可直接执行的严格动作。"""
    action = step.get("action")
    if not isinstance(action, dict):
        raise ValueError(f"第 {index} 个消息节点缺少 action 配置")
    if _required_choice(
        action,
        "type",
        label=f"第 {index} 个消息节点动作类型",
        allowed={"project_chat_message"},
    ) != "project_chat_message":
        raise ValueError(f"第 {index} 个消息节点动作类型无效")

    context_data = context if isinstance(context, dict) else {}
    channels_raw = context_data.get("chat_channels")
    channels = channels_raw if isinstance(channels_raw, list) else []
    channels_by_ref = {
        str(channel.get("ref")): channel
        for channel in channels
        if isinstance(channel, dict) and channel.get("ref") not in (None, "")
    }
    channel_ref = _identifier_text(
        action.get("channel_ref"),
        label=f"第 {index} 个消息节点目标群聊",
    )
    channel = channels_by_ref.get(channel_ref)
    if channel is None:
        raise ValueError(f"第 {index} 个消息节点引用了不可用的群聊：{channel_ref}")
    _validate_model_channel_selection(
        requirement,
        step=step,
        selected_channel=channel,
        channels=channels,
        index=index,
    )

    mention_mode = _required_choice(
        action,
        "mention_mode",
        label=f"第 {index} 个消息节点提醒方式",
        allowed={"none", "all", "users"},
    )
    mentioned_refs_raw = action.get("mentioned_user_refs")
    if not isinstance(mentioned_refs_raw, list):
        raise ValueError(f"第 {index} 个消息节点提醒成员必须是数组")
    mentioned_refs = [
        _identifier_text(
            user_ref,
            label=f"第 {index} 个消息节点提醒成员",
        )
        for user_ref in mentioned_refs_raw
    ]
    mentioned_refs = list(dict.fromkeys(mentioned_refs))
    if mention_mode == "users" and not mentioned_refs:
        raise ValueError(f"第 {index} 个消息节点至少需要一位提醒成员")
    if mention_mode != "users" and mentioned_refs:
        raise ValueError(
            f"第 {index} 个消息节点仅在提醒指定成员时才能填写成员列表",
        )

    member_refs_raw = channel.get("member_refs")
    member_refs = {
        str(user_ref)
        for user_ref in (
            member_refs_raw if isinstance(member_refs_raw, list) else []
        )
    }
    unavailable_refs = [ref for ref in mentioned_refs if ref not in member_refs]
    if unavailable_refs:
        raise ValueError(
            f"第 {index} 个消息节点包含不在目标群聊中的成员："
            f"{'、'.join(unavailable_refs)}",
        )

    current_user = context_data.get("current_user")
    if not isinstance(current_user, dict):
        raise ValueError(f"第 {index} 个消息节点缺少当前登录用户上下文")
    creator_ref = _identifier_text(
        current_user.get("ref"),
        label="当前登录用户标识",
    )

    try:
        channel_id = int(channel_ref)
        mentioned_user_ids = [int(ref) for ref in mentioned_refs]
        creator_user_id = int(creator_ref)
    except ValueError as exc:
        raise ValueError("群聊、成员或当前登录用户标识必须是数字 ID") from exc

    return {
        "type": "project_chat_message",
        "channel_id": channel_id,
        "sender_agent_id": TASK_MESSAGE_AGENT_ID,
        "sender_agent_name": TASK_MESSAGE_AGENT_NAME,
        "mention_mode": mention_mode,
        "mentioned_user_ids": mentioned_user_ids,
        "content": _required_text(
            action,
            "content",
            label=f"第 {index} 个消息节点正文",
            max_length=8000,
        ),
        "created_by_user_id": creator_user_id,
    }


def _normalize_channel_match_text(value: Any) -> str:
    return re.sub(r"[\W_]+", "", str(value or ""), flags=re.UNICODE).casefold()


def _channel_title_aliases(channel: dict[str, Any]) -> set[str]:
    title = _normalize_channel_match_text(channel.get("title"))
    if not title:
        return set()
    aliases = {title}
    wrappers = ("项目群聊", "私密群聊", "项目群", "私密群", "群聊", "群")
    for suffix in wrappers:
        normalized_suffix = _normalize_channel_match_text(suffix)
        if title.endswith(normalized_suffix):
            shortened = title[: -len(normalized_suffix)]
            if len(shortened) >= 2:
                aliases.add(shortened)
    for prefix in wrappers[:-1]:
        normalized_prefix = _normalize_channel_match_text(prefix)
        if title.startswith(normalized_prefix):
            shortened = title[len(normalized_prefix) :]
            if len(shortened) >= 2:
                aliases.add(shortened)
    return aliases


def _channels_named_in_text(
    text: str,
    channels: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized_text = _normalize_channel_match_text(text)
    if not normalized_text:
        return []
    return [
        channel
        for channel in channels
        if isinstance(channel, dict)
        and any(alias in normalized_text for alias in _channel_title_aliases(channel))
    ]


def _validate_model_channel_selection(
    requirement: str,
    *,
    step: dict[str, Any],
    selected_channel: dict[str, Any],
    channels: list[dict[str, Any]],
    index: int,
) -> None:
    """校验模型的群聊路由，错误时显式失败，绝不静默改选其他群。"""
    if not requirement.strip():
        return

    named_channels = _channels_named_in_text(requirement, channels)
    if len(named_channels) > 1:
        action = step.get("action") if isinstance(step.get("action"), dict) else {}
        local_text = " ".join(
            str(value or "")
            for value in (step.get("name"), action.get("content"))
        )
        local_matches = _channels_named_in_text(local_text, named_channels)
        if len(local_matches) == 1:
            named_channels = local_matches

    if len(named_channels) == 1:
        expected = named_channels[0]
        if str(selected_channel.get("ref")) != str(expected.get("ref")):
            raise ValueError(
                f"第 {index} 个消息节点没有使用需求中明确指定的群聊："
                f"{expected.get('title')}",
            )
        return

    if not named_channels and selected_channel.get("channel_type") != "project":
        raise ValueError(
            f"第 {index} 个消息节点的需求未明确群聊名称，"
            "目标群聊必须使用当前项目群",
        )


def _identifier_text(value: Any, *, label: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{label}无效：{value}")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label}不能为空")
    return text


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


def _parse_trigger(raw: dict[str, Any], *, now: datetime) -> Trigger:
    """严格解析模型返回的触发规则。"""
    mode_raw = _required_choice(
        raw,
        "run_mode",
        label="触发模式",
        allowed={"once", "recurring"},
    )

    first_at = _parse_datetime(raw.get("first_at"), tzinfo=now.tzinfo)
    if first_at is None:
        raise ValueError("首次执行时间缺失或格式错误")
    if first_at <= now:
        raise ValueError("首次执行时间必须晚于当前时间")

    timezone = str(now.tzinfo or "Asia/Shanghai")

    if mode_raw == "once":
        return Trigger(run_mode=RunMode.ONCE, first_at=first_at, timezone=timezone)

    unit_raw = _required_choice(
        raw,
        "interval_unit",
        label="重复间隔单位",
        allowed={unit.value for unit in IntervalUnit},
    )
    return Trigger(
        run_mode=RunMode.RECURRING,
        first_at=first_at,
        interval_value=_required_int(
            raw,
            "interval_value",
            label="重复间隔数值",
            low=1,
            high=365,
        ),
        interval_unit=IntervalUnit(unit_raw),
        timezone=timezone,
    )


def _parse_datetime(value: Any, *, tzinfo: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=tzinfo)
        except ValueError:
            continue
    return None


def _required_text(
    source: dict[str, Any],
    field: str,
    *,
    label: str,
    max_length: int,
) -> str:
    value = source.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}不能为空")
    text = value.strip()
    if len(text) > max_length:
        raise ValueError(f"{label}不能超过 {max_length} 个字符")
    return text


def _required_choice(
    source: dict[str, Any],
    field: str,
    *,
    label: str,
    allowed: set[str],
) -> str:
    value = source.get(field)
    if not isinstance(value, str) or value.lower() not in allowed:
        raise ValueError(f"{label}无效：{value}")
    return value.lower()


def _required_int(
    source: dict[str, Any],
    field: str,
    *,
    label: str,
    low: int,
    high: int,
) -> int:
    value = source.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label}必须是整数")
    if value < low or value > high:
        raise ValueError(f"{label}必须在 {low} 到 {high} 之间")
    return value


def _required_bool(source: dict[str, Any], field: str, *, label: str) -> bool:
    value = source.get(field)
    if not isinstance(value, bool):
        raise ValueError(f"{label}必须是布尔值")
    return value
