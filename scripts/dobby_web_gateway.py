"""Serve prebuilt Dobby frontends and proxy their internal API requests.

This module deliberately uses only the project's portable Python runtime.
Production/test servers therefore do not need Node.js, npm, pnpm, Vite, or
the AgentScope Web UI helper process.
"""

from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask


PROJECT_ROOT: Final = Path(__file__).resolve().parents[1]
HTTP_METHODS: Final = [
    "GET",
    "HEAD",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
]
HOP_BY_HOP_HEADERS: Final = {
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


@dataclass(frozen=True)
class ProxyRule:
    """Map one browser-visible path prefix to an internal HTTP service."""

    prefix: str
    upstream: str
    strip_prefix: bool = False

    def matches(self, path: str) -> bool:
        return path == self.prefix or path.startswith(f"{self.prefix}/")

    def target_url(self, path: str, query: str) -> str:
        target_path = path
        if self.strip_prefix:
            target_path = path[len(self.prefix) :] or "/"
        url = f"{self.upstream.rstrip('/')}{target_path}"
        return f"{url}?{query}" if query else url


@dataclass(frozen=True)
class GatewayMode:
    """Runtime settings for one static frontend."""

    static_dir: Path
    host: str
    port: int
    rules: tuple[ProxyRule, ...]


def _resolve_mode(mode: str) -> GatewayMode:
    if mode == "platform":
        return GatewayMode(
            static_dir=PROJECT_ROOT / "frontend" / "dist",
            host="0.0.0.0",
            port=38429,
            rules=(
                ProxyRule("/api", "http://127.0.0.1:38430"),
                ProxyRule("/health", "http://127.0.0.1:38430"),
            ),
        )
    if mode == "agentscope":
        return GatewayMode(
            static_dir=(
                PROJECT_ROOT
                / "AgentScope"
                / "agentscope-web-ui"
                / "frontend"
                / "dist"
            ),
            host="127.0.0.1",
            port=25173,
            rules=(
                ProxyRule(
                    "/agentscope-api",
                    "http://127.0.0.1:18642",
                    strip_prefix=True,
                ),
            ),
        )
    raise ValueError(f"Unsupported gateway mode: {mode}")


def _forward_headers(request: Request) -> list[tuple[str, str]]:
    headers = [
        (name, value)
        for name, value in request.headers.items()
        if name.lower() not in HOP_BY_HOP_HEADERS
    ]
    if request.client:
        headers.append(("x-forwarded-for", request.client.host))
    headers.append(("x-forwarded-host", request.headers.get("host", "")))
    headers.append(("x-forwarded-proto", request.url.scheme))
    return headers


def _response_headers(response: httpx.Response) -> dict[str, str]:
    return {
        name: value
        for name, value in response.headers.items()
        if name.lower() not in HOP_BY_HOP_HEADERS
    }


async def _proxy_request(request: Request, rule: ProxyRule) -> Response:
    client = httpx.AsyncClient(follow_redirects=False, timeout=None)

    async def request_body() -> AsyncIterator[bytes]:
        async for chunk in request.stream():
            yield chunk

    target_url = rule.target_url(request.url.path, request.url.query)
    try:
        upstream_request = client.build_request(
            method=request.method,
            url=target_url,
            headers=_forward_headers(request),
            content=(
                request_body()
                if request.method not in {"GET", "HEAD", "OPTIONS"}
                else None
            ),
        )
        upstream_response = await client.send(upstream_request, stream=True)
    except httpx.RequestError as exc:
        await client.aclose()
        return JSONResponse(
            status_code=502,
            content={
                "detail": (
                    "内部服务暂时不可用，请检查对应的 Dobby 服务是否已经启动。"
                ),
                "upstream": rule.upstream,
                "error": str(exc),
            },
        )

    async def close_upstream() -> None:
        await upstream_response.aclose()
        await client.aclose()

    return StreamingResponse(
        upstream_response.aiter_raw(),
        status_code=upstream_response.status_code,
        headers=_response_headers(upstream_response),
        background=BackgroundTask(close_upstream),
    )


def create_gateway(mode: str) -> FastAPI:
    """Create one static SPA server with its internal reverse-proxy rules."""

    settings = _resolve_mode(mode)
    static_dir = settings.static_dir.resolve()
    index_file = static_dir / "index.html"
    if not index_file.is_file():
        raise RuntimeError(
            f"缺少已构建前端：{index_file}。请在开发机重新生成服务器更新包。",
        )

    app = FastAPI(
        title=f"Dobby {mode} web gateway",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.api_route("/{requested_path:path}", methods=HTTP_METHODS)
    async def handle(request: Request, requested_path: str) -> Response:
        for rule in settings.rules:
            if rule.matches(request.url.path):
                return await _proxy_request(request, rule)

        if request.method not in {"GET", "HEAD"}:
            return JSONResponse(status_code=405, content={"detail": "Method Not Allowed"})

        candidate = (static_dir / requested_path).resolve()
        try:
            candidate.relative_to(static_dir)
        except ValueError:
            return JSONResponse(status_code=404, content={"detail": "Not Found"})

        if candidate.is_file():
            return FileResponse(candidate)

        # Missing asset files should remain a real 404; extensionless paths are
        # client-side routes and must fall back to the SPA entry point.
        if request.url.path.startswith("/assets/") or Path(requested_path).suffix:
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        return FileResponse(index_file)

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("platform", "agentscope"), required=True)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    arguments = parser.parse_args()

    settings = _resolve_mode(arguments.mode)
    uvicorn.run(
        create_gateway(arguments.mode),
        host=arguments.host or settings.host,
        port=arguments.port or settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
