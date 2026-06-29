#!/usr/bin/env python3
"""
Live log watcher — run in a second terminal while paper_bot.py runs.

  python paper_watch.py              # tail trades + log, play sounds
  python paper_watch.py --no-sound

Shows new lines from:
  - data/paper_trades.jsonl  (structured events + sounds)
  - logs/paper_bot.log       (SCAN / HOLD / DATA lines)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from paper.alerts import banner_close, banner_open, play_sound

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
PAPER_JSONL = os.path.join(DATA_DIR, "paper_trades.jsonl")
PAPER_LOG = os.path.join(LOG_DIR, "paper_bot.log")


def _fmt_ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _handle_trade_event(row: dict, sound: bool) -> None:
    ev = row.get("event", "")
    if ev == "open_basket":
        play_sound("open", enabled=sound)
        banner_open(
            row.get("pair", "?"),
            row.get("side", "?"),
            float(row.get("price", 0)),
            int(row.get("score", 0)),
            float(row.get("adx", 0)),
            float(row.get("rsi", 0)),
            float(row.get("tp", 0)),
            float(row.get("sl", 0)),
        )
        print(f"[{_fmt_ts()}] OPEN  {row.get('pair')} {row.get('side')} @ {row.get('price')}", flush=True)
    elif ev == "close_basket":
        pnl = float(row.get("total_profit", 0))
        play_sound("close", pnl=pnl, enabled=sound)
        banner_close(
            row.get("side", "?"),
            row.get("reason", "?"),
            pnl,
            float(row.get("balance", 0)),
        )
    elif ev == "session_end":
        print(
            f"\n[{_fmt_ts()}] SESSION END | balance=${row.get('balance')} "
            f"baskets={row.get('baskets')}\n",
            flush=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Live paper trading watcher")
    parser.add_argument("--no-sound", action="store_true")
    parser.add_argument("--from-start", action="store_true", help="Replay existing log from beginning")
    args = parser.parse_args()
    sound = not args.no_sound

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    jsonl_pos = 0 if args.from_start else (os.path.getsize(PAPER_JSONL) if os.path.isfile(PAPER_JSONL) else 0)
    log_pos = 0 if args.from_start else (os.path.getsize(PAPER_LOG) if os.path.isfile(PAPER_LOG) else 0)

    print("=" * 62)
    print("  PAPER WATCH — live logs (Ctrl+C to stop)")
    print(f"  trades: {PAPER_JSONL}")
    print(f"  log:    {PAPER_LOG}")
    print(f"  sound:  {'on' if sound else 'off'}")
    print("=" * 62)
    print("Waiting for paper_bot.py events…\n", flush=True)

    try:
        while True:
            # Structured trade events
            if os.path.isfile(PAPER_JSONL):
                with open(PAPER_JSONL, encoding="utf-8") as f:
                    f.seek(jsonl_pos)
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        _handle_trade_event(row, sound)
                    jsonl_pos = f.tell()

            # Raw bot log lines (SCAN, HOLD, DATA)
            if os.path.isfile(PAPER_LOG):
                with open(PAPER_LOG, encoding="utf-8", errors="replace") as f:
                    f.seek(log_pos)
                    for line in f:
                        text = line.rstrip()
                        if not text:
                            continue
                        # Skip duplicate banners already shown via jsonl
                        if "PAPER OPEN" in text or "PAPER CLOSE" in text:
                            continue
                        if any(k in text for k in ("SCAN #", "BRAIN", "EXEC", "PIPELINE", "AUTOPILOT", "gates")):
                            print(f"  {text}", flush=True)
                    log_pos = f.tell()

            time.sleep(0.4)
    except KeyboardInterrupt:
        print("\nWatch stopped.")


if __name__ == "__main__":
    main()
