from datetime import datetime
import uuid

class Session:
    def __init__(self):
        self.session_id = f"wecom_{uuid.uuid4().hex[:8]}"
        self.state = "ACTIVE"  # 固定状态
        self.created_at = datetime.utcnow()
        self.send_count = 0
        self.last_error = None

    def record_send(self, success: bool, error_msg: str = None):
        self.send_count += 1
        if not success:
            self.last_error = error_msg

class SessionStore:
    def __init__(self):
        self._sessions = {}

    def get_or_create(self, session_id: str = "default") -> Session:
        if session_id not in self._sessions:
            self._sessions[session_id] = Session()
        return self._sessions[session_id]

store = SessionStore()
