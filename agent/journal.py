"""Agent decision + trade journal."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from agent.types import Decision

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
AGENT_LOG = os.path.join(DATA_DIR, "agent_decisions.jsonl")


def log_decision(snapshot_ts: str, pair: str, decision: Decision, *, executed: bool, detail: str = "") -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": "agent_decision",
        "snapshot_ts": snapshot_ts,
        "pair": pair,
        "action": decision.action,
        "confidence": round(decision.confidence, 3),
        "reasoning": decision.reasoning,
        "source": decision.source,
        "executed": executed,
        "detail": detail,
    }
    with open(AGENT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
