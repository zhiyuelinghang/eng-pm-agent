"""Reliable Windows hot-reload runner for the local AgentScope service."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

from watchfiles import Change, watch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_HOME = PROJECT_ROOT / "scripts"
AGENTSCOPE_CORE_HOME = PROJECT_ROOT / "AgentScope" / "agentscope"
MEMORY_HOME = PROJECT_ROOT / "utils"
WATCH_PATHS = (SCRIPTS_HOME, AGENTSCOPE_CORE_HOME, MEMORY_HOME)
THIS_FILE = Path(__file__).resolve()
HOST = os.getenv("AGENTSCOPE_HOST", "127.0.0.1")
PORT = int(os.getenv("AGENTSCOPE_PORT", "18642"))


def _is_app_python(change: Change, path: str) -> bool:
    """Watch application Python files, excluding this supervisor itself."""
    del change
    file_path = Path(path).resolve()
    return file_path.suffix == ".py" and file_path != THIS_FILE


def _command() -> list[str]:
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "scripts.agentscope_dev_app:app",
        "--app-dir",
        str(PROJECT_ROOT),
        "--host",
        HOST,
        "--port",
        str(PORT),
    ]


def _port_in_use() -> bool:
    """Return whether another process is listening on the API port."""
    probe_host = "127.0.0.1" if HOST in {"0.0.0.0", "::"} else HOST
    try:
        with socket.create_connection((probe_host, PORT), timeout=0.5):
            return True
    except OSError:
        return False


def _start_worker() -> subprocess.Popen[bytes]:
    creation_flags = (
        subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    )
    process = subprocess.Popen(
        _command(),
        cwd=PROJECT_ROOT,
        creationflags=creation_flags,
    )
    print(f"[AgentScope] Worker 已启动，PID={process.pid}", flush=True)
    return process


def _stop_worker(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> None:
    """Run Uvicorn and restart it whenever local Python source changes."""
    if _port_in_use():
        raise SystemExit(
            f"[AgentScope] 端口 {HOST}:{PORT} 已被占用，停止启动。",
        )

    print(
        "[AgentScope] 热重载监控目录："
        + "、".join(str(path) for path in WATCH_PATHS),
        flush=True,
    )
    worker = _start_worker()
    try:
        for changes in watch(
            *WATCH_PATHS,
            watch_filter=_is_app_python,
            debounce=300,
            step=100,
            rust_timeout=1000,
            yield_on_timeout=True,
        ):
            if changes:
                changed = ", ".join(
                    sorted(Path(path).name for _, path in changes),
                )
                print(
                    f"[AgentScope] 检测到源码变化：{changed}，正在重启……",
                    flush=True,
                )
                _stop_worker(worker)
                worker = _start_worker()
            elif worker.poll() is not None:
                if _port_in_use():
                    print(
                        f"[AgentScope] 端口 {HOST}:{PORT} 已被其他进程占用，"
                        "停止自动重试。",
                        flush=True,
                    )
                    return
                print(
                    f"[AgentScope] Worker 已退出（{worker.returncode}），"
                    "监督进程同步结束。",
                    flush=True,
                )
                return
    except KeyboardInterrupt:
        print("\n[AgentScope] 正在停止开发服务……", flush=True)
    finally:
        _stop_worker(worker)


if __name__ == "__main__":
    main()
