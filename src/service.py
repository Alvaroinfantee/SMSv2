from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import Optional

from .db import init_db


worker: Optional[subprocess.Popen] = None
web: Optional[subprocess.Popen] = None


def _terminate(_signum=None, _frame=None) -> None:
    for process in (web, worker):
        if process and process.poll() is None:
            process.terminate()


def main() -> int:
    global worker, web
    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGINT, _terminate)
    init_db()

    worker = subprocess.Popen([sys.executable, "-m", "src.automation_worker"])
    try:
        port = os.getenv("PORT", "8080")
        web = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "app.py",
                "--server.address",
                "0.0.0.0",
                "--server.port",
                port,
            ]
        )
        return web.wait()
    finally:
        _terminate()
        if worker and worker.poll() is None:
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()


if __name__ == "__main__":
    raise SystemExit(main())
