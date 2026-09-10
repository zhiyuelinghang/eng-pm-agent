"""System-owned execution supervision, independent of agent configuration.

Only bounded fingerprints and counters are persisted in middle_context. No
second model judges progress, and permission waits do not consume active time.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
from time import monotonic


@dataclass(frozen=True)
class ExecutionPolicy:
    """Emergency ceilings, not the normal completion criterion."""

    max_rounds: int = 200
    max_output_tokens: int = 1_000_000
    max_active_seconds: float = 3600
    warn_repeated_rounds: int = 3
    stop_repeated_rounds: int = 6
    stop_failed_rounds: int = 6
    max_continuations: int = 4


class ExecutionGuard:
    KEY = "managed_execution_v1"

    def __init__(self, policy: ExecutionPolicy, state) -> None:
        self.policy = policy
        self.agent_state = state
        self._tick = None

    @property
    def data(self) -> dict:
        value = self.agent_state.middle_context.get(self.KEY)
        if not value or value.get("reply_id") != self.agent_state.reply_id:
            value = {
                "reply_id": self.agent_state.reply_id,
                "elapsed": 0.0, "output_tokens": 0, "history": [],
                "repeated": 0, "failed": 0, "empty": 0,
                "finalizing": False, "reason": None,
                "continuations": 0, "last_truncated": False,
                "truncated_tools": False, "partial_output": [],
            }
            self.agent_state.middle_context[self.KEY] = value
        return value

    def resume(self) -> None:
        self._tick = monotonic()
        _ = self.data

    def checkpoint(self) -> None:
        now = monotonic()
        if self._tick is not None:
            self.data["elapsed"] += max(0, now - self._tick)
            self._tick = now

    def park(self) -> None:
        self.checkpoint()
        self._tick = None

    def record_round(self, calls, results, tasks) -> None:
        data = self.data
        if not calls:
            data["empty"] += 1
            return
        if len(results) != len(calls):
            return  # Awaiting confirmation or an external result.
        data["empty"] = 0
        outputs = {item.id: item for item in results}
        entries = []
        for call in calls:
            result = outputs.get(call.id)
            if result is None:
                return
            try:
                arguments = json.loads(call.input)
            except (ValueError, TypeError):
                arguments = call.input
            output = result.output
            if isinstance(output, list):
                output = [item.model_dump(exclude={"id"}, mode="json") for item in output]
            entries.append([call.name, arguments, result.state, output])
        # Identifiers and timestamps of message envelopes are deliberately absent.
        digest = sha256(json.dumps(
            [entries, tasks], sort_keys=True, ensure_ascii=False, default=str,
        ).encode("utf-8")).hexdigest()
        data["repeated"] = data["repeated"] + 1 if digest in data["history"] else 0
        data["history"] = (data["history"] + [digest])[-12:]
        failed = all(item.state in ("error", "denied") for item in results)
        data["failed"] = data["failed"] + 1 if failed else 0

    def warning(self) -> str | None:
        data = self.data
        if max(data["repeated"], data["failed"], data["empty"]) == self.policy.warn_repeated_rounds:
            return (
                "连续多轮未取得有效进展。请检查已有结果并调整方法；"
                "不要重复相同操作或重放已经成功的写入。缺少条件时明确说明。"
            )
        return None

    def stop_reason(self) -> str | None:
        self.checkpoint()
        data, policy = self.data, self.policy
        if data["reason"]:
            return data["reason"]
        reason = None
        if data["continuations"] > policy.max_continuations:
            reason = "内容多次达到模型输出上限，已保留当前结果。"
        elif data["failed"] >= policy.stop_failed_rounds:
            reason = "工具连续执行失败，当前任务尚未完成。"
        elif max(data["repeated"], data["empty"]) >= policy.stop_repeated_rounds:
            reason = "连续多轮未取得新结果，已停止重复处理。"
        elif self.agent_state.cur_iter >= policy.max_rounds:
            reason = "本阶段处理量较大，已保留当前进度。"
        elif data["output_tokens"] >= policy.max_output_tokens:
            reason = "本阶段已达到系统处理额度，已保留当前进度。"
        elif data["elapsed"] >= policy.max_active_seconds:
            reason = "本阶段运行时间较长，已保留当前进度。"
        data["reason"] = reason
        return reason
