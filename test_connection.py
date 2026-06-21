"""Verify Exness MT5 connection before running the bot."""

from __future__ import annotations

import sys

from config import CONFIG
from mt5_client import MT5Client
from session import in_trading_session
from trend import trend_direction


def main() -> None:
    print("=" * 50)
    print("Exness MT5 connection test")
    print("=" * 50)

    if not CONFIG.login or not CONFIG.password or not CONFIG.server:
        print("ERROR: Set MT5_LOGIN, MT5_PASSWORD, MT5_SERVER in .env")
        sys.exit(1)

    client = MT5Client()
    try:
        client.connect()
        symbol = client.resolve_symbol(CONFIG.symbol, CONFIG.symbol_fallbacks)
        client.ensure_symbol(symbol)
        spread = client.spread_points(symbol)
        cost = client.estimated_spread_cost(symbol, CONFIG.lot_size)
        trend, strength = trend_direction(symbol)
        session = in_trading_session()

        print(f"Symbol:        {symbol}")
        print(f"Spread:        {spread} points")
        print(f"Spread cost:   ${cost:.4f} per round-trip (lot={CONFIG.lot_size})")
        print(f"Min profit:    ${max(CONFIG.min_profit_close, cost * CONFIG.spread_profit_multiplier):.4f}")
        print(f"M15 trend:     {trend or 'none'} ({strength:.0%})")
        print(f"In session:    {session}")
        print("OK — ready to run bot.py")
    except Exception as exc:
        print(f"FAILED: {exc}")
        sys.exit(1)
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
