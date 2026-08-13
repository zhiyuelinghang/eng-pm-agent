# -*- coding: utf-8 -*-
"""Platform-level MCP package catalogue and session runtime manager."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import stat
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from collections.abc import Iterable
from typing import BinaryIO, Self

from ..._logging import logger
from ...mcp import MCPClient, StdioMCPConfig
from ._models import (
    MCPPackageManifest,
    MCPPackageRecord,
    MCPPackageTool,
    MCPPackageVersionView,
    MCPPackageView,
    PROJECT_INITIALIZATION_VALIDATION_CAPABILITY,
    utc_now,
)


class MCPPackageError(ValueError):
    """Raised when an uploaded package is invalid or cannot be verified."""


class MCPPackageConflictError(MCPPackageError):
    """Raised when the same immutable package version already exists."""


class MCPRuntimeCapacityError(RuntimeError):
    """Raised when the configured active MCP process limit is reached."""


@dataclass
class _RuntimeEntry:
    client: MCPClient
    version: str
    last_access: float
    stop_event: asyncio.Event
    owner_task: asyncio.Task[None]


class MCPRegistryManager:
    """Own uploaded packages and per-session STDIO MCP processes.

    The package artifact is global and immutable per version.  Runtime
    clients are keyed by ``(session_id, package_id)`` so the management UI and
    engineering platform can use the same published package without sharing
    process state between conversations.
    """

    _INDEX_VERSION = 2
    _MANIFEST_NAME = "mcp.json"
    _MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
    _MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
    _ENV_PASSTHROUGH = (
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "HOME",
        "USERPROFILE",
        "LANG",
        "LC_ALL",
    )

    def __init__(
        self,
        root_dir: str | Path,
        *,
        idle_ttl: float = 3600.0,
        max_active_instances: int = 128,
        sweep_interval: float = 60.0,
        system_tool_package_ids: Iterable[str] = (),
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.packages_dir = self.root_dir / "packages"
        self.state_dir = self.root_dir / "state"
        self.staging_dir = self.root_dir / ".staging"
        self.index_path = self.root_dir / "index.json"
        self.idle_ttl = max(60.0, idle_ttl)
        self.max_active_instances = max(1, max_active_instances)
        self.sweep_interval = max(10.0, sweep_interval)
        self.system_tool_package_ids = frozenset(
            package_id.strip()
            for package_id in system_tool_package_ids
            if package_id.strip()
        )

        self._records: dict[str, MCPPackageRecord] = {}
        self._versions: dict[tuple[str, str], MCPPackageRecord] = {}
        self._catalog_lock = asyncio.Lock()
        self._install_lock = asyncio.Lock()
        self._runtime_lock = asyncio.Lock()
        self._runtime_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._runtime: dict[tuple[str, str], _RuntimeEntry] = {}
        self._starting: set[tuple[str, str]] = set()
        self._sweeper: asyncio.Task[None] | None = None

    async def __aenter__(self) -> Self:
        await asyncio.to_thread(self._prepare_directories)
        await self._load_index()
        self._sweeper = asyncio.create_task(
            self._sweep_loop(),
            name="managed-mcp-runtime-sweeper",
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._sweeper is not None:
            self._sweeper.cancel()
            await asyncio.gather(self._sweeper, return_exceptions=True)
            self._sweeper = None
        await self.close_all()

    def _prepare_directories(self) -> None:
        self.packages_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
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
            records: dict[str, MCPPackageRecord] = {}
            for item in payload.get("packages", []):
                records[item["id"]] = MCPPackageRecord.model_validate(item)
            version_items = payload.get("versions")
            if not isinstance(version_items, list):
                version_items = list(payload.get("packages", []))
            versions: dict[tuple[str, str], MCPPackageRecord] = {}
            for item in version_items:
                record = MCPPackageRecord.model_validate(item)
                versions[(record.id, record.manifest.version)] = record
            for record in records.values():
                versions.setdefault(
                    (record.id, record.manifest.version),
                    record,
                )
        except Exception as exc:  # pylint: disable=broad-except
            raise RuntimeError(
                f"Failed to load MCP registry index {self.index_path}: {exc}",
            ) from exc

        missing = [
            package_id
            for package_id, record in records.items()
            if not (self.root_dir / record.relative_dir).is_dir()
        ]
        for package_id in missing:
            logger.warning(
                "Skipping MCP package %r because its package directory is missing.",
                package_id,
            )
            records.pop(package_id, None)
        missing_versions = [
            key
            for key, record in versions.items()
            if not (self.root_dir / record.relative_dir).is_dir()
        ]
        for key in missing_versions:
            logger.warning(
                "Skipping MCP package version %r %r because its package "
                "directory is missing.",
                key[0],
                key[1],
            )
            versions.pop(key, None)
        self._records = records
        self._versions = versions

    async def _save_index(self) -> None:
        payload = {
            "schema_version": self._INDEX_VERSION,
            "packages": [
                record.model_dump(mode="json")
                for record in sorted(
                    self._records.values(),
                    key=lambda item: item.id,
                )
            ],
            "versions": [
                record.model_dump(mode="json")
                for record in sorted(
                    self._versions.values(),
                    key=lambda item: (item.id, item.manifest.version),
                )
            ],
        }
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)

        def _write() -> None:
            tmp_path = self.index_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            tmp_path.write_text(serialized, encoding="utf-8")
            os.replace(tmp_path, self.index_path)

        await asyncio.to_thread(_write)

    async def list_records(self) -> list[MCPPackageRecord]:
        async with self._catalog_lock:
            return [
                record.model_copy(deep=True)
                for record in sorted(
                    self._records.values(),
                    key=lambda item: (
                        item.manifest.display_name.casefold(),
                        item.id,
                    ),
                )
            ]

    async def get_record(
        self,
        package_id: str,
        version: str | None = None,
    ) -> MCPPackageRecord | None:
        async with self._catalog_lock:
            record = (
                self._versions.get((package_id, version))
                if version is not None
                else self._records.get(package_id)
            )
            if record is None and version is not None:
                current = self._records.get(package_id)
                if current is not None and current.manifest.version == version:
                    record = current
            return record.model_copy(deep=True) if record is not None else None

    async def list_version_records(
        self,
        package_id: str | None = None,
    ) -> list[MCPPackageRecord]:
        """Return every retained immutable version, newest upload first."""
        async with self._catalog_lock:
            records = list(self._versions.values())
            for current in self._records.values():
                if (current.id, current.manifest.version) not in self._versions:
                    records.append(current)
            if package_id is not None:
                records = [item for item in records if item.id == package_id]
            return [
                item.model_copy(deep=True)
                for item in sorted(
                    records,
                    key=lambda item: item.updated_at,
                    reverse=True,
                )
            ]

    async def list_version_views(
        self,
        *,
        capability: str | None = None,
    ) -> list[MCPPackageVersionView]:
        """Return retained versions, optionally limited to one platform slot."""
        records = await self.list_version_records()
        if capability is not None:
            records = [
                record
                for record in records
                if capability in record.manifest.platform_capabilities
            ]
        async with self._runtime_lock:
            counts: dict[tuple[str, str], int] = {}
            for (_, package_id), entry in self._runtime.items():
                if entry.owner_task.done() or not entry.client.is_connected:
                    continue
                key = (package_id, entry.version)
                counts[key] = counts.get(key, 0) + 1
        return [
            MCPPackageVersionView.from_record(
                record,
                active_instances=counts.get(
                    (record.id, record.manifest.version),
                    0,
                ),
            )
            for record in records
        ]

    async def list_views(
        self,
        assigned_ids: set[str] | None = None,
    ) -> list[MCPPackageView]:
        """Return only packages that an agent is allowed to assign.

        Packages registered as system tools deliberately stay out of the MCP
        assignment catalogue.  They are fixed platform capabilities and are
        exposed through the read-only system-tool catalogue instead.
        """
        assigned = assigned_ids or set()
        records = [
            record
            for record in await self.list_records()
            if record.id not in self.system_tool_package_ids
            and PROJECT_INITIALIZATION_VALIDATION_CAPABILITY
            not in record.manifest.platform_capabilities
        ]
        async with self._runtime_lock:
            counts: dict[str, int] = {}
            for (_, package_id), entry in self._runtime.items():
                if entry.owner_task.done() or not entry.client.is_connected:
                    continue
                counts[package_id] = counts.get(package_id, 0) + 1
        return [
            MCPPackageView.from_record(
                record,
                assigned=record.id in assigned,
                active_instances=counts.get(record.id, 0),
            )
            for record in records
        ]

    async def list_system_tool_records(self) -> list[MCPPackageRecord]:
        """Return installed packages that provide fixed system tools."""
        return [
            record
            for record in await self.list_records()
            if record.id in self.system_tool_package_ids
        ]

    async def get_platform_client(
        self,
        package_id: str,
        *,
        runtime_id: str,
        version: str | None = None,
    ) -> MCPClient:
        """Return a reusable MCP client owned by a trusted platform flow.

        Platform runtimes are deliberately separate from agent sessions. They
        can execute only through narrow service routes that select both the
        package capability and tool name; this method does not expose a
        general-purpose MCP execution gateway.
        """
        record = await self.get_record(package_id, version)
        if record is None:
            raise MCPPackageError(f"MCP package {package_id!r} is not installed.")
        return await self._get_or_start_client(
            record,
            user_id="platform-service",
            agent_id="platform-service",
            session_id=f"platform-{runtime_id}",
        )

    def is_system_tool_package(self, package_id: str) -> bool:
        """Whether ``package_id`` is managed as a fixed global capability."""
        return package_id in self.system_tool_package_ids

    async def install_archive(
        self,
        archive: BinaryIO,
        *,
        allow_system_tool_package: bool = False,
    ) -> MCPPackageRecord:
        """Validate, probe and publish one dependency-complete ZIP package.

        Fixed system-tool packages can only be updated by an explicit trusted
        maintenance caller.  The ordinary management upload path deliberately
        leaves ``allow_system_tool_package`` disabled.
        """
        async with self._install_lock:
            stage = self.staging_dir / uuid.uuid4().hex
            await asyncio.to_thread(stage.mkdir, parents=True, exist_ok=False)
            published = False
            moved_to_final = False
            final_dir: Path | None = None
            try:
                package_root, manifest = await asyncio.to_thread(
                    self._extract_and_read_manifest,
                    archive,
                    stage,
                )
                if (
                    manifest.name in self.system_tool_package_ids
                    and not allow_system_tool_package
                ):
                    raise MCPPackageError(
                        f"「{manifest.display_name}」是平台固定系统工具，"
                        "不能在智能体管理端上传或替换。",
                    )
                existing = await self.get_record(manifest.name)
                if (
                    existing is not None
                    and set(existing.manifest.platform_capabilities)
                    != set(manifest.platform_capabilities)
                ):
                    raise MCPPackageError(
                        f"MCP {manifest.name!r} cannot change platform "
                        "capabilities between versions.",
                    )
                existing_version = await self.get_record(
                    manifest.name,
                    manifest.version,
                )
                if existing_version is not None:
                    raise MCPPackageConflictError(
                        f"MCP {manifest.name!r} version "
                        f"{manifest.version!r} already exists.",
                    )

                tools = await self._probe_package(package_root, manifest)
                relative_dir = Path("packages") / manifest.name / manifest.version
                final_dir = (self.root_dir / relative_dir).resolve()
                if final_dir.exists():
                    raise MCPPackageConflictError(
                        f"MCP {manifest.name!r} version "
                        f"{manifest.version!r} already exists.",
                    )
                await asyncio.to_thread(
                    final_dir.parent.mkdir,
                    parents=True,
                    exist_ok=True,
                )
                await asyncio.to_thread(shutil.move, str(package_root), str(final_dir))
                moved_to_final = True

                now = utc_now()
                record = MCPPackageRecord(
                    id=manifest.name,
                    manifest=manifest,
                    relative_dir=relative_dir.as_posix(),
                    tools=tools,
                    created_at=existing.created_at if existing is not None else now,
                    updated_at=now,
                )
                async with self._catalog_lock:
                    previous = self._records.get(record.id)
                    version_key = (record.id, record.manifest.version)
                    previous_version = self._versions.get(version_key)
                    self._records[record.id] = record
                    self._versions[version_key] = record
                    try:
                        await self._save_index()
                    except BaseException:
                        if previous is None:
                            self._records.pop(record.id, None)
                        else:
                            self._records[record.id] = previous
                        if previous_version is None:
                            self._versions.pop(version_key, None)
                        else:
                            self._versions[version_key] = previous_version
                        raise
                published = True
                return record.model_copy(deep=True)
            finally:
                # After publication only the staging wrapper remains; before
                # publication this also removes rejected or failed packages.
                if stage.exists():
                    await asyncio.to_thread(shutil.rmtree, stage, True)
                if (
                    moved_to_final
                    and not published
                    and final_dir is not None
                    and final_dir.exists()
                ):
                    await asyncio.to_thread(shutil.rmtree, final_dir, True)
                if published:
                    logger.info("Published managed MCP package from uploaded archive.")

    def _extract_and_read_manifest(
        self,
        archive: BinaryIO,
        stage: Path,
    ) -> tuple[Path, MCPPackageManifest]:
        try:
            archive.seek(0, os.SEEK_END)
            archive_size = archive.tell()
            archive.seek(0)
        except (AttributeError, OSError):
            archive_size = 0
        if archive_size > self._MAX_ARCHIVE_BYTES:
            raise MCPPackageError("MCP package exceeds the 200 MB upload limit.")

        try:
            with zipfile.ZipFile(archive) as bundle:
                infos = bundle.infolist()
                if not infos:
                    raise MCPPackageError("MCP package is empty.")
                if sum(info.file_size for info in infos) > self._MAX_UNCOMPRESSED_BYTES:
                    raise MCPPackageError(
                        "MCP package expands beyond the 500 MB limit.",
                    )

                for info in infos:
                    self._extract_member(bundle, info, stage)
        except zipfile.BadZipFile as exc:
            raise MCPPackageError(
                "Uploaded MCP package is not a valid ZIP archive.",
            ) from exc
        except MCPPackageError:
            raise
        except (OSError, RuntimeError, NotImplementedError) as exc:
            raise MCPPackageError(
                f"MCP package could not be extracted: {exc}",
            ) from exc

        manifests = [
            path
            for path in stage.rglob(self._MANIFEST_NAME)
            if "__MACOSX" not in path.parts
        ]
        if len(manifests) != 1:
            raise MCPPackageError(
                "MCP package must contain exactly one mcp.json manifest.",
            )
        manifest_path = manifests[0]
        try:
            manifest = MCPPackageManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8"),
            )
        except Exception as exc:  # pylint: disable=broad-except
            raise MCPPackageError(f"Invalid mcp.json manifest: {exc}") from exc
        return manifest_path.parent, manifest

    def _extract_member(
        self,
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
            raise MCPPackageError(f"Unsafe path in MCP package: {info.filename!r}")
        unix_mode = info.external_attr >> 16
        if stat.S_ISLNK(unix_mode):
            raise MCPPackageError("Symbolic links are not allowed in MCP packages.")
        target = (stage / Path(*member_path.parts)).resolve()
        if stage != target and stage not in target.parents:
            raise MCPPackageError(f"Unsafe path in MCP package: {info.filename!r}")
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        with bundle.open(info) as source, target.open("wb") as destination:
            shutil.copyfileobj(source, destination)
        if unix_mode:
            target.chmod(unix_mode & 0o777)

    def _resolve_command(self, package_dir: Path, command: str) -> str:
        command_path = Path(command)
        if command_path.is_absolute():
            raise MCPPackageError(
                "MCP command must be a relative executable path inside the "
                "uploaded package.",
            )
        candidate = (package_dir / command_path).resolve()
        if candidate.is_file():
            if package_dir != candidate and package_dir not in candidate.parents:
                raise MCPPackageError(
                    "MCP command must stay inside the package directory.",
                )
            return str(candidate)
        raise MCPPackageError(
            f"MCP command {command!r} does not exist inside the uploaded "
            "package; host PATH commands are not allowed.",
        )

    def _runtime_environment(
        self,
        manifest: MCPPackageManifest,
        *,
        user_id: str,
        agent_id: str,
        session_id: str,
        platform_agent_id: str | None = None,
        platform_session_id: str | None = None,
    ) -> dict[str, str]:
        env = {
            key: os.environ[key]
            for key in self._ENV_PASSTHROUGH
            if key in os.environ
        }
        env.update(manifest.env)
        # Direct database-file injection was removed in the structured-store
        # migration.  A stale uploaded manifest cannot re-enable it.
        env.pop("DOBBY_DATABASE_PATH", None)
        if {
            "dobby_database_interactions",
        } & set(manifest.platform_capabilities):
            gateway_url = os.getenv(
                "DOBBY_AGENT_TOOL_BASE_URL",
                "http://127.0.0.1:38430/api/internal/agent-tools",
            ).strip()
            gateway_token = (
                os.getenv("DOBBY_AGENT_TOOL_TOKEN", "").strip()
                or os.getenv("AGENTSCOPE_SERVICE_TOKEN", "").strip()
            )
            if gateway_url:
                env["DOBBY_AGENT_TOOL_BASE_URL"] = gateway_url
            if gateway_token:
                # Give the package only the dedicated gateway credential name;
                # never expose the broader AgentScope service-token variable.
                env["DOBBY_AGENT_TOOL_TOKEN"] = gateway_token
            database_api_url = os.getenv(
                "DOBBY_INTERNAL_API_BASE_URL",
                "",
            ).strip().rstrip("/")
            if not database_api_url and gateway_url.rstrip("/").endswith(
                "/agent-tools",
            ):
                database_api_url = (
                    gateway_url.rstrip("/").removesuffix("/agent-tools")
                )
            if database_api_url:
                env["DOBBY_DATABASE_INTERACTION_BASE_URL"] = (
                    database_api_url + "/database-interactions"
                )
        if manifest.name == "attachment-parser":
            # Attachment-parser MCP packages ship with usable defaults, while
            # deployments may redirect them to a private MinerU router without
            # rebuilding and re-uploading the immutable ZIP artifact.
            for key in (
                "MINERU_FILE_PARSE_URL",
                "MINERU_BACKEND",
                "MINERU_SERVER_URL",
                "MINERU_TIMEOUT_SECONDS",
            ):
                value = os.getenv(key, "").strip()
                if value:
                    env[key] = value
        env.update(
            {
                "AGENTSCOPE_USER_ID": user_id,
                "AGENTSCOPE_AGENT_ID": agent_id,
                "AGENTSCOPE_SESSION_ID": session_id,
                "DOBBY_PLATFORM_AGENT_ID": platform_agent_id or agent_id,
                "DOBBY_PLATFORM_SESSION_ID": platform_session_id or session_id,
            },
        )
        scope_source = "\0".join((user_id, agent_id, session_id))
        scope_id = hashlib.sha256(scope_source.encode("utf-8")).hexdigest()[:32]
        env["AGENTSCOPE_MCP_STATE_DIR"] = str(
            (self.state_dir / manifest.name / scope_id).resolve(),
        )
        return env

    def _build_client(
        self,
        record: MCPPackageRecord,
        *,
        user_id: str,
        agent_id: str,
        session_id: str,
        platform_agent_id: str | None = None,
        platform_session_id: str | None = None,
    ) -> MCPClient:
        package_dir = (self.root_dir / record.relative_dir).resolve()
        manifest = record.manifest
        return MCPClient(
            name=record.id,
            is_stateful=True,
            execution_timeout=manifest.execution_timeout,
            mcp_config=StdioMCPConfig(
                command=self._resolve_command(package_dir, manifest.command),
                args=manifest.args,
                env=self._runtime_environment(
                    manifest,
                    user_id=user_id,
                    agent_id=agent_id,
                    session_id=session_id,
                    platform_agent_id=platform_agent_id,
                    platform_session_id=platform_session_id,
                ),
                cwd=package_dir,
            ),
        )

    async def _probe_package(
        self,
        package_dir: Path,
        manifest: MCPPackageManifest,
    ) -> list[MCPPackageTool]:
        record = MCPPackageRecord(
            id=manifest.name,
            manifest=manifest,
            relative_dir=os.path.relpath(package_dir, self.root_dir),
        )
        client = self._build_client(
            record,
            user_id="probe",
            agent_id="probe",
            session_id=f"probe-{uuid.uuid4().hex}",
        )
        try:
            # ``MCPClient.connect`` keeps an AnyIO task-group context open for
            # the lifetime of a stateful connection. ``asyncio.wait_for``
            # would enter that context in a helper task and later close it in
            # another task, which AnyIO correctly rejects. ``timeout`` cancels
            # this same task and therefore preserves context ownership.
            async with asyncio.timeout(manifest.startup_timeout):
                await client.connect()
                raw_tools = await client.list_raw_tools()
            return [
                MCPPackageTool(
                    name=tool.name,
                    display_name=(
                        str(tool.title).strip()
                        if getattr(tool, "title", None)
                        else None
                    ),
                    description=tool.description or "",
                    input_schema=dict(tool.inputSchema or {}),
                    read_only=bool(
                        tool.annotations
                        and getattr(tool.annotations, "readOnlyHint", False)
                    ),
                )
                for tool in raw_tools
            ]
        except Exception as exc:  # pylint: disable=broad-except
            raise MCPPackageError(
                f"MCP package failed startup or tools/list verification: {exc}",
            ) from exc
        finally:
            if client.is_connected:
                await client.close()

    async def delete_package(self, package_id: str) -> bool:
        async with self._catalog_lock:
            record = self._records.pop(package_id, None)
            if record is None:
                return False
            version_keys = [
                key for key in self._versions if key[0] == package_id
            ]
            removed_versions = {
                key: self._versions.pop(key)
                for key in version_keys
            }
            try:
                await self._save_index()
            except BaseException:
                self._records[package_id] = record
                self._versions.update(removed_versions)
                raise
        await self.close_package_instances(package_id)
        package_home = self.packages_dir / package_id
        if package_home.exists():
            await asyncio.to_thread(shutil.rmtree, package_home, True)
        package_state = self.state_dir / package_id
        if package_state.exists():
            await asyncio.to_thread(shutil.rmtree, package_state, True)
        return True

    async def active_version_instances(
        self,
        package_id: str,
        version: str,
    ) -> int:
        """Count connected runtime processes for one immutable version."""
        async with self._runtime_lock:
            return sum(
                1
                for (_, runtime_package_id), entry in self._runtime.items()
                if runtime_package_id == package_id
                and entry.version == version
                and not entry.owner_task.done()
                and entry.client.is_connected
            )

    async def close_version_instances(
        self,
        package_id: str,
        version: str,
    ) -> None:
        """Close runtime processes that use one package version."""
        async with self._runtime_lock:
            keys = [
                key
                for key, entry in self._runtime.items()
                if key[1] == package_id and entry.version == version
            ]
            entries = [self._runtime.pop(key) for key in keys]
        await self._close_entries(entries)

    async def delete_version(self, package_id: str, version: str) -> bool:
        """Delete one retained version and keep the package's other versions."""
        async with self._catalog_lock:
            key = (package_id, version)
            record = self._versions.get(key)
            current = self._records.get(package_id)
            if record is None and current is not None:
                if current.manifest.version == version:
                    record = current
            if record is None:
                return False

            previous_current = current
            self._versions.pop(key, None)
            remaining = [
                item
                for (item_package_id, _), item in self._versions.items()
                if item_package_id == package_id
            ]
            if current is not None and current.manifest.version == version:
                if remaining:
                    self._records[package_id] = max(
                        remaining,
                        key=lambda item: item.updated_at,
                    )
                else:
                    self._records.pop(package_id, None)
            try:
                await self._save_index()
            except BaseException:
                self._versions[key] = record
                if previous_current is not None:
                    self._records[package_id] = previous_current
                raise

        await self.close_version_instances(package_id, version)
        version_dir = (self.root_dir / record.relative_dir).resolve()
        if version_dir.exists():
            await asyncio.to_thread(shutil.rmtree, version_dir, True)
        if not remaining:
            package_home = self.packages_dir / package_id
            if package_home.exists():
                await asyncio.to_thread(shutil.rmtree, package_home, True)
            package_state = self.state_dir / package_id
            if package_state.exists():
                await asyncio.to_thread(shutil.rmtree, package_state, True)
        return True

    async def build_version_archive(
        self,
        package_id: str,
        version: str,
    ) -> Path:
        """Create a temporary ZIP for downloading one immutable version."""
        record = await self.get_record(package_id, version)
        if record is None:
            raise MCPPackageError(
                f"MCP package {package_id!r} version {version!r} is not installed.",
            )
        package_dir = (self.root_dir / record.relative_dir).resolve()
        if not package_dir.is_dir():
            raise MCPPackageError("MCP package directory is missing.")
        archive_path = self.staging_dir / (
            f"download-{package_id}-{version}-{uuid.uuid4().hex}.zip"
        )

        def _write_archive() -> None:
            root_name = f"{package_id}-mcp"
            with zipfile.ZipFile(
                archive_path,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
            ) as bundle:
                for path in sorted(package_dir.rglob("*")):
                    if not path.is_file():
                        continue
                    relative = path.relative_to(package_dir)
                    if "__pycache__" in relative.parts or path.suffix == ".pyc":
                        continue
                    bundle.write(path, (Path(root_name) / relative).as_posix())

        await asyncio.to_thread(_write_archive)
        return archive_path

    async def get_session_clients(
        self,
        *,
        user_id: str,
        agent_id: str,
        session_id: str,
        package_ids: list[str],
        platform_agent_id: str | None = None,
        platform_session_id: str | None = None,
    ) -> list[MCPClient]:
        """Return session-isolated clients for assigned and system packages.

        Agent assignments apply only to ordinary MCP packages.  Installed
        system-tool packages are always added for every agent and cannot be
        disabled by legacy or current agent configuration.
        """
        all_records = {
            record.id: record
            for record in await self.list_records()
        }
        assigned_ids = list(dict.fromkeys(package_ids))
        requested_ids = list(
            dict.fromkeys(
                [
                    *assigned_ids,
                    *(
                        package_id
                        for package_id in sorted(self.system_tool_package_ids)
                        if package_id in all_records
                    ),
                ],
            ),
        )
        records = {
            package_id: all_records[package_id]
            for package_id in requested_ids
            if package_id in all_records
            and (
                package_id in self.system_tool_package_ids
                or PROJECT_INITIALIZATION_VALIDATION_CAPABILITY
                not in all_records[package_id].manifest.platform_capabilities
            )
        }
        missing = [
            package_id
            for package_id in assigned_ids
            if package_id not in records
        ]
        if missing:
            logger.warning(
                "Ignoring missing managed MCP package assignments for agent %s: %s",
                agent_id,
                missing,
            )

        await self._close_unassigned_session_entries(session_id, set(records))
        clients = await asyncio.gather(
            *(
                self._get_or_start_client(
                    record,
                    user_id=user_id,
                    agent_id=agent_id,
                    session_id=session_id,
                    platform_agent_id=platform_agent_id,
                    platform_session_id=platform_session_id,
                )
                for record in records.values()
            ),
        )
        return list(clients)

    async def _get_or_start_client(
        self,
        record: MCPPackageRecord,
        *,
        user_id: str,
        agent_id: str,
        session_id: str,
        platform_agent_id: str | None = None,
        platform_session_id: str | None = None,
    ) -> MCPClient:
        key = (session_id, record.id)
        async with self._runtime_lock:
            key_lock = self._runtime_locks.setdefault(key, asyncio.Lock())
        async with key_lock:
            stale: _RuntimeEntry | None = None
            async with self._runtime_lock:
                entry = self._runtime.get(key)
                if (
                    entry is not None
                    and entry.version == record.manifest.version
                    and entry.client.is_connected
                    and not entry.owner_task.done()
                ):
                    entry.last_access = time.monotonic()
                    return entry.client
                if entry is not None:
                    stale = self._runtime.pop(key)
                if (
                    len(self._runtime) + len(self._starting)
                    >= self.max_active_instances
                ):
                    raise MCPRuntimeCapacityError(
                        "Managed MCP active instance limit reached; try again "
                        "after an idle conversation is released.",
                    )
                self._starting.add(key)

            if stale is not None:
                await self._close_entries([stale])

            client = self._build_client(
                record,
                user_id=user_id,
                agent_id=agent_id,
                session_id=session_id,
                platform_agent_id=platform_agent_id,
                platform_session_id=platform_session_id,
            )
            try:
                ready: asyncio.Future[None] = (
                    asyncio.get_running_loop().create_future()
                )
                stop_event = asyncio.Event()
                owner_task = asyncio.create_task(
                    self._run_owned_client(
                        client,
                        ready=ready,
                        stop_event=stop_event,
                        startup_timeout=record.manifest.startup_timeout,
                    ),
                    name=f"managed-mcp-{record.id}-{session_id}",
                )
                try:
                    await ready
                except BaseException:
                    stop_event.set()
                    await asyncio.gather(owner_task, return_exceptions=True)
                    raise
                async with self._runtime_lock:
                    self._runtime[key] = _RuntimeEntry(
                        client=client,
                        version=record.manifest.version,
                        last_access=time.monotonic(),
                        stop_event=stop_event,
                        owner_task=owner_task,
                    )
                return client
            finally:
                async with self._runtime_lock:
                    self._starting.discard(key)

    async def _run_owned_client(
        self,
        client: MCPClient,
        *,
        ready: asyncio.Future[None],
        stop_event: asyncio.Event,
        startup_timeout: float,
    ) -> None:
        """Own one stateful MCP context from connect through close.

        The MCP SDK's STDIO transport keeps an AnyIO cancel scope open while
        connected, and AnyIO requires that scope to be closed by the same
        asyncio task that entered it. A dedicated owner task lets chat turns
        safely reuse the client while lifecycle operations merely signal that
        owner to close it.
        """
        try:
            async with asyncio.timeout(startup_timeout):
                await client.connect()
            ready.set_result(None)
            await stop_event.wait()
        except BaseException as exc:  # Includes event-loop cancellation.
            if not ready.done():
                ready.set_exception(exc)
            elif not stop_event.is_set():
                logger.warning(
                    "Managed MCP %r stopped unexpectedly: %s",
                    client.name,
                    exc,
                )
        finally:
            if client.is_connected:
                await client.close()

    async def _close_unassigned_session_entries(
        self,
        session_id: str,
        assigned_ids: set[str],
    ) -> None:
        async with self._runtime_lock:
            stale_keys = [
                key
                for key in self._runtime
                if key[0] == session_id and key[1] not in assigned_ids
            ]
            entries = [self._runtime.pop(key) for key in stale_keys]
        await self._close_entries(entries)

    async def close_session(self, session_id: str) -> None:
        async with self._runtime_lock:
            keys = [key for key in self._runtime if key[0] == session_id]
            entries = [self._runtime.pop(key) for key in keys]
        await self._close_entries(entries)

    async def close_package_instances(self, package_id: str) -> None:
        async with self._runtime_lock:
            keys = [key for key in self._runtime if key[1] == package_id]
            entries = [self._runtime.pop(key) for key in keys]
        await self._close_entries(entries)

    async def close_all(self) -> None:
        async with self._runtime_lock:
            entries = list(self._runtime.values())
            self._runtime.clear()
        await self._close_entries(entries)

    async def _close_entries(self, entries: list[_RuntimeEntry]) -> None:
        if not entries:
            return
        for entry in entries:
            entry.stop_event.set()
        await asyncio.gather(
            *(entry.owner_task for entry in entries),
            return_exceptions=True,
        )

    async def _sweep_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.sweep_interval)
                cutoff = time.monotonic() - self.idle_ttl
                async with self._runtime_lock:
                    stale_keys = [
                        key
                        for key, entry in self._runtime.items()
                        if entry.last_access < cutoff
                        or entry.owner_task.done()
                    ]
                    entries = [self._runtime.pop(key) for key in stale_keys]
                await self._close_entries(entries)
        except asyncio.CancelledError:
            raise
