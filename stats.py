"""Summarize demo performance from data/trades.jsonl."""

from __future__ import annotations

import json
import os
import sys


def main() -> None:
    path = os.path.join(os.path.dirname(__file__), "data", "trades.jsonl")
    if not os.path.isfile(path):
        print("No trades yet — run the bot on demo first.")
        sys.exit(0)

    wins = losses = 0
    profit_sum = 0.0
    by_event: dict[str, int] = {}

    with open(path, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            ev = row.get("event", "")
            by_event[ev] = by_event.get(ev, 0) + 1
            if ev == "close_profit":
                wins += 1
                profit_sum += row.get("profit", 0)
            elif ev in ("close_sl", "close_timeout"):
                losses += 1
                profit_sum += row.get("profit", 0)

    total = wins + losses
    wr = wins / total * 100 if total else 0
    print(f"Closed trades: {total}")
    print(f"Wins:   {wins}")
    print(f"Losses: {losses}")
    print(f"Win rate: {wr:.1f}%")
    print(f"Net P/L (logged): ${profit_sum:.2f}")
    print(f"Events: {by_event}")


if __name__ == "__main__":
    main()
