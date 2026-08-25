from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.engine import make_url

from backend.app.config import get_settings


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = PROJECT_ROOT / "runtime" / "centrifugo"
CONFIG_PATH = RUNTIME_DIR / "config.json"


def _postgres_dsn() -> str:
    settings = get_settings()
    url = make_url(settings.database_url)
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("项目群聊实时投递只支持当前 PostgreSQL 数据库")
    query = dict(url.query)
    query["options"] = f"-csearch_path={settings.database_schema},public"
    return url.set(
        drivername="postgresql",
        query=query,
    ).render_as_string(hide_password=False)


def build_config() -> dict[str, object]:
    settings = get_settings()
    secret = settings.effective_centrifugo_token_secret
    if len(secret.encode("utf-8")) < 32:
        raise RuntimeError(
            "CENTRIFUGO_TOKEN_SECRET（或本地回退的 JWT_SECRET）至少需要 32 字节",
        )
    return {
        "http_server": {
            "address": settings.centrifugo_bind_address,
            "port": settings.centrifugo_port,
        },
        "client": {
            "token": {
                "hmac_secret_key": secret,
                "audience": "dobby-realtime",
                "issuer": "dobby-platform",
            },
            "allowed_origins": settings.cors_origin_list,
        },
        "channel": {
            "namespaces": [
                {
                    "name": "chat",
                    "history_size": 100,
                    "history_ttl": "10m",
                    "force_recovery": True,
                },
            ],
        },
        "admin": {"enabled": False},
        "consumers": [
            {
                "enabled": True,
                "name": "chat_outbox",
                "type": "postgresql",
                "postgresql": {
                    "dsn": _postgres_dsn(),
                    "outbox_table_name": "chat_realtime_outbox",
                    "num_partitions": 1,
                    "partition_select_limit": 100,
                    "partition_poll_interval": "300ms",
                    "partition_notification_channel": (
                        "chat_realtime_outbox_changed"
                    ),
                },
            },
        ],
    }


def main() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(build_config(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("[Done] Centrifugo runtime config generated: runtime/centrifugo/config.json")


if __name__ == "__main__":
    main()
