"""Run one pytest suite with explicit source roots.

The project uses an embedded Python runtime whose ``._pth`` file intentionally
does not add the current working directory.  Every suite therefore declares
its import roots instead of depending on the shell that happened to launch it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prepend",
        action="append",
        default=[],
        metavar="PATH",
        help="Path to prepend to sys.path before pytest starts; repeatable.",
    )
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()

    for raw_path in reversed(arguments.prepend):
        resolved = str(Path(raw_path).resolve())
        if resolved not in sys.path:
            sys.path.insert(0, resolved)

    import pytest

    pytest_args = arguments.pytest_args
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    return int(pytest.main(pytest_args))


if __name__ == "__main__":
    raise SystemExit(main())
