from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .api import router
from .config import get_settings
from .db import Base, SessionLocal, engine
from .models import User
from .security import hash_password


def seed_admin() -> None:
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.username == "admin")):
            db.add(User(username="admin", real_name="系统管理员", password_hash=hash_password("ChangeMe123!"), role="superadmin"))
            db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    seed_admin()
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}
