"""Validate only the images explicitly supplied for the current agent turn."""
from __future__ import annotations

import base64
import binascii
from io import BytesIO
from pathlib import Path
import warnings

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError


MAX_IMAGE_COUNT = 8
MAX_IMAGE_BYTES = 30 * 1024 * 1024
NATIVE_IMAGE_TYPES = {'PNG':'image/png', 'JPEG':'image/jpeg', 'WEBP':'image/webp', 'GIF':'image/gif'}
NATIVE_IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}


def _verified_media_type(content: bytes, declared: str | None = None) -> str:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                media_type = NATIVE_IMAGE_TYPES.get(image.format)
                if media_type is None or declared is not None and media_type != declared:
                    raise HTTPException(422, '图片格式与声明不一致；仅支持 PNG、JPEG、WEBP、GIF 原图。')
                image.verify()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(422, '图片内容无效或像素尺寸过大，请重新选择有效图片。') from exc
    return media_type


def image_blocks_for_turn(images, initialization_files, *, upload_dir: Path):
    """Initialization rows must already have passed project/conversation authorization."""
    blocks = []
    file_ids = set()
    total = 0

    def append(name, content, declared=None):
        nonlocal total
        total += len(content)
        if len(blocks) >= MAX_IMAGE_COUNT or total > MAX_IMAGE_BYTES:
            raise HTTPException(413, '每次最多发送 8 张图片，图片总大小不能超过 30MB。')
        media_type = _verified_media_type(content, declared)
        blocks.append({'type':'data', 'name':name, 'source':{'type':'base64',
            'media_type':media_type, 'data':base64.b64encode(content).decode('ascii')}})

    for image in images:
        try:
            content = base64.b64decode(image.data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(422, '图片必须是有效的 Base64 内容。') from exc
        append(image.name, content, image.media_type)

    for file in initialization_files:
        if Path(file.file_name).suffix.lower() not in NATIVE_IMAGE_SUFFIXES:
            continue
        root = (upload_dir / 'project-initialization' / str(file.project_id) / str(file.conversation_id)).resolve()
        try:
            path = Path(file.storage_path).resolve(strict=True)
            if not path.is_relative_to(root) or not path.is_file():
                raise HTTPException(403, '初始化图片不在当前会话的附件目录中。')
            with path.open('rb') as source:
                content = source.read(MAX_IMAGE_BYTES + 1)
        except (FileNotFoundError, OSError) as exc:
            raise HTTPException(409, '初始化图片原文件无法读取，请重新上传。') from exc
        append(file.file_name, content)
        file_ids.add(file.id)
    return blocks, file_ids


def image_attachment_refs(blocks):
    return [{'name':block['name'], 'media_type':block['source']['media_type']} for block in blocks]
