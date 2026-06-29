"""
Quantitative primitives for signal quality, volatility, and position math.

Concepts used (standard in algo trading):
- ATR: volatility-normalized risk
- ADX: trend strength (Wilder)
- Z-score: how extended price is vs rolling mean (Bollinger basis)
- Linear regression slope: trend momentum
- Kelly criterion: f* = (p*b - q) / b  (half-Kelly in practice)
- Expected value: EV = p*W - (1-p)*L
- Profit factor: gross wins / gross losses
"""

from __future__ import annotations

import math

import numpy as np


def ema_series(values: np.ndarray, period: int) -> np.ndarray:
    if len(values) == 0:
        return np.array([], dtype=float)
    alpha = 2.0 / (period + 1.0)
    out = np.empty(len(values), dtype=float)
    out[0] = float(values[0])
    for i in range(1, len(values)):
        out[i] = alpha * float(values[i]) + (1.0 - alpha) * out[i - 1]
    return out


def ema_last(values: np.ndarray, period: int) -> float:
    if len(values) == 0:
        return 0.0
    return float(ema_series(values, period)[-1])


def rsi(closes: np.ndarray, period: int) -> float:
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


def true_range_series(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray
) -> np.ndarray:
    tr = np.empty(len(closes), dtype=float)
    tr[0] = highs[0] - lows[0]
    for i in range(1, len(closes)):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    return tr


def atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> float:
    tr = true_range_series(highs, lows, closes)
    if len(tr) < period:
        return float(tr[-1]) if len(tr) else 0.0
    return float(tr[-period:].mean())


def atr_series(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int
) -> np.ndarray:
    tr = true_range_series(highs, lows, closes)
    out = np.empty(len(tr), dtype=float)
    for i in range(len(tr)):
        start = max(0, i - period + 1)
        out[i] = tr[start : i + 1].mean()
    return out


def adx(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> float:
    """Average Directional Index — trend strength 0..100."""
    n = len(closes)
    if n < period + 2:
        return 0.0

    up = highs[1:] - highs[:-1]
    down = lows[:-1] - lows[1:]
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)

    tr = true_range_series(highs, lows, closes)[1:]
    atr_w = ema_series(tr, period)
    plus_di = 100.0 * ema_series(plus_dm, period) / np.maximum(atr_w, 1e-12)
    minus_di = 100.0 * ema_series(minus_dm, period) / np.maximum(atr_w, 1e-12)
    dx = 100.0 * np.abs(plus_di - minus_di) / np.maximum(plus_di + minus_di, 1e-12)
    adx_line = ema_series(dx, period)
    return float(adx_line[-1])


def bollinger_zscore(closes: np.ndarray, period: int = 20, std_mult: float = 2.0) -> float:
    """Z-score of last close vs rolling mean/std (Bollinger basis)."""
    if len(closes) < period:
        return 0.0
    window = closes[-period:]
    mean = float(window.mean())
    std = float(window.std(ddof=1))
    if std < 1e-12:
        return 0.0
    return (float(closes[-1]) - mean) / std


def regression_slope(values: np.ndarray, period: int = 20) -> float:
    """OLS slope of last `period` closes (normalized per bar)."""
    if len(values) < period:
        period = len(values)
    if period < 3:
        return 0.0
    y = values[-period:].astype(float)
    x = np.arange(period, dtype=float)
    x_mean = x.mean()
    y_mean = y.mean()
    num = ((x - x_mean) * (y - y_mean)).sum()
    den = ((x - x_mean) ** 2).sum()
    if den == 0:
        return 0.0
    return float(num / den)


def volatility_ratio(current_atr: float, baseline_atr: float) -> float:
    if baseline_atr <= 0:
        return 1.0
    return current_atr / baseline_atr


def kelly_fraction(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    fraction: float = 0.5,
) -> float:
    """
    Half-Kelly by default: f* = (p*b - q) / b, then × fraction.
    Returns 0 if no edge or invalid inputs.
    """
    if win_rate <= 0 or win_rate >= 1 or avg_loss <= 0 or avg_win <= 0:
        return 0.0
    p = win_rate
    q = 1.0 - p
    b = avg_win / avg_loss
    raw = (p * b - q) / b
    if raw <= 0:
        return 0.0
    return min(1.0, raw * fraction)


def effective_sl_atr_mult(vol_ratio: float) -> float:
    from config import CONFIG

    mult = CONFIG.atr_sl_mult
    if vol_ratio >= CONFIG.atr_sl_vol_threshold:
        mult *= CONFIG.atr_sl_vol_boost
    return mult


def expected_value(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """EV per basket in account currency units."""
    if win_rate <= 0:
        return -avg_loss
    p = win_rate
    return p * avg_win - (1.0 - p) * avg_loss


def profit_factor(gross_wins: float, gross_losses: float) -> float:
    if gross_losses <= 0:
        return float("inf") if gross_wins > 0 else 0.0
    return gross_wins / gross_losses


def atr_basket_targets(
    atr_price: float,
    point: float,
    money_per_point_per_lot: float,
    lot: float,
    basket_size: int,
    tp_atr_mult: float,
    sl_atr_mult: float,
    min_profit: float,
    min_loss: float,
    max_profit: float,
    max_loss: float,
) -> tuple[float, float, int]:
    """
    Convert ATR to dollar basket TP/SL using linear point value.
    Returns (profit_target, stop_target, atr_points).
    """
    if point <= 0 or atr_price <= 0:
        return min_profit, min_loss, 0

    atr_points = max(1, int(round(atr_price / point)))
    unit = money_per_point_per_lot * lot * basket_size
    if unit <= 0:
        return min_profit, min_loss, atr_points

    profit = atr_points * tp_atr_mult * unit
    stop = atr_points * sl_atr_mult * unit
    profit = max(min_profit, min(profit, max_profit))
    stop = max(min_loss, min(stop, max_loss))
    return round(profit, 2), round(stop, 2), atr_points
