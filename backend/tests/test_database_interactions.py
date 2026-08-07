from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.agent_context_gateway import resolve_tool_context
from backend.app.database_interactions import (
    TableInteractionInput,
    TablePolicyInput,
    bootstrap_declarative_catalog,
    create_table_interaction,
    create_table_policy,
    delete_interaction,
    delete_table_policy,
    execute_table_interaction,
    list_database_tables,
    list_interaction_catalog,
    list_table_policies,
    resolve_assigned_interaction,
    update_agent_assignments,
    update_interaction,
    update_table_policy,
)
from backend.app.db import Base
from backend.app.models import (
    AgentConversation,
    DatabaseInteraction,
    DatabaseInteractionAgentAssignment,
    DatabaseInteractionTablePolicy,
    OperationLog,
    Project,
    ProjectInitializationDraft,
    ProjectInitializationDraftSection,
    ProjectInitializationAttachmentChunk,
    ProjectInitializationFile,
    ProjectMember,
    ProjectMemberPosition,
    ProjectPosition,
    RiskSource,
    Task,
    User,
    WbsItem,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def _context(db: Session, *, role: str = "user", conversation_type: str = "general"):
    user = User(
        username=f"database-{role}-{conversation_type}",
        password_hash="not-visible",
        real_name="数据库测试用户",
        identity_card_no=f"ID-{role}-{conversation_type}",
        role=role,
    )
    project = Project(name="当前项目")
    db.add_all([user, project])
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id))
    conversation = AgentConversation(
        project_id=project.id,
        user_id=user.id,
        agent_id="agent-database",
        agent_name="数据库智能体",
        conversation_type=conversation_type,
        title="数据库交互测试",
        agentscope_session_id=f"session-{role}-{conversation_type}",
        status="active",
    )
    db.add(conversation)
    db.commit()
    return resolve_tool_context(db, conversation.agentscope_session_id)


def _task_policy(db: Session) -> dict:
    return create_table_policy(
        db,
        TablePolicyInput(
            table_name="tasks",
            display_name="项目任务",
            description="仅访问当前项目任务",
            allowed_operations=["read", "create", "update", "delete"],
            readable_fields=["id", "title", "status"],
            writable_fields=["title", "task_type", "status"],
            filterable_fields=["id", "title", "status"],
            scope_type="project",
            scope_field="project_id",
            minimum_role="member",
            enabled=True,
        ),
    )


def _valid_wbs_payload() -> list[dict]:
    return [
        {
            "wbs_code": "1",
            "parent_wbs_code": None,
            "predecessor_wbs_codes": [],
            "sort_order": 1,
            "color_value": None,
            "name": "基础施工",
            "assigned_to_text": None,
            "planned_start_at": None,
            "planned_finish_at": None,
            "deadline_at": None,
            "progress_percent": 0,
            "duration_hours": None,
            "estimated_hours": None,
            "time_log_minutes": None,
            "status_text": None,
            "priority_text": None,
            "description": None,
            "budget": None,
            "actual_cost": None,
            "msp_uid": None,
            "msp_id": None,
            "source_created_at": None,
            "source_creator": None,
            "item_type": None,
            "source_project_path": None,
            "level": 1,
        },
    ]


def test_legacy_code_bindings_are_converted_to_editable_table_interactions(
    db: Session,
) -> None:
    db.add_all(
        [
            DatabaseInteraction(
                key="dobby_list_project_items",
                display_name="项目数据查询",
                description="旧固定代码查询",
                execution_kind="builtin",
                builtin_operation="list_project_items",
                input_schema={"type": "object"},
                read_only=True,
                built_in=True,
                default_assigned=True,
            ),
            DatabaseInteraction(
                key="dobby_create_task",
                display_name="创建任务",
                description="旧固定代码写入",
                execution_kind="builtin",
                builtin_operation="create_task",
                input_schema={"type": "object"},
                read_only=False,
                requires_confirmation=True,
                built_in=True,
                default_assigned=True,
            ),
        ],
    )
    db.commit()

    legacy_rows = {
        row.key: row
        for row in db.scalars(select(DatabaseInteraction)).all()
    }
    db.add_all(
        [
            DatabaseInteractionAgentAssignment(
                agent_id="agent-one",
                interaction_id=legacy_rows["dobby_list_project_items"].id,
                assigned=True,
            ),
            DatabaseInteractionAgentAssignment(
                agent_id="agent-one",
                interaction_id=legacy_rows["dobby_create_task"].id,
                assigned=False,
            ),
        ],
    )
    db.commit()

    bootstrap_declarative_catalog(db)
    catalog = list_interaction_catalog(db, "agent-one", None)

    assigned_keys = {item["key"] for item in catalog if item["assigned"]}
    assert "dobby_list_project_tasks" in assigned_keys
    assert "dobby_list_project_wbs" in assigned_keys
    assert "dobby_create_task" not in assigned_keys
    assert all("builtin_operation" not in item for item in catalog)
    assert all("execution_kind" not in item for item in catalog)
    assert not db.scalars(
        select(DatabaseInteraction).where(
            DatabaseInteraction.execution_kind == "builtin",
        ),
    ).first()
    # Clearing all assignments remains durable; it is not mistaken for an
    # uninitialized legacy agent on the next read.
    update_agent_assignments(db, "agent-one", [])
    assert not any(
        item["assigned"]
        for item in list_interaction_catalog(db, "agent-one", None)
    )


