from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.agent_context_gateway import resolve_tool_context
from backend.app.database_interaction_router import ExecuteInteractionRequest, execute_interaction
from backend.app.database_interactions import (
    TableInteractionInput, TablePolicyInput,
    _normalize_initialization_section_payload,
    bootstrap_declarative_catalog,
    execute_table_interaction,
    resolve_assigned_interaction,
    update_agent_assignments,
    update_interaction, update_table_policy,
)
from backend.app.db import Base
from backend.app.initialization_patch import ProjectInitializationPatchPayload
from backend.app.models import (
    AgentConversation, DatabaseInteraction, DatabaseInteractionTablePolicy,
    OperationLog, PlatformSchemaVersion, Project, ProjectInitializationDraft,
    ProjectInitializationDraftRecord, ProjectInitializationDraftSection,
    ProjectMember, ProjectMemberPosition, ProjectPosition, QualityMetric,
    RiskSource, User, WbsItem,
)


@pytest.fixture()
def database():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(username="initializer", password_hash="hidden", role="user",
                    real_name="资料员甲", identity_card_no="ID-PRIVATE")
        project = Project(name="当前项目", engineering_type_description="房建")
        db.add_all([user, project])
        db.flush()
        member = ProjectMember(project_id=project.id, user_id=user.id)
        conversation = AgentConversation(
            project_id=project.id, user_id=user.id, agent_id="initializer",
            agent_name="初始化助手", conversation_type="initialization",
            title="新会话", agentscope_session_id="initialization-session", status="active",
        )
        db.add_all([member, conversation])
        db.commit()
        bootstrap_declarative_catalog(db)
        interaction = db.scalar(select(DatabaseInteraction).where(
            DatabaseInteraction.key == "dobby_get_project_initialization_state",
        ))
        update_agent_assignments(db, "initializer", [interaction.id])
        yield db, resolve_tool_context(db, conversation.agentscope_session_id), interaction
    engine.dispose()


def _read(database, **arguments):
    db, context, _ = database
    return execute_interaction(ExecuteInteractionRequest(
        agentscope_session_id=context.conversation.agentscope_session_id,
        actor_agent_id="initializer", platform_agent_id=context.conversation.agent_id,
        interaction_key="dobby_get_project_initialization_state", arguments=arguments,
    ), db)["data"]


def test_reader_returns_five_confirmed_sections_across_sessions_with_bounded_pages(database):
    db, context, _ = database
    other = Project(name="其他项目")
    position = ProjectPosition(project_id=context.project.id, position_name="资料员")
    db.add_all([other, position])
    db.flush()
    db.add(ProjectMemberPosition(
        project_id=context.project.id, project_member_id=context.membership.id,
        position_id=position.id, serial_no=1, certificate_no="资料证",
        responsibility_description="资料管理",
    ))
    for index in range(23):
        db.add(WbsItem(project_id=context.project.id, wbs_code=str(index + 1),
                       name=f"正式工序{index + 1}", level=1, sort_order=index))
    db.add(WbsItem(project_id=other.id, wbs_code="1", name="其他项目机密", level=1))
    db.add(RiskSource(project_id=context.project.id, serial_no=1,
                      related_process_name="正式工序1", risk_part="基坑",
                      risk_level="较大", evaluation_condition="深基坑"))
    db.add(QualityMetric(project_id=context.project.id, wbs_code="1",
                         quality_acceptance_item="平整度", control_indicator="5mm",
                         inspection_frequency="每日", related_documents="检验记录"))
    # No draft exists in this new session: the baseline must still be visible.
    db.commit()
    overview = _read(database)
    assert overview["has_existing_data"] is True
    assert {key: value["count"] for key, value in overview["sections"].items()} == {
        "project": 1, "personnel": 1, "wbs": 23, "risks": 1, "quality_requirements": 1,
    }
    assert "items" not in overview and "latest_draft" not in overview
    first = _read(database, section="wbs", fields=["id", "wbs_code", "name"])
    second = _read(database, section="wbs", offset=first["page"]["next_offset"])
    assert len(first["items"]) == 20 and len(second["items"]) == 3
    assert second["page"]["has_more"] is False
    assert second["items"][-1]["name"] == "正式工序23"
    assert "其他项目机密" not in str(first) + str(second)
    assert _read(database, section="project")["items"][0]["engineering_type_description"] == "房建"
    person = _read(database, section="personnel")["items"][0]
    assert person["real_name"] == "资料员甲" and person["position_name"] == "资料员"
    assert "identity_card_no" not in person and "role" not in person and "password_hash" not in person
    assert _read(database, section="risks")["items"][0]["risk_part"] == "基坑"
    assert _read(database, section="quality_requirements")["items"][0]["control_indicator"] == "5mm"
    log = db.scalar(select(OperationLog).where(OperationLog.action == "agent_database_read").order_by(OperationLog.id.desc()))
    assert log.project_id == context.project.id and log.operator_id == context.user.id


