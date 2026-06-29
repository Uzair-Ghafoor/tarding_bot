#!/usr/bin/env python3
"""
Autonomous AI trading autopilot — Claude brain + quant pipeline.

Mac paper mode (no MT5):
  python autopilot.py --hours 8 --symbol EURUSD
  python autopilot.py --no-session --brain claude   # needs ANTHROPIC_API_KEY in .env

AWS live mode (MT5):
  python autopilot.py --live --hours 8

Logs:
  logs/autopilot.log          (rotating)
  data/status.json            (live snapshot for pull)
  data/events.jsonl           (full event stream)
  data/agent_decisions.jsonl
  data/paper_trades.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

sys.path.insert(0, os.path.dirname(__file__))

from backtest.engine import _pnl_at_price, _spread_cost, _targets
from backtest.guards import TradeGuards
from backtest.pairs import PAIRS
from backtest.signals import BarSetup
from config import CONFIG
from agent.brain import decide
from agent.journal import log_decision
from agent.metrics import format_scan_metrics, format_scan_one_line, gate_checklist
from agent.snapshot import build_snapshot
from paper.alerts import banner_close, banner_open, notify_mac, play_sound
from paper.basket_state import restore_runtime_basket
from paper.feed import build_frames, refresh_live_bars, refresh_tick_only, resolve_paper_pair
from paper.telemetry import heartbeat as telemetry_heartbeat
from paper.telemetry import log_event as telemetry_event
from paper.telemetry import session_start as telemetry_session_start
from paper.telemetry import write_status as telemetry_status
from run_backtest import LIVE_GUARDS
from session import in_trading_session

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PAPER_LOG = os.path.join(DATA_DIR, "paper_trades.jsonl")
RUNTIME_FILE = os.path.join(DATA_DIR, "runtime.json")


def setup_logging() -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger("autopilot")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    log_path = os.path.join(LOG_DIR, "autopilot.log")
    fh = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    logger.addHandler(fh)
    return logger


log = setup_logging()


def _log_trade(event: str, **fields) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    row = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
    with open(PAPER_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    telemetry_event(event, **fields)


def _basket_dict(active: bool, **kw) -> dict:
    return {"active": active, **kw}


def run_paper_autopilot(
    pair: str,
    *,
    hours: float,
    price_sec: float,
    history_sec: int,
    scan_sec: float,
    use_session: bool,
    use_sound: bool,
    use_claude: bool,
    guards: TradeGuards,
) -> None:
    spec = PAIRS[pair]
    end_at = datetime.now(timezone.utc) + timedelta(hours=hours)
    brain_label = "Claude+quant" if use_claude and os.getenv("ANTHROPIC_API_KEY") else "rules"

    log.info("=" * 62)
    log.info("AUTOPILOT | %s | %.1fh | brain=%s | mode=paper", pair, hours, brain_label)
    log.info("Guards: %s | balance=$%.2f", guards.label(), CONFIG.reference_balance)
    log.info(
        "Scan every %.1fs | price every %.1fs (%.2fs in basket) | history every %ds",
        scan_sec, price_sec, CONFIG.basket_price_sec, history_sec,
    )
    log.info("Session: %s", use_session)
    log.info("=" * 62)

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(RUNTIME_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "pair": pair,
            "session_filter": use_session,
            "brain": brain_label,
            "started": datetime.now(timezone.utc).isoformat(),
            "hours": hours,
        }, f)

    balance = CONFIG.reference_balance
    start_balance = balance
    in_basket = False
    side: str | None = None
    entry_price = 0.0
    entry_time: datetime | None = None
    entry_setup: BarSetup | None = None
    tp = CONFIG.basket_min_profit
    sl = CONFIG.basket_max_loss
    last_entry_at = 0.0
    last_basket_close_at = 0.0
    last_sl_close_at = 0.0
    last_sl_side: str | None = None
    last_history_at = 0.0
    last_price_at = 0.0
    last_scan_at = 0.0
    scans = decisions = opens = closes = skips = 0
    frames = None
    spread = _spread_cost(spec, CONFIG.basket_size)
    last_status_at = 0.0

    restored = restore_runtime_basket(pair)
    if restored:
        in_basket = True
        side = restored["side"]
        entry_price = restored["entry_price"]
        entry_time = restored["entry_time"]
        tp = restored["tp"]
        sl = restored["sl"]
        balance = restored["balance"]
        start_balance = CONFIG.reference_balance
        opens = restored["opens"]
        closes = restored["closes"]
        log.warning(
            "RESUME open basket | %s %s @ %.5f | tp=$%.2f sl=$%.2f | opened %s",
            pair, side, entry_price, tp, sl, restored["open_ts"][:19],
        )
        telemetry_event(
            "basket_resume",
            pair=pair,
            side=side,
            entry_price=entry_price,
            tp=tp,
            sl=sl,
        )

    telemetry_session_start(pair=pair, brain=brain_label, hours=hours, balance=balance)

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
                        "PIPELINE | history loaded | price=%.5f | bars m15=%s",
                        frames["last_price"],
                        len(frames["m15"]),
                    )
                except Exception as exc:
                    log.warning("History load failed: %s", exc)
                    time.sleep(5)
                    continue
            elif now - last_price_at >= tick_sec:
                try:
                    if in_basket:
                        refresh_tick_only(frames, pair)
                    else:
                        refresh_live_bars(frames, pair)
                    last_price_at = now
                except Exception as exc:
                    log.warning("Price refresh failed: %s", exc)

            if frames is None:
                time.sleep(0.05 if in_basket else 0.5)
                continue

            price = frames["last_price"]

            if in_basket and side and entry_time:
                mark = _pnl_at_price(spec, side, entry_price, price, CONFIG.basket_size, spread)
                held = int((datetime.now(timezone.utc) - entry_time).total_seconds())
                basket = _basket_dict(
                    True, side=side, entry_price=entry_price, mark_pnl=round(mark, 3),
                    tp=tp, sl=sl, held_sec=held,
                )
                reason = ""
                exit_pnl = mark
                if mark >= tp:
                    reason, exit_pnl = "profit", tp
                elif mark <= -sl:
                    reason, exit_pnl = "basket_stop", -sl
                elif held >= CONFIG.max_hold_seconds:
                    reason, exit_pnl = "timeout", mark

                if reason:
                    balance += exit_pnl
                    closes += 1
                    _log_trade("close_basket", pair=pair, side=side, reason=reason,
                               total_profit=round(exit_pnl, 4), balance=round(balance, 2), held_sec=held)
                    log.info("EXEC CLOSE (%s) | %s | P/L $%.2f | bal=$%.2f", reason, side, exit_pnl, balance)
                    play_sound("close", pnl=exit_pnl, enabled=use_sound)
                    tag = "WIN" if exit_pnl >= 0 else "LOSS"
                    notify_mac(f"ScalpBot {tag}", f"{side.upper()} {reason} · P/L ${exit_pnl:+.2f} · bal ${balance:.2f}",
                               sound="Hero" if exit_pnl >= 0 else "Basso")
                    banner_close(side, reason, exit_pnl, balance)
                    if reason == "basket_stop":
                        last_sl_close_at = now
                        last_sl_side = side
                    in_basket = False
                    last_basket_close_at = now
                    entry_setup = None
                    side = None

            if in_basket:
                time.sleep(0.02)
                continue

            if now - last_scan_at < scan_sec:
                time.sleep(0.2)
                continue
            last_scan_at = now
            scans += 1

            basket = _basket_dict(
                in_basket,
                side=side,
                entry_price=entry_price,
                mark_pnl=round(_pnl_at_price(spec, side, entry_price, price, CONFIG.basket_size, spread), 3) if in_basket and side else 0,
                tp=tp, sl=sl,
                held_sec=int((datetime.now(timezone.utc) - entry_time).total_seconds()) if in_basket and entry_time else 0,
            )
            snapshot = build_snapshot(
                pair, frames, guards=guards, basket=basket,
                stats={"scans": scans, "opens": opens, "balance": round(balance, 2),
                       "session_pnl": round(balance - start_balance, 2)},
                use_session=use_session,
            )
            decision = decide(snapshot, use_claude=use_claude)
            decisions += 1

            # Full parameter breakdown every scan
            log.info(format_scan_metrics(snapshot, guards, scan_n=scans))

            executed = False
            detail = ""

            if decision.action == "skip":
                skips += 1
                log.info(
                    "BRAIN [%s] → SKIP | conf=%.0f%% | %s",
                    decision.source, decision.confidence * 100, decision.reasoning,
                )
            elif decision.action == "hold" and in_basket:
                log.info(
                    "BRAIN [%s] HOLD | %s | mark=$%.2f | %s",
                    decision.source, side, basket["mark_pnl"], decision.reasoning,
                )
            elif decision.action == "close" and in_basket and side:
                mark = basket["mark_pnl"]
                balance += mark
                closes += 1
                executed = True
                detail = "ai_early_close"
                _log_trade("close_basket", pair=pair, side=side, reason="ai_close",
                           total_profit=round(mark, 4), balance=round(balance, 2))
                log.info("EXEC CLOSE (ai) | %s | P/L $%.2f | %s", side, mark, decision.reasoning)
                play_sound("close", pnl=mark, enabled=use_sound)
                notify_mac("ScalpBot CLOSE", f"{side.upper()} · P/L ${mark:+.2f}", sound="Hero" if mark >= 0 else "Basso")
                in_basket = False
                last_basket_close_at = now
                side = None
            elif decision.action in ("open_buy", "open_sell") and not in_basket:
                trade_side = "buy" if decision.action == "open_buy" else "sell"
                same_side_sl = (
                    last_sl_side == trade_side
                    and (now - last_sl_close_at) < CONFIG.post_sl_cooldown_seconds
                )
                warmup_ok = scans > CONFIG.startup_warmup_scans
                cooldown_ok = (
                    warmup_ok
                    and not same_side_sl
                    and now - last_entry_at >= CONFIG.entry_cooldown_seconds
                    and now - last_basket_close_at >= CONFIG.post_basket_cooldown_seconds
                )
                if cooldown_ok and snapshot.quant_ok:
                    from backtest.signals import evaluate_at as ev

                    m15, h1, d1 = frames["m15"], frames["h1"], frames["d1"]
                    m_idx = len(m15) - 1
                    ts = m15.index[m_idx]
                    h_idx = max(0, h1.index.searchsorted(ts, side="right") - 1)
                    d_idx = max(0, d1.index.searchsorted(ts, side="right") - 1)
                    setup = ev(h1, m15, d1, h_idx, m_idx, d_idx, guards=guards)
                    if setup.side == trade_side and setup.passes_guards(guards):
                        tp, sl = _targets(spec, setup)
                        in_basket = True
                        side = trade_side
                        entry_price = price
                        entry_time = datetime.now(timezone.utc)
                        entry_setup = setup
                        last_entry_at = now
                        opens += 1
                        executed = True
                        _log_trade(
                            "open_basket", pair=pair, side=side, price=entry_price,
                            score=setup.score, adx=round(setup.adx, 1), rsi=round(setup.rsi, 1),
                            z_score=round(setup.z_score, 2), tp=tp, sl=sl,
                            agent_reason=decision.reasoning, agent_source=decision.source,
                        )
                        log.info(
                            "EXEC OPEN | %s %s | score=%s | brain=%s | %s",
                            pair, side.upper(), setup.score, decision.source, decision.reasoning,
                        )
                        play_sound("open", enabled=use_sound)
                        notify_mac("ScalpBot OPEN", f"{pair} {side.upper()} @ {entry_price:.5f} · score {setup.score}")
                        banner_open(pair, side, entry_price, setup.score, setup.adx, setup.rsi, tp, sl)
                    else:
                        detail = "setup_mismatch"
                        skips += 1
                else:
                    if not warmup_ok:
                        detail = "warmup"
                    elif same_side_sl:
                        detail = "post_sl_cooldown"
                    else:
                        detail = "cooldown" if not cooldown_ok else "quant_blocked"
                    skips += 1
            else:
                skips += 1

            log_decision(snapshot.ts, pair, decision, executed=executed, detail=detail)

            g = gate_checklist(snapshot, guards)
            status_kw = dict(
                pair=pair,
                brain=brain_label,
                price=round(price, 5),
                balance=round(balance, 2),
                pnl=round(balance - start_balance, 2),
                scans=scans,
                opens=opens,
                closes=closes,
                skips=skips,
                in_basket=in_basket,
                side=side,
                mark_pnl=basket.get("mark_pnl", 0) if in_basket else 0,
                last_action=decision.action,
                last_reason=decision.reasoning[:120],
                score=g["score"],
                gates_passed=g["passed"],
                gates_total=g["total"],
                ready=g["ready"],
            )
            if now - last_status_at >= 60:
                telemetry_heartbeat(**status_kw)
                last_status_at = now
            else:
                telemetry_status(**status_kw)

    except KeyboardInterrupt:
        log.info("Stopped by user.")
    finally:
        if in_basket and side and frames is not None:
            price = frames["last_price"]
            mark = _pnl_at_price(spec, side, entry_price, price, CONFIG.basket_size, spread)
            held = int((datetime.now(timezone.utc) - entry_time).total_seconds()) if entry_time else 0
            balance += mark
            closes += 1
            _log_trade(
                "close_basket", pair=pair, side=side, reason="session_shutdown",
                total_profit=round(mark, 4), balance=round(balance, 2), held_sec=held,
            )
            log.info("EXEC CLOSE (shutdown) | %s | P/L $%.2f | bal=$%.2f", side, mark, balance)
        pnl = balance - start_balance
        log.info(
            "AUTOPILOT END | scans=%s decisions=%s opens=%s closes=%s skips=%s | P/L $%+.2f | bal=$%.2f",
            scans, decisions, opens, closes, skips, pnl, balance,
        )
        _log_trade("session_end", pair=pair, balance=round(balance, 2), scans=scans,
                   opens=opens, closes=closes, agent_mode=brain_label)
        telemetry_event(
            "session_end",
            pair=pair,
            balance=round(balance, 2),
            pnl=round(balance - start_balance, 2),
            scans=scans,
            opens=opens,
            closes=closes,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous AI trading autopilot")
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--scan-sec", type=float, default=3.0, help="Brain cycle every N sec (default 3)")
    parser.add_argument("--price-sec", type=float, default=2.0)
    parser.add_argument("--history-sec", type=int, default=300)
    parser.add_argument("--no-session", action="store_true")
    parser.add_argument("--no-sound", action="store_true")
    parser.add_argument("--brain", choices=("auto", "claude", "rules"), default=None,
                        help="auto=Claude if API key else rules (default from AGENT_BRAIN env or rules)")
    parser.add_argument("--live", action="store_true", help="MT5 live (AWS only)")
    args = parser.parse_args()

    if args.live:
        log.error("MT5 live autopilot: use bot.py on AWS for now; paper mode on Mac.")
        sys.exit(1)

    pair = resolve_paper_pair(args.symbol or CONFIG.symbol.rstrip("m"))
    brain_arg = args.brain or os.getenv("AGENT_BRAIN", "rules")
    use_claude = brain_arg in ("auto", "claude")
    if brain_arg == "claude" and not os.getenv("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY missing — falling back to rules brain")
        use_claude = False
    if not use_claude:
        log.info("Brain: rules engine (add ANTHROPIC_API_KEY + AGENT_BRAIN=claude for production)")

    run_paper_autopilot(
        pair,
        hours=args.hours,
        price_sec=args.price_sec,
        history_sec=args.history_sec,
        scan_sec=args.scan_sec,
        use_session=CONFIG.use_session_filter and not args.no_session,
        use_sound=not args.no_sound,
        use_claude=use_claude,
        guards=LIVE_GUARDS,
    )


if __name__ == "__main__":
    main()
