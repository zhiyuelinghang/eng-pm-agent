# -*- coding: utf-8 -*-
"""Service health response models."""

from typing import Literal

from pydantic import BaseModel, Field

ComponentStatus = Literal["ok", "not_ready", "disabled"]


class HealthResponse(BaseModel):
    """I/O-free service readiness report."""

    status: Literal["ok", "not_ready"] = Field(
        description="Overall readiness of required service components.",
    )
    version: str = Field(description="AgentScope service version.")
    components: dict[str, ComponentStatus] = Field(
        description="Readiness status for every runtime subsystem.",
    )
