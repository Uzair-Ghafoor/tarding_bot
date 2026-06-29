"""
Exness MT5 quantitative basket bot.

Math-driven execution:
- ATR-scaled basket TP/SL (volatility-normalized targets)
- Half-Kelly risk cap from basket history
- Expected-value gate (skip when EV < 0 after enough samples)
- ADX + Z-score filters in analysis layer
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass

import MetaTrader5 as mt5

from analysis import Setup, analyze
from config import CONFIG
from mt5_client import MT5Client
from quant import atr_basket_targets, effective_sl_atr_mult
from recorder import Recorder
from risk import RiskState
from session import in_trading_session


def setup_logging() -> logging.Logger:
    os.makedirs(os.path.join(os.path.dirname(__file__), "logs"), exist_ok=True)
    logger = logging.getLogger("mt5bot")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    fh = logging.FileHandler(
        os.path.join(os.path.dirname(__file__), "logs", "bot.log")
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


log = setup_logging()


@dataclass
class BasketPlan:
    profit_target: float
    stop_target: float
    atr_points: int = 0
    kelly_cap_pct: float = 0.0


_active_plan: BasketPlan | None = None


def _position_age_seconds(pos) -> float:
    return max(0.0, time.time() - pos.time)


def _basket_pnl(client: MT5Client, positions) -> float:
    return sum(client.position_profit(p.ticket) for p in positions)


def _oldest_age(positions) -> float:
    if not positions:
        return 0.0
    return max(_position_age_seconds(p) for p in positions)


def _plan_targets() -> BasketPlan:
    global _active_plan
    if _active_plan:
        return _active_plan
    return BasketPlan(
        profit_target=CONFIG.basket_min_profit,
        stop_target=CONFIG.basket_max_loss,
    )


def _compute_plan(client: MT5Client, setup: Setup, risk: RiskState) -> BasketPlan:
    kelly_cap = risk.kelly_risk_cap()
    kelly_stop = round(CONFIG.reference_balance * kelly_cap, 2)

    if not CONFIG.use_atr_targets or setup.atr_m5 <= 0:
        profit = CONFIG.basket_min_profit
        stop = min(CONFIG.basket_max_loss, kelly_stop)
        return BasketPlan(profit, stop, kelly_cap_pct=kelly_cap)

    info = mt5.symbol_info(CONFIG.symbol)
    point = float(info.point) if info else 0.01
    money_per_point = client.points_to_money(CONFIG.symbol, 1, CONFIG.lot_size)

    profit, stop, atr_pts = atr_basket_targets(
        atr_price=setup.atr_m5,
        point=point,
        money_per_point_per_lot=money_per_point / CONFIG.lot_size,
        lot=CONFIG.lot_size,
        basket_size=CONFIG.basket_size,
        tp_atr_mult=CONFIG.atr_tp_mult,
        sl_atr_mult=effective_sl_atr_mult(setup.vol_ratio),
        min_profit=CONFIG.basket_min_profit,
        min_loss=CONFIG.basket_min_profit * 0.5,
        max_profit=CONFIG.reference_balance * 0.08,
        max_loss=min(CONFIG.basket_max_loss, kelly_stop),
    )
    return BasketPlan(profit, stop, atr_pts, kelly_cap)


def _close_basket(
    client: MT5Client,
    recorder: Recorder,
    risk: RiskState,
    positions,
    reason: str,
) -> None:
    global _active_plan
    total_before = _basket_pnl(client, positions)
    expected = len(positions)
    closed = client.close_all(CONFIG.symbol, retries=4)
    remaining = client.positions(CONFIG.symbol)
    total_after = _basket_pnl(client, remaining) if remaining else 0.0
    total = total_before if not remaining else total_before + total_after

    risk.record_close(total)
    recorder.log(
        "close_basket",
        reason=reason,
        tickets=closed,
        count=closed,
        expected=expected,
        remaining=len(remaining),
        total_profit=round(total, 4),
    )
    log.info(
        "BASKET CLOSE (%s) | closed=%s expected=%s remaining=%s | P/L $%.2f",
        reason,
        closed,
        expected,
        len(remaining),
        total,
    )
    if remaining:
        log.warning("Orphan positions remain — force closing again")
        client.close_all(CONFIG.symbol, retries=5)
    _active_plan = None


def _scan_basket_exits(
    client: MT5Client,
    recorder: Recorder,
    risk: RiskState,
    positions,
) -> str | None:
    if not positions:
        return None

    n = len(positions)
    if n < CONFIG.basket_size:
        return None

    plan = _plan_targets()
    total = _basket_pnl(client, positions)
    age = _oldest_age(positions)

    if total >= plan.profit_target:
        _close_basket(client, recorder, risk, positions, "profit")
        return "profit"

    if total <= -abs(plan.stop_target):
        _close_basket(client, recorder, risk, positions, "basket_stop")
        return "basket_stop"

    if CONFIG.max_hold_seconds and age >= CONFIG.max_hold_seconds:
        _close_basket(client, recorder, risk, positions, "timeout")
        return "timeout"

    return None


def _open_basket(
    client: MT5Client,
    recorder: Recorder,
    setup: Setup,
    plan: BasketPlan,
    need: int,
) -> int:
    global _active_plan
    if not setup.ok or not setup.side:
        return 0

    spread = client.spread_points(CONFIG.symbol)
    if spread > CONFIG.max_spread_points:
        log.info("Skip | spread=%s (max %s)", spread, CONFIG.max_spread_points)
        return 0

    opened = 0
    deadline = time.time() + CONFIG.basket_fill_timeout_seconds

    while opened < need and time.time() < deadline:
        ticket = client.open_market(
            CONFIG.symbol,
            setup.side,
            CONFIG.lot_size,
            sl_points=CONFIG.stop_loss_points,
            comment=f"b{opened + 1}",
        )
        if ticket:
            opened += 1
            recorder.log(
                "open",
                ticket=ticket,
                side=setup.side,
                lot=CONFIG.lot_size,
                score=setup.score,
                reasons=setup.reasons,
                adx=round(setup.adx, 1),
                z_score=round(setup.z_score, 2),
                atr_m5=round(setup.atr_m5, 4),
                basket_slot=opened,
                profit_target=plan.profit_target,
                stop_target=plan.stop_target,
            )
        if opened < need:
            time.sleep(CONFIG.batch_open_delay)

    if opened and opened < need:
        log.warning(
            "Basket incomplete %s/%s — closing all to avoid orphans",
            opened,
            need,
        )
        client.close_all(CONFIG.symbol, retries=4)
        return 0

    if opened:
        _active_plan = plan
        log.info(
            "BASKET OPEN | %s × %.2f %s | score=%s | TP=$%.2f SL=$%.2f | "
            "ATR=%spts ADX=%.0f Z=%.2f | %s",
            opened,
            CONFIG.lot_size,
            setup.side.upper(),
            setup.score,
            plan.profit_target,
            plan.stop_target,
            plan.atr_points,
            setup.adx,
            setup.z_score,
            ", ".join(setup.reasons[:4]),
        )
    return opened


def validate_config() -> None:
    if not CONFIG.login or not CONFIG.password or not CONFIG.server:
        raise ValueError("Set MT5_LOGIN, MT5_PASSWORD, MT5_SERVER in .env")


def main() -> None:
    validate_config()
    client = MT5Client()
    recorder = Recorder()
    risk = RiskState()
    last_entry_at = 0.0
    last_basket_close_at = 0.0
    last_sl_close_at = 0.0
    last_sl_side: str | None = None
    last_status_at = 0.0
    scans = 0

    log.info("=" * 60)
    log.info(
        "Quant basket bot v3 | %s | lot=%.2f | x%s | ref $%.0f",
        CONFIG.symbol,
        CONFIG.lot_size,
        CONFIG.basket_size,
        CONFIG.reference_balance,
    )
    log.info(
        "ATR targets=%s | Kelly frac=%.0f%% | EV gate=%s",
        CONFIG.use_atr_targets,
        CONFIG.kelly_fraction * 100,
        CONFIG.use_ev_gate,
    )
    s = risk.stats
    if s.baskets:
        log.info(
            "History | baskets=%s WR=%.0f%% EV=$%.2f PF=%.2f half-Kelly=%.1f%%",
            s.baskets,
            s.win_rate * 100,
            s.expectancy,
            s.pf if s.pf != float("inf") else 99.9,
            s.half_kelly * 100,
        )
    log.info("=" * 60)

    try:
        client.connect()
        symbol = client.resolve_symbol(CONFIG.symbol, CONFIG.symbol_fallbacks)
        if symbol != CONFIG.symbol:
            log.info("Symbol: %s (was %s)", symbol, CONFIG.symbol)
        CONFIG.symbol = symbol
        client.ensure_symbol(symbol)
        bal = client.account_balance()
        log.info(
            "MT5 balance $%.2f (demo) | sizing risk as $%.0f account",
            bal,
            CONFIG.reference_balance,
        )
    except Exception as exc:
        log.error("%s", exc)
        sys.exit(1)

    try:
        while True:
            try:
                if CONFIG.use_session_filter and not in_trading_session():
                    if time.time() - last_status_at > 60:
                        log.info("Outside session (UTC) — waiting")
                        last_status_at = time.time()
                    time.sleep(5)
                    continue

                if CONFIG.use_loss_pause and not risk.can_trade():
                    if time.time() - last_status_at > 60:
                        log.warning("Paused | %ss left", risk.pause_remaining())
                        last_status_at = time.time()
                    time.sleep(2)
                    continue

                positions = client.positions(CONFIG.symbol)
                open_count = len(positions)

                close_reason = None
                if open_count:
                    close_reason = _scan_basket_exits(client, recorder, risk, positions)
                if close_reason:
                    last_basket_close_at = time.time()
                    if close_reason == "basket_stop" and positions:
                        last_sl_close_at = time.time()
                        last_sl_side = "buy" if positions[0].type == mt5.ORDER_TYPE_BUY else "sell"
                    positions = client.positions(CONFIG.symbol)
                    open_count = len(positions)

                now = time.time()
                flat = open_count == 0
                scans += 1
                same_side_sl = False
                if flat:
                    setup_probe = analyze(CONFIG.symbol)
                    if setup_probe.side and last_sl_side == setup_probe.side:
                        same_side_sl = (now - last_sl_close_at) < CONFIG.post_sl_cooldown_seconds
                warmup_ok = scans > CONFIG.startup_warmup_scans
                cooldown_ok = (
                    warmup_ok
                    and not same_side_sl
                    and now - last_entry_at >= CONFIG.entry_cooldown_seconds
                    and now - last_basket_close_at >= CONFIG.post_basket_cooldown_seconds
                )

                if flat and cooldown_ok:
                    setup = analyze(CONFIG.symbol)
                    if setup.ok and risk.expectancy_ok():
                        plan = _compute_plan(client, setup, risk)
                        opened = _open_basket(
                            client, recorder, setup, plan, CONFIG.basket_size
                        )
                        if opened >= CONFIG.basket_size:
                            last_entry_at = now
                    elif time.time() - last_status_at >= 10:
                        ev_block = setup.ok and not risk.expectancy_ok()
                        s = risk.stats
                        log.info(
                            "SCAN | score=%s | side=%s | ADX=%.0f Z=%.2f | "
                            "EV=$%.2f PF=%.2f | %s%s | daily=$%.2f",
                            setup.score,
                            setup.side or "—",
                            setup.adx,
                            setup.z_score,
                            s.expectancy,
                            s.pf if s.pf != float("inf") else 99.9,
                            ", ".join(setup.reasons[:4]) or "waiting",
                            " | EV_GATE" if ev_block else "",
                            client.today_closed_profit(CONFIG.symbol),
                        )
                        last_status_at = time.time()
                elif not flat and open_count < CONFIG.basket_size:
                    age = _oldest_age(positions)
                    if age >= CONFIG.basket_fill_timeout_seconds:
                        log.warning(
                            "Stuck partial basket %s/%s — closing all",
                            open_count,
                            CONFIG.basket_size,
                        )
                        _close_basket(client, recorder, risk, positions, "partial_abort")
                        last_basket_close_at = time.time()

                if time.time() - last_status_at >= 10:
                    positions = client.positions(CONFIG.symbol)
                    open_count = len(positions)
                    plan = _plan_targets()
                    basket_pnl = _basket_pnl(client, positions) if positions else 0.0
                    daily = client.today_closed_profit(CONFIG.symbol)
                    if open_count:
                        log.info(
                            "HOLD | open=%s/%s | P/L=$%.2f | "
                            "TP=+$%.2f SL=-$%.2f | daily=$%.2f",
                            open_count,
                            CONFIG.basket_size,
                            basket_pnl,
                            plan.profit_target,
                            plan.stop_target,
                            daily,
                        )
                    elif not cooldown_ok:
                        wait = max(
                            CONFIG.entry_cooldown_seconds - (now - last_entry_at),
                            CONFIG.post_basket_cooldown_seconds
                            - (now - last_basket_close_at),
                        )
                        log.info("COOLDOWN | %.0fs left | daily=$%.2f", max(0, wait), daily)
                    last_status_at = time.time()

            except Exception as exc:
                log.exception("Loop error: %s", exc)

            time.sleep(CONFIG.poll_seconds)
    except KeyboardInterrupt:
        log.info("Stopped.")
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
