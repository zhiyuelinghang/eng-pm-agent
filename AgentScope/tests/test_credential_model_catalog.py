"""Regression tests for credential-scoped model catalogues."""

import json
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from agentscope.app._service._credential_models import (
    CredentialModelTestResult,
    ModelDiscoveryError,
    build_credential_embedding_model_catalog,
    build_credential_model_catalog,
    discover_credential_models,
    test_credential_embedding_model,
    test_credential_model,
)
from agentscope.app._service._embedding import build_embedding_model
from agentscope.app._service._model import get_model
from agentscope.app._router._credential import (
    test_model as test_model_endpoint,
    update_credential,
)
from agentscope.app._router._knowledge_base import list_kb_embedding_models
from agentscope.app._router._schema import (
    TestCredentialModelRequest,
    UpdateCredentialRequest,
)
from agentscope.app.storage import (
    ChatModelConfig,
    CredentialRecord,
    EmbeddingModelConfig,
)
from agentscope.app.storage._utils import _dump_with_secrets
from agentscope.app._service import CredentialView
from agentscope.app.rag.knowledge_base_manager import (
    DimensionPolicy,
    DimensionPolicyKind,
)
from agentscope.credential import (
    CredentialFactory,
    CredentialModelDefinition,
    CustomOpenAICredential,
)
from agentscope.embedding import OpenAIEmbeddingModel
from agentscope.model import ChatResponse, OpenAIChatModel
from agentscope.types import ErrorType


def _credential() -> CustomOpenAICredential:
    return CustomOpenAICredential(
        name="Compatible endpoint",
        api_key="secret",
        base_url="https://example.com/v1",
    )


class CredentialModelCatalogTest(TestCase):
    """Validate factory/schema compatibility and catalogue merging."""

    def test_custom_openai_schema_is_registered_without_internal_catalog(self):
        schemas = CredentialFactory.list_schemas()
        schema = next(
            item
            for item in schemas
            if item["properties"]["type"]["const"]
            == "custom_openai_credential"
        )
        self.assertEqual(schema["title"], "自定义（OpenAI 兼容）")
        self.assertNotIn("model_catalog", schema["properties"])

    def test_custom_provider_has_no_openai_default_models(self):
        self.assertEqual(_credential().list_models(), [])
        self.assertEqual(_credential().list_embedding_models(), [])
        self.assertIs(
            _credential().get_embedding_model_class(),
            OpenAIEmbeddingModel,
        )

    def test_manual_models_override_discovery_and_hidden_state_is_applied(self):
        credential = _credential()
        credential.model_catalog.discovered_models = [
            CredentialModelDefinition(
                name="qwen/qwen3-max",
                context_size=64_000,
                output_size=4_096,
            ),
            CredentialModelDefinition(name="discovered-only"),
        ]
        credential.model_catalog.manual_models = [
            CredentialModelDefinition(
                name="qwen/qwen3-max",
                label="Qwen 3 Max",
                context_size=128_000,
                output_size=8_192,
            ),
        ]
        credential.model_catalog.hidden_model_ids = ["discovered-only"]

        models = {
            item.name: item
            for item in build_credential_model_catalog(credential)
        }

        self.assertEqual(models["qwen/qwen3-max"].source, "manual")
        self.assertEqual(
            models["qwen/qwen3-max"].context_size,
            128_000,
        )
        self.assertTrue(models["qwen/qwen3-max"].enabled)
        self.assertFalse(models["discovered-only"].enabled)

    def test_manual_embedding_model_is_separate_from_chat_catalog(self):
        credential = _credential()
        credential.model_catalog.discovered_models = [
            CredentialModelDefinition(name="embedding-model"),
        ]
        credential.model_catalog.manual_models = [
            CredentialModelDefinition(
                model_type="chat",
                name="chat-model",
            ),
            CredentialModelDefinition(
                model_type="embedding",
                name="embedding-model",
                dimensions=1024,
            ),
        ]

        chat_models = build_credential_model_catalog(credential)
        embedding_models = build_credential_embedding_model_catalog(
            credential,
        )

        self.assertEqual([item.name for item in chat_models], ["chat-model"])
        self.assertEqual(
            [item.name for item in embedding_models],
            ["embedding-model"],
        )
        self.assertEqual(embedding_models[0].dimensions, 1024)

    def test_custom_embedding_runtime_does_not_force_dimensions_parameter(self):
        credential = _credential()
        credential.model_catalog.manual_models = [
            CredentialModelDefinition(
                model_type="embedding",
                name="text-embedding-custom",
                dimensions=768,
            ),
        ]
        record = CredentialRecord(
            id=credential.id,
            user_id="owner",
            data=_dump_with_secrets(credential),
        )

        model = build_embedding_model(
            record,
            EmbeddingModelConfig(
                type="custom_openai_credential",
                credential_id=credential.id,
                model="text-embedding-custom",
                dimensions=768,
                parameters={},
            ),
        )

        self.assertEqual(model.dimensions, 768)
        self.assertFalse(model.pass_dimensions)


