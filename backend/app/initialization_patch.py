"""Sparse attachment observations, separate from validated final project data.

Omitted fields mean the attachment supplied no change.  Keep ``exclude_unset``
when serializing these models; defaults must not become instructions to clear
the existing project.  Final merged records still use the strict draft models.
"""
from __future__ import annotations

from copy import deepcopy
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
    required_keys: frozenset[str] = frozenset(),
) -> type[BaseModel]:
    fields: dict[str, Any] = {}
    for field_name, source_field in source.model_fields.items():
        field = deepcopy(source_field)
        annotation = field.annotation
        if field_name not in required_keys:
            annotation = annotation | None
            field.default = None
            field.default_factory = None
        fields[field_name] = (annotation, field)
    return create_model(name, __base__=StrictInitializationPatch, **fields)


ProjectDetailsPatch = _patch_model("ProjectDetailsPatch", ProjectDetailsDraft)
PersonnelPatch = _patch_model(
    "PersonnelPatch", PersonnelDraft,
    frozenset({"identity_card_no", "position_name"}),
)
WbsPatch = _patch_model("WbsPatch", WbsDraft, frozenset({"wbs_code"}))
RiskPatch = _patch_model(
    "RiskPatch", RiskDraftItem,
    frozenset({"related_process_name", "risk_part"}),
)
QualityRequirementPatch = _patch_model(
    "QualityRequirementPatch", QualityRequirementDraft, frozenset({"wbs_code"}),
)


class ProjectInitializationPatchPayload(StrictInitializationPatch):
    project: ProjectDetailsPatch = Field(default_factory=ProjectDetailsPatch)
    personnel: list[PersonnelPatch] = Field(default_factory=list, max_length=2000)
    wbs: list[WbsPatch] = Field(default_factory=list, max_length=10000)
    risks: list[RiskPatch] = Field(default_factory=list, max_length=5000)
    quality_requirements: list[QualityRequirementPatch] = Field(
        default_factory=list, max_length=10000,
    )
