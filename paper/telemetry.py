"""Structured paper-trading telemetry — status snapshot + event stream for remote pull."""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
STATUS_FILE = os.path.join(DATA_DIR, "status.json")
EVENTS_FILE = os.path.join(DATA_DIR, "events.jsonl")

_session_started_at: float | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: str, row: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def _atomic_write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def session_start(*, pair: str, brain: str, hours: float, balance: float) -> None:
    global _session_started_at
    _session_started_at = time.time()
    log_event(
        "session_start",
        pair=pair,
        brain=brain,
        hours=hours,
        balance=balance,
        mode="paper",
    )
    write_status(
        pair=pair,
        brain=brain,
        balance=balance,
        pnl=0.0,
        price=None,
        scans=0,
        opens=0,
        closes=0,
        skips=0,
        in_basket=False,
        last_action="starting",
        last_reason="",
    )


def log_event(event: str, **fields: Any) -> None:
    row = {"ts": _now_iso(), "event": event, **fields}
    _append_jsonl(EVENTS_FILE, row)


def write_status(**fields: Any) -> None:
    uptime = int(time.time() - _session_started_at) if _session_started_at else 0
    payload = {"ts": _now_iso(), "uptime_sec": uptime, **fields}
    _atomic_write_json(STATUS_FILE, payload)


def heartbeat(**fields: Any) -> None:
    log_event("heartbeat", **fields)
    write_status(**fields)


def read_status() -> dict:
    try:
        with open(STATUS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
