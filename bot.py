"""
Exness MT5 basket scalp bot.

Opens 10 tiny trades at once → when combined profit hits target,
closes ALL → opens a fresh batch of 10. Repeat.

Run on Windows AWS with Exness MT5 terminal open + demo account.
"""

from __future__ import annotations

import logging
import os
import sys
import time

from config import CONFIG
from mt5_client import MT5Client
from recorder import Recorder
from risk import RiskState
from session import in_trading_session
from strategy import entry_signal, signal_snapshot
from trend import trend_direction


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


def _position_age_seconds(pos) -> float:
    return max(0.0, time.time() - pos.time)


def _basket_pnl(client: MT5Client, positions) -> float:
    return sum(client.position_profit(p.ticket) for p in positions)


def _oldest_age(positions) -> float:
    if not positions:
        return 0.0
    return max(_position_age_seconds(p) for p in positions)


def _close_basket(
    client: MT5Client,
    recorder: Recorder,
    risk: RiskState,
    positions,
    reason: str,
) -> None:
    total = _basket_pnl(client, positions)
    tickets = [p.ticket for p in positions]
    closed = client.close_many(tickets)
    risk.record_close(total)
    recorder.log(
        "close_basket",
        reason=reason,
        tickets=closed,
        count=closed,
        total_profit=round(total, 4),
    )
    log.info("BASKET CLOSE (%s) | %s/%s tickets | total P/L $%.2f", reason, closed, len(tickets), total)


def _scan_basket_exits(
    client: MT5Client,
    recorder: Recorder,
    risk: RiskState,
    positions,
) -> bool:
    if not positions:
        return False

    total = _basket_pnl(client, positions)
    age = _oldest_age(positions)

    if total >= CONFIG.basket_min_profit:
        _close_basket(client, recorder, risk, positions, "profit")
        return True

    if total <= -abs(CONFIG.basket_max_loss):
        _close_basket(client, recorder, risk, positions, "basket_stop")
        return True

    if CONFIG.max_hold_seconds and age >= CONFIG.max_hold_seconds:
        _close_basket(client, recorder, risk, positions, "timeout")
        return True

    return False


def _open_basket(
    client: MT5Client,
    recorder: Recorder,
    trend_side: str,
    trend_strength: float,
    need: int,
) -> int:
    spread = client.spread_points(CONFIG.symbol)
    if spread > CONFIG.max_spread_points:
        log.info("Skip basket | spread=%s pts (max %s)", spread, CONFIG.max_spread_points)
        return 0

    rates = client.rates_m1(CONFIG.symbol)
    side = entry_signal(rates, trend_side, trend_strength)
    if side is None:
        return 0

    opened = 0
    for i in range(need):
        ticket = client.open_market(
            CONFIG.symbol,
            side,
            CONFIG.lot_size,
            sl_points=CONFIG.stop_loss_points,
            comment=f"basket{i + 1}",
        )
        if ticket:
            opened += 1
            recorder.log(
                "open",
                ticket=ticket,
                side=side,
                lot=CONFIG.lot_size,
                trend=trend_side,
                basket_slot=i + 1,
            )
        if i < need - 1:
            time.sleep(CONFIG.batch_open_delay)
    if opened:
        log.info("BASKET OPEN | %s × %s %s | trend=%s", opened, CONFIG.lot_size, side.upper(), trend_side)
    return opened


def validate_config() -> None:
    if not CONFIG.login or not CONFIG.password or not CONFIG.server:
        raise ValueError(
            "Set MT5_LOGIN, MT5_PASSWORD, MT5_SERVER in .env "
            "(copy from Exness Personal Area → My accounts)."
        )
    if CONFIG.basket_size < 1:
        raise ValueError("MT5_BASKET_SIZE must be at least 1")


