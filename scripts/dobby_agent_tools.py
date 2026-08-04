"""AgentScope tools backed by Dobby's session-bound internal gateway."""

import asyncio
import json
import logging
import os
from typing import Any

import httpx

from agentscope.app._types import AgentToolDescriptor
from agentscope.message import TextBlock, ToolResultState
from agentscope.permission import (
    PermissionBehavior,
    PermissionContext,
    PermissionDecision,
)
from agentscope.tool import ToolBase, ToolChunk

from scripts.initialization_file_parser import (
    parse_initialization_file as _parse_initialization_file,
)


logger = logging.getLogger(__name__)

_DEFAULT_GATEWAY_URL = (
    "http://127.0.0.1:38430/api/internal/agent-tools"
)

_INITIALIZATION_WORKER_READ_TOOL_NAMES = {
    "dobby_get_project_initialization_state",
    "dobby_get_project_initialization_draft",
    "dobby_read_project_initialization_artifact",
}

_TOOL_DISPLAY_NAMES = {
    "dobby_get_project_overview": "项目概览",
    "dobby_list_project_items": "项目数据查询",
    "dobby_search_documents": "工程资料搜索",
    "dobby_get_project_initialization_state": "初始化状态",
    "dobby_get_project_initialization_draft": "读取初始化草稿",
    "dobby_read_project_initialization_artifact": "读取标准化资料",
    "dobby_begin_project_initialization_normalization": "开始附件标准化",
    "dobby_write_project_initialization_artifact": "写入标准化资料",
    "dobby_finalize_project_initialization_normalization": "完成附件标准化",
    "dobby_begin_project_initialization_draft": "创建初始化草稿",
    "dobby_write_project_initialization_draft_section": "写入初始化分区",
    "dobby_import_project_initialization_artifact": "导入初始化分区",
    "dobby_finalize_project_initialization_draft": "完成初始化核验",
    "dobby_read_project_initialization_file": "读取初始化附件",
    "dobby_create_task": "创建项目任务",
    "dobby_update_task": "更新项目任务",
    "dobby_dispose_information": "处置项目信息",
    "dobby_create_project_change": "登记项目变更",
    "dobby_update_document_category": "修改资料分类",
    "dobby_create_risk": "新增风险源",
    "dobby_update_wbs_progress": "更新 WBS 进度",
}


READ_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "dobby_get_project_overview",
        "operation": "get_project_overview",
        "description": (
            "读取当前平台会话所绑定项目的概览、当前账号身份、进度摘要和"
            "任务/风险/资料数量。项目和账号由平台会话自动确定，不能跨项目。"
            "在回答项目现状、准备执行写操作或不确定当前权限时应优先调用。"
        ),
        "schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "dobby_list_project_items",
        "operation": "list_project_items",
        "description": (
            "读取当前项目的结构化业务数据。可查询任务、WBS 工序、风险源、"
            "质量指标、项目成员、最新信息、项目变更、通知、工程资料和日报。"
            "仅返回当前会话账号有权访问的项目数据。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "resource": {
                    "type": "string",
                    "enum": [
                        "tasks",
                        "wbs",
                        "risks",
                        "quality",
                        "members",
                        "information",
                        "changes",
                        "notifications",
                        "documents",
                        "daily_reports",
                    ],
                    "description": "要读取的业务资源类型。",
                },
                "keyword": {
                    "type": ["string", "null"],
                    "description": "可选关键词，用于名称或内容筛选。",
                    "maxLength": 200,
                },
                "status": {
                    "type": ["string", "null"],
                    "description": (
                        "可选状态筛选；查询 documents 时代表资料分类，"
                        "查询 notifications 时可用 read/unread。"
                    ),
                    "maxLength": 64,
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 50,
                },
            },
            "required": ["resource"],
            "additionalProperties": False,
        },
    },
    {
        "name": "dobby_search_documents",
        "operation": "search_documents",
        "description": (
            "按关键词检索当前项目已经归档的资料名称和已提取正文，返回命中"
            "文件及短摘要。此工具检索 Dobby 平台工程资料；AgentScope 知识库"
            "内容应使用 search_knowledge。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                    "description": "资料检索关键词。",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 20,
                },
            },
            "required": ["keyword"],
            "additionalProperties": False,
        },
    },
)


INITIALIZATION_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "dobby_get_project_initialization_state",
        "operation": "get_project_initialization_state",
        "description": (
            "读取当前项目已经正式入库的工程基本信息、人员、WBS、风险源、"
            "工序质量指标及最新初始化草稿摘要。此工具不返回草稿 payload；"
            "latest_draft 不为空时，必须继续调用草稿读取工具取得相关分区，"
            "不能把正式表为空解释成草稿为空。项目名称只读，不能由初始化"
            "智能体修改。"
        ),
        "schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
)