@pytest.mark.parametrize("arguments", [
    {"project_id": 999}, {"conversation_id": 999}, {"section": "all"},
    {"section": "wbs", "limit": 21}, {"section": "wbs", "offset": -1},
    {"section": "wbs", "limit": True}, {"section": "wbs", "fields": []},
])
def test_reader_rejects_scope_override_and_unbounded_arguments(database, arguments):
    with pytest.raises(HTTPException) as error:
        _read(database, **arguments)
    assert error.value.status_code == 422


@pytest.mark.parametrize("boundary", ["unassigned", "membership", "conversation", "role", "disabled"])
def test_reader_enforces_assignment_account_and_policy_permissions(database, boundary):
    db, context, interaction = database
    if boundary == "unassigned":
        update_agent_assignments(db, "initializer", [])
    elif boundary == "membership":
        db.delete(context.membership)
    elif boundary == "conversation":
        context.conversation.conversation_type = "business"
    else:
        policy = db.get(DatabaseInteractionTablePolicy, interaction.table_policy_id)
        if boundary == "role":
            policy.minimum_role = "admin"
        else:
            policy.enabled = False
    db.commit()
    with pytest.raises(HTTPException) as error:
        _read(database)
    assert error.value.status_code in {403, 409}


def test_reader_respects_business_table_field_restrictions(database):
    db, context, _ = database
    policy = db.scalar(select(DatabaseInteractionTablePolicy).where(
        DatabaseInteractionTablePolicy.table_name == "projects",
    ))
    policy.readable_fields = ["name"]
    db.commit()
    assert _read(database, section="project")["items"] == [{"name": context.project.name}]
    with pytest.raises(HTTPException) as error:
        _read(database, section="project", fields=["engineering_type_description"])
    assert error.value.status_code == 403
    personnel_policy = db.scalar(select(DatabaseInteractionTablePolicy).where(
        DatabaseInteractionTablePolicy.table_name == "users",
    ))
    personnel_policy.enabled = False
    db.commit()
    assert _read(database)["sections"]["personnel"] == {"readable": False}


def test_catalog_upgrade_refreshes_reader_without_resetting_custom_access(database):
    db, _, interaction = database
    identity = interaction.id
    interaction.input_schema = {"type": "object", "properties": {"record_id": {"type": "integer"}}}
    interaction.runtime_policy = {}
    interaction.allowed_conversation_types = ["business"]
    interaction.enabled = False
    interaction.access_mode = "workflow"
    policy = db.get(DatabaseInteractionTablePolicy, interaction.table_policy_id)
    policy.minimum_role = "admin"
    db.delete(db.get(PlatformSchemaVersion, 21))
    db.commit()
    bootstrap_declarative_catalog(db)
    db.refresh(interaction)
    assert interaction.id == identity
    assert interaction.runtime_policy == {"handler": "project_initialization_state"}
    assert "section" in interaction.input_schema["properties"]
    assert interaction.input_schema["properties"]["limit"]["maximum"] == 20
    assert interaction.enabled is False and interaction.access_mode == "workflow"
    assert interaction.allowed_conversation_types == ["business"]
    assert policy.minimum_role == "admin"


def test_sparse_wbs_observation_survives_database_writer_without_implicit_defaults(database):
    db, context, _ = database
    draft = ProjectInitializationDraft(
        project_id=context.project.id, conversation_id=context.conversation.id,
        created_by_user_id=context.user.id, status="building", payload={},
    )
    db.add(draft)
    db.commit()
    writer = db.scalar(select(DatabaseInteraction).where(
        DatabaseInteraction.key == "dobby_create_initialization_wbs_section",
    ))
    update_agent_assignments(db, "wbs-specialist", [writer.id])
    interaction, policy = resolve_assigned_interaction(db, "wbs-specialist", writer.key)
    item_schema = interaction.input_schema["properties"]["values"]["properties"]["payload"]["items"]
    assert item_schema.get("required", []) == []
    result, _ = execute_table_interaction(db, context, interaction, policy, {
        "values": {"draft_id": draft.id, "payload": [{"wbs_code": "1", "progress_percent": 0}],
                   "source_files": ["本周进度.xlsx"], "extraction_notes": []},
    }, actor_agent_id="wbs-specialist")
    section = db.get(ProjectInitializationDraftSection, result["record_id"])
    record = db.scalar(select(ProjectInitializationDraftRecord).where(
        ProjectInitializationDraftRecord.section_id == section.id,
    ))
    assert section.payload == [{"wbs_code": "1", "progress_percent": 0}]
    assert record.payload == section.payload[0]


