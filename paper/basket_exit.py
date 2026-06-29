"""Basket exit logic — tick vs bar-range (M5 hi/lo since entry, matches backtest)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from backtest.engine import _pnl_at_price
from backtest.pairs import PairSpec
from config import CONFIG


@dataclass
class ExitDecision:
    reason: str
    pnl: float
    mark_pnl: float
    best_pnl: float
    worst_pnl: float


def _utc_naive(ts: datetime) -> datetime:
    if ts.tzinfo is not None:
        return ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts


def _floor_m5(ts: datetime) -> datetime:
    ts = _utc_naive(ts)
    return ts.replace(minute=(ts.minute // 5) * 5, second=0, microsecond=0)


def price_extremes_since_entry(
    m5: pd.DataFrame | None,
    entry_time: datetime,
    current_price: float,
) -> tuple[float, float]:
    """High/low since basket open using M5 bar range + current tick."""
    hi = lo = current_price
    if m5 is None or m5.empty:
        return hi, lo

    floor = _floor_m5(entry_time)
    idx = m5.index
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    subset = m5.loc[idx >= floor]
    if len(subset):
        hi = max(float(subset["high"].max()), current_price)
        lo = min(float(subset["low"].min()), current_price)
    return hi, lo


def basket_pnl_range(
    spec: PairSpec,
    side: str,
    entry: float,
    high: float,
    low: float,
    current: float,
    basket_size: int,
    spread: float,
) -> tuple[float, float, float]:
    """Return (mark, best, worst) PnL for the basket."""
    mark = _pnl_at_price(spec, side, entry, current, basket_size, spread)
    if side == "buy":
        best = _pnl_at_price(spec, side, entry, high, basket_size, spread)
        worst = _pnl_at_price(spec, side, entry, low, basket_size, spread)
    else:
        best = _pnl_at_price(spec, side, entry, low, basket_size, spread)
        worst = _pnl_at_price(spec, side, entry, high, basket_size, spread)
    return mark, best, worst


def check_basket_exit(
    spec: PairSpec,
    side: str,
    entry: float,
    current: float,
    *,
    m5: pd.DataFrame | None,
    entry_time: datetime,
    tp: float,
    sl: float,
    spread: float,
    basket_size: int,
    held_sec: int,
    exit_mode: str | None = None,
    sl_delay_sec: int | None = None,
) -> ExitDecision | None:
    """
    Decide basket exit. bar_range uses M5 high/low since entry (TP checked before SL).
    tick uses last price only (legacy paper behaviour).
    """
    mode = (exit_mode or CONFIG.basket_exit_mode).lower()
    delay = CONFIG.sl_delay_seconds if sl_delay_sec is None else sl_delay_sec

    if mode == "bar_range":
        hi, lo = price_extremes_since_entry(m5, entry_time, current)
    else:
        hi = lo = current

    mark, best, worst = basket_pnl_range(
        spec, side, entry, hi, lo, current, basket_size, spread,
    )

    if mode == "tick":
        best = worst = mark

    if best >= tp:
        return ExitDecision("profit", tp, mark, best, worst)
    if held_sec >= delay and worst <= -sl:
        return ExitDecision("basket_stop", -sl, mark, best, worst)
    if held_sec >= CONFIG.max_hold_seconds:
        return ExitDecision("timeout", mark, mark, best, worst)
    return None
