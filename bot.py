"""
Exness MT5 smart basket bot.

1. Reads M15 + M5 + M1 charts (confluence score)
2. Opens basket only on strong setup (avoids bounce traps)
3. Closes ALL positions together on combined basket profit/loss
4. Sized for ~$30 reference account on demo
"""

from __future__ import annotations

import logging
import os
import sys
import time

from analysis import Setup, analyze
from config import CONFIG
from mt5_client import MT5Client
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
    log.info(
        "BASKET CLOSE (%s) | %s/%s tickets | combined P/L $%.2f",
        reason,
        closed,
        len(tickets),
        total,
    )


def _scan_basket_exits(
    client: MT5Client,
    recorder: Recorder,
    risk: RiskState,
    positions,
) -> bool:
    """Exit on combined basket P/L only — never single tickets."""
    if not positions:
        return False

    total = _basket_pnl(client, positions)
    age = _oldest_age(positions)
    n = len(positions)

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
    setup: Setup,
    need: int,
) -> int:
    if not setup.ok or not setup.side:
        return 0

    spread = client.spread_points(CONFIG.symbol)
    if spread > CONFIG.max_spread_points:
        log.info("Skip | spread=%s (max %s)", spread, CONFIG.max_spread_points)
        return 0

    opened = 0
    for i in range(need):
        ticket = client.open_market(
            CONFIG.symbol,
            setup.side,
            CONFIG.lot_size,
            sl_points=CONFIG.stop_loss_points,
            comment=f"b{i + 1}",
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
                basket_slot=i + 1,
            )
        if i < need - 1:
            time.sleep(CONFIG.batch_open_delay)

    if opened:
        log.info(
            "BASKET OPEN | %s × %.2f %s | score=%s | %s",
            opened,
            CONFIG.lot_size,
            setup.side.upper(),
            setup.score,
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
    last_batch_at = 0.0
    last_status_at = 0.0
    last_setup: Setup | None = None

    log.info("=" * 60)
    log.info(
        "Smart basket bot | %s | lot=%.2f | x%s | ref balance $%.0f",
        CONFIG.symbol,
        CONFIG.lot_size,
        CONFIG.basket_size,
        CONFIG.reference_balance,
    )
    log.info(
        "Close ALL when basket +$%.2f or stop -$%.2f | min score %s",
        CONFIG.basket_min_profit,
        CONFIG.basket_max_loss,
        CONFIG.min_confluence_score,
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

                setup = analyze(CONFIG.symbol)
                last_setup = setup

                positions = client.positions(CONFIG.symbol)
                open_count = len(positions)

                if open_count and _scan_basket_exits(client, recorder, risk, positions):
                    positions = client.positions(CONFIG.symbol)
                    open_count = len(positions)
                    last_batch_at = time.time()

                now = time.time()
                flat = open_count == 0
                partial = 0 < open_count < CONFIG.basket_size

                if partial and setup.ok and now - last_batch_at >= CONFIG.entry_cooldown_seconds:
                    _open_basket(client, recorder, setup, CONFIG.basket_size - open_count)
                    open_count = len(client.positions(CONFIG.symbol))

                if (
                    flat
                    and setup.ok
                    and now - last_batch_at >= CONFIG.entry_cooldown_seconds
                ):
                    opened = _open_basket(client, recorder, setup, CONFIG.basket_size)
                    if opened:
                        last_batch_at = now
                    open_count = len(client.positions(CONFIG.symbol))

                if time.time() - last_status_at >= 10:
                    basket_pnl = _basket_pnl(client, positions) if positions else 0.0
                    daily = client.today_closed_profit(CONFIG.symbol)
                    if open_count:
                        log.info(
                            "HOLD basket | open=%s/%s | combined P/L=$%.2f | "
                            "target=+$%.2f stop=-$%.2f | daily=$%.2f",
                            open_count,
                            CONFIG.basket_size,
                            basket_pnl,
                            CONFIG.basket_min_profit,
                            CONFIG.basket_max_loss,
                            daily,
                        )
                    else:
                        log.info(
                            "SCAN | score=%s | side=%s | RSI=%.0f | %s | daily=$%.2f",
                            setup.score,
                            setup.side or "—",
                            setup.rsi_m1,
                            ", ".join(setup.reasons[:5]) or "waiting",
                            daily,
                        )
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
