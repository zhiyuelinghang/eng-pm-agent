"""Sparse attachment observations, separate from validated final project data.

Omitted fields mean the attachment supplied no change.  Keep ``exclude_unset``
when serializing these models; defaults must not become instructions to clear
the existing project. Material values remain observations until the MCP judges
them; these models only enforce the transport envelope and known field names.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model

from .project_initialization import (
    PersonnelDraft,
    ProjectDetailsDraft,
    QualityRequirementDraft,
    RiskDraftItem,
    WbsDraft,
)


class StrictInitializationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _patch_model(
    name: str,
    source: type[BaseModel],
) -> type[BaseModel]:
    fields: dict[str, Any] = {}
    for field_name, source_field in source.model_fields.items():
        fields[field_name] = (Any, Field(default=None, description=source_field.description))
    return create_model(name, __base__=StrictInitializationPatch, **fields)


ProjectDetailsPatch = _patch_model("ProjectDetailsPatch", ProjectDetailsDraft)
PersonnelPatch = _patch_model("PersonnelPatch", PersonnelDraft)
WbsPatch = _patch_model("WbsPatch", WbsDraft)
RiskPatch = _patch_model("RiskPatch", RiskDraftItem)
QualityRequirementPatch = _patch_model("QualityRequirementPatch", QualityRequirementDraft)


class ProjectInitializationPatchPayload(StrictInitializationPatch):
    project: ProjectDetailsPatch = Field(default_factory=ProjectDetailsPatch)
    personnel: list[PersonnelPatch] = Field(default_factory=list, max_length=2000)
    wbs: list[WbsPatch] = Field(default_factory=list, max_length=10000)
    risks: list[RiskPatch] = Field(default_factory=list, max_length=5000)
    quality_requirements: list[QualityRequirementPatch] = Field(
        default_factory=list, max_length=10000,
    )
