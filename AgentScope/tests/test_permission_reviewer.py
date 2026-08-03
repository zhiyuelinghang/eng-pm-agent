"""Regression tests for the built-in permission reviewer."""

from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

from agentscope.agent import Agent
from agentscope.app import create_app
from agentscope.app._auth import AgentScopePrincipal
from agentscope.app._router._schema import UpdateSessionRequest
from agentscope.app._router._session import update_session
from agentscope.app.message_bus import InMemoryMessageBus
from agentscope.app._service._permission_review import (
    ModelPermissionReviewer,
    PermissionReviewerMiddleware,
)
from agentscope.app.storage import (
    AsyncSQLAlchemyStorage,
    PermissionReviewAuditRecord,
    PermissionReviewerConfigData,
    SessionConfig,
    SessionRecord,
)
from agentscope.app.workspace_manager import LocalWorkspaceManager
from agentscope.event import RequireUserConfirmEvent, ToolResultEndEvent
from agentscope.message import (
    AssistantMsg,
    TextBlock,
    ToolCallBlock,
    UserMsg,
)
from agentscope.permission import (
    PermissionBehavior,
    PermissionContext,
    PermissionDecision,
    PermissionMode,
    PermissionReviewAction,
    PermissionReviewRequest,
    PermissionReviewResult,
    PermissionReviewRisk,
    PermissionReviewerBase,
)
from agentscope.state import AgentState
from agentscope.tool import ToolBase, ToolChunk, Toolkit
from fastapi import HTTPException
from fastapi.testclient import TestClient


class _AskTool(ToolBase):
    name = "TestWrite"
    description = "Write a harmless test value."
    input_schema = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }
    is_concurrency_safe = True
    is_read_only = False
    is_external_tool = False
    is_mcp = False

    def __init__(self, *, bypass_immune: bool = False) -> None:
        super().__init__()
        self._bypass_immune = bypass_immune

    async def check_permissions(
        self,
        tool_input: dict,
        context: PermissionContext,
    ) -> PermissionDecision:
        return PermissionDecision(
            behavior=PermissionBehavior.ASK,
            message="confirmation required",
            bypass_immune=self._bypass_immune,
        )

    async def call(self, value: str) -> ToolChunk:
        return ToolChunk(content=[TextBlock(text=value)])


class _FixedReviewer(PermissionReviewerBase):
    def __init__(self, action: PermissionReviewAction) -> None:
        self.action = action
        self.requests: list[PermissionReviewRequest] = []

    async def review(
        self,
        request: PermissionReviewRequest,
    ) -> PermissionReviewResult:
        self.requests.append(request)
        return PermissionReviewResult(
            action=self.action,
            risk=PermissionReviewRisk.LOW,
            confidence=1,
            reason="test decision",
        )


class AgentPermissionReviewerIntegrationTest(IsolatedAsyncioTestCase):
    """Exercise the real Agent permission-to-execution transition."""

    async def _execute(
        self,
        action: PermissionReviewAction,
        *,
        bypass_immune: bool = False,
        mode: PermissionMode = PermissionMode.AUTO,
    ) -> tuple[list, _FixedReviewer]:
        reviewer = _FixedReviewer(action)
        tool = _AskTool(bypass_immune=bypass_immune)
        tool_call = ToolCallBlock(
            id="tool-call",
            name=tool.name,
            input='{"value":"ok"}',
        )
        state = AgentState(
            context=[
                UserMsg(name="user", content="Please write the test value."),
                AssistantMsg(name="worker", content=[tool_call]),
            ],
            permission_context=PermissionContext(mode=mode),
        )
        model = SimpleNamespace(
            count_tokens=AsyncMock(return_value=1),
        )
        agent = Agent(
            name="worker",
            system_prompt="test",
            model=model,
            toolkit=Toolkit(tools=[tool]),
            state=state,
            middlewares=[PermissionReviewerMiddleware(reviewer)],
        )
        events = [
            event async for event in agent._execute_tool_call(tool_call)
        ]
        return events, reviewer

    async def test_allow_once_executes_without_human_prompt(self) -> None:
        events, reviewer = await self._execute(
            PermissionReviewAction.ALLOW_ONCE,
        )
        self.assertEqual(len(reviewer.requests), 1)
        self.assertEqual(
            reviewer.requests[0].user_intent,
            "Please write the test value.",
        )
        self.assertFalse(
            any(isinstance(event, RequireUserConfirmEvent) for event in events),
        )
        self.assertTrue(
            any(isinstance(event, ToolResultEndEvent) for event in events),
        )

    async def test_human_required_keeps_original_prompt(self) -> None:
        events, _ = await self._execute(
            PermissionReviewAction.HUMAN_REQUIRED,
        )
        self.assertTrue(
            any(isinstance(event, RequireUserConfirmEvent) for event in events),
        )

    async def test_default_mode_never_reaches_reviewer(self) -> None:
        events, reviewer = await self._execute(
            PermissionReviewAction.ALLOW_ONCE,
            mode=PermissionMode.DEFAULT,
        )
        self.assertEqual(reviewer.requests, [])
        self.assertTrue(
            any(isinstance(event, RequireUserConfirmEvent) for event in events),
        )

    async def test_bypass_immune_never_reaches_reviewer(self) -> None:
        events, reviewer = await self._execute(
            PermissionReviewAction.ALLOW_ONCE,
            bypass_immune=True,
        )
        self.assertEqual(reviewer.requests, [])
        self.assertTrue(
            any(isinstance(event, RequireUserConfirmEvent) for event in events),
        )


