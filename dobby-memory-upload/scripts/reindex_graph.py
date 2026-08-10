#!/usr/bin/env python3
"""
GraphRAG index script — initial backfill or rebuild after prompt changes.

Usage:
  LIGHTRAG_ENABLED=true python scripts/reindex_graph.py
  LIGHTRAG_ENABLED=true python scripts/reindex_graph.py --file data/engineering_safety.md
"""

import asyncio
import os
import sys
import argparse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import LIGHTRAG_ENABLED, LIGHTRAG_WORKING_DIR
from utils.graph_rag_engine import get_graph_rag


async def main():
    parser = argparse.ArgumentParser(description="GraphRAG reindex tool")
    parser.add_argument(
        "--file", default="data/engineering_safety.md",
        help="Path to the file to index (relative to dobby-memory/)",
    )
    parser.add_argument(
        "--project", default="default",
        help="Project ID for workspace isolation",
    )
    args = parser.parse_args()

    if not LIGHTRAG_ENABLED:
        print("ERROR: LIGHTRAG_ENABLED=false. Set LIGHTRAG_ENABLED=true and retry.")
        sys.exit(1)

    file_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        args.file.lstrip("/").lstrip("\\"),
    )

    if not os.path.exists(file_path):
        print(f"ERROR: File not found: {file_path}")
        sys.exit(1)

    print(f"Initializing GraphRAG engine (project={args.project})...")
    engine = await get_graph_rag(project_id=args.project)

    if not engine._initialized:
        print(f"ERROR: GraphRAG engine failed to initialize for project '{args.project}'.")
        print("Check PostgreSQL connectivity and embed_server health.")
        sys.exit(1)

    print(f"Indexing: {file_path}")
    doc_id = await engine.index_file(file_path)
    print(f"Done! Document ID: {doc_id}")
    print(f"Graph persisted to: {os.path.join(LIGHTRAG_WORKING_DIR, args.project)}")

    await engine.finalize()


if __name__ == "__main__":
    asyncio.run(main())