@pytest.mark.parametrize("section, observation", [
    ("project", {"contract_amount_wan_yuan": 0}),
    ("personnel", [{"identity_card_no": "ID1", "position_name": "资料员", "certificate_no": "新证号"}]),
    ("risks", [{"related_process_name": "开挖", "risk_part": "基坑", "risk_level": "重大"}]),
    ("quality_requirements", [{"wbs_code": "1", "control_indicator": "5mm"}]),
])
def test_sparse_models_keep_only_observed_fields(section, observation):
    result = _normalize_initialization_section_payload(section, observation)
    actual = result if isinstance(result, dict) else result[0]
    supplied = observation if isinstance(observation, dict) else observation[0]
    assert set(actual) == set(supplied)
    payload = ProjectInitializationPatchPayload.model_validate({section: result})
    assert payload.model_dump(mode="json", exclude_unset=True) == {section: result}


@pytest.mark.parametrize("observation", [
    [{"wbs_code": "1", "children": []}],
])
def test_sparse_models_reject_unknown_transport_fields(observation):
    with pytest.raises(HTTPException) as error:
        _normalize_initialization_section_payload("wbs", observation)
    assert error.value.status_code == 422


def test_management_edits_preserve_state_finalizer_and_specialist_schemas(database):
    db, _, state = database
    policy = db.get(DatabaseInteractionTablePolicy, state.table_policy_id)
    policy_input = TablePolicyInput(**{
        name: getattr(policy, name) for name in TablePolicyInput.model_fields
    })
    update_table_policy(db, policy.id, policy_input)
    assert "section" in state.input_schema["properties"]
    finalizer = db.scalar(select(DatabaseInteraction).where(
        DatabaseInteraction.key == "dobby_finalize_project_initialization_draft",
    ))
    assert finalizer.input_schema["required"] == ["record_id"]
    for key in (state.key, "dobby_create_initialization_wbs_section"):
        interaction = db.scalar(select(DatabaseInteraction).where(DatabaseInteraction.key == key))
        request = TableInteractionInput(**{
            name: getattr(interaction, name) for name in TableInteractionInput.model_fields
        })
        if key != state.key:
            request.requires_confirmation = True
        update_interaction(db, interaction.id, request)
        if key == state.key:
            assert "section" in interaction.input_schema["properties"]
        else:
            schema = interaction.input_schema["properties"]["values"]["properties"]["payload"]
            assert schema["items"].get("required", []) == []


@pytest.mark.parametrize("status", ["applied", "rejected"])
def test_specialists_cannot_edit_finished_drafts(database, status):
    db, context, _ = database
    draft = ProjectInitializationDraft(
        project_id=context.project.id, conversation_id=context.conversation.id,
        created_by_user_id=context.user.id, status=status, payload={},
    )
    db.add(draft)
    db.commit()
    writer = db.scalar(select(DatabaseInteraction).where(
        DatabaseInteraction.key == "dobby_create_initialization_wbs_section",
    ))
    update_agent_assignments(db, "initializer", [writer.id])
    with pytest.raises(HTTPException) as error:
        execute_interaction(ExecuteInteractionRequest(
            agentscope_session_id=context.conversation.agentscope_session_id,
            actor_agent_id="initializer", interaction_key=writer.key,
            arguments={"values": {"draft_id": draft.id, "payload": [{"wbs_code": "1"}],
                                  "source_files": ["进度.xlsx"], "extraction_notes": []}},
        ), db)
    assert error.value.status_code == 409
    assert db.scalar(select(ProjectInitializationDraftSection.id)) is None


