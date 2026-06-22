"""
Multi-timeframe chart analysis — H1 bias, M15 trend, M5 entry, M1 timing.

Based on common XAUUSD scalping practice:
- H1 EMA for trend bias (only trade with higher-TF direction)
- M15 EMA stack for trend confirmation
- M5 pullback + confirmed candle close for entry
- RSI 40–65 (buy) / 35–60 (sell) — avoid overextended entries
- ATR spike filter to skip news volatility
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


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> float:
    if len(closes) < period + 2:
        return float(highs[-1] - lows[-1])
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    return float(np.mean(trs[-period:]))


def _rates(symbol: str, tf: int, count: int):
    r = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    return r if r is not None and len(r) else None


def _h1_bias(c1h: np.ndarray, price: float) -> tuple[str | None, list[str]]:
    ema = _ema(c1h, CONFIG.h1_ema_period)
    if price > ema * 1.0002:
        return "buy", ["H1_bullish"]
    if price < ema * 0.9998:
        return "sell", ["H1_bearish"]
    return None, ["H1_flat"]


def _m15_trend(c15: np.ndarray, price: float) -> tuple[str | None, int, list[str]]:
    reasons: list[str] = []
    ema_f = _ema(c15, CONFIG.trend_ema_fast)
    ema_s = _ema(c15, CONFIG.trend_ema_slow)
    score = 0
    side: str | None = None

    if ema_f > ema_s and price >= ema_s:
        side = "buy"
        score += 30
        reasons.append("M15_up")
        if price >= ema_f:
            score += 10
            reasons.append("M15_above_fast")
        if float(c15[-1]) > float(c15[-5]):
            score += 10
            reasons.append("M15_higher_close")
    elif ema_f < ema_s and price <= ema_s:
        side = "sell"
        score += 30
        reasons.append("M15_down")
        if price <= ema_f:
            score += 10
            reasons.append("M15_below_fast")
        if float(c15[-1]) < float(c15[-5]):
            score += 10
            reasons.append("M15_lower_close")

    return side, score, reasons


def _m5_entry(
    m5,
    c5: np.ndarray,
    price: float,
    side: str,
) -> tuple[bool, int, list[str]]:
    """Require completed M5 candle confirmation (not mid-candle)."""
    reasons: list[str] = []
    score = 0
    if len(m5) < 4:
        return False, 0, ["M5_short_history"]

    bar = m5[-2]  # last closed M5 bar
    ema_fast = _ema(c5, CONFIG.m5_ema_fast)
    ema_slow = _ema(c5, CONFIG.m5_ema_slow)
    bull = bar["close"] > bar["open"]
    bear = bar["close"] < bar["open"]

    if side == "buy":
        if ema_fast <= ema_slow:
            reasons.append("M5_ema_down")
            return False, 0, reasons
        if not bull:
            reasons.append("M5_need_green_close")
            return False, 0, reasons
        if bar["close"] < ema_fast:
            reasons.append("M5_below_fast_ema")
            return False, 0, reasons
        if price > ema_slow:
            score += 15
            reasons.append("M5_pullback_buy")
        else:
            reasons.append("M5_not_above_slow")
            return False, 0, reasons
    else:
        if ema_fast >= ema_slow:
            reasons.append("M5_ema_up")
            return False, 0, reasons
        if not bear:
            reasons.append("M5_need_red_close")
            return False, 0, reasons
        if bar["close"] > ema_fast:
            reasons.append("M5_above_fast_ema")
            return False, 0, reasons
        if price < ema_slow:
            score += 15
            reasons.append("M5_pullback_sell")
        else:
            reasons.append("M5_not_below_slow")
            return False, 0, reasons

    return True, score, reasons


def _rsi_ok(side: str, rsi: float) -> tuple[bool, int, list[str]]:
    reasons: list[str] = []
    if side == "buy":
        if rsi > CONFIG.rsi_buy_max:
            reasons.append(f"RSI_overbought({rsi:.0f})")
            return False, -40, reasons
        if rsi < CONFIG.rsi_buy_min:
            reasons.append(f"RSI_weak({rsi:.0f})")
            return False, -20, reasons
        score = 15 if CONFIG.rsi_buy_min <= rsi <= CONFIG.rsi_buy_max else 5
        reasons.append(f"RSI_ok({rsi:.0f})")
        return True, score, reasons

    if rsi < CONFIG.rsi_sell_min:
        reasons.append(f"RSI_oversold({rsi:.0f})")
        return False, -40, reasons
    if rsi > CONFIG.rsi_sell_max:
        reasons.append(f"RSI_weak({rsi:.0f})")
        return False, -20, reasons
    score = 15 if CONFIG.rsi_sell_min <= rsi <= CONFIG.rsi_sell_max else 5
    reasons.append(f"RSI_ok({rsi:.0f})")
    return True, score, reasons


@dataclass
class Setup:
    side: str | None
    score: int
    reasons: list[str]
    rsi_m1: float
    m15_trend: str | None
    m5_momentum: str | None
    used_fallback: bool = False

    @property
    def ok(self) -> bool:
        if self.side is None:
            return False
        min_score = (
            CONFIG.min_score_m5_fallback
            if self.used_fallback
            else CONFIG.min_confluence_score
        )
        return self.score >= min_score


def analyze(symbol: str) -> Setup:
    h1 = _rates(symbol, mt5.TIMEFRAME_H1, 80)
    m15 = _rates(symbol, mt5.TIMEFRAME_M15, 80)
    m5 = _rates(symbol, mt5.TIMEFRAME_M5, 80)
    m1 = _rates(symbol, mt5.TIMEFRAME_M1, 80)
    if h1 is None or m15 is None or m5 is None or m1 is None:
        return Setup(None, 0, ["no_chart_data"], 50.0, None, None)

    c1h = np.array([r["close"] for r in h1], dtype=float)
    c15 = np.array([r["close"] for r in m15], dtype=float)
    c5 = np.array([r["close"] for r in m5], dtype=float)
    h5 = np.array([r["high"] for r in m5], dtype=float)
    l5 = np.array([r["low"] for r in m5], dtype=float)
    c1 = np.array([r["close"] for r in m1], dtype=float)

    price = float(c1[-1])
    rsi1 = _rsi(c1, CONFIG.rsi_period)
    atr5 = _atr(h5, l5, c5, CONFIG.atr_period)
    atr_avg = _atr(h5, l5, c5, CONFIG.atr_period * 3)
    if atr_avg > 0 and atr5 > atr_avg * CONFIG.atr_spike_mult:
        return Setup(None, 0, [f"ATR_spike({atr5:.2f})"], rsi1, None, None)

    score = 0
    reasons: list[str] = []
    used_fallback = False

    h1_side, h1_reasons = _h1_bias(c1h, price)
    reasons.extend(h1_reasons)
    if h1_side is None and CONFIG.require_h1_bias:
        return Setup(None, score, reasons, rsi1, None, None)
    if h1_side:
        score += 15

    m15_side, s15, r15 = _m15_trend(c15, price)
    score += s15
    reasons.extend(r15)

    side = m15_side
    if not side and CONFIG.allow_m5_fallback:
        ema5 = _ema(c5, CONFIG.m5_ema_slow)
        up = float(c5[-1]) > float(c5[-6]) and price >= ema5
        down = float(c5[-1]) < float(c5[-6]) and price <= ema5
        if up:
            side = "buy"
            score += 15
            reasons.append("M5_up_fallback")
            used_fallback = True
        elif down:
            side = "sell"
            score += 15
            reasons.append("M5_down_fallback")
            used_fallback = True
        else:
            reasons.append("M15_no_trend")
            return Setup(None, score, reasons, rsi1, m15_side, None)

    if h1_side and side and h1_side != side:
        reasons.append(f"H1_conflict({h1_side})")
        return Setup(None, score, reasons, rsi1, m15_side, None)

    m5_ok, s5, r5 = _m5_entry(m5, c5, price, side)
    reasons.extend(r5)
    if not m5_ok:
        return Setup(None, score, reasons, rsi1, m15_side, None)
    score += s5

    rsi_ok, s_rsi, r_rsi = _rsi_ok(side, rsi1)
    reasons.extend(r_rsi)
    if not rsi_ok:
        score += s_rsi
        score = max(0, score)
        return Setup(None, score, reasons, rsi1, m15_side, side, used_fallback)
    score += s_rsi

    last1 = m1[-2] if len(m1) >= 2 else m1[-1]
    ema1 = _ema(c1, CONFIG.ema_period)
    if side == "buy":
        if last1["close"] <= last1["open"]:
            reasons.append("M1_need_green")
            return Setup(None, score, reasons, rsi1, m15_side, side, used_fallback)
        if price < ema1 * 0.999:
            reasons.append("M1_below_ema")
            return Setup(None, score, reasons, rsi1, m15_side, side, used_fallback)
        score += 10
        reasons.append("M1_confirms")
    else:
        if last1["close"] >= last1["open"]:
            reasons.append("M1_need_red")
            return Setup(None, score, reasons, rsi1, m15_side, side, used_fallback)
        if price > ema1 * 1.001:
            reasons.append("M1_above_ema")
            return Setup(None, score, reasons, rsi1, m15_side, side, used_fallback)
        score += 10
        reasons.append("M1_confirms")

    score = max(0, min(100, score))
    min_score = CONFIG.min_score_m5_fallback if used_fallback else CONFIG.min_confluence_score
    if score < min_score:
        side = None

    return Setup(side, score, reasons, rsi1, m15_side, side, used_fallback)
