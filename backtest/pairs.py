"""Instrument definitions for backtesting."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PairSpec:
    name: str
    source: str  # yahoo | binance
    ticker: str
    pip_size: float
    pip_value_usd: float  # per 0.01 lot per pip (approx)
    spread_pips: float
    point_value_usd: float | None = None  # gold: $ per $1 move per 0.01 lot


PAIRS: dict[str, PairSpec] = {
    "EURUSD": PairSpec(
        "EURUSD", "yahoo", "EURUSD=X", pip_size=0.0001, pip_value_usd=0.10, spread_pips=1.2
    ),
    "GBPUSD": PairSpec(
        "GBPUSD", "yahoo", "GBPUSD=X", pip_size=0.0001, pip_value_usd=0.10, spread_pips=1.5
    ),
    "USDJPY": PairSpec(
        "USDJPY", "yahoo", "JPY=X", pip_size=0.01, pip_value_usd=0.09, spread_pips=1.3
    ),
    "AUDUSD": PairSpec(
        "AUDUSD", "yahoo", "AUDUSD=X", pip_size=0.0001, pip_value_usd=0.10, spread_pips=1.4
    ),
    "XAUUSD": PairSpec(
        "XAUUSD",
        "yahoo",
        "GC=F",
        pip_size=0.001,
        pip_value_usd=0.10,
        spread_pips=45.0,
        point_value_usd=1.0,
    ),
    "XAUUSDT": PairSpec(
        "XAUUSDT",
        "binance",
        "XAUUSDT",
        pip_size=0.001,
        pip_value_usd=0.10,
        spread_pips=45.0,
        point_value_usd=1.0,
    ),
}

DEFAULT_PAIRS = list(PAIRS.keys())
