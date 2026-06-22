"""
Trend-aligned M1 entries for Exness basket scalping.
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


def entry_signal(
    rates_m1,
    trend_side: str,
    trend_strength: float = 0.0,
) -> str | None:
    """
    Return 'buy' or 'sell' in trend direction.
    Strong trend (>=50%): M1 candle confirmation only.
    Weaker trend: RSI pullback + candle.
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
    bullish = last["close"] > last["open"]
    bearish = last["close"] < last["open"]

    # Strong M15 trend — don't wait for RSI pullback (RSI stays low in dumps)
    if trend_strength >= 0.5:
        if trend_side == "sell" and bearish and price <= ema * 1.001:
            return "sell"
        if trend_side == "buy" and bullish and price >= ema * 0.999:
            return "buy"

    if trend_side == "buy":
        if rsi_prev < CONFIG.rsi_buy and rsi_now > rsi_prev and price >= ema * 0.9995:
            if bullish:
                return "buy"
    elif trend_side == "sell":
        if rsi_prev > CONFIG.rsi_sell and rsi_now < rsi_prev and price <= ema * 1.0005:
            if bearish:
                return "sell"
    return None


def signal_snapshot(rates_m1, trend_side: str) -> dict:
    """Debug info for logs when waiting for entry."""
    closes = np.array([r["close"] for r in rates_m1], dtype=float)
    last = rates_m1[-1]
    ema = _ema(closes[-(CONFIG.ema_period + 30) :], CONFIG.ema_period) if len(closes) > CONFIG.ema_period else 0.0
    return {
        "rsi": round(_rsi(closes, CONFIG.rsi_period), 1),
        "ema": round(ema, 5),
        "close": round(float(closes[-1]), 5),
        "candle": "up" if last["close"] > last["open"] else "down" if last["close"] < last["open"] else "doji",
        "trend": trend_side,
    }
