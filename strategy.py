"""
Trend-aligned M1 pullback entries for Exness micro-scalping.

Only trades WITH the M15 trend — no random basket filling.
"""

from __future__ import annotations

import numpy as np

from config import CONFIG


def _rsi(closes: np.ndarray, period: int) -> float:
    if len(closes) < period + 2:
        return 50.0
    delta = np.diff(closes)
    gains = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)
    avg_gain = gains[-period:].mean()
    avg_loss = losses[-period:].mean()
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def _ema(values: np.ndarray, period: int) -> float:
    if len(values) < period:
        return float(values[-1])
    alpha = 2.0 / (period + 1.0)
    ema = float(values[0])
    for v in values[1:]:
        ema = alpha * float(v) + (1.0 - alpha) * ema
    return ema


def entry_signal(rates_m1, trend_side: str) -> str | None:
    """
    M1 pullback in trend direction.
    trend_side must be 'buy' or 'sell' from M15 filter.
    """
    closes = np.array([r["close"] for r in rates_m1], dtype=float)
    need = max(CONFIG.rsi_period, CONFIG.ema_period) + 5
    if len(closes) < need:
        return None

    rsi_now = _rsi(closes, CONFIG.rsi_period)
    rsi_prev = _rsi(closes[:-1], CONFIG.rsi_period)
    ema = _ema(closes[-(CONFIG.ema_period + 30) :], CONFIG.ema_period)
    price = float(closes[-1])
    last = rates_m1[-1]

    if trend_side == "buy":
        # Pullback: RSI dipped, turning up, still above/near fast EMA
        if rsi_prev < CONFIG.rsi_buy and rsi_now > rsi_prev and price >= ema * 0.9995:
            if last["close"] > last["open"]:  # bullish confirmation candle
                return "buy"
    elif trend_side == "sell":
        if rsi_prev > CONFIG.rsi_sell and rsi_now < rsi_prev and price <= ema * 1.0005:
            if last["close"] < last["open"]:
                return "sell"
    return None
