#!/usr/bin/env python3
"""Paper autopilot — all pairs, shared balance."""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from autopilot import DATA_DIR, RUNTIME_FILE, _log_trade, setup_logging
from config import CONFIG
from paper.multi_runner import paper_pairs, run_multi_autopilot
from run_backtest import LIVE_GUARDS

log = setup_logging()


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-pair paper autopilot")
    parser.add_argument("--hours", type=float, default=8760.0)
    parser.add_argument("--scan-sec", type=float, default=5.0)
    parser.add_argument("--price-sec", type=float, default=2.0)
    parser.add_argument("--history-sec", type=int, default=300)
    parser.add_argument("--no-session", action="store_true")
    parser.add_argument("--no-sound", action="store_true")
    parser.add_argument("--brain", choices=("auto", "claude", "rules"), default=None)
    args = parser.parse_args()

    pairs = paper_pairs()
    brain_arg = args.brain or os.getenv("AGENT_BRAIN", "rules")
    use_claude = brain_arg in ("auto", "claude")
    if brain_arg == "claude" and not os.getenv("ANTHROPIC_API_KEY"):
        use_claude = False

    run_multi_autopilot(
        log,
        pairs=pairs,
        hours=args.hours,
        price_sec=args.price_sec,
        history_sec=args.history_sec,
        scan_sec=args.scan_sec,
        use_session=CONFIG.use_session_filter and not args.no_session,
        use_sound=not args.no_sound,
        use_claude=use_claude,
        guards=LIVE_GUARDS,
        data_dir=DATA_DIR,
        runtime_file=RUNTIME_FILE,
        log_trade=_log_trade,
    )


if __name__ == "__main__":
    main()
