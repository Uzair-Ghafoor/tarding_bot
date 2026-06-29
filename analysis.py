"""
Multi-timeframe analysis with quantitative filters.

Math layer:
- H1 EMA bias (higher-TF direction)
- M15 EMA trend + regression slope (momentum)
- ADX trend strength (skip chop when ADX < threshold)
- M5 pullback on closed candle
- Z-score: block entries when price is statistically extended
- ATR volatility ratio: skip news spikes
- RSI zone filter (40–65 buy / 35–60 sell)
"""

from __future__ import annotations

from dataclasses import dataclass

import MetaTrader5 as mt5
import numpy as np

from config import CONFIG
from quant import (
    adx as calc_adx,
    atr as calc_atr,
    bollinger_zscore,
    ema_last,
    regression_slope,
    rsi as calc_rsi,
    volatility_ratio,
)


def _rates(symbol: str, tf: int, count: int):
    r = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    return r if r is not None and len(r) else None


def _h1_bias(c1h: np.ndarray, price: float) -> tuple[str | None, list[str]]:
    ema = ema_last(c1h, CONFIG.h1_ema_period)
    tol = CONFIG.h1_ema_tol_pct
    if price > ema * (1 + tol):
        return "buy", ["H1_bullish"]
    if price < ema * (1 - tol):
        return "sell", ["H1_bearish"]
    return None, ["H1_flat"]


def _m15_trend(c15: np.ndarray, price: float) -> tuple[str | None, int, list[str]]:
    reasons: list[str] = []
    ema_f = ema_last(c15, CONFIG.trend_ema_fast)
    ema_s = ema_last(c15, CONFIG.trend_ema_slow)
    slope = regression_slope(c15, CONFIG.slope_period)
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
        if slope > 0:
            score += 8
            reasons.append("M15_slope_up")
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
        if slope < 0:
            score += 8
            reasons.append("M15_slope_down")

    return side, score, reasons


def _m5_entry(m5, c5: np.ndarray, price: float, side: str) -> tuple[bool, int, list[str]]:
    reasons: list[str] = []
    score = 0
    if len(m5) < 4:
        return False, 0, ["M5_short_history"]

    bar = m5[-2]
    ema_fast = ema_last(c5, CONFIG.m5_ema_fast)
    ema_slow = ema_last(c5, CONFIG.m5_ema_slow)
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


def _rsi_ok(side: str, rsi_val: float) -> tuple[bool, int, list[str]]:
    reasons: list[str] = []
    if side == "buy":
        if rsi_val > CONFIG.rsi_buy_max:
            reasons.append(f"RSI_overbought({rsi_val:.0f})")
            return False, -40, reasons
        if rsi_val < CONFIG.rsi_buy_min:
            reasons.append(f"RSI_weak({rsi_val:.0f})")
            return False, -20, reasons
        score = 15
        reasons.append(f"RSI_ok({rsi_val:.0f})")
        return True, score, reasons

    if rsi_val < CONFIG.rsi_sell_min:
        reasons.append(f"RSI_oversold({rsi_val:.0f})")
        return False, -40, reasons
    if rsi_val > CONFIG.rsi_sell_max:
        reasons.append(f"RSI_weak({rsi_val:.0f})")
        return False, -20, reasons
    score = 15
    reasons.append(f"RSI_ok({rsi_val:.0f})")
    return True, score, reasons


