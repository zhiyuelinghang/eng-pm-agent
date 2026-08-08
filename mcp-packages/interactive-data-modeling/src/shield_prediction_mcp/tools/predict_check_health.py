from __future__ import annotations

from typing import Any

from .. import __version__
from ..engine.modeling import SUPPORTED_MODELS
from ..engine.planning import model_availability
from ..schemas.envelope import ok


def predict_check_health() -> dict[str, Any]:
    """只读探查工具：检查服务版本和可用模型。前置条件：无；无副作用。"""
    return ok(
        data={
            "server": "interactive-data-modeling",
            "version": __version__,
            "contract_version": 2,
            "workflow_version": 6,
            "supported_models": list(SUPPORTED_MODELS),
            "model_availability": model_availability(),
        },
        message="服务运行正常",
    )
