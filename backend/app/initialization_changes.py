"""Reviewable, non-destructive changes from initialization draft records.

Draft record IDs identify imported proposals; formal IDs identify live business
records. Neither an omitted section nor an empty imported field means deletion.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal
import hashlib
import json
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .engineering_document_catalog import reconcile_name_based_catalogue_permissions
from .initialization_draft_queries import sync_initialization_draft_section_records
from .models import (
    EngineeringDocumentSyncState, Project, ProjectInitializationDraft, ProjectInitializationDraftRecord,
    ProjectInitializationDraftSection, ProjectMember, ProjectMemberPosition,
    ProjectPosition, QualityMetric, RiskSource, User, WbsItem, WbsPredecessor,
)
from .personnel_policy import (
    normalize_project_position_name, reconcile_user_management_roles,
    require_supported_project_position,
)
from .project_initialization import (
    InitializationApplyError, PersonnelDraft, ProjectDetailsDraft,
    QualityRequirementDraft, RiskDraftItem, WbsDraft, build_initialization_state,
    suggest_unique_username,
)
from .security import hash_password


SECTIONS = ("project", "personnel", "wbs", "risks", "quality_requirements")
MODELS = {
    "project": ProjectDetailsDraft, "personnel": PersonnelDraft,
    "wbs": WbsDraft, "risks": RiskDraftItem,
    "quality_requirements": QualityRequirementDraft,
}
FORMAL_MODELS = {"wbs": WbsItem, "risks": RiskSource, "quality_requirements": QualityMetric}
FIELD_ADAPTERS = {
    (section, name): TypeAdapter(field.rebuild_annotation())
    for section, model in MODELS.items() for name, field in model.model_fields.items()
    if name != "record_id"
}


def _json(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def _hash(value: Any) -> str:
    def normalize(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: normalize(content) for key, content in item.items()}
        if isinstance(item, list):
            return [normalize(content) for content in item]
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            # Numeric columns can remain Python ints before expiration and
            # become Decimals/floats after a DB reload; their value is equal.
            return {"$number": format(Decimal(str(item)).normalize(), "f")}
        return item

    return hashlib.sha256(json.dumps(
        normalize(_json(value)), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _nonempty(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {} and (
        not isinstance(value, str) or bool(value.strip())
    )


def _patch(section: str, raw: dict[str, Any]) -> dict[str, Any]:
    allowed = set(MODELS[section].model_fields) - {"record_id"}
    result = {}
    for key, value in raw.items():
        if key not in allowed or not _nonempty(value):
            continue
        if isinstance(value, str):
            value = value.strip()
        try:
            value = FIELD_ADAPTERS[(section, key)].validate_python(value)
        except ValidationError:
            # Keep the observation addressable; selected-row validation below
            # produces the precise field issue rather than losing the draft.
            pass
        result[key] = _json(value)
        if key == "predecessor_wbs_codes" and isinstance(result[key], list) and all(isinstance(item, str) for item in result[key]):
            result[key] = sorted(set(result[key]))
    if "position_name" in result:
        result["position_name"] = normalize_project_position_name(result["position_name"])
    return result


def _canonical(section: str, row: dict[str, Any]) -> dict[str, Any]:
    """Keep historical rows readable even if their old required fields are blank."""
    result: dict[str, Any] = {}
    for name, field in MODELS[section].model_fields.items():
        if name == "record_id":
            continue
        if name in row:
            value = row[name]
            try:
                value = FIELD_ADAPTERS[(section, name)].validate_python(value)
            except ValidationError:
                pass
            result[name] = _json(value)
            if name == "predecessor_wbs_codes" and isinstance(result[name], list):
                result[name] = sorted(set(result[name]))
        elif field.is_required():
            result[name] = None
        else:
            result[name] = _json(field.get_default(call_default_factory=True))
    return result


def _baseline(db: Session, project: Project) -> tuple[dict[str, Any], str]:
    state = build_initialization_state(db, project)
    data = {section: deepcopy(state[section]) for section in SECTIONS}
    for item in data["wbs"]:
        item["predecessor_wbs_codes"] = sorted(item["predecessor_wbs_codes"])
    # Include operational fields too: a review must become stale if somebody
    # edits a live row while the user is comparing the proposed import.
    fingerprint: dict[str, Any] = deepcopy(data)
    for section, model in FORMAL_MODELS.items():
        fingerprint[f"{section}_operational_rows"] = [
            {column.name: _json(getattr(row, column.name)) for column in model.__table__.columns}
            for row in db.scalars(select(model).where(
                model.project_id == project.id,
            ).order_by(model.id)).all()
        ]
    return data, _hash(fingerprint)


def _title(section: str, data: dict[str, Any]) -> str:
    if section == "personnel":
        return " · ".join(str(data.get(key) or "") for key in ("real_name", "position_name"))
    if section == "wbs":
        return " · ".join(str(data.get(key) or "") for key in ("wbs_code", "name"))
    if section == "risks":
        return " · ".join(str(data.get(key) or "") for key in ("related_process_name", "risk_part"))
    if section == "quality_requirements":
        return str(data.get("wbs_code") or "质量指标")
    return "工程信息"


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _match(section: str, patch: dict[str, Any], index: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    def eq(row: dict[str, Any], field: str) -> bool:
        return bool(_norm(patch.get(field))) and _norm(row.get(field)) == _norm(patch.get(field))

    def matches(field: str) -> list[dict[str, Any]]:
        value = _norm(patch.get(field))
        return index.get(field, {}).get(value, []) if value else []

    if section == "personnel":
        exact = [row for row in matches("identity_card_no") if eq(row, "position_name")]
        # Holding another position is a valid new assignment for an existing
        # account. Name-only matches are ambiguous and require a decision.
        weak = [row for row in matches("real_name") if not eq(row, "identity_card_no")]
    elif section == "wbs":
        exact = matches("wbs_code")
        weak = matches("name") + matches("msp_uid")
    elif section == "quality_requirements":
        exact = matches("wbs_code")
        weak = []
    else:
        exact = [row for row in matches("related_process_name") if eq(row, "risk_part")]
        weak = matches("risk_part") + matches("serial_no")
    if len(exact) == 1:
        return exact[0], []
    return None, list({row["id"]: row for row in exact or weak}.values())


def _issue(change: dict[str, Any] | None, message: str, *, rule: str = "conflict", field: str | None = None) -> dict[str, Any]:
    return {
        "rule_id": f"platform.change.{rule}", "level": "error",
        "section": change["section"] if change else "project",
        "target_record_id": change["record_id"] if change else None,
        "change_key": change["key"] if change else None,
        "field_name": field, "label": "待处理", "title": "变更需要处理",
        "message": message, "suggestion": "请核对该项后重新预览。",
        "related_record_ids": [], "details": {"source": "initialization_changes"},
    }


def _records(db: Session, draft: ProjectInitializationDraft) -> list[ProjectInitializationDraftRecord]:
    rows = list(db.scalars(select(ProjectInitializationDraftRecord).where(
        ProjectInitializationDraftRecord.draft_id == draft.id,
        ProjectInitializationDraftRecord.active.is_(True),
    ).order_by(ProjectInitializationDraftRecord.id)).all())
    existing_sections = {row.section_id for row in rows}
    for section in db.scalars(select(ProjectInitializationDraftSection).where(
        ProjectInitializationDraftSection.draft_id == draft.id,
    ).order_by(ProjectInitializationDraftSection.id)).all():
        if section.id not in existing_sections and section.payload:
            rows.extend(sync_initialization_draft_section_records(db, section))
    return sorted(rows, key=lambda item: item.id)


def build_change_plan(
    db: Session,
    draft: ProjectInitializationDraft,
    selected_keys: list[str] | None = None,
    resolutions: dict[str, int | None] | None = None,
) -> dict[str, Any]:
    """Build a deterministic preview from current formal data and raw proposals."""
    from .initialization_change_models import AppliedInitializationChange

    project = db.get(Project, draft.project_id)
    if project is None:
        raise InitializationApplyError("草稿关联项目不存在")
    baseline, baseline_hash = _baseline(db, project)
    users = list(db.scalars(select(User)).all())
    users_by_card = {user.identity_card_no: user for user in users}
    match_indexes: dict[str, Any] = {}
    for section in SECTIONS[1:]:
        index: dict[str, Any] = defaultdict(lambda: defaultdict(list))
        for row in baseline[section]:
            for field in ("identity_card_no", "real_name", "wbs_code", "name", "msp_uid", "related_process_name", "risk_part", "serial_no"):
                value = _norm(row.get(field))
                if value:
                    index[field][value].append(row)
        match_indexes[section] = index
    records = _records(db, draft)
    ledger = {row.change_key: row for row in db.scalars(select(AppliedInitializationChange).where(
        AppliedInitializationChange.draft_id == draft.id,
    )).all()}
    resolutions = resolutions or {}
    requested = None if selected_keys is None else set(selected_keys)
    changes: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for record in records:
        section = record.section
        if section not in SECTIONS:
            continue
        patch = _patch(section, dict(record.payload or {}))
        proposals = [(f"{record.id}:{field}", {field: value}) for field, value in patch.items()] if section == "project" else [(str(record.id), patch)]
        for key, proposal in proposals:
            if not proposal:
                continue
            payload_hash = _hash({"section": section, "patch": proposal})
            candidates: list[dict[str, Any]] = []
            if section == "project":
                target = baseline["project"]
            else:
                target, candidates = _match(section, proposal, match_indexes[section])
            resolution_error = None
            if key in resolutions:
                decision = resolutions[key]
                if candidates:
                    if decision is None:
                        target, candidates = None, []
                    else:
                        target = next((row for row in candidates if row["id"] == decision), None)
                        if target is None:
                            resolution_error = "选择的旧记录不属于当前冲突候选，请重新核对。"
                        else:
                            candidates = []
                elif decision != (target["id"] if target else None):
                    resolution_error = "当前变更不支持该匹配决定，请重新预览。"
            before = _canonical(section, target) if target else None
            after = {**(before or {}), **proposal}
            account_name_warning = None
            account = users_by_card.get(after.get("identity_card_no")) if section == "personnel" else None
            if account is not None and (before is None or before.get("identity_card_no") != account.identity_card_no):
                observed_name = after.get("real_name")
                # Adding this person to a project reuses the global identity;
                # it does not authorize changing their name in other projects.
                after["real_name"] = account.real_name
                if observed_name and observed_name != account.real_name:
                    account_name_warning = f"上传姓名「{observed_name}」与已有账号姓名「{account.real_name}」不同，本次任职沿用已有账号姓名及登录凭证。"
            fields = [{"name": field, "before": (before or {}).get(field), "after": value}
                      for field, value in after.items() if (before or {}).get(field) != value]
            operation = "conflict" if candidates or resolution_error else (
                "add" if target is None else "update" if fields else "unchanged"
            )
            applied = ledger.get(key)
            if applied is not None and applied.payload_hash == payload_hash:
                operation = "applied"
            selected = operation in {"add", "update"} if requested is None else key in requested
            if operation in {"applied", "unchanged"}:
                selected = False
            change = {
                "key": key, "record_id": record.id, "section": section,
                "title": _title(section, after), "operation": operation,
                "target_id": target["id"] if target else None,
                "before": before, "after": after, "fields": fields,
                "selected": selected, "candidates": [{"id": row["id"], "title": _title(section, row)} for row in candidates],
                "payload_hash": payload_hash,
            }
            changes.append(change)
            if account_name_warning and selected and operation in {"add", "update"}:
                warning = _issue(change, account_name_warning, rule="existing_account_name", field="real_name")
                warning.update({"level": "warning", "label": "账号复用", "title": "沿用已有账号姓名",
                                "suggestion": "请核对身份证号；如需更正账号姓名，请在人员信息中明确修改。"})
                issues.append(warning)
            if resolution_error:
                issues.append(_issue(change, resolution_error, rule="resolution"))
            elif operation == "conflict" and selected:
                item = _issue(change, "无法唯一确定新资料对应的旧记录，请选择更新哪条记录，或明确作为新增。")
                issues.append(item)

    known = {change["key"] for change in changes}
    for key in (requested or set()) - known:
        issues.append(_issue(None, f"变更 {key} 已失效，请重新预览。", rule="selection"))
    for key in resolutions.keys() - known:
        issues.append(_issue(None, f"匹配决定 {key} 已失效，请重新预览。", rule="resolution"))

    # Allocate serials for additions; updating a record must not accidentally
    # take another record's number because the uploaded sheet restarted at 1.
    for section in ("personnel", "risks"):
        occupied = {row["serial_no"]: row["id"] for row in baseline[section]}
        for change in changes:
            if change["section"] != section or not change["selected"] or change["operation"] not in {"add", "update"}:
                continue
            serial = change["after"].get("serial_no")
            if change["operation"] == "update":
                previous_serial = change["before"]["serial_no"]
                if not isinstance(serial, int) or (serial in occupied and occupied[serial] != change["target_id"]):
                    serial = previous_serial
                if serial != previous_serial:
                    occupied.pop(previous_serial, None)
            elif not isinstance(serial, int) or serial <= 0 or serial in occupied:
                serial = max(occupied, default=0) + 1
            change["after"]["serial_no"] = serial
            occupied[serial] = change["target_id"] or -change["record_id"]
            before = change["before"] or {}
            change["fields"] = [{"name": field, "before": before.get(field), "after": value}
                                for field, value in change["after"].items() if before.get(field) != value]

    # Synthetic IDs are isolated from every draft row ID, including rows in a
    # different draft; callers use the mapping to route validation annotations.
    max_record_id = db.scalar(select(ProjectInitializationDraftRecord.id).order_by(ProjectInitializationDraftRecord.id.desc()).limit(1)) or 0
    next_id = max_record_id + 1
    effective: dict[str, Any] = {}
    targets: dict[str, dict[str, Any]] = {}
    effective_by_target: dict[tuple[str, int], dict[str, Any]] = {}
    for section in SECTIONS:
        rows = [baseline[section]] if section == "project" else baseline[section]
        composed = []
        for row in rows:
            record = {**_canonical(section, row), "record_id": next_id}
            targets[str(next_id)] = {
                "section": section, "change_key": None, "change_keys": [],
                "record_id": None, "target_id": row["id"], "is_existing": True,
                "field_changes": {},
            }
            effective_by_target[(section, row["id"])] = record
            composed.append(record)
            next_id += 1
        effective[section] = composed[0] if section == "project" else composed

    selected_targets: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for change in changes:
        if not change["selected"] or change["operation"] not in {"add", "update"}:
            continue
        section = change["section"]
        if section != "project" and change["target_id"] is not None:
            selected_targets[(section, change["target_id"])].append(change)
        try:
            # Construct defaults for nullable WBS fields that are required in
            # the full payload contract but legitimately absent in a patch.
            candidate = _canonical(section, change["after"])
            validated = _json(MODELS[section].model_validate(candidate).model_dump(exclude={"record_id"}))
        except ValidationError as exc:
            for error in exc.errors(include_url=False):
                field = str(error["loc"][0]) if error["loc"] else None
                issues.append(_issue(change, f"{field or '记录'}：{error['msg']}", rule="invalid_record", field=field))
            continue
        change["after"] = validated
        if section == "project":
            # Validate each project proposal against the full accumulated row,
            # but only apply the fields explicitly confirmed by this change.
            record = effective["project"]
            for field in change["fields"]:
                record[field["name"]] = validated[field["name"]]
        elif change["target_id"] is not None:
            record = effective_by_target[(section, change["target_id"])]
            record.update(validated)
        else:
            record = {**validated, "record_id": next_id}
            targets[str(next_id)] = {
                "section": section, "change_key": None, "change_keys": [],
                "record_id": None, "target_id": None, "is_existing": False,
                "field_changes": {},
            }
            next_id += 1
            effective[section].append(record)
        mapping = targets[str(record["record_id"])]
        mapping["change_key"] = mapping["change_key"] or change["key"]
        mapping["change_keys"].append(change["key"])
        mapping["record_id"] = change["record_id"]
        for field in change["fields"]:
            mapping["field_changes"][field["name"]] = change["key"]
    for group in selected_targets.values():
        if len(group) > 1:
            for change in group:
                issues.append(_issue(change, "本次选择中有多条草稿修改同一旧记录，请保留一条后提交。", rule="duplicate_target"))

    # Imported identifiers may be corrected explicitly, but a rename must not
    # silently change references that were outside the reviewed selection.
    for change in changes:
        if not change["selected"] or change["section"] != "wbs" or change["operation"] != "update":
            continue
        old_code = change["before"]["wbs_code"]
        if change["after"].get("wbs_code") == old_code:
            continue
        dependent = any(row.get("parent_wbs_code") == old_code or old_code in row.get("predecessor_wbs_codes", []) for row in baseline["wbs"])
        dependent = dependent or any(row["wbs_code"] == old_code for row in baseline["quality_requirements"])
        if dependent:
            issues.append(_issue(change, "该 WBS 编码已有父子、前置或质量关联，请先在项目配置中调整关联编码后再导入。", rule="referenced_code", field="wbs_code"))

    unavailable = {user.username for user in users}
    credentials: dict[str, dict[str, Any]] = {}
    existing_accounts: dict[str, dict[str, Any]] = {}
    for change in changes:
        if change["section"] == "personnel":
            card = change["after"].get("identity_card_no")
            account = users_by_card.get(card) if isinstance(card, str) else None
            if account is not None:
                # Only expose the public account identity for personnel in this
                # draft, never credential hashes or unrelated platform accounts.
                existing_accounts[card] = {
                    "identity_card_no": card, "username": account.username,
                    "real_name": account.real_name,
                }
        if change["selected"] and change["section"] == "personnel" and change["operation"] in {"add", "update"}:
            person = change["after"]
            card = person.get("identity_card_no")
            if card and card not in users_by_card and card not in credentials:
                username = suggest_unique_username(person.get("real_name") or "", card, unavailable)
                unavailable.add(username)
                credentials[card] = {
                    "identity_card_no": card, "real_name": person.get("real_name"),
                    "position_name": person.get("position_name") or "",
                    "suggested_username": username, "change_keys": [],
                }
            if card in credentials:
                credentials[card]["change_keys"].append(change["key"])
    return {
        "draft_id": draft.id, "draft_revision": draft.revision,
        "baseline_hash": baseline_hash, "changes": changes,
        "selected_keys": [change["key"] for change in changes if change["selected"]],
        "resolutions": resolutions, "effective_payload": effective,
        "record_targets": targets, "issues": issues,
        "required_personnel_credentials": list(credentials.values()),
        "existing_personnel_accounts": list(existing_accounts.values()),
    }


def _credentials(db: Session, plan: dict[str, Any], supplied: list[Any]) -> dict[str, dict[str, Any]]:
    from .project_initialization import PersonnelCredentialInput

    result: dict[str, dict[str, Any]] = {}
    usernames = {user.username.casefold(): user.identity_card_no for user in db.scalars(select(User)).all()}
    for item in supplied:
        data = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        try:
            data = PersonnelCredentialInput.model_validate(data).model_dump()
        except ValidationError as exc:
            raise InitializationApplyError("新人员账号或初始密码不符合要求") from exc
        card = data["identity_card_no"]
        if card in result:
            raise InitializationApplyError("人员登录凭证中存在重复身份证号")
        owner = usernames.get(data["username"].casefold())
        if owner is not None and owner != card:
            raise InitializationApplyError(f"登录账号 {data['username']} 已被其他人员使用")
        usernames[data["username"].casefold()] = card
        result[card] = data
    for person in plan["required_personnel_credentials"]:
        if person["identity_card_no"] not in result:
            raise InitializationApplyError(f"新人员「{person['real_name']}」缺少登录账号和初始密码")
    return result


def apply_change_plan(
    db: Session,
    draft: ProjectInitializationDraft,
    plan: dict[str, Any],
    personnel_credentials: list[Any],
) -> dict[str, Any]:
    """Apply a server-built, validated selection without committing its transaction."""
    from .initialization_change_models import AppliedInitializationChange

    if plan["draft_id"] != draft.id or plan["draft_revision"] != draft.revision:
        raise InitializationApplyError("草稿已更新，请重新预览并确认。")
    project = db.get(Project, draft.project_id)
    if project is None or _baseline(db, project)[1] != plan["baseline_hash"]:
        raise InitializationApplyError("正式数据已更新，请重新对比差异后确认。")
    errors = [issue for issue in plan.get("issues", []) if issue.get("level") == "error" and issue.get("blocking", True)]
    if errors:
        raise InitializationApplyError("所选变更仍有需要处理的问题", errors)
    selected = [change for change in plan["changes"] if change["selected"] and change["operation"] in {"add", "update"}]
    if not selected:
        raise InitializationApplyError("请至少选择一项新增或更新内容。")
    credential_by_card = _credentials(db, plan, personnel_credentials)
    counts = {section: 0 for section in SECTIONS}
    operations = {"add": 0, "update": 0}
    created_usernames: list[str] = []
    affected_users: set[int] = set()
    applied_targets: dict[str, int] = {}

    for change in selected:
        section = change["section"]
        counts[section] += 1
        operations[change["operation"]] += 1
        if section == "project":
            converted = ProjectDetailsDraft.model_validate(change["after"])
            for field in change["fields"]:
                setattr(project, field["name"], getattr(converted, field["name"]))
            applied_targets[change["key"]] = project.id
        elif section == "personnel":
            person = PersonnelDraft.model_validate(change["after"])
            position_name = require_supported_project_position(person.position_name)
            assignment = db.get(ProjectMemberPosition, change["target_id"]) if change["target_id"] else None
            if assignment is not None and assignment.project_id != project.id:
                raise InitializationApplyError("人员记录不属于当前项目。")
            if assignment:
                previous_member = db.get(ProjectMember, assignment.project_member_id)
                if previous_member:
                    affected_users.add(previous_member.user_id)
            user = db.scalar(select(User).where(User.identity_card_no == person.identity_card_no))
            if user is None:
                credential = credential_by_card[person.identity_card_no]
                user = User(username=credential["username"], password_hash=hash_password(credential["initial_password"]),
                            identity_card_no=person.identity_card_no, real_name=person.real_name, role="user")
                db.add(user)
                db.flush()
                created_usernames.append(user.username)
            elif change["operation"] == "update" and change["before"].get("identity_card_no") == person.identity_card_no and any(field["name"] == "real_name" for field in change["fields"]):
                user.real_name = person.real_name
            affected_users.add(user.id)
            member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id))
            if member is None:
                member = ProjectMember(project_id=project.id, user_id=user.id)
                db.add(member)
                db.flush()
            position = db.scalar(select(ProjectPosition).where(ProjectPosition.project_id == project.id, ProjectPosition.position_name == position_name))
            if position is None:
                position = ProjectPosition(project_id=project.id, position_name=position_name)
                db.add(position)
                db.flush()
            if assignment is None:
                assignment = ProjectMemberPosition(project_id=project.id)
                db.add(assignment)
            assignment.project_member_id = member.id
            assignment.position_id = position.id
            assignment.serial_no = person.serial_no
            assignment.certificate_no = person.certificate_no
            assignment.responsibility_description = person.responsibility_description
            db.flush()
            applied_targets[change["key"]] = assignment.id

    # Materialize all WBS rows before resolving parent and predecessor links.
    for section in ("wbs", "risks", "quality_requirements"):
        for change in selected:
            if change["section"] != section:
                continue
            model = FORMAL_MODELS[section]
            row = db.get(model, change["target_id"]) if change["target_id"] else None
            if row is not None and row.project_id != project.id:
                raise InitializationApplyError("变更目标不属于当前项目。")
            converted = MODELS[section].model_validate(change["after"]).model_dump(exclude={"record_id"})
            if row is None:
                row = model(project_id=project.id)
                db.add(row)
            changed_fields = {field["name"] for field in change["fields"]}
            for field, value in converted.items():
                if field not in {"parent_wbs_code", "predecessor_wbs_codes"} and (change["operation"] == "add" or field in changed_fields):
                    setattr(row, field, value)
            db.flush()
            applied_targets[change["key"]] = row.id
        if section == "wbs":
            wbs_by_code = {row.wbs_code: row for row in db.scalars(select(WbsItem).where(WbsItem.project_id == project.id)).all()}
            for change in selected:
                if change["section"] != "wbs":
                    continue
                row = db.get(WbsItem, applied_targets[change["key"]])
                after = change["after"]
                changed_fields = {field["name"] for field in change["fields"]}
                parent_code = after.get("parent_wbs_code")
                if change["operation"] == "add" or "parent_wbs_code" in changed_fields:
                    if parent_code and parent_code not in wbs_by_code:
                        raise InitializationApplyError(f"父级 WBS {parent_code} 不存在。")
                    row.parent_id = wbs_by_code[parent_code].id if parent_code else None
                if change["operation"] == "add" or "predecessor_wbs_codes" in changed_fields:
                    db.execute(delete(WbsPredecessor).where(WbsPredecessor.wbs_item_id == row.id))
                    for code in dict.fromkeys(after.get("predecessor_wbs_codes") or []):
                        if code not in wbs_by_code:
                            raise InitializationApplyError(f"前任 WBS {code} 不存在。")
                        db.add(WbsPredecessor(wbs_item_id=row.id, predecessor_wbs_item_id=wbs_by_code[code].id))
            db.flush()

    roles = reconcile_user_management_roles(db, affected_users) if affected_users else {}
    permission_policy = reconcile_name_based_catalogue_permissions(
        db, project.id,
        enable_restricted=db.get(EngineeringDocumentSyncState, project.id) is None,
    ) if affected_users else {"applied": False}
    existing_ledger = {row.change_key: row for row in db.scalars(select(AppliedInitializationChange).where(
        AppliedInitializationChange.draft_id == draft.id,
    )).all()}
    for change in selected:
        entry = existing_ledger.get(change["key"])
        if entry is None:
            entry = AppliedInitializationChange(draft_id=draft.id, change_key=change["key"])
            db.add(entry)
        entry.record_id = change["record_id"]
        entry.payload_hash = change["payload_hash"]
        entry.target_id = applied_targets[change["key"]]
        entry.applied_at = datetime.now(UTC)
    db.flush()
    return {
        "draft_id": draft.id, "project_id": project.id,
        "status": "partially_applied", "counts": counts, "operations": operations,
        "applied_keys": list(applied_targets), "created_usernames": created_usernames,
        "account_roles": roles, "permission_policy": permission_policy,
    }
