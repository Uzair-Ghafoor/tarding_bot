"""Shared paper basket state from trade journal."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from config import CONFIG

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAPER_LOG = os.path.join(ROOT, "data", "paper_trades.jsonl")


def read_trades() -> list[dict]:
    if not os.path.isfile(PAPER_LOG):
        return []
    rows = []
    with open(PAPER_LOG, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def trades_since_session(trades: list[dict]) -> list[dict]:
    start = 0
    for i, t in enumerate(trades):
        if t.get("event") == "session_end":
            start = i + 1
    return trades[start:]


def find_open_row(trades: list[dict], pair: str) -> dict | None:
    open_row: dict | None = None
    for t in trades:
        if t.get("pair") and t.get("pair") != pair:
            continue
        ev = t.get("event")
        if ev == "open_basket":
            open_row = t
        elif ev == "close_basket" and open_row is not None:
            open_row = None
    return open_row


def session_balance(trades: list[dict]) -> float:
    bal = CONFIG.reference_balance
    for t in trades:
        if t.get("event") == "close_basket" and "balance" in t:
            bal = float(t["balance"])
    return bal


def restore_runtime_basket(pair: str) -> dict | None:
    """If journal has an unmatched open for this pair, return fields to resume management."""
    sess = trades_since_session(read_trades())
    ob = find_open_row(sess, pair)
    if ob is None:
        return None
    try:
        opened = datetime.fromisoformat(ob["ts"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        opened = datetime.now(timezone.utc)
    opens = sum(1 for t in sess if t.get("event") == "open_basket" and t.get("pair") == pair)
    closes = sum(1 for t in sess if t.get("event") == "close_basket" and t.get("pair") == pair)
    return {
        "side": ob.get("side", "buy"),
        "entry_price": float(ob.get("price", 0)),
        "entry_time": opened,
        "tp": float(ob.get("tp", CONFIG.basket_min_profit)),
        "sl": float(ob.get("sl", CONFIG.basket_max_loss)),
        "balance": session_balance(sess),
        "opens": opens,
        "closes": closes,
        "open_ts": ob.get("ts", ""),
    }
