"""Catalogue selection and native image transport use the same model binding."""
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from agentscope.app._router._agent import _validate_model_policy
from agentscope.app._router._schedule import create_schedule
from agentscope.app._router._schema._schedule import CreateScheduleRequest
from agentscope.app._router._session import _ensure_credential_exists
from agentscope.app._service._attachment_pipeline import AttachmentPipeline
from agentscope.app._service._credential_models import build_credential_model_catalog
from agentscope.app._service._model import get_model
from agentscope.app.storage import AgentModelPolicy, ChatModelConfig, TTSModelConfig
from agentscope.app.storage._utils import _dump_with_secrets
from agentscope.credential import CredentialModelDefinition, CustomOpenAICredential
from agentscope.message import Base64Source, DataBlock, TextBlock, ToolResultState, URLSource, UserMsg
from agentscope.tool import ToolChunk


IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"]


def binding(*, native_images=True):
    credential = CustomOpenAICredential(
        api_key="fictional-binding-test-key", base_url="https://example.invalid/v1",
    )
    credential.model_catalog.manual_models = [
        CredentialModelDefinition(
            name="active-model",
            input_types=["text/plain", *IMAGE_TYPES] if native_images else ["text/plain"],
        ),
        CredentialModelDefinition(name="disabled-model"),
    ]
    credential.model_catalog.hidden_model_ids = ["disabled-model"]
    config = ChatModelConfig(
        type=credential.type, credential_id=credential.id, model="active-model", parameters={},
    )
    access = SimpleNamespace(
        resolve_credential=AsyncMock(return_value=SimpleNamespace(data=_dump_with_secrets(credential))),
        resolve_agent=AsyncMock(),
        get_resource=AsyncMock(),
    )
    return credential, config, access


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["missing", "disabled", "type"])
@pytest.mark.parametrize("entry", ["runtime", "agent", "session", "schedule"])
async def test_configuration_and_execution_reject_invalid_catalogue_bindings(invalid, entry):
    _credential, config, access = binding()
    update = {"model": invalid + "-model"} if invalid != "type" else {"type": "deepseek_credential"}
    config = config.model_copy(update=update)
    storage = SimpleNamespace(upsert_schedule=AsyncMock())
    scheduler = SimpleNamespace(register_schedule=AsyncMock())
    with patch("openai.AsyncClient") as sdk, pytest.raises(HTTPException) as error:
        if entry == "runtime":
            await get_model("owner", config, access)
        elif entry == "agent":
            await _validate_model_policy("owner", AgentModelPolicy(mode="fixed", chat_model_config=config), access)
        elif entry == "session":
            await _ensure_credential_exists(access, "owner", config)
        else:
            await create_schedule(
                CreateScheduleRequest(name="test", cron_expression="0 9 * * *", agent_id="agent", chat_model_config=config),
                user_id="owner", access=access, storage=storage, scheduler=scheduler,
            )
    assert error.value.status_code == 422
    assert {"missing": "不在", "disabled": "已停用", "type": "不匹配"}[invalid] in error.value.detail
    sdk.assert_not_called()
    storage.upsert_schedule.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_model_selection_preserves_catalogue_identity_and_media_types():
    _credential, config, access = binding()
    with patch("openai.AsyncClient"):
        model = await get_model("owner", config, access)
    assert model.model == "active-model"
    assert model.input_types == ["text/plain", *IMAGE_TYPES]
    assert model.formatter.input_types == model.input_types
    policy = await _validate_model_policy("owner", AgentModelPolicy(mode="fixed", chat_model_config=config), access)
    assert policy.chat_model_config.model == "active-model"
    await _ensure_credential_exists(access, "owner", config)


@pytest.mark.asyncio
async def test_tts_visibility_check_does_not_treat_tts_as_a_chat_model():
    _credential, _config, access = binding()
    tts = TTSModelConfig(type="test-tts", credential_id="tts-credential", model="voice-model", parameters={})
    await _ensure_credential_exists(access, "owner", tts)
    access.resolve_credential.assert_not_awaited()
    access.get_resource.assert_awaited_once()


