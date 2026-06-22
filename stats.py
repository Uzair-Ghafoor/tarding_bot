"""Summarize demo performance from data/trades.jsonl."""

from __future__ import annotations

import json
import os
import sys
from collections import Counter


def main() -> None:
    path = os.path.join(os.path.dirname(__file__), "data", "trades.jsonl")
    if not os.path.isfile(path):
        print("No trades yet — run the bot on demo first.")
        sys.exit(0)

    wins = losses = 0
    profit_sum = 0.0
    win_sum = loss_sum = 0.0
    by_event: Counter[str] = Counter()
    by_reason: Counter[str] = Counter()
    orphan_closes = 0

    with open(path, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            ev = row.get("event", "")
            by_event[ev] += 1

            if ev == "close_basket":
                pnl = float(row.get("total_profit", 0))
                profit_sum += pnl
                reason = row.get("reason", "unknown")
                by_reason[reason] += 1
                remaining = int(row.get("remaining", 0))
                if remaining:
                    orphan_closes += 1
                if pnl >= 0:
                    wins += 1
                    win_sum += pnl
                else:
                    losses += 1
                    loss_sum += pnl
            elif ev == "close_profit":
                wins += 1
                p = float(row.get("profit", 0))
                profit_sum += p
                win_sum += p
            elif ev in ("close_sl", "close_timeout"):
                losses += 1
                p = float(row.get("profit", 0))
                profit_sum += p
                loss_sum += p

    baskets = wins + losses
    wr = wins / baskets * 100 if baskets else 0
    avg_win = win_sum / wins if wins else 0
    avg_loss = loss_sum / losses if losses else 0

    print("=" * 50)
    print("BASKET PERFORMANCE")
    print("=" * 50)
    print(f"Closed baskets: {baskets}")
    print(f"Wins:   {wins}")
    print(f"Losses: {losses}")
    print(f"Win rate: {wr:.1f}%")
    print(f"Net P/L: ${profit_sum:.2f}")
    if wins:
        print(f"Avg win:  ${avg_win:.2f}")
    if losses:
        print(f"Avg loss: ${avg_loss:.2f}")
    if by_reason:
        print(f"Close reasons: {dict(by_reason)}")
    if orphan_closes:
        print(f"WARNING: {orphan_closes} closes left orphan positions")
    print(f"Events: {dict(by_event)}")
    print(f"Opens logged: {by_event.get('open', 0)}")


if __name__ == "__main__":
    main()
