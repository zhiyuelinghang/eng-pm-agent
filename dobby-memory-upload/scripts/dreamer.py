"""Dreamer 夜间维护 CLI — cron 定时调用入口

Usage:
  python scripts/dreamer.py                    # 运行所有到期任务
  python scripts/dreamer.py --task verify      # 手动运行指定任务
  python scripts/dreamer.py --task curate
  python scripts/dreamer.py --project my_project  # 指定项目
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Dreamer memory maintenance")
    parser.add_argument("--task", type=str, help="Run specific task (decay|verify|curate|classify)")
    parser.add_argument("--project", type=str, default="demo", help="Project ID")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    from utils.memory_manager import MemoryManager

    mm = MemoryManager(project_id=args.project)
    results = await mm.run_dreamer(
        project_id=args.project,
        task_name=args.task,
    )

    if args.json:
        output = {
            name: {
                "skipped": r.skipped,
                "error": r.error,
                "verified": r.verified,
                "updated": r.updated,
                "archived": r.archived,
                "merged": r.merged,
                "classified": r.classified,
                "pruned": r.pruned,
                "duration_s": r.duration_seconds,
            }
            for name, r in results.items()
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        for name, r in results.items():
            if r.skipped:
                print(f"[{name}] SKIPPED: {r.reason}")
            elif r.error:
                print(f"[{name}] FAILED: {r.error}")
            else:
                parts = []
                if r.pruned: parts.append(f"pruned={r.pruned}")
                if r.verified: parts.append(f"verified={r.verified}")
                if r.updated: parts.append(f"updated={r.updated}")
                if r.merged: parts.append(f"merged={r.merged}")
                if r.archived: parts.append(f"archived={r.archived}")
                if r.classified: parts.append(f"classified={r.classified}")
                print(f"[{name}] OK ({r.duration_seconds:.1f}s): {', '.join(parts)}")

if __name__ == "__main__":
    asyncio.run(main())
