"""MT5-free signal engine for backtesting (mirrors live analysis.py logic)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtest.guards import TradeGuards
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


@dataclass
class BarSetup:
    side: str | None
    score: int
    reasons: list[str]
    rsi: float
    adx: float
    z_score: float
    atr: float
    vol_ratio: float = 1.0
    used_fallback: bool = False

    @property
    def ok(self) -> bool:
        if self.side is None:
            return False
        min_score = (
            CONFIG.min_score_m5_fallback if self.used_fallback else CONFIG.min_confluence_score
        )
        return self.score >= min_score

    def passes_guards(self, guards: TradeGuards | None) -> bool:
        if not self.ok or not self.side or guards is None:
            return self.ok
        if self.score < guards.min_score:
            return False
        if self.adx < guards.min_adx:
            return False
        if guards.block_fallback and self.used_fallback:
            return False
        if self.vol_ratio > guards.max_vol_ratio:
            return False
        if self.side == "buy":
            if self.rsi > guards.rsi_buy_max or self.rsi < guards.rsi_buy_min:
                return False
            if self.z_score > guards.max_z_buy or self.z_score < guards.min_z_buy:
                return False
        else:
            if self.rsi < guards.rsi_sell_min or self.rsi > guards.rsi_sell_max:
                return False
            if self.z_score < -guards.max_z_sell:
                return False
        return True


def _slice_closes(df: pd.DataFrame, end_idx: int, n: int) -> np.ndarray:
    start = max(0, end_idx - n + 1)
    return df["close"].iloc[start : end_idx + 1].to_numpy(dtype=float)


def _slice_hl(df: pd.DataFrame, end_idx: int, n: int) -> tuple[np.ndarray, np.ndarray]:
    start = max(0, end_idx - n + 1)
    sl = df.iloc[start : end_idx + 1]
    return sl["high"].to_numpy(dtype=float), sl["low"].to_numpy(dtype=float)


def _h1_bias(d1: pd.DataFrame, d_idx: int, price: float) -> tuple[str | None, list[str]]:
    c = _slice_closes(d1, d_idx, 80)
    ema = ema_last(c, CONFIG.h1_ema_period)
    if price > ema * 1.0002:
        return "buy", ["H1_bullish"]
    if price < ema * 0.9998:
        return "sell", ["H1_bearish"]
    return None, ["H1_flat"]


def _m15_trend(h1: pd.DataFrame, h_idx: int, price: float) -> tuple[str | None, int, list[str]]:
    c = _slice_closes(h1, h_idx, 80)
    h, l = _slice_hl(h1, h_idx, 80)
    ema_f = ema_last(c, CONFIG.trend_ema_fast)
    ema_s = ema_last(c, CONFIG.trend_ema_slow)
    slope = regression_slope(c, CONFIG.slope_period)
    score = 0
    side: str | None = None
    reasons: list[str] = []

    if ema_f > ema_s and price >= ema_s:
        side = "buy"
        score += 30
        reasons.append("M15_up")
        if price >= ema_f:
            score += 10
        if c[-1] > c[-5]:
            score += 10
        if slope > 0:
            score += 8
    elif ema_f < ema_s and price <= ema_s:
        side = "sell"
        score += 30
        reasons.append("M15_down")
        if price <= ema_f:
            score += 10
        if c[-1] < c[-5]:
            score += 10
        if slope < 0:
            score += 8

    return side, score, reasons


def evaluate_at(
    h1: pd.DataFrame,
    m15: pd.DataFrame,
    d1: pd.DataFrame,
    h_idx: int,
    m_idx: int,
    d_idx: int,
    guards: TradeGuards | None = None,
) -> BarSetup:
    if h_idx < 80 or m_idx < 30 or d_idx < 55:
        return BarSetup(None, 0, ["warmup"], 50.0, 0.0, 0.0, 0.0)

    row_m = m15.iloc[m_idx]
    price = float(row_m["close"])
    c1 = _slice_closes(m15, m_idx, 80)
    c5 = _slice_closes(h1, h_idx, 80)
    h5, l5 = _slice_hl(h1, h_idx, 80)
    c15 = c5
    h15, l15 = h5, l5

    rsi_val = calc_rsi(c1, CONFIG.rsi_period)
    atr5 = calc_atr(h5, l5, c5, CONFIG.atr_period)
    atr_avg = calc_atr(h5, l5, c5, CONFIG.atr_period * 3)
    vol_r = volatility_ratio(atr5, atr_avg)
    adx_val = calc_adx(h15, l15, c15, CONFIG.adx_period)
    z = bollinger_zscore(c5, CONFIG.bb_period, CONFIG.bb_std)

    spike_cap = guards.max_vol_ratio if guards else CONFIG.atr_spike_mult
    adx_floor = guards.min_adx if guards else CONFIG.adx_min
    if vol_r > spike_cap:
        return BarSetup(None, 0, [f"ATR_spike"], rsi_val, adx_val, z, atr5, vol_r)
    if adx_val < adx_floor:
        return BarSetup(None, 0, [f"ADX_weak"], rsi_val, adx_val, z, atr5, vol_r)

    score = 5 if adx_val < CONFIG.adx_strong else 10
    reasons: list[str] = []
    used_fallback = False

    h1_side, h1_r = _h1_bias(d1, d_idx, price)
    reasons.extend(h1_r)
    if h1_side is None and CONFIG.require_h1_bias:
        return BarSetup(None, score, reasons, rsi_val, adx_val, z, atr5, vol_r)
    if h1_side:
        score += 15

    m15_side, s15, r15 = _m15_trend(h1, h_idx, price)
    score += s15
    reasons.extend(r15)
    side = m15_side

    if not side and CONFIG.allow_m5_fallback and not (guards and guards.block_fallback):
        ema5 = ema_last(c5, CONFIG.m5_ema_slow)
        if c5[-1] > c5[-6] and price >= ema5:
            side = "buy"
            score += 15
            reasons.append("M5_up_fallback")
            used_fallback = True
        elif c5[-1] < c5[-6] and price <= ema5:
            side = "sell"
            score += 15
            reasons.append("M5_down_fallback")
            used_fallback = True
        else:
            return BarSetup(None, score, reasons + ["M15_no_trend"], rsi_val, adx_val, z, atr5, vol_r)

    if h1_side and side and h1_side != side:
        return BarSetup(None, score, reasons + ["H1_conflict"], rsi_val, adx_val, z, atr5, vol_r)

    # M5 entry on previous H1 bar
    if h_idx < 2:
        return BarSetup(None, score, reasons, rsi_val, adx_val, z, atr5, vol_r)
    prev = h1.iloc[h_idx - 1]
    ema_fast = ema_last(c5, CONFIG.m5_ema_fast)
    ema_slow = ema_last(c5, CONFIG.m5_ema_slow)
    bull = prev["close"] > prev["open"]
    bear = prev["close"] < prev["open"]

    if side == "buy":
        if ema_fast <= ema_slow or not bull or prev["close"] < ema_fast or price <= ema_slow:
            return BarSetup(None, score, reasons + ["M5_reject"], rsi_val, adx_val, z, atr5, vol_r)
        score += 15
    else:
        tol = 1.0 + CONFIG.m5_sell_ema_tol_pct
        close_ok = prev["close"] <= ema_fast * tol
        bear_ok = bear
        relaxed = False
        if (
            CONFIG.m5_sell_relax >= 1
            and z >= CONFIG.m5_sell_relax_z_floor
            and ema_fast < ema_slow
            and price <= ema_slow
        ):
            if not bear:
                relaxed = True
            bear_ok = True
            if not close_ok:
                close_ok = prev["close"] <= ema_slow * tol
        if ema_fast >= ema_slow or not bear_ok or not close_ok or price >= ema_slow:
            return BarSetup(None, score, reasons + ["M5_reject"], rsi_val, adx_val, z, atr5, vol_r)
        if relaxed:
            reasons = reasons + ["M5_sell_relaxed"]
        score += 15

    z_max_b = guards.max_z_buy if guards else CONFIG.zscore_max_buy
    z_min_b = guards.min_z_buy if guards else CONFIG.zscore_min_buy
    rsi_bmax = guards.rsi_buy_max if guards else CONFIG.rsi_buy_max
    rsi_bmin = guards.rsi_buy_min if guards else CONFIG.rsi_buy_min
    rsi_smin = guards.rsi_sell_min if guards else CONFIG.rsi_sell_min
    rsi_smax = guards.rsi_sell_max if guards else CONFIG.rsi_sell_max

    if side == "buy":
        if z > z_max_b or z < z_min_b:
            return BarSetup(None, score, reasons, rsi_val, adx_val, z, atr5, vol_r)
        score += 10 if z <= 0.5 else 5
    else:
        z_cap = guards.max_z_sell if guards else CONFIG.zscore_max_sell
        if z < -z_cap or z > -CONFIG.zscore_min_buy:
            return BarSetup(None, score, reasons, rsi_val, adx_val, z, atr5, vol_r)
        score += 10 if z >= -0.5 else 5

    if side == "buy":
        if rsi_val > rsi_bmax or rsi_val < rsi_bmin:
            return BarSetup(None, score, reasons, rsi_val, adx_val, z, atr5, vol_r)
        score += 15
    else:
        if rsi_val < rsi_smin or rsi_val > rsi_smax:
            return BarSetup(None, score, reasons, rsi_val, adx_val, z, atr5, vol_r)
        score += 15

    # M1 confirm on previous M15 bar
    if m_idx < 2:
        return BarSetup(None, score, reasons, rsi_val, adx_val, z, atr5, vol_r)
    prev_m = m15.iloc[m_idx - 1]
    ema1 = ema_last(c1, CONFIG.ema_period)
    if side == "buy":
        if prev_m["close"] <= prev_m["open"] or price < ema1 * 0.999:
            return BarSetup(None, score, reasons, rsi_val, adx_val, z, atr5, vol_r)
    else:
        if prev_m["close"] >= prev_m["open"] or price > ema1 * 1.001:
            return BarSetup(None, score, reasons, rsi_val, adx_val, z, atr5, vol_r)
    score += 10

    score = max(0, min(100, score))
    min_score = guards.min_score if guards else (
        CONFIG.min_score_m5_fallback if used_fallback else CONFIG.min_confluence_score
    )
    if score < min_score:
        side = None

    setup = BarSetup(side, score, reasons, rsi_val, adx_val, z, atr5, vol_r, used_fallback)
    if guards and not setup.passes_guards(guards):
        return BarSetup(None, score, reasons + ["guard_reject"], rsi_val, adx_val, z, atr5, vol_r, used_fallback)
    return setup
