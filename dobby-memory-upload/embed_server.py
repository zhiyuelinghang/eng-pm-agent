#!/usr/bin/env python3
"""
Minimal OpenAI-compatible embedding server for WeKnora.
Uses the already-downloaded bge-large-zh-v1.5 model.
Run: python embed_server.py
Listens on: http://localhost:9999
"""
import os
import sys
import json
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── 必须在 import transformers 之前设置 ──
# 绕过本地代理 + 强制离线模式（模型已缓存本地）
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1,huggingface.co,cdn-lfs.huggingface.co")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "BAAI/bge-large-zh-v1.5"
print(f"Loading model: {MODEL_NAME}...")
model = SentenceTransformer(MODEL_NAME)
print(f"Model loaded. dims={model.get_sentence_embedding_dimension()}")


class EmbedHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._send_json({"status": "ok"})
        if self.path == "/v1/models":
            return self._send_json({
                "object": "list",
                "data": [{"id": MODEL_NAME, "object": "model"}]
            })
        self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/v1/embeddings":
            return self._send_json({"error": "not found"}, 404)

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            inp = body.get("input", "")
            if isinstance(inp, list):
                texts = inp
            else:
                texts = [inp]

            embeddings = model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
            )

            data = []
            for i, emb in enumerate(embeddings):
                data.append({
                    "object": "embedding",
                    "index": i,
                    "embedding": emb.tolist(),
                })

            self._send_json({
                "object": "list",
                "data": data,
                "model": MODEL_NAME,
                "usage": {"prompt_tokens": sum(len(t) for t in texts), "total_tokens": sum(len(t) for t in texts)},
            })
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def log_message(self, format, *args):
        # Suppress default logging noise
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9999
    server = HTTPServer(("0.0.0.0", port), EmbedHandler)
    print(f"Embedding server listening on http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()