class AutoPermissionModeRouterTest(IsolatedAsyncioTestCase):
    """Ensure Auto cannot be selected without an enabled reviewer."""

    @staticmethod
    def _access() -> SimpleNamespace:
        return SimpleNamespace(
            resolve_agent=AsyncMock(
                return_value=SimpleNamespace(
                    data=SimpleNamespace(
                        model_policy=SimpleNamespace(
                            mode="inherit_session",
                        ),
                    ),
                ),
            ),
        )

    async def test_auto_mode_rejected_when_reviewer_is_disabled(self) -> None:
        session = SessionRecord(
            user_id="user",
            agent_id="agent",
            config=SessionConfig(workspace_id="workspace"),
        )
        storage = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            upsert_session=AsyncMock(),
        )
        reviewer_service = SimpleNamespace(
            get_config=AsyncMock(
                return_value=SimpleNamespace(
                    data=PermissionReviewerConfigData(enabled=False),
                ),
            ),
        )

        with self.assertRaises(HTTPException) as raised:
            await update_session(
                session_id=session.id,
                body=UpdateSessionRequest(
                    permission_mode=PermissionMode.AUTO,
                ),
                agent_id=session.agent_id,
                user_id=session.user_id,
                storage=storage,
                access=self._access(),
                permission_review_service=reviewer_service,
                principal=AgentScopePrincipal(
                    kind="management",
                    subject=session.user_id,
                ),
            )

        self.assertEqual(raised.exception.status_code, 422)
        storage.upsert_session.assert_not_awaited()

    async def test_auto_mode_is_persisted_when_reviewer_is_enabled(
        self,
    ) -> None:
        session = SessionRecord(
            user_id="user",
            agent_id="agent",
            config=SessionConfig(workspace_id="workspace"),
        )
        storage = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            upsert_session=AsyncMock(return_value=session),
        )
        reviewer_service = SimpleNamespace(
            get_config=AsyncMock(
                return_value=SimpleNamespace(
                    data=PermissionReviewerConfigData(
                        enabled=True,
                        credential_id="credential",
                        model="reviewer-model",
                    ),
                ),
            ),
        )

        await update_session(
            session_id=session.id,
            body=UpdateSessionRequest(
                permission_mode=PermissionMode.AUTO,
            ),
            agent_id=session.agent_id,
            user_id=session.user_id,
            storage=storage,
            access=self._access(),
            permission_review_service=reviewer_service,
            principal=AgentScopePrincipal(
                kind="management",
                subject=session.user_id,
            ),
        )

        persisted_state = storage.upsert_session.await_args.kwargs["state"]
        self.assertEqual(
            persisted_state.permission_context.mode,
            PermissionMode.AUTO,
        )