def test_agent_sparse_finalize_and_later_section_work_after_partial_confirmation(database, monkeypatch):
    from backend.app.agentscope_client import AgentScopeClient
    from backend.app.initialization_change_contracts import ApplyInitializationChangesInput, PreviewInitializationChangesInput
    from backend.app.initialization_change_service import apply_change_preview, create_change_preview

    db, context, _ = database
    context.conversation.status = "running"
    context.user.role = "admin"
    baseline = WbsItem(project_id=context.project.id, wbs_code="1", name="既有工序", level=1, progress_percent=20)
    db.add(baseline)
    db.commit()
    calls = []

    def validate(_self, payload):
        calls.append(payload)
        return {"package_id": "project-initialization-validator", "package_version": "1.2.0",
                "duration_ms": 1, "result": {"status": "ready", "ruleset_version": "test", "validation_issues": []}}

    monkeypatch.setattr(AgentScopeClient, "validate_project_initialization", validate)
    monkeypatch.setattr(AgentScopeClient, "get_initialization_validation_binding", lambda _self: {"package_id": "project-initialization-validator", "package_version": "1.2.0"})
    keys = ["dobby_create_project_initialization_draft", "dobby_create_initialization_wbs_section",
            "dobby_create_initialization_risks_section", "dobby_finalize_project_initialization_draft"]
    interactions = list(db.scalars(select(DatabaseInteraction).where(DatabaseInteraction.key.in_(keys))).all())
    update_agent_assignments(db, "initializer", [item.id for item in interactions])

    def execute(key, arguments):
        return execute_interaction(ExecuteInteractionRequest(
            agentscope_session_id=context.conversation.agentscope_session_id,
            actor_agent_id="initializer", platform_agent_id=context.conversation.agent_id,
            interaction_key=key, arguments=arguments,
        ), db)["data"]

    created = execute(keys[0], {"values": {"source_files": ["进度.xlsx"]}, "return_record": True})
    draft = db.get(ProjectInitializationDraft, created["record_id"])
    execute(keys[1], {"values": {"draft_id": draft.id, "payload": [{"wbs_code": "1", "progress_percent": 40}],
                                  "source_files": ["进度.xlsx"], "extraction_notes": []}})
    first = execute(keys[-1], {"record_id": draft.id})
    assert first["status"] == "ready"
    assert calls[-1]["wbs"][0]["name"] == "既有工序"
    assert calls[-1]["wbs"][0]["progress_percent"] == 40
    preview = create_change_preview(db, draft, context.user, PreviewInitializationChangesInput())
    assert preview["can_apply"] is True
    result = apply_change_preview(db, draft, context.user, ApplyInitializationChangesInput(preview_id=preview["preview_id"]))
    db.commit()
    assert result["status"] == "partially_applied" and draft.status != "applied"
    assert float(baseline.progress_percent) == 40
    execute(keys[2], {"values": {"draft_id": draft.id, "payload": [{"related_process_name": "既有工序", "risk_part": "基坑",
        "serial_no": 1, "risk_level": "重大", "evaluation_condition": "深基坑"}], "source_files": ["风险.xlsx"], "extraction_notes": []}})
    assert draft.status == "building"
    assert execute(keys[-1], {"record_id": draft.id})["status"] == "ready"
    assert calls[-1]["wbs"][0]["progress_percent"] == 40
    assert calls[-1]["risks"][0]["risk_part"] == "基坑"


@pytest.mark.parametrize("observation", [
    {"progress_percent": 101}, {"wbs_code": "", "level": -1},
    {"wbs_code": "1", "planned_start_at": "原文日期待核对"},
])
def test_material_defects_reach_mcp_without_transport_verdict(observation):
    assert _normalize_initialization_section_payload("wbs", [observation]) == [observation]


@pytest.mark.parametrize("table_name,operation,values", [
    ("project_initialization_drafts", "update", {"status": "ready", "validation_issues": []}),
    ("project_initialization_validation_issues", "create", {"message": "伪造问题"}),
    ("project_initialization_change_previews", "create", {"review": {"can_apply": True}}),
    ("projects", "update", {"construction_unit_name": "越权写入"}),
])
def test_custom_database_policy_cannot_grant_initializer_verdict_or_formal_writes(database, table_name, operation, values):
    db, context, _ = database
    # Deliberately broaden the configurable policy: the runtime boundary must
    # reject this even for an assigned tool, without writing any records.
    policy = DatabaseInteractionTablePolicy(table_name=table_name, allowed_operations=[operation], writable_fields=list(values), readable_fields=["id"], filterable_fields=[], scope_type="global", minimum_role="member")
    interaction = DatabaseInteraction(key="custom_bypass", table_operation=operation, allowed_conversation_types=["initialization"], fixed_values={}, context_bindings=[])
    with pytest.raises(HTTPException) as caught:
        execute_table_interaction(db, context, interaction, policy, {"record_id": 1, "values": values}, actor_agent_id="initializer")
    assert caught.value.status_code == 403


@pytest.mark.parametrize("channel", ["values", "fixed", "bound"])
def test_new_draft_verdict_cannot_be_injected_through_any_write_channel(database, channel):
    from backend.app.initialization_tool_authority import require_initialization_tool_authority
    _, context, _ = database
    channels = {"values": {}, "fixed": {}, "bound": {}}
    channels[channel] = {"status": "ready"}
    with pytest.raises(HTTPException) as caught:
        require_initialization_tool_authority("project_initialization_drafts", "create", context, channels["values"], channels["fixed"], channels["bound"])
    assert caught.value.status_code == 403
