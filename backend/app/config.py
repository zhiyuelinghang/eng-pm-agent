from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Dobby API"
    environment: str = "development"
    database_url: str
    database_schema: str = "platform"
    jwt_secret: str = "change-this-in-production"
    connector_secret_key: str = ""
    jwt_expire_minutes: int = 480
    cors_origins: str = "http://localhost:38429,http://127.0.0.1:38429"
    upload_dir: Path = Path("data/uploads")
    ai_api_key: str = ""
    ai_base_url: str = "https://api.openai.com/v1"
    ai_model: str = "gpt-4.1-mini"
    agentscope_base_url: str = "http://127.0.0.1:18642"
    agentscope_service_token: str = ""
    dobby_agent_tool_token: str = ""
    agentscope_request_timeout_seconds: float = 150.0
    agentscope_poll_interval_seconds: float = 0.35

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def effective_agent_tool_token(self) -> str:
        """Return the internal AgentScope -> Dobby gateway credential."""
        return self.dobby_agent_tool_token.strip() or self.agentscope_service_token.strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()