class ModelPermissionReviewerTest(IsolatedAsyncioTestCase):
    """Validate hard rules and model-output policy gates."""

    @staticmethod
    def _request(**updates) -> PermissionReviewRequest:
        data = {
            "agent_name": "worker",
            "tool_name": "PowerShell",
            "tool_description": "Execute PowerShell",
            "tool_input": {"command": "Get-ChildItem ."},
            "user_intent": "List files",
            "permission_mode": "default",
        }
        data.update(updates)
        return PermissionReviewRequest(**data)

    async def test_low_risk_confident_decision_is_allowed(self) -> None:
        model = SimpleNamespace(
            generate_structured_output=AsyncMock(
                return_value=SimpleNamespace(
                    content={
                        "action": "allow_once",
                        "risk": "low",
                        "confidence": 0.96,
                        "reason": "只读且符合用户意图。",
                    },
                ),
            ),
        )
        reviewer = ModelPermissionReviewer(
            models=[("review-model", model)],
            config=PermissionReviewerConfigData(
                enabled=True,
                credential_id="credential",
                model="review-model",
            ),
        )
        result = await reviewer.review(self._request())
        self.assertEqual(result.action, PermissionReviewAction.ALLOW_ONCE)
        self.assertEqual(result.model, "review-model")

    async def test_confidence_gate_escalates_to_human(self) -> None:
        model = SimpleNamespace(
            generate_structured_output=AsyncMock(
                return_value=SimpleNamespace(
                    content={
                        "action": "allow_once",
                        "risk": "low",
                        "confidence": 0.7,
                        "reason": "可能安全。",
                    },
                ),
            ),
        )
        reviewer = ModelPermissionReviewer(
            models=[("review-model", model)],
            config=PermissionReviewerConfigData(
                enabled=True,
                credential_id="credential",
                model="review-model",
                confidence_threshold=0.9,
            ),
        )
        result = await reviewer.review(self._request())
        self.assertEqual(
            result.action,
            PermissionReviewAction.HUMAN_REQUIRED,
        )
        self.assertEqual(result.source, "confidence_gate")

    async def test_destructive_command_is_human_only_without_model_call(
        self,
    ) -> None:
        model = SimpleNamespace(
            generate_structured_output=AsyncMock(),
        )
        reviewer = ModelPermissionReviewer(
            models=[("review-model", model)],
            config=PermissionReviewerConfigData(
                enabled=True,
                credential_id="credential",
                model="review-model",
            ),
        )
        result = await reviewer.review(
            self._request(
                tool_input={"command": "Remove-Item -Recurse important"},
            ),
        )
        self.assertEqual(
            result.action,
            PermissionReviewAction.HUMAN_REQUIRED,
        )
        self.assertEqual(result.source, "hard_rule")
        model.generate_structured_output.assert_not_awaited()

    async def test_explicit_ask_rule_is_never_auto_approved(self) -> None:
        model = SimpleNamespace(
            generate_structured_output=AsyncMock(),
        )
        reviewer = ModelPermissionReviewer(
            models=[("review-model", model)],
            config=PermissionReviewerConfigData(
                enabled=True,
                credential_id="credential",
                model="review-model",
            ),
        )
        result = await reviewer.review(
            self._request(permission_reason="Rule: always confirm"),
        )
        self.assertEqual(
            result.action,
            PermissionReviewAction.HUMAN_REQUIRED,
        )
        self.assertEqual(result.source, "hard_rule")
        model.generate_structured_output.assert_not_awaited()

    async def test_fallback_model_is_used_when_primary_fails(self) -> None:
        primary = SimpleNamespace(
            generate_structured_output=AsyncMock(
                side_effect=RuntimeError("primary unavailable"),
            ),
        )
        fallback = SimpleNamespace(
            generate_structured_output=AsyncMock(
                return_value=SimpleNamespace(
                    content={
                        "action": "allow_once",
                        "risk": "low",
                        "confidence": 0.98,
                        "reason": "备用模型判断为安全。",
                    },
                ),
            ),
        )
        reviewer = ModelPermissionReviewer(
            models=[
                ("primary-model", primary),
                ("fallback-model", fallback),
            ],
            config=PermissionReviewerConfigData(
                enabled=True,
                credential_id="credential",
                model="primary-model",
                fallback_credential_id="fallback-credential",
                fallback_model="fallback-model",
            ),
        )
        result = await reviewer.review(self._request())
        self.assertEqual(result.action, PermissionReviewAction.ALLOW_ONCE)
        self.assertEqual(result.model, "fallback-model")
        self.assertEqual(result.source, "fallback_model")

    async def test_credential_fields_are_human_only(self) -> None:
        model = SimpleNamespace(
            generate_structured_output=AsyncMock(),
        )
        reviewer = ModelPermissionReviewer(
            models=[("review-model", model)],
            config=PermissionReviewerConfigData(
                enabled=True,
                credential_id="credential",
                model="review-model",
            ),
        )
        result = await reviewer.review(
            self._request(tool_input={"api_key": "should-not-leave"}),
        )
        self.assertEqual(
            result.action,
            PermissionReviewAction.HUMAN_REQUIRED,
        )
        model.generate_structured_output.assert_not_awaited()

    async def test_user_intent_secrets_are_redacted_before_model(self) -> None:
        model = SimpleNamespace(
            generate_structured_output=AsyncMock(
                return_value=SimpleNamespace(
                    content={
                        "action": "human_required",
                        "risk": "high",
                        "confidence": 1,
                        "reason": "测试完成。",
                    },
                ),
            ),
        )
        reviewer = ModelPermissionReviewer(
            models=[("review-model", model)],
            config=PermissionReviewerConfigData(
                enabled=True,
                credential_id="credential",
                model="review-model",
            ),
        )
        await reviewer.review(
            self._request(
                user_intent="请使用 api_key=sk-do-not-send 执行测试。",
            ),
        )
        messages = model.generate_structured_output.await_args.args[0]
        payload = messages[1].get_text_content()
        self.assertIn("[REDACTED]", payload)
        self.assertNotIn("sk-do-not-send", payload)


