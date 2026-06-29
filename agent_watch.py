#!/usr/bin/env python3
"""Live dashboard for autopilot — tail brain decisions + trades."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
AGENT_LOG = os.path.join(DATA_DIR, "agent_decisions.jsonl")
AUTO_LOG = os.path.join(LOG_DIR, "autopilot.log")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-start", action="store_true")
    args = parser.parse_args()

    agent_pos = 0 if args.from_start else (os.path.getsize(AGENT_LOG) if os.path.isfile(AGENT_LOG) else 0)
    log_pos = 0 if args.from_start else (os.path.getsize(AUTO_LOG) if os.path.isfile(AUTO_LOG) else 0)

    print("=" * 62)
    print("  AUTOPILOT WATCH — brain decisions live (Ctrl+C stop)")
    print(f"  {AGENT_LOG}")
    print("=" * 62, flush=True)

    try:
        while True:
            if os.path.isfile(AGENT_LOG):
                with open(AGENT_LOG, encoding="utf-8") as f:
                    f.seek(agent_pos)
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        ts = row.get("ts", "")[:19]
                        print(
                            f"[{ts}] {row.get('action','?').upper():8} "
                            f"[{row.get('source','?')}] conf={row.get('confidence',0):.0%} "
                            f"{'EXEC' if row.get('executed') else '----'} | {row.get('reasoning','')}",
                            flush=True,
                        )
                    agent_pos = f.tell()

            if os.path.isfile(AUTO_LOG):
                with open(AUTO_LOG, encoding="utf-8", errors="replace") as f:
                    f.seek(log_pos)
                    for line in f:
                        text = line.rstrip()
                        if any(k in text for k in ("SCAN #", "BRAIN", "EXEC", "PIPELINE", "AUTOPILOT", "gates", "OPEN=")):
                            print(f"  {text}", flush=True)
                    log_pos = f.tell()

            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