def test_manual_multimodal_metadata_survives_discovery_refresh():
    credential, _config, _access = binding()
    credential.model_catalog.discovered_models = [CredentialModelDefinition(name="active-model")]
    before = build_credential_model_catalog(credential)[0]
    credential.model_catalog.discovered_models = [CredentialModelDefinition(name="active-model", output_size=40_000)]
    after = build_credential_model_catalog(credential)[0]
    assert before.input_types == after.input_types == ["text/plain", *IMAGE_TYPES]
    assert before.source == after.source == "manual"
    assert after.output_size is None


def image_message(media_type):
    encoded = base64.b64encode(b"native-image-transport-fixture").decode()
    return UserMsg(name="user", content=[
        TextBlock(text="Describe this image"),
        DataBlock(name="fixture-image", source=Base64Source(media_type=media_type, data=encoded)),
    ])


@pytest.mark.asyncio
@pytest.mark.parametrize("media_type", IMAGE_TYPES)
async def test_native_image_reaches_openai_request_without_ocr_or_text_substitution(media_type):
    _credential, config, access = binding()
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("captured request"))
    with patch("openai.AsyncClient", return_value=client):
        model = await get_model("owner", config, access)
    model.stream = False
    original = image_message(media_type)
    original_block = original.get_content_blocks("data")[0].model_dump()
    toolkit = SimpleNamespace(get_tool=AsyncMock())
    prepared = await AttachmentPipeline().prepare(original, toolkit, supported_input_types=model.input_types)
    toolkit.get_tool.assert_not_awaited()
    assert prepared.get_content_blocks("data")[0].model_dump() == original_block
    assert original.get_content_blocks("data")[0].model_dump() == original_block
    assert prepared.metadata["attachment_preprocessing"]["items"][0]["parser"] == "native_image"
    with pytest.raises(RuntimeError, match="captured request"):
        await model._call_api(model.model, [prepared])
    request = client.chat.completions.create.await_args.kwargs
    content = request["messages"][-1]["content"]
    images = [block for block in content if block["type"] == "image_url"]
    assert len(images) == 1
    source = original_block["source"]
    assert images[0]["image_url"]["url"] == f"data:{media_type};base64,{source['data']}"
    assert "parsed-attachments" not in str(content)


@pytest.mark.asyncio
async def test_native_image_remains_when_document_parser_fails():
    original = image_message("image/png")
    original.content.append(DataBlock(name="broken.pdf", source=Base64Source(media_type="application/pdf", data="YnJva2Vu")))
    toolkit = SimpleNamespace(get_tool=AsyncMock(return_value=None))
    prepared = await AttachmentPipeline().prepare(original, toolkit, supported_input_types=["text/plain", "image/png"])
    assert len(prepared.get_content_blocks("data")) == 1
    assert prepared.get_content_blocks("data")[0].source.media_type == "image/png"
    status = prepared.metadata["attachment_preprocessing"]
    assert status["status"] == "partial"
    assert status["ready"] == status["failed"] == 1


@pytest.mark.asyncio
async def test_text_model_parses_images_instead_of_claiming_native_vision():
    original = image_message("image/png")
    parser = SimpleNamespace(call=AsyncMock(return_value=ToolChunk(
        content=[TextBlock(text=json.dumps({"parser": "ocr", "lines": ["parsed image text"]}))],
        state=ToolResultState.SUCCESS,
    )))
    toolkit = SimpleNamespace(get_tool=AsyncMock(return_value=parser))
    prepared = await AttachmentPipeline().prepare(original, toolkit, supported_input_types=["text/plain"])
    assert not prepared.get_content_blocks("data")
    assert "parsed image text" in prepared.get_text_content()
    parser.call.assert_awaited_once()


@pytest.mark.asyncio
async def test_url_images_do_not_bypass_platform_attachment_source_restrictions():
    original = UserMsg(name="user", content=[DataBlock(name="remote.png", source=URLSource(
        media_type="image/png", url="https://example.invalid/not-fetched.png",
    ))])
    toolkit = SimpleNamespace(get_tool=AsyncMock(return_value=None))
    prepared = await AttachmentPipeline().prepare(original, toolkit, supported_input_types=IMAGE_TYPES)
    assert not prepared.get_content_blocks("data")
    assert prepared.metadata["attachment_preprocessing"]["status"] == "failed"
