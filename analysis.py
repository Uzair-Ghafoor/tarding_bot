"""
Multi-timeframe chart analysis — M15 trend, M5 fallback, M1 timing.
"""

from __future__ import annotations

from dataclasses import dataclass

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


def _rates(symbol: str, tf: int, count: int):
    r = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    return r if r is not None and len(r) else None


def _m15_trend(c15: np.ndarray, price: float) -> tuple[str | None, int, list[str]]:
    reasons: list[str] = []
    ema_f = _ema(c15, CONFIG.trend_ema_fast)
    ema_s = _ema(c15, CONFIG.trend_ema_slow)
    score = 0
    side: str | None = None

    if ema_f > ema_s and price >= ema_s:
        side = "buy"
        score += 25
        reasons.append("M15_up")
        if price >= ema_f:
            score += 10
            reasons.append("M15_above_fast")
        if float(c15[-1]) > float(c15[-5]):
            score += 10
            reasons.append("M15_higher_close")
    elif ema_f < ema_s and price <= ema_s:
        side = "sell"
        score += 25
        reasons.append("M15_down")
        if price <= ema_f:
            score += 10
            reasons.append("M15_below_fast")
        if float(c15[-1]) < float(c15[-5]):
            score += 10
            reasons.append("M15_lower_close")

    return side, score, reasons


def _m5_trend(c5: np.ndarray, price: float, ema5: float) -> tuple[str | None, int, list[str]]:
    """Fallback when M15 is choppy (common on gold)."""
    reasons: list[str] = []
    score = 0
    side: str | None = None
    if len(c5) < 8:
        return None, 0, reasons

    up_move = float(c5[-1]) > float(c5[-6]) and float(c5[-1]) >= float(c5[-2])
    down_move = float(c5[-1]) < float(c5[-6]) and float(c5[-1]) <= float(c5[-2])

    if price >= ema5 and up_move:
        side = "buy"
        score += 20
        reasons.append("M5_up_fallback")
    elif price <= ema5 and down_move:
        side = "sell"
        score += 20
        reasons.append("M5_down_fallback")

    return side, score, reasons


@dataclass
class Setup:
    side: str | None
    score: int
    reasons: list[str]
    rsi_m1: float
    m15_trend: str | None
    m5_momentum: str | None

    @property
    def ok(self) -> bool:
        return self.side is not None and self.score >= CONFIG.min_confluence_score


def analyze(symbol: str) -> Setup:
    m15 = _rates(symbol, mt5.TIMEFRAME_M15, 80)
    m5 = _rates(symbol, mt5.TIMEFRAME_M5, 60)
    m1 = _rates(symbol, mt5.TIMEFRAME_M1, 80)
    if m15 is None or m5 is None or m1 is None:
        return Setup(None, 0, ["no_chart_data"], 50.0, None, None)

    c15 = np.array([r["close"] for r in m15], dtype=float)
    c5 = np.array([r["close"] for r in m5], dtype=float)
    c1 = np.array([r["close"] for r in m1], dtype=float)

    ema5 = _ema(c5, CONFIG.m5_ema_period)
    ema1 = _ema(c1, CONFIG.ema_period)
    price = float(c1[-1])
    rsi1 = _rsi(c1, CONFIG.rsi_period)
    last1 = m1[-1]
    bull_candle = last1["close"] > last1["open"]
    bear_candle = last1["close"] < last1["open"]

    score = 0
    reasons: list[str] = []
    m15_side, s15, r15 = _m15_trend(c15, price)
    score += s15
    reasons.extend(r15)

    side = m15_side
    if not side and CONFIG.allow_m5_fallback:
        fb_side, s5fb, r5fb = _m5_trend(c5, price, ema5)
        if fb_side:
            side = fb_side
            score += s5fb
            reasons.extend(r5fb)
        else:
            reasons.append("M15_no_trend")
            return Setup(None, score, reasons, rsi1, m15_side, None)

    m5_momentum: str | None = None
    if price >= ema5 and float(c5[-1]) >= float(c5[-3]):
        m5_momentum = "buy"
    elif price <= ema5 and float(c5[-1]) <= float(c5[-3]):
        m5_momentum = "sell"

    if m5_momentum == side:
        score += 20
        reasons.append(f"M5_agrees_{side}")
    elif m5_momentum and m5_momentum != side:
        reasons.append(f"M5_conflict({m5_momentum})")
        score -= 15

    if side == "sell":
        if rsi1 > CONFIG.rsi_no_sell_above:
            reasons.append(f"RSI_high({rsi1:.0f})")
            score -= 35
        elif rsi1 <= CONFIG.rsi_sell:
            score += 10
            reasons.append("RSI_ok_sell")
        if bear_candle and price <= ema1 * 1.001:
            score += 15
            reasons.append("M1_red")
        elif not bear_candle:
            reasons.append("need_red_candle")
            score -= 10
    elif side == "buy":
        if rsi1 < CONFIG.rsi_no_buy_below:
            reasons.append(f"RSI_low({rsi1:.0f})")
            score -= 35
        elif rsi1 >= CONFIG.rsi_buy:
            score += 10
            reasons.append("RSI_ok_buy")
        if bull_candle and price >= ema1 * 0.999:
            score += 15
            reasons.append("M1_green")
        elif not bull_candle:
            reasons.append("need_green_candle")
            score -= 10

    score = max(0, min(100, score))
    if score < CONFIG.min_confluence_score:
        side = None

    return Setup(side, score, reasons, rsi1, m15_side, m5_momentum)
