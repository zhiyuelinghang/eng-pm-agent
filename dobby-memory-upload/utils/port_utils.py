"""
Port utility — safely kill processes occupying a target port.

Used by app.py at startup to auto-recover from stale processes that
didn't release the port after a previous crash or force-kill.

Cross-platform: Windows (netstat + taskkill) and Unix (lsof + kill).
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys


def _is_windows() -> bool:
    """Return True if running on Windows."""
    return sys.platform == "win32"


def _is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a port is already bound by attempting a TCP connect.

    Uses socket.connect_ex() which returns 0 if the connection succeeded
    (port is listening), non-zero otherwise. Non-destructive — does not
    affect the listening process.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        result = sock.connect_ex((host, port))
        return result == 0
    except OSError:
        return False
    finally:
        sock.close()


def _get_pid_on_port(port: int) -> int | None:
    """Find the PID of the process listening on the given port.

    Returns None if no process found or the lookup tool is unavailable.
    """
    if _is_windows():
        try:
            # netstat -ano | findstr :<port>
            output = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True, timeout=5,
            )
            for line in output.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.strip().split()
                    pid_str = parts[-1]
                    if pid_str.isdigit():
                        return int(pid_str)
        except Exception:
            pass
    else:
        try:
            # lsof -ti :<port>
            output = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True, timeout=5,
            )
            pid_str = output.stdout.strip()
            if pid_str and pid_str.isdigit():
                return int(pid_str)
        except Exception:
            pass
    return None


def kill_process_on_port(port: int, host: str = "127.0.0.1") -> bool:
    """Kill the process occupying the target port, if any.

    Returns True if the port is now free (was always free, or kill succeeded).
    Returns False if kill was attempted but failed.

    This is safe to call unconditionally at startup — it is a no-op
    when the port is already free.
    """
    if not _is_port_in_use(port, host):
        return True  # already free, nothing to do

    pid = _get_pid_on_port(port)
    if pid is None:
        print(f"⚠️  Port {port} is occupied but could not identify the process.")
        return False

    print(f"⚠️  Port {port} occupied by PID {pid}. Killing stale process...")
    try:
        if _is_windows():
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True, timeout=10,
            )
        else:
            # SIGKILL (9) is the standard Unix kill signal.
            # Fall back to SIGTERM on platforms where SIGKILL is unavailable.
            sig = getattr(signal, "SIGKILL", signal.SIGTERM)
            os.kill(pid, sig)
        print(f"  ✅ Killed PID {pid}. Port {port} released.")
        return True
    except Exception as e:
        print(f"  ❌ Failed to kill PID {pid}: {e}")
        return False
