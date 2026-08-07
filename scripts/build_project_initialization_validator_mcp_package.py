"""Build the dependency-complete project-initialization validator MCP."""
from __future__ import annotations

import argparse
import hashlib
import shutil
import tempfile
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "mcp-packages" / "project-initialization-validator"
EMBEDDED_PYTHON = PROJECT_ROOT / "python-3.13.14"
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "data"
    / "agentscope"
    / "test-packages"
    / "project-initialization-validator-mcp-windows.zip"
)
PACKAGE_ROOT_NAME = "project-initialization-validator-mcp"


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
        "python313.zip\n.\n..\nimport site\n",
        encoding="utf-8",
    )


def build(output: Path) -> tuple[Path, str]:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="project-initialization-validator-mcp-",
    ) as raw_temp:
        package_root = Path(raw_temp) / PACKAGE_ROOT_NAME
        shutil.copytree(
            SOURCE_DIR,
            package_root,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        _copy_runtime(package_root / "runtime")
        files = [path for path in package_root.rglob("*") if path.is_file()]
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
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return output, digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output, digest = build(args.output)
    print(f"已生成：{output}")
    print(f"大小：{output.stat().st_size / 1024 / 1024:.2f} MB")
    print(f"SHA256：{digest}")


if __name__ == "__main__":
    main()
