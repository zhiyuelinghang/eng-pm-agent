"""Inputs for reviewing and confirming a selected set of project changes."""
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .project_initialization import PersonnelCredentialInput


class PreviewInitializationChangesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_keys: list[str] | None = Field(default=None, max_length=30000)
    resolutions: dict[str, int | None] = Field(default_factory=dict)
    force_validation: bool = False

    @field_validator("selected_keys")
    @classmethod
    def unique_keys(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and (len(value) != len(set(value)) or any(not key or len(key) > 200 for key in value)):
            raise ValueError("请选择有效且不重复的变更项")
        return value

    @field_validator("resolutions")
    @classmethod
    def valid_targets(cls, value: dict[str, int | None]) -> dict[str, int | None]:
        if len(value) > 30000 or any(not key or len(key) > 200 or (target is not None and target <= 0) for key, target in value.items()):
            raise ValueError("数据匹配结果无效")
        return value


class ApplyInitializationChangesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: str = Field(min_length=1, max_length=36)
    allow_warnings: bool = False
    personnel_credentials: list[PersonnelCredentialInput] = Field(default_factory=list, max_length=2000)
