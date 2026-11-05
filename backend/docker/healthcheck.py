#!/usr/bin/env python
"""Container healthcheck, chosen by the role PID 1 is running.

* gunicorn / uvicorn (api) -> GET http://127.0.0.1:$PORT/health must return 200
* celery worker            -> `celery inspect ping` for this node must answer
* celery beat              -> the beat process is PID 1 and alive (healthy by definition)
* anything else            -> healthy (e.g. the one-shot migrate role)

Exit status 0 = healthy, 1 = unhealthy. Never prints configuration or secrets.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import urllib.request


def _pid1_cmdline() -> list[str]:
    try:
        with open("/proc/1/cmdline", "rb") as fh:
            return [p.decode(errors="replace") for p in fh.read().split(b"\0") if p]
    except OSError:
        return []


def _check_http() -> int:
    port = os.environ.get("PORT", "8000")
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=4) as resp:
            return 0 if resp.status == 200 else 1
    except Exception as exc:  # noqa: BLE001
        print(f"health: {type(exc).__name__}", file=sys.stderr)
        return 1


def _check_worker() -> int:
    node = f"worker@{socket.gethostname()}"
    try:
        proc = subprocess.run(
            ["celery", "-A", "app.celery_app", "inspect", "ping", "-d", node, "--timeout", "5"],
            capture_output=True,
            timeout=25,
            check=False,
            cwd="/app",
        )
    except subprocess.TimeoutExpired:
        return 1
    return 0 if proc.returncode == 0 and b"pong" in proc.stdout else 1


def main() -> int:
    cmd = " ".join(_pid1_cmdline())
    if "gunicorn" in cmd or "uvicorn" in cmd:
        return _check_http()
    if "celery" in cmd and " worker" in cmd:
        return _check_worker()
    return 0


if __name__ == "__main__":
    sys.exit(main())
