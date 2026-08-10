#!/usr/bin/env python3
"""Standalone cron entry point for Graphiti event processing (Phase 3-A).

Usage:
  python scripts/graphiti_process.py [project_id]

  # crontab example (every 30 minutes):
  # */30 * * * * cd /path/to/dobby-memory && python scripts/graphiti_process.py my_project
"""

import asyncio
import sys
from pathlib import Path

# Ensure dobby-memory is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.graphiti_client import process_pending_events  # noqa: E402


async def main() -> None:
    pid = sys.argv[1] if len(sys.argv) > 1 else "default"
    print(f"graphiti_process: project_id={pid}")
    result = await process_pending_events(pid)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