_INITIALIZATION_PAYLOAD_SCHEMA: dict[str, Any] = {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "object",
                            "description": "项目名称不在此对象中，名称不可修改。",
                            "properties": {
                                "engineering_type_description": {"type": ["string", "null"]},
                                "contract_start_date": {"type": ["string", "null"], "format": "date"},
                                "contract_end_date": {"type": ["string", "null"], "format": "date"},
                                "contract_duration_days": {"type": ["integer", "null"], "minimum": 1},
                                "contract_amount_wan_yuan": {"type": ["number", "null"], "minimum": 0},
                                "construction_unit_name": {"type": ["string", "null"]},
                                "general_contractor_unit_name": {"type": ["string", "null"]},
                                "supervision_unit_name": {"type": ["string", "null"]},
                                "design_unit_name": {"type": ["string", "null"]},
                                "survey_unit_name": {"type": ["string", "null"]},
                            },
                            "additionalProperties": False,
                        },
                        "personnel": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "serial_no": {"type": "integer", "minimum": 1},
                                    "real_name": {"type": "string"},
                                    "identity_card_no": {"type": "string"},
                                    "position_name": {"type": "string"},
                                    "certificate_no": {"type": "string"},
                                    "responsibility_description": {"type": "string"},
                                },
                                "required": [
                                    "serial_no",
                                    "real_name",
                                    "identity_card_no",
                                    "position_name",
                                    "certificate_no",
                                    "responsibility_description",
                                ],
                                "additionalProperties": False,
                            },
                        },
                        "wbs": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "wbs_code": {"type": "string"},
                                    "parent_wbs_code": {
                                        "type": ["string", "null"],
                                        "description": (
                                            "仅按点分 WBS 编码的直接前缀确定；"
                                            "根节点传 null，不得填写“顶级 WBS”"
                                            "等说明文字。"
                                        ),
                                    },
                                    "predecessor_wbs_codes": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": (
                                            "只填写附件或用户明确给出的前置 WBS"
                                            " 编码；未明确提供时传空数组，禁止按"
                                            "编码顺序、名称或日期推断。"
                                        ),
                                    },
                                    "sort_order": {"type": "integer", "minimum": 0},
                                    "color_value": {"type": ["string", "null"]},
                                    "name": {"type": "string"},
                                    "assigned_to_text": {"type": ["string", "null"]},
                                    "planned_start_at": {"type": ["string", "null"], "format": "date-time"},
                                    "planned_finish_at": {"type": ["string", "null"], "format": "date-time"},
                                    "deadline_at": {"type": ["string", "null"], "format": "date-time"},
                                    "progress_percent": {
                                        "type": ["number", "null"],
                                        "minimum": 0,
                                        "maximum": 100,
                                        "description": (
                                            "附件单元格为 0 时必须传 0；只有原始"
                                            "单元格为空时才传 null。"
                                        ),
                                    },
                                    "duration_hours": {"type": ["number", "null"], "minimum": 0},
                                    "estimated_hours": {"type": ["number", "null"], "minimum": 0},
                                    "time_log_minutes": {"type": ["integer", "null"], "minimum": 0},
                                    "status_text": {"type": ["string", "null"]},
                                    "priority_text": {"type": ["string", "null"]},
                                    "description": {"type": ["string", "null"]},
                                    "budget": {"type": ["number", "null"], "minimum": 0},
                                    "actual_cost": {"type": ["number", "null"], "minimum": 0},
                                    "msp_uid": {"type": ["string", "null"]},
                                    "msp_id": {"type": ["string", "null"]},
                                    "source_created_at": {"type": ["string", "null"], "format": "date-time"},
                                    "source_creator": {"type": ["string", "null"]},
                                    "item_type": {"type": ["string", "null"]},
                                    "source_project_path": {"type": ["string", "null"]},
                                    "level": {
                                        "type": "integer",
                                        "minimum": 1,
                                        "description": "WBS 点分编码的段数。",
                                    },
                                },
                                "required": [
                                    "wbs_code",
                                    "parent_wbs_code",
                                    "name",
                                    "planned_start_at",
                                    "planned_finish_at",
                                    "progress_percent",
                                    "status_text",
                                    "priority_text",
                                    "level",
                                ],
                                "additionalProperties": False,
                            },
                        },
                        "risks": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "serial_no": {"type": "integer", "minimum": 1},
                                    "related_process_name": {"type": "string"},
                                    "risk_part": {"type": "string"},
                                    "risk_level": {"type": "string"},
                                    "evaluation_condition": {"type": "string"},
                                    "risk_window_start_date": {"type": ["string", "null"], "format": "date"},
                                    "risk_window_end_date": {"type": ["string", "null"], "format": "date"},
                                    "summary": {"type": ["string", "null"]},
                                },
                                "required": [
                                    "serial_no",
                                    "related_process_name",
                                    "risk_part",
                                    "risk_level",
                                    "evaluation_condition",
                                ],
                                "additionalProperties": False,
                            },
                        },
                        "quality_requirements": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "wbs_code": {"type": "string"},
                                    "quality_acceptance_item": {"type": "string"},
                                    "control_indicator": {"type": "string"},
                                    "inspection_frequency": {"type": "string"},
                                    "related_documents": {"type": "string"},
                                },
                                "required": [
                                    "wbs_code",
                                    "quality_acceptance_item",
                                    "control_indicator",
                                    "inspection_frequency",
                                    "related_documents",
                                ],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": [
                        "project",
                        "personnel",
                        "wbs",
                        "risks",
                        "quality_requirements",
                    ],
                    "additionalProperties": False,
}

