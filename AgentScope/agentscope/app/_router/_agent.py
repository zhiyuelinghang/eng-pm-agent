# -*- coding: utf-8 -*-
"""Agent router — CRUD endpoints for agent configurations."""
import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
import hashlib
from html import unescape
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import time
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from ...agent import ContextConfig, ReActConfig
from ..._utils._common import _flatten_json_schema
from ..access import ResourceKind
from ..deps import (
    get_current_user_id,
    get_mcp_registry_manager,
    get_resource_access_service,
    get_session_service,
    get_storage,
)
from ._schema import (
    AgentSchemaResponse,
    AgentSchemaV2Response,
    ListAgentsResponse,
    CreateAgentRequest,
    CreateAgentResponse,
    PlatformAgentCatalogItem,
    PlatformAgentCatalogResponse,
    PlatformSettingsResponse,
    MemoryInfrastructureResponse,
    MemorySettingsResponse,
    ResetMemorySettingsRequest,
    UpdateMemorySettingsRequest,
    ListWeKnoraKnowledgeBasesResponse,
    ListWeKnoraKnowledgeResponse,
    TestWeKnoraConnectionRequest,
    TestWeKnoraConnectionResponse,
    UpdateWeKnoraConnectionRequest,
    WeKnoraApiKeyResponse,
    WeKnoraConnectionResponse,
    WeKnoraKnowledgeBaseItem,
    WeKnoraKnowledgeItem,
    WeKnoraFolderItem,
    WeKnoraFolderTreeResponse,
    CreateWeKnoraFolderRequest,
    UpdateWeKnoraFolderRequest,
    MoveWeKnoraKnowledgeRequest,
    SearchWeKnoraKnowledgeRequest,
    SearchWeKnoraKnowledgeResponse,
    WeKnoraSearchReference,
    CreateWeKnoraUrlKnowledgeRequest,
    WeKnoraKnowledgeMutationResponse,
    AskWeKnoraAgentRequest,
    AskWeKnoraAgentResponse,
    CreateWeKnoraAgentSessionRequest,
    WeKnoraAgentSessionResponse,
    StopWeKnoraAgentSessionRequest,
    StopWeKnoraAgentSessionResponse,
    ListWeKnoraProjectBindingsResponse,
    UpdateWeKnoraProjectBindingRequest,
    WeKnoraProjectBindingItem,
    UpdatePlatformSettingsRequest,
    UpdateAgentRequest,
)
from .._service import (
    AgentView,
    ResourceAccessService,
    SessionService,
    build_credential_model_catalog,
    normalize_credential_model_parameters,
)
from ..storage import (
    AgentData,
    AgentModelPolicy,
    AgentRecord,
    ChatModelConfig,
    MemorySettingsData,
    PlatformMCPVersionBinding,
    PlatformSettingsData,
    PlatformSettingsRecord,
    StorageBase,
    WeKnoraConnectionConfig,
)
from ..mcp_registry import (
    MCPPackageRecord,
    MCPRegistryManager,
    PROJECT_INITIALIZATION_VALIDATION_CAPABILITY,
)
from ...credential import CredentialFactory


logger = logging.getLogger(__name__)

try:
    _WEKNORA_JSON_MAX_CONCURRENCY = max(
        1,
        int(os.getenv("WEKNORA_JSON_MAX_CONCURRENCY", "1")),
    )
except ValueError:
    _WEKNORA_JSON_MAX_CONCURRENCY = 1

# The deployed WeKnora gateway becomes unstable when the engineering UI opens
# several knowledge bases at once. Queue JSON calls in this process instead
# of letting one page load create a burst of upstream requests. The limit is
# configurable for deployments that have verified a higher safe capacity.
_weknora_json_request_gate = asyncio.Semaphore(
    _WEKNORA_JSON_MAX_CONCURRENCY,
)
_WEKNORA_DIAGNOSTIC_BODY_BYTES = 64 * 1024
# Some WeKnora versions send ``session_title`` before the answer, while the
# integration document shows it after the final answer chunk.  Once the answer
# is complete, keep the stream open briefly for optional trailing metadata, but
# never impose a deadline while the answer itself is still being generated.
_WEKNORA_POST_ANSWER_METADATA_GRACE_SECONDS = 3.0
_WEKNORA_INLINE_CITATION_RE = re.compile(
    r"<kb\b(?P<attributes>[^>]*)/?>",
    flags=re.IGNORECASE | re.DOTALL,
)
_WEKNORA_INLINE_CITATION_ATTRIBUTE_RE = re.compile(
    r"\b(?P<name>doc|chunk_id|kb_id)\s*=\s*"
    r"(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
    flags=re.IGNORECASE | re.DOTALL,
)
_WEKNORA_WIKI_SUMMARY_REFERENCE_RE = re.compile(
    r"\[\[summary/(?P<knowledge_id>[0-9a-f][0-9a-f-]{7,})\|"
    r"(?P<title>[^\]\r\n]+)\]\]",
    flags=re.IGNORECASE,
)
_WEKNORA_SOURCE_TOOL_NAMES = {
    "browse_full_document",
    "get_knowledge",
    "get_knowledge_chunks",
    "grep_chunks",
    "list_knowledge_chunks",
    "read_knowledge",
    "wiki_read_page",
    "wiki_search",
}
_weknora_diagnostic_logger: logging.Logger | None = None

# The stop endpoint can be served by a different worker, so this registry is
# only a fast path.  The authoritative fallback always reads the active
# assistant message from WeKnora itself.
_active_weknora_message_ids: dict[str, str] = {}

# WeKnora creates missing path segments from the upload's ``folder_path``.
# This empty reserved marker keeps such a path alive without contributing
# document content.  Every public adapter response removes it again.
# WeKnora validates the extension before it persists a file.  Keep the
# reserved marker name distinctive, but end it in a format accepted by the
# current service.  The payload stays exactly zero bytes and multimodal
# processing remains disabled.
WEKNORA_FOLDER_PLACEHOLDER_FILENAME = "__dobby_folder__.md"
WEKNORA_FOLDER_PLACEHOLDER_CONTENT_TYPE = "text/markdown"

agent_router = APIRouter(
    prefix="/agent",
    tags=["agent"],
    responses={404: {"description": "Not found"}},
)


def _get_weknora_diagnostic_logger() -> logging.Logger:
    """Return the private rotating log used for malformed upstream replies."""

    global _weknora_diagnostic_logger
    if _weknora_diagnostic_logger is not None:
        return _weknora_diagnostic_logger

    diagnostic_logger = logging.getLogger(
        "agentscope.weknora.response_diagnostics",
    )
    diagnostic_logger.setLevel(logging.ERROR)
    diagnostic_logger.propagate = False
    if not diagnostic_logger.handlers:
        runtime_home = Path(
            os.getenv("AGENTSCOPE_RUNTIME_HOME", "data/agentscope"),
        )
        log_path = runtime_home / "logs" / "weknora_response_errors.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                log_path,
                maxBytes=5 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s | %(levelname)s | %(message)s",
                ),
            )
            diagnostic_logger.addHandler(handler)
        except OSError:
            # The ordinary application logger below still records the same
            # diagnostic when a read-only deployment cannot create the file.
            pass
    _weknora_diagnostic_logger = diagnostic_logger
    return diagnostic_logger


def _record_weknora_invalid_json(
    response: httpx.Response,
    *,
    request_id: str,
    method: str,
    path: str,
    queue_wait_ms: int,
) -> None:
    """Persist enough raw upstream evidence to diagnose a malformed reply."""

    body = response.content
    body_sample = body[:_WEKNORA_DIAGNOSTIC_BODY_BYTES]
    encoding = response.encoding or "utf-8"
    try:
        body_text = body_sample.decode(encoding, errors="replace")
    except LookupError:
        body_text = body_sample.decode("utf-8", errors="replace")
    upstream_request_id = (
        response.headers.get("x-request-id")
        or response.headers.get("x-correlation-id")
        or response.headers.get("cf-ray")
        or ""
    )
    message = (
        "WeKnora 非 JSON 响应 | diagnostic_id=%s | method=%s | path=%s "
        "| status=%s | content_type=%r | content_length=%s | sha256=%s "
        "| upstream_request_id=%r | queue_wait_ms=%s | body_truncated=%s "
        "| body_repr=%r"
    )
    values = (
        request_id,
        method.upper(),
        path,
        response.status_code,
        response.headers.get("content-type", ""),
        len(body),
        hashlib.sha256(body).hexdigest(),
        upstream_request_id,
        queue_wait_ms,
        len(body) > len(body_sample),
        body_text,
    )
    logger.error(message, *values)
    diagnostic_logger = _get_weknora_diagnostic_logger()
    if diagnostic_logger.handlers:
        diagnostic_logger.error(message, *values)


def _record_weknora_invalid_sse(
    raw_event: str,
    response: httpx.Response,
    *,
    request_id: str,
    path: str,
) -> None:
    """Persist a malformed WeKnora SSE frame without exposing credentials."""

    raw_bytes = raw_event.encode("utf-8", errors="replace")
    body_sample = raw_bytes[:_WEKNORA_DIAGNOSTIC_BODY_BYTES].decode(
        "utf-8",
        errors="replace",
    )
    upstream_request_id = (
        response.headers.get("x-request-id")
        or response.headers.get("x-correlation-id")
        or response.headers.get("cf-ray")
        or ""
    )
    message = (
        "WeKnora 非法 SSE 事件 | diagnostic_id=%s | path=%s | status=%s "
        "| content_type=%r | sha256=%s | upstream_request_id=%r "
        "| body_truncated=%s | body_repr=%r"
    )
    values = (
        request_id,
        path,
        response.status_code,
        response.headers.get("content-type", ""),
        hashlib.sha256(raw_bytes).hexdigest(),
        upstream_request_id,
        len(raw_bytes) > _WEKNORA_DIAGNOSTIC_BODY_BYTES,
        body_sample,
    )
    logger.error(message, *values)
    diagnostic_logger = _get_weknora_diagnostic_logger()
    if diagnostic_logger.handlers:
        diagnostic_logger.error(message, *values)


def _memory_infrastructure_response() -> MemoryInfrastructureResponse:
    """Return non-secret memory infrastructure details for the settings UI."""

    try:
        from utils import config as memory_config

        provider = str(memory_config.EMBEDDING_PROVIDER)
        model = str(memory_config.EMBEDDING_MODEL)
        dimensions = int(memory_config.EMBEDDING_DIMS)
        collection = str(memory_config.MEM0_COLLECTION)
    except (AttributeError, ImportError, TypeError, ValueError):
        provider = os.getenv("EMBEDDING_PROVIDER", "local")
        model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
        dimensions = int(os.getenv("EMBEDDING_DIMS", "1024"))
        collection = os.getenv("MEM0_COLLECTION", "dobby_memories")
    return MemoryInfrastructureResponse(
        embedding_provider=provider,
        embedding_model=model,
        embedding_dimensions=dimensions,
        mem0_collection=collection,
    )


def _memory_settings_response(
    settings: PlatformSettingsRecord,
) -> MemorySettingsResponse:
    return MemorySettingsResponse(
        settings=settings.data.memory_settings,
        revision=settings.data.memory_settings_revision,
        updated_at=settings.updated_at,
        infrastructure=_memory_infrastructure_response(),
    )


def _check_memory_settings_revision(
    expected_revision: int | None,
    current_revision: int,
) -> None:
    if expected_revision is not None and expected_revision != current_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "记忆配置已被其他操作更新，请刷新页面后重新修改。"
            ),
        )


def _validate_weknora_endpoint(base_url: str) -> str:
    """Validate a user-managed endpoint before the backend calls it."""
    normalised = base_url.strip().rstrip("/")
    parsed = urlsplit(normalised)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="WeKnora 服务地址必须是完整的 HTTP(S) URL。",
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="WeKnora 服务地址不能包含用户信息、查询参数或片段。",
        )
    return normalised


def _weknora_response(
    config: WeKnoraConnectionConfig | None,
) -> WeKnoraConnectionResponse:
    if config is None:
        return WeKnoraConnectionResponse()
    return WeKnoraConnectionResponse(
        base_url=config.base_url,
        api_prefix=config.api_prefix,
        auth_header=config.auth_header,
        api_key_configured=bool(config.api_key.get_secret_value()),
    )


def _require_weknora_connection(
    settings: PlatformSettingsRecord,
) -> WeKnoraConnectionConfig:
    connection = settings.data.weknora_connection
    if connection is None or not connection.api_key.get_secret_value():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="请先保存 WeKnora 服务地址和 API Key。",
        )
    return connection


def _build_weknora_config(
    body: UpdateWeKnoraConnectionRequest,
    existing: WeKnoraConnectionConfig | None,
) -> WeKnoraConnectionConfig:
    base_url = _validate_weknora_endpoint(body.base_url)
    api_key = body.api_key or (
        existing.api_key.get_secret_value() if existing is not None else ""
    )
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="首次配置 WeKnora 时必须填写 API Key。",
        )
    try:
        return WeKnoraConnectionConfig(
            base_url=base_url,
            api_prefix=body.api_prefix,
            auth_header=body.auth_header,
            api_key=api_key,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors()[0]["msg"],
        ) from exc


async def _request_weknora_json(
    config: WeKnoraConnectionConfig,
    path: str,
    *,
    params: dict[str, int | str] | None = None,
    method: str = "GET",
    json_body: dict | None = None,
    data: dict[str, str] | None = None,
    files: dict | None = None,
    timeout_seconds: float = 30.0,
    max_response_bytes: int = 5 * 1024 * 1024,
) -> dict:
    """Call one WeKnora JSON endpoint through the management backend."""
    url = f"{config.base_url}{config.api_prefix}{path}"
    request_id = uuid4().hex[:12]
    queued_at = time.perf_counter()
    queue_wait_ms = 0
    try:
        async with _weknora_json_request_gate:
            queue_wait_ms = round(
                (time.perf_counter() - queued_at) * 1000,
            )
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout_seconds, connect=10.0),
                follow_redirects=False,
            ) as client:
                response = await client.request(
                    method.upper(),
                    url,
                    headers={
                        config.auth_header: config.api_key.get_secret_value(),
                        "Accept": "application/json",
                    },
                    params=params,
                    json=json_body,
                    data=data,
                    files=files,
                )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="连接 WeKnora 超时，请检查服务地址和网络。",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="无法连接 WeKnora，请检查服务地址和网络。",
        ) from exc
    _validate_weknora_response(response)
    if response.status_code == status.HTTP_204_NO_CONTENT:
        return {"success": True, "data": {}}
    if len(response.content) > max_response_bytes:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WeKnora 返回内容过大，已拒绝处理。",
        )
    try:
        payload = json.loads(response.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _record_weknora_invalid_json(
            response,
            request_id=request_id,
            method=method,
            path=path,
            queue_wait_ms=queue_wait_ms,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "WeKnora 返回的不是有效 JSON"
                f"（诊断编号：{request_id}）。"
            ),
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WeKnora 返回了无效的响应结构。",
        )
    if payload.get("success") is False:
        remote_message = _text(payload.get("message"))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"WeKnora 返回失败：{remote_message[:300]}"
                if remote_message
                else "WeKnora 返回了失败响应。"
            ),
        )
    return payload