def test_catalog_upgrade_removes_obsolete_initialization_writers(
    db: Session,
) -> None:
    policy = DatabaseInteractionTablePolicy(
        table_name="project_initialization_artifacts",
        display_name="旧初始化标准资料",
        description="已废弃",
        allowed_operations=["read", "create"],
        readable_fields=["id"],
        writable_fields=[],
        filterable_fields=["id"],
        scope_type="project",
        scope_field="project_id",
        minimum_role="member",
        enabled=True,
    )
    db.add(policy)
    db.flush()
    interaction = DatabaseInteraction(
        key="initialization_records_create_artifact",
        display_name="写初始化标准资料",
        description="已废弃",
        execution_kind="table",
        table_policy_id=policy.id,
        table_operation="create",
        input_schema={"type": "object"},
        read_only=False,
        access_mode="workflow",
        enabled=True,
        built_in=False,
    )
    db.add(interaction)
    db.flush()
    db.add(
        DatabaseInteractionAgentAssignment(
            agent_id="old-initializer",
            interaction_id=interaction.id,
            assigned=True,
        ),
    )
    db.commit()

    bootstrap_declarative_catalog(db)

    assert db.scalar(
        select(DatabaseInteraction).where(
            DatabaseInteraction.key == "initialization_records_create_artifact",
        ),
    ) is None
    assert db.scalar(
        select(DatabaseInteractionTablePolicy).where(
            DatabaseInteractionTablePolicy.table_name
            == "project_initialization_artifacts",
        ),
    ) is None


def test_catalog_upgrade_rebinds_current_key_before_removing_old_policy(
    db: Session,
) -> None:
    policy = DatabaseInteractionTablePolicy(
        table_name="project_initialization_runs",
        display_name="旧初始化运行记录",
        description="已废弃",
        allowed_operations=["read"],
        readable_fields=["id"],
        writable_fields=[],
        filterable_fields=["id"],
        scope_type="project",
        scope_field="project_id",
        minimum_role="member",
        enabled=True,
    )
    db.add(policy)
    db.flush()
    interaction = DatabaseInteraction(
        key="dobby_get_project_initialization_draft",
        display_name="读取初始化草稿",
        description="迁移前仍绑定旧运行表",
        execution_kind="table",
        table_policy_id=policy.id,
        table_operation="read",
        input_schema={"type": "object"},
        read_only=True,
        access_mode="workflow",
        enabled=True,
        built_in=False,
    )
    db.add(interaction)
    db.flush()
    db.add(
        DatabaseInteractionAgentAssignment(
            agent_id="initializer",
            interaction_id=interaction.id,
            assigned=True,
        ),
    )
    db.commit()

    bootstrap_declarative_catalog(db)

    migrated = db.scalar(
        select(DatabaseInteraction).where(
            DatabaseInteraction.key == "dobby_get_project_initialization_draft",
        ),
    )
    assert migrated is not None
    migrated_policy = db.get(
        DatabaseInteractionTablePolicy,
        migrated.table_policy_id,
    )
    assert migrated_policy is not None
    assert migrated_policy.table_name == "project_initialization_drafts"
    assert db.scalar(
        select(DatabaseInteractionTablePolicy).where(
            DatabaseInteractionTablePolicy.table_name
            == "project_initialization_runs",
        ),
    ) is None
    assignment = db.scalar(
        select(DatabaseInteractionAgentAssignment).where(
            DatabaseInteractionAgentAssignment.agent_id == "initializer",
            DatabaseInteractionAgentAssignment.interaction_id == migrated.id,
        ),
    )
    assert assignment is not None
    assert assignment.assigned is True