class CredentialModelDiscoveryTest(IsolatedAsyncioTestCase):
    """Validate OpenAI-compatible discovery and its manual fallback."""

    @staticmethod
    def _client_context(response: object) -> MagicMock:
        client = AsyncMock()
        client.get.return_value = response
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=None)
        return context

    async def test_discovers_standard_openai_model_response(self):
        response = SimpleNamespace(
            status_code=200,
            content=json.dumps(
                {
                    "object": "list",
                    "data": [
                        {"id": "qwen/qwen3-max"},
                        {"id": "deepseek-v3.2"},
                    ],
                },
            ).encode(),
        )
        context = self._client_context(response)

        with patch(
            "agentscope.app._service._credential_models.httpx.AsyncClient",
            return_value=context,
        ):
            models = await discover_credential_models(_credential())

        self.assertEqual(
            [model.name for model in models],
            ["deepseek-v3.2", "qwen/qwen3-max"],
        )

    async def test_missing_models_endpoint_explains_manual_fallback(self):
        response = SimpleNamespace(status_code=404, content=b"not found")
        context = self._client_context(response)

        with patch(
            "agentscope.app._service._credential_models.httpx.AsyncClient",
            return_value=context,
        ):
            with self.assertRaisesRegex(
                ModelDiscoveryError,
                "手动添加模型",
            ):
                await discover_credential_models(_credential())

    async def test_custom_model_builds_with_the_openai_chat_adapter(self):
        credential = _credential()
        access = SimpleNamespace(
            resolve_credential=AsyncMock(
                return_value=SimpleNamespace(
                    data={
                        **credential.model_dump(mode="json"),
                        "api_key": "secret",
                    },
                ),
            ),
        )

        model = await get_model(
            user_id="model-test",
            config=ChatModelConfig(
                type="custom_openai_credential",
                credential_id=credential.id,
                model="qwen/qwen3-max",
                parameters={},
            ),
            access=access,
        )

        self.assertEqual(model.model, "qwen/qwen3-max")
        self.assertEqual(model.credential.base_url, "https://example.com/v1")

    async def test_model_test_runs_one_real_adapter_call(self):
        call = AsyncMock(
            return_value=ChatResponse(content=[], is_last=True),
        )
        with patch.object(OpenAIChatModel, "_call_api", call):
            result = await test_credential_model(
                _credential(),
                "qwen/qwen3-max",
            )

        self.assertTrue(result.success)
        self.assertEqual(result.model, "qwen/qwen3-max")
        self.assertGreaterEqual(result.latency_ms, 1)
        self.assertEqual(call.await_count, 1)

    async def test_model_test_returns_sanitised_authentication_failure(self):
        class ProviderAuthenticationError(Exception):
            status_code = 401

        with patch.object(
            OpenAIChatModel,
            "_call_api",
            AsyncMock(side_effect=ProviderAuthenticationError("bad key")),
        ):
            result = await test_credential_model(
                _credential(),
                "qwen/qwen3-max",
            )

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, ErrorType.AUTHENTICATION)
        self.assertNotIn("bad key", result.message)

    async def test_model_test_exposes_redacted_provider_response(self):
        class ProviderInvalidRequestError(Exception):
            status_code = 400

            def __init__(self) -> None:
                super().__init__("invalid request")
                self.response = SimpleNamespace(
                    status_code=400,
                    content=json.dumps(
                        {
                            "error": {
                                "message": "Unsupported input format.",
                                "echoed_api_key": "secret",
                            },
                        },
                    ).encode(),
                )

        with patch.object(
            OpenAIChatModel,
            "_call_api",
            AsyncMock(side_effect=ProviderInvalidRequestError()),
        ):
            result = await test_credential_model(
                _credential(),
                "qwen/qwen3-max",
            )

        self.assertFalse(result.success)
        self.assertEqual(result.status_code, 400)
        self.assertIn("Unsupported input format.", result.raw_response)
        self.assertNotIn('"secret"', result.raw_response)
        self.assertIn("[REDACTED]", result.raw_response)

    async def test_embedding_probe_detects_vector_dimensions(self):
        response = SimpleNamespace(
            status_code=200,
            content=json.dumps(
                {
                    "data": [
                        {
                            "index": 0,
                            "embedding": [0.1, 0.2, 0.3, 0.4],
                        },
                    ],
                },
            ).encode(),
        )
        client = AsyncMock()
        client.post.return_value = response
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "agentscope.app._service._credential_models.httpx.AsyncClient",
            return_value=context,
        ):
            result = await test_credential_embedding_model(
                _credential(),
                "text-embedding-custom",
            )

        self.assertTrue(result.success)
        self.assertEqual(result.model_type, "embedding")
        self.assertEqual(result.dimensions, 4)
        self.assertEqual(client.post.await_count, 1)

    async def test_embedding_probe_exposes_provider_error_body(self):
        response = SimpleNamespace(
            status_code=400,
            content=b'{"error":{"message":"model is not an embedding model"}}',
        )
        client = AsyncMock()
        client.post.return_value = response
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "agentscope.app._service._credential_models.httpx.AsyncClient",
            return_value=context,
        ):
            result = await test_credential_embedding_model(
                _credential(),
                "chat-only-model",
            )

        self.assertFalse(result.success)
        self.assertEqual(result.status_code, 400)
        self.assertIn("not an embedding model", result.raw_response)

    async def test_manual_embedding_appears_in_knowledge_base_picker(self):
        credential = _credential()
        credential.model_catalog.manual_models = [
            CredentialModelDefinition(
                model_type="embedding",
                name="text-embedding-custom",
                dimensions=768,
            ),
        ]
        record = CredentialRecord(
            id=credential.id,
            user_id="owner",
            data=_dump_with_secrets(credential),
        )
        view = CredentialView.model_validate(
            {
                **record.model_dump(),
                "editable": True,
            },
        )
        access = SimpleNamespace(
            list_resource=AsyncMock(return_value=[view]),
            resolve_credential=AsyncMock(return_value=record),
        )
        manager = SimpleNamespace(
            get_dimension_policy=AsyncMock(
                return_value=DimensionPolicy(
                    kind=DimensionPolicyKind.ANY,
                ),
            ),
        )

        result = await list_kb_embedding_models(
            user_id="owner",
            access=access,
            manager=manager,
        )

        self.assertEqual(len(result.providers), 1)
        self.assertEqual(
            result.providers[0].models[0].name,
            "text-embedding-custom",
        )
        self.assertEqual(result.providers[0].models[0].dimensions, 768)

    async def test_model_test_endpoint_accepts_an_enabled_catalog_model(self):
        credential = _credential()
        credential.model_catalog.manual_models = [
            CredentialModelDefinition(name="qwen/qwen3-max"),
        ]
        access = SimpleNamespace(
            resolve_credential=AsyncMock(
                return_value=SimpleNamespace(
                    data=_dump_with_secrets(credential),
                ),
            ),
        )
        expected = CredentialModelTestResult(
            success=True,
            model="qwen/qwen3-max",
            latency_ms=12,
            message="ok",
        )

        with patch(
            "agentscope.app._router._credential.test_credential_model",
            AsyncMock(return_value=expected),
        ):
            result = await test_model_endpoint(
                credential_id=credential.id,
                body=TestCredentialModelRequest(model="qwen/qwen3-max"),
                user_id="owner",
                access=access,
            )

        self.assertEqual(result, expected)

    async def test_editing_credential_preserves_hidden_catalog_data(self):
        credential = _credential()
        credential.model_catalog.manual_models = [
            CredentialModelDefinition(name="qwen/qwen3-max"),
        ]
        record = CredentialRecord(
            id=credential.id,
            user_id="owner",
            data=_dump_with_secrets(credential),
        )
        saved: list[CustomOpenAICredential] = []

        async def _upsert(_owner: str, value: CustomOpenAICredential) -> str:
            saved.append(value)
            return value.id

        async def _get(_owner: str, _credential_id: str) -> CredentialRecord:
            return CredentialRecord(
                id=credential.id,
                user_id="owner",
                data=_dump_with_secrets(saved[-1]),
            )

        storage = SimpleNamespace(
            upsert_credential=AsyncMock(side_effect=_upsert),
            get_credential=AsyncMock(side_effect=_get),
        )
        access = SimpleNamespace(
            resolve_for_edit=AsyncMock(return_value=("owner", record)),
        )

        await update_credential(
            credential_id=credential.id,
            body=UpdateCredentialRequest(
                data={
                    "type": "custom_openai_credential",
                    "name": "Renamed",
                    "api_key": "secret",
                    "base_url": "https://example.com/v1",
                },
            ),
            user_id="owner",
            storage=storage,
            access=access,
        )

        self.assertEqual(
            saved[0].model_catalog.manual_models[0].name,
            "qwen/qwen3-max",
        )
