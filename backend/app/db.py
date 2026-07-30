from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


settings = get_settings()
database_url = settings.database_url
if database_url.startswith("sqlite:///"):
    database_path = database_url.removeprefix("sqlite:///")
    if database_path and database_path != ":memory:":
        resolved_path = Path(database_path).expanduser()
        if not resolved_path.is_absolute():
            resolved_path = Path(__file__).resolve().parents[2] / resolved_path
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        database_url = f"sqlite:///{resolved_path.as_posix()}"
connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

if database_url.startswith("sqlite"):
    @event.listens_for(Engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