def test_catalog_upgrade_refreshes_managed_attachment_read_schema(
    db: Session,
) -> None:
    policy = DatabaseInteractionTablePolicy(
        table_name="project_initialization_attachment_chunks",
        display_name="初始化附件解析分块",
        description="旧白名单",
        allowed_operations=["read"],
        readable_fields=["id", "content"],
        writable_fields=[],
        filterable_fields=["id"],
        scope_type="project",
        scope_field="project_id",
        minimum_role="member",
        enabled=True,
    )
    db.add(policy)
    db.flush()
    interaction = DatabaseInteraction(
        key="dobby_list_project_initialization_attachment_chunks",
        display_name="读取初始化附件解析分块",
        description="包含 content 时必须一次只读一个分块。",
        execution_kind="table",
        table_policy_id=policy.id,
        table_operation="read",
        input_schema={
            "type": "object",
            "properties": {"record_id": {"type": "integer"}},
        },
        read_only=True,
        access_mode="workflow",
        enabled=True,
        built_in=False,
    )
    db.add(interaction)
    db.flush()
    db.add(
        DatabaseInteractionAgentAssignment(
            agent_id="initializer",
            interaction_id=interaction.id,
            assigned=True,
        ),
    )
    db.commit()

    bootstrap_declarative_catalog(db)

    refreshed = db.scalar(
        select(DatabaseInteraction).where(
            DatabaseInteraction.key
            == "dobby_list_project_initialization_attachment_chunks",
        ),
    )
    assert refreshed is not None
    assert "record_ids" in refreshed.input_schema["properties"]
    assert refreshed.input_schema["properties"]["record_ids"]["maxItems"] == 12
    assert refreshed.input_schema["properties"]["text_limit"]["maximum"] == 6000
    assert "text_field=content" in refreshed.description
    assignment = db.scalar(
        select(DatabaseInteractionAgentAssignment).where(
            DatabaseInteractionAgentAssignment.agent_id == "initializer",
            DatabaseInteractionAgentAssignment.interaction_id == refreshed.id,
        ),
    )
    assert assignment is not None
    assert assignment.assigned is True


def test_new_agent_database_interactions_require_explicit_assignment(
    db: Session,
) -> None:
    bootstrap_declarative_catalog(db)

    catalog = list_interaction_catalog(db, "new-agent", None)

    assert catalog
    assert not any(item["assigned"] for item in catalog)
    assert not any(
        row.default_assigned
        for row in db.scalars(select(DatabaseInteraction)).all()
    )


def test_sensitive_columns_are_never_exposed_to_policy_editor() -> None:
    users = next(item for item in list_database_tables() if item["name"] == "users")
    names = {column["name"] for column in users["columns"]}

    assert "username" in names
    assert "real_name" in names
    assert "password_hash" not in names
    assert "identity_card_no" not in names


def test_structured_read_is_scoped_to_current_project(db: Session) -> None:
    context = _context(db)
    other_project = Project(name="其他项目")
    db.add(other_project)
    db.flush()
    db.add_all(
        [
            Task(
                project_id=context.project.id,
                title="当前项目任务",
                task_type="daily_confirm",
                status="pending",
            ),
            Task(
                project_id=other_project.id,
                title="其他项目任务",
                task_type="daily_confirm",
                status="pending",
            ),
        ],
    )
    db.commit()
    policy = _task_policy(db)
    interaction = create_table_interaction(
        db,
        TableInteractionInput(
            key="query_project_tasks",
            display_name="查询项目任务",
            table_policy_id=policy["id"],
            table_operation="read",
        ),
    )
    update_agent_assignments(db, "agent-database", [interaction["id"]])
    row, policy_row = resolve_assigned_interaction(
        db,
        "agent-database",
        "query_project_tasks",
    )
    assert policy_row is not None

    data, _ = execute_table_interaction(
        db,
        context,
        row,
        policy_row,
        {"fields": ["id", "title"], "limit": 50},
    )

    assert [item["title"] for item in data] == ["当前项目任务"]


