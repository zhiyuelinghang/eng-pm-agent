import hashlib
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Dobby API"
    environment: str = "development"
    database_url: str
    database_schema: str = "platform"
    memory_database_url: str = ""
    memory_database_schema: str = "memory"
    memory_tenant_id: str = ""
    agentscope_global_config_id: str = ""
    jwt_secret: str = "change-this-in-production"
    connector_secret_key: str = ""
    jwt_expire_minutes: int = 480
    cors_origins: str = "http://localhost:38429,http://127.0.0.1:38429"
    frontend_public_url: str = "http://127.0.0.1:38429"
    centrifugo_enabled: bool = False
    centrifugo_ws_url: str = "ws://127.0.0.1:38431/connection/websocket"
    centrifugo_token_secret: str = ""
    centrifugo_token_ttl_seconds: int = 120
    centrifugo_bind_address: str = "0.0.0.0"
    centrifugo_port: int = 38431
    upload_dir: Path = Path("data/uploads")
    agentscope_base_url: str = "http://127.0.0.1:18642"
    agentscope_service_token: str = ""
    dobby_agent_tool_token: str = ""
    agentscope_request_timeout_seconds: float = 150.0
    agentscope_poll_interval_seconds: float = 0.35

    # 任务引擎：沿用平台 DATABASE_URL，仅使用独立 schema 隔离引擎表。
    task_engine_schema: str = "task_engine"
    task_engine_tz: str = "Asia/Shanghai"
    task_engine_tick_interval_seconds: float = 5.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def effective_agent_tool_token(self) -> str:
        """Return the internal AgentScope -> Dobby gateway credential."""
        return self.dobby_agent_tool_token.strip() or self.agentscope_service_token.strip()

    @property
    def effective_centrifugo_token_secret(self) -> str:
        """Use a dedicated key, or derive an isolated local key from JWT_SECRET."""

        dedicated = self.centrifugo_token_secret.strip()
        if dedicated:
            return dedicated
        jwt_secret = self.jwt_secret.strip()
        if not jwt_secret:
            return ""
        return hashlib.sha256(
            f"dobby-centrifugo:{jwt_secret}".encode("utf-8"),
        ).hexdigest()


@lru_cache
def get_settings() -> Settings:
    return Settings()