INITIALIZATION_TOOL_DEFINITIONS += (
    {
        "name": "dobby_get_project_initialization_draft",
        "operation": "get_project_initialization_draft",
        "description": (
            "读取当前初始化会话最新草稿的完整结构化数据。必须按分区读取；"
            "WBS、人员、风险、质量和校验结果支持 start/limit 分页。补充已有"
            "草稿前，先读取本次所需分区；不得因为正式业务表尚未入库就重新"
            "解析全部旧附件。草稿中的 WBS 可以用于匹配新增质量指标；风险源"
            "不关联 WBS。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "enum": [
                        "project",
                        "personnel",
                        "wbs",
                        "risks",
                        "quality_requirements",
                        "validation_issues",
                    ],
                    "description": "需要读取的草稿分区。",
                },
                "start": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 1,
                    "description": "数组分区从 1 开始的起始记录。",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 100,
                    "description": "本次最多返回的记录数。",
                },
            },
            "required": ["section"],
            "additionalProperties": False,
        },
    },
    {
        "name": "dobby_read_project_initialization_artifact",
        "operation": "read_project_initialization_artifact",
        "description": (
            "读取初始化主智能体已经整理并通过校验的标准资料。先不传 "
            "part_index 读取分片清单，再按分片分页读取 JSON 记录或 "
            "Markdown 行；读取指定分片时必须同时传 artifact_format。"
            "专项智能体只能读取这里的标准资料，不得重新读取原始附件。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "normalization_id": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "初始化主智能体完成的标准化批次 ID。",
                },
                "section": {
                    "type": "string",
                    "enum": [
                        "project",
                        "personnel",
                        "wbs",
                        "risks",
                        "quality_requirements",
                    ],
                    "description": "要读取的标准资料业务分区。",
                },
                "part_index": {
                    "type": ["integer", "null"],
                    "minimum": 1,
                    "description": "不填时返回分片清单，填写后返回该分片内容。",
                },
                "artifact_format": {
                    "type": ["string", "null"],
                    "enum": ["json", "markdown", None],
                    "description": (
                        "读取指定 part_index 时必填，避免同编号 JSON 与 "
                        "Markdown 混淆。"
                    ),
                },
                "start": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 1,
                    "description": "JSON 数组记录或 Markdown 行的起始位置。",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 100,
                    "description": "本次最多读取的记录数或行数。",
                },
            },
            "required": ["normalization_id", "section"],
            "additionalProperties": False,
        },
    },
)

_INITIALIZATION_READ_TOOL_DEFINITIONS = tuple(
    definition
    for definition in INITIALIZATION_TOOL_DEFINITIONS
    if definition["name"] in _INITIALIZATION_WORKER_READ_TOOL_NAMES
)


def _canonical_record_schema(
    title: str,
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "title": title,
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


_PROJECT_ARTIFACT_SCHEMA = _canonical_record_schema(
    "工程基本信息对象",
    {
        "engineering_type_description": {
            "type": ["string", "null"],
            "maxLength": 10000,
        },
        "contract_start_date": {
            "type": ["string", "null"],
            "format": "date",
        },
        "contract_end_date": {
            "type": ["string", "null"],
            "format": "date",
        },
        "contract_duration_days": {
            "type": ["integer", "null"],
            "minimum": 1,
        },
        "contract_amount_wan_yuan": {
            "type": ["number", "string", "null"],
        },
        "construction_unit_name": {"type": ["string", "null"]},
        "general_contractor_unit_name": {"type": ["string", "null"]},
        "supervision_unit_name": {"type": ["string", "null"]},
        "design_unit_name": {"type": ["string", "null"]},
        "survey_unit_name": {"type": ["string", "null"]},
    },
    [],
)

_PERSONNEL_ARTIFACT_SCHEMA = _canonical_record_schema(
    "人员任职记录",
    {
        "serial_no": {"type": "integer", "minimum": 1},
        "real_name": {"type": "string", "minLength": 1},
        "identity_card_no": {"type": "string", "minLength": 1},
        "position_name": {"type": "string", "minLength": 1},
        "certificate_no": {"type": "string", "minLength": 1},
        "responsibility_description": {"type": "string", "minLength": 1},
    },
    [
        "serial_no",
        "real_name",
        "identity_card_no",
        "position_name",
        "certificate_no",
        "responsibility_description",
    ],
)

_WBS_ARTIFACT_SCHEMA = _canonical_record_schema(
    "WBS 记录",
    {
        "wbs_code": {"type": "string", "minLength": 1},
        "parent_wbs_code": {"type": ["string", "null"]},
        "predecessor_wbs_codes": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 100,
        },
        "sort_order": {"type": "integer", "minimum": 0},
        "color_value": {"type": ["string", "null"]},
        "name": {"type": "string", "minLength": 1},
        "assigned_to_text": {"type": ["string", "null"]},
        "planned_start_at": {"type": ["string", "null"]},
        "planned_finish_at": {"type": ["string", "null"]},
        "deadline_at": {"type": ["string", "null"]},
        "progress_percent": {
            "type": ["number", "string", "null"],
        },
        "duration_hours": {"type": ["number", "string", "null"]},
        "estimated_hours": {"type": ["number", "string", "null"]},
        "time_log_minutes": {"type": ["integer", "null"]},
        "status_text": {"type": ["string", "null"]},
        "priority_text": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        "budget": {"type": ["number", "string", "null"]},
        "actual_cost": {"type": ["number", "string", "null"]},
        "msp_uid": {"type": ["string", "null"]},
        "msp_id": {"type": ["string", "null"]},
        "source_created_at": {"type": ["string", "null"]},
        "source_creator": {"type": ["string", "null"]},
        "item_type": {"type": ["string", "null"]},
        "source_project_path": {"type": ["string", "null"]},
        "level": {"type": "integer", "minimum": 1},
    },
    [
        "wbs_code",
        "parent_wbs_code",
        "name",
        "planned_start_at",
        "planned_finish_at",
        "progress_percent",
        "status_text",
        "priority_text",
        "level",
    ],
)

_RISK_ARTIFACT_SCHEMA = _canonical_record_schema(
    "风险源记录",
    {
        "serial_no": {"type": "integer", "minimum": 1},
        "related_process_name": {"type": "string", "minLength": 1},
        "risk_part": {"type": "string", "minLength": 1},
        "risk_level": {"type": "string", "minLength": 1},
        "evaluation_condition": {"type": "string", "minLength": 1},
        "risk_window_start_date": {
            "type": ["string", "null"],
            "format": "date",
        },
        "risk_window_end_date": {
            "type": ["string", "null"],
            "format": "date",
        },
        "summary": {"type": ["string", "null"]},
    },
    [
        "serial_no",
        "related_process_name",
        "risk_part",
        "risk_level",
        "evaluation_condition",
    ],
)

