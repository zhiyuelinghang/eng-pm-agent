"""Sparse specialist payload schemas and source-evidence validation."""
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, TypeAdapter, ValidationError

from .initialization_patch import (
    PersonnelPatch, ProjectDetailsPatch, QualityRequirementPatch, RiskPatch, WbsPatch,
)

_INITIALIZATION_SECTION_MODELS: dict[str, type[BaseModel]] = {
    "project": ProjectDetailsPatch,
    "personnel": PersonnelPatch,
    "wbs": WbsPatch,
    "risks": RiskPatch,
    "quality_requirements": QualityRequirementPatch,
}
_INITIALIZATION_ARRAY_SECTIONS = frozenset(
    {"personnel", "wbs", "risks", "quality_requirements"},
)
_INITIALIZATION_SECTION_MAX_ITEMS = {
    "personnel": 2000,
    "wbs": 10000,
    "risks": 5000,
    "quality_requirements": 10000,
}
_INITIALIZATION_SECTION_ADAPTERS = {
    "project": TypeAdapter(ProjectDetailsPatch),
    "personnel": TypeAdapter(list[PersonnelPatch]),
    "wbs": TypeAdapter(list[WbsPatch]),
    "risks": TypeAdapter(list[RiskPatch]),
    "quality_requirements": TypeAdapter(list[QualityRequirementPatch]),
}

def _initialization_section_payload_schema(section: str) -> dict[str, Any]:
    """Describe attachment observations without manufacturing absent fields."""
    model = _INITIALIZATION_SECTION_MODELS.get(section)
    if model is None:
        raise HTTPException(status_code=422, detail="初始化草稿分区类型无效")
    item_schema = model.model_json_schema()
    item_schema.get("properties", {}).pop("record_id", None)
    if isinstance(item_schema.get("required"), list):
        item_schema["required"] = [
            name for name in item_schema["required"] if name != "record_id"
        ]
    if section == "project":
        item_schema["description"] = (
            "本次资料识别到的工程信息；未提供字段省略，保留正式旧值。"
            "字段名必须与此结构完全一致，禁止额外包裹。"
        )
        return item_schema
    return {
        "type": "array",
        "items": item_schema,
        "minItems": 0,
        "maxItems": _INITIALIZATION_SECTION_MAX_ITEMS[section],
        "description": (
            "本次草稿分区的记录数组，更新草稿时保留该分区已提取的其他记录。"
            "每条只提供匹配键和本次识别到的字段，未提供字段保持正式旧值；"
            "字段名必须与 items 完全一致，禁止嵌套 children 或额外包裹。"
        ),
    }


def _normalize_initialization_section_payload(
    section: str,
    payload: Any,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Validate and serialize one project-initialization payload batch."""
    adapter = _INITIALIZATION_SECTION_ADAPTERS.get(section)
    if adapter is None:
        raise HTTPException(status_code=422, detail="初始化草稿分区类型无效")
    if section in _INITIALIZATION_ARRAY_SECTIONS:
        max_items = _INITIALIZATION_SECTION_MAX_ITEMS[section]
        if not isinstance(payload, list) or len(payload) > max_items:
            raise HTTPException(
                status_code=422,
                detail=(
                    "数组型初始化分区必须写入不超过 "
                    f"{max_items} 条完整标准记录"
                ),
            )
    if isinstance(payload, list):
        normalized_input = [
            {key: value for key, value in item.items() if key != "record_id"}
            if isinstance(item, dict)
            else item
            for item in payload
        ]
    elif isinstance(payload, dict):
        normalized_input = {
            key: value for key, value in payload.items() if key != "record_id"
        }
    else:
        normalized_input = payload
    try:
        validated = adapter.validate_python(normalized_input)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "初始化草稿分区字段不符合标准结构",
                "errors": exc.errors(include_input=False),
            },
        ) from exc
    serialized = adapter.dump_python(validated, mode="json", exclude_unset=True)
    if isinstance(serialized, list):
        return [
            {key: value for key, value in item.items() if key != "record_id"}
            for item in serialized
        ]
    return {
        key: value for key, value in serialized.items() if key != "record_id"
    }


def _validate_initialization_section_evidence(values: dict[str, Any]) -> None:
    """Require every specialist write to retain a usable evidence trail."""
    source_files = values.get("source_files")
    valid_source_files = (
        isinstance(source_files, dict)
        and bool(source_files)
    ) or (
        isinstance(source_files, list)
        and bool(source_files)
        and all(
            (isinstance(item, str) and bool(item.strip()))
            or (isinstance(item, dict) and bool(item))
            for item in source_files
        )
    )
    if not valid_source_files:
        raise HTTPException(
            status_code=422,
            detail=(
                "初始化草稿分区必须记录非空 source_files，"
                "并保留 file_id、chunk_id 或来源文件名"
            ),
        )
    extraction_notes = values.get("extraction_notes")
    if not isinstance(extraction_notes, list) or any(
        not isinstance(item, str) or not item.strip()
        for item in extraction_notes
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "初始化草稿分区必须显式提交 extraction_notes 数组；"
                "没有来源或转换说明时使用空数组"
            ),
        )
