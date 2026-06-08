from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, text
import redis
from minio import Minio

from .config import settings
from .database import Base, engine
from . import models  # noqa: F401  确保模型被注册后再建表
from .routers import router
from .auth_router import router as auth_router
from .hermes_proxy import router as hermes_router
from .users_router import router as users_router
from .roles_router import router as roles_router

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="工程管理智能体 · 平台骨架")


@app.on_event("startup")
def on_startup():
    """启动时自动建表（前期用，后续可换 Alembic 迁移），并种入内置角色。"""
    Base.metadata.create_all(bind=engine)
    _seed_builtin_roles()


def _seed_builtin_roles():
    """确保内置角色 admin / member 存在。"""
    from sqlalchemy.orm import Session

    builtin = [
        ("admin", "管理员", "平台管理员，拥有用户与角色管理等全部权限"),
        ("member", "普通成员", "普通成员，仅能查看被授权的项目数据"),
    ]
    with Session(engine) as db:
        for code, name, desc in builtin:
            exists = db.query(models.Role).filter(models.Role.code == code).first()
            if exists is None:
                db.add(models.Role(code=code, name=name, description=desc, builtin=True))
        db.commit()

app.include_router(auth_router)
app.include_router(router)
app.include_router(hermes_router)
app.include_router(users_router)
app.include_router(roles_router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def root():
    """B7 演示页。"""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    """检查 PostgreSQL / Redis / MinIO 三个依赖是否连通。"""
    checks: dict[str, str] = {}

    try:
        engine = create_engine(settings.database_url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["postgres"] = f"error: {exc}"

    try:
        redis.from_url(settings.redis_url).ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {exc}"

    try:
        Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=False,
        ).list_buckets()
        checks["minio"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["minio"] = f"error: {exc}"

    return {"healthy": all(v == "ok" for v in checks.values()), "checks": checks}
