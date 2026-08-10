#!/usr/bin/env python3
"""
Clean Mem0 memory store — removes test/demo data from the shared scope.

Run: python scripts/clean_mem0.py [--dry-run]

This deletes ALL memories stored under the default MEM0_USER_ID
("project_demo") that were created by demo scripts and ad-hoc testing.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
except ImportError:
    pass

from utils.langgraph_utils import get_mem0
from utils.config import MEM0_USER_ID


def main():
    parser = argparse.ArgumentParser(description="Clean Mem0 memory store")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")
    args = parser.parse_args()

    mem = get_mem0()

    # List all memories under the shared default scope
    print(f"Fetching memories for user_id='{MEM0_USER_ID}'...")
    try:
        all_memories = mem.search("", filters={"user_id": MEM0_USER_ID}, limit=1000, threshold=0.0)
    except Exception as e:
        print(f"Error fetching memories: {e}")
        sys.exit(1)

    results = all_memories if isinstance(all_memories, list) else all_memories.get("results", [])

    if not results:
        print("No memories found. Clean!")
        return

    print(f"Found {len(results)} memories to clean:\n")
    for i, m in enumerate(results, 1):
        text = m.get("memory", str(m)) if isinstance(m, dict) else str(m)
        mem_id = m.get("id", "?") if isinstance(m, dict) else "?"
        print(f"  [{i}] id={mem_id}: {text[:120]}...")

    if args.dry_run:
        print(f"\n[Dry run] Would delete {len(results)} memories.")
        return

    confirm = input(f"\nDelete all {len(results)} memories? [y/N]: ")
    if confirm.lower() != "y":
        print("Aborted.")
        return

    deleted = 0
    for m in results:
        mem_id = m.get("id") if isinstance(m, dict) else None
        if mem_id:
            try:
                mem.delete(memory_id=mem_id)
                deleted += 1
            except Exception as e:
                print(f"  Failed to delete {mem_id}: {e}")
        else:
            print(f"  Skipped (no id): {m}")

    print(f"\nDeleted {deleted}/{len(results)} memories.")

    # Verify
    try:
        remaining = mem.search("", user_id=MEM0_USER_ID, limit=1000, threshold=0.0)
        rem_results = remaining if isinstance(remaining, list) else remaining.get("results", [])
        print(f"Remaining memories: {len(rem_results)}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
