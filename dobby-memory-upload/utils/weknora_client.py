"""
Lightweight WeKnora REST client for demo Step 2.

Extracted from wk_mcp-server_weknora_mcp_server.py — keeps only the parts
needed for KB management and hybrid search. No MCP protocol layer.
"""

import logging
import os
from typing import Any

import requests
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)


class WeKnoraClient:
    """Minimal WeKnora REST client for KB search + document management."""

    def __init__(self, base_url: str, api_key: str = "", timeout: tuple | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
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
            return resp.json()
        except RequestException as e:
            logger.error(f"WeKnora API error: {e}")
            raise

    # ── Health ─────────────────────────────────────────────────────────

    def health_check(self) -> bool:
        """Check WeKnora API is reachable."""
        try:
            self._request("GET", "/tenants")
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

    def upload_file(self, kb_id: str, file_path: str, enable_multimodel: bool = False) -> dict:
        """Upload a local file to a knowledge base."""
        import os as _os
        abs_path = _os.path.abspath(file_path)
        if not _os.path.exists(abs_path):
            raise FileNotFoundError(f"File not found: {abs_path}")
        with open(abs_path, "rb") as f:
            files = {"file": f}
            data = {"enable_multimodel": str(enable_multimodel).lower()}
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

    def list_knowledge(self, kb_id: str, page: int = 1, page_size: int = 20) -> dict:
        """List knowledge entries in a KB."""
        params = {"page": page, "page_size": page_size}
        return self._request("GET", f"/knowledge-bases/{kb_id}/knowledge", params=params)

    def delete_knowledge(self, knowledge_id: str) -> dict:
        """Delete a knowledge entry."""
        return self._request("DELETE", f"/knowledge/{knowledge_id}")

    def get_knowledge(self, knowledge_id: str) -> dict:
        """Get a single knowledge entry."""
        return self._request("GET", f"/knowledge/{knowledge_id}")

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
