"""
Exness MT5 smart basket bot.

Execution rules (fixes partial-close / orphan bugs):
- One basket at a time — fully flat before new entries
- All N positions must open before basket P/L exit logic runs
- Close ALL with retries; no partial basket management
- Long cooldown after any basket close
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


def _scan_basket_exits(
    client: MT5Client,
    recorder: Recorder,
    risk: RiskState,
    positions,
) -> bool:
    if not positions:
        return False

    n = len(positions)
    if n < CONFIG.basket_size:
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
    deadline = time.time() + CONFIG.basket_fill_timeout_seconds
    slot = 0

    while opened < need and time.time() < deadline:
        slot += 1
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
                basket_slot=opened,
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
        log.info(
            "BASKET OPEN | %s × %.2f %s | score=%s | %s",
            opened,
            CONFIG.lot_size,
            setup.side.upper(),
            setup.score,
            ", ".join(setup.reasons[:5]),
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
    last_status_at = 0.0

    log.info("=" * 60)
    log.info(
        "Smart basket bot v2 | %s | lot=%.2f | x%s | ref balance $%.0f",
        CONFIG.symbol,
        CONFIG.lot_size,
        CONFIG.basket_size,
        CONFIG.reference_balance,
    )
    log.info(
        "Close ALL when basket +$%.2f or stop -$%.2f | min score %s (fallback %s)",
        CONFIG.basket_min_profit,
        CONFIG.basket_max_loss,
        CONFIG.min_confluence_score,
        CONFIG.min_score_m5_fallback,
    )
    log.info(
        "Cooldown %ss entry / %ss after close | no broker SL=%s",
        CONFIG.entry_cooldown_seconds,
        CONFIG.post_basket_cooldown_seconds,
        CONFIG.stop_loss_points == 0,
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

                if open_count and _scan_basket_exits(client, recorder, risk, positions):
                    last_basket_close_at = time.time()
                    positions = client.positions(CONFIG.symbol)
                    open_count = len(positions)

                now = time.time()
                flat = open_count == 0
                cooldown_ok = (
                    now - last_entry_at >= CONFIG.entry_cooldown_seconds
                    and now - last_basket_close_at >= CONFIG.post_basket_cooldown_seconds
                )

                if flat and cooldown_ok:
                    setup = analyze(CONFIG.symbol)
                    if setup.ok:
                        opened = _open_basket(client, recorder, setup, CONFIG.basket_size)
                        if opened >= CONFIG.basket_size:
                            last_entry_at = now
                    elif time.time() - last_status_at >= 10:
                        log.info(
                            "SCAN | score=%s | side=%s | RSI=%.0f | %s | daily=$%.2f",
                            setup.score,
                            setup.side or "—",
                            setup.rsi_m1,
                            ", ".join(setup.reasons[:5]) or "waiting",
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
                    elif not cooldown_ok:
                        wait = max(
                            CONFIG.entry_cooldown_seconds - (now - last_entry_at),
                            CONFIG.post_basket_cooldown_seconds
                            - (now - last_basket_close_at),
                        )
                        log.info(
                            "COOLDOWN | %.0fs left | daily=$%.2f",
                            max(0, wait),
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
