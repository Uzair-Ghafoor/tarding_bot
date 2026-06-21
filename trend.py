"""Multi-timeframe trend filter for Exness MT5 scalping."""

from __future__ import annotations

import MetaTrader5 as mt5
import numpy as np

from config import CONFIG


def _ema(values: np.ndarray, period: int) -> float:
    if len(values) < period:
        return float(values[-1])
    alpha = 2.0 / (period + 1.0)
    ema = float(values[0])
    for v in values[1:]:
        ema = alpha * float(v) + (1.0 - alpha) * ema
    return ema


def trend_direction(symbol: str) -> tuple[str | None, float]:
    """
    Return ('buy'|'sell'|None, strength 0..1) from M15 EMA stack.
    None = choppy / no clear trend — bot should not trade.
    """
    bars = max(CONFIG.trend_ema_slow, CONFIG.trend_ema_fast) + 20
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, bars)
    if rates is None or len(rates) < CONFIG.trend_ema_slow + 5:
        return None, 0.0

    closes = np.array([r["close"] for r in rates], dtype=float)
    fast = _ema(closes, CONFIG.trend_ema_fast)
    slow = _ema(closes, CONFIG.trend_ema_slow)
    price = float(closes[-1])

    if fast > slow and price >= fast:
        gap = (fast - slow) / slow if slow else 0.0
        strength = min(1.0, abs(gap) / CONFIG.trend_min_gap_pct)
        if strength >= CONFIG.trend_min_strength:
            return "buy", strength
    if fast < slow and price <= fast:
        gap = (slow - fast) / slow if slow else 0.0
        strength = min(1.0, abs(gap) / CONFIG.trend_min_gap_pct)
        if strength >= CONFIG.trend_min_strength:
            return "sell", strength
    return None, 0.0
