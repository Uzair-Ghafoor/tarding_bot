#!/usr/bin/env python3
"""Print paper bot status from pulled or local data/status.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_status(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _tail_events(path: Path, n: int = 5) -> list[dict]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    out = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def main() -> None:
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data"
    status_path = base / "status.json" if base.is_dir() else base
    data_dir = status_path.parent
    s = _load_status(status_path)

    if not s:
        print("No status.json — bot may not be running or logs not pulled yet.")
        print(f"Expected: {status_path}")
        sys.exit(1)

    pnl = float(s.get("pnl", 0))
    sign = "+" if pnl >= 0 else ""
    print("─" * 48)
    mode = s.get("mode", "single")
    print(f"  ScalpBot paper  ·  {s.get('pair', '?')}" + (" (multi)" if mode == "multi" else ""))
    print("─" * 48)
    print(f"  Updated    {str(s.get('ts', ''))[:19]}")
    print(f"  Uptime     {s.get('uptime_sec', 0) // 3600}h {(s.get('uptime_sec', 0) % 3600) // 60}m")
    if mode == "multi":
        print(f"  Balance    ${float(s.get('balance', 0)):.2f}   P/L {sign}${pnl:.2f}")
        print(f"  Scans      {s.get('scans', 0):,}   opens {s.get('opens', 0)}  closes {s.get('closes', 0)}")
        print("  Pairs:")
        for pname, ps in (s.get("pairs") or {}).items():
            b = "OPEN" if ps.get("in_basket") else "flat"
            print(f"    {pname:8} {b:5}  score={ps.get('score', 0):3}  gates={ps.get('gates_passed', 0)}/{ps.get('gates_total', 8)}  {ps.get('last_reason', '')[:36]}")
        print("─" * 48)
    else:
        print(f"  Price      {s.get('price', '—')}")
        print(f"  Balance    ${float(s.get('balance', 0)):.2f}   P/L {sign}${pnl:.2f}")
        print(f"  Scans      {s.get('scans', 0):,}   opens {s.get('opens', 0)}  closes {s.get('closes', 0)}")
        basket = "OPEN" if s.get("in_basket") else "flat"
        print(f"  Basket     {basket}", end="")
        if s.get("in_basket"):
            print(f"  {s.get('side', '')}  mark ${float(s.get('mark_pnl', 0)):+.2f}")
        else:
            print()
        print(f"  Last       {s.get('last_action', '—')} — {s.get('last_reason', '')[:50]}")
        if s.get("score") is not None:
            print(f"  Signal     score={s.get('score')}  gates={s.get('gates_passed', '?')}/{s.get('gates_total', '?')}")
        print("─" * 48)

    events = _tail_events(data_dir / "events.jsonl", 4)
    if events:
        print("  Recent events:")
        for e in events:
            ev = e.get("event", "?")
            ts = str(e.get("ts", ""))[11:19]
            extra = e.get("reason") or e.get("total_profit") or e.get("detail") or ""
            if ev == "close_basket":
                extra = f"${float(e.get('total_profit', 0)):+.2f} {e.get('reason', '')}"
            print(f"    {ts}  {ev}  {extra}")


if __name__ == "__main__":
    main()
