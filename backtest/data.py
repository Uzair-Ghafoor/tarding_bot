"""Download and cache historical OHLC (daily 10yr + hourly recent)."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

from backtest.pairs import PAIRS, PairSpec

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")


def _cache_path(pair: str, kind: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{pair}_{kind}.parquet")


def _meta_path(pair: str) -> str:
    return os.path.join(CACHE_DIR, f"{pair}_meta.json")


def _utc_naive(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if out.index.tz is not None:
        out.index = out.index.tz_convert("UTC").tz_localize(None)
    return out.sort_index()


def _save_meta(pair: str, meta: dict) -> None:
    with open(_meta_path(pair), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, default=str)


def _normalize_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]
    df = df.rename(columns={"adj close": "close"})
    keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
    out = _utc_naive(df[keep].copy())
    out = out[~out.index.duplicated(keep="last")].dropna(subset=["open", "high", "low", "close"])
    return out


def _fetch_yahoo_hourly_recent(spec: PairSpec) -> pd.DataFrame:
    """Yahoo limits 1h data to ~730 days — single recent window."""
    import yfinance as yf

    raw = yf.download(
        spec.ticker,
        period="700d",
        interval="1h",
        progress=False,
        auto_adjust=True,
    )
    if raw is None or not len(raw):
        return pd.DataFrame()
    return _normalize_ohlc(raw)


def _fetch_yahoo_daily(spec: PairSpec, years: int) -> pd.DataFrame:
    import yfinance as yf

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365 * years + 30)
    raw = yf.download(
        spec.ticker,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        interval="1d",
        progress=False,
        auto_adjust=True,
    )
    if raw is None or not len(raw):
        raise RuntimeError(f"No Yahoo daily data for {spec.name}")
    return _normalize_ohlc(raw)


def _fetch_binance_hourly(spec: PairSpec, years: int) -> pd.DataFrame:
    import json as _json
    import ssl
    import urllib.request

    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()

    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = int((datetime.now(timezone.utc) - timedelta(days=365 * years)).timestamp() * 1000)
    rows: list[list] = []
    cursor = start_ms
    symbol = spec.ticker.upper()
    bases = [
        f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&startTime={{}}&limit=1000",
        f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1h&startTime={{}}&limit=1000",
    ]
    base_url = bases[0]

    while cursor < end_ms:
        url = base_url.format(cursor)
        try:
            with urllib.request.urlopen(url, timeout=30, context=ctx) as resp:
                batch = _json.loads(resp.read().decode())
        except Exception:
            if base_url == bases[0]:
                base_url = bases[1]
                continue
            raise
        if not batch:
            break
        rows.extend(batch)
        cursor = int(batch[-1][0]) + 1
        time.sleep(0.12)

    if not rows:
        raise RuntimeError(f"No Binance data for {spec.name}")

    df = pd.DataFrame(
        rows,
        columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "qav", "trades", "tb_base", "tb_quote", "ignore",
        ],
    )
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("open_time")
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return _normalize_ohlc(df)


def resample_m15(h1: pd.DataFrame) -> pd.DataFrame:
    """Synthetic M15 from H1 (4 segments per hour)."""
    parts: list[dict] = []
    for ts, row in h1.iterrows():
        o, h, l, c = row["open"], row["high"], row["low"], row["close"]
        seg_o = [o, (o + c) / 2, (o + h) / 2, (l + c) / 2]
        seg_c = [(o + c) / 2, (o + h) / 2, (l + c) / 2, c]
        seg_h = [max(o, x) for x in seg_c]
        seg_l = [min(o, x) for x in seg_c]
        for i in range(4):
            parts.append(
                {
                    "time": ts + timedelta(minutes=15 * i),
                    "open": seg_o[i],
                    "high": seg_h[i],
                    "low": seg_l[i],
                    "close": seg_c[i],
                }
            )
    return _utc_naive(pd.DataFrame(parts).set_index("time"))


def load_pair_data(
    pair: str,
    years: int = 10,
    refresh: bool = False,
    mode: str = "daily",
) -> dict:
    """
    mode=daily  → 10yr daily bars (full history backtest)
    mode=hourly → ~2yr H1 + synthetic M15 (scalp proxy)
    """
    spec = PAIRS[pair]
    tag = "d1" if mode == "daily" else "h1"
    main_path = _cache_path(pair, tag)

    if not refresh and os.path.isfile(main_path):
        main = pd.read_parquet(main_path)
        meta_path = _meta_path(pair)
        meta = {}
        if os.path.isfile(meta_path):
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        if mode == "daily":
            d1 = main
            return {"h1": d1, "d1": d1, "m15": d1, "meta": meta, "mode": mode}
        h1 = main
        d1_path = _cache_path(pair, "d1")
        d1 = pd.read_parquet(d1_path) if os.path.isfile(d1_path) else h1.resample("1D").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna()
        return {"h1": h1, "d1": d1, "m15": resample_m15(h1), "meta": meta, "mode": mode}

    if mode == "daily":
        if spec.source == "binance":
            h1 = _fetch_binance_hourly(spec, years)
            d1 = h1.resample("1D").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
            ).dropna()
        else:
            d1 = _fetch_yahoo_daily(spec, years)
        meta = {
            "pair": pair,
            "mode": mode,
            "source": spec.source,
            "bars": len(d1),
            "from": str(d1.index.min()),
            "to": str(d1.index.max()),
            "years_requested": years,
        }
        d1.to_parquet(main_path)
        _save_meta(pair, meta)
        return {"h1": d1, "d1": d1, "m15": d1, "meta": meta, "mode": mode}

    # hourly mode
    if spec.source == "binance":
        h1 = _fetch_binance_hourly(spec, min(years, 6))
    else:
        h1 = _fetch_yahoo_hourly_recent(spec)
        if h1.empty:
            raise RuntimeError(f"No recent hourly data for {spec.name}")
    d1 = _fetch_yahoo_daily(spec, years) if spec.source != "binance" else h1.resample("1D").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()
    m15 = resample_m15(h1)
    meta = {
        "pair": pair,
        "mode": mode,
        "source": spec.source,
        "h1_bars": len(h1),
        "d1_bars": len(d1),
        "from": str(h1.index.min()),
        "to": str(h1.index.max()),
        "years_requested": years,
    }
    h1.to_parquet(main_path)
    d1.to_parquet(_cache_path(pair, "d1"))
    _save_meta(pair, meta)
    return {"h1": h1, "d1": d1, "m15": m15, "meta": meta, "mode": mode}