_QUALITY_ARTIFACT_SCHEMA = _canonical_record_schema(
    "质量指标记录",
    {
        "wbs_code": {"type": "string", "minLength": 1},
        "quality_acceptance_item": {"type": "string", "minLength": 1},
        "control_indicator": {"type": "string", "minLength": 1},
        "inspection_frequency": {"type": "string", "minLength": 1},
        "related_documents": {"type": "string", "minLength": 1},
    },
    [
        "wbs_code",
        "quality_acceptance_item",
        "control_indicator",
        "inspection_frequency",
        "related_documents",
    ],
)

_INITIALIZATION_ARTIFACT_JSON_SCHEMA: dict[str, Any] = {
    "anyOf": [
        _PROJECT_ARTIFACT_SCHEMA,
        *[
            {
                "title": title,
                "type": "array",
                "minItems": 1,
                "maxItems": 20,
                "items": item_schema,
            }
            for title, item_schema in (
                ("人员记录数组", _PERSONNEL_ARTIFACT_SCHEMA),
                ("WBS 记录数组", _WBS_ARTIFACT_SCHEMA),
                ("风险源记录数组", _RISK_ARTIFACT_SCHEMA),
                ("质量指标记录数组", _QUALITY_ARTIFACT_SCHEMA),
            )
        ],
    ],
    "description": (
        "必须与 section 对应。工程信息为一个对象；其他分区为数组。"
        "数组第 1 部分必须只提交 1 条试写记录，成功后后续每部分最多 20 条。"
        "只能使用这里声明的标准字段，禁止自造别名。"
    ),
}


INITIALIZATION_ORCHESTRATOR_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "dobby_begin_project_initialization_normalization",
        "operation": "begin_project_initialization_normalization",
        "description": (
            "在读取本轮原始附件前建立标准化批次。只有初始化主智能体可以"
            "调用。复杂附件必须先完成本批次的读取、拆分、标准资料写入和"
            "校验，之后才能创建计划、团队或邀请专项智能体。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "source_file_ids": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                    "maxItems": 100,
                    "uniqueItems": True,
                    "description": "本轮需要读取和标准化的原始附件 ID。",
                },
            },
            "required": ["source_file_ids"],
            "additionalProperties": False,
        },
    },
    {
        "name": "dobby_write_project_initialization_artifact",
        "operation": "write_project_initialization_artifact",
        "description": (
            "把主智能体从任意原始附件中整理出的单个业务分区写成标准 JSON "
            "或 Markdown。结构化入库数据必须写成符合平台字段规范的 JSON；"
            "Markdown 只用于叙述、证据或补充说明。除工程信息外，每个分区"
            "第一次必须用 part_index=1 且只提交 1 条记录试写；收到 "
            "probe_accepted 后，才从 part_index=2 起按每批最多 20 条连续"
            "写入。单个分片最多 64KB，禁止把不同业务分区混在同一份资料中。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "normalization_id": {
                    "type": "integer",
                    "minimum": 1,
                },
                "section": {
                    "type": "string",
                    "enum": [
                        "project",
                        "personnel",
                        "wbs",
                        "risks",
                        "quality_requirements",
                    ],
                },
                "artifact_format": {
                    "type": "string",
                    "enum": ["json", "markdown"],
                },
                "part_index": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                    "default": 1,
                },
                "file_name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 300,
                    "description": "仅文件名；格式为 json 时使用 .json 后缀。",
                },
                "json_data": {
                    **_INITIALIZATION_ARTIFACT_JSON_SCHEMA,
                },
                "markdown_content": {
                    "type": ["string", "null"],
                    "maxLength": 65536,
                    "description": "Markdown 格式时提供。",
                },
                "source_file_ids": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                    "maxItems": 100,
                    "uniqueItems": True,
                },
                "source_locations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 1000,
                    "description": "来源工作表、行号、页码或文档段落。",
                },
            },
            "required": [
                "normalization_id",
                "section",
                "artifact_format",
                "part_index",
                "file_name",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "dobby_finalize_project_initialization_normalization",
        "operation": "finalize_project_initialization_normalization",
        "description": (
            "校验并封存本轮标准资料。每个待入草稿的业务分区都必须有可直接"
            "批量导入的规范 JSON；所有分片完整且字段合法后才会返回 ready。"
            "只有返回 ready 后，才允许创建执行计划、团队和草稿任务。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "normalization_id": {
                    "type": "integer",
                    "minimum": 1,
                },
                "expected_sections": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "project",
                            "personnel",
                            "wbs",
                            "risks",
                            "quality_requirements",
                        ],
                    },
                    "minItems": 1,
                    "maxItems": 5,
                    "uniqueItems": True,
                },
            },
            "required": ["normalization_id", "expected_sections"],
            "additionalProperties": False,
        },
    },
    {
        "name": "dobby_begin_project_initialization_draft",
        "operation": "begin_project_initialization_draft",
        "description": (
            "使用已经 ready 的标准化批次建立本轮草稿任务。只有初始化主"
            "智能体可以调用；不得跳过标准化直接建立草稿。工具会返回 "
            "draft_id 和待完成分区，之后再邀请对应持久化专项智能体。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "normalization_id": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "已经完成并通过校验的标准化批次 ID。",
                },
                "expected_sections": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "project",
                            "personnel",
                            "wbs",
                            "risks",
                            "quality_requirements",
                        ],
                    },
                    "minItems": 1,
                    "maxItems": 5,
                    "uniqueItems": True,
                    "description": "本轮附件或问答实际涉及、必须重新完成的分区。",
                },
                "source_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 100,
                    "description": "本轮使用的附件文件名。",
                },
            },
            "required": ["normalization_id", "expected_sections"],
            "additionalProperties": False,
        },
    },
)


