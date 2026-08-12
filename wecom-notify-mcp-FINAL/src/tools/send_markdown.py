from src.session.store import store
from src.schemas.envelope import ok, err
from src.validation.message_validator import validate_markdown_content
from src.engine.webhook_sender import send_markdown as engine_send_markdown

def send_markdown(session_id: str, content: str):
    session = store.get_or_create(session_id)

    issues = validate_markdown_content(content)
    if issues:
        return err(session_id, session.state, code="INVALID_INPUT",
                   message="; ".join(issues), recoverable=True,
                   suggestion="请修正 Markdown 内容后重试")

    success, resp = engine_send_markdown(content)

    session.record_send(success, error_msg=resp.get("errmsg") if not success else None)

    if success:
        return ok(session_id, session.state,
                  data={"msgtype": "markdown", "result": resp},
                  message="Markdown 消息已发送至群聊")
    else:
        return err(session_id, session.state,
                   code="SEND_FAILED", message=resp.get("errmsg", str(resp)),
                   recoverable=True, suggestion="请检查 Webhook 地址或网络连接")
