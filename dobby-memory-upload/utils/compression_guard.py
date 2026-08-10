"""
Compression quality guard — prevents death-spiral from repeated poor compressions.

参考: Agentica death-spiral guards (circuit breaker + iterative summary + anchor check).
Magic Context: 85% force-materialize, 95% emergency fail-closed.

五层防护:
  1. 多维度质量评分 — 六信号加权平均（信息密度、长度分布、幻影检测、结构完整性、事实引用密度、语义连贯性）
  2. 会话级故障计数 — 计数器存入 DobbyState，经 PostgresSaver 持久化，会话间隔离
  3. 任务锚点验证 — 压缩后验证活跃 task_id、决策、偏好是否保留在新摘要中
  4. L2 进程级告警 — 跨会话全局 reset 计数器，超阈值写 WARNING 日志
  5. 迭代摘要 — 压缩 prompt 支持增量更新模式（在 compression.py 中实现）

三道防线（会话级）:
  ① 连续压缩上限: ≥3次 → reset（清除摘要，重新开始）
  ② 质量下滑检测: 近2次压缩后质量 < 0.3 → trim_only（仅截断不压缩）
  ③ 最小间隔: 距上次压缩 < 5轮 → trim_only

三种处置:
  - compress: 正常LLM压缩
  - trim_only: 仅保留最后20条消息，复用旧摘要
  - reset: 清除摘要，仅保留系统提示+最后10条消息
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from . import config as _cfg


@dataclass
class CompressionDecision:
    """Result of compression guard check."""
    action: str       # "compress" | "trim_only" | "reset" | "skip"
    reason: str
    quality_score: float = 0.0


# ============================================================
# Quality data structures
# ============================================================

@dataclass
class QualityScore:
    """Multi-dimensional quality score — six signals weighted average."""
    score: float = 0.0            # 0-1 综合分
    signals: dict = field(default_factory=dict)  # {"information_density": 0.8, ...}
    verdict: str = "good"         # "good" | "suspect" | "bad"
    details: str = ""


@dataclass
class AnchorReport:
    """Task anchor preservation check result."""
    total_anchors: int = 0
    preserved: int = 0
    missing: list = field(default_factory=list)
    score: float = 1.0          # preserved / total
    verdict: str = "all_present" # "all_present" | "partial_loss" | "severe_loss"


# ============================================================
# QualityScorer — six-signal weighted average
# ============================================================

class QualityScorer:
    """Multi-dimensional quality scorer.

    Six signals, each 0-1, final score = Σ(signal_i × weight_i).
    All methods are static — stateless, pure functions.
    """

    _SIGNALS = [
        ("information_density",   0.25),
        ("length_distribution",   0.15),
        ("refusal_detection",     0.25),
        ("structural_integrity",  0.10),
        ("factual_reference",     0.15),
        ("semantic_coherence",    0.10),
    ]

    _REFUSAL_PATTERNS = [
        "抱歉", "无法", "作为AI", "我不能", "我无法", "无法提供",
        "I cannot", "I'm unable", "As an AI",
        r"超出.*能力", r"没有.*信息", r"没有.*数据",
    ]

    @classmethod
    def score_reply(cls, content: str) -> QualityScore:
        """Score an agent reply text.

        Used by supervisor_node after receiving a role response.
        """
        if not content:
            return QualityScore(score=0.0, verdict="bad", details="empty content")

        signals = {}
        for name, _ in cls._SIGNALS:
            try:
                scorer = getattr(cls, f"_score_{name}")
                signals[name] = scorer(content)
            except Exception:
                signals[name] = 0.5  # fallback on error

        weights = {name: w for name, w in cls._SIGNALS}
        score = sum(signals[n] * weights[n] for n in signals)

        if score >= 0.6:
            verdict = "good"
        elif score >= 0.3:
            verdict = "suspect"
        else:
            verdict = "bad"

        details = _build_details(signals)
        return QualityScore(score=round(score, 4), signals=signals, verdict=verdict, details=details)

    @classmethod
    def score_summary(
        cls,
        summary_text: str,
        tasks_before: dict,
        tasks_after: dict,
        decisions: list,
        context_to_preserve: str,
    ) -> QualityScore:
        """Score a compression summary, including anchor verification.

        Anchor loss can cap the final score:
          - severe_loss → max 0.4
          - partial_loss → max 0.7
        """
        # 1. Base six-signal scoring
        base = cls.score_reply(summary_text)

        # 2. Anchor verification
        anchor = verify_anchors(summary_text, tasks_after, decisions, context_to_preserve)

        # 3. Apply anchor penalty
        score = base.score
        if anchor.verdict == "severe_loss":
            score = min(score, 0.4)
        elif anchor.verdict == "partial_loss":
            score = min(score, 0.7)

        signals = dict(base.signals)
        signals["anchor_preservation"] = anchor.score

        if score >= 0.6:
            verdict = "good"
        elif score >= 0.3:
            verdict = "suspect"
        else:
            verdict = "bad"

        details = base.details + f"; anchors={anchor.preserved}/{anchor.total_anchors} ({anchor.verdict})"
        return QualityScore(score=round(score, 4), signals=signals, verdict=verdict, details=details)

    # ── Six signal methods ──

    @staticmethod
    def _tokenize(content: str) -> list[str]:
        """Split text into tokens — handles both space-separated (English) and
        character-level (Chinese) text.

        If whitespace-split produces very few tokens relative to character count,
        falls back to character-level splitting for CJK text.
        """
        words = content.split()
        # Heuristic: if average token length > 4 chars, likely CJK without spaces
        if words and sum(len(w) for w in words) / len(words) > 4:
            return list(content)  # character-level for CJK
        return words

    @staticmethod
    def _score_information_density(content: str) -> float:
        """unique_tokens / total_tokens — detects repetitive filler."""
        tokens = QualityScorer._tokenize(content)
        if not tokens:
            return 0.0
        ratio = len(set(tokens)) / len(tokens)
        return min(ratio * 1.5, 1.0)  # scale up: 0.67 ratio → 1.0

    @staticmethod
    def _score_length_distribution(content: str) -> float:
        """Length within reasonable range — penalizes too-short or too-long."""
        n = len(content)
        if n < 20:
            return 0.05
        if n < 100:
            return 0.4
        if n < 2000:
            return 1.0
        if n < 8000:
            return 0.7
        return 0.3

    @classmethod
    def _score_refusal_detection(cls, content: str) -> float:
        """Detect refusal / limitation patterns — lower = more refusal signals."""
        hits = 0
        for pat in cls._REFUSAL_PATTERNS:
            if re.search(pat, content):
                hits += 1
        if hits == 0:
            return 1.0
        if hits == 1:
            return 0.5
        if hits == 2:
            return 0.3
        return 0.1

    @staticmethod
    def _score_structural_integrity(content: str) -> float:
        """Check paragraph breaks, punctuation, and ending markers."""
        score = 0.5  # start neutral
        # Has paragraph breaks (multiline content with blank lines)?
        if re.search(r'\n\s*\n', content):
            score += 0.2
        # Ends with a sentence-ending character?
        if content.rstrip().endswith(('.', '。', '！', '?', '）', ')', '`')):
            score += 0.15
        # Has at least one punctuation mark?
        if re.search(r'[。，！？、；：""''（）]', content):
            score += 0.15
        return min(score, 1.0)

    @staticmethod
    def _score_factual_reference(content: str) -> float:
        """Detect specific references — standard codes, dates, numbers."""
        score = 0.3  # base: no specific refs
        # Standard codes like GB50300-2013, JGJ59-2011
        if re.search(r'[A-Z]{2,}[\s-]?\d+', content):
            score += 0.4
        # Dates
        if re.search(r'\d{4}[-/]\d{2}[-/]\d{2}', content):
            score += 0.15
        # Multi-digit numbers (quantities, measurements)
        if re.search(r'\d{3,}', content):
            score += 0.15
        return min(score, 1.0)

    @staticmethod
    def _score_semantic_coherence(content: str) -> float:
        """Adjacent sentence word overlap — detects topic jumps."""
        sentences = re.split(r'[。！？\n]+', content)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 5]
        if len(sentences) < 2:
            return 0.7  # single sentence -> neutral

        overlaps = []
        for s1, s2 in zip(sentences, sentences[1:]):
            w1 = set(QualityScorer._tokenize(s1))
            w2 = set(QualityScorer._tokenize(s2))
            if w1 and w2:
                overlap = len(w1 & w2) / min(len(w1), len(w2))
                overlaps.append(overlap)

        if not overlaps:
            return 0.7
        avg_overlap = sum(overlaps) / len(overlaps)
        # 0.15-0.5 is normal for Chinese text; below 0.1 is chaotic
        if avg_overlap < 0.1:
            return 0.2
        if avg_overlap > 0.6:
            return 0.8  # very coherent but may be repetitive
        return 0.5 + avg_overlap * 0.5  # scale to 0.5-1.0 range


def _build_details(signals: dict) -> str:
    """Build human-readable diagnostic string from signals."""
    parts = []
    for name, val in sorted(signals.items()):
        label = {
            "information_density": "密度",
            "length_distribution": "长度",
            "refusal_detection": "幻影",
            "structural_integrity": "结构",
            "factual_reference": "引用",
            "semantic_coherence": "连贯",
        }.get(name, name[:4])
        parts.append(f"{label}={val:.2f}")
    return "; ".join(parts)


# ============================================================
# Anchor verification
# ============================================================

def verify_anchors(
    new_summary: str,
    new_tasks: dict,
    decisions: list,
    context_to_preserve: str,
) -> AnchorReport:
    """Verify that task anchors survived compression.

    Three anchor types:
      1. Active tasks (status != "done") — task_id must appear in summary
      2. Recent decisions (last 3) — first 40 chars must appear in summary
      3. User preferences (context_to_preserve) — first 40 chars must appear

    Pure string-match — no LLM call.
    Does NOT block compression — only affects quality score.
    """
    anchors: list[tuple[str, str, str]] = []  # (type, match_key, human_label)

    # ── Anchor 1: Active tasks ──
    for task_id, info in new_tasks.items():
        if isinstance(info, dict) and info.get("status") != "done":
            anchors.append(("task", task_id, f"任务[{task_id}]"))

    # ── Anchor 2: Recent decisions ──
    for d in (decisions or [])[-3:]:
        key = str(d)[:40]
        if key.strip():
            anchors.append(("decision", key, f"决策「{key}...」"))

    # ── Anchor 3: User preferences ──
    if context_to_preserve:
        pref_key = str(context_to_preserve)[:40]
        if pref_key.strip():
            anchors.append(("preference", pref_key, f"偏好「{pref_key}...」"))

    if not anchors:
        return AnchorReport(total_anchors=0, preserved=0, score=1.0, verdict="all_present")

    preserved = 0
    missing: list[str] = []
    for _atype, key, desc in anchors:
        if key in new_summary:
            preserved += 1
        else:
            missing.append(desc)

    total = len(anchors)
    score = preserved / total
    if score >= 0.8:
        verdict = "all_present"
    elif score >= 0.5:
        verdict = "partial_loss"
    else:
        verdict = "severe_loss"

    return AnchorReport(
        total_anchors=total,
        preserved=preserved,
        missing=missing,
        score=round(score, 4),
        verdict=verdict,
    )


# ============================================================
# CompressionGuard (session-level counters + L2 process alert)
# ============================================================

class CompressionGuard:
    """Compression quality guard with three-line defense + L2 alert.

    Session-level state (_guard_compress_count, _guard_quality_scores)
    is stored in DobbyState (dict), persisted via PostgresSaver.
    L2 process-level counter (_l2_reset_counter) lives in this instance.
    """

    def __init__(
        self,
        max_consecutive: int = 3,
        quality_threshold: float = 0.3,
        min_rounds_between: int = 5,
    ):
        self._max_consecutive = max_consecutive
        self._quality_threshold = quality_threshold
        self._min_rounds_between = min_rounds_between

        # ── L2 process-level state (not session-scoped) ──
        self._l2_reset_counter: int = 0
        self._l2_last_alert_ts: float = 0.0
        self._l2_alert_cooldown: float = 3600.0  # 1 hour

    # ── Public API ──

    def decide(self, messages: list, state: dict) -> CompressionDecision:
        """Check all three lines of defense using session-level state.

        Args:
            messages: current message list (for future content-based checks)
            state: DobbyState dict with _guard_compress_count / _guard_quality_scores
        """
        session_count = state.get("_guard_compress_count", 0)
        session_scores = list(state.get("_guard_quality_scores", []))

        # ── Line 1: Consecutive compression cap ──
        if session_count >= self._max_consecutive:
            return CompressionDecision(
                action="reset",
                reason=f"会话内连续压缩{session_count}次(上限{self._max_consecutive})，建议重置对话",
            )

        # ── Line 2: Quality degradation ──
        if len(session_scores) >= 2:
            recent_avg = sum(session_scores[-2:]) / 2
            if recent_avg < self._quality_threshold:
                return CompressionDecision(
                    action="trim_only",
                    reason=f"近2次压缩后质量={recent_avg:.2f}<{self._quality_threshold}，仅截断不压缩",
                    quality_score=recent_avg,
                )

        # ── Line 3: Minimum interval ──
        last = state.get("last_compress_round", 0)
        current = state.get("message_count", 0)
        if current - last < self._min_rounds_between and last > 0:
            return CompressionDecision(
                action="trim_only",
                reason=f"距上次压缩仅{current - last}轮(最少间隔{self._min_rounds_between})",
            )

        return CompressionDecision(action="compress", reason="通过三道防线检查")

    def record_quality(self, state: dict, score: float) -> dict:
        """Record a quality score into session-level state.

        Returns a dict to merge into DobbyState.
        """
        scores = list(state.get("_guard_quality_scores", []))
        scores.append(score)
        if len(scores) > 5:
            scores = scores[-5:]
        return {"_guard_quality_scores": scores}

    def on_compress(self, state: dict) -> dict:
        """Signal that a compression was performed.

        Returns a dict with incremented counter to merge into DobbyState.
        """
        return {"_guard_compress_count": state.get("_guard_compress_count", 0) + 1}

    def on_reset(self, state: dict) -> dict:
        """Signal that a reset was performed — clears session state, bumps L2 counter.

        Returns a dict with zeroed counters to merge into DobbyState.
        """
        self._l2_reset_counter += 1

        threshold = getattr(_cfg, "COMPRESSION_L2_ALERT_THRESHOLD", 10)
        if self._l2_reset_counter >= threshold:
            self._emit_l2_alert()

        return {"_guard_compress_count": 0, "_guard_quality_scores": []}

    # ── L2 alert ──

    def _emit_l2_alert(self) -> None:
        """Emit L2 process-level alert via logging + audit_logger.

        1-hour cooldown between alerts.
        """
        now = time.monotonic()
        if now - self._l2_last_alert_ts < self._l2_alert_cooldown:
            return
        self._l2_last_alert_ts = now

        threshold = getattr(_cfg, "COMPRESSION_L2_ALERT_THRESHOLD", 10)
        alert_msg = (
            f"[L2 Compression Alert] 进程累计 {self._l2_reset_counter} 次压缩 reset，"
            f"超过阈值 {threshold}。"
            f"可能原因：LLM API 不稳定、压缩 prompt 需要调整、模型幻觉率升高。"
            f"建议：检查 DeepSeek API 状态、审查最近压缩日志。"
        )

        # Channel 1: Python logging
        import logging
        logger = logging.getLogger("dobby.compression")
        logger.warning(alert_msg)

        # Channel 2: audit_logger (async, best-effort)
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_async_log_alert(alert_msg))
        except RuntimeError:
            pass  # not in async context


async def _async_log_alert(alert_msg: str) -> None:
    """Write L2 alert to audit_logger (best-effort)."""
    try:
        from .audit_logger import get_audit_logger
        await get_audit_logger().log_message(
            "system", alert_msg, role="compression_guard",
        )
    except Exception:
        pass
