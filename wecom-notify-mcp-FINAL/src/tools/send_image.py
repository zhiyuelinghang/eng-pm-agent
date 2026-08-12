import os
from src.session.store import store
from src.schemas.envelope import ok, err
from src.engine.webhook_sender import send_image as engine_send_image

MAX_IMAGE_SIZE_MB = 2

def send_image(session_id: str, image_source: str):
    """
    image_source 可以是本地文件路径，或者 base64 字符串
    """
    session = store.get_or_create(session_id)

    # 校验：如果是文件路径，检查文件是否存在和大小
    if not image_source.startswith("data:image"):
        if not os.path.isfile(image_source):
            return err(session_id, session.state,
                       code="INVALID_INPUT",
                       message=f"文件不存在: {image_source}",
                       recoverable=True,
                       suggestion="请提供正确的图片文件路径")
        size_mb = os.path.getsize(image_source) / (1024 * 1024)
        if size_mb > MAX_IMAGE_SIZE_MB:
            return err(session_id, session.state,
                       code="RESOURCE_LIMIT",
                       message=f"图片大小 {size_mb:.1f}MB 超过 {MAX_IMAGE_SIZE_MB}MB 限制",
                       recoverable=True,
                       suggestion="请压缩图片或使用更小的文件")

    # 发送
    success, resp = engine_send_image(image_source)

    session.record_send(success, error_msg=resp.get("errmsg") if not success else None)

    if success:
        return ok(session_id, session.state,
                  data={"msgtype": "image", "result": resp},
                  message="图片已发送至群聊")
    else:
        return err(session_id, session.state,
                   code="SEND_FAILED",
                   message=resp.get("errmsg", str(resp)),
                   recoverable=True,
                   suggestion="请检查 Webhook 地址、图片大小或格式")
