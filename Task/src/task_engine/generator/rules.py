"""从中文需求描述中解析出任务流——不依赖任何模型。

这是引擎的保底能力：模型不可用、没配 key、或调用超时的情况下，用户依然能得到一个
可编辑的合理流程，而不是一个错误提示。工程现场对可用性的要求高于智能程度。

解析策略是刻意保守的：只认有把握的模式，认不出就落到通用模板，绝不猜。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from ..domain.models import Assignee, IntervalUnit, RunMode, Site, TaskFlow, Trigger
from .templates import build_from_template

# 中文数字，覆盖口语里的常见写法
CN_NUMBERS: dict[str, int] = {
    "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "七": 7, "八": 8, "九": 9, "十": 10, "半": 1,
}

UNIT_MAP: dict[str, IntervalUnit] = {
    "小时": IntervalUnit.HOUR, "钟头": IntervalUnit.HOUR,
    "天": IntervalUnit.DAY, "日": IntervalUnit.DAY,
    "周": IntervalUnit.WEEK, "星期": IntervalUnit.WEEK, "礼拜": IntervalUnit.WEEK,
    "月": IntervalUnit.MONTH,
}

# 星期几 → ISO weekday (周一=1)
WEEKDAYS: dict[str, int] = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7,
}

# 需求关键词 → 模板。顺序即优先级，先匹配到的胜出。
TEMPLATE_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("隐患", "整改", "违章", "临边", "防护"), "hazard_rectification"),
    (("巡检", "监测", "核查数据", "基坑", "测斜"), "periodic_inspection"),
    (("资料", "补齐", "缺失", "补全", "台账"), "material_completion"),
    (("风险", "预警", "处置", "应急"), "risk_response"),
    (("报告", "审核", "审批", "报审", "方案"), "report_review"),
    (("条件", "验收", "报验", "放行", "开工"), "condition_check"),
)


def parse_number(raw: str) -> int:
    """把 "3" 或 "三" 解析成整数，认不出时返回 1。"""
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    if raw in CN_NUMBERS:
        return CN_NUMBERS[raw]
    # "十二" 这类组合
    if raw.startswith("十") and len(raw) == 2:
        return 10 + CN_NUMBERS.get(raw[1], 0)
    return 1


def detect_template(requirement: str) -> str:
    """按关键词猜测最贴合的模板。"""
    for keywords, template_key in TEMPLATE_HINTS:
        if any(word in requirement for word in keywords):
            return template_key
    return "generic"


def parse_trigger(requirement: str, *, now: datetime) -> Trigger:
    """从需求文本中解析触发规则。

    支持的表述：
      「每周五…」「每周一检查…」    → 每周，首次落在最近的那个星期几
      「每 3 天…」「每三天…」        → 每 3 天
      「每月…」「每个月…」          → 每月
      「每两周…」                   → 每 2 周
    认不出周期表述时返回一次性触发。
    """
    text = requirement.strip()
    base_time = now.replace(minute=0, second=0, microsecond=0)
    # 默认早上 9 点——工程现场的常规开工时间
    default_at = base_time.replace(hour=9)
    if default_at <= now:
        default_at += timedelta(days=1)

    # 「每周五」这类带星期几的表述
    weekday_match = re.search(r"每(?:周|星期|礼拜)([一二三四五六日天])", text)
    if weekday_match:
        target = WEEKDAYS[weekday_match.group(1)]
        first_at = _next_weekday(now, target)
        return Trigger(
            run_mode=RunMode.RECURRING,
            first_at=first_at,
            interval_value=1,
            interval_unit=IntervalUnit.WEEK,
        )

    # 「每 3 天」「每三个月」「每两周」「每隔一天」「每半个月」
    # 「每隔」是口语里常见的同义说法；「半个月」按 15 天处理，比归到「月」更贴近本意
    if re.search(r"每隔?\s*半\s*(?:个)?\s*月", text):
        return Trigger(
            run_mode=RunMode.RECURRING,
            first_at=default_at,
            interval_value=15,
            interval_unit=IntervalUnit.DAY,
        )

    interval_match = re.search(
        r"每(?:隔)?\s*([0-9]+|[一两二三四五六七八九十]+)?\s*(?:个)?\s*(小时|钟头|天|日|周|星期|礼拜|月)",
        text,
    )
    if interval_match:
        raw_value, raw_unit = interval_match.groups()
        value = parse_number(raw_value) if raw_value else 1
        unit = UNIT_MAP[raw_unit]
        # 「每0天」这类无意义的间隔按 1 处理——保底路径不能抛错，
        # 用户宁可拿到一个可编辑的每日任务，也好过一句报错。
        return Trigger(
            run_mode=RunMode.RECURRING,
            first_at=default_at,
            interval_value=max(1, value),
            interval_unit=unit,
        )

    # 「定时」「周期」等泛化表述——默认按周
    if any(word in text for word in ("定期", "周期", "定时", "循环")):
        return Trigger(
            run_mode=RunMode.RECURRING,
            first_at=default_at,
            interval_value=1,
            interval_unit=IntervalUnit.WEEK,
        )

    return Trigger(run_mode=RunMode.ONCE, first_at=default_at)


def _next_weekday(now: datetime, target_iso_weekday: int) -> datetime:
    """找到下一个指定星期几的早上 9 点。今天就是且未过 9 点时取今天。"""
    candidate = now.replace(hour=9, minute=0, second=0, microsecond=0)
    delta = (target_iso_weekday - now.isoweekday()) % 7
    if delta == 0 and candidate <= now:
        delta = 7
    return candidate + timedelta(days=delta)


def extract_title(requirement: str) -> str:
    """从需求里提炼标题：取第一个句读之前的内容，去掉周期前缀。"""
    text = requirement.strip()
    # 去掉「每周五」「每 3 天」这类时间前缀，它们属于触发规则而非标题
    text = re.sub(
        r"^每(?:隔)?\s*(?:半|[0-9]+|[一两二三四五六七八九十]+)?\s*(?:个)?\s*"
        r"(?:小时|钟头|天|日|周|星期|礼拜|月)?[一二三四五六日天]?\s*",
        "",
        text,
    )
    # 截到第一个句读
    for sep in ("；", ";", "。", "，", ",", "\n"):
        index = text.find(sep)
        if index > 0:
            text = text[:index]
            break
    title = text.strip()[:60]
    return title or requirement.strip()[:60]


def build_rule_based_flow(
    requirement: str,
    *,
    now: datetime,
    assignees: list[Assignee] | None = None,
    confirmer: Assignee | None = None,
    site: Site | None = None,
    watchers: list[Assignee] | None = None,
) -> TaskFlow:
    """纯规则生成任务流。永远成功——这是保底路径，不允许抛错。"""
    template_key = detect_template(requirement)
    trigger = parse_trigger(requirement, now=now)
    title = extract_title(requirement)

    flow = build_from_template(
        template_key,
        title=title,
        assignees=assignees,
        confirmer=confirmer,
        site=site,
        watchers=watchers,
    )
    return TaskFlow(
        title=flow.title,
        steps=flow.steps,
        summary=requirement.strip()[:200],
        category=flow.category,
        priority=flow.priority,
        trigger=trigger,
        site=flow.site,
        confirmer=flow.confirmer,
        watchers=flow.watchers,
        tags=flow.tags,
        origin="rules",
        origin_note=(
            f"未启用模型，已按「{template_key}」规则模板生成 {len(flow.steps)} 个可编辑节点。"
            f"触发方式：{trigger.describe()}"
        ),
        scope=flow.scope,
    )