def test_structured_read_supports_bounded_primary_key_batches(
    db: Session,
) -> None:
    context = _context(db)
    tasks = [
        Task(
            project_id=context.project.id,
            title=f"批量任务 {index}",
            task_type="daily_confirm",
            status="pending",
        )
        for index in range(1, 4)
    ]
    db.add_all(tasks)
    db.commit()
    task_ids = [task.id for task in tasks]
    policy = _task_policy(db)
    interaction = create_table_interaction(
        db,
        TableInteractionInput(
            key="batch_query_project_tasks",
            display_name="批量查询项目任务",
            table_policy_id=policy["id"],
            table_operation="read",
        ),
    )
    update_agent_assignments(db, "agent-database", [interaction["id"]])
    row, policy_row = resolve_assigned_interaction(
        db,
        "agent-database",
        "batch_query_project_tasks",
    )
    assert policy_row is not None
    record_ids_schema = row.input_schema["properties"]["record_ids"]
    assert record_ids_schema["maxItems"] == 12
    assert record_ids_schema["uniqueItems"] is True

    data, _ = execute_table_interaction(
        db,
        context,
        row,
        policy_row,
        {
            "fields": ["id", "title"],
            "record_ids": [task_ids[2], task_ids[0]],
            "limit": 2,
        },
    )

    assert data == [
        {"id": task_ids[0], "title": "批量任务 1"},
        {"id": task_ids[2], "title": "批量任务 3"},
    ]

    with pytest.raises(HTTPException) as both_error:
        execute_table_interaction(
            db,
            context,
            row,
            policy_row,
            {
                "fields": ["id"],
                "record_id": task_ids[0],
                "record_ids": [task_ids[0]],
            },
        )
    assert both_error.value.status_code == 422

    with pytest.raises(HTTPException) as duplicate_error:
        execute_table_interaction(
            db,
            context,
            row,
            policy_row,
            {
                "fields": ["id"],
                "record_ids": [task_ids[0], task_ids[0]],
            },
        )
    assert duplicate_error.value.status_code == 422


def test_structured_read_pages_json_arrays_without_truncating_records(
    db: Session,
) -> None:
    context = _context(db, conversation_type="initialization")
    draft = ProjectInitializationDraft(
        project_id=context.project.id,
        conversation_id=context.conversation.id,
        created_by_user_id=context.user.id,
        status="building",
        payload={},
        validation_issues=[],
        source_files=[],
    )
    db.add(draft)
    db.flush()
    db.add(
        ProjectInitializationDraftSection(
            draft_id=draft.id,
            project_id=context.project.id,
            conversation_id=context.conversation.id,
            section="wbs",
            writer_agent_id="wbs-agent",
            payload=[{"wbs_code": str(index)} for index in range(45)],
            source_files=[],
            extraction_notes=[],
        ),
    )
    db.commit()
    bootstrap_declarative_catalog(db)
    interaction = db.scalar(
        select(DatabaseInteraction).where(
            DatabaseInteraction.key
            == "dobby_list_project_initialization_sections",
        ),
    )
    assert interaction is not None
    assert interaction.input_schema["properties"]["json_limit"]["maximum"] == 20
    update_agent_assignments(db, "agent-database", [interaction.id])
    row, policy = resolve_assigned_interaction(
        db,
        "agent-database",
        interaction.key,
    )
    assert policy is not None

    data, _ = execute_table_interaction(
        db,
        context,
        row,
        policy,
        {
            "fields": ["section", "payload"],
            "filters": {"section": "wbs"},
            "limit": 1,
            "json_field": "payload",
            "json_offset": 20,
            "json_limit": 20,
        },
    )

    assert [item["wbs_code"] for item in data[0]["payload"]] == [
        str(index) for index in range(20, 40)
    ]
    assert data[0]["_json_page"] == {
        "field": "payload",
        "offset": 20,
        "limit": 20,
        "returned": 20,
        "total": 45,
        "has_more": True,
        "next_offset": 40,
    }

    with pytest.raises(HTTPException) as missing_field_error:
        execute_table_interaction(
            db,
            context,
            row,
            policy,
            {
                "fields": ["section"],
                "filters": {"section": "wbs"},
                "limit": 1,
                "json_field": "payload",
                "json_offset": 0,
                "json_limit": 20,
            },
        )
    assert missing_field_error.value.status_code == 422


