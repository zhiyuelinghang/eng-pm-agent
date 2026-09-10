"""Unknown output metadata must not impose a fabricated API output limit."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentscope.app._service._credential_models import (
    build_credential_model_catalog,
    discover_credential_models,
    test_credential_model as check_model,
)
from agentscope.app._service._model import get_model
from agentscope.app.middleware._managed_model_middleware import ManagedModelMiddleware
from agentscope.app.storage import ChatModelConfig
from agentscope.app.storage._utils import _dump_with_secrets
from agentscope.credential import (
    AnthropicCredential,
    CredentialModelDefinition,
    CustomOpenAICredential,
)
from agentscope.message import UserMsg
from agentscope.model import AnthropicChatModel, ChatResponse


def custom_credential(output_size=None, parameters=None):
    credential = CustomOpenAICredential(
        api_key="fictional-output-limit-test-key",
        base_url="https://example.invalid/v1",
    )
    credential.model_catalog.manual_models = [
        CredentialModelDefinition(name="unverified-model", output_size=output_size),
    ]
    if parameters:
        credential.model_catalog.model_default_parameters = {
            "unverified-model": parameters,
        }
    return credential


async def runtime_model(credential, name="unverified-model"):
    access = SimpleNamespace(resolve_credential=AsyncMock(
        return_value=SimpleNamespace(data=_dump_with_secrets(credential)),
    ))
    return await get_model(
        "test-owner",
        ChatModelConfig(type=credential.type, credential_id=credential.id, model=name, parameters={}),
        access,
    )


def test_unknown_manual_output_metadata_stays_null_in_api_schema():
    definition = CredentialModelDefinition(name="unverified-model")
    assert definition.output_size is None
    assert definition.context_size == 128_000
    card = build_credential_model_catalog(custom_credential())[0]
    assert card.model_dump(mode="json")["output_size"] is None
    assert "maximum" not in card.parameter_schema["properties"]["max_tokens"]


def test_confirmed_output_metadata_still_constrains_parameter_schema():
    card = build_credential_model_catalog(custom_credential(96_000))[0]
    assert card.output_size == 96_000
    assert card.parameter_schema["properties"]["max_tokens"]["maximum"] == 96_000


@pytest.mark.asyncio
async def test_models_discovery_does_not_invent_output_capability():
    client = MagicMock()
    client.get = AsyncMock(return_value=SimpleNamespace(
        status_code=200,
        content=b'{"data":[{"id":"unverified-model"}]}',
    ))
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    with patch("agentscope.app._service._credential_models.httpx.AsyncClient", return_value=context):
        models = await discover_credential_models(custom_credential())
    assert len(models) == 1
    assert models[0].output_size is None


@pytest.mark.asyncio
@pytest.mark.parametrize("known,explicit,expected", [
    (None, None, None),
    (None, 70_000, 70_000),
    (90_000, None, 90_000),
    (90_000, 70_000, 70_000),
    (90_000, 100_000, 90_000),
])
async def test_custom_runtime_request_uses_only_known_or_explicit_limits(known, explicit, expected):
    parameters = {"max_tokens": explicit} if explicit is not None else {}
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("captured request"))
    with patch("openai.AsyncClient", return_value=client):
        model = await runtime_model(custom_credential(known, parameters))
    model.stream = False
    model.count_tokens = AsyncMock(return_value=1000)
    assert model.context_size == 128_000
    assert model.parameters.max_tokens == expected
    messages = [UserMsg(name="test", content="test")]

    async def send(**_kwargs):
        return await model._call_api(model.model, messages)

    with pytest.raises(RuntimeError, match="captured request"):
        await ManagedModelMiddleware().on_model_call(None, {
            "current_model": model, "messages": messages, "tools": [],
        }, send)
    request = client.chat.completions.create.await_args.kwargs
    if expected is None:
        assert "max_tokens" not in request
        assert "max_completion_tokens" not in request
        assert getattr(model, "_managed_output_limit", None) is None
        model.count_tokens.assert_not_awaited()
    else:
        assert request["max_tokens"] == expected


@pytest.mark.asyncio
async def test_custom_request_body_limit_and_thinking_fields_are_preserved():
    body = {"max_completion_tokens": 64_000, "enable_thinking": True}
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("captured request"))
    with patch("openai.AsyncClient", return_value=client):
        model = await runtime_model(custom_credential(parameters={"__request_body__": body}))
    model.stream = False
    with pytest.raises(RuntimeError, match="captured request"):
        await model._call_api(model.model, [UserMsg(name="test", content="test")])
    request = client.chat.completions.create.await_args.kwargs
    assert request["extra_body"] == body
    assert "max_tokens" not in request
    assert "max_completion_tokens" not in request


@pytest.mark.asyncio
async def test_known_anthropic_runtime_uses_confirmed_catalogue_limit():
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=RuntimeError("captured request"))
    credential = AnthropicCredential(api_key="fictional-output-limit-test-key")
    name = "claude-sonnet-4-6"
    limit = next(card.output_size for card in build_credential_model_catalog(credential) if card.name == name)
    with patch("anthropic.AsyncAnthropic", return_value=client):
        model = await runtime_model(credential, name)
    model.stream = False
    with pytest.raises(RuntimeError, match="captured request"):
        await model._call_api(name, [UserMsg(name="test", content="test")])
    assert client.messages.create.await_args.kwargs["max_tokens"] == limit


@pytest.mark.asyncio
async def test_known_anthropic_model_test_uses_same_catalogue_limit():
    credential = AnthropicCredential(api_key="fictional-output-limit-test-key")
    name = "claude-sonnet-4-6"
    limit = next(card.output_size for card in build_credential_model_catalog(credential) if card.name == name)
    seen = []

    async def call(model, *_args, **_kwargs):
        seen.append(model.parameters.max_tokens)
        return ChatResponse(content=[], is_last=True)

    with patch("anthropic.AsyncAnthropic"), patch.object(AnthropicChatModel, "_call_api", call):
        result = await check_model(credential, name)
    assert result.success
    assert seen == [limit]


@pytest.mark.asyncio
async def test_unknown_anthropic_requires_explicit_output_limit_before_network_call():
    client = MagicMock()
    client.messages.create = AsyncMock()
    credential = AnthropicCredential(api_key="fictional-output-limit-test-key")
    credential.model_catalog.manual_models = [CredentialModelDefinition(name="unverified-model")]
    with patch("anthropic.AsyncAnthropic", return_value=client):
        model = await runtime_model(credential)
        assert model.parameters.max_tokens is None
        with pytest.raises(ValueError, match="要求明确的输出上限"):
            await model._call_api(model.model, [UserMsg(name="test", content="test")])
        result = await check_model(credential, model.model)
    assert not result.success
    assert "要求明确的输出上限" in result.raw_response
    client.messages.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_anthropic_accepts_explicit_custom_request_limit():
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=RuntimeError("captured request"))
    with patch("anthropic.AsyncAnthropic", return_value=client):
        model = AnthropicChatModel(
            credential=AnthropicCredential(api_key="fictional-output-limit-test-key"),
            model="unverified-model",
            stream=False,
        )
    model.set_request_body_overrides({"max_tokens": 20_000, "thinking": {"type": "disabled"}})
    with pytest.raises(RuntimeError, match="captured request"):
        await model._call_api(model.model, [UserMsg(name="test", content="test")])
    request = client.messages.create.await_args.kwargs
    assert request["max_tokens"] == 20_000
    assert request["extra_body"] == {"max_tokens": 20_000, "thinking": {"type": "disabled"}}
