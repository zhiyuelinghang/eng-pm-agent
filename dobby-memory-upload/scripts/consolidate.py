#!/usr/bin/env python3
"""Standalone cron entry point for experience Phase 2 consolidation.

Usage:
  python scripts/consolidate.py [project_id]

  # crontab example (daily at 2 AM):
  # 0 2 * * * cd /path/to/dobby-memory && python scripts/consolidate.py my_project
"""

import asyncio
import sys
from pathlib import Path

# Ensure dobby-memory is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.consolidation_engine import ConsolidationEngine


async def main() -> None:
    pid = sys.argv[1] if len(sys.argv) > 1 else "default"
    print(f"consolidate: project_id={pid}")
    engine = ConsolidationEngine()
    result = await engine.run(pid, source="experiences", mode="nightly")
    print(
        f"  items_loaded={result.items_loaded} "
        f"direct_merged={result.direct_merged} "
        f"llm_judged={result.llm_judged} "
        f"created={result.created} updated={result.updated} "
        f"error={result.error}" if result.error else ""
    )


if __name__ == "__main__":
    asyncio.run(main())