def _initialization_section_writer_definition(
    section: str,
) -> dict[str, Any]:
    labels = {
        "project": "工程基本信息",
        "personnel": "人员与岗位",
        "wbs": "WBS 与进度",
        "risks": "风险源",
        "quality_requirements": "质量指标",
    }
    return {
        "name": "dobby_write_project_initialization_draft_section",
        "operation": "write_project_initialization_draft_section",
        "description": (
            f"将完整的{labels[section]}识别结果直接写入自己唯一拥有的草稿"
            "分区。该工具不会写正式业务表，也不能修改其他专家的分区。"
            "写入前应读取已有同名草稿分区；补充新附件时合并已有有效记录后"
            "整体替换本分区。完成写入后只需通过 TeamSay 向负责人报告简短"
            "状态，不要在团队消息中复制整批结构化数据。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "draft_id": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "初始化主智能体建立任务后返回的草稿 ID。",
                },
                "data": _INITIALIZATION_PAYLOAD_SCHEMA["properties"][section],
                "source_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 100,
                    "description": "本分区实际读取的附件文件名。",
                },
                "extraction_notes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 200,
                    "description": (
                        "来源位置、无法确定项和原文冲突等简短证据说明；"
                        "不得在这里改写结构化数据。"
                    ),
                },
            },
            "required": ["draft_id", "data"],
            "additionalProperties": False,
        },
    }


def _initialization_artifact_import_definition(
    section: str,
) -> dict[str, Any]:
    labels = {
        "project": "工程基本信息",
        "personnel": "人员与岗位",
        "wbs": "WBS 与进度",
        "risks": "风险源",
        "quality_requirements": "质量指标",
    }
    return {
        "name": "dobby_import_project_initialization_artifact",
        "operation": "import_project_initialization_artifact",
        "description": (
            f"把主智能体已标准化并通过校验的{labels[section]} JSON 分片"
            "一次性批量导入当前专家唯一拥有的草稿分区。后端负责合并分片"
            "和结构校验，不要在工具参数中重新生成或复制整批 JSON。调用前"
            "先用标准资料读取工具核对清单和必要内容。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "draft_id": {
                    "type": "integer",
                    "minimum": 1,
                },
                "normalization_id": {
                    "type": "integer",
                    "minimum": 1,
                },
                "extraction_notes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 200,
                    "description": "专项核对结论或需交给统一核验的简短说明。",
                },
            },
            "required": ["draft_id", "normalization_id"],
            "additionalProperties": False,
        },
    }


INITIALIZATION_SPECIALIST_TOOL_DEFINITIONS: dict[
    str,
    tuple[dict[str, Any], ...],
] = {
    section: (
        _initialization_artifact_import_definition(section),
        _initialization_section_writer_definition(section),
    )
    for section in (
        "project",
        "personnel",
        "wbs",
        "risks",
        "quality_requirements",
    )
}

INITIALIZATION_VALIDATOR_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "dobby_finalize_project_initialization_draft",
        "operation": "finalize_project_initialization_draft",
        "description": (
            "在所有本轮专项分区写入完成后，提交独立语义核验结论并完成草稿"
            "汇总。平台会重新执行确定性结构、关联和时间规则校验，再把语义"
            "问题合并进核对清单。只有初始化核验智能体可以调用；不得代替"
            "专项智能体提取附件。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "draft_id": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "待核验的草稿 ID。",
                },
                "semantic_issues": {
                    "type": "array",
                    "maxItems": 500,
                    "items": {
                        "type": "object",
                        "properties": {
                            "level": {
                                "type": "string",
                                "enum": ["error", "warning"],
                            },
                            "path": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 300,
                            },
                            "message": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 2000,
                            },
                        },
                        "required": ["level", "path", "message"],
                        "additionalProperties": False,
                    },
                    "description": (
                        "只提交规则引擎难以确定的跨专业语义问题；"
                        "没有额外问题时传空数组。"
                    ),
                },
                "review_summary": {
                    "type": ["string", "null"],
                    "maxLength": 10000,
                    "description": "面向初始化主智能体的简短核验摘要。",
                },
            },
            "required": ["draft_id", "semantic_issues"],
            "additionalProperties": False,
        },
    },
)


INITIALIZATION_FILE_TOOL_DEFINITION: dict[str, Any] = {
    "name": "dobby_read_project_initialization_file",
    "description": (
        "读取并解析当前项目初始化会话中已上传的原始附件。平台只负责授权"
        "和传输原始文件；XLS/XLSX、DOCX、PPTX、PDF、图片、CSV、"
        "TXT/Markdown 的结构化解析及本地 OCR 在 AgentScope 进程内完成。"
        "先用初始化状态工具取得 file_id；大文件应按 start 和 limit 分段"
        "读取，表格文件可通过 sheet_name 指定工作表。"
    ),
    "schema": {
        "type": "object",
        "properties": {
            "file_id": {
                "type": "integer",
                "description": "初始化状态中返回的附件 ID。",
            },
            "sheet_name": {
                "type": ["string", "null"],
                "description": (
                    "读取 XLS/XLSX 时指定工作表；不填则读取第一张表。"
                ),
            },
            "start": {
                "type": "integer",
                "minimum": 1,
                "default": 1,
                "description": "起始行、页或文档块，均从 1 开始。",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 500,
                "default": 100,
                "description": "本次最多返回的行、页或文档块数量。",
            },
            "ocr_mode": {
                "type": "string",
                "enum": ["auto", "always", "never"],
                "default": "auto",
                "description": (
                    "本地 OCR 策略。auto 仅识别图片或缺少文本层的 PDF；"
                    "always 强制识别；never 跳过 OCR。"
                ),
            },
        },
        "required": ["file_id"],
        "additionalProperties": False,
    },
}


