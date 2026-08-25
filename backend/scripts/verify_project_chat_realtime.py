"""Verify the real project-chat API and PostgreSQL -> Centrifugo delivery path."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from uuid import uuid4

import httpx
from sqlalchemy import select
from websockets.sync.client import connect


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.db import SessionLocal  # noqa: E402
from backend.app.models import Project, User  # noqa: E402
from backend.app.security import create_access_token  # noqa: E402


API_BASE_URL = "http://127.0.0.1:38430/api"
EXPECTED_ORIGIN = "http://127.0.0.1:38429"


def _frames(raw: str | bytes) -> list[dict[str, object]]:
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _wait_for_connect(websocket) -> None:
    for _ in range(10):
        for frame in _frames(websocket.recv(timeout=5)):
            if frame.get("id") != 1:
                continue
            if frame.get("error"):
                raise RuntimeError(f"Centrifugo rejected the token: {frame['error']}")
            if frame.get("connect") is not None:
                return
    raise TimeoutError("Centrifugo did not confirm the connection")


def _wait_for_message(websocket, message_id: int) -> None:
    for _ in range(20):
        for frame in _frames(websocket.recv(timeout=5)):
            push = frame.get("push")
            if not isinstance(push, dict):
                continue
            publication = push.get("pub")
            if not isinstance(publication, dict):
                continue
            data = publication.get("data")
            if not isinstance(data, dict):
                continue
            message = data.get("message")
            if isinstance(message, dict) and message.get("id") == message_id:
                return
    raise TimeoutError("The PostgreSQL outbox publication did not arrive")


def main() -> int:
    suffix = uuid4().hex[:10]
    project_id: int | None = None
    with SessionLocal() as db:
        admin = db.scalar(
            select(User).where(User.role == "admin").order_by(User.id.asc()),
        )
        if admin is None:
            raise RuntimeError("No platform administrator is available for verification")
        project = Project(name=f"__chat_realtime_verification_{suffix}")
        db.add(project)
        db.commit()
        db.refresh(project)
        project_id = project.id
        access_token = create_access_token(admin.id, admin.role)

    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(
            base_url=API_BASE_URL,
            headers=headers,
            timeout=10,
        ) as client:
            channel_response = client.get(f"/projects/{project_id}/chat/channels")
            channel_response.raise_for_status()
            channel = channel_response.json()["data"][0]

            token_response = client.get(
                f"/projects/{project_id}/chat/realtime-token",
            )
            token_response.raise_for_status()
            realtime = token_response.json()["data"]
            if not realtime["enabled"] or not realtime["token"]:
                raise RuntimeError("The backend did not enable the realtime token")

            with connect(
                realtime["ws_url"],
                origin=EXPECTED_ORIGIN,
                open_timeout=5,
            ) as websocket:
                websocket.send(
                    json.dumps(
                        {
                            "id": 1,
                            "connect": {
                                "token": realtime["token"],
                                "name": "dobby-realtime-verifier",
                            },
                        },
                    ),
                )
                _wait_for_connect(websocket)

                content = f"realtime-verification-{suffix}"
                message_response = client.post(
                    f"/chat/channels/{channel['id']}/messages",
                    json={
                        "content": content,
                        "client_message_id": f"verify-{uuid4().hex}",
                    },
                )
                message_response.raise_for_status()
                created = message_response.json()["data"]
                _wait_for_message(websocket, int(created["id"]))

        print("PROJECT_CHAT_REALTIME_OK")
        return 0
    finally:
        if project_id is not None:
            with SessionLocal() as db:
                project = db.get(Project, project_id)
                if project is not None:
                    db.delete(project)
                    db.commit()


if __name__ == "__main__":
    raise SystemExit(main())