def _validate_weknora_response(response: httpx.Response) -> None:
    """Translate remote HTTP status codes to stable management errors."""

    if response.status_code in {301, 302, 303, 307, 308}:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WeKnora 返回了重定向，请直接填写最终服务地址。",
        )
    if response.status_code in {401, 403}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="WeKnora 拒绝鉴权，请检查 API Key 和鉴权请求头。",
        )
    if response.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WeKnora 中不存在所请求的智能体、知识库或资料。",
        )
    if not 200 <= response.status_code < 300:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"WeKnora 返回 HTTP {response.status_code}，请检查配置。",
        )


def _dobby_internal_api_base_url() -> str:
    """Return the trusted engineering-platform internal API root."""

    explicit = os.getenv("DOBBY_INTERNAL_API_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    gateway = os.getenv(
        "DOBBY_AGENT_TOOL_BASE_URL",
        "http://127.0.0.1:38430/api/internal/agent-tools",
    ).strip().rstrip("/")
    return gateway.rsplit("/agent-tools", 1)[0]


async def _request_dobby_project_bindings(
    path: str = "",
    *,
    method: str = "GET",
    json_body: dict | None = None,
) -> object:
    """Read or update project bindings through the trusted service API."""

    token = (
        os.getenv("DOBBY_AGENT_TOOL_TOKEN", "").strip()
        or os.getenv("AGENTSCOPE_SERVICE_TOKEN", "").strip()
    )
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="尚未配置工程平台内部服务令牌。",
        )
    url = (
        f"{_dobby_internal_api_base_url()}"
        f"/agent-tools/weknora-project-bindings{path}"
    )
    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(20.0),
        ) as client:
            response = await client.request(
                method,
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=json_body,
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="读取工程项目列表超时，请确认业务后端已启动。",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="无法连接工程管理业务后端。",
        ) from exc
    if response.status_code in {401, 403}:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="工程平台内部服务令牌不一致。",
        )
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="工程项目不存在。")
    if not 200 <= response.status_code < 300:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"工程管理业务后端返回 HTTP {response.status_code}。",
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="工程管理业务后端返回了无效响应。",
        ) from exc
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="工程管理业务后端返回了失败响应。",
        )
    return payload.get("data")


async def _request_weknora_bytes(
    config: WeKnoraConnectionConfig,
    path: str,
    *,
    params: dict[str, str] | None = None,
    root_path: bool = False,
    max_response_bytes: int = 64 * 1024 * 1024,
) -> tuple[bytes, str, str]:
    """Download one authenticated WeKnora file or preview response."""
    url = (
        f"{config.base_url}{path}"
        if root_path
        else f"{config.base_url}{config.api_prefix}{path}"
    )
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0),
            follow_redirects=False,
        ) as client:
            response = await client.get(
                url,
                headers={
                    config.auth_header: config.api_key.get_secret_value(),
                    "Accept": "*/*",
                },
                params=params,
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="下载 WeKnora 资料超时。",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="无法连接 WeKnora 下载资料。",
        ) from exc
    _validate_weknora_response(response)
    if len(response.content) > max_response_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="WeKnora 返回的资料超过平台代理大小限制。",
        )
    return (
        response.content,
        response.headers.get("content-type", "application/octet-stream"),
        response.headers.get("content-disposition", ""),
    )


async def _stream_weknora_sse_events(
    config: WeKnoraConnectionConfig,
    path: str,
    body: dict,
    *,
    params: dict[str, str] | None = None,
    session_id: str = "",
) -> AsyncIterator[dict]:
    """Yield complete WeKnora SSE events without an answer deadline."""

    url = f"{config.base_url}{config.api_prefix}{path}"
    request_id = uuid4().hex[:12]
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=None,
                write=30.0,
                pool=10.0,
            ),
            follow_redirects=False,
        ) as client:
            async with client.stream(
                "POST",
                url,
                headers={
                    config.auth_header: config.api_key.get_secret_value(),
                    "Accept": "text/event-stream",
                },
                params=params,
                json=body,
            ) as response:
                _validate_weknora_response(response)
                data_lines: list[str] = []

                async def parse_event(raw_event: str) -> dict:
                    try:
                        event = json.loads(raw_event)
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        _record_weknora_invalid_sse(
                            raw_event,
                            response,
                            request_id=request_id,
                            path=path,
                        )
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=(
                                "WeKnora 返回了无法解析的流式事件"
                                f"（诊断编号：{request_id}）。"
                            ),
                        ) from exc
                    if not isinstance(event, dict):
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="WeKnora 返回了无效的流式事件结构。",
                        )
                    return event

                answer_done_deadline: float | None = None
                line_iterator = response.aiter_lines().__aiter__()
                while True:
                    try:
                        if answer_done_deadline is None:
                            raw_line = await anext(line_iterator)
                        else:
                            remaining = (
                                answer_done_deadline
                                - asyncio.get_running_loop().time()
                            )
                            if remaining <= 0:
                                return
                            raw_line = await asyncio.wait_for(
                                anext(line_iterator),
                                timeout=remaining,
                            )
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError:
                        # The answer is already complete.  This grace period is
                        # only for an optional title or reference event and is
                        # deliberately not an answer-generation timeout.
                        return
                    line = raw_line.rstrip("\r")
                    if line == "":
                        if not data_lines:
                            continue
                        event = await parse_event("\n".join(data_lines))
                        data_lines.clear()
                        response_type = _text(event.get("response_type"))
                        message_id = _text(
                            event.get("message_id") or event.get("id"),
                        )
                        if (
                            session_id
                            and message_id
                            and response_type == "answer"
                        ):
                            _active_weknora_message_ids[session_id] = message_id
                        yield event
                        if response_type in {"complete", "error", "stop"}:
                            return
                        if (
                            response_type == "answer"
                            and event.get("done") is True
                        ):
                            answer_done_deadline = (
                                asyncio.get_running_loop().time()
                                + _WEKNORA_POST_ANSWER_METADATA_GRACE_SECONDS
                            )
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())

                if data_lines:
                    event = await parse_event("\n".join(data_lines))
                    response_type = _text(event.get("response_type"))
                    message_id = _text(
                        event.get("message_id") or event.get("id"),
                    )
                    if (
                        session_id
                        and message_id
                        and response_type == "answer"
                    ):
                        _active_weknora_message_ids[session_id] = message_id
                    yield event
    except HTTPException:
        raise
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="连接 WeKnora 智能体超时。",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="无法连接 WeKnora 智能体。",
        ) from exc
    finally:
        if session_id:
            _active_weknora_message_ids.pop(session_id, None)


async def _request_weknora_sse(
    config: WeKnoraConnectionConfig,
    path: str,
    body: dict,
    *,
    params: dict[str, str] | None = None,
    session_id: str = "",
) -> list[dict]:
    """Aggregate WeKnora SSE for backward-compatible non-stream callers."""

    return [
        event
        async for event in _stream_weknora_sse_events(
            config,
            path,
            body,
            params=params,
            session_id=session_id,
        )
    ]


def _weknora_list_payload(payload: dict) -> tuple[list[dict], dict]:
    """Extract either the documented array or paginated list shape."""
    data = payload.get("data", [])
    if isinstance(data, list):
        # The deployed WeKnora API returns list items in ``data`` while
        # pagination fields (total/page/page_size) live at the response root.
        # Preserve the root metadata or callers will mistake the first page
        # length for the complete result count.
        return [item for item in data if isinstance(item, dict)], payload
    if isinstance(data, dict) and isinstance(data.get("list"), list):
        return (
            [item for item in data["list"] if isinstance(item, dict)],
            data,
        )
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="WeKnora 列表响应结构无效。",
    )


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _normalise_weknora_folder_path(value: object) -> str:
    """Normalise one WeKnora folder path without changing its segments."""

    path = _text(value).replace("\\", "/").strip("/")
    return "/".join(segment for segment in path.split("/") if segment)


