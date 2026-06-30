"""Paper autopilot — trade all pairs on one shared balance."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from agent.brain import decide
from agent.journal import log_decision
from agent.metrics import format_scan_metrics, gate_checklist
from agent.snapshot import build_snapshot
from backtest.engine import _pnl_at_price, _targets
from backtest.guards import TradeGuards
from backtest.pairs import PAIRS
from backtest.signals import BarSetup, evaluate_at
from config import CONFIG
from paper.alerts import banner_close, banner_open, notify_mac, play_sound
from paper.basket_state import restore_runtime_basket
from paper.basket_exit import check_basket_exit
from paper.binance_futures import create_binance_client
from paper.fees import paper_close_cost, paper_open_cost, paper_pnl_spread
from paper.feed import build_frames, refresh_live_bars, refresh_tick_only
from paper.telemetry import heartbeat as telemetry_heartbeat
from paper.telemetry import log_event as telemetry_event
from paper.telemetry import session_start as telemetry_session_start
from paper.telemetry import write_status as telemetry_status

PAIR_ORDER = ["XAUUSDT"]


def paper_pairs() -> list[str]:
    raw = (CONFIG.paper_pairs or "").strip()
    if raw:
        return [p.strip() for p in raw.split(",") if p.strip() in PAIRS]
    return [p for p in PAIR_ORDER if p in PAIRS]


@dataclass
class PairState:
    pair: str
    frames: dict | None = None
    in_basket: bool = False
    side: str | None = None
    entry_price: float = 0.0
    entry_time: datetime | None = None
    entry_setup: BarSetup | None = None
    tp: float = field(default_factory=lambda: CONFIG.basket_min_profit)
    sl: float = field(default_factory=lambda: CONFIG.basket_max_loss)
    scans: int = 0
    decisions: int = 0
    opens: int = 0
    closes: int = 0
    skips: int = 0
    last_scan_at: float = 0.0
    last_history_at: float = 0.0
    last_price_at: float = 0.0
    last_entry_at: float = 0.0
    last_basket_close_at: float = 0.0
    last_sl_close_at: float = 0.0
    last_sl_side: str | None = None
    last_action: str = "skip"
    last_reason: str = ""
    score: int = 0
    gates_passed: int = 0
    gates_total: int = 8
    ready: bool = False
    spread: float = 0.0

    def status_dict(self, price: float) -> dict[str, Any]:
        mark = 0.0
        if self.in_basket and self.side:
            spec = PAIRS[self.pair]
            mark = round(
                _pnl_at_price(spec, self.side, self.entry_price, price, CONFIG.basket_size, self.spread),
                3,
            )
        return {
            "pair": self.pair,
            "price": round(price, 5),
            "in_basket": self.in_basket,
            "side": self.side,
            "mark_pnl": mark,
            "scans": self.scans,
            "opens": self.opens,
            "closes": self.closes,
            "skips": self.skips,
            "last_action": self.last_action,
            "last_reason": self.last_reason[:120],
            "score": self.score,
            "gates_passed": self.gates_passed,
            "gates_total": self.gates_total,
            "ready": self.ready,
        }


def run_multi_autopilot(
    log,
    *,
    pairs: list[str],
    hours: float,
    price_sec: float,
    history_sec: int,
    scan_sec: float,
    use_session: bool,
    use_sound: bool,
    use_claude: bool,
    guards: TradeGuards,
    data_dir: str,
    runtime_file: str,
    log_trade,
) -> None:
    end_at = datetime.now(timezone.utc) + timedelta(hours=hours)
    brain_label = "Claude+quant" if use_claude and __import__("os").getenv("ANTHROPIC_API_KEY") else "rules"

    log.info("=" * 62)
    log.info("AUTOPILOT MULTI | %s | %.1fh | brain=%s", ", ".join(pairs), hours, brain_label)
    log.info("Guards: %s | balance=$%.2f", guards.label(), CONFIG.reference_balance)
    log.info("Session: %s | scan=%.1fs | price=%.1fs", use_session, scan_sec, price_sec)
    binance = create_binance_client(log)
    if binance:
        log.info("Execution: BINANCE FUTURES TESTNET (real test orders)")
    else:
        log.info("Execution: paper simulation")
    log.info("=" * 62)

    import os

    os.makedirs(data_dir, exist_ok=True)
    with open(runtime_file, "w", encoding="utf-8") as f:
        json.dump({
            "mode": "multi",
            "pairs": pairs,
            "session_filter": use_session,
            "brain": brain_label,
            "binance_testnet": binance is not None,
            "started": datetime.now(timezone.utc).isoformat(),
            "hours": hours,
        }, f)

    balance = CONFIG.reference_balance
    start_balance = balance
    states: dict[str, PairState] = {}
    for pair in pairs:
        st = PairState(pair=pair, spread=paper_pnl_spread(PAIRS[pair], CONFIG.basket_size))
        restored = None if binance else restore_runtime_basket(pair)
        if restored:
            st.in_basket = True
            st.side = restored["side"]
            st.entry_price = restored["entry_price"]
            st.entry_time = restored["entry_time"]
            st.tp = restored["tp"]
            st.sl = restored["sl"]
            balance = restored["balance"]
            st.opens = restored["opens"]
            st.closes = restored["closes"]
            log.warning("RESUME | %s %s @ %.5f", pair, st.side, st.entry_price)
        states[pair] = st

    if binance:
        symbol = CONFIG.binance_symbol
        pos = binance.get_position(symbol)
        if pos:
            try:
                binance.close_market(symbol)
                log.info("CLEAN | closed %s %s qty=%.4f @ %.5f", symbol, pos.side, pos.qty, pos.entry_price)
            except Exception as exc:
                log.error("CLEAN | failed to close %s: %s", symbol, exc)
        for st in states.values():
            st.in_basket = False
            st.side = None
            st.entry_setup = None
        balance = start_balance = CONFIG.reference_balance
        log.info("BINANCE | fresh $%.2f session (exchange orders, paper P/L tracking)", balance)

    telemetry_session_start(pair="MULTI", brain=brain_label, hours=hours, balance=balance)
    total_scans = total_opens = total_closes = total_skips = 0
    last_status_at = 0.0

    try:
        while datetime.now(timezone.utc) < end_at:
            now = time.time()
            any_in_basket = any(s.in_basket for s in states.values())

            for pair, st in states.items():
                spec = PAIRS[pair]
                tick_sec = CONFIG.basket_price_sec if st.in_basket else price_sec

                if st.frames is None or now - st.last_history_at >= history_sec:
                    try:
                        st.frames = build_frames(pair, history_max_age_sec=history_sec)
                        st.last_history_at = now
                        st.last_price_at = now
                    except Exception as exc:
                        log.warning("%s history failed: %s", pair, exc)
                        continue
                elif now - st.last_price_at >= tick_sec:
                    try:
                        if st.in_basket and CONFIG.basket_exit_mode == "bar_range":
                            refresh_live_bars(st.frames, pair)
                        elif st.in_basket:
                            refresh_tick_only(st.frames, pair)
                        else:
                            refresh_live_bars(st.frames, pair)
                        st.last_price_at = now
                    except Exception as exc:
                        log.warning("%s price failed: %s", pair, exc)

                if st.frames is None:
                    continue

                price = st.frames["last_price"]

                if st.in_basket and st.side and st.entry_time:
                    held = int((datetime.now(timezone.utc) - st.entry_time).total_seconds())
                    m5 = st.frames.get("m5") if st.frames else None
                    decision = check_basket_exit(
                        spec, st.side, st.entry_price, price,
                        m5=m5,
                        entry_time=st.entry_time,
                        tp=st.tp,
                        sl=st.sl,
                        spread=st.spread,
                        basket_size=CONFIG.basket_size,
                        held_sec=held,
                    )
                    if decision:
                        reason = decision.reason
                        held = int((datetime.now(timezone.utc) - st.entry_time).total_seconds())
                        bal_before = balance
                        close_fees = 0.0
                        if binance and spec.ticker == CONFIG.binance_symbol:
                            try:
                                binance.close_market(CONFIG.binance_symbol)
                                close_fees = paper_close_cost(spec, price)
                                exit_pnl = round(decision.pnl - close_fees, 4)
                                balance += exit_pnl
                                gross_pnl = round(decision.pnl, 4)
                            except Exception as exc:
                                log.error("BINANCE CLOSE failed: %s", exc)
                                continue
                        else:
                            close_fees = paper_close_cost(spec, price)
                            exit_pnl = round(decision.pnl - close_fees, 4)
                            balance += exit_pnl
                            gross_pnl = round(decision.pnl, 4)
                        st.closes += 1
                        total_closes += 1
                        log_trade(
                            "close_basket", pair=pair, side=st.side, reason=reason,
                            total_profit=exit_pnl, gross_pnl=gross_pnl,
                            fees=close_fees, balance=round(balance, 2), held_sec=held,
                            execution="binance_testnet" if binance else "paper",
                        )
                        log.info(
                            "EXEC CLOSE (%s) | %s %s | P/L $%.2f (fees $%.2f) | bal=$%.2f",
                            reason, pair, st.side, exit_pnl, close_fees, balance,
                        )
                        play_sound("close", pnl=exit_pnl, enabled=use_sound)
                        if reason == "basket_stop":
                            st.last_sl_close_at = now
                            st.last_sl_side = st.side
                        st.in_basket = False
                        st.last_basket_close_at = now
                        st.side = None
                        st.entry_setup = None

                if st.in_basket:
                    continue

                if now - st.last_scan_at < scan_sec:
                    continue
                st.last_scan_at = now
                st.scans += 1
                total_scans += 1

                basket = {
                    "active": False,
                    "side": st.side,
                    "entry_price": st.entry_price,
                    "mark_pnl": 0,
                    "tp": st.tp,
                    "sl": st.sl,
                    "held_sec": 0,
                }
                snapshot = build_snapshot(
                    pair, st.frames, guards=guards, basket=basket,
                    stats={"scans": st.scans, "opens": st.opens, "balance": round(balance, 2),
                           "session_pnl": round(balance - start_balance, 2)},
                    use_session=use_session,
                )
                decision = decide(snapshot, use_claude=use_claude)
                st.decisions += 1

                if st.scans % 20 == 1:
                    log.info("[%s] %s", pair, format_scan_metrics(snapshot, guards, scan_n=st.scans))

                executed = False
                detail = ""
                st.last_action = decision.action
                st.last_reason = decision.reasoning

                if decision.action == "skip":
                    st.skips += 1
                    total_skips += 1
                elif decision.action in ("open_buy", "open_sell"):
                    trade_side = "buy" if decision.action == "open_buy" else "sell"
                    same_side_sl = (
                        st.last_sl_side == trade_side
                        and (now - st.last_sl_close_at) < CONFIG.post_sl_cooldown_seconds
                    )
                    warmup_ok = st.scans > CONFIG.startup_warmup_scans
                    cooldown_ok = (
                        warmup_ok
                        and not same_side_sl
                        and now - st.last_entry_at >= CONFIG.entry_cooldown_seconds
                        and now - st.last_basket_close_at >= CONFIG.post_basket_cooldown_seconds
                    )
                    if cooldown_ok and snapshot.quant_ok:
                        m15, h1, d1 = st.frames["m15"], st.frames["h1"], st.frames["d1"]
                        m_idx = len(m15) - 1
                        ts = m15.index[m_idx]
                        h_idx = max(0, h1.index.searchsorted(ts, side="right") - 1)
                        d_idx = max(0, d1.index.searchsorted(ts, side="right") - 1)
                        setup = evaluate_at(h1, m15, d1, h_idx, m_idx, d_idx, guards=guards)
                        if setup.side == trade_side and setup.passes_guards(guards):
                            tp, sl = _targets(spec, setup)
                            use_binance = binance is not None and spec.ticker == CONFIG.binance_symbol
                            if use_binance:
                                try:
                                    fill = binance.open_market(CONFIG.binance_symbol, trade_side, price)
                                    entry_px = fill.avg_price
                                    open_fees = paper_open_cost(spec, entry_px)
                                    balance -= open_fees
                                except Exception as exc:
                                    log.error("BINANCE OPEN failed: %s", exc)
                                    st.skips += 1
                                    total_skips += 1
                                    continue
                            else:
                                open_fees = paper_open_cost(spec, price)
                                balance -= open_fees
                                entry_px = price
                            st.in_basket = True
                            st.side = trade_side
                            st.entry_price = entry_px
                            st.entry_time = datetime.now(timezone.utc)
                            st.entry_setup = setup
                            st.last_entry_at = now
                            st.tp = tp
                            st.sl = sl
                            st.opens += 1
                            total_opens += 1
                            executed = True
                            log_trade(
                                "open_basket", pair=pair, side=st.side, price=st.entry_price,
                                score=setup.score, adx=round(setup.adx, 1), rsi=round(setup.rsi, 1),
                                z_score=round(setup.z_score, 2), tp=tp, sl=sl,
                                fees=open_fees, balance=round(balance, 2),
                                agent_reason=decision.reasoning, agent_source=decision.source,
                                execution="binance_testnet" if use_binance else "paper",
                            )
                            log.info(
                                "EXEC OPEN | %s %s | score=%s | fees $%.2f | %s",
                                pair, st.side.upper(), setup.score, open_fees, decision.reasoning,
                            )
                            play_sound("open", enabled=use_sound)
                            notify_mac("ScalpBot OPEN", f"{pair} {st.side.upper()} @ {st.entry_price:.5f}")
                            banner_open(pair, st.side, st.entry_price, setup.score, setup.adx, setup.rsi, tp, sl)
                        else:
                            st.skips += 1
                            total_skips += 1
                    else:
                        st.skips += 1
                        total_skips += 1
                else:
                    st.skips += 1
                    total_skips += 1

                log_decision(snapshot.ts, pair, decision, executed=executed, detail=detail)
                g = gate_checklist(snapshot, guards)
                st.score = g["score"]
                st.gates_passed = g["passed"]
                st.gates_total = g["total"]
                st.ready = g["ready"]

            pair_status = {
                p: s.status_dict(s.frames["last_price"] if s.frames else 0.0)
                for p, s in states.items()
            }
            status_kw = dict(
                mode="multi",
                pairs=pair_status,
                pair=pairs[0],
                brain=brain_label,
                balance=round(balance, 2),
                pnl=round(balance - start_balance, 2),
                scans=total_scans,
                opens=total_opens,
                closes=total_closes,
                skips=total_skips,
                in_basket=any_in_basket,
            )
            if now - last_status_at >= 60:
                telemetry_heartbeat(**status_kw)
                last_status_at = now
            else:
                telemetry_status(**status_kw)

            time.sleep(0.05 if any_in_basket else 0.15)

    except KeyboardInterrupt:
        log.info("Stopped by user.")
    finally:
        for pair, st in states.items():
            if st.in_basket and st.side and st.frames is not None:
                spec = PAIRS[pair]
                price = st.frames["last_price"]
                use_binance = binance is not None and spec.ticker == CONFIG.binance_symbol
                if use_binance:
                    try:
                        binance.close_market(CONFIG.binance_symbol)
                        close_fees = paper_close_cost(spec, price)
                        mark = _pnl_at_price(spec, st.side, st.entry_price, price, CONFIG.basket_size, st.spread)
                        exit_pnl = round(mark - close_fees, 4)
                        gross_pnl = round(mark, 4)
                        balance += exit_pnl
                    except Exception as exc:
                        log.error("BINANCE shutdown close failed: %s", exc)
                        continue
                else:
                    mark = _pnl_at_price(spec, st.side, st.entry_price, price, CONFIG.basket_size, st.spread)
                    close_fees = paper_close_cost(spec, price)
                    exit_pnl = round(mark - close_fees, 4)
                    gross_pnl = round(mark, 4)
                    balance += exit_pnl
                log_trade(
                    "close_basket", pair=pair, side=st.side, reason="session_shutdown",
                    total_profit=exit_pnl, gross_pnl=gross_pnl, fees=close_fees,
                    balance=round(balance, 2),
                    execution="binance_testnet" if use_binance else "paper",
                )
        log.info(
            "AUTOPILOT MULTI END | scans=%s opens=%s closes=%s | P/L $%+.2f",
            total_scans, total_opens, total_closes, balance - start_balance,
        )
        telemetry_event("session_end", mode="multi", balance=round(balance, 2), opens=total_opens, closes=total_closes)