def test_structured_read_pages_long_text_without_losing_content(
    db: Session,
) -> None:
    context = _context(db, conversation_type="initialization")
    content = "附件正文" * 4000
    source_file = ProjectInitializationFile(
        project_id=context.project.id,
        conversation_id=context.conversation.id,
        uploaded_by_user_id=context.user.id,
        file_name="进度计划.xlsx",
        storage_path="test/进度计划.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        file_size=1024,
        file_hash="file-hash",
    )
    db.add(source_file)
    db.flush()
    chunk = ProjectInitializationAttachmentChunk(
        project_id=context.project.id,
        conversation_id=context.conversation.id,
        file_id=source_file.id,
        file_name="进度计划.xlsx",
        chunk_index=1,
        chunk_count=1,
        status="ready",
        parser="test",
        content=content,
        content_hash="hash",
        parse_details={},
    )
    db.add(chunk)
    db.commit()
    bootstrap_declarative_catalog(db)
    interaction = db.scalar(
        select(DatabaseInteraction).where(
            DatabaseInteraction.key
            == "dobby_list_project_initialization_attachment_chunks",
        ),
    )
    assert interaction is not None
    assert interaction.input_schema["properties"]["text_limit"]["maximum"] == 6000
    update_agent_assignments(db, "agent-database", [interaction.id])
    row, policy = resolve_assigned_interaction(
        db,
        "agent-database",
        interaction.key,
    )
    assert policy is not None

    data, _ = execute_table_interaction(
        db,
        context,
        row,
        policy,
        {
            "fields": ["id", "content"],
            "record_id": chunk.id,
            "limit": 1,
            "text_field": "content",
            "text_offset": 6000,
            "text_limit": 6000,
        },
    )

    assert data[0]["content"] == content[6000:12000]
    assert data[0]["_text_page"] == {
        "field": "content",
        "offset": 6000,
        "limit": 6000,
        "returned": 6000,
        "total": len(content),
        "has_more": True,
        "next_offset": 12000,
    }


def test_structured_read_supports_keyword_without_leaving_whitelist(
    db: Session,
) -> None:
    context = _context(db)
    db.add_all(
        [
            Task(
                project_id=context.project.id,
                title="核对临边防护资料",
                task_type="daily_confirm",
                status="pending",
            ),
            Task(
                project_id=context.project.id,
                title="整理施工日报",
                task_type="daily_confirm",
                status="pending",
            ),
        ],
    )
    db.commit()
    policy = _task_policy(db)
    interaction = create_table_interaction(
        db,
        TableInteractionInput(
            key="search_project_tasks",
            display_name="检索项目任务",
            table_policy_id=policy["id"],
            table_operation="read",
        ),
    )
    update_agent_assignments(db, "agent-database", [interaction["id"]])
    row, policy_row = resolve_assigned_interaction(
        db,
        "agent-database",
        "search_project_tasks",
    )
    assert policy_row is not None

    data, _ = execute_table_interaction(
        db,
        context,
        row,
        policy_row,
        {"fields": ["id", "title"], "keyword": "防护"},
    )

    assert [item["title"] for item in data] == ["核对临边防护资料"]


def test_configured_task_join_returns_real_business_names(db: Session) -> None:
    context = _context(db)
    assignee = User(
        username="task-owner",
        password_hash="not-visible",
        real_name="任务负责人",
        identity_card_no="TASK-OWNER-ID",
        role="user",
    )
    wbs = WbsItem(
        project_id=context.project.id,
        wbs_code="1.2",
        name="基坑开挖",
        sort_order=1,
        level=2,
    )
    risk = RiskSource(
        project_id=context.project.id,
        serial_no=1,
        related_process_name="基坑开挖",
        risk_part="深基坑临边",
        risk_level="较大风险",
        evaluation_condition="开挖深度超过阈值",
    )
    db.add_all([assignee, wbs, risk])
    db.flush()
    db.add(
        Task(
            project_id=context.project.id,
            title="复核临边防护",
            task_type="risk_review",
            status="pending",
            assignee_user_id=assignee.id,
            wbs_item_id=wbs.id,
            risk_source_id=risk.id,
        ),
    )
    db.commit()

    bootstrap_declarative_catalog(db)
    interaction = db.scalar(
        select(DatabaseInteraction).where(
            DatabaseInteraction.key == "dobby_list_project_tasks",
        ),
    )
    assert interaction is not None
    assert len(interaction.join_rules) == 4
    update_agent_assignments(db, "agent-database", [interaction.id])
    row, policy = resolve_assigned_interaction(
        db,
        "agent-database",
        interaction.key,
    )
    assert policy is not None

    data, _ = execute_table_interaction(
        db,
        context,
        row,
        policy,
        {
            "fields": [
                "title",
                "assignee.real_name",
                "assignee.username",
                "wbs.wbs_code",
                "wbs.name",
                "risk.risk_part",
            ],
            "filters": {"assignee.real_name": "任务负责人"},
        },
    )

    assert data == [
        {
            "title": "复核临边防护",
            "assignee.real_name": "任务负责人",
            "assignee.username": "task-owner",
            "wbs.wbs_code": "1.2",
            "wbs.name": "基坑开挖",
            "risk.risk_part": "深基坑临边",
        },
    ]