def _validate_weknora_folder_path(value: object) -> str:
    """Validate a user-created path before using it in a marker upload."""

    raw_path = _text(value).replace("\\", "/").strip("/")
    segments = raw_path.split("/") if raw_path else []
    if (
        not segments
        or any(
            not segment.strip()
            or segment.strip() in {".", ".."}
            or "\x00" in segment
            or segment.casefold()
            == WEKNORA_FOLDER_PLACEHOLDER_FILENAME.casefold()
            for segment in segments
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="文件夹路径无效。",
        )
    return "/".join(segment.strip() for segment in segments)


def _is_weknora_folder_placeholder(
    item: dict | WeKnoraKnowledgeItem,
) -> bool:
    """Whether a remote knowledge item is our private empty folder marker."""

    if isinstance(item, dict):
        values = (
            item.get("file_name"),
            item.get("filename"),
            item.get("title"),
            item.get("knowledge_filename"),
            item.get("knowledge_title"),
            item.get("source"),
        )
    else:
        values = (item.file_name, item.title, item.source)
    expected = WEKNORA_FOLDER_PLACEHOLDER_FILENAME.casefold()
    for value in values:
        leaf = _text(value).replace("\\", "/").rsplit("/", 1)[-1]
        if leaf.casefold() == expected:
            return True
    return False


def _integer(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _extract_weknora_inline_citations(answer: str) -> list[dict[str, str]]:
    """Extract the inline ``<kb .../>`` citations used by agent-chat.

    Some deployed WeKnora versions do not emit a separate ``references`` SSE
    event.  Instead, the answer contains one or more self-closing ``kb`` tags.
    Keep this parser deliberately small and attribute-based so arbitrary answer
    text is never interpreted as HTML.
    """

    citations: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for match in _WEKNORA_INLINE_CITATION_RE.finditer(answer):
        attributes = {
            attribute.group("name").lower(): unescape(
                attribute.group("value"),
            ).strip()
            for attribute in _WEKNORA_INLINE_CITATION_ATTRIBUTE_RE.finditer(
                match.group("attributes"),
            )
        }
        document = attributes.get("doc", "").replace("\\", "/").strip()
        filename = document.rsplit("/", 1)[-1].strip()
        if not filename:
            continue
        citation = {
            "filename": filename,
            "chunk_id": attributes.get("chunk_id", ""),
            "knowledge_base_id": attributes.get("kb_id", ""),
        }
        identity = (
            citation["knowledge_base_id"],
            citation["filename"].casefold(),
            citation["chunk_id"],
        )
        if identity in seen:
            continue
        seen.add(identity)
        citations.append(citation)
    return citations


def _weknora_reference_filename(item: dict) -> str:
    nested_file = item.get("file_info")
    file_item = nested_file if isinstance(nested_file, dict) else {}
    return (
        _text(item.get("knowledge_filename"))
        or _text(item.get("filename"))
        or _text(item.get("file_name"))
        or _text(file_item.get("file_name"))
        or _text(item.get("knowledge_title"))
        or _text(item.get("title"))
    )


def _merge_weknora_reference_items(*groups: list[dict]) -> list[dict]:
    """Merge chunk- and file-level citations without duplicate file cards."""

    merged_items: list[dict] = []
    for group in groups:
        for raw_item in group:
            if not isinstance(raw_item, dict):
                continue
            item = dict(raw_item)
            item_chunk_id = _text(item.get("chunk_id") or item.get("id"))
            item_knowledge_id = _text(item.get("knowledge_id"))
            item_kb_id = _text(item.get("knowledge_base_id"))
            item_filename = _weknora_reference_filename(item).casefold()
            duplicate_index: int | None = None
            for index, existing in enumerate(merged_items):
                existing_chunk_id = _text(
                    existing.get("chunk_id") or existing.get("id"),
                )
                existing_knowledge_id = _text(existing.get("knowledge_id"))
                existing_kb_id = _text(existing.get("knowledge_base_id"))
                existing_filename = _weknora_reference_filename(
                    existing,
                ).casefold()
                same_chunk = bool(
                    item_chunk_id
                    and existing_chunk_id
                    and item_chunk_id == existing_chunk_id
                )
                same_knowledge = bool(
                    item_knowledge_id
                    and existing_knowledge_id
                    and item_knowledge_id == existing_knowledge_id
                )
                same_file = bool(
                    item_filename
                    and existing_filename
                    and item_filename == existing_filename
                    and (
                        not item_kb_id
                        or not existing_kb_id
                        or item_kb_id == existing_kb_id
                    )
                )
                if same_chunk or same_knowledge or same_file:
                    duplicate_index = index
                    break
            if duplicate_index is None:
                merged_items.append(item)
                continue
            existing = merged_items[duplicate_index]
            for key, value in item.items():
                if value not in (None, "", [], {}):
                    existing[key] = value
    return merged_items


def _weknora_reference_from_record(record: dict) -> dict | None:
    """Build one citation candidate from a WeKnora tool-data record."""

    knowledge_id = _text(record.get("knowledge_id"))
    if not knowledge_id:
        return None
    title = (
        _text(record.get("knowledge_title"))
        or _text(record.get("title"))
        or _text(record.get("knowledge_filename"))
        or _text(record.get("filename"))
        or _text(record.get("file_name"))
    )
    filename = (
        _text(record.get("knowledge_filename"))
        or _text(record.get("filename"))
        or _text(record.get("file_name"))
        or title
    )
    return {
        "knowledge_id": knowledge_id,
        "knowledge_base_id": _text(record.get("knowledge_base_id")),
        "chunk_id": _text(record.get("chunk_id") or record.get("id")),
        "knowledge_title": title,
        "knowledge_filename": filename,
        "content": _text(
            record.get("content") or record.get("content_snippet"),
        )[:2000],
    }


def _weknora_nested_reference_records(value: object) -> list[dict]:
    """Find documented ``knowledge_id`` records inside tool result data."""

    references: list[dict] = []
    if isinstance(value, dict):
        candidate = _weknora_reference_from_record(value)
        if candidate is not None:
            references.append(candidate)
        for nested in value.values():
            references.extend(_weknora_nested_reference_records(nested))
    elif isinstance(value, list):
        for nested in value:
            references.extend(_weknora_nested_reference_records(nested))
    return references


def _weknora_tool_reference_items(
    event: dict,
    tool_calls: dict[str, dict],
) -> tuple[list[dict], list[dict[str, str]]]:
    """Extract source documents exposed by WeKnora tool events.

    Agent-chat does not consistently append inline ``<kb>`` tags or a final
    ``references`` event.  Its documented tool events still identify the
    source that was searched/read (for example ``list_knowledge_chunks``
    returns ``knowledge_id`` and ``knowledge_title``).  Preserve that actual
    upstream evidence instead of guessing a document from answer text.
    """

    response_type = _text(event.get("response_type"))
    data = event.get("data")
    if not isinstance(data, dict):
        return [], []
    tool_call_id = _text(data.get("tool_call_id"))
    tool_name = _text(data.get("tool_name"))
    if response_type == "tool_call":
        if not tool_call_id:
            return [], []
        current = tool_calls.setdefault(tool_call_id, {})
        if tool_name:
            current["tool_name"] = tool_name
        arguments = data.get("arguments")
        if isinstance(arguments, dict):
            current["arguments"] = arguments
        return [], []
    if response_type != "tool_result" or data.get("success") is False:
        return [], []

    call = tool_calls.get(tool_call_id, {})
    tool_name = tool_name or _text(call.get("tool_name"))
    if tool_name not in _WEKNORA_SOURCE_TOOL_NAMES:
        return [], []
    arguments = call.get("arguments")
    arguments = arguments if isinstance(arguments, dict) else {}

    references = _weknora_nested_reference_records(data)
    argument_kb_id = _text(arguments.get("knowledge_base_id"))
    argument_ids: list[str] = []
    argument_id = _text(arguments.get("knowledge_id"))
    if argument_id:
        argument_ids.append(argument_id)
    raw_argument_ids = arguments.get("knowledge_ids")
    if isinstance(raw_argument_ids, list):
        argument_ids.extend(
            _text(item) for item in raw_argument_ids if _text(item)
        )
    direct_title = (
        _text(data.get("knowledge_title"))
        or _text(data.get("knowledge_filename"))
        or _text(data.get("filename"))
        or _text(data.get("file_name"))
    )
    for knowledge_id in argument_ids:
        references.append(
            {
                "knowledge_id": knowledge_id,
                "knowledge_base_id": argument_kb_id,
                "knowledge_title": direct_title,
                "knowledge_filename": direct_title,
            },
        )

    output = data.get("output")
    inline_citations: list[dict[str, str]] = []
    if isinstance(output, str):
        inline_citations = _extract_weknora_inline_citations(output)
        found_kbs = data.get("found_kbs")
        found_kbs = found_kbs if isinstance(found_kbs, dict) else {}
        for match in _WEKNORA_WIKI_SUMMARY_REFERENCE_RE.finditer(output):
            knowledge_id = match.group("knowledge_id")
            summary_slug = f"summary/{knowledge_id}"
            raw_kb_ids = found_kbs.get(summary_slug)
            kb_id = (
                _text(raw_kb_ids[0])
                if isinstance(raw_kb_ids, list) and raw_kb_ids
                else ""
            )
            title = unescape(match.group("title")).strip()
            title = re.sub(
                r"\s*-\s*Summary\s*$",
                "",
                title,
                flags=re.IGNORECASE,
            ).strip()
            references.append(
                {
                    "knowledge_id": knowledge_id,
                    "knowledge_base_id": kb_id,
                    "knowledge_title": title,
                    "knowledge_filename": title,
                },
            )
    return _merge_weknora_reference_items(references), inline_citations


async def _find_weknora_citation_source(
    config: WeKnoraConnectionConfig,
    knowledge_base_ids: list[str],
    filename: str,
) -> WeKnoraKnowledgeItem | None:
    """Resolve an inline citation to its file without concurrent API calls."""

    target = filename.casefold()
    for knowledge_base_id in knowledge_base_ids:
        encoded_id = quote(knowledge_base_id, safe="")
        try:
            payload = await _request_weknora_json(
                config,
                f"/knowledge-bases/{encoded_id}/knowledge",
                params={
                    "page": 1,
                    "page_size": 100,
                    "keyword": filename[:512],
                },
            )
            raw_items, _ = _weknora_list_payload(payload)
        except (HTTPException, ValidationError, TypeError, ValueError) as exc:
            logger.warning(
                "WeKnora 内嵌引用资料查找失败：kb=%s file=%s "
                "status=%s detail=%s",
                knowledge_base_id,
                filename,
                getattr(exc, "status_code", "invalid-data"),
                getattr(exc, "detail", str(exc)),
            )
            continue
        for raw_item in raw_items:
            if _is_weknora_folder_placeholder(raw_item):
                continue
            item = _weknora_knowledge_item(raw_item, knowledge_base_id)
            candidates = {
                item.file_name.casefold(),
                item.title.casefold(),
                item.source.replace("\\", "/").rsplit("/", 1)[-1].casefold(),
            }
            if target in candidates:
                return item
    return None


async def _enrich_weknora_inline_citations(
    config: WeKnoraConnectionConfig,
    answer: str,
    allowed_knowledge_base_ids: list[str],
    known_references: list[dict] | None = None,
) -> list[dict]:
    """Turn agent-chat inline tags into the platform citation contract."""

    return await _enrich_weknora_citation_items(
        config,
        _extract_weknora_inline_citations(answer),
        allowed_knowledge_base_ids,
        known_references,
    )


async def _enrich_weknora_citation_items(
    config: WeKnoraConnectionConfig,
    citations: list[dict[str, str]],
    allowed_knowledge_base_ids: list[str],
    known_references: list[dict] | None = None,
) -> list[dict]:
    """Resolve already parsed citation tags to source-file metadata."""

    if not citations:
        return []
    known = known_references or []
    resolved_cache: dict[tuple[str, str], WeKnoraKnowledgeItem | None] = {}
    references: list[dict] = []
    for citation in citations:
        filename = citation["filename"]
        chunk_id = citation["chunk_id"]
        cited_kb_id = citation["knowledge_base_id"]
        matching_known = next(
            (
                item
                for item in known
                if (
                    chunk_id
                    and chunk_id
                    == _text(item.get("chunk_id") or item.get("id"))
                )
                or (
                    filename.casefold()
                    == _weknora_reference_filename(item).casefold()
                )
            ),
            None,
        )
        if matching_known is not None:
            references.append(
                _merge_weknora_reference_items(
                    [
                        {
                            "chunk_id": chunk_id,
                            "knowledge_base_id": cited_kb_id,
                            "filename": filename,
                        },
                    ],
                    [matching_known],
                )[0],
            )
            continue

        candidate_kb_ids = list(allowed_knowledge_base_ids)
        if cited_kb_id in candidate_kb_ids:
            candidate_kb_ids.remove(cited_kb_id)
            candidate_kb_ids.insert(0, cited_kb_id)
        cache_key = ("\x1f".join(candidate_kb_ids), filename.casefold())
        if cache_key not in resolved_cache:
            resolved_cache[cache_key] = await _find_weknora_citation_source(
                config,
                candidate_kb_ids,
                filename,
            )
        details = resolved_cache[cache_key]
        reference = WeKnoraSearchReference(
            chunk_id=chunk_id,
            knowledge_id=details.id if details else "",
            knowledge_base_id=(
                details.knowledge_base_id
                if details and details.knowledge_base_id
                else cited_kb_id
            ),
            title=details.title if details else filename,
            filename=details.file_name if details else filename,
            folder_path=details.folder_path if details else "",
            knowledge_channel=details.channel if details else "",
            file_type=details.file_type if details else "",
            file_size=details.file_size if details else None,
            source=details.source if details else "",
            knowledge_type=details.type if details else "",
            parse_status=details.parse_status if details else "",
            download_url=(
                f"/agent/platform/weknora/knowledge/"
                f"{quote(details.id, safe='')}/download"
                if details
                else ""
            ),
            preview_url=(
                f"/agent/platform/weknora/knowledge/"
                f"{quote(details.id, safe='')}/preview"
                if details
                else ""
            ),
        ).model_dump()
        references.append(reference)
    return _merge_weknora_reference_items(references)


def _weknora_knowledge_item(
    item: dict,
    knowledge_base_id: str | None = None,
) -> WeKnoraKnowledgeItem:
    """Normalise one documented knowledge object for management APIs."""

    file_size = item.get("file_size")
    normalised_file_size = (
        _integer(file_size) if file_size is not None else None
    )
    return WeKnoraKnowledgeItem(
        id=_text(item.get("id")),
        knowledge_base_id=(
            _text(item.get("knowledge_base_id"))
            or knowledge_base_id
        ),
        type=_text(item.get("type")),
        title=_text(item.get("title")),
        description=_text(item.get("description")),
        file_name=_text(item.get("file_name")),
        folder_path=_text(item.get("folder_path")),
        file_type=_text(item.get("file_type")),
        file_size=normalised_file_size,
        source=_text(item.get("source")),
        channel=_text(item.get("channel")),
        parse_status=_text(item.get("parse_status")),
        enable_status=_text(item.get("enable_status")),
        created_at=_text(item.get("created_at")) or None,
        processed_at=_text(item.get("processed_at")) or None,
    )


def _weknora_folder_item(
    item: dict,
    placeholder_paths: list[str] | None = None,
) -> WeKnoraFolderItem | None:
    """Normalise one recursive node from the documented folder response."""

    path = _normalise_weknora_folder_path(item.get("path"))
    if not path:
        return None
    hidden_paths = placeholder_paths or []
    direct_hidden = sum(hidden_path == path for hidden_path in hidden_paths)
    nested_prefix = f"{path}/"
    nested_hidden = sum(
        hidden_path == path or hidden_path.startswith(nested_prefix)
        for hidden_path in hidden_paths
    )
    raw_children = item.get("children", [])
    children: list[WeKnoraFolderItem] = []
    if isinstance(raw_children, list):
        for raw_child in raw_children:
            if not isinstance(raw_child, dict):
                continue
            child = _weknora_folder_item(raw_child, hidden_paths)
            if child is not None:
                children.append(child)
    return WeKnoraFolderItem(
        path=path,
        name=_text(item.get("name")) or path.rsplit("/", 1)[-1],
        document_count=max(
            _integer(item.get("document_count")) - direct_hidden,
            0,
        ),
        total_count=max(
            _integer(item.get("total_count")) - nested_hidden,
            0,
        ),
        children=children,
    )


async def _fetch_weknora_folder_placeholders(
    config: WeKnoraConnectionConfig,
    knowledge_base_id: str,
) -> list[WeKnoraKnowledgeItem]:
    """Load private folder markers so counts and lists can hide them."""

    encoded_id = quote(knowledge_base_id, safe="")
    page_size = 100
    placeholders: list[WeKnoraKnowledgeItem] = []
    seen_items = 0
    for page in range(1, 10001):
        payload = await _request_weknora_json(
            config,
            f"/knowledge-bases/{encoded_id}/knowledge",
            params={
                "page": page,
                "page_size": page_size,
                "keyword": WEKNORA_FOLDER_PLACEHOLDER_FILENAME,
            },
        )
        raw_items, metadata = _weknora_list_payload(payload)
        seen_items += len(raw_items)
        for item in raw_items:
            if _is_weknora_folder_placeholder(item):
                placeholders.append(
                    _weknora_knowledge_item(item, knowledge_base_id),
                )
        raw_total = _integer(metadata.get("total"), seen_items)
        if (
            not raw_items
            or len(raw_items) < page_size
            or seen_items >= raw_total
        ):
            break
    return placeholders


async def _fetch_weknora_agent(
    config: WeKnoraConnectionConfig,
    agent_id: str,
) -> tuple[str, str, list[str]]:
    """Load one WeKnora robot and its documented knowledge-base scope."""

    encoded_id = quote(agent_id, safe="")
    payload = await _request_weknora_json(config, f"/agents/{encoded_id}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WeKnora 智能体详情响应结构无效。",
        )
    remote_id = _text(data.get("id"))
    if remote_id and remote_id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WeKnora 返回的智能体 ID 与配置不一致。",
        )
    raw_config = data.get("config")
    if not isinstance(raw_config, dict):
        raw_config = {}
    selection_mode = _text(raw_config.get("kb_selection_mode")) or "all"
    raw_ids = raw_config.get("knowledge_bases", [])
    if not isinstance(raw_ids, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WeKnora 智能体的知识库配置结构无效。",
        )
    selected_ids = list(
        dict.fromkeys(_text(item) for item in raw_ids if _text(item)),
    )
    if selection_mode == "none":
        selected_ids = []
    elif selection_mode == "all":
        selected_ids = [
            item.id for item in await _fetch_weknora_knowledge_bases(config)
        ]
    return remote_id or agent_id, _text(data.get("name")), selected_ids


async def _weknora_agent_knowledge_base_ids(
    config: WeKnoraConnectionConfig,
    agent_id: str | None,
) -> list[str] | None:
    """Return the robot-owned KB scope, or ``None`` for admin management."""

    # FastAPI's ``Query`` default is only resolved during dependency injection;
    # direct service-level calls (including unit tests) receive the descriptor.
    # Treat every non-string value as the unrestricted administration scope.
    if not isinstance(agent_id, str) or not agent_id.strip():
        return None
    agent_id = agent_id.strip()
    _, _, knowledge_base_ids = await _fetch_weknora_agent(config, agent_id)
    if not knowledge_base_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该 WeKnora 机器人没有配置可读取的知识库。",
        )
    return knowledge_base_ids


def _require_weknora_knowledge_base_access(
    knowledge_base_id: str,
    allowed_ids: list[str] | None,
) -> None:
    if allowed_ids is not None and knowledge_base_id not in allowed_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前项目绑定的 WeKnora 机器人无权访问该知识库。",
        )


async def _fetch_weknora_knowledge_item_by_id(
    config: WeKnoraConnectionConfig,
    knowledge_id: str,
) -> WeKnoraKnowledgeItem:
    payload = await _request_weknora_json(
        config,
        f"/knowledge/{quote(knowledge_id, safe='')}",
    )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WeKnora 资料详情响应结构无效。",
        )
    item = _weknora_knowledge_item(data)
    if not item.id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WeKnora 资料详情缺少知识 ID。",
        )
    return item


async def _require_weknora_knowledge_access(
    config: WeKnoraConnectionConfig,
    knowledge_id: str,
    allowed_ids: list[str] | None,
) -> WeKnoraKnowledgeItem:
    item = await _fetch_weknora_knowledge_item_by_id(config, knowledge_id)
    if not item.knowledge_base_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WeKnora 资料详情缺少知识库 ID。",
        )
    _require_weknora_knowledge_base_access(
        item.knowledge_base_id,
        allowed_ids,
    )
    return item


async def _fetch_weknora_knowledge_bases(
    config: WeKnoraConnectionConfig,
) -> list[WeKnoraKnowledgeBaseItem]:
    payload = await _request_weknora_json(config, "/knowledge-bases")
    raw_items, _ = _weknora_list_payload(payload)
    result: list[WeKnoraKnowledgeBaseItem] = []
    for item in raw_items:
        item_id = _text(item.get("id"))
        if not item_id:
            continue
        result.append(
            WeKnoraKnowledgeBaseItem(
                id=item_id,
                name=_text(item.get("name")) or item_id,
                description=_text(item.get("description")),
                created_at=_text(item.get("created_at")) or None,
                updated_at=_text(item.get("updated_at")) or None,
            ),
        )
    return result


async def _fetch_weknora_knowledge(
    config: WeKnoraConnectionConfig,
    knowledge_base_id: str,
    *,
    page: int,
    page_size: int,
    folder_path: str | None = None,
    folder_recursive: bool = True,
    keyword: str = "",
) -> tuple[list[WeKnoraKnowledgeItem], int]:
    encoded_id = quote(knowledge_base_id, safe="")
    params: dict[str, int | str] = {"page": page, "page_size": page_size}
    if folder_path is not None:
        params.update(
            {
                "folder_path": folder_path,
                "folder_recursive": str(folder_recursive).lower(),
            },
        )
    if keyword:
        params["keyword"] = keyword
    payload = await _request_weknora_json(
        config,
        f"/knowledge-bases/{encoded_id}/knowledge",
        params=params,
    )
    raw_items, metadata = _weknora_list_payload(payload)
    result: list[WeKnoraKnowledgeItem] = []
    for item in raw_items:
        item_id = _text(item.get("id"))
        if not item_id or _is_weknora_folder_placeholder(item):
            continue
        result.append(_weknora_knowledge_item(item, knowledge_base_id))
    placeholders = await _fetch_weknora_folder_placeholders(
        config,
        knowledge_base_id,
    )
    normalised_folder_path = (
        _normalise_weknora_folder_path(folder_path)
        if folder_path is not None
        else None
    )

    def placeholder_is_in_scope(item: WeKnoraKnowledgeItem) -> bool:
        if keyword and keyword.casefold() not in (
            WEKNORA_FOLDER_PLACEHOLDER_FILENAME.casefold()
        ):
            return False
        if normalised_folder_path is None:
            return True
        item_path = _normalise_weknora_folder_path(item.folder_path)
        if folder_recursive:
            return (
                item_path == normalised_folder_path
                or item_path.startswith(f"{normalised_folder_path}/")
            )
        return item_path == normalised_folder_path

    hidden_total = sum(
        placeholder_is_in_scope(item) for item in placeholders
    )
    raw_total = metadata.get("total", len(result))
    try:
        total = max(int(raw_total) - hidden_total, len(result))
    except (TypeError, ValueError):
        total = len(result)
    return result, total


