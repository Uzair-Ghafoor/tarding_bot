"""Live OHLC feed for paper trading — Binance XAUUSDT tick + bars."""

from __future__ import annotations

import json
import ssl
import time
import urllib.request
from datetime import datetime, timezone

import pandas as pd

from backtest.data import _fetch_yahoo_daily, _fetch_yahoo_hourly_recent, _normalize_ohlc
from backtest.pairs import PAIRS, PairSpec

# Bot symbol → paper pair name
SYMBOL_MAP = {
    "XAUUSD": "XAUUSD",
    "XAUUSDm": "XAUUSD",
    "EURUSD": "EURUSD",
    "EURUSDm": "EURUSD",
    "GBPUSD": "GBPUSD",
    "USDJPY": "USDJPY",
    "AUDUSD": "AUDUSD",
    "XAUUSDT": "XAUUSDT",
    "XAUUSDTm": "XAUUSDT",
}

_history_cache: dict[str, tuple[float, pd.DataFrame, pd.DataFrame]] = {}


def resolve_paper_pair(symbol: str) -> str:
    s = symbol.upper().rstrip("M")
    if s in PAIRS:
        return s
    if symbol in SYMBOL_MAP:
        return SYMBOL_MAP[symbol]
    raise ValueError(f"Unknown paper symbol {symbol}. Use one of: {list(PAIRS)}")


def _ssl_ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _resample_m15(m5: pd.DataFrame) -> pd.DataFrame:
    return m5.resample("15min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()


def _load_history(pair: str, max_age_sec: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    now = time.time()
    cached = _history_cache.get(pair)
    if cached and now - cached[0] < max_age_sec:
        return cached[1], cached[2]

    spec = PAIRS[pair]
    if spec.source == "binance":
        from backtest.data import _fetch_binance_hourly

        h1 = _fetch_binance_hourly(spec, 2)
        d1 = h1.resample("1D").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna()
    else:
        h1 = _fetch_yahoo_hourly_recent(spec)
        if h1.empty:
            raise RuntimeError(f"No hourly history for {spec.name}")
        d1 = _fetch_yahoo_daily(spec, 2)

    _history_cache[pair] = (now, h1, d1)
    return h1, d1


def _fetch_yahoo_5m(spec: PairSpec, *, period: str = "2d") -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(
        spec.ticker,
        period=period,
        interval="5m",
        progress=False,
        auto_adjust=True,
    )
    if raw is None or not len(raw):
        raise RuntimeError(f"No 5m data for {spec.ticker}")
    return _normalize_ohlc(raw)


def _fetch_binance_5m(spec: PairSpec, *, limit: int = 500) -> pd.DataFrame:
    ctx = _ssl_ctx()
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - limit * 5 * 60 * 1000
    for base in (
        f"https://api.binance.com/api/v3/klines?symbol={spec.ticker}&interval=5m&startTime={start_ms}&limit={limit}",
        f"https://fapi.binance.com/fapi/v1/klines?symbol={spec.ticker}&interval=5m&startTime={start_ms}&limit={limit}",
    ):
        try:
            with urllib.request.urlopen(base, timeout=12, context=ctx) as resp:
                batch = json.loads(resp.read().decode())
            break
        except Exception:
            batch = []
    if not batch:
        raise RuntimeError(f"No 5m data for {spec.ticker}")

    df = pd.DataFrame(
        batch,
        columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "qav", "trades", "tb_base", "tb_quote", "ignore",
        ],
    )
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("open_time")
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    out = _normalize_ohlc(df)
    if out.index.tz is not None:
        out.index = out.index.tz_convert("UTC").tz_localize(None)
    return out


def _fetch_binance_tick(spec: PairSpec) -> float | None:
    ctx = _ssl_ctx()
    for url in (
        f"https://api.binance.com/api/v3/ticker/price?symbol={spec.ticker}",
        f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={spec.ticker}",
    ):
        try:
            with urllib.request.urlopen(url, timeout=5, context=ctx) as resp:
                data = json.loads(resp.read().decode())
            return float(data["price"])
        except Exception:
            continue
    return None


def _fetch_live_m5(spec: PairSpec) -> pd.DataFrame:
    if spec.source == "binance":
        return _fetch_binance_5m(spec)
    return _fetch_yahoo_5m(spec, period="2d")


def build_frames(pair: str, *, history_max_age_sec: float = 0) -> dict[str, pd.DataFrame]:
    """Full load: slow H1/daily history + fresh 5m bars."""
    spec = PAIRS[pair]
    h1, d1 = _load_history(pair, max_age_sec=history_max_age_sec)
    m5 = _fetch_live_m5(spec)
    m15 = _resample_m15(m5)
    price = float(m5["close"].iloc[-1])
    if spec.source == "binance":
        tick = _fetch_binance_tick(spec)
        if tick is not None:
            price = tick
    return {"m5": m5, "m15": m15, "h1": h1, "d1": d1, "last_price": price}


def fetch_tick_price(pair: str) -> float:
    """Fast live price — Binance ticker or Yahoo fast_info (~200ms)."""
    spec = PAIRS[pair]
    if spec.source == "binance":
        tick = _fetch_binance_tick(spec)
        if tick is not None:
            return tick
    import yfinance as yf

    t = yf.Ticker(spec.ticker)
    p = getattr(t, "fast_info", None)
    if p is not None:
        lp = getattr(p, "last_price", None)
        if lp is not None:
            return float(lp)
    raise RuntimeError(f"No tick price for {pair}")


def refresh_tick_only(frames: dict, pair: str) -> float:
    """Update last_price only — no bar refetch (sub-second)."""
    price = fetch_tick_price(pair)
    frames["last_price"] = price
    return price


def refresh_live_bars(frames: dict, pair: str) -> float:
    """Fast path: update 5m/M15/last price only; keep cached H1/daily."""
    spec = PAIRS[pair]
    m5 = _fetch_live_m5(spec)
    frames["m5"] = m5
    frames["m15"] = _resample_m15(m5)
    price = float(m5["close"].iloc[-1])
    if spec.source == "binance":
        tick = _fetch_binance_tick(spec)
        if tick is not None:
            price = tick
    frames["last_price"] = price
    return price