def _zscore_ok(side: str, z: float) -> tuple[bool, int, list[str]]:
    reasons: list[str] = []
    if side == "buy":
        if z > CONFIG.zscore_max_buy:
            reasons.append(f"Z_extended({z:.2f})")
            return False, -25, reasons
        if z < CONFIG.zscore_min_buy:
            reasons.append(f"Z_weak({z:.2f})")
            return False, -10, reasons
        score = 10 if z <= 0.5 else 5
        reasons.append(f"Z_ok({z:.2f})")
        return True, score, reasons

    if z < -CONFIG.zscore_max_sell:
        reasons.append(f"Z_extended({z:.2f})")
        return False, -25, reasons
    if z > -CONFIG.zscore_min_buy:
        reasons.append(f"Z_weak({z:.2f})")
        return False, -10, reasons
    score = 10 if z >= -0.5 else 5
    reasons.append(f"Z_ok({z:.2f})")
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
    adx: float = 0.0
    z_score: float = 0.0
    slope_m15: float = 0.0
    atr_m5: float = 0.0
    vol_ratio: float = 1.0

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
    h15 = np.array([r["high"] for r in m15], dtype=float)
    l15 = np.array([r["low"] for r in m15], dtype=float)
    c5 = np.array([r["close"] for r in m5], dtype=float)
    h5 = np.array([r["high"] for r in m5], dtype=float)
    l5 = np.array([r["low"] for r in m5], dtype=float)
    c1 = np.array([r["close"] for r in m1], dtype=float)

    price = float(c1[-1])
    rsi1 = calc_rsi(c1, CONFIG.rsi_period)
    atr5 = calc_atr(h5, l5, c5, CONFIG.atr_period)
    atr_avg = calc_atr(h5, l5, c5, CONFIG.atr_period * 3)
    vol_r = volatility_ratio(atr5, atr_avg)
    adx_val = calc_adx(h15, l15, c15, CONFIG.adx_period)
    z = bollinger_zscore(c5, CONFIG.bb_period, CONFIG.bb_std)
    slope15 = regression_slope(c15, CONFIG.slope_period)

    if vol_r > CONFIG.atr_spike_mult:
        return Setup(
            None, 0, [f"ATR_spike(ratio={vol_r:.2f})"], rsi1, None, None,
            adx=adx_val, z_score=z, slope_m15=slope15, atr_m5=atr5, vol_ratio=vol_r,
        )

    if adx_val < CONFIG.adx_min:
        return Setup(
            None, 0, [f"ADX_weak({adx_val:.0f})"], rsi1, None, None,
            adx=adx_val, z_score=z, slope_m15=slope15, atr_m5=atr5, vol_ratio=vol_r,
        )

    score = 0
    reasons: list[str] = []
    used_fallback = False

    if adx_val >= CONFIG.adx_strong:
        score += 10
        reasons.append(f"ADX_strong({adx_val:.0f})")
    else:
        score += 5
        reasons.append(f"ADX_ok({adx_val:.0f})")

    h1_side, h1_reasons = _h1_bias(c1h, price)
    reasons.extend(h1_reasons)
    if h1_side is None and CONFIG.require_h1_bias:
        return Setup(
            None, score, reasons, rsi1, None, None,
            adx=adx_val, z_score=z, slope_m15=slope15, atr_m5=atr5, vol_ratio=vol_r,
        )
    if h1_side:
        score += 15

    m15_side, s15, r15 = _m15_trend(c15, price)
    score += s15
    reasons.extend(r15)

    side = m15_side
    if not side and CONFIG.allow_m5_fallback:
        ema5 = ema_last(c5, CONFIG.m5_ema_slow)
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
            return Setup(
                None, score, reasons, rsi1, m15_side, None, used_fallback,
                adx_val, z, slope15, atr5, vol_r,
            )

    if h1_side and side and h1_side != side:
        if CONFIG.block_h1_conflict:
            reasons.append(f"H1_conflict({h1_side})")
            return Setup(
                None, score, reasons, rsi1, m15_side, None, used_fallback,
                adx_val, z, slope15, atr5, vol_r,
            )
        reasons.append(f"H1_conflict_soft({h1_side})")
        score = max(0, score - 8)

    m5_ok, s5, r5 = _m5_entry(m5, c5, price, side)
    reasons.extend(r5)
    if not m5_ok:
        return Setup(
            None, score, reasons, rsi1, m15_side, None, used_fallback,
            adx_val, z, slope15, atr5, vol_r,
        )
    score += s5

    z_ok, s_z, r_z = _zscore_ok(side, z)
    reasons.extend(r_z)
    if not z_ok:
        score += s_z
        score = max(0, score)
        return Setup(
            None, score, reasons, rsi1, m15_side, side, used_fallback,
            adx_val, z, slope15, atr5, vol_r,
        )
    score += s_z

    rsi_ok, s_rsi, r_rsi = _rsi_ok(side, rsi1)
    reasons.extend(r_rsi)
    if not rsi_ok:
        score += s_rsi
        score = max(0, score)
        return Setup(
            None, score, reasons, rsi1, m15_side, side, used_fallback,
            adx_val, z, slope15, atr5, vol_r,
        )
    score += s_rsi

    last1 = m1[-2] if len(m1) >= 2 else m1[-1]
    ema1 = ema_last(c1, CONFIG.ema_period)
    if side == "buy":
        if last1["close"] <= last1["open"]:
            reasons.append("M1_need_green")
            return Setup(
                None, score, reasons, rsi1, m15_side, side, used_fallback,
                adx_val, z, slope15, atr5, vol_r,
            )
        if price < ema1 * 0.999:
            reasons.append("M1_below_ema")
            return Setup(
                None, score, reasons, rsi1, m15_side, side, used_fallback,
                adx_val, z, slope15, atr5, vol_r,
            )
        score += 10
        reasons.append("M1_confirms")
    else:
        if last1["close"] >= last1["open"]:
            reasons.append("M1_need_red")
            return Setup(
                None, score, reasons, rsi1, m15_side, side, used_fallback,
                adx_val, z, slope15, atr5, vol_r,
            )
        if price > ema1 * 1.001:
            reasons.append("M1_above_ema")
            return Setup(
                None, score, reasons, rsi1, m15_side, side, used_fallback,
                adx_val, z, slope15, atr5, vol_r,
            )
        score += 10
        reasons.append("M1_confirms")

    score = max(0, min(100, score))
    min_score = CONFIG.min_score_m5_fallback if used_fallback else CONFIG.min_confluence_score
    if score < min_score:
        side = None

    return Setup(
        side, score, reasons, rsi1, m15_side, side, used_fallback,
        adx_val, z, slope15, atr5, vol_r,
    )
