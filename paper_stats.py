"""Summarize Mac paper-trading session from data/paper_trades.jsonl."""

from __future__ import annotations

import json
import os
import sys

import pandas as pd


def main() -> None:
    path = os.path.join(os.path.dirname(__file__), "data", "paper_trades.jsonl")
    if not os.path.isfile(path):
        print("No paper trades yet. Run: python paper_bot.py --hours 48")
        sys.exit(0)

    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))

    df = pd.DataFrame(rows)
    opens = df[df["event"] == "open_basket"]
    closes = df[df["event"] == "close_basket"]

    print("=" * 60)
    print("PAPER TRADING SESSION")
    print("=" * 60)
    if not df.empty:
        print(f"From {df['ts'].iloc[0]}")
        print(f"To   {df['ts'].iloc[-1]}")

    print(f"\nBaskets opened: {len(opens)}")
    if not closes.empty:
        wins = (closes["total_profit"] >= 0).sum()
        losses = (closes["total_profit"] < 0).sum()
        net = closes["total_profit"].sum()
        wr = wins / len(closes) * 100 if len(closes) else 0
        print(f"Baskets closed: {len(closes)} | Wins: {wins} | Losses: {losses}")
        print(f"Win rate: {wr:.1f}% | Net P/L: ${net:+.2f}")
        print("\nClose reasons:")
        print(closes["reason"].value_counts().to_string())
        if "balance" in closes.columns:
            print(f"\nFinal balance: ${closes['balance'].iloc[-1]:.2f}")

    print("\nRecent events:")
    print(df.tail(10).to_string(index=False))


if __name__ == "__main__":
    main()
