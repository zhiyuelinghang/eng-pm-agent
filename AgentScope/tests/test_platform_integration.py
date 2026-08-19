"""Regression tests for the engineering-platform integration contract."""

import asyncio
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException, Response, UploadFile

from agentscope.agent import ContextConfig, ReActConfig
from agentscope.message import UserMsg
from agentscope.app._auth import AgentScopePrincipal
from agentscope.app._router._agent import (
    WEKNORA_FOLDER_PLACEHOLDER_CONTENT_TYPE,
    WEKNORA_FOLDER_PLACEHOLDER_FILENAME,
    _demote_other_global_main_agents,
    _extract_weknora_inline_citations,
    _fetch_weknora_folder_tree,
    _fetch_weknora_knowledge,
    _fetch_weknora_knowledge_bases,
    _normalise_platform_agent_data,
    _request_weknora_json,
    _search_weknora_knowledge,
    _stream_weknora_sse_events,
    _weknora_tool_reference_items,
    ask_weknora_agent,
    create_weknora_folder,
    create_weknora_agent_session,
    delete_agent,
    delete_weknora_folder,
    get_platform_agent_catalog,
    get_weknora_knowledge as _get_weknora_knowledge_endpoint,
    get_weknora_connection,
    list_weknora_project_bindings,
    list_weknora_knowledge as _list_weknora_knowledge_endpoint,
    list_weknora_knowledge_bases as _list_weknora_knowledge_bases_endpoint,
    proxy_weknora_resource,
    reveal_weknora_api_key,
    stop_weknora_agent_session,
    stream_weknora_agent,
    test_weknora_connection as _test_weknora_connection_endpoint,
    upload_weknora_knowledge as _upload_weknora_knowledge_endpoint,
    update_platform_settings,
    update_weknora_project_binding,
    update_weknora_connection,
)
from agentscope.app._router._schema import (
    AskWeKnoraAgentRequest,
    CreateWeKnoraAgentSessionRequest,
    CreateWeKnoraFolderRequest,
    CreateSessionRequest,
    SearchWeKnoraKnowledgeRequest,
    StopWeKnoraAgentSessionRequest,
    UpdateMessageMetadataRequest,
    UpdatePlatformSettingsRequest,
    UpdateWeKnoraProjectBindingRequest,
    TestWeKnoraConnectionRequest as WeKnoraConnectionTestRequest,
    UpdateWeKnoraConnectionRequest,
    UpdateSessionRequest,
    WeKnoraFolderItem,
    WeKnoraFolderTreeResponse,
    WeKnoraKnowledgeBaseItem,
    WeKnoraKnowledgeItem,
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
    WeKnoraConnectionConfig,
    SessionConfig,
    SessionRecord,
)
from agentscope.app.storage import AsyncSQLAlchemyStorage
from agentscope.app.storage._utils import _dump_with_secrets


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

    async def test_platform_settings_persists_engineering_document_agent(
        self,
    ) -> None:
        engineering = _record(
            "engineering-documents",
            "Engineering Documents",
            fixed_model=True,
        )
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="preserved-secret",
        )
        storage = SimpleNamespace(
            get_agent=AsyncMock(return_value=engineering),
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        weknora_connection=connection,
                    ),
                ),
            ),
            list_agents=AsyncMock(return_value=[engineering]),
            upsert_agent=AsyncMock(return_value="agent"),
        )

        async def save_settings(_user_id, data):
            return PlatformSettingsRecord(user_id=USER_ID, data=data)

        storage.upsert_platform_settings = AsyncMock(side_effect=save_settings)

        response = await update_platform_settings(
            body=UpdatePlatformSettingsRequest(
                engineering_document_agent_id=engineering.id,
            ),
            user_id=USER_ID,
            storage=storage,
            manager=SimpleNamespace(list_records=AsyncMock(return_value=[])),
        )

        self.assertEqual(response.engineering_document_agent_id, engineering.id)
        saved = storage.upsert_platform_settings.await_args.args[1]
        self.assertEqual(saved.engineering_document_agent_id, engineering.id)
        self.assertEqual(
            saved.weknora_connection.api_key.get_secret_value(),
            "preserved-secret",
        )

    async def test_engineering_document_agent_rejects_disabled_agent(
        self,
    ) -> None:
        disabled = _record(
            "engineering-disabled",
            "Engineering Disabled",
            enabled=False,
            fixed_model=True,
        )
        storage = SimpleNamespace(
            get_agent=AsyncMock(return_value=disabled),
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(user_id=USER_ID),
            ),
            list_agents=AsyncMock(return_value=[disabled]),
            upsert_agent=AsyncMock(return_value="agent"),
        )

        with self.assertRaises(HTTPException) as context:
            await update_platform_settings(
                body=UpdatePlatformSettingsRequest(
                    engineering_document_agent_id=disabled.id,
                ),
                user_id=USER_ID,
                storage=storage,
                manager=SimpleNamespace(
                    list_records=AsyncMock(return_value=[]),
                ),
            )

        self.assertEqual(context.exception.status_code, 422)

    async def test_weknora_connection_is_configurable_and_secret_free(
        self,
    ) -> None:
        current = PlatformSettingsRecord(user_id=USER_ID)

        async def load_settings(_user_id):
            return current

        async def save_settings(_user_id, data):
            nonlocal current
            current = PlatformSettingsRecord(user_id=USER_ID, data=data)
            return current

        storage = SimpleNamespace(
            get_platform_settings=AsyncMock(side_effect=load_settings),
            upsert_platform_settings=AsyncMock(side_effect=save_settings),
            list_agents=AsyncMock(return_value=[]),
            upsert_agent=AsyncMock(return_value="agent"),
        )

        response = await update_weknora_connection(
            body=UpdateWeKnoraConnectionRequest(
                base_url="https://weknora.example.com/",
                api_prefix="api/v1/",
                auth_header="X-API-Key",
                api_key="tenant-secret",
            ),
            user_id=USER_ID,
            storage=storage,
        )

        self.assertEqual(response.base_url, "https://weknora.example.com")
        self.assertEqual(response.api_prefix, "/api/v1")
        self.assertTrue(response.api_key_configured)
        self.assertNotIn("api_key", response.model_dump())
        self.assertEqual(
            current.data.weknora_connection.api_key.get_secret_value(),
            "tenant-secret",
        )

        response = await update_weknora_connection(
            body=UpdateWeKnoraConnectionRequest(
                base_url="https://weknora.example.com",
                api_prefix="/api/v2",
                auth_header="X-Tenant-Key",
            ),
            user_id=USER_ID,
            storage=storage,
        )

        self.assertEqual(response.api_prefix, "/api/v2")
        self.assertEqual(
            current.data.weknora_connection.api_key.get_secret_value(),
            "tenant-secret",
        )
        dumped = _dump_with_secrets(current)
        self.assertEqual(
            dumped["data"]["weknora_connection"]["api_key"],
            "tenant-secret",
        )
        read_response = await get_weknora_connection(
            user_id=USER_ID,
            storage=storage,
        )
        self.assertNotIn("api_key", read_response.model_dump())

    async def test_weknora_connection_test_uses_saved_secret(self) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_prefix="/api/v1",
            auth_header="X-API-Key",
            agent_id="agent-001",
            api_key="saved-secret",
        )
        storage = SimpleNamespace(
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        weknora_connection=connection,
                    ),
                ),
            ),
            list_agents=AsyncMock(return_value=[]),
            upsert_agent=AsyncMock(return_value="agent"),
        )
        probe = AsyncMock(return_value=3)

        with patch(
            "agentscope.app._router._agent._probe_weknora",
            new=probe,
        ):
            response = await _test_weknora_connection_endpoint(
                body=WeKnoraConnectionTestRequest(
                    base_url="https://weknora.example.com",
                    api_prefix="/api/v1",
                    auth_header="X-API-Key",
                ),
                user_id=USER_ID,
                storage=storage,
            )

        self.assertTrue(response.success)
        self.assertEqual(response.knowledge_base_count, 3)
        probed = probe.await_args.args[0]
        self.assertEqual(probed.api_key.get_secret_value(), "saved-secret")

    async def test_weknora_requests_allow_loopback_and_private_endpoints(
        self,
    ) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="http://127.219.0.240:8080",
            api_prefix="/api/v1",
            auth_header="X-API-Key",
            api_key="saved-secret",
        )
        response = httpx.Response(
            200,
            json={"success": True, "data": {"items": []}},
            request=httpx.Request(
                "GET",
                "http://127.219.0.240:8080/api/v1/knowledge-bases",
            ),
        )
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = False
        client.request.return_value = response

        with patch(
            "agentscope.app._router._agent.httpx.AsyncClient",
            return_value=client,
        ):
            payload = await _request_weknora_json(
                connection,
                "/knowledge-bases",
            )

        self.assertTrue(payload["success"])
        client.request.assert_awaited_once()

    async def test_weknora_invalid_json_records_raw_response_diagnostic(
        self,
    ) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_prefix="/api/v1",
            auth_header="X-API-Key",
            api_key="saved-secret",
        )
        response = httpx.Response(
            200,
            content=b"<html><body>upstream overloaded</body></html>",
            headers={"content-type": "text/html", "x-request-id": "wk-7"},
            request=httpx.Request(
                "GET",
                "https://weknora.example.com/api/v1/knowledge-bases",
            ),
        )
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = False
        client.request.return_value = response

        with (
            patch(
                "agentscope.app._router._agent.httpx.AsyncClient",
                return_value=client,
            ),
            patch(
                "agentscope.app._router._agent._record_weknora_invalid_json",
            ) as record_diagnostic,
        ):
            with self.assertRaisesRegex(HTTPException, "诊断编号"):
                await _request_weknora_json(connection, "/knowledge-bases")

        record_diagnostic.assert_called_once()
        self.assertEqual(
            record_diagnostic.call_args.args[0].content,
            response.content,
        )
        self.assertEqual(
            record_diagnostic.call_args.kwargs["path"],
            "/knowledge-bases",
        )

    async def test_weknora_json_requests_are_queued_instead_of_bursting(
        self,
    ) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_prefix="/api/v1",
            auth_header="X-API-Key",
            api_key="saved-secret",
        )
        active_requests = 0
        max_active_requests = 0

        class RecordingClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                del args
                return False

            async def request(self, method, url, **kwargs):
                nonlocal active_requests, max_active_requests
                del kwargs
                active_requests += 1
                max_active_requests = max(max_active_requests, active_requests)
                await asyncio.sleep(0.01)
                active_requests -= 1
                return httpx.Response(
                    200,
                    json={"success": True, "data": {}},
                    request=httpx.Request(method, url),
                )

        with (
            patch(
                "agentscope.app._router._agent.httpx.AsyncClient",
                return_value=RecordingClient(),
            ),
            patch(
                "agentscope.app._router._agent._weknora_json_request_gate",
                new=asyncio.Semaphore(1),
            ),
        ):
            await asyncio.gather(
                _request_weknora_json(connection, "/knowledge-bases"),
                _request_weknora_json(connection, "/agents/agent-1"),
                _request_weknora_json(connection, "/sessions"),
            )

        self.assertEqual(max_active_requests, 1)

    async def test_project_robot_bindings_are_loaded_from_business_db(
        self,
    ) -> None:
        projects = [
            {
                "project_id": 7,
                "project_name": "滨江项目",
                "weknora_agent_id": "robot-007",
                "updated_at": None,
            },
            {
                "project_id": 8,
                "project_name": "城北项目",
                "weknora_agent_id": None,
                "updated_at": None,
            },
        ]
        with patch(
            "agentscope.app._router._agent._request_dobby_project_bindings",
            new=AsyncMock(return_value=projects),
        ):
            response = await list_weknora_project_bindings(user_id=USER_ID)

        self.assertEqual(response.total, 2)
        self.assertEqual(response.projects[0].weknora_agent_id, "robot-007")
        self.assertIsNone(response.projects[1].weknora_agent_id)

    async def test_project_robot_is_validated_before_it_is_persisted(
        self,
    ) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )
        storage = SimpleNamespace(
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(weknora_connection=connection),
                ),
            ),
            list_agents=AsyncMock(return_value=[]),
            upsert_agent=AsyncMock(),
        )
        persisted = {
            "project_id": 7,
            "project_name": "滨江项目",
            "weknora_agent_id": "robot-007",
            "updated_at": None,
        }
        persist_mock = AsyncMock(return_value=persisted)
        with (
            patch(
                "agentscope.app._router._agent._fetch_weknora_agent",
                new=AsyncMock(
                    return_value=("robot-007", "滨江资料机器人", ["kb-1"]),
                ),
            ) as fetch_mock,
            patch(
                "agentscope.app._router._agent._request_dobby_project_bindings",
                new=persist_mock,
            ),
        ):
            response = await update_weknora_project_binding(
                project_id=7,
                body=UpdateWeKnoraProjectBindingRequest(
                    weknora_agent_id=" robot-007 ",
                ),
                user_id=USER_ID,
                storage=storage,
            )

        self.assertEqual(response.weknora_agent_id, "robot-007")
        fetch_mock.assert_awaited_once_with(connection, "robot-007")
        persist_mock.assert_awaited_once_with(
            "/7",
            method="PUT",
            json_body={"weknora_agent_id": "robot-007"},
        )

    async def test_weknora_api_key_is_revealed_only_by_explicit_endpoint(
        self,
    ) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )
        storage = SimpleNamespace(
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        weknora_connection=connection,
                    ),
                ),
            ),
            list_agents=AsyncMock(return_value=[]),
            upsert_agent=AsyncMock(return_value="agent"),
        )
        raw_response = Response()

        revealed = await reveal_weknora_api_key(
            response=raw_response,
            user_id=USER_ID,
            storage=storage,
        )

        self.assertEqual(revealed.api_key, "saved-secret")
        self.assertEqual(raw_response.headers["cache-control"], "no-store")
        self.assertEqual(raw_response.headers["pragma"], "no-cache")

        connection_view = await get_weknora_connection(
            user_id=USER_ID,
            storage=storage,
        )
        self.assertNotIn("api_key", connection_view.model_dump())

    async def test_weknora_knowledge_bases_are_loaded_with_saved_connection(
        self,
    ) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )
        storage = SimpleNamespace(
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        weknora_connection=connection,
                    ),
                ),
            ),
            list_agents=AsyncMock(return_value=[]),
            upsert_agent=AsyncMock(return_value="agent"),
        )
        fetch = AsyncMock(
            return_value=[
                WeKnoraKnowledgeBaseItem(
                    id="kb-1",
                    name="工程规范",
                    description="施工规范与验收资料",
                ),
            ],
        )

        with patch(
            "agentscope.app._router._agent._fetch_weknora_knowledge_bases",
            new=fetch,
        ):
            response = await _list_weknora_knowledge_bases_endpoint(
                user_id=USER_ID,
                storage=storage,
            )

        self.assertEqual(response.total, 1)
        self.assertEqual(response.knowledge_bases[0].id, "kb-1")
        fetched_connection = fetch.await_args.args[0]
        self.assertEqual(
            fetched_connection.api_key.get_secret_value(),
            "saved-secret",
        )

    async def test_weknora_knowledge_is_loaded_for_selected_base(self) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )
        storage = SimpleNamespace(
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        weknora_connection=connection,
                    ),
                ),
            ),
            list_agents=AsyncMock(return_value=[]),
            upsert_agent=AsyncMock(return_value="agent"),
        )
        fetch = AsyncMock(
            return_value=(
                [
                    WeKnoraKnowledgeItem(
                        id="knowledge-1",
                        knowledge_base_id="kb/1",
                        title="施工组织设计.pdf",
                        file_name="施工组织设计.pdf",
                        file_type="pdf",
                        file_size=2048,
                        parse_status="completed",
                    ),
                ],
                1,
            ),
        )

        with patch(
            "agentscope.app._router._agent._fetch_weknora_knowledge",
            new=fetch,
        ):
            response = await _list_weknora_knowledge_endpoint(
                knowledge_base_id="kb/1",
                page=2,
                page_size=20,
                folder_path="01_合同图纸与方案/图纸",
                folder_recursive=False,
                keyword="人防",
                user_id=USER_ID,
                storage=storage,
            )

        self.assertEqual(response.total, 1)
        self.assertEqual(response.page, 2)
        self.assertEqual(response.knowledge[0].parse_status, "completed")
        self.assertEqual(fetch.await_args.args[1], "kb/1")
        self.assertEqual(
            fetch.await_args.kwargs,
            {
                "page": 2,
                "page_size": 20,
                "folder_path": "01_合同图纸与方案/图纸",
                "folder_recursive": False,
                "keyword": "人防",
            },
        )

    async def test_weknora_knowledge_detail_uses_robot_scope(self) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )
        storage = SimpleNamespace(
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        weknora_connection=connection,
                    ),
                ),
            ),
            list_agents=AsyncMock(return_value=[]),
            upsert_agent=AsyncMock(return_value="agent"),
        )
        expected = WeKnoraKnowledgeItem(
            id="knowledge/1",
            knowledge_base_id="kb/1",
            file_name="施工组织设计.pdf",
            folder_path="01_合同图纸与方案/图纸",
        )
        allowed_ids = AsyncMock(return_value=["kb/1"])
        require_access = AsyncMock(return_value=expected)

        with (
            patch(
                "agentscope.app._router._agent."
                "_weknora_agent_knowledge_base_ids",
                new=allowed_ids,
            ),
            patch(
                "agentscope.app._router._agent."
                "_require_weknora_knowledge_access",
                new=require_access,
            ),
        ):
            response = await _get_weknora_knowledge_endpoint(
                knowledge_id="knowledge/1",
                weknora_agent_id="robot-1",
                user_id=USER_ID,
                storage=storage,
            )

        self.assertEqual(response, expected)
        allowed_ids.assert_awaited_once_with(connection, "robot-1")
        require_access.assert_awaited_once_with(
            connection,
            "knowledge/1",
            ["kb/1"],
        )

    async def test_weknora_list_shapes_and_root_pagination_are_normalised(
        self,
    ) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )
        request = AsyncMock(
            side_effect=[
                {
                    "success": True,
                    "data": [
                        {
                            "id": "kb-1",
                            "name": "工程规范",
                            "description": "施工规范与验收资料",
                        },
                    ],
                },
                {
                    "success": True,
                    "data": [
                        {
                            "id": "knowledge-1",
                            "title": "施工组织设计",
                            "file_name": "施工组织设计.pdf",
                            "folder_path": "01_合同图纸与方案/方案",
                            "file_type": "pdf",
                            "file_size": "2048",
                            "parse_status": "completed",
                        },
                    ],
                    "total": 877,
                    "page": 2,
                    "page_size": 20,
                },
                {
                    "success": True,
                    "data": [],
                    "total": 0,
                },
            ],
        )

        with patch(
            "agentscope.app._router._agent._request_weknora_json",
            new=request,
        ):
            knowledge_bases = await _fetch_weknora_knowledge_bases(connection)
            knowledge, total = await _fetch_weknora_knowledge(
                connection,
                "kb/1",
                page=2,
                page_size=20,
            )

        self.assertEqual(knowledge_bases[0].name, "工程规范")
        self.assertEqual(knowledge[0].file_size, 2048)
        self.assertEqual(knowledge[0].knowledge_base_id, "kb/1")
        self.assertEqual(
            knowledge[0].folder_path,
            "01_合同图纸与方案/方案",
        )
        self.assertEqual(total, 877)
        self.assertEqual(
            request.await_args_list[0].args,
            (connection, "/knowledge-bases"),
        )
        self.assertEqual(
            request.await_args_list[1].args,
            (connection, "/knowledge-bases/kb%2F1/knowledge"),
        )
        self.assertEqual(
            request.await_args_list[1].kwargs,
            {"params": {"page": 2, "page_size": 20}},
        )

    async def test_weknora_folder_tree_uses_documented_contract(self) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )
        request = AsyncMock(
            side_effect=[{
                "success": True,
                "data": {
                    "root_document_count": 2,
                    "total_document_count": 12,
                    "folders": [
                        {
                            "path": "01_合同图纸与方案",
                            "name": "01_合同图纸与方案",
                            "document_count": 3,
                            "total_count": 10,
                            "children": [
                                {
                                    "path": "01_合同图纸与方案/图纸",
                                    "name": "图纸",
                                    "document_count": 7,
                                    "total_count": 7,
                                },
                            ],
                        },
                    ],
                },
            }, {
                "success": True,
                "data": [],
                "total": 0,
            }],
        )

        with patch(
            "agentscope.app._router._agent._request_weknora_json",
            new=request,
        ):
            tree = await _fetch_weknora_folder_tree(connection, "kb/1")

        self.assertEqual(tree.root_document_count, 2)
        self.assertEqual(tree.total_document_count, 12)
        self.assertEqual(tree.folders[0].children[0].name, "图纸")
        self.assertEqual(
            request.await_args_list[0].args,
            (connection, "/knowledge-bases/kb%2F1/knowledge/folders"),
        )

    async def test_weknora_folder_markers_are_hidden_from_file_lists(
        self,
    ) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )
        marker = {
            "id": "folder-marker-1",
            "file_name": WEKNORA_FOLDER_PLACEHOLDER_FILENAME,
            "folder_path": "方案/空目录",
            "file_size": 0,
        }
        request = AsyncMock(
            side_effect=[
                {
                    "success": True,
                    "data": [
                        {
                            "id": "knowledge-1",
                            "file_name": "施工方案.pdf",
                            "folder_path": "方案/空目录",
                        },
                        marker,
                    ],
                    "total": 2,
                },
                {"success": True, "data": [marker], "total": 1},
            ],
        )

        with patch(
            "agentscope.app._router._agent._request_weknora_json",
            new=request,
        ):
            knowledge, total = await _fetch_weknora_knowledge(
                connection,
                "kb-1",
                page=1,
                page_size=100,
                folder_path="方案/空目录",
                folder_recursive=False,
            )

        self.assertEqual([item.id for item in knowledge], ["knowledge-1"])
        self.assertEqual(total, 1)

    async def test_weknora_folder_markers_are_hidden_from_counts(self) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )
        request = AsyncMock(
            side_effect=[
                {
                    "success": True,
                    "data": {
                        "root_document_count": 0,
                        "total_document_count": 3,
                        "folders": [
                            {
                                "path": "方案",
                                "name": "方案",
                                "document_count": 1,
                                "total_count": 3,
                                "children": [
                                    {
                                        "path": "方案/空目录",
                                        "name": "空目录",
                                        "document_count": 1,
                                        "total_count": 1,
                                    },
                                ],
                            },
                        ],
                    },
                },
                {
                    "success": True,
                    "data": [
                        {
                            "id": "folder-marker-1",
                            "file_name": WEKNORA_FOLDER_PLACEHOLDER_FILENAME,
                            "folder_path": "方案/空目录",
                        },
                    ],
                    "total": 1,
                },
            ],
        )

        with patch(
            "agentscope.app._router._agent._request_weknora_json",
            new=request,
        ):
            tree = await _fetch_weknora_folder_tree(connection, "kb-1")

        self.assertEqual(tree.total_document_count, 2)
        self.assertEqual(tree.folders[0].document_count, 1)
        self.assertEqual(tree.folders[0].total_count, 2)
        self.assertEqual(tree.folders[0].children[0].document_count, 0)
        self.assertEqual(tree.folders[0].children[0].total_count, 0)

    async def test_weknora_folder_creation_uploads_empty_private_marker(
        self,
    ) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )
        storage = SimpleNamespace(
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        weknora_connection=connection,
                    ),
                ),
            ),
            list_agents=AsyncMock(return_value=[]),
            upsert_agent=AsyncMock(return_value="agent"),
        )
        request = AsyncMock(
            side_effect=[
                {
                    "success": True,
                    "data": {
                        "root_document_count": 0,
                        "total_document_count": 0,
                        "folders": [],
                    },
                },
                {"success": True, "data": [], "total": 0},
                {
                    "success": True,
                    "data": {
                        "id": "folder-marker-1",
                        "file_name": WEKNORA_FOLDER_PLACEHOLDER_FILENAME,
                        "folder_path": "方案/新目录",
                    },
                },
            ],
        )

        with patch(
            "agentscope.app._router._agent._request_weknora_json",
            new=request,
        ):
            response = await create_weknora_folder(
                knowledge_base_id="kb/1",
                body=CreateWeKnoraFolderRequest(
                    folder_path="/方案/新目录/",
                ),
                user_id=USER_ID,
                storage=storage,
            )

        upload_call = request.await_args_list[2]
        self.assertEqual(response.knowledge_id, "folder-marker-1")
        self.assertEqual(
            upload_call.kwargs["data"],
            {
                "enable_multimodel": "false",
                "channel": "api",
                "fileName": (
                    f"方案/新目录/{WEKNORA_FOLDER_PLACEHOLDER_FILENAME}"
                ),
                "folder_path": "方案/新目录",
            },
        )
        self.assertEqual(
            upload_call.kwargs["files"]["file"],
            (
                WEKNORA_FOLDER_PLACEHOLDER_FILENAME,
                b"",
                WEKNORA_FOLDER_PLACEHOLDER_CONTENT_TYPE,
            ),
        )

    async def test_weknora_empty_folder_deletion_removes_its_marker(
        self,
    ) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )
        storage = SimpleNamespace(
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        weknora_connection=connection,
                    ),
                ),
            ),
            list_agents=AsyncMock(return_value=[]),
            upsert_agent=AsyncMock(return_value="agent"),
        )
        tree = WeKnoraFolderTreeResponse(
            folders=[WeKnoraFolderItem(
                path="方案/空目录",
                name="空目录",
            )],
        )
        marker = WeKnoraKnowledgeItem(
            id="folder-marker/1",
            file_name=WEKNORA_FOLDER_PLACEHOLDER_FILENAME,
            folder_path="方案/空目录",
        )
        request = AsyncMock(return_value={"success": True})

        with (
            patch(
                "agentscope.app._router._agent._weknora_agent_knowledge_base_ids",
                new=AsyncMock(return_value=["kb/1"]),
            ),
            patch(
                "agentscope.app._router._agent._fetch_weknora_folder_tree",
                new=AsyncMock(return_value=tree),
            ),
            patch(
                "agentscope.app._router._agent._fetch_weknora_folder_placeholders",
                new=AsyncMock(return_value=[marker]),
            ),
            patch(
                "agentscope.app._router._agent._request_weknora_json",
                new=request,
            ),
        ):
            response = await delete_weknora_folder(
                knowledge_base_id="kb/1",
                folder_path="/方案/空目录/",
                weknora_agent_id="robot-1",
                user_id=USER_ID,
                storage=storage,
            )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            request.await_args.args,
            (connection, "/knowledge/folder-marker%2F1"),
        )
        self.assertEqual(request.await_args.kwargs, {"method": "DELETE"})

    async def test_weknora_folder_deletion_rejects_child_folders(
        self,
    ) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )
        storage = SimpleNamespace(
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        weknora_connection=connection,
                    ),
                ),
            ),
            list_agents=AsyncMock(return_value=[]),
            upsert_agent=AsyncMock(return_value="agent"),
        )
        tree = WeKnoraFolderTreeResponse(
            folders=[WeKnoraFolderItem(
                path="方案/父目录",
                name="父目录",
                children=[WeKnoraFolderItem(
                    path="方案/父目录/子目录",
                    name="子目录",
                )],
            )],
        )

        with (
            patch(
                "agentscope.app._router._agent._weknora_agent_knowledge_base_ids",
                new=AsyncMock(return_value=["kb-1"]),
            ),
            patch(
                "agentscope.app._router._agent._fetch_weknora_folder_tree",
                new=AsyncMock(return_value=tree),
            ),
        ):
            with self.assertRaises(HTTPException) as caught:
                await delete_weknora_folder(
                    knowledge_base_id="kb-1",
                    folder_path="方案/父目录",
                    weknora_agent_id="robot-1",
                    user_id=USER_ID,
                    storage=storage,
                )

        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("只能删除空目录", str(caught.exception.detail))

    async def test_recursive_weknora_folder_deletion_removes_all_content(
        self,
    ) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )
        storage = SimpleNamespace(
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        weknora_connection=connection,
                    ),
                ),
            ),
            list_agents=AsyncMock(return_value=[]),
            upsert_agent=AsyncMock(return_value="agent"),
        )
        tree = WeKnoraFolderTreeResponse(
            folders=[WeKnoraFolderItem(
                path="方案/父目录",
                name="父目录",
                document_count=1,
                total_count=2,
                children=[WeKnoraFolderItem(
                    path="方案/父目录/子目录",
                    name="子目录",
                    document_count=1,
                    total_count=1,
                )],
            )],
        )
        markers = [
            WeKnoraKnowledgeItem(
                id="marker-root",
                file_name=WEKNORA_FOLDER_PLACEHOLDER_FILENAME,
                folder_path="方案/父目录",
            ),
            WeKnoraKnowledgeItem(
                id="marker-child",
                file_name=WEKNORA_FOLDER_PLACEHOLDER_FILENAME,
                folder_path="方案/父目录/子目录",
            ),
        ]
        request = AsyncMock(
            side_effect=[
                {
                    "success": True,
                    "data": [
                        {
                            "id": "knowledge/root",
                            "file_name": "根目录方案.pdf",
                            "folder_path": "方案/父目录",
                        },
                        {
                            "id": "knowledge-child",
                            "file_name": "子目录方案.pdf",
                            "folder_path": "方案/父目录/子目录",
                        },
                        {
                            "id": "marker-root",
                            "file_name": WEKNORA_FOLDER_PLACEHOLDER_FILENAME,
                            "folder_path": "方案/父目录",
                        },
                    ],
                    "total": 3,
                },
                {"success": True},
                {"success": True},
                {"success": True},
                {"success": True},
            ],
        )

        with (
            patch(
                "agentscope.app._router._agent._weknora_agent_knowledge_base_ids",
                new=AsyncMock(return_value=["kb/1"]),
            ),
            patch(
                "agentscope.app._router._agent._fetch_weknora_folder_tree",
                new=AsyncMock(return_value=tree),
            ),
            patch(
                "agentscope.app._router._agent._fetch_weknora_folder_placeholders",
                new=AsyncMock(return_value=markers),
            ),
            patch(
                "agentscope.app._router._agent._request_weknora_json",
                new=request,
            ),
        ):
            response = await delete_weknora_folder(
                knowledge_base_id="kb/1",
                folder_path="方案/父目录",
                recursive=True,
                weknora_agent_id="robot-1",
                user_id=USER_ID,
                storage=storage,
            )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            request.await_args_list[0].kwargs["params"],
            {
                "page": 1,
                "page_size": 100,
                "folder_path": "方案/父目录",
                "folder_recursive": "true",
            },
        )
        self.assertEqual(
            [call.args[1] for call in request.await_args_list[1:]],
            [
                "/knowledge/knowledge%2Froot",
                "/knowledge/knowledge-child",
                "/knowledge/marker-child",
                "/knowledge/marker-root",
            ],
        )

    async def test_weknora_upload_separates_filename_and_folder_path(
        self,
    ) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )
        storage = SimpleNamespace(
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        weknora_connection=connection,
                    ),
                ),
            ),
            list_agents=AsyncMock(return_value=[]),
            upsert_agent=AsyncMock(return_value="agent"),
        )
        request = AsyncMock(
            return_value={
                "success": True,
                "data": {
                    "id": "knowledge-1",
                    "file_name": "监测报表.pdf",
                    "parse_status": "pending",
                },
            },
        )
        upload = UploadFile(
            file=BytesIO(b"pdf-content"),
            filename="监测报表.pdf",
        )

        with patch(
            "agentscope.app._router._agent._request_weknora_json",
            new=request,
        ):
            response = await _upload_weknora_knowledge_endpoint(
                knowledge_base_id="kb/1",
                file=upload,
                enable_multimodel=True,
                folder_path="/04_监测检测与试验/",
                user_id=USER_ID,
                storage=storage,
            )

        self.assertEqual(response.knowledge_id, "knowledge-1")
        self.assertEqual(
            request.await_args.kwargs["data"],
            {
                "enable_multimodel": "true",
                "channel": "api",
                "fileName": "监测报表.pdf",
                "folder_path": "04_监测检测与试验",
            },
        )

    async def test_weknora_hybrid_search_uses_documented_contract(self) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )
        request = AsyncMock(
            side_effect=[
                {
                    "success": True,
                    "data": [
                        {
                            "knowledge_id": "knowledge-1",
                            "knowledge_title": "VPN 配置手册",
                            "knowledge_filename": "vpn-guide.pdf",
                            "content": "VPN 连接配置步骤",
                            "score": 0.92,
                            "chunk_index": 3,
                            "start_at": 1200,
                            "end_at": 1800,
                            "match_type": "hybrid",
                        },
                    ],
                },
                {
                    "success": True,
                    "data": [
                        {
                            "id": "knowledge-1",
                            "file_name": "vpn-guide.pdf",
                            "folder_path": "运维/VPN",
                            "file_type": "pdf",
                            "file_size": 2048000,
                            "parse_status": "completed",
                        },
                    ],
                },
            ],
        )

        with patch(
            "agentscope.app._router._agent._request_weknora_json",
            new=request,
        ):
            references = await _search_weknora_knowledge(
                connection,
                "kb/1",
                SearchWeKnoraKnowledgeRequest(query="如何配置 VPN？"),
            )

        self.assertEqual(len(references), 1)
        self.assertEqual(references[0].filename, "vpn-guide.pdf")
        self.assertEqual(references[0].file_type, "pdf")
        self.assertEqual(references[0].folder_path, "运维/VPN")
        self.assertEqual(references[0].score, 0.92)
        self.assertEqual(
            request.await_args_list[0].args,
            (connection, "/knowledge-bases/kb%2F1/hybrid-search"),
        )
        self.assertEqual(
            request.await_args_list[0].kwargs,
            {
                "method": "POST",
                "json_body": {
                    "query_text": "如何配置 VPN？",
                    "vector_threshold": 0.5,
                    "keyword_threshold": 0.3,
                    "match_count": 5,
                },
            },
        )
        self.assertEqual(
            request.await_args_list[1].args,
            (connection, "/knowledge/batch"),
        )
        self.assertEqual(
            request.await_args_list[1].kwargs,
            {"params": {"ids": "knowledge-1"}},
        )

    async def test_weknora_agent_query_uses_project_robot_id(self) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            agent_id="agent-001",
            api_key="saved-secret",
        )
        storage = SimpleNamespace(
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        weknora_connection=connection,
                    ),
                ),
            ),
            list_agents=AsyncMock(return_value=[]),
            upsert_agent=AsyncMock(return_value="agent"),
        )
        request = AsyncMock(
            side_effect=[
                {
                    "success": True,
                    "data": {"id": "session-001"},
                },
                {
                    "success": True,
                    "data": [
                        {
                            "id": "knowledge-1",
                            "file_name": "方案.pdf",
                            "folder_path": "方案",
                            "file_type": "pdf",
                            "file_size": 2048,
                            "parse_status": "completed",
                        },
                    ],
                },
            ],
        )
        sse = AsyncMock(
            return_value=[
                {"response_type": "answer", "content": "第一段"},
                {"response_type": "answer", "content": "第二段"},
                {
                    "response_type": "references",
                    "knowledge_references": [
                        {
                            "id": "chunk-1",
                            "knowledge_id": "knowledge-1",
                            "content": "与问题匹配的方案片段",
                            "score": 0.9,
                            "chunk_index": 2,
                            "match_type": "hybrid",
                            "chunk_type": "text",
                            "knowledge_channel": "web",
                        },
                    ],
                },
                {
                    "response_type": "session_title",
                    "content": "方案对比",
                    "done": True,
                },
                {"response_type": "complete"},
            ],
        )

        with (
            patch(
                "agentscope.app._router._agent._request_weknora_json",
                new=request,
            ),
            patch(
                "agentscope.app._router._agent._request_weknora_sse",
                new=sse,
            ),
            patch(
                "agentscope.app._router._agent._weknora_agent_knowledge_base_ids",
                new=AsyncMock(return_value=["kb-001"]),
            ),
        ):
            response = await ask_weknora_agent(
                body=AskWeKnoraAgentRequest(
                    query="对比两种方案",
                    weknora_agent_id="project-robot-001",
                    knowledge_base_ids=["kb-001"],
                ),
                user_id=USER_ID,
                storage=storage,
            )

        self.assertEqual(response.session_id, "session-001")
        self.assertEqual(response.answer, "第一段第二段")
        self.assertEqual(response.references[0]["knowledge_id"], "knowledge-1")
        self.assertEqual(response.references[0]["filename"], "方案.pdf")
        self.assertEqual(response.references[0]["chunk_id"], "chunk-1")
        self.assertEqual(response.references[0]["chunk_index"], 2)
        self.assertEqual(response.references[0]["match_type"], "hybrid")
        self.assertEqual(response.references[0]["chunk_type"], "text")
        self.assertEqual(response.references[0]["knowledge_channel"], "web")
        self.assertEqual(response.session_title, "方案对比")
        self.assertEqual(
            request.await_args_list[0].args,
            (connection, "/sessions"),
        )
        self.assertEqual(
            request.await_args_list[0].kwargs,
            {"method": "POST", "json_body": {"agent_id": "project-robot-001"}},
        )
        self.assertEqual(
            sse.await_args.args,
            (
                connection,
                "/agent-chat/session-001",
                {
                    "query": "对比两种方案",
                    "agent_enabled": True,
                    "agent_id": "project-robot-001",
                    "knowledge_base_ids": ["kb-001"],
                    "knowledge_ids": [],
                    "channel": "api",
                },
            ),
        )
        self.assertEqual(
            sse.await_args.kwargs,
            {
                "params": {"resource_urls": "public"},
                "session_id": "session-001",
            },
        )

    async def test_weknora_agent_query_resolves_inline_kb_citations(
        self,
    ) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )
        storage = SimpleNamespace(
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        weknora_connection=connection,
                    ),
                ),
            ),
            list_agents=AsyncMock(return_value=[]),
            upsert_agent=AsyncMock(return_value="agent"),
        )
        request = AsyncMock(
            side_effect=[
                {"success": True, "data": {"id": "session-inline"}},
                {
                    "success": True,
                    "data": [
                        {
                            "id": "knowledge-safety-helmet",
                            "knowledge_base_id": "kb-001",
                            "title": "安全帽zmd.pdf",
                            "file_name": "安全帽zmd.pdf",
                            "folder_path": "安全防护用品",
                            "file_type": "pdf",
                            "file_size": 8192,
                            "channel": "web",
                            "parse_status": "completed",
                        },
                    ],
                    "total": 1,
                },
            ],
        )
        answer = (
            "安全帽应满足冲击吸收要求。"
            '<kb doc="安全帽zmd.pdf" chunk_id="chunk-inline-1" '
            'kb_id="kb-001" />'
        )
        sse = AsyncMock(
            return_value=[
                {"response_type": "answer", "content": answer, "done": True},
            ],
        )

        with (
            patch(
                "agentscope.app._router._agent._request_weknora_json",
                new=request,
            ),
            patch(
                "agentscope.app._router._agent._request_weknora_sse",
                new=sse,
            ),
            patch(
                "agentscope.app._router._agent._weknora_agent_knowledge_base_ids",
                new=AsyncMock(return_value=["kb-001"]),
            ),
        ):
            response = await ask_weknora_agent(
                body=AskWeKnoraAgentRequest(
                    query="安全帽有哪些关键要求？",
                    weknora_agent_id="project-robot-001",
                ),
                user_id=USER_ID,
                storage=storage,
            )

        self.assertEqual(response.answer, answer)
        self.assertEqual(len(response.references), 1)
        reference = response.references[0]
        self.assertEqual(reference["chunk_id"], "chunk-inline-1")
        self.assertEqual(reference["knowledge_id"], "knowledge-safety-helmet")
        self.assertEqual(reference["knowledge_base_id"], "kb-001")
        self.assertEqual(reference["filename"], "安全帽zmd.pdf")
        self.assertEqual(reference["folder_path"], "安全防护用品")
        self.assertEqual(reference["file_size"], 8192)
        self.assertEqual(
            request.await_args_list[1].args,
            (connection, "/knowledge-bases/kb-001/knowledge"),
        )
        self.assertEqual(
            request.await_args_list[1].kwargs,
            {
                "params": {
                    "page": 1,
                    "page_size": 100,
                    "keyword": "安全帽zmd.pdf",
                },
            },
        )

    def test_weknora_inline_citation_parser_deduplicates_tags(self) -> None:
        answer = (
            "结论一"
            "<kb kb_id='kb-1' chunk_id='chunk-1' doc='目录/安全网.pdf'/>"
            "结论二"
            "<kb doc='目录/安全网.pdf' chunk_id='chunk-1' kb_id='kb-1' />"
        )
        self.assertEqual(
            _extract_weknora_inline_citations(answer),
            [
                {
                    "filename": "安全网.pdf",
                    "chunk_id": "chunk-1",
                    "knowledge_base_id": "kb-1",
                },
            ],
        )

    def test_weknora_tool_result_exposes_read_document_reference(self) -> None:
        tool_calls: dict[str, dict] = {}
        _weknora_tool_reference_items(
            {
                "response_type": "tool_call",
                "data": {
                    "tool_call_id": "call-1",
                    "tool_name": "list_knowledge_chunks",
                    "arguments": {
                        "knowledge_id": "knowledge-helmet",
                        "limit": 50,
                    },
                },
            },
            tool_calls,
        )

        references, citations = _weknora_tool_reference_items(
            {
                "response_type": "tool_result",
                "data": {
                    "tool_call_id": "call-1",
                    "tool_name": "list_knowledge_chunks",
                    "success": True,
                    "knowledge_id": "knowledge-helmet",
                    "knowledge_title": "安全帽zmd.pdf",
                    "fetched_chunks": 44,
                    "total_chunks": 44,
                },
            },
            tool_calls,
        )

        self.assertEqual(citations, [])
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0]["knowledge_id"], "knowledge-helmet")
        self.assertEqual(
            references[0]["knowledge_filename"],
            "安全帽zmd.pdf",
        )

    def test_weknora_wiki_summary_result_maps_to_source_document(self) -> None:
        references, citations = _weknora_tool_reference_items(
            {
                "response_type": "tool_result",
                "data": {
                    "tool_call_id": "call-wiki",
                    "tool_name": "wiki_search",
                    "success": True,
                    "found_kbs": {"summary/abc12345": ["kb-1"]},
                    "output": (
                        "<link>[[summary/abc12345|"
                        "安全帽zmd.pdf - Summary]]</link>"
                    ),
                },
            },
            {},
        )

        self.assertEqual(citations, [])
        self.assertEqual(
            references,
            [
                {
                    "knowledge_id": "abc12345",
                    "knowledge_base_id": "kb-1",
                    "knowledge_title": "安全帽zmd.pdf",
                    "knowledge_filename": "安全帽zmd.pdf",
                },
            ],
        )

    async def test_weknora_sse_keeps_title_after_final_answer_chunk(
        self,
    ) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )

        class FakeResponse:
            status_code = 200
            headers = {"content-type": "text/event-stream"}

            async def aiter_lines(self):
                for line in (
                    'data: {"id":"message-1","response_type":"answer",',
                    'data: "content":"完成","done":true}',
                    "",
                    'data: {"response_type":"session_title",'
                    '"content":"自动标题","done":true}',
                    "",
                ):
                    yield line

        class FakeStream:
            async def __aenter__(self):
                return FakeResponse()

            async def __aexit__(self, *args):
                del args
                return False

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                del args
                return False

            def stream(self, *args, **kwargs):
                del args, kwargs
                return FakeStream()

        with patch(
            "agentscope.app._router._agent.httpx.AsyncClient",
            return_value=FakeClient(),
        ):
            events = [
                event
                async for event in _stream_weknora_sse_events(
                    connection,
                    "/agent-chat/session-1",
                    {"query": "问题"},
                    session_id="session-1",
                )
            ]

        self.assertEqual(
            [event["response_type"] for event in events],
            ["answer", "session_title"],
        )
        self.assertEqual(events[1]["content"], "自动标题")

    async def test_weknora_sse_does_not_treat_early_title_as_terminal(
        self,
    ) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )

        class FakeResponse:
            status_code = 200
            headers = {"content-type": "text/event-stream"}

            async def aiter_lines(self):
                for line in (
                    'data: {"response_type":"session_title",'
                    '"content":"提前到达的标题","done":true}',
                    "",
                    'data: {"id":"message-1","response_type":"answer",'
                    '"content":"真正答案","done":true}',
                    "",
                ):
                    yield line

        class FakeStream:
            async def __aenter__(self):
                return FakeResponse()

            async def __aexit__(self, *args):
                del args
                return False

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                del args
                return False

            def stream(self, *args, **kwargs):
                del args, kwargs
                return FakeStream()

        with patch(
            "agentscope.app._router._agent.httpx.AsyncClient",
            return_value=FakeClient(),
        ):
            events = [
                event
                async for event in _stream_weknora_sse_events(
                    connection,
                    "/agent-chat/session-1",
                    {"query": "问题"},
                    session_id="session-1",
                )
            ]

        self.assertEqual(
            [event["response_type"] for event in events],
            ["session_title", "answer"],
        )
        self.assertEqual(events[1]["content"], "真正答案")

    async def test_weknora_resource_proxy_uses_documented_root_route(
        self,
    ) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )
        storage = SimpleNamespace(
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        weknora_connection=connection,
                    ),
                ),
            ),
            list_agents=AsyncMock(return_value=[]),
            upsert_agent=AsyncMock(return_value="agent"),
        )
        download = AsyncMock(
            return_value=(b"image", "image/png", "inline"),
        )

        with (
            patch(
                "agentscope.app._router._agent._weknora_agent_knowledge_base_ids",
                new=AsyncMock(return_value=["kb-001"]),
            ),
            patch(
                "agentscope.app._router._agent._request_weknora_bytes",
                new=download,
            ),
        ):
            response = await proxy_weknora_resource(
                resource_id="image_handle-1",
                weknora_agent_id="project-robot-001",
                user_id=USER_ID,
                storage=storage,
            )

        self.assertEqual(response.body, b"image")
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(
            download.await_args.args,
            (connection, "/files"),
        )
        self.assertEqual(
            download.await_args.kwargs,
            {
                "params": {"file_path": "resource://image_handle-1"},
                "root_path": True,
                "max_response_bytes": 32 * 1024 * 1024,
            },
        )

    async def test_weknora_stream_relays_incremental_events_and_complete(
        self,
    ) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )

        upstream_calls: list[tuple[tuple, dict]] = []

        async def upstream(*args, **kwargs):
            upstream_calls.append((args, kwargs))
            yield {
                "response_type": "agent_query",
                "content": "检索中",
                "done": False,
            }
            yield {
                "response_type": "answer",
                "content": "答案",
                "done": True,
            }
            yield {
                "response_type": "references",
                "knowledge_references": [
                    {"knowledge_id": "knowledge-1", "score": 0.88},
                ],
            }
            yield {
                "response_type": "session_title",
                "content": "回答标题",
                "done": True,
            }

        with (
            patch(
                "agentscope.app._router._agent._prepare_weknora_agent_query",
                new=AsyncMock(
                    return_value=(connection, "session-1", {"query": "问题"}),
                ),
            ),
            patch(
                "agentscope.app._router._agent._stream_weknora_sse_events",
                new=upstream,
            ),
            patch(
                "agentscope.app._router._agent._enrich_weknora_reference_items",
                new=AsyncMock(
                    return_value=[
                        {
                            "knowledge_id": "knowledge-1",
                            "filename": "方案.pdf",
                            "score": 0.88,
                        },
                    ],
                ),
            ),
        ):
            response = await stream_weknora_agent(
                body=AskWeKnoraAgentRequest(
                    query="问题",
                    weknora_agent_id="robot-1",
                ),
                user_id=USER_ID,
                storage=SimpleNamespace(),
            )
            chunks = [chunk async for chunk in response.body_iterator]

        body = "".join(
            chunk.decode() if isinstance(chunk, bytes) else chunk
            for chunk in chunks
        )
        self.assertIn('"response_type":"session"', body)
        self.assertIn('"response_type":"agent_query"', body)
        self.assertIn('"response_type":"references"', body)
        self.assertIn('"response_type":"session_title"', body)
        self.assertIn('"response_type":"complete"', body)
        self.assertLess(
            body.index('"response_type":"references"'),
            body.index('"response_type":"session_title"'),
        )
        self.assertEqual(
            upstream_calls[0][1]["params"],
            {"resource_urls": "public"},
        )

    async def test_weknora_stream_emits_references_for_inline_kb_tags(
        self,
    ) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )
        answer = (
            "安全网需满足耐冲击要求。"
            '<kb doc="安全网.pdf" chunk_id="chunk-net" kb_id="kb-1" />'
        )

        async def upstream(*args, **kwargs):
            del args, kwargs
            yield {
                "response_type": "answer",
                "content": answer,
                "done": True,
            }

        inline_enrichment = AsyncMock(
            return_value=[
                {
                    "chunk_id": "chunk-net",
                    "knowledge_id": "knowledge-net",
                    "knowledge_base_id": "kb-1",
                    "filename": "安全网.pdf",
                },
            ],
        )
        with (
            patch(
                "agentscope.app._router._agent._prepare_weknora_agent_query",
                new=AsyncMock(
                    return_value=(
                        connection,
                        "session-inline",
                        {"query": "问题", "knowledge_base_ids": ["kb-1"]},
                    ),
                ),
            ),
            patch(
                "agentscope.app._router._agent._stream_weknora_sse_events",
                new=upstream,
            ),
            patch(
                "agentscope.app._router._agent._enrich_weknora_inline_citations",
                new=inline_enrichment,
            ),
        ):
            response = await stream_weknora_agent(
                body=AskWeKnoraAgentRequest(
                    query="问题",
                    weknora_agent_id="robot-1",
                ),
                user_id=USER_ID,
                storage=SimpleNamespace(),
            )
            chunks = [chunk async for chunk in response.body_iterator]

        body = "".join(
            chunk.decode() if isinstance(chunk, bytes) else chunk
            for chunk in chunks
        )
        self.assertIn('"response_type":"answer"', body)
        self.assertIn('"response_type":"references"', body)
        self.assertIn('"filename":"安全网.pdf"', body)
        self.assertLess(
            body.index('"response_type":"answer"'),
            body.index('"response_type":"references"'),
        )
        inline_enrichment.assert_awaited_once_with(
            connection,
            answer,
            ["kb-1"],
            [],
        )

    async def test_weknora_stream_emits_references_from_tool_results(
        self,
    ) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            api_key="saved-secret",
        )

        async def upstream(*args, **kwargs):
            del args, kwargs
            yield {
                "response_type": "tool_call",
                "content": "Calling tool: list_knowledge_chunks",
                "data": {
                    "tool_call_id": "call-1",
                    "tool_name": "list_knowledge_chunks",
                    "arguments": {
                        "knowledge_id": "knowledge-helmet",
                    },
                },
            }
            yield {
                "response_type": "tool_result",
                "data": {
                    "tool_call_id": "call-1",
                    "tool_name": "list_knowledge_chunks",
                    "success": True,
                    "knowledge_id": "knowledge-helmet",
                    "knowledge_title": "安全帽zmd.pdf",
                },
            }
            yield {
                "response_type": "answer",
                "content": "普通型不超过430g。",
                "done": True,
            }

        enrichment = AsyncMock(
            return_value=[
                {
                    "knowledge_id": "knowledge-helmet",
                    "knowledge_base_id": "kb-1",
                    "filename": "安全帽zmd.pdf",
                    "preview_url": "/preview",
                },
            ],
        )
        with (
            patch(
                "agentscope.app._router._agent._prepare_weknora_agent_query",
                new=AsyncMock(
                    return_value=(
                        connection,
                        "session-tool-reference",
                        {"query": "问题", "knowledge_base_ids": ["kb-1"]},
                    ),
                ),
            ),
            patch(
                "agentscope.app._router._agent._stream_weknora_sse_events",
                new=upstream,
            ),
            patch(
                "agentscope.app._router._agent._enrich_weknora_reference_items",
                new=enrichment,
            ),
        ):
            response = await stream_weknora_agent(
                body=AskWeKnoraAgentRequest(
                    query="问题",
                    weknora_agent_id="robot-1",
                ),
                user_id=USER_ID,
                storage=SimpleNamespace(),
            )
            chunks = [chunk async for chunk in response.body_iterator]

        body = "".join(
            chunk.decode() if isinstance(chunk, bytes) else chunk
            for chunk in chunks
        )
        self.assertIn('"response_type":"references"', body)
        self.assertIn('"filename":"安全帽zmd.pdf"', body)
        enrichment.assert_awaited_once()
        raw_references = enrichment.await_args.args[1]
        self.assertEqual(len(raw_references), 1)
        self.assertEqual(
            raw_references[0]["knowledge_id"],
            "knowledge-helmet",
        )

    async def test_weknora_session_is_created_before_long_answer(self) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            agent_id="agent-001",
            api_key="saved-secret",
        )
        storage = SimpleNamespace(
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        weknora_connection=connection,
                    ),
                ),
            ),
            list_agents=AsyncMock(return_value=[]),
            upsert_agent=AsyncMock(return_value="agent"),
        )
        request = AsyncMock(
            return_value={"success": True, "data": {"id": "session-002"}},
        )
        with (
            patch(
                "agentscope.app._router._agent._request_weknora_json",
                new=request,
            ),
            patch(
                "agentscope.app._router._agent._weknora_agent_knowledge_base_ids",
                new=AsyncMock(return_value=["kb-001"]),
            ),
        ):
            response = await create_weknora_agent_session(
                body=CreateWeKnoraAgentSessionRequest(
                    weknora_agent_id="project-robot-001",
                ),
                user_id=USER_ID,
                storage=storage,
            )

        self.assertEqual(response.session_id, "session-002")
        self.assertEqual(request.await_args.args, (connection, "/sessions"))
        self.assertEqual(
            request.await_args.kwargs,
            {"method": "POST", "json_body": {"agent_id": "project-robot-001"}},
        )

    async def test_weknora_stop_resolves_active_assistant_message(self) -> None:
        connection = WeKnoraConnectionConfig(
            base_url="https://weknora.example.com",
            agent_id="agent-001",
            api_key="saved-secret",
        )
        storage = SimpleNamespace(
            get_platform_settings=AsyncMock(
                return_value=PlatformSettingsRecord(
                    user_id=USER_ID,
                    data=PlatformSettingsData(
                        weknora_connection=connection,
                    ),
                ),
            ),
            list_agents=AsyncMock(return_value=[]),
            upsert_agent=AsyncMock(return_value="agent"),
        )
        request = AsyncMock(
            side_effect=[
                {
                    "success": True,
                    "data": [
                        {
                            "id": "message-001",
                            "role": "assistant",
                            "is_completed": False,
                        },
                    ],
                },
                {"success": True, "message": "Generation stopped"},
            ],
        )
        with (
            patch(
                "agentscope.app._router._agent._request_weknora_json",
                new=request,
            ),
            patch(
                "agentscope.app._router._agent._weknora_agent_knowledge_base_ids",
                new=AsyncMock(return_value=["kb-001"]),
            ),
        ):
            response = await stop_weknora_agent_session(
                session_id="session-001",
                body=StopWeKnoraAgentSessionRequest(
                    weknora_agent_id="project-robot-001",
                ),
                user_id=USER_ID,
                storage=storage,
            )

        self.assertTrue(response.stopped)
        self.assertEqual(response.message_id, "message-001")
        self.assertEqual(
            request.await_args_list[0].args,
            (connection, "/messages/session-001/load"),
        )
        self.assertEqual(
            request.await_args_list[1].args,
            (connection, "/sessions/session-001/stop"),
        )
        self.assertEqual(
            request.await_args_list[1].kwargs["json_body"],
            {"message_id": "message-001"},
        )

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
                    weknora_connection=WeKnoraConnectionConfig(
                        base_url="https://weknora.example.com",
                        api_key="sqlite-secret",
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
        self.assertEqual(
            loaded.data.weknora_connection.api_key.get_secret_value(),
            "sqlite-secret",
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
