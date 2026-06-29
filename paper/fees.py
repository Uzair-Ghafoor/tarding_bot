"""Binance paper trading costs — spread + taker fees on open and close."""

from __future__ import annotations

import json
import urllib.request

from backtest.pairs import PairSpec
from config import CONFIG


def paper_notional_usd(price: float) -> float:
    """USD notional per basket for fee math (scaled to reference balance)."""
    return CONFIG.reference_balance * CONFIG.paper_notional_mult


def paper_qty_oz(price: float) -> float:
    if price <= 0:
        return 0.0
    return paper_notional_usd(price) / price


def _fetch_book_ticker(symbol: str) -> tuple[float, float] | None:
    from paper.feed import _binance_fapi_base, _ssl_ctx

    ctx = _ssl_ctx()
    fapi = _binance_fapi_base()
    for url in (
        f"{fapi}/fapi/v1/ticker/bookTicker?symbol={symbol}",
        f"https://fapi.binance.com/fapi/v1/ticker/bookTicker?symbol={symbol}",
    ):
        try:
            with urllib.request.urlopen(url, timeout=5, context=ctx) as resp:
                data = json.loads(resp.read().decode())
            return float(data["bidPrice"]), float(data["askPrice"])
        except Exception:
            continue
    return None


def binance_half_spread_usd(spec: PairSpec, price: float) -> float:
    """Half bid-ask spread cost for paper qty (entry or exit slippage)."""
    book = _fetch_book_ticker(spec.ticker)
    if book:
        bid, ask = book
        spread = max(0.0, ask - bid)
    else:
        spread = spec.spread_pips * spec.pip_size
    return spread * paper_qty_oz(price)


def binance_taker_fee_usd(price: float) -> float:
    """Taker fee on one fill (market order) for paper notional."""
    return paper_notional_usd(price) * CONFIG.binance_taker_fee


def paper_open_cost(spec: PairSpec, price: float) -> float:
    """Spread slippage + taker fee when opening a basket."""
    if spec.source != "binance":
        from backtest.engine import _spread_cost
        return _spread_cost(spec, CONFIG.basket_size)
    return round(binance_half_spread_usd(spec, price) + binance_taker_fee_usd(price), 4)


def paper_close_cost(spec: PairSpec, price: float) -> float:
    """Spread slippage + taker fee when closing a basket."""
    if spec.source != "binance":
        return 0.0
    return round(binance_half_spread_usd(spec, price) + binance_taker_fee_usd(price), 4)


def paper_pnl_spread(spec: PairSpec, basket_size: int) -> float:
    """Spread drag inside mark PnL — zero for Binance (fees applied on open/close)."""
    if spec.source == "binance":
        return 0.0
    from backtest.engine import _spread_cost
    return _spread_cost(spec, basket_size)
