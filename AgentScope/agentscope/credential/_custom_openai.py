# -*- coding: utf-8 -*-
"""Credential for a user-supplied OpenAI-compatible endpoint."""
from typing import TYPE_CHECKING, Literal, Type
from urllib.parse import urlsplit

from pydantic import ConfigDict, Field, SecretStr, field_validator

from ._base import CredentialBase

if TYPE_CHECKING:
    from ..embedding import EmbeddingModelBase, EmbeddingModelCard
    from ..model import ChatModelBase, ModelCard


class CustomOpenAICredential(CredentialBase):
    """A custom OpenAI-compatible chat and embeddings service."""

    model_config = ConfigDict(
        title="自定义（OpenAI 兼容）",
    )

    type: Literal["custom_openai_credential"] = "custom_openai_credential"

    api_key: SecretStr = Field(
        title="API Key",
        description="The API key accepted by the compatible service.",
    )

    base_url: str = Field(
        title="API Base URL",
        description=(
            "OpenAI-compatible API base URL, normally ending in /v1."
        ),
        examples=["https://model-router.edu-aliyun.com/v1"],
    )

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                "API Base URL must be an absolute http:// or https:// URL.",
            )
        if parsed.username or parsed.password:
            raise ValueError("API Base URL must not contain user information.")
        if parsed.query or parsed.fragment:
            raise ValueError(
                "API Base URL must not contain a query string or fragment.",
            )
        return value

    @classmethod
    def get_chat_model_class(cls) -> Type["ChatModelBase"]:
        """Use the generic OpenAI Chat Completions adapter."""
        from ..model import OpenAIChatModel

        return OpenAIChatModel

    @classmethod
    def get_embedding_model_class(cls) -> Type["EmbeddingModelBase"]:
        """Use the generic OpenAI-compatible embeddings adapter."""
        from ..embedding import OpenAIEmbeddingModel

        return OpenAIEmbeddingModel

    @classmethod
    def list_models(cls) -> list["ModelCard"]:
        """Custom services do not inherit OpenAI's fixed GPT catalogue."""
        return []

    @classmethod
    def list_embedding_models(cls) -> list["EmbeddingModelCard"]:
        """Custom services do not inherit OpenAI's fixed embedding catalog."""
        return []
