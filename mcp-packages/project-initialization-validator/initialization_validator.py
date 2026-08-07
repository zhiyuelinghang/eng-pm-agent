"""Deterministic, versioned rules for project-initialization drafts."""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal


ValidationLevel = Literal["error", "warning"]
RULESET_VERSION = "2026.08.1"


def _issue(
    rule_id: str,
    level: ValidationLevel,
    path: str,
    message: str,
) -> dict[str, str]:
    return {
        "rule_id": rule_id,
        "level": level,
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


def _wbs_code_sort_key(value: str) -> tuple[tuple[int, int | str], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in value.split(".")
    )


def _temporal(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.combine(
                    date.fromisoformat(text),
                    datetime.min.time(),
                )
            except ValueError:
                return None
    else:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _records(
    draft: dict[str, Any],
    name: str,
    issues: list[dict[str, str]],
) -> list[dict[str, Any]]:
    value = draft.get(name, [])
    if not isinstance(value, list):
        issues.append(
            _issue(
                f"{name}.section_type",
                "error",
                name,
                f"{name} 分区必须是数组",
            ),
        )
        return []
    records: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if isinstance(item, dict):
            records.append(item)
        else:
            issues.append(
                _issue(
                    f"{name}.record_type",
                    "error",
                    f"{name}.{index}",
                    "记录必须是对象",
                ),
            )
    return records


def validate_project_initialization(draft: dict[str, Any]) -> dict[str, Any]:
    """Validate one canonical draft and return a stable MCP result."""
    if not isinstance(draft, dict):
        raise ValueError("draft 必须是对象")
    issues: list[dict[str, str]] = []
    project = draft.get("project", {})
    if not isinstance(project, dict):
        issues.append(
            _issue(
                "project.section_type",
                "error",
                "project",
                "project 分区必须是对象",
            ),
        )
        project = {}
    personnel = _records(draft, "personnel", issues)
    wbs = _records(draft, "wbs", issues)
    risks = _records(draft, "risks", issues)
    quality = _records(draft, "quality_requirements", issues)

    project_start = _temporal(project.get("contract_start_date"))
    project_end = _temporal(project.get("contract_end_date"))
    if project_start and project_end and project_end < project_start:
        issues.append(
            _issue(
                "project.contract_date_order",
                "error",
                "project.contract_end_date",
                "合同竣工日期不能早于合同开工日期",
            ),
        )
    if any(value in (None, "") for value in project.values()) or not project:
        issues.append(
            _issue(
                "project.missing_fields",
                "warning",
                "project",
                "仍有项目基本信息未识别，可继续询问用户或由用户确认部分初始化",
            ),
        )

    for name, records, message in (
        ("personnel", personnel, "未识别到项目人员"),
        ("wbs", wbs, "未识别到 WBS 数据"),
        ("risks", risks, "未识别到风险清单"),
        ("quality_requirements", quality, "未识别到工序质量指标"),
    ):
        if not records:
            issues.append(_issue(f"{name}.empty", "warning", name, message))

    personnel_serials = [item.get("serial_no") for item in personnel]
    for serial_no in sorted(
        _duplicates(personnel_serials),
        key=lambda value: str(value),
    ):
        issues.append(
            _issue(
                "personnel.duplicate_serial",
                "error",
                "personnel",
                f"人员序号 {serial_no} 重复",
            ),
        )
    personnel_by_card: dict[str, list[dict[str, Any]]] = {}
    for person in personnel:
        card_no = str(person.get("identity_card_no") or "")
        if card_no:
            personnel_by_card.setdefault(card_no, []).append(person)
    for card_no, assignments in sorted(personnel_by_card.items()):
        if len(assignments) < 2:
            continue
        position_names = [str(item.get("position_name") or "") for item in assignments]
        for position_name in sorted(_duplicates(position_names)):
            issues.append(
                _issue(
                    "personnel.duplicate_position",
                    "error",
                    "personnel",
                    f"身份证号 {card_no} 的岗位「{position_name}」重复",
                ),
            )
        unique_positions = list(dict.fromkeys(position_names))
        if len(unique_positions) > 1:
            issues.append(
                _issue(
                    "personnel.multiple_positions",
                    "warning",
                    "personnel",
                    (
                        f"身份证号 {card_no} 对应多个岗位"
                        f"（{'、'.join(unique_positions)}）；这些岗位将共用同一个"
                        "平台账号，请核对是否为本人兼任"
                    ),
                ),
            )

    wbs_by_code: dict[str, dict[str, Any]] = {}
    for item in wbs:
        code = str(item.get("wbs_code") or "")
        if code in wbs_by_code:
            issues.append(
                _issue(
                    "wbs.duplicate_code",
                    "error",
                    "wbs",
                    f"WBS 编码 {code} 重复",
                ),
            )
        else:
            wbs_by_code[code] = item
        started = _temporal(item.get("planned_start_at"))
        finished = _temporal(item.get("planned_finish_at"))
        if started and finished and finished < started:
            issues.append(
                _issue(
                    "wbs.date_order",
                    "error",
                    f"wbs.{code}.planned_finish_at",
                    "计划结束时间不能早于计划开始时间",
                ),
            )
        if str(item.get("name") or "").strip() in {
            "任务名称",
            "未命名任务",
            "未命名工序",
        }:
            issues.append(
                _issue(
                    "wbs.placeholder_name",
                    "warning",
                    f"wbs.{code}.name",
                    f"WBS {code} 的名称“{item.get('name')}”疑似占位内容，请核对",
                ),
            )

    siblings_by_parent: dict[str | None, list[dict[str, Any]]] = {}
    for item in wbs:
        parent_code = item.get("parent_wbs_code")
        siblings_by_parent.setdefault(
            str(parent_code) if parent_code not in (None, "") else None,
            [],
        ).append(item)
    for siblings in siblings_by_parent.values():
        siblings.sort(key=lambda item: _wbs_code_sort_key(str(item.get("wbs_code") or "")))
        latest: dict[str, Any] | None = None
        for item in siblings:
            started = _temporal(item.get("planned_start_at"))
            if started is None:
                continue
            latest_started = _temporal(latest.get("planned_start_at")) if latest else None
            if latest is not None and latest_started and started < latest_started:
                code = str(item.get("wbs_code") or "")
                previous_code = str(latest.get("wbs_code") or "")
                issues.append(
                    _issue(
                        "wbs.sibling_start_order",
                        "warning",
                        f"wbs.{code}.planned_start_at",
                        (
                            f"WBS {code} 的计划开始早于编码在前的同级 WBS "
                            f"{previous_code}；同级 WBS 编码顺序与开始时间顺序冲突，"
                            "请核对原始计划"
                        ),
                    ),
                )
            if latest_started is None or started >= latest_started:
                latest = item

    for item in wbs:
        code = str(item.get("wbs_code") or "")
        parent_code = item.get("parent_wbs_code")
        parent_key = str(parent_code) if parent_code not in (None, "") else None
        if parent_key:
            parent = wbs_by_code.get(parent_key)
            if parent is None:
                issues.append(
                    _issue(
                        "wbs.missing_parent",
                        "error",
                        f"wbs.{code}.parent_wbs_code",
                        f"父级 WBS {parent_key} 不存在",
                    ),
                )
            else:
                parent_level = parent.get("level")
                level = item.get("level")
                if isinstance(parent_level, int) and isinstance(level, int) and parent_level >= level:
                    issues.append(
                        _issue(
                            "wbs.parent_level",
                            "error",
                            f"wbs.{code}.level",
                            "子节点层级必须大于父节点层级",
                        ),
                    )
                started = _temporal(item.get("planned_start_at"))
                parent_started = _temporal(parent.get("planned_start_at"))
                if started and parent_started and started < parent_started:
                    issues.append(
                        _issue(
                            "wbs.before_parent_start",
                            "warning",
                            f"wbs.{code}.planned_start_at",
                            f"WBS {code} 的计划开始早于父级 {parent_key}，请核对父级汇总日期",
                        ),
                    )
                finished = _temporal(item.get("planned_finish_at"))
                parent_finished = _temporal(parent.get("planned_finish_at"))
                if finished and parent_finished and finished > parent_finished:
                    issues.append(
                        _issue(
                            "wbs.after_parent_finish",
                            "warning",
                            f"wbs.{code}.planned_finish_at",
                            f"WBS {code} 的计划完成晚于父级 {parent_key}，请核对父级汇总日期",
                        ),
                    )
        expected_parent = code.rsplit(".", 1)[0] if "." in code else None
        if expected_parent != parent_key:
            issues.append(
                _issue(
                    "wbs.parent_from_code",
                    "error",
                    f"wbs.{code}.parent_wbs_code",
                    (
                        f"WBS {code} 按编码应归属 {expected_parent or '根节点'}，"
                        f"当前上级为 {parent_key or '空'}"
                    ),
                ),
            )
        expected_level = code.count(".") + 1
        if item.get("level") != expected_level:
            issues.append(
                _issue(
                    "wbs.level_from_code",
                    "error",
                    f"wbs.{code}.level",
                    f"WBS {code} 按编码应为第 {expected_level} 层，当前为第 {item.get('level')} 层",
                ),
            )
        predecessors = item.get("predecessor_wbs_codes") or []
        if not isinstance(predecessors, list):
            predecessors = []
        for predecessor_code_value in predecessors:
            predecessor_code = str(predecessor_code_value)
            if predecessor_code == code:
                issues.append(
                    _issue(
                        "wbs.self_predecessor",
                        "error",
                        f"wbs.{code}.predecessor_wbs_codes",
                        "WBS 节点不能把自己设为前任",
                    ),
                )
            elif predecessor_code not in wbs_by_code:
                issues.append(
                    _issue(
                        "wbs.missing_predecessor",
                        "error",
                        f"wbs.{code}.predecessor_wbs_codes",
                        f"前任 WBS {predecessor_code} 不存在",
                    ),
                )
            else:
                started = _temporal(item.get("planned_start_at"))
                predecessor_finished = _temporal(
                    wbs_by_code[predecessor_code].get("planned_finish_at"),
                )
                if started and predecessor_finished and started < predecessor_finished:
                    issues.append(
                        _issue(
                            "wbs.predecessor_overlap",
                            "warning",
                            f"wbs.{code}.planned_start_at",
                            (
                                f"WBS {code} 的计划开始早于前任 {predecessor_code} 的"
                                "计划完成；如属于搭接施工或开始-开始关系，请人工确认"
                            ),
                        ),
                    )

    parent_by_code = {
        str(item.get("wbs_code") or ""): str(item.get("parent_wbs_code"))
        for item in wbs
        if item.get("parent_wbs_code") not in (None, "")
    }
    for code in parent_by_code:
        visited: set[str] = set()
        cursor: str | None = code
        while cursor is not None:
            if cursor in visited:
                issues.append(
                    _issue(
                        "wbs.parent_cycle",
                        "error",
                        f"wbs.{code}",
                        "WBS 父子关系存在循环",
                    ),
                )
                break
            visited.add(cursor)
            cursor = parent_by_code.get(cursor)

    predecessor_by_code = {
        str(item.get("wbs_code") or ""): tuple(
            str(value) for value in (item.get("predecessor_wbs_codes") or [])
        )
        for item in wbs
        if isinstance(item.get("predecessor_wbs_codes") or [], list)
    }
    cycle_codes: set[str] = set()

    def visit_predecessor(current: str, visiting: set[str], visited: set[str]) -> bool:
        if current in visiting:
            return True
        if current in visited:
            return False
        visiting.add(current)
        cyclic = any(
            predecessor in predecessor_by_code
            and visit_predecessor(predecessor, visiting, visited)
            for predecessor in predecessor_by_code.get(current, ())
        )
        visiting.discard(current)
        visited.add(current)
        return cyclic

    for code in predecessor_by_code:
        if visit_predecessor(code, set(), set()):
            cycle_codes.add(code)
    for code in sorted(cycle_codes, key=_wbs_code_sort_key):
        issues.append(
            _issue(
                "wbs.predecessor_cycle",
                "error",
                f"wbs.{code}.predecessor_wbs_codes",
                "WBS 前置关系存在循环",
            ),
        )

    for serial_no in sorted(
        _duplicates([item.get("serial_no") for item in risks]),
        key=lambda value: str(value),
    ):
        issues.append(
            _issue(
                "risks.duplicate_serial",
                "error",
                "risks",
                f"风险序号 {serial_no} 重复",
            ),
        )
    for item in risks:
        started = _temporal(item.get("risk_window_start_date"))
        finished = _temporal(item.get("risk_window_end_date"))
        if started and finished and finished < started:
            serial_no = item.get("serial_no")
            issues.append(
                _issue(
                    "risks.window_date_order",
                    "error",
                    f"risks.{serial_no}.risk_window_end_date",
                    "风险窗口结束日期不能早于开始日期",
                ),
            )

    quality_codes = [str(item.get("wbs_code") or "") for item in quality]
    for code in sorted(_duplicates(quality_codes), key=_wbs_code_sort_key):
        issues.append(
            _issue(
                "quality.duplicate_wbs",
                "error",
                "quality_requirements",
                f"WBS {code} 存在多条质量指标记录",
            ),
        )
    for item in quality:
        code = str(item.get("wbs_code") or "")
        if code not in wbs_by_code:
            issues.append(
                _issue(
                    "quality.missing_wbs",
                    "error",
                    f"quality_requirements.{code}",
                    f"关联 WBS {code} 不存在",
                ),
            )

    unique_issues: list[dict[str, str]] = []
    seen_issues: set[tuple[str, str, str, str]] = set()
    for item in issues:
        key = (
            item["rule_id"],
            item["level"],
            item["path"],
            item["message"],
        )
        if key not in seen_issues:
            seen_issues.add(key)
            unique_issues.append(item)
    error_count = sum(item["level"] == "error" for item in unique_issues)
    warning_count = sum(item["level"] == "warning" for item in unique_issues)
    return {
        "ruleset_version": RULESET_VERSION,
        "status": "invalid" if error_count else "ready",
        "validation_issues": unique_issues,
        "requires_semantic_review": [],
        "summary": {
            "project_fields": sum(value not in (None, "") for value in project.values()),
            "personnel": len(personnel),
            "wbs": len(wbs),
            "risks": len(risks),
            "quality_requirements": len(quality),
            "errors": error_count,
            "warnings": warning_count,
        },
    }