async def _fetch_weknora_folder_tree(
    config: WeKnoraConnectionConfig,
    knowledge_base_id: str,
) -> WeKnoraFolderTreeResponse:
    """Load WeKnora's complete folder hierarchy for one knowledge base."""

    encoded_id = quote(knowledge_base_id, safe="")
    payload = await _request_weknora_json(
        config,
        f"/knowledge-bases/{encoded_id}/knowledge/folders",
    )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WeKnora 文件夹树响应结构无效。",
        )
    raw_folders = data.get("folders", [])
    if not isinstance(raw_folders, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WeKnora 文件夹树节点结构无效。",
        )
    placeholders = await _fetch_weknora_folder_placeholders(
        config,
        knowledge_base_id,
    )
    placeholder_paths = [
        _normalise_weknora_folder_path(item.folder_path)
        for item in placeholders
    ]
    folders: list[WeKnoraFolderItem] = []
    for raw_folder in raw_folders:
        if not isinstance(raw_folder, dict):
            continue
        folder = _weknora_folder_item(raw_folder, placeholder_paths)
        if folder is not None:
            folders.append(folder)
    return WeKnoraFolderTreeResponse(
        root_document_count=max(
            _integer(data.get("root_document_count"))
            - sum(not path for path in placeholder_paths),
            0,
        ),
        total_document_count=max(
            _integer(data.get("total_document_count"))
            - len(placeholder_paths),
            0,
        ),
        folders=folders,
    )


async def _fetch_weknora_knowledge_batch(
    config: WeKnoraConnectionConfig,
    knowledge_ids: list[str],
) -> dict[str, WeKnoraKnowledgeItem]:
    """Fetch source metadata for a set of hybrid-search references."""

    unique_ids = list(dict.fromkeys(item for item in knowledge_ids if item))
    if not unique_ids:
        return {}
    payload = await _request_weknora_json(
        config,
        "/knowledge/batch",
        params={"ids": ",".join(unique_ids)},
    )
    raw_items, _ = _weknora_list_payload(payload)
    result: dict[str, WeKnoraKnowledgeItem] = {}
    for item in raw_items:
        item_id = _text(item.get("id"))
        if item_id:
            result[item_id] = _weknora_knowledge_item(item)
    return result


async def _search_weknora_knowledge(
    config: WeKnoraConnectionConfig,
    knowledge_base_id: str,
    request: SearchWeKnoraKnowledgeRequest,
) -> list[WeKnoraSearchReference]:
    """Run hybrid search and enrich each hit with source-file metadata."""

    encoded_id = quote(knowledge_base_id, safe="")
    payload = await _request_weknora_json(
        config,
        f"/knowledge-bases/{encoded_id}/hybrid-search",
        method="POST",
        json_body={
            "query_text": request.query,
            "vector_threshold": request.vector_threshold,
            "keyword_threshold": request.keyword_threshold,
            "match_count": request.top_k,
        },
    )
    raw_results = payload.get("data", [])
    if isinstance(raw_results, dict):
        raw_results = raw_results.get(
            "results",
            raw_results.get("items", raw_results.get("list", [])),
        )
    if not isinstance(raw_results, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WeKnora 混合检索响应结构无效。",
        )
    hits = [item for item in raw_results if isinstance(item, dict)]
    knowledge_ids = [
        _text(item.get("knowledge_id"))
        for item in hits
        if _text(item.get("knowledge_id"))
    ]
    file_info = await _fetch_weknora_knowledge_batch(config, knowledge_ids)
    references: list[WeKnoraSearchReference] = []
    for item in hits[: request.top_k]:
        knowledge_id = _text(item.get("knowledge_id"))
        details = file_info.get(knowledge_id)
        if (
            (details is not None and _is_weknora_folder_placeholder(details))
            or _is_weknora_folder_placeholder(item)
        ):
            continue
        references.append(
            WeKnoraSearchReference(
                chunk_id=_text(item.get("id")),
                knowledge_id=knowledge_id,
                title=(
                    _text(item.get("knowledge_title"))
                    or (details.title if details else "")
                ),
                filename=(
                    _text(item.get("knowledge_filename"))
                    or (details.file_name if details else "")
                ),
                folder_path=details.folder_path if details else "",
                content=_text(item.get("content")),
                score=(
                    _number(item.get("score"))
                    if item.get("score") is not None
                    else None
                ),
                chunk_index=(
                    _integer(item.get("chunk_index"))
                    if item.get("chunk_index") is not None
                    else None
                ),
                start_at=(
                    _integer(item.get("start_at"))
                    if item.get("start_at") is not None
                    else None
                ),
                end_at=(
                    _integer(item.get("end_at"))
                    if item.get("end_at") is not None
                    else None
                ),
                match_type=_text(item.get("match_type")),
                chunk_type=_text(item.get("chunk_type")),
                knowledge_channel=_text(item.get("knowledge_channel")),
                file_type=details.file_type if details else "",
                file_size=details.file_size if details else None,
                source=(
                    details.source
                    if details
                    else _text(item.get("knowledge_source"))
                ),
                knowledge_type=details.type if details else "",
                parse_status=details.parse_status if details else "",
                download_url=(
                    f"/agent/platform/weknora/knowledge/"
                    f"{quote(knowledge_id, safe='')}/download"
                    if knowledge_id
                    else ""
                ),
                preview_url=(
                    f"/agent/platform/weknora/knowledge/"
                    f"{quote(knowledge_id, safe='')}/preview"
                    if knowledge_id
                    else ""
                ),
            ),
        )
    return references


async def _enrich_weknora_reference_items(
    config: WeKnoraConnectionConfig,
    raw_references: object,
) -> list[dict]:
    """Normalise actual WeKnora citations and add source-file metadata."""

    if not isinstance(raw_references, list):
        return []
    raw_items = [item for item in raw_references if isinstance(item, dict)]
    knowledge_ids = [
        _text(item.get("knowledge_id"))
        for item in raw_items
        if _text(item.get("knowledge_id"))
    ]
    try:
        file_info = await _fetch_weknora_knowledge_batch(
            config,
            knowledge_ids,
        )
    except (HTTPException, ValidationError, TypeError, ValueError) as exc:
        # A metadata lookup must not turn an otherwise valid answer into a
        # failed chat. The original citation remains authoritative and is
        # still forwarded with every field WeKnora supplied.
        logger.warning(
            "WeKnora 引用元数据补全失败：status=%s detail=%s",
            getattr(exc, "status_code", "invalid-data"),
            getattr(exc, "detail", str(exc)),
        )
        file_info = {}

    references: list[dict] = []
    for item in raw_items:
        knowledge_id = _text(item.get("knowledge_id"))
        details = file_info.get(knowledge_id)
        if (
            (details is not None and _is_weknora_folder_placeholder(details))
            or _is_weknora_folder_placeholder(item)
        ):
            continue
        nested_file = item.get("file_info")
        file_item = nested_file if isinstance(nested_file, dict) else {}
        reference = WeKnoraSearchReference(
            chunk_id=(
                _text(item.get("id"))
                or _text(item.get("chunk_id"))
            ),
            knowledge_id=knowledge_id,
            knowledge_base_id=(
                _text(item.get("knowledge_base_id"))
                or (details.knowledge_base_id if details else "")
                or ""
            ),
            title=(
                _text(item.get("knowledge_title"))
                or _text(item.get("title"))
                or (details.title if details else "")
            ),
            filename=(
                _text(item.get("knowledge_filename"))
                or _text(item.get("file_name"))
                or _text(item.get("filename"))
                or _text(file_item.get("file_name"))
                or (details.file_name if details else "")
            ),
            folder_path=(
                _text(item.get("folder_path"))
                or _text(file_item.get("folder_path"))
                or (details.folder_path if details else "")
            ),
            content=(
                _text(item.get("content"))
                or _text(item.get("content_snippet"))
            ),
            score=(
                _number(item.get("score"))
                if item.get("score") is not None
                else None
            ),
            chunk_index=(
                _integer(item.get("chunk_index"))
                if item.get("chunk_index") is not None
                else None
            ),
            start_at=(
                _integer(item.get("start_at"))
                if item.get("start_at") is not None
                else None
            ),
            end_at=(
                _integer(item.get("end_at"))
                if item.get("end_at") is not None
                else None
            ),
            match_type=_text(item.get("match_type")),
            chunk_type=_text(item.get("chunk_type")),
            knowledge_channel=(
                _text(item.get("knowledge_channel"))
                or _text(item.get("channel"))
                or (details.channel if details else "")
            ),
            file_type=(
                _text(item.get("file_type"))
                or _text(file_item.get("file_type"))
                or (details.file_type if details else "")
            ),
            file_size=(
                details.file_size
                if details is not None
                else (
                    _integer(item.get("file_size"))
                    if item.get("file_size") is not None
                    else None
                )
            ),
            source=(
                _text(item.get("knowledge_source"))
                or _text(item.get("source"))
                or (details.source if details else "")
            ),
            knowledge_type=(
                _text(item.get("knowledge_type"))
                or (details.type if details else "")
            ),
            parse_status=(
                _text(item.get("parse_status"))
                or (details.parse_status if details else "")
            ),
            download_url=(
                f"/agent/platform/weknora/knowledge/"
                f"{quote(knowledge_id, safe='')}/download"
                if knowledge_id
                else ""
            ),
            preview_url=(
                f"/agent/platform/weknora/knowledge/"
                f"{quote(knowledge_id, safe='')}/preview"
                if knowledge_id
                else ""
            ),
        ).model_dump()
        references.append(reference)
    return references


def _weknora_mutation_result(
    payload: dict,
    *,
    default_message: str,
) -> WeKnoraKnowledgeMutationResponse:
    """Normalise the response shared by file and URL ingestion."""

    data = payload.get("data")
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WeKnora 入库响应结构无效。",
        )
    knowledge_id = _text(data.get("id"))
    if not knowledge_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WeKnora 入库成功响应缺少知识 ID。",
        )
    return WeKnoraKnowledgeMutationResponse(
        knowledge_id=knowledge_id,
        file_name=_text(data.get("file_name")),
        title=_text(data.get("title")),
        parse_status=_text(data.get("parse_status")),
        message=_text(payload.get("message")) or default_message,
    )


async def _probe_weknora(
    config: WeKnoraConnectionConfig,
) -> int:
    knowledge_base_count = len(await _fetch_weknora_knowledge_bases(config))
    return knowledge_base_count


def _is_initialization_validation_package(record: MCPPackageRecord) -> bool:
    """Whether one package version satisfies the platform validation slot."""
    return (
        PROJECT_INITIALIZATION_VALIDATION_CAPABILITY
        in record.manifest.platform_capabilities
        and len(record.tools) == 1
    )


async def _migrate_initialization_validation_binding(
    settings: PlatformSettingsRecord,
    *,
    storage: StorageBase,
    user_id: str,
    manager: MCPRegistryManager,
) -> PlatformSettingsRecord:
    """Bind the sole legacy validator package once, without naming it."""
    if settings.data.project_initializer_validation_mcp is not None:
        return settings
    candidates = [
        record
        for record in await manager.list_records()
        if _is_initialization_validation_package(record)
    ]
    if len(candidates) != 1:
        return settings
    record = candidates[0]
    data = settings.data.model_copy(
        update={
            "project_initializer_validation_mcp": PlatformMCPVersionBinding(
                package_id=record.id,
                version=record.manifest.version,
            ),
        },
    )
    return await storage.upsert_platform_settings(user_id, data)


def _normalise_platform_agent_data(data: AgentData) -> AgentData:
    """Apply invariants implied by an agent's platform role."""
    platform_config = data.platform_config
    updates = {}
    if platform_config.role == "global_main" and data.call_config.scope != "all":
        updates["call_config"] = data.call_config.model_copy(
            update={"scope": "all"},
        )
    if platform_config.role == "system_internal" and platform_config.published:
        updates["platform_config"] = platform_config.model_copy(
            update={"published": False},
        )
    return data.model_copy(update=updates) if updates else data


async def _demote_other_global_main_agents(
    storage: StorageBase,
    global_config_id: str,
    selected_agent_id: str,
) -> None:
    """Keep exactly one global-main agent in the platform configuration."""
    for record in await storage.list_agents(global_config_id):
        if (
            record.id == selected_agent_id
            or record.data.platform_config.role != "global_main"
        ):
            continue
        demoted_config = record.data.platform_config.model_copy(
            update={"role": "business"},
        )
        demoted_call_config = record.data.call_config.model_copy(
            update={"scope": "selected"},
        )
        demoted = record.model_copy(
            update={
                "data": record.data.model_copy(
                    update={
                        "platform_config": demoted_config,
                        "call_config": demoted_call_config,
                    },
                ),
                "updated_at": datetime.now(),
            },
        )
        await storage.upsert_agent(global_config_id, demoted)


async def _synchronise_global_main_agent_roles(
    storage: StorageBase,
    global_config_id: str,
    selected_agent_id: str | None,
) -> None:
    """Mirror the authoritative pointer into legacy per-agent role fields.

    The pointer in :class:`PlatformSettingsData` is authoritative. Keeping the
    old role field synchronized preserves wire compatibility with older
    clients while ensuring there is never more than one derived
    ``global_main`` role.
    """
    for record in await storage.list_agents(global_config_id):
        current_role = record.data.platform_config.role
        desired_role = (
            "global_main"
            if record.id == selected_agent_id
            else ("business" if current_role == "global_main" else current_role)
        )
        if record.id == selected_agent_id:
            desired_scope = "all"
        elif current_role == "global_main":
            # A former main must not retain its platform-wide privilege.
            # Keep any explicit IDs so the admin can reuse the old whitelist.
            desired_scope = "selected"
        else:
            desired_scope = record.data.call_config.scope
        if (
            desired_role == current_role
            and desired_scope == record.data.call_config.scope
        ):
            continue
        platform_config = record.data.platform_config.model_copy(
            update={"role": desired_role},
        )
        call_config = record.data.call_config.model_copy(
            update={"scope": desired_scope},
        )
        updated = record.model_copy(
            update={
                "data": record.data.model_copy(
                    update={
                        "platform_config": platform_config,
                        "call_config": call_config,
                    },
                ),
                "updated_at": datetime.now(),
            },
        )
        await storage.upsert_agent(global_config_id, updated)


async def _synchronise_project_initializer_role(
    storage: StorageBase,
    global_config_id: str,
    selected_agent_id: str | None,
) -> None:
    """Keep the selected initializer hidden with an explicit allowlist."""
    if selected_agent_id is None:
        return
    record = await storage.get_agent(global_config_id, selected_agent_id)
    if record is None:
        return
    platform_config = record.data.platform_config
    call_config = record.data.call_config
    if (
        platform_config.role == "system_internal"
        and not platform_config.published
        and call_config.scope == "selected"
    ):
        return
    updated = record.model_copy(
        update={
            "data": record.data.model_copy(
                update={
                    "platform_config": platform_config.model_copy(
                        update={
                            "role": "system_internal",
                            "published": False,
                        },
                    ),
                    "call_config": call_config.model_copy(
                        update={"scope": "selected"},
                    ),
                },
            ),
            "updated_at": datetime.now(),
        },
    )
    await storage.upsert_agent(global_config_id, updated)


