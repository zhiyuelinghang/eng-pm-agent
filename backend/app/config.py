from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "工程智管家 API"
    environment: str = "development"
    database_url: str = "sqlite:///./data/engpm.db"
    jwt_secret: str = "change-this-in-production"
    jwt_expire_minutes: int = 480
    cors_origins: str = "http://localhost:38429,http://127.0.0.1:38429"
    upload_dir: Path = Path("data/uploads")
    ai_api_key: str = ""
    ai_base_url: str = "https://api.openai.com/v1"
    ai_model: str = "gpt-4.1-mini"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
