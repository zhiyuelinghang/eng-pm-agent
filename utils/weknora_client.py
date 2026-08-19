"""WeKnora REST client for the AgentScope 2.0 knowledge integration.

The client follows the project integration guide for knowledge management,
hybrid retrieval, source metadata, sessions, and SSE chat.  It deliberately
uses WeKnora as an HTTP service rather than adding an MCP transport layer.
"""

import json
import logging
import os
from typing import Any, Iterator

import requests
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)


class WeKnoraClient:
    """WeKnora REST client aligned with the AgentScope 2.0 guide."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout: tuple | None = None,
        *,
        agent_id: str = "",
        chat_timeout: float = 300.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.agent_id = agent_id.strip()
        self.chat_timeout = max(float(chat_timeout), 30.0)
        self.verify_ssl = os.getenv("WEKNORA_VERIFY_SSL", "true").lower() != "false"
        if not self.verify_ssl:
            import urllib3
            logger.warning("SSL verification DISABLED (WEKNORA_VERIFY_SSL=false)")
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self.session = requests.Session()
        self.session.verify = self.verify_ssl
        self.session.trust_env = False  # bypass HTTP_PROXY for localhost
        # ── HTTP timeout (connect, read) — prevents infinite hang ──
        if timeout is None:
            timeout = (
                float(os.getenv("WEKNORA_TIMEOUT_CONNECT", "5.0")),
                float(os.getenv("WEKNORA_TIMEOUT_READ", "30.0")),
            )
        self.timeout = timeout
        self.timeout_upload = (timeout[0], max(timeout[1], 60.0))  # uploads get ≥60s read
        headers = {"Content-Type": "application/json"}
        if api_key:
            # Support both JWT Bearer tokens and X-API-Key
            if api_key.startswith("eyJ"):
                headers["Authorization"] = f"Bearer {api_key}"
            else:
                headers["X-API-Key"] = api_key
        self.session.headers.update(headers)

    # ── Helpers ────────────────────────────────────────────────────────

    def _request(self, method: str, endpoint: str, **kwargs) -> dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        try:
            resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, dict):
                raise ValueError("WeKnora returned a non-object JSON response")
            if payload.get("success") is False:
                raise RuntimeError(
                    str(payload.get("message") or "WeKnora request failed"),
                )
            return payload
        except RequestException as e:
            logger.error(f"WeKnora API error: {e}")
            raise

    # ── Health ─────────────────────────────────────────────────────────

    def health_check(self) -> bool:
        """Check WeKnora API is reachable."""
        try:
            self.list_knowledge_bases()
            return True
        except Exception:
            return False

    # ── Knowledge Base Management ─────────────────────────────────────

    def list_knowledge_bases(self) -> list[dict]:
        """List all knowledge bases."""
        resp = self._request("GET", "/knowledge-bases")
        data = resp.get("data", resp)
        if isinstance(data, dict):
            return data.get("list", data.get("items", []))
        return data if isinstance(data, list) else []

    def get_knowledge_base(self, kb_id: str) -> dict:
        """Get a single KB by ID."""
        return self._request("GET", f"/knowledge-bases/{kb_id}")

    def create_knowledge_base(
        self,
        name: str,
        description: str = "",
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> dict:
        """Create a new knowledge base."""
        config = {
            "chunking_config": {
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "separators": ["\n\n", "\n", "。", ".", "；", ";"],
            },
        }
        data = {"name": name, "description": description, **config}
        return self._request("POST", "/knowledge-bases", json=data)

    def delete_knowledge_base(self, kb_id: str) -> dict:
        """Delete a knowledge base."""
        return self._request("DELETE", f"/knowledge-bases/{kb_id}")

    # ── Knowledge (Documents) ─────────────────────────────────────────

    def upload_file(
        self,
        kb_id: str,
        file_path: str,
        enable_multimodel: bool = True,
        *,
        folder_path: str = "",
    ) -> dict:
        """Upload a file using v0.7.2's separate file/folder fields."""
        import os as _os
        abs_path = _os.path.abspath(file_path)
        if not _os.path.exists(abs_path):
            raise FileNotFoundError(f"File not found: {abs_path}")
        with open(abs_path, "rb") as f:
            files = {"file": f}
            data = {
                "enable_multimodel": str(enable_multimodel).lower(),
                "channel": "api",
                "fileName": _os.path.basename(abs_path),
            }
            normalised_folder_path = folder_path.strip().strip("/")
            if normalised_folder_path:
                data["folder_path"] = normalised_folder_path
            headers = {k: v for k, v in self.session.headers.items() if k != "Content-Type"}
            resp = self.session.post(
                f"{self.base_url}/knowledge-bases/{kb_id}/knowledge/file",
                headers=headers,
                files=files,
                data=data,
                timeout=self.timeout_upload,
            )
            resp.raise_for_status()
            return resp.json()

    def list_knowledge(
        self,
        kb_id: str,
        page: int = 1,
        page_size: int = 20,
        *,
        folder_path: str | None = None,
        folder_recursive: bool = True,
        **filters: str,
    ) -> dict:
        """List knowledge entries in a KB."""
        params = {"page": page, "page_size": page_size}
        if folder_path is not None:
            params.update({
                "folder_path": folder_path,
                "folder_recursive": str(folder_recursive).lower(),
            })
        params.update({key: value for key, value in filters.items() if value})
        return self._request("GET", f"/knowledge-bases/{kb_id}/knowledge", params=params)

    def get_folder_tree(self, kb_id: str) -> dict:
        """Return WeKnora's complete v0.7.2 folder tree."""

        payload = self._request(
            "GET",
            f"/knowledge-bases/{kb_id}/knowledge/folders",
        )
        data = payload.get("data", {})
        return data if isinstance(data, dict) else {}

    def delete_knowledge(self, knowledge_id: str) -> dict:
        """Delete a knowledge entry."""
        return self._request("DELETE", f"/knowledge/{knowledge_id}")

    def get_knowledge(self, knowledge_id: str) -> dict:
        """Get a single knowledge entry."""
        payload = self._request("GET", f"/knowledge/{knowledge_id}")
        data = payload.get("data", {})
        return data if isinstance(data, dict) else {}

    def get_knowledge_batch(self, knowledge_ids: list[str]) -> list[dict]:
        """Fetch file metadata for multiple knowledge items in one request."""

        unique_ids = list(dict.fromkeys(item for item in knowledge_ids if item))
        if not unique_ids:
            return []
        payload = self._request(
            "GET",
            "/knowledge/batch",
            params={"ids": ",".join(unique_ids)},
        )
        data = payload.get("data", [])
        if isinstance(data, dict):
            data = data.get("list", data.get("items", []))
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def create_from_url(
        self,
        kb_id: str,
        url: str,
        enable_multimodel: bool = True,
        *,
        title: str = "",
    ) -> dict:
        """Create a knowledge item by asking WeKnora to fetch a URL."""

        body: dict[str, Any] = {
            "url": url,
            "enable_multimodel": enable_multimodel,
            "channel": "api",
        }
        if title:
            body.update({"title": title, "file_name": title})
        return self._request(
            "POST",
            f"/knowledge-bases/{kb_id}/knowledge/url",
            json=body,
        )

    def download_file(self, knowledge_id: str) -> bytes:
        """Download an authenticated original file."""

        response = self.session.get(
            f"{self.base_url}/knowledge/{knowledge_id}/download",
            timeout=self.timeout_upload,
        )
        response.raise_for_status()
        return response.content

    def preview_file(self, knowledge_id: str) -> requests.Response:
        """Return the authenticated preview response without altering its type."""

        response = self.session.get(
            f"{self.base_url}/knowledge/{knowledge_id}/preview",
            timeout=self.timeout_upload,
        )
        response.raise_for_status()
        return response

    # ── Agents and chat ───────────────────────────────────────────────

    def list_agents(self) -> list[dict]:
        """List custom WeKnora agents visible to the configured tenant."""

        payload = self._request("GET", "/agents")
        data = payload.get("data", [])
        if isinstance(data, dict):
            data = data.get("list", data.get("items", []))
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    def get_agent(self, agent_id: str | None = None) -> dict:
        """Get one custom WeKnora agent by ID."""

        target = (agent_id or self.agent_id).strip()
        if not target:
            raise ValueError("WeKnora agent_id is required")
        payload = self._request("GET", f"/agents/{target}")
        data = payload.get("data", {})
        return data if isinstance(data, dict) else {}

    def create_session(
        self,
        kb_id: str,
        *,
        title: str = "AgentScope 工程知识问答",
        max_rounds: int = 10,
    ) -> str:
        """Create a WeKnora chat session and return its ID."""

        payload = self._request(
            "POST",
            "/sessions",
            json={
                "knowledge_base_id": kb_id,
                "title": title,
                "session_strategy": {
                    "max_rounds": max(1, int(max_rounds)),
                    "enable_rewrite": True,
                    "fallback_strategy": "FIXED_RESPONSE",
                    "fallback_response": "抱歉，我暂时无法回答这个问题。",
                },
            },
        )
        data = payload.get("data", {})
        return str(data.get("id") or "") if isinstance(data, dict) else ""

    def _chat_events(
        self,
        endpoint: str,
        body: dict[str, Any],
        *,
        params: dict[str, str] | None = None,
    ) -> Iterator[dict]:
        response = self.session.post(
            f"{self.base_url}{endpoint}",
            params=params,
            json=body,
            stream=True,
            timeout=(self.timeout[0], self.chat_timeout),
        )
        response.raise_for_status()
        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:].lstrip())
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            yield event
            if event.get("response_type") in {"complete", "error"}:
                break

    def chat_stream(
        self,
        session_id: str,
        query: str,
        kb_ids: list[str] | None = None,
    ) -> Iterator[dict]:
        """Stream the documented WeKnora knowledge-chat events."""

        body: dict[str, Any] = {
            "query": query,
            "web_search_enabled": False,
            "enable_memory": False,
            "channel": "api",
        }
        if kb_ids:
            body["knowledge_base_ids"] = kb_ids
        return self._chat_events(f"/knowledge-chat/{session_id}", body)

    def agent_chat_stream(
        self,
        session_id: str,
        query: str,
        kb_ids: list[str] | None = None,
        *,
        agent_id: str | None = None,
    ) -> Iterator[dict]:
        """Stream the documented WeKnora agent-chat events."""

        target_agent_id = (agent_id or self.agent_id).strip()
        if not target_agent_id:
            raise ValueError("WeKnora agent_id is required")
        body: dict[str, Any] = {
            "query": query,
            "agent_id": target_agent_id,
            "channel": "api",
        }
        if kb_ids:
            body["knowledge_base_ids"] = kb_ids
        return self._chat_events(
            f"/agent-chat/{session_id}",
            body,
            params={"resource_urls": "public"},
        )

    # ── Search ★ Core ─────────────────────────────────────────────────

    def hybrid_search(
        self,
        kb_id: str,
        query: str,
        vector_threshold: float = 0.5,
        keyword_threshold: float = 0.3,
        match_count: int = 5,
    ) -> list[dict]:
        """
        Hybrid search: BM25 keyword + vector semantic + GraphRAG.

        Returns list of search result dicts with keys:
          - content / chunk_content
          - score
          - knowledge_id / document_id
          - metadata / source
        """
        config = {
            "vector_threshold": vector_threshold,
            "keyword_threshold": keyword_threshold,
            "match_count": match_count,
        }
        resp = self._request(
            "POST",
            f"/knowledge-bases/{kb_id}/hybrid-search",
            json={"query_text": query, **config},
        )

        # Normalize response shape — WeKnora wraps in data.{results|items}
        results = resp.get("data", resp)
        if isinstance(results, dict):
            results = results.get("results", results.get("items", []))
        if not isinstance(results, list):
            return []

        return results
