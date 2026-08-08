from __future__ import annotations

import re


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", value).strip("._")
    return cleaned[:80] or "artifact"