WRITE_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "dobby_create_task",
        "operation": "create_task",
        "description": (
            "在当前项目创建一条真实任务，并写入审计记录。调用前应先查询成员、"
            "WBS 和风险源，引用的 ID 必须属于当前项目。不要把“建议创建”当作"
            "已经创建；只有工具成功返回后才能向用户确认完成。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "minLength": 1, "maxLength": 300},
                "task_type": {
                    "type": "string",
                    "enum": [
                        "risk_alert",
                        "material_missing",
                        "daily_confirm",
                        "draft_review",
                        "fill_platform",
                    ],
                    "default": "risk_alert",
                },
                "risk_level": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "default": "low",
                },
                "assignee_user_id": {"type": ["integer", "null"]},
                "confirmer_user_id": {"type": ["integer", "null"]},
                "due_at": {
                    "type": ["string", "null"],
                    "description": "截止日期或时间，推荐 ISO 格式。",
                },
                "wbs_item_id": {"type": ["integer", "null"]},
                "risk_source_id": {"type": ["integer", "null"]},
                "trigger_reason": {
                    "type": ["string", "null"],
                    "maxLength": 2000,
                },
                "required_materials": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 30,
                    "default": [],
                },
            },
            "required": ["title"],
            "additionalProperties": False,
        },
    },
    {
        "name": "dobby_update_task",
        "operation": "update_task",
        "description": (
            "更新当前项目的真实任务：状态流转、转交、添加处置说明或更新流程"
            "步骤。必须先读取任务当前状态；工具会执行合法流转和项目成员校验。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "action": {
                    "type": "string",
                    "enum": [
                        "transition",
                        "reassign",
                        "add_note",
                        "update_step",
                    ],
                },
                "status": {
                    "type": ["string", "null"],
                    "description": "状态流转或步骤更新时的新状态。",
                },
                "assignee_user_id": {"type": ["integer", "null"]},
                "step_index": {
                    "type": ["integer", "null"],
                    "minimum": 0,
                    "description": "更新流程步骤时使用，从 0 开始。",
                },
                "note": {"type": ["string", "null"], "maxLength": 2000},
            },
            "required": ["task_id", "action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "dobby_dispose_information",
        "operation": "dispose_information",
        "description": (
            "确认、否认或修订当前项目的一条最新信息记录，并写入审计日志。"
            "修订时必须提供 content。执行前先读取原记录和可用依据。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "record_id": {"type": "integer"},
                "action": {
                    "type": "string",
                    "enum": ["confirm", "deny", "revise"],
                },
                "content": {"type": ["string", "null"], "maxLength": 10000},
            },
            "required": ["record_id", "action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "dobby_create_project_change",
        "operation": "create_project_change",
        "description": (
            "在当前项目登记一条待审核的项目变更，并保留来源引用和审计记录。"
            "仅用于已有事实或用户明确要求登记的变更，不得自行编造变更事实。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 100,
                    "default": "工程内容变更",
                },
                "title": {"type": "string", "minLength": 1, "maxLength": 300},
                "content": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 10000,
                },
                "source_refs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 30,
                    "default": [],
                },
            },
            "required": ["title", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "dobby_update_document_category",
        "operation": "update_document_category",
        "description": (
            "修改当前项目一份已归档资料的分类，并写入审计记录。先查询资料 ID，"
            "仅在用户要求或分类依据充分时执行。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "attachment_id": {"type": "integer"},
                "category": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 100,
                },
            },
            "required": ["attachment_id", "category"],
            "additionalProperties": False,
        },
    },
)


ADMIN_WRITE_TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "dobby_create_risk",
        "operation": "create_risk",
        "description": (
            "以当前平台管理员身份在当前项目新增真实风险源，并写入审计记录。"
            "这是管理员级写操作；相关工序按风险清单原文填写，并核验风险窗口。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "serial_no": {"type": "integer", "minimum": 1},
                "related_process_name": {"type": "string", "minLength": 1, "maxLength": 300},
                "risk_part": {"type": "string", "minLength": 1, "maxLength": 300},
                "risk_level": {"type": "string", "minLength": 1, "maxLength": 50},
                "evaluation_condition": {"type": "string", "minLength": 1, "maxLength": 20000},
                "risk_window_start_date": {"type": ["string", "null"], "format": "date"},
                "risk_window_end_date": {"type": ["string", "null"], "format": "date"},
                "summary": {"type": ["string", "null"], "maxLength": 20000},
            },
            "required": [
                "serial_no",
                "related_process_name",
                "risk_part",
                "risk_level",
                "evaluation_condition",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "dobby_update_wbs_progress",
        "operation": "update_wbs_progress",
        "description": (
            "以当前平台管理员身份更新当前项目 WBS 工序的真实进度和状态，"
            "并写入审计记录。必须先读取工序现状和进度依据。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "wbs_item_id": {"type": "integer"},
                "progress_percent": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 100,
                },
                "status_text": {"type": ["string", "null"], "maxLength": 100},
                "note": {"type": ["string", "null"], "maxLength": 1000},
            },
            "required": ["wbs_item_id", "progress_percent"],
            "additionalProperties": False,
        },
    },
)


