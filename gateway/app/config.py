from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量 / .env 读取的配置。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://app:app@db:5432/engpm"
    redis_url: str = "redis://redis:6379/0"
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin123"

    # JWT（前期默认值仅供本地开发，生产须用环境变量覆盖）
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720

    # Hermes（角色 C 的运行底座）只读对接配置。
    # 令牌从 .env 注入，切勿写入代码或提交到仓库。
    hermes_base_url: str = "http://127.0.0.1:8088"
    hermes_api_key: str = ""
    hermes_timeout: float = 10.0

    # 微信群消息归档目录（weflow-archive 脚本的产出根目录）
    weflow_archive_root: str = "/workspace/eng-pm-agent/weflow-archive"


settings = Settings()
