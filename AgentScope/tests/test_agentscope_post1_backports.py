# -*- coding: utf-8 -*-
"""Regression coverage for selected post-v2.0.7 upstream fixes."""
from datetime import datetime
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase

from pydantic import BaseModel

from agentscope.formatter import OpenAIChatFormatter, OpenAIResponseFormatter
from agentscope.message import (
    AssistantMsg,
    Base64Source,
    DataBlock,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
    ToolResultState,
    URLSource,
)
from agentscope.middleware._tracing._extractor import (
    _get_chat_response_finish_reason,
)
from agentscope.model import ChatResponse, FinishedReason, GeminiChatModel
from agentscope.model._gemini._model import _sanitize_schema_for_gemini
from agentscope.model._openai_response._model import _dump_reasoning_item


class _ReasoningItem(BaseModel):
    id: str
    type: str = "reasoning"
    summary: list[dict]
    encrypted_content: str | None = None
    status: str | None = None


class FormatterPostReleaseBackportTest(IsolatedAsyncioTestCase):
    """Formatter fixes keep replayed histories stable and provider-native."""

    async def test_multimodal_identifier_is_stable(self) -> None:
        formatter = OpenAIChatFormatter()
        image = DataBlock(
            id="stable-image-id",
            source=Base64Source(
                data="aW1hZ2U=",
                media_type="image/png",
            ),
        )

        first = formatter.convert_tool_result_to_string([image])
        second = formatter.convert_tool_result_to_string([image])

        self.assertEqual(first[0], second[0])
        self.assertEqual(
            [block.text for block in first[1] if isinstance(block, TextBlock)],
            [block.text for block in second[1] if isinstance(block, TextBlock)],
        )
        self.assertIn("[stable-image-id]", first[0])

    async def test_responses_tool_image_uses_native_output(self) -> None:
        formatter = OpenAIResponseFormatter()
        formatted = await formatter.format(
            [
                AssistantMsg(
                    name="assistant",
                    content=[
                        ToolCallBlock(
                            id="call-image",
                            name="capture",
                            input="{}",
                        ),
                        ToolResultBlock(
                            id="call-image",
                            name="capture",
                            output=[
                                TextBlock(text="截图"),
                                DataBlock(
                                    source=Base64Source(
                                        data="aW1hZ2U=",
                                        media_type="image/png",
                                    ),
                                ),
                            ],
                            state=ToolResultState.SUCCESS,
                        ),
                    ],
                ),
            ],
        )

        self.assertEqual(
            formatted[1]["output"],
            [
                {"type": "input_text", "text": "截图"},
                {
                    "type": "input_image",
                    "image_url": "data:image/png;base64,aW1hZ2U=",
                },
            ],
        )

    async def test_responses_tool_pdf_keeps_platform_text_fallback(self) -> None:
        formatter = OpenAIResponseFormatter(
            input_types=["text/plain", "application/pdf"],
        )
        output = formatter._format_tool_result_output(
            [
                DataBlock(
                    source=URLSource(
                        url="https://example.test/manual.pdf",
                        media_type="application/pdf",
                    ),
                ),
            ],
        )

        self.assertIsInstance(output, str)
        self.assertIn("https://example.test/manual.pdf", output)

    async def test_encrypted_reasoning_is_replayed_verbatim(self) -> None:
        raw = {
            "type": "reasoning",
            "id": "rs-encrypted",
            "summary": [],
            "content": [],
            "encrypted_content": "ciphertext",
            "status": "completed",
        }
        formatted = await OpenAIResponseFormatter().format(
            [
                AssistantMsg(
                    name="assistant",
                    content=[
                        ThinkingBlock(
                            thinking="",
                            reasoning_item_id="rs-encrypted",
                            reasoning_item_raw=raw,
                        ),
                    ],
                ),
            ],
        )

        self.assertEqual(formatted, [raw])
        self.assertIsNot(formatted[0], raw)


class ProviderPostReleaseBackportTest(TestCase):
    """Provider schemas and usage accounting follow upstream semantics."""

    def test_reasoning_dump_excludes_optional_null_fields(self) -> None:
        dumped = _dump_reasoning_item(
            _ReasoningItem(
                id="rs-1",
                summary=[],
                encrypted_content="ciphertext",
            ),
        )
        self.assertNotIn("status", dumped)
        self.assertEqual(dumped["encrypted_content"], "ciphertext")

    def test_gemini_nullable_type_arrays_are_sanitized(self) -> None:
        self.assertEqual(
            _sanitize_schema_for_gemini(
                {"type": ["string", "null"]},
            ),
            {"type": "string"},
        )
        self.assertEqual(
            _sanitize_schema_for_gemini(
                {"type": ["string", "integer", "null"]},
            ),
            {"anyOf": [{"type": "string"}, {"type": "integer"}]},
        )

    def test_gemini_usage_separates_tool_and_output_tokens(self) -> None:
        usage = GeminiChatModel._extract_usage(
            SimpleNamespace(),
            SimpleNamespace(
                prompt_token_count=10,
                total_token_count=25,
                tool_use_prompt_token_count=3,
                candidates_token_count=7,
                thoughts_token_count=5,
                cached_content_token_count=2,
            ),
            datetime.now(),
        )

        self.assertEqual(usage.input_tokens, 13)
        self.assertEqual(usage.output_tokens, 12)
        self.assertEqual(usage.cache_input_tokens, 2)

    def test_audio_mpeg_maps_to_mp3_without_filename_inference(self) -> None:
        formatted = OpenAIChatFormatter._format_audio_source(
            Base64Source(data="YXVkaW8=", media_type="audio/mpeg"),
        )
        self.assertEqual(formatted["input_audio"]["format"], "mp3")

    def test_interrupted_response_is_reported_to_tracing(self) -> None:
        response = ChatResponse(
            content=[],
            is_last=True,
            finished_reason=FinishedReason.INTERRUPTED,
        )
        self.assertEqual(
            _get_chat_response_finish_reason(response),
            "interrupted",
        )
