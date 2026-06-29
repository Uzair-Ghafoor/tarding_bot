#!/usr/bin/env python3
"""
Paper trade on Mac with live Yahoo/Binance data — no MT5 required.

  python paper_bot.py --hours 48
  python paper_bot.py --hours 24 --symbol EURUSD
  python paper_stats.py

Data is ~15 min delayed on Yahoo forex; good enough to test logic & frequency.
Run in background:  nohup python paper_bot.py --hours 48 &
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

from backtest.engine import _pnl_at_price, _spread_cost, _targets
from backtest.guards import TradeGuards
from backtest.pairs import PAIRS
from backtest.signals import BarSetup, evaluate_at
from config import CONFIG
from paper.alerts import banner_close, banner_open, play_sound
from paper.basket_exit import check_basket_exit
from paper.feed import build_frames, refresh_live_bars, refresh_tick_only, resolve_paper_pair
from run_backtest import LIVE_GUARDS
from session import in_trading_session

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PAPER_LOG = os.path.join(DATA_DIR, "paper_trades.jsonl")


def setup_logging() -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger("paper")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    fh = logging.FileHandler(os.path.join(LOG_DIR, "paper_bot.log"))
    fh.setFormatter(fmt)
    logger.addHandler(sh)
    logger.addHandler(fh)
    return logger


log = setup_logging()


def _log_event(event: str, **fields) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    row = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
    with open(PAPER_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _align_last(m15, h1, d1):
    m_idx = len(m15) - 1
    ts = m15.index[m_idx]
    h_idx = h1.index.searchsorted(ts, side="right") - 1
    d_idx = d1.index.searchsorted(ts, side="right") - 1
    return max(0, h_idx), m_idx, max(0, d_idx)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mac paper trading bot")
    parser.add_argument("--hours", type=float, default=48.0, help="Run duration (default 48)")
    parser.add_argument("--symbol", type=str, default=None, help="Pair e.g. XAUUSD, EURUSD")
    parser.add_argument("--price-sec", type=float, default=2.0, help="Poll live price every N sec (default 2)")
    parser.add_argument("--history-sec", type=int, default=300, help="Reload H1/daily history every N sec (default 300)")
    parser.add_argument("--scan-log-sec", type=float, default=5.0, help="Min seconds between SCAN log lines (default 5)")
    parser.add_argument("--refresh-sec", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--no-session", action="store_true", help="Trade 24/7 (for weekend Mac tests)")
    parser.add_argument("--no-sound", action="store_true", help="Disable open/close sounds")
    args = parser.parse_args()

    pair = resolve_paper_pair(args.symbol or CONFIG.symbol.rstrip("m"))
    spec = PAIRS[pair]
    price_sec = float(args.refresh_sec if args.refresh_sec is not None else args.price_sec)
    history_sec = args.history_sec
    scan_log_sec = args.scan_log_sec
    price_move_log = spec.pip_size * 3
    use_session = CONFIG.use_session_filter and not args.no_session
    use_sound = not args.no_sound
    guards: TradeGuards = LIVE_GUARDS
    end_at = datetime.now(timezone.utc) + timedelta(hours=args.hours)

    log.info("=" * 60)
    log.info("PAPER BOT (Mac) | %s | %.1fh | no real orders", pair, args.hours)
    log.info("Guards: %s | ref balance $%.0f", guards.label(), CONFIG.reference_balance)
    log.info(
        "Poll: price every %.1fs | history every %ds | scan log every %.0fs",
        price_sec, history_sec, scan_log_sec,
    )
    log.info("Session filter: %s | sound: %s | log: %s", use_session, use_sound, PAPER_LOG)
    log.info("=" * 60)

    balance = CONFIG.reference_balance
    in_basket = False
    side: str | None = None
    entry_price = 0.0
    entry_time: datetime | None = None
    entry_setup: BarSetup | None = None
    tp = CONFIG.basket_min_profit
    sl = CONFIG.basket_max_loss
    last_entry_at = 0.0
    last_basket_close_at = 0.0
    last_history_at = 0.0
    last_price_at = 0.0
    last_status_at = 0.0
    last_logged_price: float | None = None
    scans = signals_seen = baskets_opened = 0

    frames: dict | None = None
    spread = _spread_cost(spec, CONFIG.basket_size)

    try:
        while datetime.now(timezone.utc) < end_at:
            now = time.time()

            tick_sec = CONFIG.basket_price_sec if in_basket else price_sec

            if frames is None or now - last_history_at >= history_sec:
                try:
                    frames = build_frames(pair, history_max_age_sec=history_sec)
                    last_history_at = now
                    last_price_at = now
                    log.info(
                        "HISTORY | price=%.5f | m15=%s h1=%s d1=%s | bar=%s",
                        frames["last_price"],
                        len(frames["m15"]),
                        len(frames["h1"]),
                        len(frames["d1"]),
                        frames["m5"].index[-1],
                    )
                except Exception as exc:
                    log.warning("History load failed: %s", exc)
                    time.sleep(5)
                    continue
            elif now - last_price_at >= tick_sec:
                try:
                    if in_basket and CONFIG.basket_exit_mode == "bar_range":
                        price = refresh_live_bars(frames, pair)
                    elif in_basket:
                        price = refresh_tick_only(frames, pair)
                    else:
                        price = refresh_live_bars(frames, pair)
                    last_price_at = now
                    moved = (
                        last_logged_price is not None
                        and abs(price - last_logged_price) >= price_move_log
                    )
                    if moved and now - last_status_at >= 1.0:
                        log.info("TICK | price=%.5f | bar=%s", price, frames["m5"].index[-1])
                        last_status_at = now
                except Exception as exc:
                    log.warning("Price refresh failed: %s", exc)

            if frames is None:
                time.sleep(0.02 if in_basket else 0.5)
                continue

            price = frames["last_price"]
            m15, h1, d1 = frames["m15"], frames["h1"], frames["d1"]

            if use_session and not in_trading_session():
                if now - last_status_at > 120:
                    log.info("Outside session (UTC) — waiting")
                    last_status_at = now
                time.sleep(5)
                continue

            if in_basket and side and entry_setup:
                held = int((datetime.now(timezone.utc) - entry_time).total_seconds()) if entry_time else 0
                decision = check_basket_exit(
                    spec, side, entry_price, price,
                    m5=frames.get("m5"),
                    entry_time=entry_time or datetime.now(timezone.utc),
                    tp=tp,
                    sl=sl,
                    spread=spread,
                    basket_size=CONFIG.basket_size,
                    held_sec=held,
                )
                if decision:
                    reason, exit_pnl = decision.reason, decision.pnl
                    balance += exit_pnl
                    _log_event(
                        "close_basket",
                        pair=pair,
                        side=side,
                        reason=reason,
                        total_profit=round(exit_pnl, 4),
                        balance=round(balance, 2),
                        held_sec=int(held),
                    )
                    log.info(
                        "PAPER CLOSE (%s) | %s | P/L $%.2f | balance $%.2f",
                        reason, side, exit_pnl, balance,
                    )
                    play_sound("close", pnl=exit_pnl, enabled=use_sound)
                    banner_close(side, reason, exit_pnl, balance)
                    in_basket = False
                    last_basket_close_at = now
                    entry_setup = None

                if in_basket:
                    time.sleep(0.02)
                    continue

            elif not in_basket:
                cooldown_ok = (
                    now - last_entry_at >= CONFIG.entry_cooldown_seconds
                    and now - last_basket_close_at >= CONFIG.post_basket_cooldown_seconds
                )
                if cooldown_ok:
                    h_idx, m_idx, d_idx = _align_last(m15, h1, d1)
                    setup = evaluate_at(h1, m15, d1, h_idx, m_idx, d_idx, guards=guards)
                    scans += 1
                    if setup.side:
                        signals_seen += 1
                    if setup.passes_guards(guards) and setup.side:
                        tp, sl = _targets(spec, setup)
                        in_basket = True
                        side = setup.side
                        entry_price = price
                        entry_time = datetime.now(timezone.utc)
                        entry_setup = setup
                        last_entry_at = now
                        baskets_opened += 1
                        _log_event(
                            "open_basket",
                            pair=pair,
                            side=side,
                            price=entry_price,
                            score=setup.score,
                            adx=round(setup.adx, 1),
                            rsi=round(setup.rsi, 1),
                            z_score=round(setup.z_score, 2),
                            tp=tp,
                            sl=sl,
                            reasons=setup.reasons[:5],
                        )
                        log.info(
                            "PAPER OPEN | %s %s | score=%s ADX=%.0f RSI=%.0f | TP=$%.2f SL=$%.2f",
                            pair, side.upper(), setup.score, setup.adx, setup.rsi, tp, sl,
                        )
                        play_sound("open", enabled=use_sound)
                        banner_open(pair, side, entry_price, setup.score, setup.adx, setup.rsi, tp, sl)
                    elif (
                        now - last_status_at >= scan_log_sec
                        or (
                            last_logged_price is not None
                            and abs(price - last_logged_price) >= price_move_log
                        )
                    ):
                        log.info(
                            "SCAN | score=%s side=%s | %s | price=%.5f | balance=$%.2f",
                            setup.score,
                            setup.side or "—",
                            ", ".join(setup.reasons[:4]) or "wait",
                            price,
                            balance,
                        )
                        last_status_at = now
                        last_logged_price = price

            if in_basket and now - last_status_at >= 2.0:
                pnl = _pnl_at_price(spec, side, entry_price, price, CONFIG.basket_size, spread)
                log.info(
                    "HOLD | %s %s | price=%.5f mark P/L=$%.2f | target=+$%.2f stop=-$%.2f | bal=$%.2f",
                    pair, side, price, pnl, tp, sl, balance,
                )
                last_status_at = now
                last_logged_price = price

            time.sleep(CONFIG.poll_seconds)

    except KeyboardInterrupt:
        log.info("Stopped by user.")
    finally:
        log.info(
            "SESSION END | scans=%s signals=%s baskets=%s | balance=$%.2f (start $%.2f)",
            scans, signals_seen, baskets_opened, balance, CONFIG.reference_balance,
        )
        _log_event(
            "session_end",
            pair=pair,
            balance=round(balance, 2),
            scans=scans,
            signals=signals_seen,
            baskets=baskets_opened,
        )


if __name__ == "__main__":
    main()