async def _load_platform_settings(
    storage: StorageBase,
    global_config_id: str,
) -> PlatformSettingsRecord:
    """Load settings and migrate the former per-agent main role once."""
    existing = await storage.get_platform_settings(global_config_id)
    if existing is not None:
        await _synchronise_global_main_agent_roles(
            storage,
            global_config_id,
            existing.data.global_main_agent_id,
        )
        await _synchronise_project_initializer_role(
            storage,
            global_config_id,
            existing.data.project_initializer_agent_id,
        )
        return existing

    records = await storage.list_agents(global_config_id)
    legacy_candidates = sorted(
        (
            record
            for record in records
            if record.data.platform_config.role == "global_main"
        ),
        key=lambda record: (
            not record.data.platform_config.enabled,
            record.data.platform_config.sort_order,
            record.data.name,
            record.id,
        ),
    )
    selected_id = legacy_candidates[0].id if legacy_candidates else None
    data = PlatformSettingsData(global_main_agent_id=selected_id)
    try:
        settings = await storage.upsert_platform_settings(
            global_config_id,
            data,
        )
    except NotImplementedError:
        settings = PlatformSettingsRecord(
            user_id=global_config_id,
            data=data,
        )
    await _synchronise_global_main_agent_roles(
        storage,
        global_config_id,
        selected_id,
    )
    await _synchronise_project_initializer_role(
        storage,
        global_config_id,
        data.project_initializer_agent_id,
    )
    return settings


def _catalog_item(agent: AgentView) -> PlatformAgentCatalogItem:
    config = agent.data.platform_config
    description = (
        (config.description or "").strip()
        or (agent.data.invite_config.invite_description or "").strip()
        or "暂无业务说明"
    )
    permission_mode = config.permission_mode
    return PlatformAgentCatalogItem(
        id=agent.id,
        name=agent.data.name,
        description=description,
        category=config.category.strip() or "通用",
        role=config.role,
        enabled=config.enabled,
        published=config.published,
        invitable=bool(agent.data.invite_config.invitable),
        model_ready=(
            agent.data.model_policy.mode == "fixed"
            and agent.data.model_policy.chat_model_config is not None
        ),
        sort_order=config.sort_order,
        permission_mode=getattr(permission_mode, "value", permission_mode),
        knowledge_config=config.knowledge_config,
        initialization_role=config.initialization_role,
    )


