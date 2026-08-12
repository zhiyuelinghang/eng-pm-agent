from src.session.store import store
from src.schemas.envelope import ok, err, needs_input
from src.validation.message_validator import validate_news_articles
from src.engine.webhook_sender import send_news as engine_send_news

def send_news(session_id: str, articles: list):
    session = store.get_or_create(session_id)

    # 校验
    issues = validate_news_articles(articles)
    if issues:
        # 生成修正建议：返回 needs_input 让 Agent 重新组织
        return needs_input(
            session_id, session.state,
            message="图文消息校验不通过：" + "; ".join(issues),
            options={
                "articles": {
                    "type": "free_text",
                    "candidates": []  # 无法自动修正，引导用户修改
                }
            },
            needs=["articles"]
        )

    success, resp = engine_send_news(articles)

    session.record_send(success, error_msg=resp.get("errmsg") if not success else None)

    if success:
        return ok(session_id, session.state,
                  data={"msgtype": "news", "article_count": len(articles), "result": resp},
                  message=f"{len(articles)} 条图文消息已发送至群聊")
    else:
        return err(session_id, session.state,
                   code="SEND_FAILED",
                   message=resp.get("errmsg", str(resp)),
                   recoverable=True,
                   suggestion="请检查图文内容格式或网络连接")
