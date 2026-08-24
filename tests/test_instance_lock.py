from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from event_radar.config import Settings
from event_radar.instance_lock import EventRadarInstanceLock, EventRadarInstanceRunningError


def _wait_for_file(path: Path, process: subprocess.Popen[str], timeout_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise AssertionError(f"child process exited before signaling readiness: {stderr}")
        time.sleep(0.05)
    raise AssertionError("child process did not acquire the instance lock in time")


def test_instance_lock_prevents_duplicate_processes(tmp_path: Path) -> None:
    database_path = tmp_path / "event_radar.sqlite3"
    ready_file = tmp_path / "instance-ready"
    settings = Settings(database_path=database_path, app_host="127.0.0.1", app_port=8137, start_collectors=False)
    child_code = f"""
from pathlib import Path
import time

from event_radar.config import Settings
from event_radar.instance_lock import EventRadarInstanceLock

settings = Settings(
    database_path=Path({str(database_path)!r}),
    app_host="127.0.0.1",
    app_port=8141,
    start_collectors=False,
)
lock = EventRadarInstanceLock(settings)
lock.acquire()
Path({str(ready_file)!r}).write_text("ready", encoding="utf-8")
try:
    time.sleep(30)
finally:
    lock.release()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", child_code],
        cwd=str(tmp_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_file(ready_file, process)
        lock = EventRadarInstanceLock(settings)
        with pytest.raises(EventRadarInstanceRunningError, match="event_radar_instance_running"):
            lock.acquire()
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    lock = EventRadarInstanceLock(settings)
    lock.acquire()
    lock.release()
