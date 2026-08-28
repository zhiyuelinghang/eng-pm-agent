"""Dobby 后端服务。"""

from __future__ import annotations

from pathlib import Path
import sys


_TASK_ENGINE_SRC = Path(__file__).resolve().parents[2] / "Task" / "src"
if str(_TASK_ENGINE_SRC) not in sys.path:
    sys.path.insert(0, str(_TASK_ENGINE_SRC))