def main() -> None:
    validate_config()
    client = MT5Client()
    recorder = Recorder()
    risk = RiskState()
    last_batch_at = 0.0
    last_status_at = 0.0

    log.info("=" * 60)
    log.info(
        "Exness basket scalp | %s | lot=%.2f | batch=%s | "
        "close all at +$%.2f | demo=%s",
        CONFIG.symbol,
        CONFIG.lot_size,
        CONFIG.basket_size,
        CONFIG.basket_min_profit,
        CONFIG.demo_only,
    )
    log.info("=" * 60)

    try:
        client.connect()
        symbol = client.resolve_symbol(CONFIG.symbol, CONFIG.symbol_fallbacks)
        if symbol != CONFIG.symbol:
            log.info("Using symbol %s (configured %s)", symbol, CONFIG.symbol)
        CONFIG.symbol = symbol
        client.ensure_symbol(symbol)
    except Exception as exc:
        log.error("%s", exc)
        sys.exit(1)

    try:
        while True:
            try:
                if not in_trading_session():
                    if time.time() - last_status_at > 60:
                        log.info("Outside trading session (UTC) — waiting…")
                        last_status_at = time.time()
                    time.sleep(5)
                    continue

                if not risk.can_trade():
                    if time.time() - last_status_at > 60:
                        log.warning(
                            "Paused after losses | %ss left",
                            risk.pause_remaining(),
                        )
                        last_status_at = time.time()
                    time.sleep(2)
                    continue

                daily_pnl = client.today_closed_profit(CONFIG.symbol)
                if daily_pnl <= -abs(CONFIG.max_daily_loss):
                    log.warning("Daily loss limit (%.2f) — no new batches today.", daily_pnl)
                    time.sleep(10)
                    continue

                trend_side, strength = trend_direction(CONFIG.symbol)
                positions = client.positions(CONFIG.symbol)
                open_count = len(positions)

                if open_count and _scan_basket_exits(client, recorder, risk, positions):
                    positions = client.positions(CONFIG.symbol)
                    open_count = len(positions)
                    last_batch_at = time.time()

                now = time.time()
                flat = open_count == 0
                partial = 0 < open_count < CONFIG.basket_size

                # Recover incomplete basket (some orders failed)
                if partial and now - last_batch_at >= CONFIG.entry_cooldown_seconds:
                    need = CONFIG.basket_size - open_count
                    if trend_side:
                        _open_basket(client, recorder, trend_side, strength or 0.0, need)
                    open_count = len(client.positions(CONFIG.symbol))

                # New full basket when flat
                if (
                    flat
                    and trend_side is not None
                    and now - last_batch_at >= CONFIG.entry_cooldown_seconds
                ):
                    opened = _open_basket(
                        client, recorder, trend_side, strength or 0.0, CONFIG.basket_size
                    )
                    if opened:
                        last_batch_at = now
                    open_count = len(client.positions(CONFIG.symbol))

                if time.time() - last_status_at >= 8:
                    basket_pnl = _basket_pnl(client, positions) if positions else 0.0
                    extra = ""
                    if flat and trend_side and open_count == 0:
                        rates = client.rates_m1(CONFIG.symbol)
                        snap = signal_snapshot(rates, trend_side)
                        extra = (
                            f" | wait: need {trend_side} candle (last={snap['candle']}, RSI={snap['rsi']})"
                        )
                    log.info(
                        "trend=%s (%.0f%%) | open=%s/%s | basket P/L=$%.2f | "
                        "target=+$%.2f | daily=$%.2f | W/L=%s/%s%s",
                        trend_side or "flat",
                        (strength or 0) * 100,
                        open_count,
                        CONFIG.basket_size,
                        basket_pnl,
                        CONFIG.basket_min_profit,
                        daily_pnl,
                        risk.wins,
                        risk.losses,
                        extra,
                    )
                    last_status_at = time.time()

            except Exception as exc:
                log.exception("Loop error: %s", exc)

            time.sleep(CONFIG.poll_seconds)
    except KeyboardInterrupt:
        log.info("Stopped by user.")
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
