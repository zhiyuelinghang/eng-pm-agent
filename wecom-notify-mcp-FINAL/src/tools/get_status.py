from src.session.store import store
from src.schemas.envelope import ok

def get_status(session_id: str):
    session = store.get_or_create(session_id)
    data = {
        "state": session.state,
        "send_count": session.send_count,
        "last_error": session.last_error
    }
    return ok(session_id, session.state, data=data, message="当前机器人为活跃状态")
