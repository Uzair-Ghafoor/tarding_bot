"""Basket backtest engine with spread + ATR targets."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backtest.guards import TradeGuards
from backtest.pairs import PairSpec
from backtest.signals import BarSetup, evaluate_at
from config import CONFIG
from quant import atr_basket_targets, effective_sl_atr_mult, expected_value, profit_factor
@dataclass
class BasketTrade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    side: str
    pnl: float
    reason: str
    score: int
    adx: float = 0.0
    rsi: float = 50.0
    z_score: float = 0.0
    vol_ratio: float = 1.0
    used_fallback: bool = False
    reasons: list[str] = field(default_factory=list)


@dataclass
class BacktestResult:
    pair: str
    start: pd.Timestamp
    end: pd.Timestamp
    initial_balance: float
    final_balance: float
    trades: list[BasketTrade] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=pd.Series)
    meta: dict = field(default_factory=dict)

    @property
    def net_pnl(self) -> float:
        return self.final_balance - self.initial_balance

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.pnl >= 0)
        return wins / len(self.trades)

    @property
    def expectancy(self) -> float:
        if not self.trades:
            return 0.0
        wins = [t.pnl for t in self.trades if t.pnl >= 0]
        losses = [-t.pnl for t in self.trades if t.pnl < 0]
        if not losses:
            return float(np.mean(wins)) if wins else 0.0
        p = len(wins) / len(self.trades)
        return expected_value(p, float(np.mean(wins)) if wins else 0, float(np.mean(losses)))

    @property
    def pf(self) -> float:
        gw = sum(t.pnl for t in self.trades if t.pnl >= 0)
        gl = sum(-t.pnl for t in self.trades if t.pnl < 0)
        return profit_factor(gw, gl)

    @property
    def max_drawdown_pct(self) -> float:
        if self.equity_curve.empty:
            return 0.0
        peak = self.equity_curve.cummax()
        dd = (self.equity_curve - peak) / peak.replace(0, np.nan)
        return float(abs(dd.min()) * 100)


def _gold_oz_equiv(basket_size: int) -> float:
    """MT5 Exness: 1.0 lot = 100 oz → 0.01 lot × N positions."""
    return 100.0 * CONFIG.lot_size * basket_size


def _pnl_at_price(
    spec: PairSpec, side: str, entry: float, price: float, basket_size: int, spread: float
) -> float:
    move = (price - entry) if side == "buy" else (entry - price)
    if spec.name in ("XAUUSD", "XAUUSDT"):
        return move * _gold_oz_equiv(basket_size) - spread
    pips = move / spec.pip_size
    units = CONFIG.lot_size / 0.01
    return pips * spec.pip_value_usd * units * basket_size - spread


def _spread_cost(spec: PairSpec, basket_size: int) -> float:
    if spec.name in ("XAUUSD", "XAUUSDT"):
        return abs(_pnl_at_price(spec, "buy", 0.0, spec.spread_pips * spec.pip_size, basket_size, 0.0))
    units = CONFIG.lot_size / 0.01
    return spec.spread_pips * spec.pip_value_usd * units * basket_size


def _targets(spec: PairSpec, setup: BarSetup) -> tuple[float, float]:
    point = spec.pip_size
    money_per_point = _pnl_at_price(spec, "buy", 0.0, point, 1, 0.0)
    profit, stop, _ = atr_basket_targets(
        atr_price=setup.atr,
        point=point,
        money_per_point_per_lot=money_per_point / CONFIG.lot_size,
        lot=CONFIG.lot_size,
        basket_size=CONFIG.basket_size,
        tp_atr_mult=CONFIG.atr_tp_mult,
        sl_atr_mult=effective_sl_atr_mult(setup.vol_ratio),
        min_profit=CONFIG.basket_min_profit,
        min_loss=CONFIG.basket_min_profit * 0.5,
        max_profit=CONFIG.reference_balance * 0.08,
        max_loss=CONFIG.basket_max_loss,
    )
    return profit, stop


def _align_indices(h1: pd.DataFrame, m15: pd.DataFrame, d1: pd.DataFrame) -> pd.DataFrame:
    """Map each M15 bar to corresponding H1 and D1 index (UTC-naive)."""
    m_idx = m15.index
    if m_idx.tz is not None:
        m_idx = m_idx.tz_convert("UTC").tz_localize(None)
    h_idx = h1.index
    if h_idx.tz is not None:
        h_idx = h_idx.tz_convert("UTC").tz_localize(None)
    d_idx = d1.index
    if d_idx.tz is not None:
        d_idx = d_idx.tz_convert("UTC").tz_localize(None)

    h1_pos = h_idx.searchsorted(m_idx, side="right") - 1
    d1_pos = d_idx.searchsorted(m_idx, side="right") - 1
    return pd.DataFrame({"m15": np.arange(len(m15)), "h1": h1_pos, "d1": d1_pos}, index=m_idx)


def run_backtest(
    pair: str,
    spec: PairSpec,
    h1: pd.DataFrame,
    m15: pd.DataFrame,
    d1: pd.DataFrame,
    initial_balance: float | None = None,
    bar_minutes: int = 15,
    guards: TradeGuards | None = None,
) -> BacktestResult:
    balance = initial_balance or CONFIG.reference_balance
    align = _align_indices(h1, m15, d1)
    trades: list[BasketTrade] = []
    equity = []
    eq_times = []

    in_basket = False
    side: str | None = None
    entry_i = 0
    entry_time: pd.Timestamp | None = None
    entry_price = 0.0
    tp = CONFIG.basket_min_profit
    sl = CONFIG.basket_max_loss
    entry_score = 0
    entry_meta: BarSetup | None = None
    cooldown_until = 0
    bars_per_cooldown = max(1, CONFIG.entry_cooldown_seconds // (bar_minutes * 60))
    post_close_cooldown = max(1, CONFIG.post_basket_cooldown_seconds // (bar_minutes * 60))
    max_hold_bars = max(1, CONFIG.max_hold_seconds // (bar_minutes * 60))

    spread_once = _spread_cost(spec, CONFIG.basket_size)

    for i in range(len(m15)):
        ts = m15.index[i]
        price = float(m15.iloc[i]["close"])
        h_idx = int(align.iloc[i]["h1"])
        d_idx = int(align.iloc[i]["d1"])

        if in_basket and side:
            row = m15.iloc[i]
            hi, lo = float(row["high"]), float(row["low"])
            if side == "buy":
                best_pnl = _pnl_at_price(spec, side, entry_price, hi, CONFIG.basket_size, spread_once)
                worst_pnl = _pnl_at_price(spec, side, entry_price, lo, CONFIG.basket_size, spread_once)
            else:
                best_pnl = _pnl_at_price(spec, side, entry_price, lo, CONFIG.basket_size, spread_once)
                worst_pnl = _pnl_at_price(spec, side, entry_price, hi, CONFIG.basket_size, spread_once)
            close_pnl = _pnl_at_price(spec, side, entry_price, price, CONFIG.basket_size, spread_once)
            held = i - entry_i
            reason = ""
            exit_pnl = close_pnl
            if best_pnl >= tp:
                reason, exit_pnl = "profit", tp
            elif worst_pnl <= -sl:
                reason, exit_pnl = "basket_stop", -sl
            elif held >= max_hold_bars:
                reason, exit_pnl = "timeout", close_pnl

            if reason:
                balance += exit_pnl
                meta = entry_meta
                trades.append(
                    BasketTrade(
                        entry_time,
                        ts,
                        side,
                        exit_pnl,
                        reason,
                        entry_score,
                        adx=meta.adx if meta else 0.0,
                        rsi=meta.rsi if meta else 50.0,
                        z_score=meta.z_score if meta else 0.0,
                        vol_ratio=meta.vol_ratio if meta else 1.0,
                        used_fallback=meta.used_fallback if meta else False,
                        reasons=list(meta.reasons) if meta else [],
                    )
                )
                in_basket = False
                cooldown_until = i + post_close_cooldown
                equity.append(balance)
                eq_times.append(ts)
            continue

        if in_basket or i < cooldown_until:
            continue

        setup = evaluate_at(h1, m15, d1, h_idx, i, d_idx, guards=guards)
        if not setup.passes_guards(guards):
            continue

        tp, sl = _targets(spec, setup)
        in_basket = True
        side = setup.side
        entry_i = i
        entry_time = ts
        entry_price = price
        entry_score = setup.score
        entry_meta = setup

    if in_basket and side and entry_time:
        price = float(m15.iloc[-1]["close"])
        pnl = _pnl_at_price(spec, side, entry_price, price, CONFIG.basket_size, spread_once)
        balance += pnl
        meta = entry_meta
        trades.append(
            BasketTrade(
                entry_time,
                m15.index[-1],
                side,
                pnl,
                "eod",
                entry_score,
                adx=meta.adx if meta else 0.0,
                rsi=meta.rsi if meta else 50.0,
                z_score=meta.z_score if meta else 0.0,
                vol_ratio=meta.vol_ratio if meta else 1.0,
                used_fallback=meta.used_fallback if meta else False,
                reasons=list(meta.reasons) if meta else [],
            )
        )
        equity.append(balance)
        eq_times.append(m15.index[-1])

    eq_series = pd.Series(equity, index=eq_times) if eq_times else pd.Series(dtype=float)
    return BacktestResult(
        pair=pair,
        start=m15.index[0],
        end=m15.index[-1],
        initial_balance=initial_balance or CONFIG.reference_balance,
        final_balance=balance,
        trades=trades,
        equity_curve=eq_series,
        meta={
            "bars": len(m15),
            "bar_minutes": bar_minutes,
            "spread_cost": spread_once,
            "guards": guards.label() if guards else "baseline",
        },
    )