class PermissionReviewerSQLStorageTest(IsolatedAsyncioTestCase):
    """Ensure the new records round-trip through the SQLite backend."""

    async def test_config_and_audit_round_trip(self) -> None:
        storage = AsyncSQLAlchemyStorage(
            "sqlite+aiosqlite:///:memory:",
            create_tables=True,
        )
        async with storage:
            config = PermissionReviewerConfigData(
                enabled=True,
                credential_id="credential",
                model="review-model",
            )
            saved = await storage.upsert_permission_reviewer_config(
                "user",
                config,
            )
            loaded = await storage.get_permission_reviewer_config("user")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.id, saved.id)
            self.assertEqual(loaded.data.model, "review-model")

            await storage.append_permission_review_audit(
                PermissionReviewAuditRecord(
                    user_id="user",
                    agent_id="agent",
                    session_id="session",
                    tool_name="PowerShell",
                    action="allow_once",
                    risk="low",
                    confidence=0.99,
                    reason="safe",
                    source="model",
                    model="review-model",
                ),
            )
            audits = await storage.list_permission_review_audits("user")
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0].tool_name, "PowerShell")

    async def test_alembic_upgrade_creates_reviewer_tables(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "reviewer.db"
            storage = AsyncSQLAlchemyStorage(
                f"sqlite+aiosqlite:///{db_path.as_posix()}",
                create_tables=False,
                auto_migrate=True,
            )
            async with storage:
                saved = await storage.upsert_permission_reviewer_config(
                    "user",
                    PermissionReviewerConfigData(),
                )
                self.assertEqual(saved.user_id, "user")


class PermissionReviewerRouterTest(TestCase):
    """Smoke-test the real FastAPI routes and lifespan wiring."""

    def test_get_and_update_disabled_config(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "router.db"
            storage = AsyncSQLAlchemyStorage(
                f"sqlite+aiosqlite:///{db_path.as_posix()}",
                create_tables=True,
            )
            app = create_app(
                storage=storage,
                message_bus=InMemoryMessageBus(),
                workspace_manager=LocalWorkspaceManager(
                    basedir=str(Path(temp_dir) / "workspaces"),
                ),
            )
            headers = {"X-User-ID": "router-test"}
            with TestClient(app) as client:
                initial = client.get(
                    "/credential/system/permission-reviewer",
                    headers=headers,
                )
                self.assertEqual(initial.status_code, 200)
                self.assertFalse(initial.json()["config"]["enabled"])

                updated = client.put(
                    "/credential/system/permission-reviewer",
                    headers=headers,
                    json={
                        "enabled": False,
                        "credential_id": None,
                        "model": None,
                        "parameters": {},
                        "fallback_credential_id": None,
                        "fallback_model": None,
                        "fallback_parameters": {},
                        "confidence_threshold": 0.9,
                        "max_auto_risk": "low",
                        "timeout_seconds": 20,
                    },
                )
                self.assertEqual(updated.status_code, 200)
                self.assertEqual(
                    updated.json()["config"]["confidence_threshold"],
                    0.9,
                )
