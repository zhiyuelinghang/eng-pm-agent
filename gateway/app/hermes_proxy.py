"""Hermes 只读代理路由。

前端不直接访问 Hermes（其 CORS 关闭，且令牌不能下发到浏览器），
统一由网关后端携带令牌转发，仅暴露只读的元数据 / 会话查询接口。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from .config import settings

router = APIRouter(prefix="/hermes", tags=["hermes"])


def _hermes_get(path: str, *, auth: bool = True) -> dict:
    """向 Hermes 发起 GET 请求并返回解析后的 JSON。"""
    url = settings.hermes_base_url.rstrip("/") + path
    req = urllib.request.Request(url, method="GET")
    if auth and settings.hermes_api_key:
        req.add_header("Authorization", f"Bearer {settings.hermes_api_key}")
    try:
        with urllib.request.urlopen(req, timeout=settings.hermes_timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # noqa: PERF203
        raise HTTPException(status_code=502, detail=f"Hermes 返回 {exc.code}: {exc.reason}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"无法连接 Hermes: {exc}")


def _hermes_request(method: str, path: str, payload: dict | None = None) -> dict:
    """向 Hermes 发起写请求（POST/PATCH/DELETE）。"""
    url = settings.hermes_base_url.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if settings.hermes_api_key:
        req.add_header("Authorization", f"Bearer {settings.hermes_api_key}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=settings.hermes_timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")
        try:
            detail = json.loads(detail).get("error", detail)
        except Exception:  # noqa: BLE001
            pass
        raise HTTPException(status_code=400, detail=f"Hermes: {detail}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"无法连接 Hermes: {exc}")


@router.get("/overview")
def overview():
    """平台概览：健康状态 + 能力 + 模型 + 数量统计。"""
    health = _hermes_get("/health", auth=False)
    caps = _hermes_get("/v1/capabilities")
    models = _hermes_get("/v1/models").get("data", [])
    skills = _hermes_get("/v1/skills").get("data", [])
    toolsets = _hermes_get("/v1/toolsets").get("data", [])
    try:
        sessions = _hermes_get("/api/sessions").get("data", [])
    except HTTPException:
        sessions = []
    try:
        jobs = _hermes_get("/api/jobs").get("jobs", [])
    except HTTPException:
        jobs = []

    enabled_toolsets = [t for t in toolsets if t.get("enabled")]
    active_jobs = [j for j in jobs if j.get("enabled") and j.get("state") != "paused"]
    return {
        "platform": health.get("platform") or caps.get("platform"),
        "status": health.get("status"),
        "runtime": caps.get("runtime", {}),
        "features": caps.get("features", {}),
        "models": [m.get("id") for m in models],
        "stats": {
            "skills": len(skills),
            "toolsets": len(toolsets),
            "toolsets_enabled": len(enabled_toolsets),
            "sessions": len(sessions),
            "jobs": len(jobs),
            "jobs_active": len(active_jobs),
        },
    }


@router.get("/skills")
def skills():
    """技能清单（按返回原样，前端按 category 分组）。"""
    return _hermes_get("/v1/skills").get("data", [])


@router.get("/toolsets")
def toolsets():
    """工具集清单。"""
    return _hermes_get("/v1/toolsets").get("data", [])


@router.get("/sessions")
def sessions():
    """会话历史（最近在前）。"""
    data = _hermes_get("/api/sessions").get("data", [])
    data.sort(key=lambda s: s.get("last_active") or 0, reverse=True)
    return data


@router.get("/jobs")
def jobs():
    """定时任务（cron）列表，next_run 升序。"""
    data = _hermes_get("/api/jobs").get("jobs", [])
    data.sort(key=lambda j: j.get("next_run_at") or "9999")
    return data


@router.post("/jobs")
def create_job(payload: dict = Body(...)):
    """创建定时任务。必填 name、schedule，可选 prompt。"""
    name = (payload.get("name") or "").strip()
    schedule = (payload.get("schedule") or "").strip()
    if not name or not schedule:
        raise HTTPException(status_code=422, detail="name 和 schedule 必填")
    body = {"name": name, "schedule": schedule, "prompt": payload.get("prompt") or ""}
    return _hermes_request("POST", "/api/jobs", body)


@router.patch("/jobs/{job_id}")
def update_job(job_id: str, payload: dict = Body(...)):
    """暂停/恢复任务：{enabled: false/true}。"""
    body = {"enabled": bool(payload.get("enabled"))}
    return _hermes_request("PATCH", f"/api/jobs/{job_id}", body)


@router.post("/jobs/{job_id}/run")
def run_job(job_id: str):
    """让任务在下次调度 tick 立即运行一次。"""
    return _hermes_request("POST", f"/api/jobs/{job_id}/run", {})


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    """删除定时任务。"""
    return _hermes_request("DELETE", f"/api/jobs/{job_id}")


# ---- 微信群消息归档（weflow-archive 脚本产出）只读展示 ----

def _archive_root() -> Path:
    return Path(settings.weflow_archive_root)


@router.get("/wechat/groups")
def wechat_groups():
    """微信群列表：从 _index.json 读取，附最近归档日期与今日消息数。"""
    root = _archive_root()
    index = root / "_index.json"
    if not index.exists():
        return []
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"解析归档索引失败: {exc}")

    groups = []
    for chatroom_id, info in data.items():
        folder = root / info.get("folder", "")
        dates, last_date, last_count = [], None, 0
        text_dir = folder / "text"
        if text_dir.is_dir():
            dates = sorted(
                (f.stem for f in text_dir.glob("*.jsonl")), reverse=True
            )
            if dates:
                last_date = dates[0]
                try:
                    with (text_dir / f"{last_date}.jsonl").open(encoding="utf-8") as fh:
                        last_count = sum(1 for _ in fh)
                except Exception:  # noqa: BLE001
                    last_count = 0
        members = 0
        mfile = folder / "members.json"
        if mfile.exists():
            try:
                m = json.loads(mfile.read_text(encoding="utf-8"))
                members = len(m) if isinstance(m, (list, dict)) else 0
            except Exception:  # noqa: BLE001
                members = 0
        groups.append({
            "chatroom_id": chatroom_id,
            "name": info.get("displayName") or info.get("folder"),
            "folder": info.get("folder"),
            "dates": dates,
            "last_date": last_date,
            "last_count": last_count,
            "members": members,
            "updated": info.get("updated"),
        })
    groups.sort(key=lambda g: g.get("updated") or 0, reverse=True)
    return groups


def _safe_folder(root: Path, folder: str) -> Path:
    """防目录穿越：folder 必须是 root 下的直接子目录。"""
    target = (root / folder).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        raise HTTPException(status_code=400, detail="非法路径")
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="群归档不存在")
    return target


@router.get("/wechat/messages")
def wechat_messages(folder: str, date: str | None = None):
    """某群某天的消息列表。date 省略时取最新一天。"""
    root = _archive_root()
    target = _safe_folder(root, folder)
    text_dir = target / "text"
    if not text_dir.is_dir():
        return {"date": None, "dates": [], "messages": []}
    dates = sorted((f.stem for f in text_dir.glob("*.jsonl")), reverse=True)
    if not dates:
        return {"date": None, "dates": [], "messages": []}
    if date is None or date not in dates:
        date = dates[0]
    # 基本日期校验，防穿越
    if not all(c.isdigit() or c == "-" for c in date):
        raise HTTPException(status_code=400, detail="非法日期")
    messages = []
    jf = text_dir / f"{date}.jsonl"
    if jf.exists():
        with jf.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    m = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                media = m.get("media") or {}
                meta = media.get("meta") or {}
                messages.append({
                    "time": m.get("time"),
                    "type": m.get("typeName"),
                    "sender": m.get("senderName") or m.get("sender"),
                    "is_send": m.get("isSend"),
                    "content": m.get("content"),
                    "has_media": bool(media),
                    "media_kind": media.get("kind"),
                    "media_category": media.get("category"),
                    "file_name": meta.get("filename"),
                    "file_ext": meta.get("fileext"),
                    "file_size": meta.get("size") or meta.get("length"),
                })
    return {"date": date, "dates": dates, "messages": messages}
