"""Pure computation boundary.

Legacy computation modules remain import-compatible while new code depends on
this package for engine-owned errors and utilities rather than session state.
"""

from .errors import DomainError
from .utils import safe_name

__all__ = ["DomainError", "safe_name"]
