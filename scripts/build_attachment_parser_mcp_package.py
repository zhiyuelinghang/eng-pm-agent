"""Build the dependency-complete fixed attachment parser package."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import shutil
import tempfile
import zipfile
from pathlib import Path

from packaging.requirements import Requirement


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "mcp-packages" / "attachment-parser"
EMBEDDED_PYTHON = PROJECT_ROOT / "python-3.13.14"
SITE_PACKAGES = EMBEDDED_PYTHON / "Lib" / "site-packages"
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "data"
    / "agentscope"
    / "test-packages"
    / "attachment-parser-mcp-windows.zip"
)
PACKAGE_ROOT_NAME = "attachment-parser-mcp"
ROOT_DISTRIBUTIONS = (
    "httpx",
    "openpyxl",
    "xlrd",
    "python-docx",
    "python-pptx",
    "pdfplumber",
    "pypdfium2",
    "rapidocr-onnxruntime",
)
_IGNORED_PARTS = frozenset(
    {
        "__pycache__",
        "tests",
        "test",
        "testing",
        "benchmarks",
        "docs",
        "examples",
    },
)
_IGNORED_SUFFIXES = frozenset(
    {
        ".c",
        ".h",
        ".lib",
        ".pc",
        ".pxd",
        ".pxi",
        ".pyc",
        ".pyi",
        ".pyo",
        ".pyx",
        ".typed",
    },
)


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
        and (
            path.name in required
            or path.suffix.lower() in {".pyd", ".dll"}
        )
    ]
    missing = sorted(required - {path.name for path in selected})
    if missing:
        raise FileNotFoundError(f"便携 Python 运行时缺少文件：{missing}")
    for source in selected:
        shutil.copy2(source, destination / source.name)
    (destination / "python313._pth").write_text(
        "python313.zip\n.\n..\n..\\packages\nimport site\n",
        encoding="utf-8",
    )


def _runtime_distributions() -> list[importlib.metadata.Distribution]:
    pending = list(ROOT_DISTRIBUTIONS)
    resolved: dict[str, importlib.metadata.Distribution] = {}
    while pending:
        requested_name = pending.pop()
        distribution = importlib.metadata.distribution(requested_name)
        canonical_name = str(distribution.metadata["Name"]).lower().replace("_", "-")
        if canonical_name in resolved:
            continue
        resolved[canonical_name] = distribution
        for raw_requirement in distribution.requires or []:
            requirement = Requirement(raw_requirement)
            if requirement.marker is not None and not requirement.marker.evaluate(
                {"extra": ""},
            ):
                continue
            pending.append(requirement.name)
    return [resolved[name] for name in sorted(resolved)]


def _copy_dependencies(destination: Path) -> list[str]:
    destination.mkdir(parents=True, exist_ok=True)
    copied: set[Path] = set()
    names: list[str] = []
    site_root = SITE_PACKAGES.resolve()
    for distribution in _runtime_distributions():
        names.append(str(distribution.metadata["Name"]))
        for member in distribution.files or []:
            relative = Path(member)
            if any(part.lower() in _IGNORED_PARTS for part in relative.parts):
                continue
            if relative.suffix.lower() in _IGNORED_SUFFIXES:
                continue
            dist_info_parts = [
                part for part in relative.parts if part.endswith(".dist-info")
            ]
            if dist_info_parts and relative.name != "METADATA":
                continue
            source = Path(distribution.locate_file(member)).resolve()
            if not source.is_file() or site_root not in source.parents:
                continue
            target_relative = source.relative_to(site_root)
            if target_relative in copied:
                continue
            copied.add(target_relative)
            target = destination / target_relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return names


def build(output: Path) -> tuple[Path, str, list[str]]:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="attachment-parser-mcp-") as raw_temp:
        package_root = Path(raw_temp) / PACKAGE_ROOT_NAME
        shutil.copytree(
            SOURCE_DIR,
            package_root,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        _copy_runtime(package_root / "runtime")
        distributions = _copy_dependencies(package_root / "packages")
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
    return output, digest, distributions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output, digest, distributions = build(args.output)
    print(f"已生成：{output}")
    print(f"大小：{output.stat().st_size / 1024 / 1024:.2f} MB")
    print(f"依赖：{'、'.join(distributions)}")
    print(f"SHA256：{digest}")


if __name__ == "__main__":
    main()
