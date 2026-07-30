"""Regression tests for the engineering-platform integration contract."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from fastapi import HTTPException

from agentscope.agent import ContextConfig, ReActConfig
from agentscope.app._router._agent import (
    _demote_other_global_main_agents,
    _normalise_platform_agent_data,
    delete_agent,
    get_platform_agent_catalog,
    update_platform_settings,
)
from agentscope.app._router._schema import (
    CreateSessionRequest,
    UpdatePlatformSettingsRequest,
    UpdateSessionRequest,
)
from agentscope.app._router._session import create_session, update_session
from agentscope.app._service import AgentView
from agentscope.app.storage import (
    AgentCallConfig,
    AgentData,
    AgentModelPolicy,
    AgentRecord,
    ChatModelConfig,
    PlatformAgentConfig,
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
                "initializer",
                "Initializer",
                role="system_internal",
                published=False,
                fixed_model=True,
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
                        project_initializer_agent_id="initializer",
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
        self.assertEqual(catalog.project_initializer.id, "initializer")
        self.assertEqual(
            catalog.project_initializer.role,
            "system_internal",
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

    async def test_project_initializer_is_hidden_and_cannot_collaborate(
        self,
    ) -> None:
        main = _record(
            "main",
            "Main",
            role="global_main",
            fixed_model=True,
        )
        initializer = _record(
            "initializer",
            "Initializer",
            fixed_model=True,
        )
        storage = SimpleNamespace(
            get_agent=AsyncMock(return_value=initializer),
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        global_main_agent_id="main",
                    ),
                ),
            ),
            list_agents=AsyncMock(return_value=[main, initializer]),
            upsert_agent=AsyncMock(return_value="agent"),
            upsert_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        global_main_agent_id="main",
                        project_initializer_agent_id="initializer",
                    ),
                ),
            ),
        )

        response = await update_platform_settings(
            body=UpdatePlatformSettingsRequest(
                project_initializer_agent_id="initializer",
            ),
            user_id=USER_ID,
            storage=storage,
        )

        self.assertEqual(
            response.project_initializer_agent_id,
            "initializer",
        )
        updated_initializer = next(
            call.args[1]
            for call in storage.upsert_agent.await_args_list
            if call.args[1].id == "initializer"
        )
        self.assertEqual(
            updated_initializer.data.platform_config.role,
            "system_internal",
        )
        self.assertFalse(
            updated_initializer.data.platform_config.published,
        )
        self.assertEqual(
            updated_initializer.data.call_config.scope,
            "none",
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
        )

        self.assertEqual(response.session_id, "session-id")
        session_config = storage.upsert_session.await_args.kwargs["config"]
        self.assertEqual(session_config.chat_model_config.model, "fixed-model")
        access.get_resource.assert_awaited_once_with(
            USER_ID,
            "credential",
            "credential-fixed-model",
        )

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
        )

        session_config = storage.upsert_session.await_args.kwargs["config"]
        self.assertEqual(
            session_config.chat_model_config.model,
            "latest-fixed-model",
        )

    async def test_platform_settings_round_trip_through_sqlite(self) -> None:
        storage = AsyncSQLAlchemyStorage(
            "sqlite+aiosqlite:///:memory:",
            create_tables=True,
        )
        async with storage:
            saved = await storage.upsert_platform_settings(
                USER_ID,
                PlatformSettingsData(global_main_agent_id="main"),
            )
            loaded = await storage.get_platform_settings(USER_ID)

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.id, saved.id)
        self.assertEqual(loaded.data.global_main_agent_id, "main")

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
