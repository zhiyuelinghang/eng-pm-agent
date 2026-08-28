# -*- coding: utf-8 -*-
"""Platform-level, versioned skill package catalogue."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import stat
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Self

import frontmatter

from ..._logging import logger
from ...skill import Skill
from ._models import (
    SkillPackageRecord,
    SkillPackageVersionView,
    SkillPackageView,
    utc_now,
)


class SkillPackageError(ValueError):
    """Raised when a managed skill package is invalid."""


class SkillPackageConflictError(SkillPackageError):
    """Raised when an operation would publish a duplicate skill."""


class SkillRegistryManager:
    """Own managed skill artifacts and resolve agent assignments at runtime."""

    _INDEX_VERSION = 1
    _SKILL_FILE = "SKILL.md"
    _MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
    _MAX_UNCOMPRESSED_BYTES = 150 * 1024 * 1024
    _MAX_FILES = 2000
    _MAX_MARKDOWN_BYTES = 2 * 1024 * 1024

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.packages_dir = self.root_dir / "packages"
        self.staging_dir = self.root_dir / ".staging"
        self.index_path = self.root_dir / "index.json"
        self._records: dict[str, SkillPackageRecord] = {}
        self._versions: dict[tuple[str, int], SkillPackageRecord] = {}
        self._catalog_lock = asyncio.Lock()
        self._publish_lock = asyncio.Lock()

    async def __aenter__(self) -> Self:
        await asyncio.to_thread(self._prepare_directories)
        await self._load_index()
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def _prepare_directories(self) -> None:
        self.packages_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)

    async def _load_index(self) -> None:
        if not self.index_path.exists():
            return
        try:
            raw = await asyncio.to_thread(
                self.index_path.read_text,
                encoding="utf-8",
            )
            payload = json.loads(raw)
            records = {
                item["id"]: SkillPackageRecord.model_validate(item)
                for item in payload.get("packages", [])
            }
            versions = {
                (record.id, record.version): record
                for record in (
                    SkillPackageRecord.model_validate(item)
                    for item in payload.get("versions", [])
                )
            }
            for record in records.values():
                versions.setdefault((record.id, record.version), record)
        except Exception as exc:  # pylint: disable=broad-except
            raise RuntimeError(
                f"Failed to load skill registry index {self.index_path}: {exc}",
            ) from exc

        self._records = {
            package_id: record
            for package_id, record in records.items()
            if (self.root_dir / record.relative_dir).is_dir()
        }
        self._versions = {
            key: record
            for key, record in versions.items()
            if (self.root_dir / record.relative_dir).is_dir()
        }

    async def _save_index(self) -> None:
        payload = {
            "schema_version": self._INDEX_VERSION,
            "packages": [
                item.model_dump(mode="json")
                for item in sorted(self._records.values(), key=lambda row: row.id)
            ],
            "versions": [
                item.model_dump(mode="json")
                for item in sorted(
                    self._versions.values(),
                    key=lambda row: (row.id, row.version),
                )
            ],
        }
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)

        def _write() -> None:
            tmp_path = self.index_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            tmp_path.write_text(serialized, encoding="utf-8")
            os.replace(tmp_path, self.index_path)

        await asyncio.to_thread(_write)

    async def list_records(self) -> list[SkillPackageRecord]:
        async with self._catalog_lock:
            return [
                item.model_copy(deep=True)
                for item in sorted(
                    self._records.values(),
                    key=lambda row: (row.name.casefold(), row.id),
                )
            ]

    async def get_record(
        self,
        package_id: str,
        version: int | None = None,
    ) -> SkillPackageRecord | None:
        async with self._catalog_lock:
            record = (
                self._versions.get((package_id, version))
                if version is not None
                else self._records.get(package_id)
            )
            return record.model_copy(deep=True) if record is not None else None

    async def list_version_records(
        self,
        package_id: str,
    ) -> list[SkillPackageRecord]:
        async with self._catalog_lock:
            return [
                item.model_copy(deep=True)
                for item in sorted(
                    (
                        record
                        for (item_id, _), record in self._versions.items()
                        if item_id == package_id
                    ),
                    key=lambda row: row.version,
                    reverse=True,
                )
            ]

    async def list_views(
        self,
        assigned_ids: set[str] | None = None,
    ) -> list[SkillPackageView]:
        assigned = assigned_ids or set()
        views: list[SkillPackageView] = []
        for record in await self.list_records():
            name, description, markdown = await asyncio.to_thread(
                self._read_skill,
                record,
            )
            views.append(
                SkillPackageView(
                    id=record.id,
                    version=record.version,
                    name=name,
                    description=description,
                    markdown=markdown,
                    source=record.source,
                    assigned=record.id in assigned,
                    asset_count=await asyncio.to_thread(
                        self._asset_count,
                        record,
                    ),
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                ),
            )
        return views

    async def list_version_views(
        self,
        package_id: str,
    ) -> list[SkillPackageVersionView]:
        views: list[SkillPackageVersionView] = []
        for record in await self.list_version_records(package_id):
            views.append(
                SkillPackageVersionView(
                    package_id=record.id,
                    version=record.version,
                    name=record.name,
                    description=record.description,
                    source=record.source,
                    asset_count=await asyncio.to_thread(
                        self._asset_count,
                        record,
                    ),
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                ),
            )
        return views

    async def create_skill(
        self,
        *,
        name: str,
        description: str,
        markdown: str,
    ) -> SkillPackageRecord:
        """Create a pure ``SKILL.md`` package in the platform registry."""
        async with self._publish_lock:
            if await self._find_by_name(name.strip()) is not None:
                raise SkillPackageConflictError(
                    f"技能名称 {name.strip()!r} 已存在，请编辑现有技能。",
                )
            stage = self.staging_dir / uuid.uuid4().hex
            package_root = stage / "package"
            await asyncio.to_thread(package_root.mkdir, parents=True)
            try:
                await asyncio.to_thread(
                    self._write_skill,
                    package_root,
                    name,
                    description,
                    markdown,
                )
                return await self._publish_directory(
                    package_root,
                    source="editor",
                )
            finally:
                if stage.exists():
                    await asyncio.to_thread(shutil.rmtree, stage, True)

    async def update_skill(
        self,
        package_id: str,
        *,
        name: str,
        description: str,
        markdown: str,
    ) -> SkillPackageRecord:
        """Publish an edited skill as a new immutable package version."""
        async with self._publish_lock:
            current = await self.get_record(package_id)
            if current is None:
                raise SkillPackageError(f"技能包 {package_id!r} 不存在。")
            name_owner = await self._find_by_name(name.strip())
            if name_owner is not None and name_owner.id != package_id:
                raise SkillPackageConflictError(
                    f"技能名称 {name.strip()!r} 已被其他技能使用。",
                )
            stage = self.staging_dir / uuid.uuid4().hex
            package_root = stage / "package"
            source_dir = self.root_dir / current.relative_dir
            await asyncio.to_thread(shutil.copytree, source_dir, package_root)
            try:
                await asyncio.to_thread(
                    self._write_skill,
                    package_root,
                    name,
                    description,
                    markdown,
                )
                return await self._publish_directory(
                    package_root,
                    source="editor",
                    package_id=package_id,
                )
            finally:
                if stage.exists():
                    await asyncio.to_thread(shutil.rmtree, stage, True)

    async def install_archive(self, archive: BinaryIO) -> SkillPackageRecord:
        """Validate and publish a ZIP package containing one ``SKILL.md``."""
        async with self._publish_lock:
            stage = self.staging_dir / uuid.uuid4().hex
            await asyncio.to_thread(stage.mkdir, parents=True, exist_ok=False)
            try:
                package_root = await asyncio.to_thread(
                    self._extract_skill_package,
                    archive,
                    stage,
                )
                name, _, _ = await asyncio.to_thread(
                    self._parse_skill_path,
                    package_root / self._SKILL_FILE,
                )
                existing = await self._find_by_name(name)
                return await self._publish_directory(
                    package_root,
                    source="upload",
                    package_id=existing.id if existing is not None else None,
                )
            finally:
                if stage.exists():
                    await asyncio.to_thread(shutil.rmtree, stage, True)

    async def _publish_directory(
        self,
        package_root: Path,
        *,
        source: str,
        package_id: str | None = None,
    ) -> SkillPackageRecord:
        name, description, _ = await asyncio.to_thread(
            self._parse_skill_path,
            package_root / self._SKILL_FILE,
        )
        current = await self.get_record(package_id) if package_id else None
        if current is not None and current.name != name:
            other = await self._find_by_name(name)
            if other is not None and other.id != current.id:
                raise SkillPackageConflictError(
                    f"技能名称 {name!r} 已被其他技能使用。",
                )
        resolved_id = current.id if current is not None else self._new_id(name)
        version = current.version + 1 if current is not None else 1
        content_hash = await asyncio.to_thread(self._hash_tree, package_root)
        if current is not None and current.content_hash == content_hash:
            raise SkillPackageConflictError("技能内容没有变化，无需生成新版本。")

        relative_dir = Path("packages") / resolved_id / str(version)
        final_dir = (self.root_dir / relative_dir).resolve()
        if final_dir.exists():
            raise SkillPackageConflictError(
                f"技能 {name!r} 的版本 v{version} 已存在。",
            )
        await asyncio.to_thread(final_dir.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.move, str(package_root), str(final_dir))

        now = utc_now()
        record = SkillPackageRecord(
            id=resolved_id,
            version=version,
            name=name,
            description=description,
            relative_dir=relative_dir.as_posix(),
            source=source,
            content_hash=content_hash,
            created_at=current.created_at if current is not None else now,
            updated_at=now,
        )
        try:
            async with self._catalog_lock:
                previous = self._records.get(record.id)
                self._records[record.id] = record
                self._versions[(record.id, record.version)] = record
                try:
                    await self._save_index()
                except BaseException:
                    if previous is None:
                        self._records.pop(record.id, None)
                    else:
                        self._records[record.id] = previous
                    self._versions.pop((record.id, record.version), None)
                    raise
        except BaseException:
            if final_dir.exists():
                await asyncio.to_thread(shutil.rmtree, final_dir, True)
            raise
        return record.model_copy(deep=True)

    async def delete_package(self, package_id: str) -> bool:
        """Delete every retained version of an unassigned skill package."""
        async with self._publish_lock:
            async with self._catalog_lock:
                current = self._records.pop(package_id, None)
                if current is None:
                    return False
                removed_versions = {
                    key: value
                    for key, value in self._versions.items()
                    if key[0] == package_id
                }
                for key in removed_versions:
                    self._versions.pop(key, None)
                try:
                    await self._save_index()
                except BaseException:
                    self._records[package_id] = current
                    self._versions.update(removed_versions)
                    raise
            package_dir = self.packages_dir / package_id
            if package_dir.exists():
                await asyncio.to_thread(shutil.rmtree, package_dir, True)
            return True

    async def get_assigned_skills(self, package_ids: list[str]) -> list[Skill]:
        """Resolve current assigned versions for one agent invocation."""
        skills: list[Skill] = []
        for package_id in dict.fromkeys(package_ids):
            record = await self.get_record(package_id)
            if record is None:
                logger.warning("Assigned skill package %r is missing.", package_id)
                continue
            try:
                name, description, markdown = await asyncio.to_thread(
                    self._read_skill,
                    record,
                )
                package_dir = self.root_dir / record.relative_dir
                updated_at = await asyncio.to_thread(
                    (package_dir / self._SKILL_FILE).stat,
                )
                skills.append(
                    Skill(
                        name=name,
                        description=description,
                        dir=str(package_dir),
                        markdown=markdown,
                        updated_at=updated_at.st_mtime,
                    ),
                )
            except (OSError, SkillPackageError) as exc:
                logger.warning(
                    "Unable to load managed skill %r: %s",
                    package_id,
                    exc,
                )
        return skills

    async def build_version_archive(
        self,
        package_id: str,
        version: int,
    ) -> Path:
        """Build a temporary ZIP archive for one retained package version."""
        record = await self.get_record(package_id, version)
        if record is None:
            raise SkillPackageError("指定的技能版本不存在。")
        source_dir = self.root_dir / record.relative_dir
        output = self.staging_dir / (
            f"download-{package_id}-v{version}-{uuid.uuid4().hex}.zip"
        )

        def _build() -> None:
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle:
                for path in source_dir.rglob("*"):
                    if path.is_file():
                        bundle.write(path, path.relative_to(source_dir).as_posix())

        await asyncio.to_thread(_build)
        return output

    async def _find_by_name(self, name: str) -> SkillPackageRecord | None:
        normalized = name.strip().casefold()
        for record in await self.list_records():
            if record.name.casefold() == normalized:
                return record
        return None

    @staticmethod
    def _new_id(name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:48]
        prefix = slug or "skill"
        return f"{prefix}-{uuid.uuid4().hex[:12]}"

    def _write_skill(
        self,
        package_root: Path,
        name: str,
        description: str,
        markdown: str,
    ) -> None:
        name = name.strip()
        description = description.strip()
        markdown = markdown.strip()
        if not name or not description or not markdown:
            raise SkillPackageError("技能名称、简介和执行说明均不能为空。")
        if len(name) > 100 or len(description) > 4000:
            raise SkillPackageError("技能名称或简介超过长度限制。")
        if "\x00" in name + description + markdown:
            raise SkillPackageError("技能内容不能包含 NUL 字符。")
        encoded = markdown.encode("utf-8")
        if len(encoded) > self._MAX_MARKDOWN_BYTES:
            raise SkillPackageError("SKILL.md 超过 2 MB 限制。")
        document = frontmatter.Post(
            markdown,
            name=name,
            description=description,
        )
        (package_root / self._SKILL_FILE).write_text(
            frontmatter.dumps(document),
            encoding="utf-8",
        )
        self._parse_skill_path(package_root / self._SKILL_FILE)

    def _read_skill(
        self,
        record: SkillPackageRecord,
    ) -> tuple[str, str, str]:
        return self._parse_skill_path(
            self.root_dir / record.relative_dir / self._SKILL_FILE,
        )

    def _parse_skill_path(self, skill_path: Path) -> tuple[str, str, str]:
        if not skill_path.is_file():
            raise SkillPackageError("技能包缺少 SKILL.md。")
        if skill_path.stat().st_size > self._MAX_MARKDOWN_BYTES:
            raise SkillPackageError("SKILL.md 超过 2 MB 限制。")
        try:
            document = frontmatter.loads(skill_path.read_text(encoding="utf-8"))
        except Exception as exc:  # pylint: disable=broad-except
            raise SkillPackageError(f"SKILL.md 无法解析：{exc}") from exc
        name = str(document.get("name") or "").strip()
        description = str(document.get("description") or "").strip()
        markdown = document.content.strip()
        if not name or not description or not markdown:
            raise SkillPackageError(
                "SKILL.md 必须包含 name、description 和执行说明正文。",
            )
        if len(name) > 100 or len(description) > 4000:
            raise SkillPackageError("SKILL.md 的 name 或 description 超过长度限制。")
        return name, description, markdown

    def _extract_skill_package(self, archive: BinaryIO, stage: Path) -> Path:
        try:
            archive.seek(0, os.SEEK_END)
            archive_size = archive.tell()
            archive.seek(0)
        except (AttributeError, OSError):
            archive_size = 0
        if archive_size > self._MAX_ARCHIVE_BYTES:
            raise SkillPackageError("技能包超过 50 MB 上传限制。")
        try:
            with zipfile.ZipFile(archive) as bundle:
                infos = bundle.infolist()
                if not infos:
                    raise SkillPackageError("技能包为空。")
                if len(infos) > self._MAX_FILES:
                    raise SkillPackageError("技能包文件数量超过 2000 个。")
                if sum(item.file_size for item in infos) > self._MAX_UNCOMPRESSED_BYTES:
                    raise SkillPackageError("技能包解压后超过 150 MB 限制。")
                for info in infos:
                    self._extract_member(bundle, info, stage)
        except zipfile.BadZipFile as exc:
            raise SkillPackageError("上传文件不是有效的 ZIP 技能包。") from exc
        except SkillPackageError:
            raise
        except (OSError, RuntimeError, NotImplementedError) as exc:
            raise SkillPackageError(f"技能包无法解压：{exc}") from exc

        skill_files = [
            path
            for path in stage.rglob(self._SKILL_FILE)
            if "__MACOSX" not in path.parts
        ]
        if len(skill_files) != 1:
            raise SkillPackageError("技能包必须且只能包含一个 SKILL.md。")
        self._parse_skill_path(skill_files[0])
        return skill_files[0].parent

    @staticmethod
    def _extract_member(
        bundle: zipfile.ZipFile,
        info: zipfile.ZipInfo,
        stage: Path,
    ) -> None:
        normalized = info.filename.replace("\\", "/")
        member_path = PurePosixPath(normalized)
        if (
            member_path.is_absolute()
            or ".." in member_path.parts
            or "\x00" in normalized
        ):
            raise SkillPackageError(f"技能包包含不安全路径：{info.filename!r}")
        unix_mode = info.external_attr >> 16
        if stat.S_ISLNK(unix_mode):
            raise SkillPackageError("技能包不允许包含符号链接。")
        target = (stage / Path(*member_path.parts)).resolve()
        if stage != target and stage not in target.parents:
            raise SkillPackageError(f"技能包包含不安全路径：{info.filename!r}")
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        with bundle.open(info) as source, target.open("wb") as destination:
            shutil.copyfileobj(source, destination)

    def _hash_tree(self, package_root: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(item for item in package_root.rglob("*") if item.is_file()):
            digest.update(path.relative_to(package_root).as_posix().encode("utf-8"))
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
        return digest.hexdigest()

    def _asset_count(self, record: SkillPackageRecord) -> int:
        package_dir = self.root_dir / record.relative_dir
        return sum(
            1
            for path in package_dir.rglob("*")
            if path.is_file() and path.name != self._SKILL_FILE
        )