async def _validate_model_policy(
    user_id: str,
    policy: AgentModelPolicy,
    access: ResourceAccessService,
) -> AgentModelPolicy:
    """Validate and normalize an agent's fixed model configuration."""
    if policy.mode != "fixed" or policy.chat_model_config is None:
        return policy

    config = policy.chat_model_config
    record = await access.resolve_credential(
        user_id,
        config.credential_id,
    )
    credential = CredentialFactory.from_dict(record.data)
    credential_type = getattr(credential, "type", None)
    if config.type != credential_type:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Agent model provider type does not match the selected "
                "credential."
            ),
        )

    candidate = next(
        (
            model
            for model in build_credential_model_catalog(credential)
            if model.name == config.model
        ),
        None,
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Model {config.model!r} is not present in the selected "
                "credential."
            ),
        )

    try:
        parameters = normalize_credential_model_parameters(
            credential,
            config.model,
            config.parameters,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return policy.model_copy(
        update={
            "chat_model_config": config.model_copy(
                update={"parameters": parameters},
            ),
        },
    )


@agent_router.get(
    "/schema",
    response_model=AgentSchemaResponse,
    deprecated=True,
    summary="[Deprecated] Legacy sectioned schema — use /schema/v2",
)
async def get_agent_schema() -> AgentSchemaResponse:
    """Return the legacy sectioned JSON Schema fragments.

    .. deprecated::
        Superseded by :func:`get_agent_schema_v2`, which returns the
        full :class:`AgentData` schema in a single ``schema`` field.
        Kept for backwards compatibility with existing API consumers.
        New consumers should call ``GET /agent/schema/v2``.

    The frontend previously used three sections — identity, context
    config, and react config — so we return them as separate
    self-contained schemas rather than a single :class:`AgentData`
    schema with ``$ref`` s.

    Returns:
        `AgentSchemaResponse`:
            Schemas for the three form sections.
    """
    # Slice ``AgentData``'s schema down to the identity-relevant fields.
    # Going through ``AgentData.model_json_schema()`` (rather than building
    # a dict by hand) keeps Pydantic as the single source of truth for
    # defaults, titles, descriptions, and the ``format: textarea`` hint.
    agent_schema = AgentData.model_json_schema()
    identity_keys = ("name", "system_prompt")
    identity = {
        "type": "object",
        "title": "Identity",
        "properties": {
            k: v
            for k, v in agent_schema.get("properties", {}).items()
            if k in identity_keys
        },
        "required": [
            r for r in agent_schema.get("required", []) if r in identity_keys
        ],
    }

    context_schema = ContextConfig.model_json_schema()
    # Dobby owns compression as one platform-wide policy. Keep only the
    # genuinely agent-specific context option in the agent editor.
    for memory_owned_field in (
        "trigger_ratio",
        "reserve_ratio",
        "compression_prompt",
        "summary_template",
        "summary_schema",
    ):
        context_schema.get("properties", {}).pop(memory_owned_field, None)

    return AgentSchemaResponse(
        identity=identity,
        context_config=context_schema,
        react_config=ReActConfig.model_json_schema(),
    )


@agent_router.get(
    "/schema/v2",
    response_model=AgentSchemaV2Response,
    summary="Full AgentData JSON Schema for the agent form",
)
async def get_agent_schema_v2() -> AgentSchemaV2Response:
    """Return the full :class:`AgentData` JSON Schema.

    Superset of the legacy sectioned endpoint. The response body is a
    single ``schema`` field carrying the whole Pydantic-generated
    schema of :class:`AgentData`, with two curated exclusions handled
    at the model layer (so no post-processing is needed here):

    - ``id``: server-assigned, marked :class:`SkipJsonSchema` on
      :attr:`AgentData.id`.
    - ``context_config.summary_schema``: internal structured-output
      spec for the compression model, dropped below since it is not
      user-editable and there is no equivalent hook on the Pydantic
      side.

    ``$ref`` inlining is delegated to
    :func:`~agentscope._utils._common._flatten_json_schema` so the
    frontend can render every property from the response body alone.

    The frontend derives its section grouping (identity / context /
    react / invite) directly from this schema — top-level scalar
    properties are the "identity" section, and top-level nested-object
    properties each become their own section. Adding a new
    user-editable field to :class:`AgentData` is thus enough to have it
    appear in the create / edit form without a router change.

    Returns:
        `AgentSchemaV2Response`:
            ``schema`` = the full :class:`AgentData` JSON Schema.
    """
    schema = _flatten_json_schema(AgentData.model_json_schema())
    # Compression is configured once from the dedicated Memory Settings
    # page. The agent editor retains only tool_result_limit.
    context_config = schema.get("properties", {}).get("context_config", {})
    for memory_owned_field in (
        "trigger_ratio",
        "reserve_ratio",
        "compression_prompt",
        "summary_template",
        "summary_schema",
    ):
        context_config.get("properties", {}).pop(memory_owned_field, None)
    return AgentSchemaV2Response(schema=schema)


@agent_router.get(
    "/",
    response_model=ListAgentsResponse,
    summary="List all agents",
)
async def list_agents(
    user_id: str = Depends(get_current_user_id),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> ListAgentsResponse:
    """Return all agent records visible to the authenticated user.

    Includes the caller's own ``source == "user"`` agents plus any agents
    shared to them through :class:`ResourceAccessPolicyBase`. Each entry
    carries an ``editable`` flag indicating whether the caller may
    PATCH/DELETE it.

    Args:
        user_id (`str`):
            Injected authenticated user ID.
        access (`ResourceAccessService`):
            Injected resource access service.

    Returns:
        `ListAgentsResponse`:
            All visible agent records paired with per-viewer editability.
    """
    entries = await access.list_resource(user_id, ResourceKind.AGENT)
    return ListAgentsResponse(agents=entries, total=len(entries))


@agent_router.get(
    "/platform/catalog",
    response_model=PlatformAgentCatalogResponse,
    summary="Published agent catalogue for the engineering platform",
)
async def get_platform_agent_catalog(
    user_id: str = Depends(get_current_user_id),
    access: ResourceAccessService = Depends(get_resource_access_service),
    storage: StorageBase = Depends(get_storage),
) -> PlatformAgentCatalogResponse:
    """Return the configured global main agent and published business agents.

    The response intentionally excludes prompts, credentials, and provider
    parameters.  It is the stable contract consumed by the engineering
    platform's backend gateway.
    """
    settings = await _load_platform_settings(storage, user_id)
    selected_id = settings.data.global_main_agent_id
    initializer_id = settings.data.project_initializer_agent_id
    entries = await access.list_resource(user_id, ResourceKind.AGENT)
    items = [_catalog_item(entry) for entry in entries]
    selected_item = next(
        (
            item
            for item in items
            if item.id == selected_id and item.enabled
        ),
        None,
    )
    if selected_item is not None:
        selected_item = selected_item.model_copy(
            update={"role": "global_main", "published": False},
        )
    initializer_item = next(
        (
            item
            for item in items
            if item.id == initializer_id
            and item.id != selected_id
            and item.enabled
        ),
        None,
    )
    if initializer_item is not None:
        initializer_item = initializer_item.model_copy(
            update={"role": "system_internal", "published": False},
        )
    business_agents = sorted(
        (
            item
            for item in items
            if item.id != selected_id
            and item.id != initializer_id
            and item.role == "business"
            and item.enabled
            and item.published
        ),
        key=lambda item: (item.sort_order, item.name, item.id),
    )
    initialization_workers = sorted(
        (
            item
            for item in items
            if item.id != initializer_id
            and item.role == "system_internal"
            and item.enabled
            and item.initialization_role in {
                "project",
                "personnel",
                "wbs",
                "risks",
                "quality_requirements",
                "validator",
            }
        ),
        key=lambda item: (item.sort_order, item.name, item.id),
    )
    return PlatformAgentCatalogResponse(
        global_main=selected_item,
        project_initializer=initializer_item,
        initialization_workers=initialization_workers,
        business_agents=business_agents,
        total=len(business_agents),
    )


@agent_router.get(
    "/platform/settings",
    response_model=PlatformSettingsResponse,
    summary="Get platform-wide AgentScope settings",
)
async def get_platform_settings(
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    manager: MCPRegistryManager = Depends(get_mcp_registry_manager),
) -> PlatformSettingsResponse:
    """Return the global settings shared by the whole platform."""
    settings = await _load_platform_settings(storage, user_id)
    settings = await _migrate_initialization_validation_binding(
        settings,
        storage=storage,
        user_id=user_id,
        manager=manager,
    )
    return PlatformSettingsResponse(
        global_main_agent_id=settings.data.global_main_agent_id,
        project_initializer_agent_id=(
            settings.data.project_initializer_agent_id
        ),
        project_initializer_validation_mcp=(
            settings.data.project_initializer_validation_mcp
        ),
        engineering_document_agent_id=(
            settings.data.engineering_document_agent_id
        ),
    )


async def _validate_memory_model_config(
    user_id: str,
    config: ChatModelConfig | None,
    access: ResourceAccessService,
) -> ChatModelConfig | None:
    """Validate and normalize the optional global memory model."""

    if config is None:
        return None

    record = await access.resolve_credential(user_id, config.credential_id)
    credential = CredentialFactory.from_dict(record.data)
    credential_type = getattr(credential, "type", None)
    if config.type != credential_type:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="记忆处理模型与所选凭证类型不匹配。",
        )

    candidate = next(
        (
            model
            for model in build_credential_model_catalog(credential)
            if model.name == config.model and model.enabled
        ),
        None,
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="所选记忆处理模型在该凭证中不存在或已被停用。",
        )

    try:
        parameters = normalize_credential_model_parameters(
            credential,
            config.model,
            config.parameters,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    normalized = config.model_copy(update={"parameters": parameters})
    try:
        from ..memory import build_memory_model_runtime_config

        build_memory_model_runtime_config(
            normalized,
            credential,
            context_size=candidate.context_size,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return normalized


@agent_router.get(
    "/platform/memory-settings",
    response_model=MemorySettingsResponse,
    summary="Get platform-wide Dobby memory settings",
)
async def get_memory_settings(
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> MemorySettingsResponse:
    """Return the active versioned memory policy and safe infrastructure."""

    settings = await _load_platform_settings(storage, user_id)
    return _memory_settings_response(settings)


@agent_router.put(
    "/platform/memory-settings",
    response_model=MemorySettingsResponse,
    summary="Update platform-wide Dobby memory settings",
)
async def update_memory_settings(
    body: UpdateMemorySettingsRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> MemorySettingsResponse:
    """Atomically replace memory policy while preserving other settings."""

    current = await _load_platform_settings(storage, user_id)
    _check_memory_settings_revision(
        body.expected_revision,
        current.data.memory_settings_revision,
    )
    memory_model_config = await _validate_memory_model_config(
        user_id,
        body.settings.memory_model_config,
        access,
    )
    normalized_settings = body.settings.model_copy(
        update={"memory_model_config": memory_model_config},
    )
    updated_data = current.data.model_copy(
        update={
            "memory_settings": normalized_settings,
            "memory_settings_revision": (
                current.data.memory_settings_revision + 1
            ),
        },
    )
    updated = await storage.upsert_platform_settings(user_id, updated_data)
    return _memory_settings_response(updated)


@agent_router.post(
    "/platform/memory-settings/reset",
    response_model=MemorySettingsResponse,
    summary="Restore reference-branch Dobby memory defaults",
)
async def reset_memory_settings(
    body: ResetMemorySettingsRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> MemorySettingsResponse:
    """Restore the integrated Dobby memory defaults."""

    current = await _load_platform_settings(storage, user_id)
    _check_memory_settings_revision(
        body.expected_revision,
        current.data.memory_settings_revision,
    )
    updated_data = current.data.model_copy(
        update={
            "memory_settings": MemorySettingsData(),
            "memory_settings_revision": (
                current.data.memory_settings_revision + 1
            ),
        },
    )
    updated = await storage.upsert_platform_settings(user_id, updated_data)
    return _memory_settings_response(updated)


@agent_router.get(
    "/platform/weknora-connection",
    response_model=WeKnoraConnectionResponse,
    summary="Get the independently managed WeKnora connection",
)
async def get_weknora_connection(
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> WeKnoraConnectionResponse:
    settings = await _load_platform_settings(storage, user_id)
    return _weknora_response(settings.data.weknora_connection)


@agent_router.get(
    "/platform/weknora-connection/api-key",
    response_model=WeKnoraApiKeyResponse,
    summary="Reveal the saved WeKnora API key on explicit admin request",
)
async def reveal_weknora_api_key(
    response: Response,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> WeKnoraApiKeyResponse:
    settings = await _load_platform_settings(storage, user_id)
    connection = _require_weknora_connection(settings)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return WeKnoraApiKeyResponse(
        api_key=connection.api_key.get_secret_value(),
    )


@agent_router.put(
    "/platform/weknora-connection",
    response_model=WeKnoraConnectionResponse,
    summary="Save the independently managed WeKnora connection",
)
async def update_weknora_connection(
    body: UpdateWeKnoraConnectionRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> WeKnoraConnectionResponse:
    current = await _load_platform_settings(storage, user_id)
    connection = _build_weknora_config(
        body,
        current.data.weknora_connection,
    )
    updated_data = current.data.model_copy(
        update={"weknora_connection": connection},
    )
    settings = await storage.upsert_platform_settings(user_id, updated_data)
    return _weknora_response(settings.data.weknora_connection)


@agent_router.post(
    "/platform/weknora-connection/test",
    response_model=TestWeKnoraConnectionResponse,
    summary="Test a WeKnora connection by listing knowledge bases",
)
async def test_weknora_connection(
    body: TestWeKnoraConnectionRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> TestWeKnoraConnectionResponse:
    current = await _load_platform_settings(storage, user_id)
    connection = _build_weknora_config(
        body,
        current.data.weknora_connection,
    )
    knowledge_base_count = await _probe_weknora(connection)
    return TestWeKnoraConnectionResponse(
        success=True,
        knowledge_base_count=knowledge_base_count,
        message=(
            f"连接成功，读取到 {knowledge_base_count} 个知识库。"
        ),
    )


@agent_router.get(
    "/platform/weknora/project-bindings",
    response_model=ListWeKnoraProjectBindingsResponse,
    summary="List engineering projects and their WeKnora robots",
)
async def list_weknora_project_bindings(
    user_id: str = Depends(get_current_user_id),
) -> ListWeKnoraProjectBindingsResponse:
    del user_id
    data = await _request_dobby_project_bindings()
    if not isinstance(data, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="工程管理业务后端返回的项目列表结构无效。",
        )
    projects = [
        WeKnoraProjectBindingItem.model_validate(item)
        for item in data
        if isinstance(item, dict)
    ]
    return ListWeKnoraProjectBindingsResponse(
        projects=projects,
        total=len(projects),
    )


@agent_router.put(
    "/platform/weknora/project-bindings/{project_id}",
    response_model=WeKnoraProjectBindingItem,
    summary="Assign a WeKnora robot to one engineering project",
)
async def update_weknora_project_binding(
    project_id: int,
    body: UpdateWeKnoraProjectBindingRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> WeKnoraProjectBindingItem:
    agent_id = (body.weknora_agent_id or "").strip()
    if agent_id:
        settings = await _load_platform_settings(storage, user_id)
        connection = _require_weknora_connection(settings)
        _, _, knowledge_base_ids = await _fetch_weknora_agent(
            connection,
            agent_id,
        )
        if not knowledge_base_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="该 WeKnora 机器人没有配置可读取的知识库。",
            )
    data = await _request_dobby_project_bindings(
        f"/{project_id}",
        method="PUT",
        json_body={"weknora_agent_id": agent_id or None},
    )
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="工程管理业务后端返回的绑定结果结构无效。",
        )
    return WeKnoraProjectBindingItem.model_validate(data)


@agent_router.get(
    "/platform/weknora/knowledge-bases",
    response_model=ListWeKnoraKnowledgeBasesResponse,
    summary="List knowledge bases from the configured WeKnora tenant",
)
async def list_weknora_knowledge_bases(
    weknora_agent_id: str | None = Query(default=None, max_length=128),
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> ListWeKnoraKnowledgeBasesResponse:
    settings = await _load_platform_settings(storage, user_id)
    connection = _require_weknora_connection(settings)
    allowed_ids = await _weknora_agent_knowledge_base_ids(
        connection,
        weknora_agent_id,
    )
    knowledge_bases = await _fetch_weknora_knowledge_bases(connection)
    if allowed_ids is not None:
        by_id = {item.id: item for item in knowledge_bases}
        knowledge_bases = [by_id[item_id] for item_id in allowed_ids if item_id in by_id]
    return ListWeKnoraKnowledgeBasesResponse(
        knowledge_bases=knowledge_bases,
        total=len(knowledge_bases),
    )


@agent_router.get(
    "/platform/weknora/knowledge-bases/{knowledge_base_id}/knowledge/folders",
    response_model=WeKnoraFolderTreeResponse,
    summary="Load WeKnora's documented folder hierarchy",
)
async def get_weknora_folder_tree(
    knowledge_base_id: str,
    weknora_agent_id: str | None = Query(default=None, max_length=128),
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> WeKnoraFolderTreeResponse:
    settings = await _load_platform_settings(storage, user_id)
    connection = _require_weknora_connection(settings)
    _require_weknora_knowledge_base_access(
        knowledge_base_id,
        await _weknora_agent_knowledge_base_ids(connection, weknora_agent_id),
    )
    return await _fetch_weknora_folder_tree(
        connection,
        knowledge_base_id,
    )


@agent_router.post(
    "/platform/weknora/knowledge-bases/{knowledge_base_id}/knowledge/folders",
    response_model=WeKnoraKnowledgeMutationResponse,
    summary="Create a persistent WeKnora folder with an empty marker",
)
async def create_weknora_folder(
    knowledge_base_id: str,
    body: CreateWeKnoraFolderRequest,
    weknora_agent_id: str | None = Query(default=None, max_length=128),
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> WeKnoraKnowledgeMutationResponse:
    settings = await _load_platform_settings(storage, user_id)
    connection = _require_weknora_connection(settings)
    _require_weknora_knowledge_base_access(
        knowledge_base_id,
        await _weknora_agent_knowledge_base_ids(connection, weknora_agent_id),
    )
    folder_path = _validate_weknora_folder_path(body.folder_path)
    tree = await _fetch_weknora_folder_tree(connection, knowledge_base_id)

    def collect_paths(nodes: list[WeKnoraFolderItem]) -> set[str]:
        paths: set[str] = set()
        for node in nodes:
            paths.add(_normalise_weknora_folder_path(node.path))
            paths.update(collect_paths(node.children))
        return paths

    if folder_path in collect_paths(tree.folders):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该文件夹已经存在。",
        )
    encoded_id = quote(knowledge_base_id, safe="")
    payload = await _request_weknora_json(
        connection,
        f"/knowledge-bases/{encoded_id}/knowledge/file",
        method="POST",
        data={
            "enable_multimodel": "false",
            "channel": "api",
            # The current WeKnora deployment exposes ``folder_path`` on
            # reads but still derives a newly-created path from ``fileName``
            # during uploads.  Send both representations: current releases
            # consume ``folder_path`` while the deployed build consumes the
            # path-qualified fileName.
            "fileName": (
                f"{folder_path}/{WEKNORA_FOLDER_PLACEHOLDER_FILENAME}"
            ),
            "folder_path": folder_path,
        },
        files={
            "file": (
                WEKNORA_FOLDER_PLACEHOLDER_FILENAME,
                b"",
                WEKNORA_FOLDER_PLACEHOLDER_CONTENT_TYPE,
            ),
        },
        timeout_seconds=120.0,
    )
    return _weknora_mutation_result(
        payload,
        default_message="文件夹已创建。",
    )


@agent_router.delete(
    "/platform/weknora/knowledge-bases/{knowledge_base_id}/knowledge/folders",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one WeKnora folder and optionally all nested content",
)
async def delete_weknora_folder(
    knowledge_base_id: str,
    folder_path: str = Query(min_length=1, max_length=4096),
    recursive: bool = False,
    weknora_agent_id: str | None = Query(default=None, max_length=128),
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> Response:
    settings = await _load_platform_settings(storage, user_id)
    connection = _require_weknora_connection(settings)
    _require_weknora_knowledge_base_access(
        knowledge_base_id,
        await _weknora_agent_knowledge_base_ids(connection, weknora_agent_id),
    )
    normalised_path = _validate_weknora_folder_path(folder_path)
    tree = await _fetch_weknora_folder_tree(connection, knowledge_base_id)

    def find_folder(
        nodes: list[WeKnoraFolderItem],
    ) -> WeKnoraFolderItem | None:
        for node in nodes:
            if _normalise_weknora_folder_path(node.path) == normalised_path:
                return node
            matched = find_folder(node.children)
            if matched is not None:
                return matched
        return None

    folder = find_folder(tree.folders)
    if folder is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件夹不存在。",
        )
    if (
        not recursive
        and (
            folder.document_count > 0
            or folder.total_count > 0
            or folder.children
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="只能删除空目录，请先移走其中的资料和子目录。",
        )

    placeholders = await _fetch_weknora_folder_placeholders(
        connection,
        knowledge_base_id,
    )
    nested_prefix = f"{normalised_path}/"
    scoped_markers = [
        item
        for item in placeholders
        if (
            _normalise_weknora_folder_path(item.folder_path)
            == normalised_path
            or (
                recursive
                and _normalise_weknora_folder_path(item.folder_path).startswith(
                    nested_prefix,
                )
            )
        )
    ]

    if not recursive:
        if not scoped_markers:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该空目录不是由平台占位文件创建，当前无法安全删除。",
            )
        for marker in scoped_markers:
            await _request_weknora_json(
                connection,
                f"/knowledge/{quote(marker.id, safe='')}",
                method="DELETE",
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    encoded_id = quote(knowledge_base_id, safe="")
    page_size = 100
    seen_remote_items = 0
    knowledge_ids: list[str] = []
    seen_knowledge_ids: set[str] = set()
    for page in range(1, 10001):
        payload = await _request_weknora_json(
            connection,
            f"/knowledge-bases/{encoded_id}/knowledge",
            params={
                "page": page,
                "page_size": page_size,
                "folder_path": normalised_path,
                "folder_recursive": "true",
            },
        )
        raw_items, metadata = _weknora_list_payload(payload)
        seen_remote_items += len(raw_items)
        for item in raw_items:
            item_id = _text(item.get("id"))
            item_path = _normalise_weknora_folder_path(item.get("folder_path"))
            if (
                not item_id
                or item_id in seen_knowledge_ids
                or _is_weknora_folder_placeholder(item)
                or not (
                    item_path == normalised_path
                    or item_path.startswith(nested_prefix)
                )
            ):
                continue
            seen_knowledge_ids.add(item_id)
            knowledge_ids.append(item_id)
        raw_total = _integer(metadata.get("total"), seen_remote_items)
        if (
            not raw_items
            or len(raw_items) < page_size
            or seen_remote_items >= raw_total
        ):
            break

    if not knowledge_ids and not scoped_markers:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该目录没有可删除的资料或平台占位文件。",
        )

    for knowledge_id in knowledge_ids:
        await _request_weknora_json(
            connection,
            f"/knowledge/{quote(knowledge_id, safe='')}",
            method="DELETE",
        )
    for marker in sorted(
        scoped_markers,
        key=lambda item: _normalise_weknora_folder_path(
            item.folder_path,
        ).count("/"),
        reverse=True,
    ):
        await _request_weknora_json(
            connection,
            f"/knowledge/{quote(marker.id, safe='')}",
            method="DELETE",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@agent_router.put(
    "/platform/weknora/knowledge-bases/{knowledge_base_id}/knowledge/folders",
    summary="Rename or move a WeKnora folder",
)
async def update_weknora_folder(
    knowledge_base_id: str,
    body: UpdateWeKnoraFolderRequest,
    weknora_agent_id: str | None = Query(default=None, max_length=128),
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> dict:
    settings = await _load_platform_settings(storage, user_id)
    connection = _require_weknora_connection(settings)
    _require_weknora_knowledge_base_access(
        knowledge_base_id,
        await _weknora_agent_knowledge_base_ids(connection, weknora_agent_id),
    )
    source_path = body.source_path.strip().strip("/")
    target_path = body.target_path.strip().strip("/")
    if not source_path or not target_path or source_path == target_path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="文件夹原路径和目标路径必须有效且不能相同。",
        )
    return await _request_weknora_json(
        connection,
        f"/knowledge-bases/{quote(knowledge_base_id, safe='')}/knowledge/folders",
        method="PUT",
        json_body={"from": source_path, "to": target_path},
    )


@agent_router.post(
    "/platform/weknora/knowledge-bases/{knowledge_base_id}/knowledge/move",
    summary="Move WeKnora knowledge items to a folder",
)
async def move_weknora_knowledge(
    knowledge_base_id: str,
    body: MoveWeKnoraKnowledgeRequest,
    weknora_agent_id: str | None = Query(default=None, max_length=128),
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> dict:
    settings = await _load_platform_settings(storage, user_id)
    connection = _require_weknora_connection(settings)
    allowed_ids = await _weknora_agent_knowledge_base_ids(
        connection,
        weknora_agent_id,
    )
    _require_weknora_knowledge_base_access(knowledge_base_id, allowed_ids)
    knowledge_ids = list(dict.fromkeys(body.knowledge_ids))
    for knowledge_id in knowledge_ids:
        item = await _require_weknora_knowledge_access(
            connection,
            knowledge_id,
            allowed_ids,
        )
        if item.knowledge_base_id != knowledge_base_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="待移动资料不属于目标知识库。",
            )
    return await _request_weknora_json(
        connection,
        "/knowledge/folder",
        method="POST",
        json_body={
            "kb_id": knowledge_base_id,
            "knowledge_ids": knowledge_ids,
            "folder_path": body.folder_path.strip().strip("/"),
        },
    )


@agent_router.get(
    "/platform/weknora/knowledge-bases/{knowledge_base_id}/knowledge",
    response_model=ListWeKnoraKnowledgeResponse,
    summary="List engineering content from one WeKnora knowledge base",
)
async def list_weknora_knowledge(
    knowledge_base_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    folder_path: str | None = Query(default=None, max_length=4096),
    folder_recursive: bool = Query(default=True),
    keyword: str = Query(default="", max_length=512),
    weknora_agent_id: str | None = Query(default=None, max_length=128),
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> ListWeKnoraKnowledgeResponse:
    settings = await _load_platform_settings(storage, user_id)
    connection = _require_weknora_connection(settings)
    _require_weknora_knowledge_base_access(
        knowledge_base_id,
        await _weknora_agent_knowledge_base_ids(connection, weknora_agent_id),
    )
    knowledge, total = await _fetch_weknora_knowledge(
        connection,
        knowledge_base_id,
        page=page,
        page_size=page_size,
        folder_path=folder_path,
        folder_recursive=folder_recursive,
        keyword=keyword.strip(),
    )
    return ListWeKnoraKnowledgeResponse(
        knowledge=knowledge,
        total=total,
        page=page,
        page_size=page_size,
    )


@agent_router.post(
    "/platform/weknora/knowledge-bases/{knowledge_base_id}/search",
    response_model=SearchWeKnoraKnowledgeResponse,
    summary="Run WeKnora hybrid search with source metadata",
)
async def search_weknora_knowledge(
    knowledge_base_id: str,
    body: SearchWeKnoraKnowledgeRequest,
    weknora_agent_id: str | None = Query(default=None, max_length=128),
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> SearchWeKnoraKnowledgeResponse:
    settings = await _load_platform_settings(storage, user_id)
    connection = _require_weknora_connection(settings)
    _require_weknora_knowledge_base_access(
        knowledge_base_id,
        await _weknora_agent_knowledge_base_ids(connection, weknora_agent_id),
    )
    references = await _search_weknora_knowledge(
        connection,
        knowledge_base_id,
        body,
    )
    return SearchWeKnoraKnowledgeResponse(
        query=body.query,
        total=len(references),
        references=references,
    )


@agent_router.post(
    "/platform/weknora/knowledge-bases/{knowledge_base_id}/knowledge/file",
    response_model=WeKnoraKnowledgeMutationResponse,
    summary="Proxy a file upload to WeKnora",
)
async def upload_weknora_knowledge(
    knowledge_base_id: str,
    file: UploadFile = File(...),
    enable_multimodel: bool = Form(default=True),
    folder_path: str = Form(default="", max_length=4096),
    weknora_agent_id: str | None = Query(default=None, max_length=128),
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> WeKnoraKnowledgeMutationResponse:
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="请选择需要上传的文件。",
        )
    document_filename = file.filename.replace("\\", "/").rsplit("/", 1)[-1]
    if not document_filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="上传文件名无效。",
        )
    if document_filename.casefold() == (
        WEKNORA_FOLDER_PLACEHOLDER_FILENAME.casefold()
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="该文件名由系统保留用于维护资料目录。",
        )
    max_upload_bytes = 50 * 1024 * 1024
    content = await file.read(max_upload_bytes + 1)
    await file.close()
    if len(content) > max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="上传文件不能超过 50 MB。",
        )
    settings = await _load_platform_settings(storage, user_id)
    connection = _require_weknora_connection(settings)
    _require_weknora_knowledge_base_access(
        knowledge_base_id,
        await _weknora_agent_knowledge_base_ids(connection, weknora_agent_id),
    )
    encoded_id = quote(knowledge_base_id, safe="")
    normalised_folder_path = folder_path.strip().strip("/")
    upload_data = {
        "enable_multimodel": str(enable_multimodel).lower(),
        "channel": "api",
        "fileName": document_filename,
    }
    if normalised_folder_path:
        upload_data["folder_path"] = normalised_folder_path
    payload = await _request_weknora_json(
        connection,
        f"/knowledge-bases/{encoded_id}/knowledge/file",
        method="POST",
        data=upload_data,
        files={
            "file": (
                document_filename,
                content,
                file.content_type or "application/octet-stream",
            ),
        },
        timeout_seconds=120.0,
    )
    return _weknora_mutation_result(
        payload,
        default_message="文件上传成功，WeKnora 正在后台解析。",
    )


@agent_router.post(
    "/platform/weknora/knowledge-bases/{knowledge_base_id}/knowledge/url",
    response_model=WeKnoraKnowledgeMutationResponse,
    summary="Create WeKnora knowledge from a URL",
)
async def create_weknora_url_knowledge(
    knowledge_base_id: str,
    body: CreateWeKnoraUrlKnowledgeRequest,
    weknora_agent_id: str | None = Query(default=None, max_length=128),
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> WeKnoraKnowledgeMutationResponse:
    parsed = urlsplit(body.url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="资料 URL 必须是完整的 HTTP(S) 地址。",
        )
    settings = await _load_platform_settings(storage, user_id)
    connection = _require_weknora_connection(settings)
    _require_weknora_knowledge_base_access(
        knowledge_base_id,
        await _weknora_agent_knowledge_base_ids(connection, weknora_agent_id),
    )
    encoded_id = quote(knowledge_base_id, safe="")
    request_body: dict[str, object] = {
        "url": body.url.strip(),
        "enable_multimodel": body.enable_multimodel,
        "channel": "api",
    }
    if body.title.strip():
        request_body["title"] = body.title.strip()
        request_body["file_name"] = body.title.strip()
    payload = await _request_weknora_json(
        connection,
        f"/knowledge-bases/{encoded_id}/knowledge/url",
        method="POST",
        json_body=request_body,
        timeout_seconds=120.0,
    )
    return _weknora_mutation_result(
        payload,
        default_message="URL 已提交，WeKnora 正在后台解析。",
    )


@agent_router.get(
    "/platform/weknora/knowledge/{knowledge_id}",
    response_model=WeKnoraKnowledgeItem,
    summary="Get the current metadata for one WeKnora knowledge item",
)
async def get_weknora_knowledge(
    knowledge_id: str,
    weknora_agent_id: str | None = Query(default=None, max_length=128),
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> WeKnoraKnowledgeItem:
    """Return live file metadata after enforcing the robot's KB scope."""

    settings = await _load_platform_settings(storage, user_id)
    connection = _require_weknora_connection(settings)
    return await _require_weknora_knowledge_access(
        connection,
        knowledge_id,
        await _weknora_agent_knowledge_base_ids(connection, weknora_agent_id),
    )


@agent_router.delete(
    "/platform/weknora/knowledge/{knowledge_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one WeKnora knowledge item",
)
async def delete_weknora_knowledge(
    knowledge_id: str,
    weknora_agent_id: str | None = Query(default=None, max_length=128),
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> Response:
    settings = await _load_platform_settings(storage, user_id)
    connection = _require_weknora_connection(settings)
    await _require_weknora_knowledge_access(
        connection,
        knowledge_id,
        await _weknora_agent_knowledge_base_ids(connection, weknora_agent_id),
    )
    encoded_id = quote(knowledge_id, safe="")
    await _request_weknora_json(
        connection,
        f"/knowledge/{encoded_id}",
        method="DELETE",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _proxy_weknora_knowledge_content(
    knowledge_id: str,
    operation: str,
    *,
    user_id: str,
    storage: StorageBase,
    weknora_agent_id: str | None = None,
) -> Response:
    settings = await _load_platform_settings(storage, user_id)
    connection = _require_weknora_connection(settings)
    await _require_weknora_knowledge_access(
        connection,
        knowledge_id,
        await _weknora_agent_knowledge_base_ids(connection, weknora_agent_id),
    )
    encoded_id = quote(knowledge_id, safe="")
    content, content_type, content_disposition = await _request_weknora_bytes(
        connection,
        f"/knowledge/{encoded_id}/{operation}",
    )
    headers = {
        "Content-Type": content_type,
        "Cache-Control": "private, no-store",
    }
    if content_disposition:
        headers["Content-Disposition"] = content_disposition
    return Response(content=content, headers=headers)


@agent_router.get(
    "/platform/weknora/knowledge/{knowledge_id}/download",
    summary="Proxy an authenticated WeKnora file download",
)
async def download_weknora_knowledge(
    knowledge_id: str,
    weknora_agent_id: str | None = Query(default=None, max_length=128),
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> Response:
    return await _proxy_weknora_knowledge_content(
        knowledge_id,
        "download",
        user_id=user_id,
        storage=storage,
        weknora_agent_id=weknora_agent_id,
    )


@agent_router.get(
    "/platform/weknora/knowledge/{knowledge_id}/preview",
    summary="Proxy an authenticated WeKnora file preview",
)
async def preview_weknora_knowledge(
    knowledge_id: str,
    weknora_agent_id: str | None = Query(default=None, max_length=128),
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> Response:
    return await _proxy_weknora_knowledge_content(
        knowledge_id,
        "preview",
        user_id=user_id,
        storage=storage,
        weknora_agent_id=weknora_agent_id,
    )


@agent_router.get(
    "/platform/weknora/resources/{resource_id}",
    summary="Proxy an authenticated WeKnora resource handle",
)
async def proxy_weknora_resource(
    resource_id: str,
    weknora_agent_id: str = Query(min_length=1, max_length=128),
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> Response:
    """Resolve one documented ``resource://`` handle through `/files`."""

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", resource_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="WeKnora 资源句柄无效。",
        )
    settings = await _load_platform_settings(storage, user_id)
    connection = _require_weknora_connection(settings)
    allowed_ids = await _weknora_agent_knowledge_base_ids(
        connection,
        weknora_agent_id,
    )
    assert allowed_ids is not None
    content, content_type, content_disposition = await _request_weknora_bytes(
        connection,
        "/files",
        params={"file_path": f"resource://{resource_id}"},
        root_path=True,
        max_response_bytes=32 * 1024 * 1024,
    )
    headers = {
        "Content-Type": content_type,
        "Cache-Control": "private, no-store",
    }
    if (
        content_disposition
        and "\n" not in content_disposition
        and "\r" not in content_disposition
    ):
        headers["Content-Disposition"] = content_disposition
    return Response(content=content, headers=headers)


async def _create_weknora_agent_session(
    connection: WeKnoraConnectionConfig,
    weknora_agent_id: str,
) -> WeKnoraAgentSessionResponse:
    """Create the remote session used before a long-running query starts."""

    session_payload = await _request_weknora_json(
        connection,
        "/sessions",
        method="POST",
        json_body={"agent_id": weknora_agent_id},
    )
    session_data = session_payload.get("data")
    session_id = (
        _text(session_data.get("id"))
        if isinstance(session_data, dict)
        else ""
    )
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WeKnora 创建会话后未返回 session_id。",
        )
    return WeKnoraAgentSessionResponse(session_id=session_id)


@agent_router.post(
    "/platform/weknora/sessions",
    response_model=WeKnoraAgentSessionResponse,
    summary="Create a WeKnora session for a project-bound robot",
)
async def create_weknora_agent_session(
    body: CreateWeKnoraAgentSessionRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> WeKnoraAgentSessionResponse:
    settings = await _load_platform_settings(storage, user_id)
    connection = _require_weknora_connection(settings)
    allowed_ids = await _weknora_agent_knowledge_base_ids(
        connection,
        body.weknora_agent_id,
    )
    assert allowed_ids is not None
    return await _create_weknora_agent_session(
        connection,
        body.weknora_agent_id,
    )


async def _active_weknora_assistant_message_id(
    connection: WeKnoraConnectionConfig,
    session_id: str,
) -> str:
    """Resolve the incomplete assistant message required by WeKnora stop."""

    active_message_id = _active_weknora_message_ids.get(session_id, "")
    if active_message_id:
        return active_message_id

    # A stop click can arrive just before WeKnora persists the assistant
    # message. Retry briefly so the user does not have to click twice.
    for attempt in range(8):
        payload = await _request_weknora_json(
            connection,
            f"/messages/{quote(session_id, safe='')}/load",
            params={"limit": 20},
            timeout_seconds=5.0,
        )
        messages = payload.get("data")
        if isinstance(messages, list):
            for item in reversed(messages):
                if not isinstance(item, dict):
                    continue
                if _text(item.get("role")).lower() != "assistant":
                    continue
                if (
                    "is_completed" not in item
                    or item.get("is_completed") is not False
                ):
                    continue
                message_id = _text(item.get("id"))
                if message_id:
                    return message_id
        if attempt < 7:
            await asyncio.sleep(0.15)
    return ""


@agent_router.post(
    "/platform/weknora/sessions/{session_id}/stop",
    response_model=StopWeKnoraAgentSessionResponse,
    summary="Stop an active WeKnora answer",
)
async def stop_weknora_agent_session(
    session_id: str,
    body: StopWeKnoraAgentSessionRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> StopWeKnoraAgentSessionResponse:
    settings = await _load_platform_settings(storage, user_id)
    connection = _require_weknora_connection(settings)
    allowed_ids = await _weknora_agent_knowledge_base_ids(
        connection,
        body.weknora_agent_id,
    )
    assert allowed_ids is not None
    message_id = await _active_weknora_assistant_message_id(
        connection,
        session_id,
    )
    if not message_id:
        return StopWeKnoraAgentSessionResponse(
            session_id=session_id,
            stopped=False,
            message="当前会话没有正在生成的回答。",
        )
    payload = await _request_weknora_json(
        connection,
        f"/sessions/{quote(session_id, safe='')}/stop",
        method="POST",
        json_body={"message_id": message_id},
    )
    remote_message = _text(payload.get("message"))
    stopped = "already completed" not in remote_message.lower()
    return StopWeKnoraAgentSessionResponse(
        session_id=session_id,
        message_id=message_id,
        stopped=stopped,
        message=(
            "回答已终止。"
            if stopped
            else "该回答已经生成完成。"
        ),
    )


@agent_router.post(
    "/platform/weknora/agent-query",
    response_model=AskWeKnoraAgentResponse,
    summary="Call the configured WeKnora agent-chat endpoint",
)
async def ask_weknora_agent(
    body: AskWeKnoraAgentRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> AskWeKnoraAgentResponse:
    connection, session_id, request_body = await _prepare_weknora_agent_query(
        body,
        user_id=user_id,
        storage=storage,
    )
    events = await _request_weknora_sse(
        connection,
        f"/agent-chat/{quote(session_id, safe='')}",
        request_body,
        params={"resource_urls": "public"},
        session_id=session_id,
    )
    answer_parts: list[str] = []
    references: list[dict] = []
    tool_references: list[dict] = []
    tool_inline_citations: list[dict[str, str]] = []
    tool_calls: dict[str, dict] = {}
    session_title = ""
    for event in events:
        response_type = _text(event.get("response_type"))
        event_tool_references, event_tool_citations = (
            _weknora_tool_reference_items(event, tool_calls)
        )
        tool_references.extend(event_tool_references)
        tool_inline_citations.extend(event_tool_citations)
        if response_type == "answer":
            content = event.get("content")
            if isinstance(content, str):
                answer_parts.append(content)
        elif response_type == "references":
            raw_references = event.get("knowledge_references")
            if isinstance(raw_references, list):
                references.extend(
                    item for item in raw_references if isinstance(item, dict)
                )
        elif response_type == "session_title":
            session_title = _text(event.get("content"))
        elif response_type == "error":
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    _text(event.get("content"))
                    or "WeKnora 智能体返回错误。"
                ),
            )
    answer = "".join(answer_parts)
    references = await _enrich_weknora_reference_items(
        connection,
        _merge_weknora_reference_items(references, tool_references),
    )
    inline_references = await _enrich_weknora_inline_citations(
        connection,
        answer,
        list(request_body.get("knowledge_base_ids", [])),
        references,
    )
    tool_inline_references = await _enrich_weknora_citation_items(
        connection,
        tool_inline_citations,
        list(request_body.get("knowledge_base_ids", [])),
        references,
    )
    references = _merge_weknora_reference_items(
        references,
        inline_references,
        tool_inline_references,
    )
    return AskWeKnoraAgentResponse(
        session_id=session_id,
        answer=answer,
        references=references,
        session_title=session_title,
    )


async def _prepare_weknora_agent_query(
    body: AskWeKnoraAgentRequest,
    *,
    user_id: str,
    storage: StorageBase,
) -> tuple[WeKnoraConnectionConfig, str, dict]:
    """Authorize one query and build the documented agent-chat payload."""

    settings = await _load_platform_settings(storage, user_id)
    connection = _require_weknora_connection(settings)
    allowed_ids = await _weknora_agent_knowledge_base_ids(
        connection,
        body.weknora_agent_id,
    )
    assert allowed_ids is not None
    knowledge_base_ids = list(dict.fromkeys(body.knowledge_base_ids))
    if not knowledge_base_ids:
        knowledge_base_ids = allowed_ids
    for knowledge_base_id in knowledge_base_ids:
        _require_weknora_knowledge_base_access(
            knowledge_base_id,
            allowed_ids,
        )
    if not knowledge_base_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="WeKnora 中没有可用于对话的知识库。",
        )
    knowledge_ids = list(dict.fromkeys(body.knowledge_ids))
    for knowledge_id in knowledge_ids:
        await _require_weknora_knowledge_access(
            connection,
            knowledge_id,
            allowed_ids,
        )
    session_id = body.session_id or ""
    if not session_id:
        session = await _create_weknora_agent_session(
            connection,
            body.weknora_agent_id,
        )
        session_id = session.session_id
    return (
        connection,
        session_id,
        {
            "query": body.query,
            "agent_enabled": True,
            "agent_id": body.weknora_agent_id,
            "knowledge_base_ids": knowledge_base_ids,
            "knowledge_ids": knowledge_ids,
            "channel": "api",
        },
    )


def _weknora_sse_frame(payload: dict) -> str:
    return (
        "event: message\n"
        f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


@agent_router.post(
    "/platform/weknora/agent-query/stream",
    summary="Stream the configured WeKnora agent-chat endpoint",
)
async def stream_weknora_agent(
    body: AskWeKnoraAgentRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> StreamingResponse:
    connection, session_id, request_body = await _prepare_weknora_agent_query(
        body,
        user_id=user_id,
        storage=storage,
    )

    async def relay() -> AsyncIterator[str]:
        pending_references: list[dict] = []
        tool_references: list[dict] = []
        tool_inline_citations: list[dict[str, str]] = []
        tool_calls: dict[str, dict] = {}
        answer_parts: list[str] = []
        reference_event: dict | None = None
        title_event: dict | None = None
        terminal_event: dict | None = None
        yield _weknora_sse_frame(
            {
                "response_type": "session",
                "session_id": session_id,
                "done": True,
            },
        )
        try:
            async for raw_event in _stream_weknora_sse_events(
                connection,
                f"/agent-chat/{quote(session_id, safe='')}",
                request_body,
                params={"resource_urls": "public"},
                session_id=session_id,
            ):
                event = dict(raw_event)
                event["session_id"] = session_id
                response_type = _text(event.get("response_type"))
                event_tool_references, event_tool_citations = (
                    _weknora_tool_reference_items(event, tool_calls)
                )
                tool_references.extend(event_tool_references)
                tool_inline_citations.extend(event_tool_citations)
                if response_type == "references":
                    raw_references = event.get("knowledge_references")
                    if isinstance(raw_references, list):
                        pending_references.extend(
                            item
                            for item in raw_references
                            if isinstance(item, dict)
                        )
                    reference_event = event
                    continue
                if response_type == "answer":
                    content = event.get("content")
                    if isinstance(content, str):
                        answer_parts.append(content)
                if response_type == "session_title":
                    title_event = event
                    continue
                if response_type in {"complete", "error", "stop"}:
                    terminal_event = event
                    continue
                yield _weknora_sse_frame(event)
        except HTTPException as exc:
            terminal_event = {
                "response_type": "error",
                "session_id": session_id,
                "content": str(exc.detail),
                "status_code": exc.status_code,
                "done": True,
            }

        # Metadata lookup is intentionally deferred until the upstream SSE
        # connection has closed.  Some WeKnora deployments become unstable
        # when a batch metadata request runs concurrently with agent-chat.
        enriched: list[dict] = []
        raw_references = _merge_weknora_reference_items(
            pending_references,
            tool_references,
        )
        if raw_references:
            enriched = await _enrich_weknora_reference_items(
                connection,
                raw_references,
            )
        inline_references = await _enrich_weknora_inline_citations(
            connection,
            "".join(answer_parts),
            list(request_body.get("knowledge_base_ids", [])),
            enriched,
        )
        tool_inline_references = await _enrich_weknora_citation_items(
            connection,
            tool_inline_citations,
            list(request_body.get("knowledge_base_ids", [])),
            enriched,
        )
        enriched = _merge_weknora_reference_items(
            enriched,
            inline_references,
            tool_inline_references,
        )
        if enriched:
            citation_event = dict(reference_event or {})
            citation_event.update(
                {
                    "response_type": "references",
                    "session_id": session_id,
                    "knowledge_references": enriched,
                },
            )
            yield _weknora_sse_frame(citation_event)
        if title_event is not None:
            yield _weknora_sse_frame(title_event)
        if terminal_event is not None:
            yield _weknora_sse_frame(terminal_event)
        else:
            yield _weknora_sse_frame(
                {
                    "response_type": "complete",
                    "session_id": session_id,
                    "done": True,
                },
            )

    return StreamingResponse(
        relay(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@agent_router.put(
    "/platform/settings",
    response_model=PlatformSettingsResponse,
    summary="Update platform-wide AgentScope settings",
)
async def update_platform_settings(
    body: UpdatePlatformSettingsRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    manager: MCPRegistryManager = Depends(get_mcp_registry_manager),
) -> PlatformSettingsResponse:
    """Update global agent assignments without exposing per-account settings."""
    if not body.model_fields_set:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one platform setting must be provided.",
        )
    current = await _load_platform_settings(storage, user_id)
    current = await _migrate_initialization_validation_binding(
        current,
        storage=storage,
        user_id=user_id,
        manager=manager,
    )
    global_main_agent_id = current.data.global_main_agent_id
    project_initializer_agent_id = (
        current.data.project_initializer_agent_id
    )
    validation_mcp = current.data.project_initializer_validation_mcp
    engineering_document_agent_id = (
        current.data.engineering_document_agent_id
    )
    previous_validation_mcp = validation_mcp

    async def validate_candidate(
        agent_id: str,
        purpose: str,
    ) -> AgentRecord:
        selected = await storage.get_agent(user_id, agent_id)
        if selected is None or selected.source != "user":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"The selected {purpose} agent does not exist.",
            )
        if not selected.data.platform_config.enabled:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"The {purpose} agent must be enabled.",
            )
        if (
            selected.data.model_policy.mode != "fixed"
            or selected.data.model_policy.chat_model_config is None
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"The {purpose} agent must use a fixed chat model.",
            )
        return selected

    if "global_main_agent_id" in body.model_fields_set:
        if body.global_main_agent_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The platform main agent cannot be cleared.",
            )
        await validate_candidate(
            body.global_main_agent_id,
            "platform main",
        )
        global_main_agent_id = body.global_main_agent_id
    if "project_initializer_agent_id" in body.model_fields_set:
        if body.project_initializer_agent_id is not None:
            await validate_candidate(
                body.project_initializer_agent_id,
                "project initializer",
            )
        project_initializer_agent_id = body.project_initializer_agent_id
    if "project_initializer_validation_mcp" in body.model_fields_set:
        requested_binding = body.project_initializer_validation_mcp
        if requested_binding is not None:
            record = await manager.get_record(
                requested_binding.package_id,
                requested_binding.version,
            )
            if record is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="选择的核验 MCP 版本不存在，请刷新后重新选择。",
                )
            if not _is_initialization_validation_package(record):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "选择的 MCP 未声明项目初始化核验能力，或包含多个"
                        "核验入口。"
                    ),
                )
        validation_mcp = requested_binding
    if "engineering_document_agent_id" in body.model_fields_set:
        if body.engineering_document_agent_id is not None:
            await validate_candidate(
                body.engineering_document_agent_id,
                "engineering document manager",
            )
        engineering_document_agent_id = body.engineering_document_agent_id
    if (
        global_main_agent_id is not None
        and global_main_agent_id == project_initializer_agent_id
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "The platform main agent and project initializer must be "
                "different agents."
            ),
        )
    if project_initializer_agent_id is not None and validation_mcp is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="项目初始化智能体必须配置一个核验 MCP 版本。",
        )
    if validation_mcp is not None:
        selected_validation_record = await manager.get_record(
            validation_mcp.package_id,
            validation_mcp.version,
        )
        if (
            selected_validation_record is None
            or not _is_initialization_validation_package(
                selected_validation_record,
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="当前核验 MCP 配置已不可用，请重新选择版本。",
            )
    settings = await storage.upsert_platform_settings(
        user_id,
        current.data.model_copy(
            update={
                "global_main_agent_id": global_main_agent_id,
                "project_initializer_agent_id": project_initializer_agent_id,
                "project_initializer_validation_mcp": validation_mcp,
                "engineering_document_agent_id": (
                    engineering_document_agent_id
                ),
            },
        ),
    )
    if (
        previous_validation_mcp is not None
        and previous_validation_mcp != validation_mcp
    ):
        await manager.close_version_instances(
            previous_validation_mcp.package_id,
            previous_validation_mcp.version,
        )
    await _synchronise_global_main_agent_roles(
        storage,
        user_id,
        settings.data.global_main_agent_id,
    )
    await _synchronise_project_initializer_role(
        storage,
        user_id,
        settings.data.project_initializer_agent_id,
    )
    return PlatformSettingsResponse(
        global_main_agent_id=settings.data.global_main_agent_id,
        project_initializer_agent_id=(
            settings.data.project_initializer_agent_id
        ),
        project_initializer_validation_mcp=(
            settings.data.project_initializer_validation_mcp
        ),
        engineering_document_agent_id=(
            settings.data.engineering_document_agent_id
        ),
    )


@agent_router.post(
    "/",
    response_model=CreateAgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new agent",
)
async def create_agent(
    body: CreateAgentRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> CreateAgentResponse:
    """Create and persist a new agent configuration.

    Args:
        body (`CreateAgentRequest`):
            Agent configuration to store.
        user_id (`str`):
            Injected authenticated user ID.
        storage (`StorageBase`):
            Injected storage backend.

    Returns:
        `CreateAgentResponse`:
            The server-assigned agent identifier.

    Raises:
        `HTTPException`: 422 if the request body passes
            :class:`CreateAgentRequest` validation but the resulting
            :class:`AgentData` fails its cross-field invariants (e.g.
            ``invite_config.invitable=True`` without a non-empty
            ``invite_description``). Symmetrical with
            :func:`update_agent`.
    """
    if body.platform_config.role == "global_main":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Configure the platform main agent in Platform Settings "
                "instead of assigning the role on an agent."
            ),
        )
    try:
        model_policy = await _validate_model_policy(
            user_id,
            body.model_policy,
            access,
        )
        data = AgentData(
            name=body.name,
            system_prompt=body.system_prompt,
            context_config=body.context_config,
            react_config=body.react_config,
            model_policy=model_policy,
            platform_config=body.platform_config,
            invite_config=body.invite_config,
            call_config=body.call_config,
            mcp_config=body.mcp_config,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc
    data = _normalise_platform_agent_data(data)
    record = AgentRecord(user_id=user_id, data=data)
    agent_id = await storage.upsert_agent(user_id, record)
    return CreateAgentResponse(agent_id=agent_id)


@agent_router.patch(
    "/{agent_id}",
    response_model=AgentView,
    summary="Update an agent",
)
async def update_agent(
    agent_id: str,
    body: UpdateAgentRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> AgentView:
    """Partially update an existing agent configuration.

    Only the fields present in the request body are updated; all other fields
    keep their current values.

    Args:
        agent_id (`str`): The agent to update.
        body (`UpdateAgentRequest`): Fields to update.
        user_id (`str`): Injected authenticated user ID.
        storage (`StorageBase`): Injected storage backend.
        access (`ResourceAccessService`): Injected access service.

    Returns:
        `AgentView`: The full agent record after the update.

    Raises:
        `HTTPException`: 404 if the agent is not visible to the caller;
            403 if visible but only readable.
    """
    owner_id, existing = await access.resolve_for_edit(
        user_id,
        ResourceKind.AGENT,
        agent_id,
    )
    settings = await _load_platform_settings(storage, owner_id)
    selected_id = settings.data.global_main_agent_id
    is_selected_main = selected_id == agent_id
    if (
        body.platform_config is not None
        and body.platform_config.role == "global_main"
        and not is_selected_main
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Configure the platform main agent in Platform Settings "
                "instead of assigning the role on an agent."
            ),
        )

    updates = body.model_dump(exclude_none=True)
    # ``model_copy(update=...)`` skips validators; re-run
    # ``AgentData.model_validate`` on the merged shape so the
    # ``invite_config`` sub-model's ``invitable ⇒ non-empty description``
    # invariant enforced by ``@model_validator(mode="after")`` produces
    # an HTTP 422 instead of a stored-but-invalid record.
    try:
        updated_data = AgentData.model_validate(
            {**existing.data.model_dump(), **updates},
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc
    updated_data = updated_data.model_copy(
        update={
            "model_policy": await _validate_model_policy(
                user_id,
                updated_data.model_policy,
                access,
            ),
        },
    )
    updated_data = _normalise_platform_agent_data(updated_data)
    if is_selected_main:
        if not updated_data.platform_config.enabled:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Select another platform main agent before disabling "
                    "the current one."
                ),
            )
        if (
            updated_data.model_policy.mode != "fixed"
            or updated_data.model_policy.chat_model_config is None
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "The current platform main agent must keep a fixed "
                    "chat model. Select another main agent first."
                ),
            )
        updated_data = updated_data.model_copy(
            update={
                "platform_config": (
                    updated_data.platform_config.model_copy(
                        update={"role": "global_main"},
                    )
                ),
                "call_config": updated_data.call_config.model_copy(
                    update={"scope": "all"},
                ),
            },
        )
    elif updated_data.platform_config.role == "global_main":
        updated_data = updated_data.model_copy(
            update={
                "platform_config": (
                    updated_data.platform_config.model_copy(
                        update={"role": "business"},
                    )
                ),
            },
        )
    if agent_id in updated_data.call_config.allowed_agent_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="An agent cannot include itself in allowed_agent_ids.",
        )
    updated_agent = existing.model_copy(
        update={"data": updated_data, "updated_at": datetime.now()},
    )
    await storage.upsert_agent(owner_id, updated_agent)
    # Only reachable via ``resolve_for_edit``, so the caller has edit
    # permission by construction.
    return AgentView.model_validate(
        {**updated_agent.model_dump(), "editable": True},
    )


@agent_router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an agent",
)
async def delete_agent(
    agent_id: str,
    request: Request = None,  # type: ignore[assignment]
    user_id: str = Depends(get_current_user_id),
    session_service: SessionService = Depends(get_session_service),
    storage: StorageBase = Depends(get_storage),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> None:
    """Permanently delete an agent configuration.

    Cascades through every session owned by this agent (and, for team
    leaders, through every worker session) — cancelling any in-flight
    chat run, removing storage records, and purging bus state.

    Args:
        agent_id (`str`): The agent to delete.
        user_id (`str`): Injected authenticated user ID.
        session_service (`SessionService`): Injected session service.
        access (`ResourceAccessService`): Injected access service — used
            to resolve the owning user and enforce the edit permission
            when a shared editor deletes the agent.

    Raises:
        `HTTPException`: 404 if the agent is not visible to the caller;
            403 if visible but only readable.
    """
    owner_id, _ = await access.resolve_for_edit(
        user_id,
        ResourceKind.AGENT,
        agent_id,
    )
    settings = await _load_platform_settings(storage, owner_id)
    if settings.data.global_main_agent_id == agent_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Select another platform main agent before deleting the "
                "current one."
            ),
        )
    deleted = await session_service.delete_agent(owner_id, agent_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found.",
        )
    database_manager = (
        getattr(request.app.state, "database_interaction_manager", None)
        if request is not None
        else None
    )
    if database_manager is not None:
        try:
            await database_manager.delete_assignments(agent_id)
        except Exception as exc:  # pragma: no cover - remote cleanup fallback
            # The agent is already gone from authoritative AgentScope storage.
            # Orphaned external assignment rows are inert and can be retried;
            # do not turn a successful delete into a misleading client error.
            logger.warning(
                "Unable to clean database interaction assignments for %s: %s",
                agent_id,
                exc,
            )
