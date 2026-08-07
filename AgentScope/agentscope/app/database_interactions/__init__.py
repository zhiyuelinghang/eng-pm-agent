"""Database-interaction management proxy."""

from ._manager import (
    DatabaseInteractionGatewayError,
    DatabaseInteractionManager,
)
from ._tool import (
    DatabaseInteractionTool,
    create_database_interaction_tools,
    runtime_argument_error,
)

__all__ = [
    "DatabaseInteractionGatewayError",
    "DatabaseInteractionManager",
    "DatabaseInteractionTool",
    "create_database_interaction_tools",
    "runtime_argument_error",
]
