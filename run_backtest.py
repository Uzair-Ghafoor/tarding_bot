#!/usr/bin/env python3
"""
Backtest + loss analysis + improved rerun + interactive Plotly charts.

  python run_backtest.py                  # full pipeline, charts open in browser
  python run_backtest.py --no-show        # print tables only (CI / headless)
  python run_backtest.py --pair EURUSD    # single pair deep-dive
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from backtest.data import load_pair_data
from backtest.engine import run_backtest
from backtest.guards import TradeGuards
from backtest.loss_analysis import (
    all_trades_df,
    print_loss_report,
    suggest_guards,
)
from backtest.pairs import DEFAULT_PAIRS, PAIRS
from backtest.plot import print_table
from backtest.viz import (
    show_comparison,
    show_equity_overlay,
    show_loss_deep_dive,
    show_pair_dashboard,
)
from config import CONFIG

# Frozen "old" settings for honest before/after comparison
BASELINE_GUARDS = TradeGuards(
    min_score=75,
    min_adx=18.0,
    max_z_buy=1.2,
    rsi_buy_max=65.0,
    max_vol_ratio=2.2,
    block_fallback=False,
)

LIVE_GUARDS = TradeGuards(
    min_score=CONFIG.min_confluence_score,
    min_adx=CONFIG.adx_min,
    max_z_buy=CONFIG.zscore_max_buy,
    max_z_sell=CONFIG.zscore_max_sell,
    rsi_buy_max=CONFIG.rsi_buy_max,
    max_vol_ratio=CONFIG.atr_spike_mult,
    block_fallback=False,
)


def _run_pairs(pairs: list[str], years: int, mode: str, refresh: bool, guards: TradeGuards | None):
    bar_minutes = 1440 if mode == "daily" else 15
    results = []
    for pair in pairs:
        print(f"\n[{pair}] loading ({mode})...")
        try:
            data = load_pair_data(pair, years=years, refresh=refresh, mode=mode)
        except Exception as exc:
            print(f"  SKIP: {exc}")
            continue
        label = guards.label() if guards else "baseline"
        print(f"  backtest ({label})...")
        r = run_backtest(
            pair,
            PAIRS[pair],
            data["h1"],
            data["m15"],
            data["d1"],
            bar_minutes=bar_minutes,
            guards=guards,
        )
        print(
            f"  WR={r.win_rate * 100:.1f}% Net=${r.net_pnl:+.2f} trades={len(r.trades)}"
        )
        results.append(r)
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", nargs="+", default=DEFAULT_PAIRS, choices=list(PAIRS.keys()))
    parser.add_argument("--pair", type=str, default=None, help="Single pair deep-dive")
    parser.add_argument("--years", type=int, default=10)
    parser.add_argument("--mode", choices=("daily", "hourly"), default="daily")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--no-show", action="store_true", help="Skip Plotly browser windows")
    args = parser.parse_args()

    pairs = [args.pair] if args.pair else args.pairs
    print("=" * 60)
    print("STEP 1 — BASELINE BACKTEST")
    print("=" * 60)
    baseline = _run_pairs(pairs, args.years, args.mode, args.refresh, guards=BASELINE_GUARDS)
    if not baseline:
        sys.exit(1)
    print_table(baseline)

    all_df = all_trades_df(baseline)
    guards = suggest_guards(all_df, LIVE_GUARDS)
    print_loss_report(all_df, guards)

    print("\n" + "=" * 60)
    print("STEP 2 — RERUN WITH LOSS-DRIVEN + LIVE FILTERS")
    print("=" * 60)
    improved = _run_pairs(pairs, args.years, args.mode, False, guards=guards)
    print_table(improved)

    # Summary comparison
    print("\n" + "=" * 60)
    print("BASELINE vs IMPROVED")
    print("=" * 60)
    bmap = {r.pair: r for r in baseline}
    imap = {r.pair: r for r in improved}
    for p in sorted(bmap):
        b, i = bmap[p], imap.get(p)
        if not i:
            continue
        print(
            f"{p}: WR {b.win_rate * 100:.1f}% → {i.win_rate * 100:.1f}% | "
            f"Net ${b.net_pnl:+.2f} → ${i.net_pnl:+.2f} | "
            f"Trades {len(b.trades)} → {len(i.trades)}"
        )

    if args.no_show:
        print("\n(--no-show: skipping Plotly charts)")
        return

    print("\nOpening interactive charts in your browser...")
    show_comparison(baseline, improved)
    show_equity_overlay(baseline, improved)
    show_loss_deep_dive(all_df, guards)

    if args.pair and baseline:
        show_pair_dashboard(bmap[args.pair], "baseline")
        if args.pair in imap:
            show_pair_dashboard(imap[args.pair], "improved")


if __name__ == "__main__":
    main()
