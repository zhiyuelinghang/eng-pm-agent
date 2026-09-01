"""Enforce source-file size ratchets and the main extracted boundaries."""
from __future__ import annotations

import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".vue", ".css"}
DEFAULT_LIMITS = {
    ".py": 1500,
    ".ts": 1500,
    ".tsx": 1500,
    ".vue": 1500,
    ".css": 1500,
}
TEST_FILE_LIMIT = 2000
IGNORED_DIRECTORIES = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "site-packages",
}

# Known large modules use explicit ratchets.  A ratchet may be lowered after a
# refactor, but must not be raised merely to make a new oversized change pass.
FILE_RATCHETS = {
    "backend/app/api.py": 2500,
    "backend/app/database_interactions.py": 2550,
    "backend/app/engineering_document_catalog.py": 1700,
    "backend/app/engineering_documents_api.py": 1550,
    "backend/app/models.py": 2050,
    "frontend/src/components/admin/ProjectDocumentPermissionPanel.vue": 1650,
    "frontend/src/components/business/ProjectKnowledgeChat.vue": 1650,
    "frontend/src/components/chat/ProjectGroupChat.vue": 2050,
    "frontend/src/views/workspace/AiWorkPlatformView.vue": 2900,
    "frontend/src/views/workspace/DocumentLibraryView.vue": 2050,
    "frontend/src/views/workspace/ProjectSetupView.vue": 3100,
    "frontend/src/views/workspace/styles/AiWorkPlatformView.base.css": 1850,
    "frontend/src/views/workspace/styles/AiWorkPlatformView.tasks.css": 2350,
}

REQUIRED_MARKERS = {
    "backend/app/api.py": (
        "from .api_common import (",
    ),
    "backend/app/database_interactions.py": (
        "from .database_interaction_contracts import (",
    ),
    "backend/app/main.py": (
        "app.include_router(agent_conversations_router)",
        "app.include_router(engineering_documents_router)",
    ),
    "frontend/src/views/workspace/AiWorkPlatformView.vue": (
        '<style scoped src="./styles/AiWorkPlatformView.base.css"></style>',
        '<style scoped src="./styles/AiWorkPlatformView.tasks.css"></style>',
    ),
    "frontend/src/views/workspace/ProjectSetupView.vue": (
        "from './project-setup/presentation'",
        '<style scoped src="./styles/ProjectSetupView.css"></style>',
    ),
}

FORBIDDEN_MARKERS = {
    "backend/app/api.py": (
        '@router.get("/agents/catalog")',
        '@router.get("/projects/{project_id}/engineering-documents/workspace")',
    ),
}


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def _scan_roots() -> list[Path]:
    roots = [
        PROJECT_ROOT / "backend" / "app",
        PROJECT_ROOT / "backend" / "tests",
        PROJECT_ROOT / "frontend" / "src",
        PROJECT_ROOT / "scripts",
    ]
    packages_root = PROJECT_ROOT / "mcp-packages"
    if packages_root.is_dir():
        for package in packages_root.iterdir():
            if not package.is_dir():
                continue
            roots.extend((package / "src", package / "tests"))
    return [root for root in roots if root.is_dir()]


def _source_files() -> list[Path]:
    files: set[Path] = set()
    for root in _scan_roots():
        for current_root, directory_names, file_names in os.walk(root):
            directory_names[:] = [
                name
                for name in directory_names
                if name not in IGNORED_DIRECTORIES
            ]
            current = Path(current_root)
            for name in file_names:
                candidate = current / name
                if candidate.suffix.lower() in SOURCE_SUFFIXES:
                    files.add(candidate)

    packages_root = PROJECT_ROOT / "mcp-packages"
    if packages_root.is_dir():
        for package in packages_root.iterdir():
            if package.is_dir():
                files.update(package.glob("*.py"))
    return sorted(files)


def _relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _is_test_file(relative_path: str) -> bool:
    return "/tests/" in f"/{relative_path}" or Path(relative_path).name.startswith(
        "test_",
    )


def _line_limit(path: Path) -> int:
    relative_path = _relative(path)
    if relative_path in FILE_RATCHETS:
        return FILE_RATCHETS[relative_path]
    if _is_test_file(relative_path):
        return TEST_FILE_LIMIT
    return DEFAULT_LIMITS[path.suffix.lower()]


def _read_source(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def main() -> int:
    _configure_console()
    violations: list[str] = []
    checked = 0
    for path in _source_files():
        relative_path = _relative(path)
        try:
            source = _read_source(path)
        except (OSError, UnicodeError) as exc:
            violations.append(f"{relative_path}：无法按 UTF-8 读取（{exc}）")
            continue
        checked += 1
        line_count = len(source.splitlines())
        line_limit = _line_limit(path)
        if line_count > line_limit:
            violations.append(
                f"{relative_path}：{line_count} 行，超过 {line_limit} 行上限",
            )

    for relative_path, markers in REQUIRED_MARKERS.items():
        source = _read_source(PROJECT_ROOT / relative_path)
        for marker in markers:
            if marker not in source:
                violations.append(
                    f"{relative_path}：缺少结构边界标记 {marker!r}",
                )

    for relative_path, markers in FORBIDDEN_MARKERS.items():
        source = _read_source(PROJECT_ROOT / relative_path)
        for marker in markers:
            if marker in source:
                violations.append(
                    f"{relative_path}：已拆分职责回流 {marker!r}",
                )

    if violations:
        print("代码结构检查失败：")
        for violation in violations:
            print(f"  - {violation}")
        return 1

    print(f"代码结构检查通过：已检查 {checked} 个源码/测试文件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
