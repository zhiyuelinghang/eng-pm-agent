# -*- coding: utf-8 -*-
"""Credential-scoped model catalog data structures."""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class CredentialModelDefinition(BaseModel):
    """A model supplied by discovery or entered by the user."""

    model_type: Literal["chat", "embedding"] = Field(
        default="chat",
        description=(
            "How AgentScope should use this model. Existing catalog records "
            "default to chat for backward compatibility."
        ),
    )
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
    dimensions: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Embedding vector dimensions. Required for embedding models and "
            "unused by chat models."
        ),
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

    @model_validator(mode="after")
    def _require_embedding_dimensions(self) -> "CredentialModelDefinition":
        if self.model_type == "embedding" and self.dimensions is None:
            raise ValueError(
                "Embedding model definitions require detected dimensions.",
            )
        return self


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
    hidden_embedding_model_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Built-in embedding model identifiers hidden by the user."
        ),
    )
    model_default_parameters: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description=(
            "Provider-specific default inference parameters keyed by exact "
            "chat model identifier. Runtime/session parameters override "
            "these values."
        ),
    )
    last_discovery_at: datetime | None = Field(
        default=None,
        description="Most recent discovery attempt timestamp.",
    )
    last_discovery_error: str | None = Field(
        default=None,
        description="Most recent discovery failure, if any.",
    )

    @field_validator("hidden_model_ids", "hidden_embedding_model_ids")
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

    @field_validator("model_default_parameters")
    @classmethod
    def _normalise_model_default_parameters(
        cls,
        values: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Normalise model ids and omit empty parameter records."""
        if len(values) > 1000:
            raise ValueError(
                "At most 1000 model default parameter records are allowed.",
            )
        result: dict[str, dict[str, Any]] = {}
        for raw_name, parameters in values.items():
            name = raw_name.strip()
            if not name or len(name) > 512:
                raise ValueError(
                    "Model default parameter keys must be non-empty model "
                    "identifiers no longer than 512 characters.",
                )
            if parameters:
                result[name] = dict(parameters)
        return result
