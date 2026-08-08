"""Public MCP tool implementations; one module per tool.

The registry is loaded lazily so the orchestration service can live in this
layer without creating a package-import cycle with the process-local runtime.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any


def load_public_tools() -> tuple[Any, ...]:
    from .predict_check_health import predict_check_health
    from .predict_confirm_pipeline_plan import predict_confirm_pipeline_plan
    from .predict_confirm_variables import predict_confirm_variables
    from .predict_create_session import predict_create_session
    from .predict_evaluate_models import predict_evaluate_models
    from .predict_export_model import predict_export_model
    from .predict_get_job_status import predict_get_job_status
    from .predict_get_status import predict_get_status
    from .predict_import_data import predict_import_data
    from .predict_list_sessions import predict_list_sessions
    from .predict_profile_data import predict_profile_data
    from .predict_propose_pipeline_plan import predict_propose_pipeline_plan
    from .predict_rewind_session import predict_rewind_session

    return (
        predict_check_health,
        predict_import_data,
        predict_create_session,
        predict_profile_data,
        predict_confirm_variables,
        predict_propose_pipeline_plan,
        predict_confirm_pipeline_plan,
        predict_evaluate_models,
        predict_export_model,
        predict_rewind_session,
        predict_get_status,
        predict_list_sessions,
        predict_get_job_status,
    )


class _LazyPublicTools(Sequence[Any]):
    def _items(self) -> tuple[Any, ...]:
        return load_public_tools()

    def __iter__(self) -> Iterator[Any]:
        return iter(self._items())

    def __len__(self) -> int:
        return len(self._items())

    def __getitem__(self, index):
        return self._items()[index]


PUBLIC_TOOLS: Sequence[Any] = _LazyPublicTools()

__all__ = ["PUBLIC_TOOLS", "load_public_tools"]
