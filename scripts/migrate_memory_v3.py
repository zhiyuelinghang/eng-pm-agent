"""Preview/import legacy memory into the three drawers without model calls.

使用项目内嵌 Python：scripts/migrate_memory_v3.py [--apply]
先执行数据库迁移；默认仅核对，--apply 保留旧表并导入明确归属的数据。
"""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from utils import config
    from utils.memory_migration import migrate_legacy_memories
    from utils.memory_repository import MemoryRepository
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply",action="store_true")
    args = parser.parse_args()
    repo = MemoryRepository(config.DATABASE_URL)
    try:
        print(json.dumps(migrate_legacy_memories(repo,tenant_id=config.MEMORY_TENANT_ID,
                         collection=config.MEM0_COLLECTION,apply=args.apply),ensure_ascii=False,indent=2))
    finally:
        repo.close()


if __name__ == "__main__":
    main()
