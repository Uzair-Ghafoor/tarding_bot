"""Append-only trade/event log for MT5 bot."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone


class Recorder:
    def __init__(self, path: str | None = None):
        base = os.path.dirname(__file__)
        self.path = path or os.path.join(base, "data", "trades.jsonl")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def log(self, event: str, **fields) -> None:
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **fields,
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
