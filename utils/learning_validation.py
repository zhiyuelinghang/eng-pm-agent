"""Deterministic publication gate; semantic value is decided in the single learning call."""
from datetime import datetime, timezone
from .memory_repository import MemoryError


def automatic_validation(kind, detail):
    evidence = detail.get('evidence') or []
    ids = set(detail.get('evidence_ids') or [])
    cited = [e for e in evidence if e.get('id') in ids]
    if not ids or ids != {e.get('id') for e in cited}:
        raise MemoryError('invented_evidence', '学习成果没有完整可追溯的引用证据。')
    if not any(e.get('kind') in {'user', 'tool', 'task', 'memory', 'feedback'} and
               e.get('outcome') not in {'assistant_claim', 'error', 'failure'} and str(e.get('text', '')).strip() for e in cited):
        raise MemoryError('insufficient_evidence', '缺少用户、实际结果或有效来源支持，不能仅凭助手自评或失败记录启用。')
    if not str(detail.get('conditions', '')).strip() or not str(detail.get('limitations', '')).strip():
        raise MemoryError('learning_detail_required', '缺少适用条件或限制。')
    steps = detail.get('steps') or []
    if kind == 'skill' and not steps or len(steps) > 10 or any(not isinstance(s,str) or not s.strip() or len(s)>2000 for s in steps):
        raise MemoryError('invalid_skill', '操作技能需要明确、有界的步骤。')
    return {**detail, 'validation_state': 'verified', 'validation_method': 'automatic_v1',
            'reviewed_by': 'system', 'reviewed_at': datetime.now(timezone.utc).isoformat(),
            'review_note': '系统已检查来源、引用、适用范围和结果证据；自动生效，不代表人工验收。'}
