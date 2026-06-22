"""
Multi-timeframe chart analysis — only trade high-confluence setups.

Reads M15 (trend), M5 (momentum), M1 (timing + RSI filter).
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
    """
    Score 0–100. Trade only when score >= min_confluence_score.
    """
    reasons: list[str] = []
    score = 0
    side: str | None = None

    m15 = _rates(symbol, mt5.TIMEFRAME_M15, 80)
    m5 = _rates(symbol, mt5.TIMEFRAME_M5, 60)
    m1 = _rates(symbol, mt5.TIMEFRAME_M1, 80)
    if m15 is None or m5 is None or m1 is None:
        return Setup(None, 0, ["no_chart_data"], 50.0, None, None)

    c15 = np.array([r["close"] for r in m15], dtype=float)
    c5 = np.array([r["close"] for r in m5], dtype=float)
    c1 = np.array([r["close"] for r in m1], dtype=float)

    ema15_f = _ema(c15, CONFIG.trend_ema_fast)
    ema15_s = _ema(c15, CONFIG.trend_ema_slow)
    ema5 = _ema(c5, CONFIG.m5_ema_period)
    ema1 = _ema(c1, CONFIG.ema_period)
    price = float(c1[-1])
    rsi1 = _rsi(c1, CONFIG.rsi_period)
    last1 = m1[-1]
    bull_candle = last1["close"] > last1["open"]
    bear_candle = last1["close"] < last1["open"]

    # --- M15 trend (40 pts) ---
    m15_trend: str | None = None
    if ema15_f > ema15_s and price >= ema15_f:
        m15_trend = "buy"
        score += 25
        reasons.append("M15_uptrend")
        if float(c15[-1]) > float(c15[-5]):
            score += 15
            reasons.append("M15_higher_close")
    elif ema15_f < ema15_s and price <= ema15_f:
        m15_trend = "sell"
        score += 25
        reasons.append("M15_downtrend")
        if float(c15[-1]) < float(c15[-5]):
            score += 15
            reasons.append("M15_lower_close")

    if not m15_trend:
        reasons.append("M15_no_trend")
        return Setup(None, score, reasons, rsi1, None, None)

    # --- M5 momentum must agree (25 pts) ---
    m5_momentum: str | None = None
    if price >= ema5 and float(c5[-1]) >= float(c5[-3]):
        m5_momentum = "buy"
    elif price <= ema5 and float(c5[-1]) <= float(c5[-3]):
        m5_momentum = "sell"

    if m5_momentum == m15_trend:
        score += 25
        reasons.append(f"M5_agrees_{m15_trend}")
    else:
        reasons.append(f"M5_conflict({m5_momentum})")
        score -= 20

    side = m15_trend

    # --- M1 RSI filter — avoid selling tops / buying bottoms (20 pts) ---
    if side == "sell":
        if rsi1 > CONFIG.rsi_no_sell_above:
            reasons.append(f"RSI_too_high({rsi1:.0f})")
            score -= 40
        elif rsi1 < CONFIG.rsi_sell:
            score += 10
            reasons.append("RSI_sell_zone")
        if bear_candle and price <= ema1:
            score += 10
            reasons.append("M1_bear_candle")
        elif not bear_candle:
            reasons.append("M1_need_red_candle")
            score -= 15
    elif side == "buy":
        if rsi1 < CONFIG.rsi_no_buy_below:
            reasons.append(f"RSI_too_low({rsi1:.0f})")
            score -= 40
        elif rsi1 > CONFIG.rsi_buy:
            score += 10
            reasons.append("RSI_buy_zone")
        if bull_candle and price >= ema1:
            score += 10
            reasons.append("M1_bull_candle")
        elif not bull_candle:
            reasons.append("M1_need_green_candle")
            score -= 15

    score = max(0, min(100, score))
    if score < CONFIG.min_confluence_score:
        side = None

    return Setup(side, score, reasons, rsi1, m15_trend, m5_momentum)
