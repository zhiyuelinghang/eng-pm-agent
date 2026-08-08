"""Regression tests for the engineering-platform integration contract."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from fastapi import HTTPException

from agentscope.agent import ContextConfig, ReActConfig
from agentscope.message import UserMsg
from agentscope.app._auth import AgentScopePrincipal
from agentscope.app._router._agent import (
    _demote_other_global_main_agents,
    _normalise_platform_agent_data,
    delete_agent,
    get_platform_agent_catalog,
    update_platform_settings,
)
from agentscope.app._router._schema import (
    CreateSessionRequest,
    UpdateMessageMetadataRequest,
    UpdatePlatformSettingsRequest,
    UpdateSessionRequest,
)
from agentscope.app._router._session import (
    create_session,
    update_message_metadata,
    update_session,
)
from agentscope.app._service import AgentView
from agentscope.app.mcp_registry import (
    MCPPackageManifest,
    MCPPackageRecord,
    MCPPackageTool,
)
from agentscope.app.storage import (
    AgentCallConfig,
    AgentData,
    AgentModelPolicy,
    AgentRecord,
    ChatModelConfig,
    PlatformAgentConfig,
    PlatformMCPVersionBinding,
    PlatformSessionContext,
    PlatformSettingsData,
    PlatformSettingsRecord,
    SessionConfig,
    SessionRecord,
)
from agentscope.app.storage import AsyncSQLAlchemyStorage


USER_ID = "platform-test"


def _model(model: str) -> ChatModelConfig:
    return ChatModelConfig(
        type="custom_openai_credential",
        credential_id=f"credential-{model}",
        model=model,
        parameters={},
    )


def _record(
    agent_id: str,
    name: str,
    *,
    role: str = "business",
    enabled: bool = True,
    published: bool = True,
    sort_order: int = 100,
    fixed_model: bool = False,
    initialization_role: str | None = None,
) -> AgentRecord:
    return AgentRecord(
        id=agent_id,
        user_id=USER_ID,
        data=AgentData(
            name=name,
            context_config=ContextConfig(),
            react_config=ReActConfig(),
            model_policy=(
                AgentModelPolicy(
                    mode="fixed",
                    chat_model_config=_model(name),
                )
                if fixed_model
                else AgentModelPolicy()
            ),
            platform_config=PlatformAgentConfig(
                role=role,
                enabled=enabled,
                published=published,
                sort_order=sort_order,
                initialization_role=initialization_role,
            ),
        ),
    )


def _view(record: AgentRecord) -> AgentView:
    return AgentView.model_validate(
        {**record.model_dump(mode="python"), "editable": True},
    )


class PlatformAgentContractTest(IsolatedAsyncioTestCase):
    """Validate compatibility, publication filtering, and session policy."""

    def test_legacy_agent_defaults_to_published_business_agent(self) -> None:
        legacy = AgentData.model_validate(
            {
                "name": "legacy",
                "context_config": {},
                "react_config": {},
            },
        )
        self.assertEqual(legacy.platform_config.role, "business")
        self.assertTrue(legacy.platform_config.enabled)
        self.assertTrue(legacy.platform_config.published)
        self.assertFalse(
            legacy.platform_config.allow_global_main_call,
        )

    def test_initialization_role_is_persisted_but_hidden_from_form_schema(
        self,
    ) -> None:
        config = PlatformAgentConfig(initialization_role="validator")

        self.assertEqual(config.initialization_role, "validator")
        self.assertEqual(
            config.model_dump(mode="json")["initialization_role"],
            "validator",
        )
        self.assertNotIn(
            "initialization_role",
            PlatformAgentConfig.model_json_schema()["properties"],
        )

    def test_role_invariants_are_normalised(self) -> None:
        main = _record("main", "Main", role="global_main").data.model_copy(
            update={"call_config": AgentCallConfig(scope="none")},
        )
        normalised_main = _normalise_platform_agent_data(main)
        self.assertEqual(normalised_main.call_config.scope, "all")

        internal = _record(
            "internal",
            "Internal",
            role="system_internal",
            published=True,
        ).data
        normalised_internal = _normalise_platform_agent_data(internal)
        self.assertFalse(normalised_internal.platform_config.published)

    async def test_catalog_filters_and_sorts_platform_agents(self) -> None:
        records = [
            _record(
                "main",
                "Platform Main",
                role="global_main",
                fixed_model=True,
            ),
            _record("later", "Later", sort_order=200),
            _record("first", "First", sort_order=10, fixed_model=True),
            _record("disabled", "Disabled", enabled=False),
            _record("draft", "Draft", published=False),
            _record("internal", "Internal", role="system_internal"),
            _record(
                "wbs-worker",
                "WBS Worker",
                role="system_internal",
                published=False,
                fixed_model=True,
                initialization_role="wbs",
            ),
        ]
        access = SimpleNamespace(
            list_resource=AsyncMock(
                return_value=[_view(record) for record in records],
            ),
        )
        storage = SimpleNamespace(
            get_agent=AsyncMock(return_value=records[-1]),
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        global_main_agent_id="main",
                    ),
                ),
            ),
            list_agents=AsyncMock(return_value=records),
            upsert_agent=AsyncMock(),
        )

        catalog = await get_platform_agent_catalog(
            user_id=USER_ID,
            access=access,
            storage=storage,
        )

        self.assertEqual(catalog.global_main.id, "main")
        self.assertTrue(catalog.global_main.model_ready)
        self.assertEqual(
            [item.id for item in catalog.initialization_workers],
            ["wbs-worker"],
        )
        self.assertEqual(
            [item.id for item in catalog.business_agents],
            ["first", "later"],
        )
        self.assertEqual(catalog.total, 2)

    async def test_platform_settings_pointer_selects_exactly_one_main(
        self,
    ) -> None:
        old_main = _record(
            "old",
            "Old",
            role="global_main",
            fixed_model=True,
        )
        selected = _record(
            "selected",
            "Selected",
            fixed_model=True,
        )
        storage = SimpleNamespace(
            get_agent=AsyncMock(return_value=selected),
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        global_main_agent_id="old",
                    ),
                ),
            ),
            list_agents=AsyncMock(return_value=[old_main, selected]),
            upsert_agent=AsyncMock(return_value="agent"),
            upsert_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        global_main_agent_id="selected",
                    ),
                ),
            ),
        )

        response = await update_platform_settings(
            body=UpdatePlatformSettingsRequest(
                global_main_agent_id="selected",
            ),
            user_id=USER_ID,
            storage=storage,
            manager=SimpleNamespace(
                list_records=AsyncMock(return_value=[]),
            ),
        )

        self.assertEqual(response.global_main_agent_id, "selected")
        updated = {
            call.args[1].id: call.args[1]
            for call in storage.upsert_agent.await_args_list
        }
        self.assertEqual(
            updated["old"].data.platform_config.role,
            "business",
        )
        self.assertEqual(updated["old"].data.call_config.scope, "selected")
        self.assertEqual(
            updated["selected"].data.platform_config.role,
            "global_main",
        )
        self.assertEqual(updated["selected"].data.call_config.scope, "all")

    async def test_platform_settings_selects_an_exact_validation_version(
        self,
    ) -> None:
        initializer = _record(
            "initializer",
            "Initializer",
            fixed_model=True,
        )
        old_binding = PlatformMCPVersionBinding(
            package_id="validation-rules",
            version="1.0.0",
        )
        new_binding = PlatformMCPVersionBinding(
            package_id="validation-rules",
            version="2.0.0",
        )
        storage = SimpleNamespace(
            get_agent=AsyncMock(return_value=initializer),
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        project_initializer_agent_id="initializer",
                        project_initializer_validation_mcp=old_binding,
                    ),
                ),
            ),
            list_agents=AsyncMock(return_value=[initializer]),
            upsert_agent=AsyncMock(return_value="initializer"),
        )

        async def save_settings(_user_id, data):
            return PlatformSettingsRecord(user_id=USER_ID, data=data)

        storage.upsert_platform_settings = AsyncMock(side_effect=save_settings)
        manager = SimpleNamespace(
            get_record=AsyncMock(
                return_value=MCPPackageRecord(
                    id="validation-rules",
                    manifest=MCPPackageManifest(
                        name="validation-rules",
                        display_name="核验规则",
                        version="2.0.0",
                        command="server.exe",
                        platform_capabilities=[
                            "project_initialization_validation",
                        ],
                    ),
                    relative_dir="packages/validation-rules/2.0.0",
                    tools=[MCPPackageTool(name="validate")],
                ),
            ),
            close_version_instances=AsyncMock(),
        )

        response = await update_platform_settings(
            body=UpdatePlatformSettingsRequest(
                project_initializer_agent_id="initializer",
                project_initializer_validation_mcp=new_binding,
            ),
            user_id=USER_ID,
            storage=storage,
            manager=manager,
        )

        self.assertEqual(response.project_initializer_validation_mcp, new_binding)
        manager.get_record.assert_awaited_with(
            "validation-rules",
            "2.0.0",
        )
        manager.close_version_instances.assert_awaited_once_with(
            "validation-rules",
            "1.0.0",
        )

    async def test_selecting_main_demotes_the_previous_main(self) -> None:
        old_main = _record("old", "Old", role="global_main")
        selected_main = _record("new", "New", role="global_main")
        storage = SimpleNamespace(
            list_agents=AsyncMock(return_value=[old_main, selected_main]),
            upsert_agent=AsyncMock(return_value="old"),
        )

        await _demote_other_global_main_agents(storage, USER_ID, "new")

        storage.upsert_agent.assert_awaited_once()
        demoted = storage.upsert_agent.await_args.args[1]
        self.assertEqual(demoted.id, "old")
        self.assertEqual(demoted.data.platform_config.role, "business")
        self.assertEqual(demoted.data.call_config.scope, "selected")

    async def test_current_main_cannot_be_deleted(self) -> None:
        main = _record(
            "main",
            "Main",
            role="global_main",
            fixed_model=True,
        )
        storage = SimpleNamespace(
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        global_main_agent_id="main",
                    ),
                ),
            ),
            list_agents=AsyncMock(return_value=[main]),
            upsert_agent=AsyncMock(),
        )
        access = SimpleNamespace(
            resolve_for_edit=AsyncMock(return_value=(USER_ID, main)),
        )
        session_service = SimpleNamespace(delete_agent=AsyncMock())

        with self.assertRaises(HTTPException) as context:
            await delete_agent(
                agent_id="main",
                user_id=USER_ID,
                session_service=session_service,
                storage=storage,
                access=access,
            )

        self.assertEqual(context.exception.status_code, 409)
        session_service.delete_agent.assert_not_awaited()

    async def test_fixed_agent_model_is_enforced_when_session_is_created(
        self,
    ) -> None:
        fixed = _record("fixed", "fixed-model", fixed_model=True)
        access = SimpleNamespace(
            resolve_agent=AsyncMock(return_value=fixed),
            get_resource=AsyncMock(return_value=object()),
        )
        storage = SimpleNamespace(
            upsert_session=AsyncMock(
                return_value=SimpleNamespace(id="session-id"),
            ),
        )
        workspace = SimpleNamespace(
            assign_workspace_id=lambda **_: "workspace-id",
        )

        response = await create_session(
            body=CreateSessionRequest(
                agent_id="fixed",
                chat_model_config=_model("client-override"),
            ),
            user_id=USER_ID,
            storage=storage,
            workspace_manager=workspace,
            access=access,
            principal=AgentScopePrincipal(
                kind="management",
                subject=USER_ID,
            ),
        )

        self.assertEqual(response.session_id, "session-id")
        session_config = storage.upsert_session.await_args.kwargs["config"]
        self.assertEqual(session_config.chat_model_config.model, "fixed-model")
        access.get_resource.assert_awaited_once_with(
            USER_ID,
            "credential",
            "credential-fixed-model",
        )

    async def test_platform_session_applies_exact_tool_allow_rules(
        self,
    ) -> None:
        fixed = _record("fixed", "fixed-model", fixed_model=True)
        access = SimpleNamespace(
            resolve_agent=AsyncMock(return_value=fixed),
            get_resource=AsyncMock(return_value=object()),
        )
        storage = SimpleNamespace(
            upsert_session=AsyncMock(
                return_value=SimpleNamespace(id="session-id"),
            ),
        )
        workspace = SimpleNamespace(
            assign_workspace_id=lambda **_: "workspace-id",
        )
        tool_name = "mcp__sample-package__import"

        await create_session(
            body=CreateSessionRequest(
                agent_id="fixed",
                platform_context=PlatformSessionContext(
                    user_id="1",
                    username="admin",
                    display_name="系统管理员",
                    project_id="2",
                    project_name="测试项目",
                    conversation_id="3",
                    conversation_title="项目初始化",
                    conversation_type="initialization",
                    agent_name="初始化助手",
                    auto_allowed_tool_names=[tool_name],
                ),
            ),
            user_id=USER_ID,
            storage=storage,
            workspace_manager=workspace,
            access=access,
            principal=AgentScopePrincipal(
                kind="service",
                subject="engineering-platform",
            ),
        )

        state = storage.upsert_session.await_args.kwargs["state"]
        rule = state.permission_context.allow_rules[tool_name][0]
        self.assertEqual(rule.tool_name, tool_name)
        self.assertEqual(rule.behavior.value, "allow")
        self.assertEqual(rule.source, "platformSession")

    async def test_fixed_agent_model_is_resynchronised_on_session_update(
        self,
    ) -> None:
        fixed = _record("fixed", "latest-fixed-model", fixed_model=True)
        session = SessionRecord(
            user_id=USER_ID,
            agent_id="fixed",
            config=SessionConfig(
                workspace_id="workspace-id",
                chat_model_config=_model("stale-model"),
            ),
        )
        access = SimpleNamespace(
            resolve_agent=AsyncMock(return_value=fixed),
            get_resource=AsyncMock(return_value=object()),
        )
        storage = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            upsert_session=AsyncMock(return_value=session),
        )

        await update_session(
            session_id=session.id,
            body=UpdateSessionRequest(name="同步配置"),
            agent_id="fixed",
            user_id=USER_ID,
            storage=storage,
            access=access,
            permission_review_service=SimpleNamespace(),
            principal=AgentScopePrincipal(
                kind="management",
                subject=USER_ID,
            ),
        )

        session_config = storage.upsert_session.await_args.kwargs["config"]
        self.assertEqual(
            session_config.chat_model_config.model,
            "latest-fixed-model",
        )

    async def test_platform_metadata_is_merged_into_source_message(
        self,
    ) -> None:
        message = UserMsg(
            name="平台用户",
            content="测试消息",
            id="message-1",
            metadata={"source": "engineering_platform"},
        )
        session = SessionRecord(
            user_id=USER_ID,
            agent_id="agent-1",
            config=SessionConfig(workspace_id="workspace"),
        )
        storage = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            get_message=AsyncMock(return_value=message),
            upsert_message=AsyncMock(),
        )

        result = await update_message_metadata(
            session_id="session-1",
            message_id="message-1",
            body=UpdateMessageMetadataRequest(
                metadata={"platform_status": "completed"},
            ),
            agent_id="agent-1",
            user_id=USER_ID,
            storage=storage,
            principal=AgentScopePrincipal(
                kind="management",
                subject=USER_ID,
            ),
        )

        self.assertEqual(result["content"][0]["text"], "测试消息")
        self.assertEqual(
            result["metadata"],
            {
                "source": "engineering_platform",
                "platform_status": "completed",
            },
        )
        persisted = storage.upsert_message.await_args.args[2]
        self.assertEqual(
            persisted.metadata["platform_status"],
            "completed",
        )

    async def test_platform_settings_round_trip_through_sqlite(self) -> None:
        storage = AsyncSQLAlchemyStorage(
            "sqlite+aiosqlite:///:memory:",
            create_tables=True,
        )
        async with storage:
            saved = await storage.upsert_platform_settings(
                USER_ID,
                PlatformSettingsData(
                    global_main_agent_id="main",
                    project_initializer_validation_mcp=(
                        PlatformMCPVersionBinding(
                            package_id="validation-rules",
                            version="2.0.0",
                        )
                    ),
                ),
            )
            loaded = await storage.get_platform_settings(USER_ID)

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.id, saved.id)
        self.assertEqual(loaded.data.global_main_agent_id, "main")
        self.assertEqual(
            loaded.data.project_initializer_validation_mcp,
            PlatformMCPVersionBinding(
                package_id="validation-rules",
                version="2.0.0",
            ),
        )

    async def test_alembic_creates_platform_settings_table(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "platform-settings.db"
            storage = AsyncSQLAlchemyStorage(
                f"sqlite+aiosqlite:///{db_path.as_posix()}",
                create_tables=False,
                auto_migrate=True,
            )
            async with storage:
                saved = await storage.upsert_platform_settings(
                    USER_ID,
                    PlatformSettingsData(global_main_agent_id="main"),
                )
                self.assertEqual(
                    saved.data.global_main_agent_id,
                    "main",
                )
