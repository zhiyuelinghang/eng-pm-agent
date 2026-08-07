"""Non-configurable safety checks for final project-initialization writes.

Business review rules live in the versioned MCP.  This module intentionally
contains only invariants required to keep the formal database coherent even
when an uploaded rule package is faulty or incomplete.
"""
from __future__ import annotations

from typing import Any


def _issue(path: str, message: str) -> dict[str, str]:
    return {
        "rule_id": "platform.integrity",
        "level": "error",
        "path": path,
        "message": message,
    }


def _duplicates(values: list[Any]) -> set[Any]:
    seen: set[Any] = set()
    duplicates: set[Any] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def validate_initialization_integrity(payload: Any) -> list[dict[str, str]]:
    """Return only hard structural and referential errors."""
    issues: list[dict[str, str]] = []
    project = payload.project
    if (
        project.contract_start_date
        and project.contract_end_date
        and project.contract_end_date < project.contract_start_date
    ):
        issues.append(
            _issue(
                "project.contract_end_date",
                "合同竣工日期不能早于合同开工日期",
            ),
        )

    for serial_no in sorted(
        _duplicates([item.serial_no for item in payload.personnel]),
    ):
        issues.append(_issue("personnel", f"人员序号 {serial_no} 重复"))
    assignments: set[tuple[str, str]] = set()
    for person in payload.personnel:
        assignment = (person.identity_card_no, person.position_name)
        if assignment in assignments:
            issues.append(
                _issue(
                    "personnel",
                    (
                        f"身份证号 {person.identity_card_no} 的岗位"
                        f"「{person.position_name}」重复"
                    ),
                ),
            )
        assignments.add(assignment)

    wbs_by_code: dict[str, Any] = {}
    for item in payload.wbs:
        if item.wbs_code in wbs_by_code:
            issues.append(_issue("wbs", f"WBS 编码 {item.wbs_code} 重复"))
        else:
            wbs_by_code[item.wbs_code] = item
        if (
            item.planned_start_at
            and item.planned_finish_at
            and item.planned_finish_at < item.planned_start_at
        ):
            issues.append(
                _issue(
                    f"wbs.{item.wbs_code}.planned_finish_at",
                    "计划结束时间不能早于计划开始时间",
                ),
            )

    parent_by_code: dict[str, str] = {}
    predecessor_by_code: dict[str, tuple[str, ...]] = {}
    for item in payload.wbs:
        if item.parent_wbs_code:
            parent_by_code[item.wbs_code] = item.parent_wbs_code
            parent = wbs_by_code.get(item.parent_wbs_code)
            if parent is None:
                issues.append(
                    _issue(
                        f"wbs.{item.wbs_code}.parent_wbs_code",
                        f"父级 WBS {item.parent_wbs_code} 不存在",
                    ),
                )
            elif parent.level >= item.level:
                issues.append(
                    _issue(
                        f"wbs.{item.wbs_code}.level",
                        "子节点层级必须大于父节点层级",
                    ),
                )
        expected_parent = (
            item.wbs_code.rsplit(".", 1)[0]
            if "." in item.wbs_code
            else None
        )
        if expected_parent != item.parent_wbs_code:
            issues.append(
                _issue(
                    f"wbs.{item.wbs_code}.parent_wbs_code",
                    (
                        f"WBS {item.wbs_code} 按编码应归属 "
                        f"{expected_parent or '根节点'}"
                    ),
                ),
            )
        expected_level = item.wbs_code.count(".") + 1
        if item.level != expected_level:
            issues.append(
                _issue(
                    f"wbs.{item.wbs_code}.level",
                    f"WBS {item.wbs_code} 按编码应为第 {expected_level} 层",
                ),
            )
        predecessor_by_code[item.wbs_code] = tuple(item.predecessor_wbs_codes)
        for predecessor in item.predecessor_wbs_codes:
            if predecessor == item.wbs_code:
                issues.append(
                    _issue(
                        f"wbs.{item.wbs_code}.predecessor_wbs_codes",
                        "WBS 节点不能把自己设为前任",
                    ),
                )
            elif predecessor not in wbs_by_code:
                issues.append(
                    _issue(
                        f"wbs.{item.wbs_code}.predecessor_wbs_codes",
                        f"前任 WBS {predecessor} 不存在",
                    ),
                )

    for code in parent_by_code:
        visited: set[str] = set()
        cursor: str | None = code
        while cursor is not None:
            if cursor in visited:
                issues.append(_issue(f"wbs.{code}", "WBS 父子关系存在循环"))
                break
            visited.add(cursor)
            cursor = parent_by_code.get(cursor)

    def has_predecessor_cycle(
        code: str,
        visiting: set[str],
        visited: set[str],
    ) -> bool:
        if code in visiting:
            return True
        if code in visited:
            return False
        visiting.add(code)
        for predecessor in predecessor_by_code.get(code, ()):
            if (
                predecessor in predecessor_by_code
                and has_predecessor_cycle(predecessor, visiting, visited)
            ):
                return True
        visiting.remove(code)
        visited.add(code)
        return False

    for code in predecessor_by_code:
        if has_predecessor_cycle(code, set(), set()):
            issues.append(
                _issue(
                    f"wbs.{code}.predecessor_wbs_codes",
                    "WBS 前置关系存在循环",
                ),
            )

    for serial_no in sorted(
        _duplicates([item.serial_no for item in payload.risks]),
    ):
        issues.append(_issue("risks", f"风险序号 {serial_no} 重复"))
    for item in payload.risks:
        if (
            item.risk_window_start_date
            and item.risk_window_end_date
            and item.risk_window_end_date < item.risk_window_start_date
        ):
            issues.append(
                _issue(
                    f"risks.{item.serial_no}.risk_window_end_date",
                    "风险窗口结束日期不能早于开始日期",
                ),
            )

    quality_codes = [item.wbs_code for item in payload.quality_requirements]
    for code in sorted(_duplicates(quality_codes)):
        issues.append(
            _issue(
                "quality_requirements",
                f"WBS {code} 存在多条质量指标记录",
            ),
        )
    for item in payload.quality_requirements:
        if item.wbs_code not in wbs_by_code:
            issues.append(
                _issue(
                    f"quality_requirements.{item.wbs_code}",
                    f"关联 WBS {item.wbs_code} 不存在",
                ),
            )

    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in issues:
        key = (item["path"], item["message"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique
