#!/usr/bin/env python3
"""
weflow-mcp: 把 WeFlow 的 HTTP API 包装成 MCP 工具供 Hermes 调用。

本版在原有"查询"能力之上，增加了"归档"能力，用于把群聊记录
持久化成项目资料：分群存储、按类型分子文件夹、按自然日切片、
保留时间戳、增量追加（不重头整理）。

启动（stdio）：
    WEFLOW_BASE=http://100.x.x.10:5031 \\
    WEFLOW_TOKEN=xxxx \\
    WEFLOW_ARCHIVE_ROOT=/workspace/eng-pm-agent/weflow-archive \\
    python3 weflow_mcp.py

依赖：
    pip install "mcp[cli]>=1.0" requests

环境变量：
    WEFLOW_BASE          WeFlow API 地址（默认 http://127.0.0.1:5031）
    WEFLOW_TOKEN         访问令牌（必填）
    WEFLOW_ARCHIVE_ROOT  归档根目录（默认 /workspace/eng-pm-agent/weflow-archive）
                         多个 profile 想共享归档时，把它们都指向同一个目录。
    WEFLOW_ARCHIVE_GROUPS  定时归档的群列表，逗号分隔的 chatroomId
                           （供 archive_all_configured_groups 使用）
    WEFLOW_KEEP_VOICE    是否归档语音，默认 0（不归档，按需求关闭）
    WEFLOW_KEEP_EMOJI    是否归档表情，默认 0（表情包通常不是项目资料）
    WEFLOW_KEEP_VIDEO    是否归档视频，默认 1
    WEFLOW_LOOKBACK_DAYS 增量归档默认回看天数，默认 2（含当天，兜住迟到消息）

注：本进程建议跑在能同时访问 WeFlow（Windows）和归档目录的机器/容器上。
    它通过 NetBird/局域网 IP 访问 Windows 上的 WeFlow API；mediaUrl 里的
    127.0.0.1 会被自动改写成 WEFLOW_BASE 的主机。
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import time
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

import requests
from mcp.server.fastmcp import FastMCP

try:
    import fcntl  # POSIX 文件锁；非 POSIX 平台降级为无锁
    _HAS_FCNTL = True
except ImportError:  # pragma: no cover
    _HAS_FCNTL = False

# ----------------------------- 配置 -----------------------------
WEFLOW_BASE = os.environ.get("WEFLOW_BASE", "http://127.0.0.1:5031").rstrip("/")
WEFLOW_TOKEN = os.environ.get("WEFLOW_TOKEN", "")
ARCHIVE_ROOT = os.environ.get(
    "WEFLOW_ARCHIVE_ROOT", "/workspace/eng-pm-agent/weflow-archive"
)


def _env_flag(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


KEEP_VOICE = _env_flag("WEFLOW_KEEP_VOICE", False)
KEEP_EMOJI = _env_flag("WEFLOW_KEEP_EMOJI", False)
KEEP_VIDEO = _env_flag("WEFLOW_KEEP_VIDEO", True)
LOOKBACK_DAYS = int(os.environ.get("WEFLOW_LOOKBACK_DAYS", "2"))

# 自然日切片用的时区偏移（小时）。默认 +8（北京时间），避免容器时区不同
# 导致临近午夜的消息被切到错误的日期。可用 WEFLOW_TZ_OFFSET 调整。
TZ_OFFSET_HOURS = float(os.environ.get("WEFLOW_TZ_OFFSET", "8"))
_TZ = dt.timezone(dt.timedelta(hours=TZ_OFFSET_HOURS))

# localType -> 可读类型名
LOCAL_TYPE_NAMES = {
    1: "text", 3: "image", 34: "voice", 43: "video", 47: "emoji", 49: "app",
}

# 扩展名 -> 归档子目录分类
EXT_CATEGORY = {
    # 图片
    ".jpg": "images", ".jpeg": "images", ".png": "images", ".gif": "images",
    ".webp": "images", ".bmp": "images", ".heic": "images",
    # 视频
    ".mp4": "videos", ".mov": "videos", ".avi": "videos", ".mkv": "videos",
    # 文档
    ".doc": "word", ".docx": "word",
    ".pdf": "pdf",
    ".xls": "excel", ".xlsx": "excel", ".csv": "excel",
    ".ppt": "ppt", ".pptx": "ppt",
    ".txt": "files", ".zip": "files", ".rar": "files", ".7z": "files",
}

mcp = FastMCP("weflow")

# ----------------------------- HTTP -----------------------------


def _get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    if not WEFLOW_TOKEN:
        raise RuntimeError("环境变量 WEFLOW_TOKEN 未设置")
    r = requests.get(
        f"{WEFLOW_BASE}{path}",
        params=params,
        headers={"Authorization": f"Bearer {WEFLOW_TOKEN}"},
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and data.get("success") is False:
        raise RuntimeError(f"WeFlow 返回错误：{data}")
    return data


def _rewrite_media_host(media_url: str) -> str:
    """把 mediaUrl 里的 127.0.0.1:5031 改写成 WEFLOW_BASE 的 scheme+host。"""
    if not media_url:
        return media_url
    base = urlsplit(WEFLOW_BASE)
    cur = urlsplit(media_url)
    # 只替换 scheme 和 netloc，路径/查询保留
    return urlunsplit((base.scheme, base.netloc, cur.path, cur.query, cur.fragment))


def _download(media_url: str) -> bytes:
    """通过 HTTP 下载媒体文件（带鉴权，自动改写 host）。"""
    url = _rewrite_media_host(media_url)
    r = requests.get(
        url,
        headers={"Authorization": f"Bearer {WEFLOW_TOKEN}"},
        timeout=120,
    )
    r.raise_for_status()
    return r.content


# ----------------------------- 工具：路径/文件 -----------------------------


def _sanitize(name: str, fallback: str = "unknown") -> str:
    """清洗成安全的文件/目录名。"""
    if not name:
        return fallback
    name = name.strip()
    # 替换路径分隔符与不安全字符
    name = re.sub(r"[\\/:*?\"<>|@\s]+", "_", name)
    name = name.strip("._") or fallback
    return name[:80]


def _ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def _read_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json(path: str, obj: Any) -> None:
    _ensure_dir(os.path.dirname(path))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


@contextlib.contextmanager
def _locked(lock_path: str):
    """跨进程文件锁，保证多个 profile 并发归档同一群时不冲突。"""
    _ensure_dir(os.path.dirname(lock_path))
    f = open(lock_path, "w")
    try:
        if _HAS_FCNTL:
            fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        if _HAS_FCNTL:
            with contextlib.suppress(Exception):
                fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def _category_for(filename: str, media_type: str) -> str:
    """根据文件名扩展名 + mediaType 推断归档分类子目录。"""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in EXT_CATEGORY:
        return EXT_CATEGORY[ext]
    mt = (media_type or "").lower()
    if mt == "image":
        return "images"
    if mt == "video":
        return "videos"
    if mt in ("voice", "audio"):
        return "voices"
    return "other"


def _ts_to_date(ts: int) -> str:
    """Unix 秒 -> 指定时区的自然日 YYYY-MM-DD（默认北京时间）。"""
    return dt.datetime.fromtimestamp(ts, _TZ).strftime("%Y-%m-%d")


def _ts_to_human(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, _TZ).strftime("%Y-%m-%d %H:%M:%S")


def _is_group(session: dict) -> bool:
    """稳健判定一个会话是否为群聊。
    WeFlow 数据里 type 普遍为 0，真正区分类型靠 sessionType
    (group/channel/private)；同时微信群 username 形如 xxx@chatroom。
    两个条件满足其一即认为是群聊。"""
    st = (session.get("sessionType") or "").lower()
    if st:
        return st == "group"
    return str(session.get("username", "")).endswith("@chatroom")


def _xml_first(xml: str, tag: str) -> str:
    """从一段 XML 文本里取第一个 <tag>...</tag> 的内容（轻量，不引入解析器依赖）。"""
    if not xml:
        return ""
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.DOTALL)
    return m.group(1).strip() if m else ""


def _xml_attr(xml: str, tag: str, attr: str) -> str:
    """取 <tag ... attr="值" ...> 里某个属性值。"""
    if not xml:
        return ""
    m = re.search(rf"<{tag}\b[^>]*\b{attr}=\"(.*?)\"", xml, re.DOTALL)
    return m.group(1).strip() if m else ""


def _classify_message(msg: dict) -> dict:
    """根据 content 前缀 + rawContent 的 XML，判定消息真实类型并提取媒体元数据。

    返回: {"typeName": ..., "category": ..., "meta": {...或None}}
      typeName: text/image/video/voice/file/emoji/link/other
      category: 归档子目录（images/videos/word/pdf/excel/ppt/files/other/None）
      meta:     文件/图片的元数据（文件名、大小、md5、cdn 引用等），无则 None
    """
    ltype = msg.get("localType")
    raw = msg.get("rawContent") or ""
    content = msg.get("parsedContent") or msg.get("content") or ""

    # 纯文本（localType==1 且无 appmsg/img）
    if ltype == 1 and "<appmsg" not in raw and "<img" not in raw:
        return {"typeName": "text", "category": None, "meta": None}

    # 图片：localType==3 或 rawContent 里有 <img
    if ltype == 3 or "<img " in raw or "<img\t" in raw:
        meta = {
            "md5": _xml_attr(raw, "img", "md5"),
            "length": _xml_attr(raw, "img", "length"),
            "aeskey": _xml_attr(raw, "img", "aeskey"),
        }
        meta = {k: v for k, v in meta.items() if v}
        return {"typeName": "image", "category": "images", "meta": meta or None}

    # 视频
    if ltype == 43 or "<videomsg" in raw:
        return {"typeName": "video", "category": "videos", "meta": None}

    # 语音
    if ltype == 34 or "<voicemsg" in raw:
        return {"typeName": "voice", "category": "voices", "meta": None}

    # 表情
    if ltype == 47 or "<emoji " in raw:
        return {"typeName": "emoji", "category": "emojis", "meta": None}

    # 文件 / 应用消息：rawContent 里有 <appmsg>
    if "<appmsg" in raw:
        title = _xml_first(raw, "title")
        fileext = _xml_first(raw, "fileext").lower()
        appmsg_type = _xml_first(raw, "type")  # <type>6</type> 表示文件
        totallen = _xml_first(raw, "totallen")
        md5 = _xml_first(raw, "md5")
        # 有 fileext 或 appmsg type=6 => 文件
        if fileext or appmsg_type == "6":
            ext = ("." + fileext) if fileext and not fileext.startswith(".") else (fileext or os.path.splitext(title)[1])
            category = EXT_CATEGORY.get(ext.lower(), "files")
            meta = {
                "filename": title,
                "fileext": fileext,
                "size": int(totallen) if totallen.isdigit() else totallen,
                "md5": md5,
                "attachid": _xml_first(raw, "attachid"),
                "cdnattachurl": _xml_first(raw, "cdnattachurl"),
                "aeskey": _xml_first(raw, "aeskey"),
                "media_expire_at": _xml_first(raw, "media_expire_at"),
            }
            meta = {k: v for k, v in meta.items() if v}
            return {"typeName": "file", "category": category, "meta": meta}
        # 其它 appmsg（链接/卡片等）
        link_title = title or content
        return {"typeName": "link", "category": None,
                "meta": {"title": link_title} if link_title else None}

    # 兜底
    return {"typeName": "other", "category": None, "meta": None}


# ----------------------------- 群目录索引 -----------------------------


def _index_path() -> str:
    return os.path.join(ARCHIVE_ROOT, "_index.json")


def _resolve_group_dir(chatroom_id: str, display_name: str = "") -> str:
    """为某个 chatroomId 解析/创建稳定的归档目录。
    目录名一旦确定就复用（即使群改名也不另起目录）。"""
    with _locked(os.path.join(ARCHIVE_ROOT, "_index.lock")):
        index = _read_json(_index_path(), {})
        entry = index.get(chatroom_id)
        if entry and entry.get("folder"):
            folder = entry["folder"]
            # 更新一下显示名
            if display_name and entry.get("displayName") != display_name:
                entry["displayName"] = display_name
                entry["updated"] = int(time.time())
                index[chatroom_id] = entry
                _write_json(_index_path(), index)
        else:
            slug = _sanitize(display_name) if display_name else _sanitize(chatroom_id)
            short = hashlib.sha1(chatroom_id.encode("utf-8")).hexdigest()[:8]
            folder = f"{slug}_{short}"
            index[chatroom_id] = {
                "folder": folder,
                "chatroomId": chatroom_id,
                "displayName": display_name,
                "created": int(time.time()),
                "updated": int(time.time()),
            }
            _write_json(_index_path(), index)
        group_dir = os.path.join(ARCHIVE_ROOT, folder)
        _ensure_dir(group_dir)
        # 写一份可读的群信息
        info_path = os.path.join(group_dir, "_group_info.json")
        info = _read_json(info_path, {})
        info.update({
            "chatroomId": chatroom_id,
            "displayName": display_name or info.get("displayName", ""),
            "folder": folder,
        })
        _write_json(info_path, info)
        return group_dir


# ----------------------------- 成员名解析 -----------------------------


def _pick_member_name(m: dict) -> str:
    for k in ("groupNickname", "remark", "displayName", "nickname", "alias"):
        v = m.get(k)
        if v:
            return v
    return m.get("wxid", "")


def _refresh_members(chatroom_id: str, group_dir: str) -> dict[str, str]:
    """拉取群成员并缓存 wxid->显示名 到 members.json。失败则用旧缓存。"""
    members_path = os.path.join(group_dir, "members.json")
    try:
        data = _get("/api/v1/group-members", {"chatroomId": chatroom_id})
        mapping = {
            m["wxid"]: _pick_member_name(m)
            for m in data.get("members", [])
            if m.get("wxid")
        }
        if mapping:
            _write_json(members_path, {
                "chatroomId": chatroom_id,
                "updatedAt": int(time.time()),
                "members": mapping,
            })
        return mapping
    except Exception:
        cached = _read_json(members_path, {})
        return cached.get("members", {})


# ----------------------------- 归档核心 -----------------------------


def _existing_local_ids(day_file: str) -> set:
    """读出某天文字日志里已存在的 localId，用于去重。"""
    ids = set()
    if not os.path.exists(day_file):
        return ids
    with open(day_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if "localId" in obj and obj["localId"] is not None:
                    ids.add(obj["localId"])
            except json.JSONDecodeError:
                continue
    return ids


def _msg_dedup_key(msg: dict) -> Any:
    """localId 优先；缺失时用 (createTime, sender, content) 的哈希兜底。"""
    if msg.get("localId") is not None:
        return msg["localId"]
    raw = f"{msg.get('createTime')}|{msg.get('senderUsername')}|{msg.get('content')}"
    return "h:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _archive_messages(
    chatroom_id: str,
    display_name: str,
    messages: list[dict],
    members: dict[str, str],
    group_dir: str,
) -> dict:
    """把一批消息写入归档（去重、分类、按日切片、保留时间戳）。"""
    text_root = _ensure_dir(os.path.join(group_dir, "text"))
    # 预读涉及到的每天已存在 localId
    day_ids_cache: dict[str, set] = {}

    stats = {
        "appended": 0, "skipped_dup": 0, "skipped_voice": 0, "skipped_emoji": 0,
        "media_downloaded": 0, "media_failed": 0, "media_reference_only": 0,
        "by_category": {}, "max_local_id": None,
    }

    # 按 localId / createTime 升序，保证写入顺序即时间顺序
    def _sort_key(m):
        return (m.get("localId") if m.get("localId") is not None else 0,
                m.get("createTime", 0))
    messages = sorted(messages, key=_sort_key)

    for msg in messages:
        ts = int(msg.get("createTime") or 0)
        day = _ts_to_date(ts) if ts else "0000-00-00"
        day_file = os.path.join(text_root, f"{day}.jsonl")

        if day not in day_ids_cache:
            day_ids_cache[day] = _existing_local_ids(day_file)

        dedup = _msg_dedup_key(msg)
        if dedup in day_ids_cache[day]:
            stats["skipped_dup"] += 1
            continue

        sender_wxid = msg.get("senderUsername", "")
        sender_name = members.get(sender_wxid, sender_wxid)

        # 用 content 前缀 + rawContent XML 判定真实类型，提取媒体元数据
        cls = _classify_message(msg)
        type_name = cls["typeName"]
        category = cls["category"]
        meta = cls["meta"]

        # 语音/表情按配置跳过（这里是基于真实类型再判一次，兜住复合 localType）
        if type_name == "voice" and not KEEP_VOICE:
            stats["skipped_voice"] += 1
            continue
        if type_name == "emoji" and not KEEP_EMOJI:
            stats["skipped_emoji"] += 1
            continue

        media_ref = None
        media_url = msg.get("mediaUrl") or ""  # WeFlow 目前基本为空

        if category in ("images", "videos", "voices", "word", "pdf", "excel", "ppt", "files", "other") or type_name in ("file", "image", "video"):
            if category == "videos" and not KEEP_VIDEO:
                media_ref = {"kind": "video_skipped", "meta": meta}
            elif media_url:
                # WeFlow 若真的给了可下载地址，就下载本体
                try:
                    content_bytes = _download(media_url)
                    safe_sender = _sanitize(sender_name, "x")
                    fname = (meta or {}).get("filename") or f"{msg.get('localId','m')}"
                    safe_name = _sanitize(fname, f"{msg.get('localId','m')}")
                    if not os.path.splitext(safe_name)[1] and meta and meta.get("fileext"):
                        safe_name += "." + meta["fileext"]
                    out_dir = _ensure_dir(os.path.join(group_dir, category or "other", day))
                    out_path = os.path.join(out_dir, f"{ts}_{safe_sender}_{safe_name}")
                    with open(out_path, "wb") as f:
                        f.write(content_bytes)
                    if ts:
                        with contextlib.suppress(Exception):
                            os.utime(out_path, (ts, ts))
                    media_ref = {"kind": category, "file": os.path.relpath(out_path, group_dir), "meta": meta}
                    stats["media_downloaded"] += 1
                    stats["by_category"][category] = stats["by_category"].get(category, 0) + 1
                except Exception as e:
                    media_ref = {"kind": "download_failed", "meta": meta, "error": str(e)[:200]}
                    stats["media_failed"] += 1
            else:
                # 无下载地址（当前 WeFlow 的图片/文件均属此类）：
                # 保留完整元数据为"引用"，并把引用清单按分类落到对应子目录，
                # 这样日后查"哪天发过哪些 PDF/图片"能直接定位。
                media_ref = {"kind": "reference_only", "category": category, "meta": meta,
                             "note": "WeFlow 未提供可下载本体，已保留文件名/大小/md5/CDN 引用"}
                stats["media_reference_only"] += 1
                # 同步写一条引用清单到 <category>/<day>/_refs.jsonl
                if category and meta:
                    ref_dir = _ensure_dir(os.path.join(group_dir, category, day))
                    ref_line = {"localId": msg.get("localId"), "ts": ts,
                                "time": _ts_to_human(ts) if ts else "",
                                "sender": sender_wxid, "senderName": sender_name, "meta": meta}
                    with open(os.path.join(ref_dir, "_refs.jsonl"), "a", encoding="utf-8") as rf:
                        rf.write(json.dumps(ref_line, ensure_ascii=False) + "\n")

        record = {
            "localId": msg.get("localId"),
            "serverId": msg.get("serverId"),
            "ts": ts,
            "time": _ts_to_human(ts) if ts else "",
            "typeName": type_name,
            "isSend": msg.get("isSend"),
            "sender": sender_wxid,
            "senderName": sender_name,
            "content": msg.get("parsedContent") or msg.get("content") or "",
            "media": media_ref,
        }

        _ensure_dir(text_root)
        with open(day_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        day_ids_cache[day].add(dedup)
        stats["appended"] += 1
        lid = msg.get("localId")
        if lid is not None:
            if stats["max_local_id"] is None or lid > stats["max_local_id"]:
                stats["max_local_id"] = lid

    return stats


def _fetch_window(chatroom_id: str, start: str, end: str, limit: int = 10000) -> list[dict]:
    """拉取 [start,end] 的消息，开启图片/视频媒体导出（关闭语音/表情）。"""
    params: dict[str, Any] = {
        "talker": chatroom_id, "limit": limit,
        "media": 1,
        "image": 1,
        "voice": 1 if KEEP_VOICE else 0,
        "video": 1 if KEEP_VIDEO else 0,
        "emoji": 1 if KEEP_EMOJI else 0,
    }
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    data = _get("/api/v1/messages", params)
    return data.get("messages", [])


def _do_archive(chatroom_id: str, start: str, end: str, display_name: str = "") -> dict:
    """归档某个时间窗口，带锁、更新状态。返回统计。"""
    # 先尽量拿到群显示名（用于目录命名）
    if not display_name:
        with contextlib.suppress(Exception):
            sess = _get("/api/v1/sessions", {"keyword": "", "limit": 200})
            for s in sess.get("sessions", []):
                if s.get("username") == chatroom_id:
                    display_name = s.get("displayName", "")
                    break

    group_dir = _resolve_group_dir(chatroom_id, display_name)
    lock_path = os.path.join(group_dir, ".archive.lock")

    with _locked(lock_path):
        members = _refresh_members(chatroom_id, group_dir)
        messages = _fetch_window(chatroom_id, start, end)
        stats = _archive_messages(chatroom_id, display_name, messages, members, group_dir)

        # 更新状态文件
        state_path = os.path.join(group_dir, "_state.json")
        state = _read_json(state_path, {})
        prev_max = state.get("last_local_id")
        new_max = stats["max_local_id"]
        if new_max is not None and (prev_max is None or new_max > prev_max):
            state["last_local_id"] = new_max
        state["chatroomId"] = chatroom_id
        state["displayName"] = display_name or state.get("displayName", "")
        state["last_run_at"] = _ts_to_human(int(time.time()))
        state["last_window"] = {"start": start, "end": end}
        totals = state.get("totals", {})
        totals["appended"] = totals.get("appended", 0) + stats["appended"]
        totals["media_downloaded"] = totals.get("media_downloaded", 0) + stats["media_downloaded"]
        totals["media_reference_only"] = totals.get("media_reference_only", 0) + stats["media_reference_only"]
        state["totals"] = totals
        _write_json(state_path, state)

    result = {"chatroomId": chatroom_id, "displayName": display_name,
              "folder": os.path.basename(group_dir), "window": {"start": start, "end": end}}
    result.update(stats)
    return result


# ----------------------------- 原有查询工具（保留） -----------------------------


@mcp.tool()
def search_sessions(keyword: str = "", limit: int = 20) -> dict:
    """搜索微信会话（私聊 + 群聊）。

    参数:
        keyword: 显示名或 username 关键词，留空返回最近会话
        limit:   返回条数上限

    返回的 sessions 列表中，每条包含 username/displayName/type(1私聊,2群聊)/
    lastTimestamp/unreadCount。用户报了群名时可先用本工具反查 chatroomId。
    """
    return _get("/api/v1/sessions", {"keyword": keyword, "limit": limit})


@mcp.tool()
def find_chatroom_id_by_name(name: str) -> str:
    """根据群名找 chatroomId。返回单个 ID，或多候选时返回所有候选让你确认。"""
    data = _get("/api/v1/sessions", {"keyword": name, "limit": 20})
    groups = [s for s in data.get("sessions", []) if _is_group(s)]
    if not groups:
        return f"找不到名为「{name}」的群聊；请先确认 WeFlow 里能看到这个群。"
    if len(groups) == 1:
        return groups[0]["username"]
    lines = [f"- {s['displayName']}: {s['username']}" for s in groups]
    return "找到多个候选群聊，请告诉我具体要哪一个：\n" + "\n".join(lines)


@mcp.tool()
def get_group_members(chatroom_id: str, include_message_counts: bool = False) -> dict:
    """获取群成员列表，含 wxid -> 显示名映射。

    把消息里的 senderUsername(wxid) 翻译成可读人名时先调本工具。
    """
    params: dict[str, Any] = {"chatroomId": chatroom_id}
    if include_message_counts:
        params["includeMessageCounts"] = 1
    return _get("/api/v1/group-members", params)


@mcp.tool()
def get_messages(chatroom_id: str, start_date: str = "", end_date: str = "",
                 limit: int = 1000, keyword: str = "") -> dict:
    """拉取一段时间窗口内的消息（只读，不归档）。

    参数:
        chatroom_id: 群 ID 或私聊对方 wxid
        start_date:  YYYYMMDD，可省略
        end_date:    YYYYMMDD（会自动扩展到当天 23:59:59）
        limit:       最大 10000，默认 1000
        keyword:     按显示文本过滤
    """
    params: dict[str, Any] = {"talker": chatroom_id, "limit": limit}
    if start_date:
        params["start"] = start_date
    if end_date:
        params["end"] = end_date
    if keyword:
        params["keyword"] = keyword
    return _get("/api/v1/messages", params)


@mcp.tool()
def health() -> dict:
    """检查 WeFlow 服务是否在线。无需 token。"""
    r = requests.get(f"{WEFLOW_BASE}/health", timeout=10)
    return r.json()


@mcp.tool()
def list_all_groups(keyword: str = "", limit: int = 500) -> dict:
    """列出所有群聊的「群名 + chatroomId」，便于挑选要归档的群。

    参数:
        keyword: 可选，按群名/username 过滤；留空返回全部群聊
        limit:   拉取会话上限（默认 500，足够覆盖大多数情况）

    返回:
        {"count": N, "groups": [{"displayName": 群名, "chatroomId": xxx@chatroom,
          "lastTimestamp": ..., "lastActive": "可读时间"}, ...]}

    用法：先调本工具拿到各群的 chatroomId，再把要长期归档的群 ID
    填进环境变量 WEFLOW_ARCHIVE_GROUPS（逗号分隔）。
    """
    data = _get("/api/v1/sessions", {"keyword": keyword, "limit": limit})
    groups = []
    for s in data.get("sessions", []):
        if not _is_group(s):  # 只要群聊
            continue
        ts = s.get("lastTimestamp")
        groups.append({
            "displayName": s.get("displayName", ""),
            "chatroomId": s.get("username", ""),
            "lastTimestamp": ts,
            "lastActive": _ts_to_human(int(ts)) if ts else "",
            "unreadCount": s.get("unreadCount"),
        })
    # 按最近活跃排序，方便挑选
    groups.sort(key=lambda g: g.get("lastTimestamp") or 0, reverse=True)
    return {"count": len(groups), "groups": groups}


# ----------------------------- 新增归档工具 -----------------------------


@mcp.tool()
def archive_group_for_date(chatroom_id: str, date: str, display_name: str = "") -> dict:
    """归档某个群「某一天」的聊天记录（可用于补抓历史某天）。

    参数:
        chatroom_id: 群 ID（xxx@chatroom）
        date:        YYYYMMDD，例如 '20260607'
        display_name: 可选，群显示名（用于目录命名，留空会自动查）

    行为：分群存储、按消息类型分子目录、按自然日切片、保留时间戳、
    自动去重（重复运行同一天不会重复写入）。语音默认不归档。
    返回本次归档的统计。
    """
    return _do_archive(chatroom_id, date, date, display_name)


@mcp.tool()
def archive_group_incremental(chatroom_id: str, lookback_days: int = 0,
                              display_name: str = "") -> dict:
    """增量归档某个群最近若干天的记录（推荐给定时任务用）。

    参数:
        chatroom_id:   群 ID
        lookback_days: 回看天数（含当天）。0 表示用默认值（环境变量
                       WEFLOW_LOOKBACK_DAYS，默认 2，兜住迟到/补发消息）
        display_name:  可选群显示名

    只追加新消息（按 localId 去重），不会重头整理已归档内容。
    """
    days = lookback_days if lookback_days and lookback_days > 0 else LOOKBACK_DAYS
    end = dt.date.today()
    start = end - dt.timedelta(days=max(0, days - 1))
    return _do_archive(
        chatroom_id, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), display_name
    )


@mcp.tool()
def archive_group_yesterday(chatroom_id: str, display_name: str = "") -> dict:
    """归档某个群「昨日」的全部记录（日报场景一键工具）。"""
    y = (dt.date.today() - dt.timedelta(days=1)).strftime("%Y%m%d")
    return _do_archive(chatroom_id, y, y, display_name)


@mcp.tool()
def archive_all_configured_groups(lookback_days: int = 0) -> dict:
    """对环境变量 WEFLOW_ARCHIVE_GROUPS 里配置的所有群做增量归档。

    WEFLOW_ARCHIVE_GROUPS 是逗号分隔的 chatroomId 列表。
    这是「定时任务」最常调用的入口：一次把所有要跟踪的群都增量归档。
    """
    raw = os.environ.get("WEFLOW_ARCHIVE_GROUPS", "").strip()
    if not raw:
        return {"error": "未配置 WEFLOW_ARCHIVE_GROUPS（逗号分隔的 chatroomId）"}
    groups = [g.strip() for g in raw.split(",") if g.strip()]
    days = lookback_days if lookback_days and lookback_days > 0 else LOOKBACK_DAYS
    end = dt.date.today()
    start = end - dt.timedelta(days=max(0, days - 1))
    results = []
    for gid in groups:
        try:
            results.append(_do_archive(gid, start.strftime("%Y%m%d"), end.strftime("%Y%m%d")))
        except Exception as e:
            results.append({"chatroomId": gid, "error": str(e)[:300]})
    return {"count": len(results), "results": results}


@mcp.tool()
def get_archive_status(chatroom_id: str = "") -> dict:
    """查看归档状态。

    不传 chatroom_id：返回归档根目录下所有已归档群的概览（来自 _index.json）。
    传 chatroom_id：返回该群的 _state.json（最后归档时间、累计条数等）。
    """
    if not chatroom_id:
        index = _read_json(_index_path(), {})
        return {"archiveRoot": ARCHIVE_ROOT, "groups": index}
    index = _read_json(_index_path(), {})
    entry = index.get(chatroom_id)
    if not entry:
        return {"error": f"{chatroom_id} 尚未归档过"}
    state_path = os.path.join(ARCHIVE_ROOT, entry["folder"], "_state.json")
    return _read_json(state_path, {"error": "无状态文件"})


@mcp.tool()
def read_archived_day(chatroom_id: str, date: str, limit: int = 500) -> dict:
    """读回某个群某天已归档的文字日志（供日后查询）。

    参数:
        chatroom_id: 群 ID
        date:        YYYY-MM-DD（注意是带横线的归档日期格式）
        limit:       最多返回多少条
    """
    index = _read_json(_index_path(), {})
    entry = index.get(chatroom_id)
    if not entry:
        return {"error": f"{chatroom_id} 尚未归档过"}
    day_file = os.path.join(ARCHIVE_ROOT, entry["folder"], "text", f"{date}.jsonl")
    if not os.path.exists(day_file):
        return {"error": f"没有 {date} 的归档", "file": day_file}
    records = []
    with open(day_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            with contextlib.suppress(json.JSONDecodeError):
                records.append(json.loads(line))
            if len(records) >= limit:
                break
    return {"chatroomId": chatroom_id, "date": date,
            "count": len(records), "messages": records}


if __name__ == "__main__":
    mcp.run()  # stdio