def test_configured_personnel_join_supports_chained_relations(db: Session) -> None:
    context = _context(db)
    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == context.project.id,
            ProjectMember.user_id == context.user.id,
        ),
    )
    assert member is not None
    position = ProjectPosition(
        project_id=context.project.id,
        position_name="项目经理",
    )
    db.add(position)
    db.flush()
    db.add(
        ProjectMemberPosition(
            project_id=context.project.id,
            project_member_id=member.id,
            position_id=position.id,
            serial_no=1,
            certificate_no="CERT-001",
            responsibility_description="负责项目统筹",
        ),
    )
    db.commit()

    bootstrap_declarative_catalog(db)
    interaction = db.scalar(
        select(DatabaseInteraction).where(
            DatabaseInteraction.key == "dobby_list_project_personnel",
        ),
    )
    assert interaction is not None
    update_agent_assignments(db, "agent-database", [interaction.id])
    row, policy = resolve_assigned_interaction(
        db,
        "agent-database",
        interaction.key,
    )
    assert policy is not None

    data, _ = execute_table_interaction(
        db,
        context,
        row,
        policy,
        {
            "fields": [
                "serial_no",
                "account.real_name",
                "account.username",
                "position.position_name",
            ],
        },
    )

    assert data == [
        {
            "serial_no": 1,
            "account.real_name": "数据库测试用户",
            "account.username": "database-user-general",
            "position.position_name": "项目经理",
        },
    ]


def test_structured_write_injects_scope_and_writes_audit(db: Session) -> None:
    context = _context(db, role="admin")
    policy = _task_policy(db)
    interaction = create_table_interaction(
        db,
        TableInteractionInput(
            key="create_project_task",
            display_name="新增项目任务",
            table_policy_id=policy["id"],
            table_operation="create",
            requires_confirmation=True,
        ),
    )
    update_agent_assignments(db, "agent-database", [interaction["id"]])
    row, policy_row = resolve_assigned_interaction(
        db,
        "agent-database",
        "create_project_task",
    )
    assert policy_row is not None

    result, _ = execute_table_interaction(
        db,
        context,
        row,
        policy_row,
        {
            "values": {
                "title": "智能体创建的任务",
                "task_type": "daily_confirm",
                "status": "pending",
            },
        },
    )

    task = db.get(Task, result["record_id"])
    assert task is not None
    assert task.project_id == context.project.id
    log = db.scalar(
        select(OperationLog).where(
            OperationLog.action == "agent_database_create",
            OperationLog.target_id == task.id,
        ),
    )
    assert log is not None


def test_initialization_specialist_section_is_fixed_by_platform(db: Session) -> None:
    context = _context(db, conversation_type="initialization")
    draft = ProjectInitializationDraft(
        project_id=context.project.id,
        conversation_id=context.conversation.id,
        created_by_user_id=context.user.id,
        status="building",
        payload={},
    )
    db.add(draft)
    db.commit()

    bootstrap_declarative_catalog(db)
    interaction = db.scalar(
        select(DatabaseInteraction).where(
            DatabaseInteraction.key
            == "dobby_create_initialization_wbs_section",
        ),
    )
    assert interaction is not None
    assert interaction.fixed_values == {"section": "wbs"}
    assert interaction.runtime_policy == {}
    values_schema = interaction.input_schema["properties"]["values"]
    assert "section" not in values_schema["properties"]
    payload_schema = values_schema["properties"]["payload"]
    assert payload_schema["type"] == "array"
    assert payload_schema["items"]["additionalProperties"] is False
    assert set(values_schema["required"]) >= {
        "payload",
        "source_files",
        "extraction_notes",
    }
    assert values_schema["properties"]["source_files"]["anyOf"][0][
        "minItems"
    ] == 1
    assert set(payload_schema["items"]["properties"]) == set(
        _valid_wbs_payload()[0],
    )
    update_agent_assignments(db, "wbs-specialist", [interaction.id])
    row, policy = resolve_assigned_interaction(
        db,
        "wbs-specialist",
        interaction.key,
    )
    assert policy is not None

    with pytest.raises(HTTPException) as evidence_error:
        execute_table_interaction(
            db,
            context,
            row,
            policy,
            {"values": {"draft_id": draft.id, "payload": _valid_wbs_payload()}},
            actor_agent_id="wbs-specialist",
        )
    assert evidence_error.value.status_code == 422
    assert "source_files" in evidence_error.value.detail

    result, _ = execute_table_interaction(
        db,
        context,
        row,
        policy,
        {
            "values": {
                "draft_id": draft.id,
                "payload": _valid_wbs_payload(),
                "source_files": {
                    "chunks": [
                        {
                            "file_id": 2,
                            "chunk_id": 7,
                            "file_name": "总进度计划.xlsx",
                        },
                    ],
                },
                "extraction_notes": [],
            },
        },
        actor_agent_id="wbs-specialist",
    )

    section = db.get(ProjectInitializationDraftSection, result["record_id"])
    assert section is not None
    assert section.section == "wbs"
    assert section.writer_agent_id == "wbs-specialist"
    assert set(section.payload[0]) == set(_valid_wbs_payload()[0])
    assert section.payload[0]["wbs_code"] == "1"
    assert section.payload[0]["progress_percent"] == "0"
    assert section.source_files["chunks"][0]["file_id"] == 2
    assert section.extraction_notes == []


