from __future__ import annotations

import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent


def _bootstrap_source_checkout() -> None:
    """Expose source and cached dependencies when run from this monorepo."""

    source_root = PACKAGE_ROOT / "src"
    if not source_root.is_dir():
        return
    dependency_cache = (
        PACKAGE_ROOT.parents[1]
        / "data"
        / "agentscope"
        / "build-cache"
        / "interactive-data-modeling-py313"
    )
    for path in (source_root, dependency_cache):
        if path.is_dir() and str(path) not in sys.path:
            sys.path.insert(0, str(path))


def main() -> None:
    """Import the MCP server only in the actual STDIO parent process."""
    _bootstrap_source_checkout()
    from shield_prediction_mcp.server import main as run_server

    run_server()


if __name__ == "__main__":
    main()