class DobbyInitializationFileTool(ToolBase):
    """AgentScope-side parser for raw, session-authorized platform files."""

    name = str(INITIALIZATION_FILE_TOOL_DEFINITION["name"])
    description = str(INITIALIZATION_FILE_TOOL_DEFINITION["description"])
    input_schema = dict(INITIALIZATION_FILE_TOOL_DEFINITION["schema"])
    is_concurrency_safe = False
    is_external_tool = False
    is_state_injected = False
    is_mcp = False
    is_read_only = True

    def __init__(
        self,
        session_id: str,
        base_url: str,
        token: str,
    ) -> None:
        super().__init__()
        self._session_id = session_id
        self._base_url = base_url.rstrip("/")
        self._token = token

    async def check_permissions(
        self,
        tool_input: dict[str, Any],
        context: PermissionContext,
    ) -> PermissionDecision:
        del tool_input, context
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="该工具只读取当前初始化会话已授权的原始附件。",
        )

    async def call(
        self,
        file_id: int,
        sheet_name: str | None = None,
        start: int = 1,
        limit: int = 100,
        ocr_mode: str = "auto",
    ) -> ToolChunk:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(
                    (
                        f"{self._base_url}/initialization-files/"
                        f"{file_id}/content"
                    ),
                    headers={"Authorization": f"Bearer {self._token}"},
                    params={
                        "agentscope_session_id": self._session_id,
                    },
                )
            if response.is_error:
                try:
                    detail = response.json().get("detail", response.text)
                except ValueError:
                    detail = response.text or response.reason_phrase
                raise ValueError(
                    f"读取附件失败（{response.status_code}）：{detail}",
                )
            suffix = response.headers.get(
                "X-Dobby-File-Extension",
                "",
            ).lower()
            parsed = await asyncio.to_thread(
                _parse_initialization_file,
                response.content,
                suffix,
                sheet_name,
                max(1, start),
                min(max(1, limit), 500),
                ocr_mode,
            )
            parsed["file_id"] = file_id
            return ToolChunk(
                content=[
                    TextBlock(
                        text=json.dumps(
                            parsed,
                            ensure_ascii=False,
                            default=str,
                        ),
                    ),
                ],
                state=ToolResultState.SUCCESS,
                is_last=True,
                metadata={
                    "operation": "read_project_initialization_file",
                    "platform_data_changed": False,
                },
            )
        except (
            httpx.HTTPError,
            ImportError,
            ValueError,
            OSError,
            RuntimeError,
        ) as exc:
            logger.warning("Unable to parse initialization file: %s", exc)
            return ToolChunk(
                content=[TextBlock(text=f"初始化附件读取失败：{exc}")],
                state=ToolResultState.ERROR,
                is_last=True,
                metadata={
                    "operation": "read_project_initialization_file",
                },
            )


class DobbyGatewayTool(ToolBase):
    """One semantic Dobby operation bound to a platform chat session."""

    is_concurrency_safe = False
    is_external_tool = False
    is_state_injected = False
    is_mcp = False

    def __init__(
        self,
        definition: dict[str, Any],
        session_id: str,
        actor_agent_id: str,
        initialization_role: str | None,
        base_url: str,
        token: str,
        requires_confirmation: bool,
        changes_business_data: bool,
    ) -> None:
        super().__init__()
        self.name = str(definition["name"])
        self.description = str(definition["description"])
        self.input_schema = dict(definition["schema"])
        self.is_read_only = not changes_business_data
        self._operation = str(definition["operation"])
        self._session_id = session_id
        self._actor_agent_id = actor_agent_id
        self._initialization_role = initialization_role
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._requires_confirmation = requires_confirmation
        self._changes_business_data = changes_business_data

    async def check_permissions(
        self,
        tool_input: dict[str, Any],
        context: PermissionContext,
    ) -> PermissionDecision:
        del tool_input, context
        if not self._requires_confirmation:
            return PermissionDecision(
                behavior=PermissionBehavior.ALLOW,
                message="该 Dobby 工具仅读取项目数据或保存待核对草稿。",
            )
        return PermissionDecision(
            behavior=PermissionBehavior.ASK,
            message=(
                "该操作将修改当前平台账号有权访问的项目数据，"
                "需要权限模式或权限审核员批准。"
            ),
        )

    async def call(self, **kwargs: Any) -> ToolChunk:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self._base_url}/execute",
                    headers={"Authorization": f"Bearer {self._token}"},
                    json={
                        "agentscope_session_id": self._session_id,
                        "actor_agent_id": self._actor_agent_id,
                        "initialization_role": self._initialization_role,
                        "operation": self._operation,
                        "arguments": kwargs,
                    },
                )
            if response.is_error:
                try:
                    payload = response.json()
                    detail = payload.get("detail", payload)
                except ValueError:
                    detail = response.text or response.reason_phrase
                return ToolChunk(
                    content=[
                        TextBlock(
                            text=(
                                f"Dobby 操作失败（{response.status_code}）："
                                f"{json.dumps(detail, ensure_ascii=False)}"
                            ),
                        ),
                    ],
                    state=ToolResultState.ERROR,
                    is_last=True,
                    metadata={"operation": self._operation},
                )
            payload = response.json()
            return ToolChunk(
                content=[
                    TextBlock(
                        text=json.dumps(payload, ensure_ascii=False, default=str),
                    ),
                ],
                state=ToolResultState.SUCCESS,
                is_last=True,
                metadata={
                    "operation": self._operation,
                    "platform_data_changed": self._changes_business_data,
                },
            )
        except httpx.HTTPError as exc:
            logger.warning("Dobby agent tool gateway request failed: %s", exc)
            return ToolChunk(
                content=[
                    TextBlock(
                        text=f"Dobby 平台工具网关当前不可用：{exc}",
                    ),
                ],
                state=ToolResultState.ERROR,
                is_last=True,
                metadata={"operation": self._operation},
            )


def _gateway_settings() -> tuple[str, str]:
    base_url = os.getenv("DOBBY_AGENT_TOOL_BASE_URL", _DEFAULT_GATEWAY_URL).strip()
    token = (
        os.getenv("DOBBY_AGENT_TOOL_TOKEN", "").strip()
        or os.getenv("AGENTSCOPE_SERVICE_TOKEN", "").strip()
    )
    return base_url, token


