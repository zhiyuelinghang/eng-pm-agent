"""生成器测试：模板、规则解析与模型降级。

规则解析是保底路径，必须永不抛错——这里用各种真实的中文表述压它。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from task_engine.domain.models import Assignee, IntervalUnit, RunMode
from task_engine.generator.llm import FlowGenerator, LLMConfig, extract_json
from task_engine.generator.rules import (
    build_rule_based_flow,
    detect_template,
    extract_title,
    parse_number,
    parse_trigger,
)
from task_engine.generator.templates import (
    TEMPLATES,
    build_from_template,
    find_template,
    list_templates,
)

TZ = ZoneInfo("Asia/Shanghai")
# 2026-03-02 是星期一
MONDAY = datetime(2026, 3, 2, 14, 0, tzinfo=TZ)

ZHANG = Assignee(ref="u1", display_name="张三")
LI = Assignee(ref="u2", display_name="李四")


class TestTemplates:
    def test_all_templates_are_valid(self):
        for template in TEMPLATES:
            flow = build_from_template(template.key)
            assert len(flow.steps) >= 2
            assert flow.title

    def test_every_template_has_review_and_closure(self):
        """每个模板都应包含复核与闭环环节——可追溯性的基本要求。"""
        for template in TEMPLATES:
            names = "".join(step.name for step in template.steps)
            assert any(word in names for word in ("复核", "确认", "审核", "分析")), template.key
            assert any(word in names for word in ("归档", "关闭", "通过", "入库")), template.key

    def test_assignees_are_distributed(self):
        flow = build_from_template("hazard_rectification", assignees=[ZHANG, LI])
        assert flow.steps[0].assignee == ZHANG
        assert flow.steps[1].assignee == LI
        assert flow.steps[2].assignee == ZHANG  # 轮转

    def test_lookup_by_label(self):
        assert find_template("隐患整改") is not None
        assert find_template("hazard_rectification") is not None

    def test_unknown_template_lists_options(self):
        with pytest.raises(KeyError, match="可用模板"):
            build_from_template("不存在的模板")

    def test_list_templates_shape(self):
        listed = list_templates()
        assert len(listed) == len(TEMPLATES)
        assert all("key" in item and "steps" in item for item in listed)

    def test_no_assignee_leaves_unassigned(self):
        flow = build_from_template("generic")
        assert all(step.assignee is None for step in flow.steps)


class TestParseNumber:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("3", 3), ("三", 3), ("两", 2), ("一", 1), ("十", 10), ("十二", 12), ("乱码", 1)],
    )
    def test_variants(self, raw, expected):
        assert parse_number(raw) == expected


class TestParseTrigger:
    def test_weekly_with_weekday(self):
        trigger = parse_trigger("每周五检查监测数据", now=MONDAY)
        assert trigger.run_mode is RunMode.RECURRING
        assert trigger.interval_unit is IntervalUnit.WEEK
        assert trigger.first_at.isoweekday() == 5  # 周五

    def test_weekday_today_rolls_forward_if_past(self):
        # 周一下午 14:00 说"每周一"，首次应落到下周一（今天 9 点已过）
        trigger = parse_trigger("每周一巡检", now=MONDAY)
        assert trigger.first_at.isoweekday() == 1
        assert trigger.first_at > MONDAY

    def test_interval_days_arabic(self):
        trigger = parse_trigger("每 3 天核查一次", now=MONDAY)
        assert trigger.interval_value == 3
        assert trigger.interval_unit is IntervalUnit.DAY

    def test_interval_days_chinese(self):
        trigger = parse_trigger("每三天核查一次", now=MONDAY)
        assert trigger.interval_value == 3
        assert trigger.interval_unit is IntervalUnit.DAY

    def test_interval_two_weeks(self):
        trigger = parse_trigger("每两周复核一次资料", now=MONDAY)
        assert trigger.interval_value == 2
        assert trigger.interval_unit is IntervalUnit.WEEK

    def test_monthly(self):
        trigger = parse_trigger("每月归档一次台账", now=MONDAY)
        assert trigger.interval_unit is IntervalUnit.MONTH

    def test_hourly(self):
        trigger = parse_trigger("每2小时巡查一次", now=MONDAY)
        assert trigger.interval_unit is IntervalUnit.HOUR
        assert trigger.interval_value == 2

    def test_vague_periodic_defaults_weekly(self):
        trigger = parse_trigger("定期检查现场安全状况", now=MONDAY)
        assert trigger.run_mode is RunMode.RECURRING
        assert trigger.interval_unit is IntervalUnit.WEEK

    def test_one_off_when_no_period(self):
        trigger = parse_trigger("发现临边防护缺失后发起整改", now=MONDAY)
        assert trigger.run_mode is RunMode.ONCE

    def test_first_at_always_future(self):
        for text in ["每周一巡检", "定期检查", "立即整改隐患"]:
            trigger = parse_trigger(text, now=MONDAY)
            assert trigger.first_at > MONDAY, text


class TestDetectTemplate:
    @pytest.mark.parametrize(
        ("requirement", "expected"),
        [
            ("发现临边防护缺失后发起整改并闭环", "hazard_rectification"),
            ("每周核查基坑监测数据", "periodic_inspection"),
            ("补齐日报缺失资料并由资料员复核", "material_completion"),
            ("风险预警后组织处置", "risk_response"),
            ("提交施工方案并审核", "report_review"),
            ("开工条件验收", "condition_check"),
            ("随便做点什么事情", "generic"),
        ],
    )
    def test_keyword_routing(self, requirement, expected):
        assert detect_template(requirement) == expected


class TestExtractTitle:
    def test_strips_period_prefix(self):
        assert extract_title("每周五检查基坑监测数据") == "检查基坑监测数据"

    def test_cuts_at_punctuation(self):
        title = extract_title("整改现场隐患；然后复核归档")
        assert title == "整改现场隐患"

    def test_handles_plain_text(self):
        assert extract_title("补齐资料") == "补齐资料"

    def test_never_empty(self):
        assert extract_title("每周") != ""


class TestRuleBasedFlow:
    def test_produces_usable_flow(self):
        flow = build_rule_based_flow("每周五检查基坑监测数据并复核归档", now=MONDAY)
        assert flow.origin == "rules"
        assert len(flow.steps) >= 2
        assert flow.trigger.run_mode is RunMode.RECURRING

    def test_assigns_people(self):
        flow = build_rule_based_flow("整改隐患", now=MONDAY, assignees=[ZHANG, LI])
        assert flow.steps[0].assignee == ZHANG

    def test_never_raises_on_odd_input(self):
        """保底路径必须扛住任何输入。"""
        for text in ["？？？", "a", "每每每每", "。。。", "每周每月每天", "12345"]:
            flow = build_rule_based_flow(text, now=MONDAY)
            assert len(flow.steps) >= 2, text

    def test_zero_interval_is_normalized(self):
        """「每0天」是无意义的间隔，应归一为 1 而非抛错。"""
        flow = build_rule_based_flow("每0天检查一次", now=MONDAY)
        assert flow.trigger.interval_value >= 1
        assert len(flow.steps) >= 2

    def test_meige_phrasing(self):
        """「每隔一天」是口语里常见的同义说法。"""
        trigger = parse_trigger("每隔一天巡查现场", now=MONDAY)
        assert trigger.run_mode is RunMode.RECURRING
        assert trigger.interval_unit is IntervalUnit.DAY

    def test_half_month(self):
        """「每半个月」按 15 天处理，比归到「月」更贴近本意。"""
        trigger = parse_trigger("每半个月核查一次资料", now=MONDAY)
        assert trigger.run_mode is RunMode.RECURRING
        assert trigger.interval_unit is IntervalUnit.DAY
        assert trigger.interval_value == 15

    def test_meige_prefix_stripped_from_title(self):
        assert extract_title("每隔一天巡查现场") == "巡查现场"

    def test_origin_note_explains(self):
        flow = build_rule_based_flow("整改隐患", now=MONDAY)
        assert "规则模板" in flow.origin_note


class TestExtractJson:
    def test_plain_json(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_json_with_prose(self):
        assert extract_json('好的，这是结果：{"a": 1} 希望有帮助') == {"a": 1}

    def test_rejects_non_object(self):
        with pytest.raises((ValueError, Exception)):
            extract_json("[1, 2, 3]")


class TestGeneratorFallback:
    def test_without_api_key_uses_rules(self):
        generator = FlowGenerator(LLMConfig(api_key=""))
        flow = generator.generate("每周五检查基坑监测数据", now=MONDAY)
        assert flow.origin == "rules"
        assert flow.trigger.run_mode is RunMode.RECURRING

    def test_model_failure_degrades_gracefully(self):
        # 指向一个不存在的地址，强制失败
        generator = FlowGenerator(
            LLMConfig(api_key="sk-fake", base_url="http://127.0.0.1:1/v1", timeout_seconds=0.5),
        )
        flow = generator.generate("整改现场隐患并闭环", now=MONDAY)
        assert flow.origin == "rules"
        assert "模型暂不可用" in flow.origin_note
        assert len(flow.steps) >= 2  # 用户依然拿到可用的流程

    def test_short_requirement_rejected(self):
        generator = FlowGenerator(LLMConfig(api_key=""))
        with pytest.raises(ValueError, match="太短"):
            generator.generate("整改", now=MONDAY)

    def test_config_from_env(self, monkeypatch):
        monkeypatch.setenv("TASK_ENGINE_AI_KEY", "sk-test")
        monkeypatch.setenv("TASK_ENGINE_AI_MODEL", "custom-model")
        config = LLMConfig.from_env()
        assert config.enabled is True
        assert config.model == "custom-model"


class TestModelOutputValidation:
    """模型输出必须逐字段校验——它可能返回任何东西。"""

    def _convert(self, raw, **kwargs):
        generator = FlowGenerator(LLMConfig(api_key="sk-x"))
        fallback = build_rule_based_flow("整改隐患", now=MONDAY)
        return generator._to_flow(
            raw, requirement="整改隐患", now=MONDAY,
            assignees=kwargs.get("assignees"), confirmer=None, site=None,
            watchers=None, fallback=fallback,
        )

    def test_fabricated_assignee_is_dropped(self):
        flow = self._convert(
            {"title": "x", "steps": [
                {"name": "执行", "assignee_ref": "不存在的人"},
                {"name": "复核", "assignee_ref": "u1"},
            ]},
            assignees=[ZHANG],
        )
        assert flow.steps[0].assignee is None  # 编造的被丢弃
        assert flow.steps[1].assignee == ZHANG

    def test_invalid_category_falls_back(self):
        flow = self._convert({
            "title": "x", "category": "不存在的分类",
            "steps": [{"name": "a"}, {"name": "b"}],
        })
        assert flow.category in {"safety", "quality", "document", "risk", "monitoring", "general"}

    def test_past_first_at_is_replaced(self):
        flow = self._convert({
            "title": "x", "run_mode": "once", "first_at": "2020-01-01 09:00",
            "steps": [{"name": "a"}, {"name": "b"}],
        })
        assert flow.trigger.first_at > MONDAY

    def test_too_few_steps_raises(self):
        with pytest.raises(ValueError, match="节点数量不足"):
            self._convert({"title": "x", "steps": [{"name": "只有一个"}]})

    def test_steps_are_capped(self):
        flow = self._convert({
            "title": "x",
            "steps": [{"name": f"节点{i}"} for i in range(50)],
        })
        assert len(flow.steps) <= 10

    def test_absurd_offset_is_clamped(self):
        flow = self._convert({
            "title": "x",
            "steps": [{"name": "a", "due_offset_days": 99999}, {"name": "b", "due_offset_days": -5}],
        })
        assert flow.steps[0].due_offset_days <= 365
        assert flow.steps[1].due_offset_days >= 1
