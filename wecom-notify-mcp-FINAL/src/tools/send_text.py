from src.session.store import store
from src.schemas.envelope import ok, err
from src.validation.message_validator import validate_text_content
from src.engine.webhook_sender import send_text as engine_send_text

def send_text(session_id: str, content: str, mentioned_list: list = None, mentioned_mobile_list: list = None):
    session = store.get_or_create(session_id)

    # 校验
    issues = validate_text_content(content)
    if issues:
        return err(session_id, session.state, code="INVALID_INPUT",
                   message="; ".join(issues), recoverable=True,
                   suggestion="请修正消息内容后重试")

    # 发送
    success, resp = engine_send_text(content, mentioned_list, mentioned_mobile_list)

    # 记录
    session.record_send(success, error_msg=resp.get("errmsg") if not success else None)

    if success:
        return ok(session_id, session.state,
                  data={"msgtype": "text", "result": resp},
                  message="消息已发送至群聊")
    else:
        return err(session_id, session.state,
                   code="SEND_FAILED", message=resp.get("errmsg", str(resp)),
                   recoverable=True, suggestion="请检查 Webhook 地址或网络连接")