def create_dobby_agent_tool_catalog(
    initialization_role: str | None,
) -> list[AgentToolDescriptor]:
    """Return the complete assignable Dobby catalogue for one agent role.

    Catalogue construction is deliberately independent from the live platform
    session. Runtime capabilities still decide which assigned tools can be
    instantiated for a particular conversation.
    """
    read_definitions: list[dict[str, Any]] = list(READ_TOOL_DEFINITIONS)
    write_definitions: list[dict[str, Any]] = []

    if initialization_role is not None:
        read_definitions.extend(_INITIALIZATION_READ_TOOL_DEFINITIONS)
        if initialization_role == "orchestrator":
            read_definitions.append(INITIALIZATION_FILE_TOOL_DEFINITION)
            write_definitions.extend(
                INITIALIZATION_ORCHESTRATOR_TOOL_DEFINITIONS,
            )
        elif initialization_role in INITIALIZATION_SPECIALIST_TOOL_DEFINITIONS:
            write_definitions.extend(
                INITIALIZATION_SPECIALIST_TOOL_DEFINITIONS[
                    initialization_role
                ],
            )
        elif initialization_role == "validator":
            write_definitions.extend(
                INITIALIZATION_VALIDATOR_TOOL_DEFINITIONS,
            )
    else:
        write_definitions.extend(WRITE_TOOL_DEFINITIONS)
        write_definitions.extend(ADMIN_WRITE_TOOL_DEFINITIONS)

    descriptors: list[AgentToolDescriptor] = []
    seen: set[str] = set()
    for read_only, definitions in (
        (True, read_definitions),
        (False, write_definitions),
    ):
        for definition in definitions:
            name = str(definition["name"])
            if name in seen:
                continue
            seen.add(name)
            descriptors.append(
                AgentToolDescriptor(
                    name=name,
                    display_name=_TOOL_DISPLAY_NAMES.get(name),
                    description=str(definition.get("description") or ""),
                    input_schema=dict(definition.get("schema") or {}),
                    read_only=read_only,
                ),
            )
    return descriptors


async def create_dobby_agent_tools(
    user_id: str,
    agent_id: str,
    session_id: str,
    *,
    platform_session_id: str | None = None,
    platform_agent_id: str | None = None,
    read_only: bool = False,
    initialization_role: str | None = None,
) -> list[ToolBase]:
    """Build tools for a Dobby platform session or its internal worker.

    ``platform_session_id`` lets a temporary team worker inherit the
    authoritative project/user boundary of its leader's platform conversation.
    Team workers remain read-only for ordinary business operations. Their
    persisted ``initialization_role`` may additionally grant exactly one
    bounded draft operation: write one owned section or finalize review.
    """
    del user_id
    context_session_id = platform_session_id or session_id
    context_agent_id = platform_agent_id or agent_id
    base_url, token = _gateway_settings()
    if not token:
        logger.warning(
            "Dobby agent tools disabled: no internal service token configured.",
        )
        return []

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(
                f"{base_url}/context",
                headers={"Authorization": f"Bearer {token}"},
                params={"agentscope_session_id": context_session_id},
            )
        if response.status_code in {403, 404}:
            return []
        response.raise_for_status()
        context = response.json().get("data") or {}
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning("Unable to resolve Dobby tool context: %s", exc)
        return []

    # Prevent a mapped session from being used to assemble tools for a
    # different AgentScope agent.
    if str(context.get("agent_id") or "") != context_agent_id:
        return []

    capabilities = context.get("capabilities") or {}
    effective_initialization_role = initialization_role
    if (
        capabilities.get("initialization_draft")
        and effective_initialization_role is None
        and not read_only
    ):
        # The leader of a platform initialization conversation is the
        # orchestrator even before its persisted record is re-provisioned.
        effective_initialization_role = "orchestrator"
    definitions: list[tuple[dict[str, Any], bool, bool]] = [
        *((definition, False, False) for definition in READ_TOOL_DEFINITIONS),
    ]
    if capabilities.get("initialization_draft"):
        definitions.extend(
            (definition, False, False)
            for definition in _INITIALIZATION_READ_TOOL_DEFINITIONS
        )
        if effective_initialization_role == "orchestrator":
            definitions.extend(
                (definition, False, False)
                for definition in INITIALIZATION_ORCHESTRATOR_TOOL_DEFINITIONS
            )
        elif (
            effective_initialization_role
            in INITIALIZATION_SPECIALIST_TOOL_DEFINITIONS
        ):
            definitions.extend(
                (definition, False, False)
                for definition in INITIALIZATION_SPECIALIST_TOOL_DEFINITIONS[
                    effective_initialization_role
                ]
            )
        elif effective_initialization_role == "validator":
            definitions.extend(
                (definition, False, False)
                for definition in INITIALIZATION_VALIDATOR_TOOL_DEFINITIONS
            )
    is_initialization_agent = effective_initialization_role in {
        "orchestrator",
        "project",
        "personnel",
        "wbs",
        "risks",
        "quality_requirements",
        "validator",
    }
    if (
        capabilities.get("write")
        and not read_only
        and not is_initialization_agent
    ):
        definitions.extend(
            (definition, True, True) for definition in WRITE_TOOL_DEFINITIONS
        )
    if (
        capabilities.get("admin_write")
        and not read_only
        and not is_initialization_agent
    ):
        definitions.extend(
            (definition, True, True)
            for definition in ADMIN_WRITE_TOOL_DEFINITIONS
        )

    tools: list[ToolBase] = [
        DobbyGatewayTool(
            definition=definition,
            session_id=context_session_id,
            actor_agent_id=agent_id,
            initialization_role=effective_initialization_role,
            base_url=base_url,
            token=token,
            requires_confirmation=requires_confirmation,
            changes_business_data=changes_business_data,
        )
        for (
            definition,
            requires_confirmation,
            changes_business_data,
        ) in definitions
    ]
    if (
        capabilities.get("initialization_draft")
        and effective_initialization_role == "orchestrator"
    ):
        tools.append(
            DobbyInitializationFileTool(
                session_id=context_session_id,
                base_url=base_url,
                token=token,
            ),
        )
    return tools