def test_initialization_draft_creation_keeps_envelope_canonical(
    db: Session,
) -> None:
    context = _context(db, conversation_type="initialization")
    bootstrap_declarative_catalog(db)
    interaction = db.scalar(
        select(DatabaseInteraction).where(
            DatabaseInteraction.key
            == "dobby_create_project_initialization_draft",
        ),
    )
    assert interaction is not None
    update_agent_assignments(db, "initialization-orchestrator", [interaction.id])
    row, policy = resolve_assigned_interaction(
        db,
        "initialization-orchestrator",
        interaction.key,
    )
    assert policy is not None

    result, _ = execute_table_interaction(
        db,
        context,
        row,
        policy,
        {
            "values": {
                "status": "ready",
                "payload": {
                    "engineering_info": {"project_name": "旧结构"},
                    "quality_metrics": [{"name": "旧字段"}],
                },
                "validation_issues": [
                    {
                        "level": "error",
                        "path": "payload",
                        "message": "不应由创建动作写入",
                    },
                ],
                "source_files": ["附件.xlsx"],
            },
        },
        actor_agent_id="initialization-orchestrator",
    )

    draft = db.get(ProjectInitializationDraft, result["record_id"])
    assert draft is not None
    assert draft.status == "building"
    assert draft.payload == {}
    assert draft.validation_issues == []
    assert draft.source_files == ["附件.xlsx"]


def test_initialization_section_rejects_nested_or_translated_payload(
    db: Session,
) -> None:
    context = _context(db, conversation_type="initialization")
    draft = ProjectInitializationDraft(
        project_id=context.project.id,
        conversation_id=context.conversation.id,
        created_by_user_id=context.user.id,
        status="building",
        payload={},
    )
    db.add(draft)
    db.commit()
    bootstrap_declarative_catalog(db)
    interaction = db.scalar(
        select(DatabaseInteraction).where(
            DatabaseInteraction.key
            == "dobby_create_initialization_wbs_section",
        ),
    )
    assert interaction is not None
    update_agent_assignments(db, "wbs-specialist", [interaction.id])
    row, policy = resolve_assigned_interaction(
        db,
        "wbs-specialist",
        interaction.key,
    )
    assert policy is not None

    invalid = _valid_wbs_payload()
    invalid[0]["children"] = [{"名称": "错误嵌套节点"}]
    with pytest.raises(HTTPException) as error:
        execute_table_interaction(
            db,
            context,
            row,
            policy,
            {"values": {"draft_id": draft.id, "payload": invalid}},
            actor_agent_id="wbs-specialist",
        )

    assert error.value.status_code == 422
    assert error.value.detail["message"] == "初始化草稿分区字段不符合标准结构"


