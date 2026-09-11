"""Deterministic, versioned rules for project-initialization drafts."""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from typing import Any, Literal


ValidationLevel = Literal["error", "warning"]
RULESET_VERSION = "2026.09.4"
PROJECT_RULES = json.loads(Path(__file__).with_name("project_rules.json").read_text(encoding="utf-8"))
PERSONNEL_POSITIONS = tuple(PROJECT_RULES["personnel_positions"])


def _record_id(record: dict[str, Any] | None) -> int | None:
    value = record.get("record_id") if record else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _issue(
    rule_id: str,
    level: ValidationLevel,
    section: str,
    record: dict[str, Any] | None,
    field_name: str | None,
    title: str,
    message: str,
    suggestion: str,
    *,
    label: str | None = None,
    related: list[dict[str, Any]] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target_id = _record_id(record)
    related_ids = [
        value
        for value in (_record_id(item) for item in (related or []))
        if value is not None and value != target_id
    ]
    return {
        "rule_id": rule_id,
        "level": level,
        "section": section,
        "target_record_id": target_id,
        "field_name": field_name,
        "label": label or ("必须修正" if level == "error" else "需要核对"),
        "title": title,
        "message": message,
        "suggestion": suggestion,
        "related_record_ids": list(dict.fromkeys(related_ids)),
        "details": details or {},
    }


def _groups(
    records: list[dict[str, Any]],
    field_name: str,
) -> dict[Any, list[dict[str, Any]]]:
    grouped: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        value = record.get(field_name)
        try:
            hash(value)
        except TypeError:
            # Invalid scalar values have their own field annotation; they
            # must not crash duplicate checks and hide all validation output.
            continue
        grouped[value].append(record)
    return grouped


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
                parsed = datetime.combine(date.fromisoformat(text), datetime.min.time())
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
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    value = draft.get(name, [])
    if not isinstance(value, list):
        issues.append(
            _issue(
                f"{name}.section_type",
                "error",
                name,
                None,
                None,
                "草稿分区格式错误",
                f"{name} 分区必须是记录数组。",
                "请重新整理并提交该草稿分区。",
            ),
        )
        return []
    records: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            records.append(item)
        else:
            issues.append(
                _issue(
                    f"{name}.record_type",
                    "error",
                    name,
                    None,
                    None,
                    "草稿记录格式错误",
                    "草稿分区中存在不是对象的记录。",
                    "请重新整理并提交该草稿分区。",
                ),
            )
    return records


def _batch_issues(issues: list[dict[str, Any]], scope: Any, records: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The MCP owns which business findings affect a partially selected batch."""
    if scope is None:
        return issues
    targets = scope["record_targets"]
    selected = set(scope["selected_keys"])
    by_id = {str(row.get("record_id")): row for row in (records or [])}
    by_key = {key: (raw_id, by_id.get(raw_id, {})) for raw_id, mapping in targets.items() for key in mapping.get("change_keys", [])}
    sections = set(scope["sections"])
    result = []
    seen = set()
    for issue in issues:
        target = targets.get(str(issue.get("target_record_id")), {})
        keys = list(target.get("change_keys", []))
        field = issue.get("field_name")
        if target.get("section") == "project" and field:
            fields = ("contract_start_date", "contract_end_date") if issue["rule_id"] == "project.contract_date_order" else (field,)
            keys = [target.get("field_changes", {}).get(name) for name in fields]
        for related_id in issue.get("related_record_ids", []):
            keys.extend(targets.get(str(related_id), {}).get("change_keys", []))
        affected = list(dict.fromkeys(key for key in keys if key in selected))
        if not affected and (issue.get("target_record_id") is not None or issue["section"] not in sections or issue["rule_id"].endswith(".empty")):
            continue
        for key in affected or [None]:
            annotation = {**issue, "details": {**issue.get("details", {}), "change_keys": [key] if key else []}}
            raw_id, row = by_key.get(key, (None, {}))
            code = row.get("wbs_code")
            if raw_id and issue["section"] == "wbs":
                annotation["target_record_id"] = int(raw_id)
                if issue["rule_id"] == "wbs.sibling_start_order" and issue.get("details", {}).get("wbs_code") != code:
                    annotation["message"] = f"关联工序 {issue['details']['wbs_code']} 的计划开始早于本工序（{code}），请核对两项计划时间。"
                if issue["rule_id"] == "wbs.predecessor_overlap" and code == issue.get("details", {}).get("predecessor_wbs_code"):
                    annotation["field_name"] = "planned_finish_at"
                    annotation["message"] = f"本工序（{code}）作为前置工序，计划完成晚于后续工序的计划开始。"
            identity = (annotation["rule_id"], key, annotation.get("field_name"), annotation["message"])
            if identity in seen:
                continue
            seen.add(identity)
            result.append(annotation)
    return result


def _catalogue_issues(sections: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Versioned catalogue and value rules; no platform imports or mutation."""
    issues: list[dict[str, Any]] = []
    for person in sections["personnel"]:
        raw = person.get("position_name")
        position = raw.strip() if isinstance(raw, str) else None
        if position not in PERSONNEL_POSITIONS:
            issues.append(_issue(
                "personnel.unsupported_position", "error", "personnel", person,
                "position_name", "岗位不在固定范围",
                f"岗位「{position or raw or '空白岗位'}」不在系统固定的 {len(PERSONNEL_POSITIONS)} 个岗位中。",
                f"请人工核对岗位并修改原始资料后重新上传。允许岗位：{'、'.join(PERSONNEL_POSITIONS)}。",
                details={"allowed_positions": list(PERSONNEL_POSITIONS)},
            ))
    for section, fields in PROJECT_RULES["numeric_fields"].items():
        for row in sections[section]:
            for field, rule in fields.items():
                raw = row.get(field)
                if raw is None or (isinstance(raw, str) and not raw.strip()):
                    # These rules constrain supplied values, not requiredness.
                    continue
                try:
                    number = Decimal(str(raw))
                    valid_number = not isinstance(raw, bool) and number.is_finite()
                except (InvalidOperation, ValueError):
                    valid_number = False
                if not valid_number:
                    reason = "必须为有效的有限数值。"
                elif rule.get("integer") and number != number.to_integral_value():
                    reason = "必须为整数。"
                elif number < rule["minimum"] or (rule.get("exclusive_minimum") and number == rule["minimum"]):
                    reason = f"必须{'大于' if rule.get('exclusive_minimum') else '大于或等于'} {rule['minimum']}。"
                elif "maximum" in rule and number > rule["maximum"]:
                    reason = f"不能大于 {rule['maximum']}。"
                else:
                    continue
                issues.append(_issue(
                    f"{section}.{field}.value", "error", section, row, field,
                    f"{rule['label']}取值不符合规则", f"{rule['label']}{reason}",
                    "请人工核对原始资料，修正后重新上传。",
                    details={"value": raw, "constraint": rule},
                ))
    return issues


def validate_project_initialization(draft: dict[str, Any]) -> dict[str, Any]:
    """Validate one canonical draft and return row/field annotations."""
    if not isinstance(draft, dict):
        raise ValueError("draft 必须是对象")
    issues: list[dict[str, Any]] = []
    project = draft.get("project", {})
    if not isinstance(project, dict):
        issues.append(
            _issue(
                "project.section_type",
                "error",
                "project",
                None,
                None,
                "工程信息格式错误",
                "工程信息分区必须是对象。",
                "请重新整理并提交工程信息。",
            ),
        )
        project = {}
    personnel = _records(draft, "personnel", issues)
    wbs = _records(draft, "wbs", issues)
    risks = _records(draft, "risks", issues)
    quality = _records(draft, "quality_requirements", issues)
    issues.extend(_catalogue_issues({
        "project": [project], "personnel": personnel, "wbs": wbs,
        "risks": risks, "quality_requirements": quality,
    }))

    # The platform supplies identity matches as facts; only the MCP turns a
    # duplicate identity into a material issue requiring human correction.
    scope = draft.get("validation_scope") or {}
    records_by_id = {str(row.get("record_id")): row for row in [project, *personnel, *wbs, *risks, *quality]}
    for raw_id, target in scope.get("record_targets", {}).items():
        section = target["section"]
        row = records_by_id.get(raw_id, {"record_id": int(raw_id)})
        if section != "project" and target.get("target_id") is not None and len(target.get("observations", [])) > 1:
            issues.append(_issue(
                "matching.duplicate_target", "error", section, row, None,
                "多条上传记录对应同一现有记录", "本次资料中有多条记录修改同一旧记录。",
                "请人工整理原始资料，消除重复后重新上传。",
            ))
        account = target.get("existing_account")
        if account and not target.get("updates_existing_identity") and row.get("real_name") != account.get("real_name"):
            issues.append(_issue(
                "personnel.existing_account_name", "error", "personnel", row, "real_name",
                "姓名与已有账号不一致", f"上传姓名「{row.get('real_name') or ''}」与已有账号姓名「{account['real_name']}」不同。",
                "请人工核对身份证号和姓名，修正原始资料后重新上传。",
            ))
        candidates = target.get("matching_candidates", [])
        if len(candidates) < 2:
            continue
        section = target["section"]
        field = {"personnel": "identity_card_no", "wbs": "wbs_code", "quality_requirements": "wbs_code", "risks": "related_process_name"}.get(section)
        issues.append(_issue(
            "matching.duplicate_identity", "error", section, {"record_id": int(raw_id)}, field,
            "现有记录的识别信息重复", f"同一组识别信息对应 {len(candidates)} 条现有记录，无法确定本次更新对象。",
            "请人工核对现有记录与原始资料，消除重复后重新上传。",
            details={"candidate_ids": [item["id"] for item in candidates]},
        ))

    project_start = _temporal(project.get("contract_start_date"))
    project_end = _temporal(project.get("contract_end_date"))
    if project_start and project_end and project_end < project_start:
        issues.append(
            _issue(
                "project.contract_date_order",
                "error",
                "project",
                project,
                "contract_end_date",
                "合同日期顺序错误",
                "合同竣工日期不能早于合同开工日期。",
                "请对照合同修正开工或竣工日期。",
                details={
                    "contract_start_date": project.get("contract_start_date"),
                    "contract_end_date": project.get("contract_end_date"),
                },
            ),
        )
    if _record_id(project) is None:
        issues.append(
            _issue(
                "project.empty",
                "warning",
                "project",
                None,
                None,
                "工程基本信息为空",
                "未识别到可定位的工程基本信息记录。",
                "请确认工程资料是否已完成整理和提交。",
                label="分区为空",
            ),
        )
    for field_name, value in project.items():
        if (
            _record_id(project) is not None
            and field_name != "record_id"
            and value in (None, "")
        ):
            issues.append(
                _issue(
                    "project.missing_field",
                    "warning",
                    "project",
                    project,
                    field_name,
                    "工程信息未识别",
                    "该项工程信息尚未从附件中识别。",
                    "请对照原始附件核对；确实未提供时可确认后继续。",
                    label="信息缺失",
                    details={"field_name": field_name},
                ),
            )

    for name, records, title, message in (
        ("personnel", personnel, "人员信息为空", "未识别到项目人员。"),
        ("wbs", wbs, "WBS 信息为空", "未识别到 WBS 数据。"),
        ("risks", risks, "风险信息为空", "未识别到风险清单。"),
        (
            "quality_requirements",
            quality,
            "质量指标为空",
            "未识别到工序质量指标。",
        ),
    ):
        if not records:
            issues.append(
                _issue(
                    f"{name}.empty",
                    "warning",
                    name,
                    None,
                    None,
                    title,
                    message,
                    "请确认附件是否包含该分区数据；确实没有时可确认后继续。",
                    label="分区为空",
                ),
            )

    for serial_no, records in _groups(personnel, "serial_no").items():
        if len(records) > 1:
            for record in records:
                issues.append(
                    _issue(
                        "personnel.duplicate_serial",
                        "error",
                        "personnel",
                        record,
                        "serial_no",
                        "人员序号重复",
                        f"人员序号 {serial_no} 对应多条记录。",
                        "请按原始人员名单修正重复序号。",
                        related=records,
                        details={"serial_no": serial_no},
                    ),
                )
    personnel_by_card: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for person in personnel:
        card_no = str(person.get("identity_card_no") or "")
        if card_no:
            personnel_by_card[card_no].append(person)
    for card_no, assignments in sorted(personnel_by_card.items()):
        positions = _groups(assignments, "position_name")
        for position_name, records in positions.items():
            if len(records) > 1:
                for record in records:
                    issues.append(
                        _issue(
                            "personnel.duplicate_position",
                            "error",
                            "personnel",
                            record,
                            "position_name",
                            "人员岗位重复",
                            f"该人员的岗位「{position_name}」重复。",
                            "请删除重复岗位记录或修正岗位名称。",
                            related=records,
                            details={"identity_card_no": card_no},
                        ),
                    )
        unique_positions = list(dict.fromkeys(str(item.get("position_name") or "") for item in assignments))
        if len(unique_positions) > 1:
            for record in assignments:
                issues.append(
                    _issue(
                        "personnel.multiple_positions",
                        "warning",
                        "personnel",
                        record,
                        "position_name",
                        "同一人员兼任多个岗位",
                        f"该人员对应多个岗位（{'、'.join(unique_positions)}）。",
                        "请核对是否为本人兼任；确认后这些岗位将共用同一个平台账号。",
                        related=assignments,
                        details={"identity_card_no": card_no, "positions": unique_positions},
                    ),
                )

    wbs_groups = _groups(wbs, "wbs_code")
    wbs_by_code = {str(code or ""): records[0] for code, records in wbs_groups.items()}
    for code, records in wbs_groups.items():
        if len(records) > 1:
            for record in records:
                issues.append(
                    _issue(
                        "wbs.duplicate_code",
                        "error",
                        "wbs",
                        record,
                        "wbs_code",
                        "WBS 编码重复",
                        f"WBS 编码 {code} 对应多条记录。",
                        "请按原始计划修正重复编码。",
                        related=records,
                        details={"wbs_code": code},
                    ),
                )
    for item in wbs:
        code = str(item.get("wbs_code") or "")
        started = _temporal(item.get("planned_start_at"))
        finished = _temporal(item.get("planned_finish_at"))
        if started and finished and finished < started:
            issues.append(
                _issue(
                    "wbs.date_order",
                    "error",
                    "wbs",
                    item,
                    "planned_finish_at",
                    "计划日期顺序错误",
                    "计划结束时间不能早于计划开始时间。",
                    "请对照原始进度计划修正日期。",
                ),
            )
        if str(item.get("name") or "").strip() in {"任务名称", "未命名任务", "未命名工序"}:
            issues.append(
                _issue(
                    "wbs.placeholder_name",
                    "warning",
                    "wbs",
                    item,
                    "name",
                    "工序名称疑似占位内容",
                    f"当前名称“{item.get('name')}”不像实际工序名称。",
                    "请对照原始进度计划填写真实工序名称。",
                    label="名称待核对",
                    details={"wbs_code": code, "value": item.get("name")},
                ),
            )

    siblings_by_parent: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
    for item in wbs:
        parent = item.get("parent_wbs_code")
        siblings_by_parent[str(parent) if parent not in (None, "") else None].append(item)
    for siblings in siblings_by_parent.values():
        siblings.sort(key=lambda item: _wbs_code_sort_key(str(item.get("wbs_code") or "")))
        latest: dict[str, Any] | None = None
        for item in siblings:
            started = _temporal(item.get("planned_start_at"))
            if started is None:
                continue
            latest_started = _temporal(latest.get("planned_start_at")) if latest else None
            if latest is not None and latest_started and started < latest_started:
                issues.append(
                    _issue(
                        "wbs.sibling_start_order",
                        "warning",
                        "wbs",
                        item,
                        "planned_start_at",
                        "同级工序时间顺序待核对",
                        "该工序的计划开始早于编码在前的同级工序。",
                        "请核对 WBS 编码顺序与原始计划时间。",
                        related=[latest],
                        details={
                            "wbs_code": item.get("wbs_code"),
                            "previous_wbs_code": latest.get("wbs_code"),
                        },
                    ),
                )
            if latest_started is None or started >= latest_started:
                latest = item

    for item in wbs:
        code = str(item.get("wbs_code") or "")
        raw_parent = item.get("parent_wbs_code")
        parent_code = str(raw_parent) if raw_parent not in (None, "") else None
        parent = wbs_by_code.get(parent_code or "") if parent_code else None
        if parent_code:
            if parent is None:
                issues.append(
                    _issue(
                        "wbs.missing_parent",
                        "error",
                        "wbs",
                        item,
                        "parent_wbs_code",
                        "父级 WBS 不存在",
                        f"父级 WBS {parent_code} 不存在。",
                        "请修正父级编码或补充缺失的父级记录。",
                    ),
                )
            else:
                if isinstance(parent.get("level"), int) and isinstance(item.get("level"), int) and parent["level"] >= item["level"]:
                    issues.append(
                        _issue(
                            "wbs.parent_level",
                            "error",
                            "wbs",
                            item,
                            "level",
                            "WBS 层级错误",
                            "子节点层级必须大于父节点层级。",
                            "请修正当前层级或父级关系。",
                            related=[parent],
                        ),
                    )
                started = _temporal(item.get("planned_start_at"))
                parent_started = _temporal(parent.get("planned_start_at"))
                if started and parent_started and started < parent_started:
                    issues.append(
                        _issue(
                            "wbs.before_parent_start",
                            "warning",
                            "wbs",
                            item,
                            "planned_start_at",
                            "子工序早于父级开始",
                            f"该工序的计划开始早于父级 {parent_code}。",
                            "请核对父级汇总日期。",
                            related=[parent],
                        ),
                    )
                finished = _temporal(item.get("planned_finish_at"))
                parent_finished = _temporal(parent.get("planned_finish_at"))
                if finished and parent_finished and finished > parent_finished:
                    issues.append(
                        _issue(
                            "wbs.after_parent_finish",
                            "warning",
                            "wbs",
                            item,
                            "planned_finish_at",
                            "子工序晚于父级完成",
                            f"该工序的计划完成晚于父级 {parent_code}。",
                            "请核对父级汇总日期。",
                            related=[parent],
                        ),
                    )
        expected_parent = code.rsplit(".", 1)[0] if "." in code else None
        if expected_parent != parent_code:
            issues.append(
                _issue(
                    "wbs.parent_from_code",
                    "error",
                    "wbs",
                    item,
                    "parent_wbs_code",
                    "WBS 归属与编码不一致",
                    f"按编码应归属 {expected_parent or '根节点'}，当前为 {parent_code or '空'}。",
                    "请修正父级编码或 WBS 编码。",
                ),
            )
        expected_level = code.count(".") + 1
        if item.get("level") != expected_level:
            issues.append(
                _issue(
                    "wbs.level_from_code",
                    "error",
                    "wbs",
                    item,
                    "level",
                    "WBS 层级与编码不一致",
                    f"按编码应为第 {expected_level} 层，当前为第 {item.get('level')} 层。",
                    "请修正层级或 WBS 编码。",
                ),
            )
        predecessors = item.get("predecessor_wbs_codes") or []
        if not isinstance(predecessors, list):
            predecessors = []
        for raw_predecessor in predecessors:
            predecessor_code = str(raw_predecessor)
            predecessor = wbs_by_code.get(predecessor_code)
            if predecessor_code == code:
                issues.append(
                    _issue(
                        "wbs.self_predecessor",
                        "error",
                        "wbs",
                        item,
                        "predecessor_wbs_codes",
                        "前任 WBS 引用了自身",
                        "WBS 节点不能把自己设为前任。",
                        "请移除该前任关系。",
                    ),
                )
            elif predecessor is None:
                issues.append(
                    _issue(
                        "wbs.missing_predecessor",
                        "error",
                        "wbs",
                        item,
                        "predecessor_wbs_codes",
                        "前任 WBS 不存在",
                        f"前任 WBS {predecessor_code} 不存在。",
                        "请修正前任编码或补充对应记录。",
                    ),
                )
            else:
                started = _temporal(item.get("planned_start_at"))
                predecessor_finished = _temporal(predecessor.get("planned_finish_at"))
                if started and predecessor_finished and started < predecessor_finished:
                    issues.append(
                        _issue(
                            "wbs.predecessor_overlap",
                            "warning",
                            "wbs",
                            item,
                            "planned_start_at",
                            "前后工序时间存在搭接",
                            f"计划开始早于前任 {predecessor_code} 的计划完成。",
                            "如属于搭接施工或开始—开始关系，可核对后继续。",
                            related=[predecessor],
                            details={"predecessor_wbs_code": predecessor_code},
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
                        "wbs",
                        wbs_by_code.get(code),
                        None,
                        "WBS 父子关系循环",
                        "WBS 父子关系存在循环。",
                        "请重新梳理当前记录的父级关系。",
                    ),
                )
                break
            visited.add(cursor)
            cursor = parent_by_code.get(cursor)

    predecessor_by_code = {
        str(item.get("wbs_code") or ""): tuple(str(value) for value in (item.get("predecessor_wbs_codes") or []))
        for item in wbs
        if isinstance(item.get("predecessor_wbs_codes") or [], list)
    }

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
                    "error",
                    "wbs",
                    wbs_by_code.get(code),
                    "predecessor_wbs_codes",
                    "WBS 前置关系循环",
                    "WBS 前置关系存在循环。",
                    "请重新梳理当前记录的前任关系。",
                ),
            )

    for serial_no, records in _groups(risks, "serial_no").items():
        if len(records) > 1:
            for record in records:
                issues.append(
                    _issue(
                        "risks.duplicate_serial",
                        "error",
                        "risks",
                        record,
                        "serial_no",
                        "风险序号重复",
                        f"风险序号 {serial_no} 对应多条记录。",
                        "请按原始风险清单修正重复序号。",
                        related=records,
                    ),
                )
    for item in risks:
        started = _temporal(item.get("risk_window_start_date"))
        finished = _temporal(item.get("risk_window_end_date"))
        if started and finished and finished < started:
            issues.append(
                _issue(
                    "risks.window_date_order",
                    "error",
                    "risks",
                    item,
                    "risk_window_end_date",
                    "风险窗口日期顺序错误",
                    "风险窗口结束日期不能早于开始日期。",
                    "请对照原始风险清单修正日期。",
                ),
            )

    for code, records in _groups(quality, "wbs_code").items():
        if len(records) > 1:
            for record in records:
                issues.append(
                    _issue(
                        "quality.duplicate_wbs",
                        "error",
                        "quality_requirements",
                        record,
                        "wbs_code",
                        "质量指标关联重复",
                        f"WBS {code} 存在多条质量指标记录。",
                        "请合并重复记录或修正关联 WBS。",
                        related=records,
                    ),
                )
    for item in quality:
        code = str(item.get("wbs_code") or "")
        if code not in wbs_by_code:
            issues.append(
                _issue(
                    "quality.missing_wbs",
                    "error",
                    "quality_requirements",
                    item,
                    "wbs_code",
                    "关联 WBS 不存在",
                    f"关联 WBS {code} 不存在。",
                    "请修正关联编码或补充对应 WBS 记录。",
                ),
            )

    unique_issues: list[dict[str, Any]] = []
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
            unique_issues.append(item)
    unique_issues = _batch_issues(unique_issues, draft.get("validation_scope"), [project, *personnel, *wbs, *risks, *quality])
    error_count = sum(item["level"] == "error" for item in unique_issues)
    warning_count = sum(item["level"] == "warning" for item in unique_issues)
    return {
        "ruleset_version": RULESET_VERSION,
        "status": "invalid" if error_count else "ready",
        "validation_issues": unique_issues,
        "requires_semantic_review": [],
        "summary": {
            "project_fields": sum(
                name != "record_id" and value not in (None, "")
                for name, value in project.items()
            ),
            "personnel": len(personnel),
            "wbs": len(wbs),
            "risks": len(risks),
            "quality_requirements": len(quality),
            "errors": error_count,
            "warnings": warning_count,
        },
    }
