"""内置任务流模板。

模板是引擎的"冷启动"能力：不配任何模型也能立刻用起来。这些模板取自工程管理的
常见闭环场景，每个都遵循「执行 → 复核 → 归档」的基本骨架，因为可追溯性要求
任何一次处理都得有人复核、有材料留痕。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.models import Assignee, Site, StepSpec, TaskFlow


@dataclass(frozen=True, slots=True)
class TemplateStep:
    """模板中的一步：名称 + 交付物 + 是否强制留痕。"""

    name: str
    deliverable: str
    requires_attachment: bool = False
    due_offset_days: int = 1


@dataclass(frozen=True, slots=True)
class Template:
    key: str
    label: str
    category: str
    summary: str
    steps: tuple[TemplateStep, ...]


TEMPLATES: tuple[Template, ...] = (
    Template(
        key="hazard_rectification",
        label="隐患整改",
        category="safety",
        summary="发现隐患后派单整改，复核合格并留痕闭环",
        steps=(
            TemplateStep("发现并记录隐患", "隐患记录与现场照片", requires_attachment=True),
            TemplateStep("派单整改", "整改方案", due_offset_days=2),
            TemplateStep("整改完成报验", "整改后照片", requires_attachment=True, due_offset_days=2),
            TemplateStep("安全员复核", "复核意见"),
            TemplateStep("闭环归档", "闭环证明"),
        ),
    ),
    Template(
        key="condition_check",
        label="条件核查",
        category="quality",
        summary="按清单核查作业条件，现场复核后确认放行",
        steps=(
            TemplateStep("发起核查", "核查清单"),
            TemplateStep("现场复核", "现场记录与照片", requires_attachment=True),
            TemplateStep("负责人确认", "确认意见"),
            TemplateStep("核查归档", "闭环资料"),
        ),
    ),
    Template(
        key="material_completion",
        label="资料补全",
        category="document",
        summary="识别缺失资料并补齐，经复核后归档",
        steps=(
            TemplateStep("识别缺失项", "缺失项清单"),
            TemplateStep("补齐资料", "补充资料", requires_attachment=True, due_offset_days=3),
            TemplateStep("资料复核", "复核意见"),
            TemplateStep("归档入库", "完整资料包"),
        ),
    ),
    Template(
        key="risk_response",
        label="风险处置",
        category="risk",
        summary="风险触发后复核数据、处置并关闭",
        steps=(
            TemplateStep("风险触发确认", "风险依据"),
            TemplateStep("数据复核", "监测或核验数据", requires_attachment=True),
            TemplateStep("制定处置措施", "处置方案"),
            TemplateStep("处置执行", "执行记录", requires_attachment=True, due_offset_days=2),
            TemplateStep("风险关闭确认", "关闭依据"),
        ),
    ),
    Template(
        key="report_review",
        label="报告审核",
        category="document",
        summary="提交报告后逐级审核，修订至定稿",
        steps=(
            TemplateStep("提交报告", "报告文件", requires_attachment=True),
            TemplateStep("依据审核", "审核意见", due_offset_days=2),
            TemplateStep("问题修订", "修订稿", due_offset_days=2),
            TemplateStep("审核通过", "定稿文件"),
        ),
    ),
    Template(
        key="periodic_inspection",
        label="周期巡检",
        category="monitoring",
        summary="按周期巡检并记录，异常时上报处理",
        steps=(
            TemplateStep("执行巡检", "巡检记录与照片", requires_attachment=True),
            TemplateStep("数据汇总分析", "分析结论"),
            TemplateStep("异常上报处理", "处理意见"),
            TemplateStep("巡检归档", "巡检报告"),
        ),
    ),
    Template(
        key="generic",
        label="通用流程",
        category="general",
        summary="发起、执行、复核、归档的通用四段式",
        steps=(
            TemplateStep("发起任务", "任务依据"),
            TemplateStep("执行处理", "过程资料", requires_attachment=True, due_offset_days=2),
            TemplateStep("复核确认", "复核意见"),
            TemplateStep("闭环归档", "闭环资料"),
        ),
    ),
)

TEMPLATES_BY_KEY: dict[str, Template] = {tpl.key: tpl for tpl in TEMPLATES}
# 中文标签也可作为入口，方便自然语言调用
TEMPLATES_BY_LABEL: dict[str, Template] = {tpl.label: tpl for tpl in TEMPLATES}


def find_template(key_or_label: str) -> Template | None:
    return TEMPLATES_BY_KEY.get(key_or_label) or TEMPLATES_BY_LABEL.get(key_or_label)


def build_from_template(
    key_or_label: str,
    *,
    title: str = "",
    assignees: list[Assignee] | None = None,
    confirmer: Assignee | None = None,
    site: Site | None = None,
    watchers: list[Assignee] | None = None,
) -> TaskFlow:
    """由模板生成任务流。

    `assignees` 按顺序轮流分配给各节点；为空时节点保持待指定。
    模板阶段允许留空，但布置成真实任务前必须补齐责任人、确认人与工点
    （由 TaskFlow.require_dispatchable() 校验）。
    """
    template = find_template(key_or_label)
    if template is None:
        available = "、".join(f"{t.key}({t.label})" for t in TEMPLATES)
        raise KeyError(f"未知模板：{key_or_label}。可用模板：{available}")

    people = assignees or []
    steps = tuple(
        StepSpec(
            name=step.name,
            assignee=people[index % len(people)] if people else None,
            due_offset_days=step.due_offset_days,
            deliverable=step.deliverable,
            requires_attachment=step.requires_attachment,
        )
        for index, step in enumerate(template.steps)
    )

    return TaskFlow(
        title=title or template.label,
        steps=steps,
        summary=template.summary,
        category=template.category,
        site=site,
        confirmer=confirmer,
        watchers=tuple(watchers or ()),
        origin="template",
        origin_note=f"由「{template.label}」模板生成 {len(steps)} 个节点，可继续调整",
    )


def list_templates() -> list[dict[str, object]]:
    """列出所有模板，供 MCP 工具返回给调用方选择。"""
    return [
        {
            "key": tpl.key,
            "label": tpl.label,
            "category": tpl.category,
            "summary": tpl.summary,
            "step_count": len(tpl.steps),
            "steps": [step.name for step in tpl.steps],
        }
        for tpl in TEMPLATES
    ]
