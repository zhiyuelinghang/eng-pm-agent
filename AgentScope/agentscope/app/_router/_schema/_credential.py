# -*- coding: utf-8 -*-
"""Request / response schemas for the credential router."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ..._service import (
    CredentialEmbeddingModelEntry,
    CredentialModelEntry,
    CredentialView,
)
from ....credential import CredentialModelDefinition


class CreateCredentialRequest(BaseModel):
    """Request body for creating a new credential."""

    data: dict = Field(description="Credential payload (e.g. API keys).")


class CreateCredentialResponse(BaseModel):
    """Response body after creating a credential."""

    credential_id: str = Field(
        description="Server-assigned credential identifier.",
    )


class UpdateCredentialRequest(BaseModel):
    """Request body for updating an existing credential."""

    data: dict = Field(description="New credential payload.")


class ListCredentialsResponse(BaseModel):
    """Response body for listing credentials."""

    credentials: list[CredentialView] = Field(
        description="Credential records.",
    )
    total: int = Field(description="Total number of credentials.")


class ListCredentialSchemasResponse(BaseModel):
    """Response body for listing credential type schemas."""

    schemas: list[dict] = Field(
        description="JSON schemas for all registered credential types.",
    )


class UpdateCredentialModelCatalogRequest(BaseModel):
    """Replace the user-managed portion of a credential's model catalog."""

    manual_models: list[CredentialModelDefinition] = Field(
        default_factory=list,
        description="Models maintained explicitly by the user.",
    )
    hidden_model_ids: list[str] = Field(
        default_factory=list,
        description="Built-in or discovered model identifiers to hide.",
    )
    hidden_embedding_model_ids: list[str] = Field(
        default_factory=list,
        description="Built-in embedding model identifiers to hide.",
    )


class TestCredentialModelRequest(BaseModel):
    """Request one real, minimal completion from a catalogued model."""

    model: str = Field(
        min_length=1,
        max_length=512,
        description="Exact provider model identifier to test.",
    )
    model_type: Literal["chat", "embedding"] = Field(
        default="chat",
        description="Whether to run a chat completion or embedding request.",
    )

    @field_validator("model")
    @classmethod
    def _strip_model(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Model identifier must not be empty.")
        return value


class CredentialModelCatalogResponse(BaseModel):
    """Resolved model catalog for one concrete credential."""

    models: list[CredentialModelEntry] = Field(
        description="All known chat models, including disabled entries.",
    )
    embedding_models: list[CredentialEmbeddingModelEntry] = Field(
        description="All known embedding models, including disabled entries.",
    )
    manual_models: list[CredentialModelDefinition] = Field(
        description="The exact persisted manual model definitions.",
    )
    hidden_model_ids: list[str] = Field(
        description="The exact persisted hidden chat model identifiers.",
    )
    hidden_embedding_model_ids: list[str] = Field(
        description="The exact persisted hidden embedding model identifiers.",
    )
    total: int = Field(description="Number of enabled candidate models.")
    discovery_supported: bool = Field(
        description="Whether GET /models discovery is supported.",
    )
    last_discovery_at: datetime | None = Field(default=None)
    last_discovery_error: str | None = Field(default=None)
