"""Non-configurable database-safety checks for initialization drafts.

Business review rules live in the versioned validator MCP.  These checks only
protect referential and structural invariants required by the final database
write, and use the same row/field annotation contract as the MCP.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def _record_id(record: Any | None) -> int | None:
    value = getattr(record, "record_id", None) if record is not None else None
    return value if isinstance(value, int) and value > 0 else None


def _issue(
    rule_id: str,
    section: str,
    record: Any | None,
    field_name: str | None,
    title: str,
    message: str,
    *,
    related: list[Any] | None = None,
) -> dict[str, Any]:
    related_ids = [
        value
        for value in (_record_id(item) for item in (related or []))
        if value is not None and value != _record_id(record)
    ]
    return {
        "rule_id": f"platform.integrity.{rule_id}",
        "level": "error",
        "section": section,
        "target_record_id": _record_id(record),
        "field_name": field_name,
        "label": "结构错误",
        "title": title,
        "message": message,
        "suggestion": "请修正该数据后重新执行核验。",
        "related_record_ids": list(dict.fromkeys(related_ids)),
        "details": {"source": "platform_integrity"},
    }


def _groups(records: list[Any], field_name: str) -> dict[Any, list[Any]]:
    grouped: dict[Any, list[Any]] = defaultdict(list)
    for record in records:
        grouped[getattr(record, field_name)].append(record)
    return grouped


def validate_initialization_integrity(payload: Any) -> list[dict[str, Any]]:
    """Return hard structural and referential errors with precise targets."""
    issues: list[dict[str, Any]] = []
    project = payload.project
    if (
        project.contract_start_date
        and project.contract_end_date
        and project.contract_end_date < project.contract_start_date
    ):
        issues.append(
            _issue(
                "project.contract_date_order",
                "project",
                project,
                "contract_end_date",
                "合同日期顺序错误",
                "合同竣工日期不能早于合同开工日期。",
            ),
        )

    for serial_no, records in _groups(payload.personnel, "serial_no").items():
        if len(records) > 1:
            for record in records:
                issues.append(
                    _issue(
                        "personnel.duplicate_serial",
                        "personnel",
                        record,
                        "serial_no",
                        "人员序号重复",
                        f"人员序号 {serial_no} 对应多条记录。",
                        related=records,
                    ),
                )
    assignments: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for person in payload.personnel:
        assignments[(person.identity_card_no, person.position_name)].append(person)
    for (card_no, position_name), records in assignments.items():
        if len(records) > 1:
            for record in records:
                issues.append(
                    _issue(
                        "personnel.duplicate_assignment",
                        "personnel",
                        record,
                        "position_name",
                        "人员岗位重复",
                        f"身份证号 {card_no} 的岗位「{position_name}」重复。",
                        related=records,
                    ),
                )

    wbs_groups = _groups(payload.wbs, "wbs_code")
    wbs_by_code = {code: records[0] for code, records in wbs_groups.items()}
    for code, records in wbs_groups.items():
        if len(records) > 1:
            for record in records:
                issues.append(
                    _issue(
                        "wbs.duplicate_code",
                        "wbs",
                        record,
                        "wbs_code",
                        "WBS 编码重复",
                        f"WBS 编码 {code} 对应多条记录。",
                        related=records,
                    ),
                )

    parent_by_code: dict[str, str] = {}
    predecessor_by_code: dict[str, tuple[str, ...]] = {}
    for item in payload.wbs:
        code = item.wbs_code
        if (
            item.planned_start_at
            and item.planned_finish_at
            and item.planned_finish_at < item.planned_start_at
        ):
            issues.append(
                _issue(
                    "wbs.date_order",
                    "wbs",
                    item,
                    "planned_finish_at",
                    "计划日期顺序错误",
                    "计划结束时间不能早于计划开始时间。",
                ),
            )
        if item.parent_wbs_code:
            parent_by_code[code] = item.parent_wbs_code
            parent = wbs_by_code.get(item.parent_wbs_code)
            if parent is None:
                issues.append(
                    _issue(
                        "wbs.missing_parent",
                        "wbs",
                        item,
                        "parent_wbs_code",
                        "父级 WBS 不存在",
                        f"父级 WBS {item.parent_wbs_code} 不存在。",
                    ),
                )
            elif parent.level >= item.level:
                issues.append(
                    _issue(
                        "wbs.parent_level",
                        "wbs",
                        item,
                        "level",
                        "WBS 层级错误",
                        "子节点层级必须大于父节点层级。",
                        related=[parent],
                    ),
                )
        expected_parent = code.rsplit(".", 1)[0] if "." in code else None
        if expected_parent != item.parent_wbs_code:
            issues.append(
                _issue(
                    "wbs.parent_from_code",
                    "wbs",
                    item,
                    "parent_wbs_code",
                    "WBS 归属与编码不一致",
                    f"WBS {code} 按编码应归属 {expected_parent or '根节点'}。",
                ),
            )
        expected_level = code.count(".") + 1
        if item.level != expected_level:
            issues.append(
                _issue(
                    "wbs.level_from_code",
                    "wbs",
                    item,
                    "level",
                    "WBS 层级与编码不一致",
                    f"WBS {code} 按编码应为第 {expected_level} 层。",
                ),
            )
        predecessor_by_code[code] = tuple(item.predecessor_wbs_codes)
        for predecessor_code in item.predecessor_wbs_codes:
            predecessor = wbs_by_code.get(predecessor_code)
            if predecessor_code == code:
                issues.append(
                    _issue(
                        "wbs.self_predecessor",
                        "wbs",
                        item,
                        "predecessor_wbs_codes",
                        "WBS 前任引用自身",
                        "WBS 节点不能把自己设为前任。",
                    ),
                )
            elif predecessor is None:
                issues.append(
                    _issue(
                        "wbs.missing_predecessor",
                        "wbs",
                        item,
                        "predecessor_wbs_codes",
                        "前任 WBS 不存在",
                        f"前任 WBS {predecessor_code} 不存在。",
                    ),
                )

    for code in parent_by_code:
        visited: set[str] = set()
        cursor: str | None = code
        while cursor is not None:
            if cursor in visited:
                issues.append(
                    _issue(
                        "wbs.parent_cycle",
                        "wbs",
                        wbs_by_code.get(code),
                        None,
                        "WBS 父子关系循环",
                        "WBS 父子关系存在循环。",
                    ),
                )
                break
            visited.add(cursor)
            cursor = parent_by_code.get(cursor)

    def has_predecessor_cycle(code: str, visiting: set[str], visited: set[str]) -> bool:
        if code in visiting:
            return True
        if code in visited:
            return False
        visiting.add(code)
        cyclic = any(
            predecessor in predecessor_by_code
            and has_predecessor_cycle(predecessor, visiting, visited)
            for predecessor in predecessor_by_code.get(code, ())
        )
        visiting.discard(code)
        visited.add(code)
        return cyclic

    for code in predecessor_by_code:
        if has_predecessor_cycle(code, set(), set()):
            issues.append(
                _issue(
                    "wbs.predecessor_cycle",
                    "wbs",
                    wbs_by_code.get(code),
                    "predecessor_wbs_codes",
                    "WBS 前置关系循环",
                    "WBS 前置关系存在循环。",
                ),
            )

    for serial_no, records in _groups(payload.risks, "serial_no").items():
        if len(records) > 1:
            for record in records:
                issues.append(
                    _issue(
                        "risks.duplicate_serial",
                        "risks",
                        record,
                        "serial_no",
                        "风险序号重复",
                        f"风险序号 {serial_no} 对应多条记录。",
                        related=records,
                    ),
                )
    for item in payload.risks:
        if (
            item.risk_window_start_date
            and item.risk_window_end_date
            and item.risk_window_end_date < item.risk_window_start_date
        ):
            issues.append(
                _issue(
                    "risks.window_date_order",
                    "risks",
                    item,
                    "risk_window_end_date",
                    "风险窗口日期顺序错误",
                    "风险窗口结束日期不能早于开始日期。",
                ),
            )

    for code, records in _groups(payload.quality_requirements, "wbs_code").items():
        if len(records) > 1:
            for record in records:
                issues.append(
                    _issue(
                        "quality.duplicate_wbs",
                        "quality_requirements",
                        record,
                        "wbs_code",
                        "质量指标关联重复",
                        f"WBS {code} 存在多条质量指标记录。",
                        related=records,
                    ),
                )
    for item in payload.quality_requirements:
        if item.wbs_code not in wbs_by_code:
            issues.append(
                _issue(
                    "quality.missing_wbs",
                    "quality_requirements",
                    item,
                    "wbs_code",
                    "关联 WBS 不存在",
                    f"关联 WBS {item.wbs_code} 不存在。",
                ),
            )

    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in issues:
        key = (
            item["rule_id"],
            item["target_record_id"],
            item["field_name"],
            item["message"],
        )
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique
