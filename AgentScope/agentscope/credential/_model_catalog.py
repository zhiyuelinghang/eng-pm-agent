# -*- coding: utf-8 -*-
"""Credential-scoped chat model catalog data structures."""
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class CredentialModelDefinition(BaseModel):
    """A model supplied by discovery or entered by the user."""

    name: str = Field(
        min_length=1,
        max_length=512,
        description="The exact model identifier sent to the provider.",
    )
    label: str | None = Field(
        default=None,
        max_length=512,
        description="Optional user-facing model label.",
    )
    context_size: int = Field(
        default=128_000,
        gt=0,
        description="Context window used by AgentScope.",
    )
    output_size: int = Field(
        default=8_192,
        gt=0,
        description="Maximum output tokens used by AgentScope.",
    )
    input_types: list[str] = Field(
        default_factory=lambda: ["text/plain"],
        description="Supported input MIME types.",
    )
    output_types: list[str] = Field(
        default_factory=lambda: ["text/plain"],
        description="Supported output MIME types.",
    )

    @field_validator("name")
    @classmethod
    def _strip_and_validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Model identifier must not be empty.")
        return value

    @field_validator("label")
    @classmethod
    def _strip_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class CredentialModelCatalog(BaseModel):
    """Persisted model customisation for one credential."""

    discovered_models: list[CredentialModelDefinition] = Field(
        default_factory=list,
        description="Latest successful provider discovery snapshot.",
    )
    manual_models: list[CredentialModelDefinition] = Field(
        default_factory=list,
        description="Models explicitly maintained by the user.",
    )
    hidden_model_ids: list[str] = Field(
        default_factory=list,
        description="Built-in or discovered model identifiers hidden by user.",
    )
    last_discovery_at: datetime | None = Field(
        default=None,
        description="Most recent discovery attempt timestamp.",
    )
    last_discovery_error: str | None = Field(
        default=None,
        description="Most recent discovery failure, if any.",
    )

    @field_validator("hidden_model_ids")
    @classmethod
    def _normalise_hidden_ids(cls, values: list[str]) -> list[str]:
        """Trim, remove blanks, and keep identifiers in stable order."""
        seen: set[str] = set()
        result: list[str] = []
        for raw in values:
            value = raw.strip()
            if value and value not in seen:
                result.append(value)
                seen.add(value)
        return result