def test_initialization_finalizer_cannot_publish_deterministically_invalid_draft(
    db: Session,
) -> None:
    context = _context(db, conversation_type="initialization")
    draft = ProjectInitializationDraft(
        project_id=context.project.id,
        conversation_id=context.conversation.id,
        created_by_user_id=context.user.id,
        status="building",
        payload={},
    )
    db.add(draft)
    db.flush()
    invalid_wbs = _valid_wbs_payload()
    invalid_wbs[0]["wbs_code"] = "1.1"
    invalid_wbs[0]["level"] = 2
    db.add(
        ProjectInitializationDraftSection(
            draft_id=draft.id,
            project_id=context.project.id,
            conversation_id=context.conversation.id,
            section="wbs",
            writer_agent_id="wbs-specialist",
            payload=invalid_wbs,
            source_files=[],
            extraction_notes=[],
        ),
    )
    db.commit()
    bootstrap_declarative_catalog(db)
    interaction = db.scalar(
        select(DatabaseInteraction).where(
            DatabaseInteraction.key
            == "dobby_finalize_project_initialization_draft",
        ),
    )
    assert interaction is not None
    finalizer_values_schema = interaction.input_schema["properties"]["values"]
    assert set(finalizer_values_schema["required"]) == {
        "status",
        "validation_issues",
    }
    issue_schema = finalizer_values_schema["properties"]["validation_issues"][
        "items"
    ]
    assert issue_schema["required"] == ["level", "path", "message"]
    assert issue_schema["additionalProperties"] is False
    update_agent_assignments(db, "validator", [interaction.id])
    row, policy = resolve_assigned_interaction(
        db,
        "validator",
        interaction.key,
    )
    assert policy is not None

    with pytest.raises(HTTPException) as error:
        execute_table_interaction(
            db,
            context,
            row,
            policy,
            {
                "record_id": draft.id,
                "values": {"status": "ready", "validation_issues": []},
            },
            actor_agent_id="validator",
        )

    assert error.value.status_code == 422
    assert error.value.detail["message"] == (
        "初始化草稿仍有确定性错误，不能标记为 ready"
    )


def test_unassigned_interaction_is_rejected(db: Session) -> None:
    policy = _task_policy(db)
    create_table_interaction(
        db,
        TableInteractionInput(
            key="unassigned_task_query",
            display_name="未分配查询",
            table_policy_id=policy["id"],
            table_operation="read",
        ),
    )

    with pytest.raises(HTTPException) as error:
        resolve_assigned_interaction(
            db,
            "agent-database",
            "unassigned_task_query",
        )

    assert error.value.status_code == 403


def test_relation_editor_rejects_non_foreign_key_conditions(db: Session) -> None:
    task_policy = _task_policy(db)
    account_policy = create_table_policy(
        db,
        TablePolicyInput(
            table_name="users",
            display_name="平台账号",
            allowed_operations=["read"],
            readable_fields=["id", "username", "real_name"],
            writable_fields=[],
            filterable_fields=["id", "username", "real_name"],
            scope_type="user",
            scope_field="id",
            minimum_role="member",
        ),
    )

    with pytest.raises(HTTPException) as error:
        create_table_interaction(
            db,
            TableInteractionInput(
                key="invalid_account_join",
                display_name="错误关联",
                table_policy_id=task_policy["id"],
                table_operation="read",
                join_rules=[
                    {
                        "alias": "account",
                        "source_alias": "main",
                        "source_field": "title",
                        "target_policy_id": account_policy["id"],
                        "target_field": "real_name",
                        "readable_fields": ["username"],
                    },
                ],
            ),
        )

    assert error.value.status_code == 422
    assert "真实存在的外键关系" in error.value.detail


def test_policy_and_custom_interaction_support_full_management_lifecycle(
    db: Session,
) -> None:
    policy = _task_policy(db)
    interaction = create_table_interaction(
        db,
        TableInteractionInput(
            key="manage_project_tasks",
            display_name="管理项目任务",
            description="初始说明",
            table_policy_id=policy["id"],
            table_operation="read",
        ),
    )

    updated_interaction = update_interaction(
        db,
        interaction["id"],
        TableInteractionInput(
            key="manage_project_tasks",
            display_name="查询项目任务",
            description="修改后的说明",
            table_policy_id=policy["id"],
            table_operation="read",
            sort_order=12,
        ),
    )
    assert updated_interaction["display_name"] == "查询项目任务"
    assert updated_interaction["description"] == "修改后的说明"
    assert updated_interaction["sort_order"] == 12

    updated_policy = update_table_policy(
        db,
        policy["id"],
        TablePolicyInput(
            table_name="tasks",
            display_name="项目任务白名单",
            description="修改后的访问边界",
            allowed_operations=["read"],
            readable_fields=["id", "title", "status"],
            writable_fields=[],
            filterable_fields=["id", "title", "status"],
            scope_type="project",
            scope_field="project_id",
            minimum_role="member",
            enabled=True,
        ),
    )
    assert updated_policy["display_name"] == "项目任务白名单"
    assert list_table_policies(db)[0]["allowed_operations"] == ["read"]

    with pytest.raises(HTTPException) as in_use:
        delete_table_policy(db, policy["id"])
    assert in_use.value.status_code == 409

    delete_interaction(db, interaction["id"])
    delete_table_policy(db, policy["id"])
    assert list_table_policies(db) == []
