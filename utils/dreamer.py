"""DreamerScheduler + DreamerTask(ABC) — 参考 Magic Context task-scheduler"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import config as _cfg


@dataclass
class DreamerResult:
    """单个 Task 的执行结果"""
    task_name: str = ""
    skipped: bool = False
    reason: str = ""
    # verify
    verified: int = 0
    updated: int = 0
    # curate
    archived: int = 0
    merged: int = 0
    tightened: int = 0
    # classify
    classified: int = 0
    # decay
    pruned: int = 0
    consolidated: int = 0
    # generic
    error: str = ""
    duration_seconds: float = 0.0


@dataclass
class DreamerTaskConfig:
    """单个维护任务的 cron 配置 — 参考 Magic Context task-config.ts"""
    name: str
    cron: str = ""             # "0 3 * * *" 或 "" 禁用
    timeout_seconds: int = 1200
    model: str | None = None   # None=使用 DREAMER_DEFAULT_MODEL
    enabled: bool = True


class DreamerTask(ABC):
    """维护任务基类 — 参考 Magic Context dreamer.ts"""

    def __init__(self, config: DreamerTaskConfig):
        self.config = config

    @abstractmethod
    async def run(self, project_id: str) -> DreamerResult:
        """执行维护逻辑。子类实现。"""
        ...

    def _get_db_conn(self):
        """复用 lifecycle.py:152-158 的 psycopg 连接模式"""
        import psycopg
        return psycopg.Connection.connect(
            _cfg.DATABASE_URL,
            autocommit=True,
            prepare_threshold=0,
        )

    def _cron_matches(self, now: datetime) -> bool:
        """简易 cron 检查：当前时间是否匹配 cron 表达式"""
        if not self.config.cron or not self.config.enabled:
            return False
        parts = self.config.cron.strip().split()
        if len(parts) != 5:
            return False
        minute, hour, dom, month, dow = parts
        return (
            self._match_field(minute, now.minute) and
            self._match_field(hour, now.hour) and
            self._match_field(dom, now.day) and
            self._match_field(month, now.month) and
            self._match_field(dow, (now.weekday() + 1) % 7)  # cron: 0=Sun, Python: 0=Mon
        )

    @staticmethod
    def _match_field(pattern: str, value: int) -> bool:
        if pattern == "*":
            return True
        if "," in pattern:
            return any(DreamerTask._match_field(p.strip(), value) for p in pattern.split(","))
        if "/" in pattern:
            base, step = pattern.split("/")
            step = int(step)
            base_val = 0 if base == "*" else int(base)
            return value >= base_val and (value - base_val) % step == 0
        if "-" in pattern:
            lo, hi = pattern.split("-")
            return int(lo) <= value <= int(hi)
        return int(pattern) == value


# ============================================================
# DreamerScheduler — 任务调度器
# ============================================================

class DreamerScheduler:
    """任务调度器 — 参考 Magic Context task-scheduler.ts

    管理所有 Task 的 cron 调度、PG advisory lock、熔断器。
    """

    def __init__(self, project_id: str):
        self.project_id = project_id
        self._circuit_state: dict[str, int] = {}  # task_name → failures
        self._tasks: dict[str, DreamerTask] = {}
        self._init_tasks()

    def _init_tasks(self):
        """从 DREAMER_TASK_REGISTRY 实例化所有 Task"""
        from .dreamer_tasks import DREAMER_TASK_REGISTRY

        configs = {
            "decay": DreamerTaskConfig(
                name="decay", cron=_cfg.DREAMER_DECAY_CRON,
                timeout_seconds=_cfg.DREAMER_DEFAULT_TIMEOUT,
                model=_cfg.DREAMER_DEFAULT_MODEL,
                enabled=_cfg.DREAMER_ENABLED,
            ),
            "verify": DreamerTaskConfig(
                name="verify", cron=_cfg.DREAMER_VERIFY_CRON,
                timeout_seconds=_cfg.DREAMER_DEFAULT_TIMEOUT,
                model=_cfg.DREAMER_DEFAULT_MODEL,
                enabled=_cfg.DREAMER_ENABLED,
            ),
            "curate": DreamerTaskConfig(
                name="curate", cron=_cfg.DREAMER_CURATE_CRON,
                timeout_seconds=_cfg.DREAMER_DEFAULT_TIMEOUT * 2,  # curate 可以更久
                model=_cfg.DREAMER_DEFAULT_MODEL,
                enabled=_cfg.DREAMER_ENABLED,
            ),
            "classify": DreamerTaskConfig(
                name="classify", cron=_cfg.DREAMER_CLASSIFY_CRON,
                timeout_seconds=_cfg.DREAMER_DEFAULT_TIMEOUT,
                model=_cfg.DREAMER_DEFAULT_MODEL,
                enabled=_cfg.DREAMER_ENABLED,
            ),
        }

        for name, task_cls in DREAMER_TASK_REGISTRY.items():
            cfg = configs.get(name)
            if cfg and cfg.enabled:
                self._tasks[name] = task_cls(cfg)

    async def run_due_tasks(self) -> dict[str, DreamerResult]:
        """运行所有 cron 到期的 Task"""
        now = datetime.now(timezone.utc)
        results: dict[str, DreamerResult] = {}

        for name, task in self._tasks.items():
            if not task.config.enabled:
                continue
            if not task._cron_matches(now):
                continue
            if self._circuit_state.get(name, 0) >= _cfg.DREAMER_CIRCUIT_BREAKER_MAX_FAILURES:
                results[name] = DreamerResult(
                    task_name=name, skipped=True,
                    reason=f"circuit_breaker:{self._circuit_state[name]}",
                )
                continue

            result = await task.run(self.project_id)
            results[name] = result

            if result.error:
                self._circuit_state[name] = self._circuit_state.get(name, 0) + 1
            else:
                self._circuit_state[name] = 0

        return results

    async def run_task(self, task_name: str) -> DreamerResult:
        """手动运行单个 Task，绕过 cron 和熔断器"""
        task = self._tasks.get(task_name)
        if task is None:
            return DreamerResult(task_name=task_name, skipped=True,
                                 reason=f"unknown_task:{task_name}")
        self._circuit_state[task_name] = 0  # 手动重置熔断器
        return await task.run(self.project_id)
