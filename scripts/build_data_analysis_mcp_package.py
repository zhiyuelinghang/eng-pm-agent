"""Build the dependency-complete interactive data-modeling MCP package."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "mcp-packages" / "interactive-data-modeling"
EMBEDDED_PYTHON = PROJECT_ROOT / "python-3.13.14"
RUNTIME_PYTHON = EMBEDDED_PYTHON / "python.exe"
REQUIREMENTS = SOURCE_DIR / "requirements-platform.txt"
DEFAULT_DEPENDENCY_CACHE = (
    PROJECT_ROOT
    / "data"
    / "agentscope"
    / "build-cache"
    / "interactive-data-modeling-py313"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "data"
    / "agentscope"
    / "test-packages"
    / "interactive-data-modeling-mcp-windows.zip"
)
PACKAGE_ROOT_NAME = "interactive-data-modeling-mcp"
UPSTREAM_COMMIT = "b91abb0bbefff440c103865d57ba64a87e5aea4c"


def _copy_runtime(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    required = {
        "python.exe",
        "python3.dll",
        "python313.dll",
        "python313.zip",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
    }
    selected = [
        path
        for path in EMBEDDED_PYTHON.iterdir()
        if path.is_file()
        and (path.name in required or path.suffix.lower() in {".pyd", ".dll"})
    ]
    missing = sorted(required - {path.name for path in selected})
    if missing:
        raise FileNotFoundError(f"便携 Python 运行时缺少文件：{missing}")
    for source in selected:
        shutil.copy2(source, destination / source.name)
    (destination / "python313._pth").write_text(
        (
            "python313.zip\n"
            ".\n"
            "..\n"
            "..\\packages\n"
            "..\\packages\\win32\n"
            "..\\packages\\win32\\lib\n"
            "..\\packages\\pythonwin\n"
            "import site\n"
        ),
        encoding="utf-8",
    )


def _refresh_dependencies(cache: Path) -> None:
    expected_parent = (
        PROJECT_ROOT / "data" / "agentscope" / "build-cache"
    ).resolve()
    resolved = cache.resolve()
    if expected_parent not in resolved.parents:
        raise RuntimeError("依赖缓存目录必须位于 data/agentscope/build-cache 内")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=False)
    subprocess.run(
        [
            str(RUNTIME_PYTHON),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-compile",
            "--target",
            str(resolved),
            "--requirement",
            str(REQUIREMENTS),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )


def _copy_dependencies(cache: Path, destination: Path) -> None:
    if not cache.is_dir():
        raise FileNotFoundError(
            "数据分析 MCP 依赖缓存不存在，请先使用 "
            "--refresh-dependencies 构建一次",
        )
    cache_root = cache.resolve()

    def _ignore(directory: str, names: list[str]) -> set[str]:
        ignored = {
            name
            for name in names
            if name == "__pycache__" or name.endswith((".pyc", ".pyo"))
        }
        if Path(directory).resolve() == cache_root:
            ignored.update(
                name
                for name in names
                if name in {"tests", "test", "benchmarks", "docs", "examples"}
            )
        return ignored

    shutil.copytree(cache, destination, ignore=_ignore)


def _dependency_versions(cache: Path) -> dict[str, str]:
    versions: dict[str, str] = {}
    for distribution in importlib.metadata.distributions(path=[str(cache)]):
        name = str(distribution.metadata.get("Name") or "").strip()
        if name:
            versions[name] = distribution.version
    return dict(sorted(versions.items(), key=lambda item: item[0].lower()))


def build(
    output: Path,
    dependency_cache: Path,
    *,
    refresh_dependencies: bool = False,
) -> tuple[Path, str, dict[str, str], int]:
    output = output.resolve()
    dependency_cache = dependency_cache.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if refresh_dependencies:
        _refresh_dependencies(dependency_cache)
    dependencies = _dependency_versions(dependency_cache)
    if not dependencies:
        raise RuntimeError("依赖缓存为空，请使用 --refresh-dependencies 重新构建")

    with tempfile.TemporaryDirectory(prefix="interactive-data-modeling-mcp-") as raw:
        package_root = Path(raw) / PACKAGE_ROOT_NAME
        package_root.mkdir(parents=True)
        for name in (
            "mcp.json",
            "server.py",
            "README.md",
            "平台适配说明.md",
            "requirements-platform.txt",
        ):
            shutil.copy2(SOURCE_DIR / name, package_root / name)
        _copy_runtime(package_root / "runtime")
        packages = package_root / "packages"
        _copy_dependencies(dependency_cache, packages)
        shutil.copytree(
            SOURCE_DIR / "src" / "shield_prediction_mcp",
            packages / "shield_prediction_mcp",
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        prompt_dir = packages / "shield_prediction_mcp" / "prompts"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE_DIR / "prompts" / "build_model.md", prompt_dir)
        metadata = {
            "package": "interactive-data-modeling",
            "platform_version": json.loads(
                (SOURCE_DIR / "mcp.json").read_text(encoding="utf-8"),
            )["version"],
            "upstream_commit": UPSTREAM_COMMIT,
            "python": "3.13.14",
            "built_at": datetime.now(timezone.utc).isoformat(),
            "dependencies": dependencies,
        }
        (package_root / "BUILD-METADATA.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        files = [path for path in package_root.rglob("*") if path.is_file()]
        uncompressed = sum(path.stat().st_size for path in files)
        if uncompressed > 500 * 1024 * 1024:
            raise RuntimeError("MCP 解压后大小超过平台 500MB 上限")
        with zipfile.ZipFile(
            output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for path in sorted(files):
                archive.write(
                    path,
                    Path(PACKAGE_ROOT_NAME) / path.relative_to(package_root),
                )
    if output.stat().st_size > 200 * 1024 * 1024:
        output.unlink(missing_ok=True)
        raise RuntimeError("MCP ZIP 超过平台 200MB 上传上限")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return output, digest, dependencies, uncompressed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--dependency-cache",
        type=Path,
        default=DEFAULT_DEPENDENCY_CACHE,
    )
    parser.add_argument("--refresh-dependencies", action="store_true")
    args = parser.parse_args()
    output, digest, dependencies, uncompressed = build(
        args.output,
        args.dependency_cache,
        refresh_dependencies=args.refresh_dependencies,
    )
    print(f"已生成：{output}")
    print(f"ZIP 大小：{output.stat().st_size / 1024 / 1024:.2f} MB")
    print(f"解压大小：{uncompressed / 1024 / 1024:.2f} MB")
    print(f"依赖数量：{len(dependencies)}")
    print(f"SHA256：{digest}")


if __name__ == "__main__":
    main()
