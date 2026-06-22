"""Thin wrapper around the MetaTrader5 Python package."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable

import MetaTrader5 as mt5

from config import CONFIG

log = logging.getLogger("mt5bot")


class MT5Client:
    def __init__(self):
        self._connected = False

    def connect(self) -> None:
        init_kwargs = {}
        if CONFIG.terminal_path:
            init_kwargs["path"] = CONFIG.terminal_path
        if CONFIG.login:
            init_kwargs["login"] = CONFIG.login
            init_kwargs["password"] = CONFIG.password
            init_kwargs["server"] = CONFIG.server

        if not mt5.initialize(**init_kwargs):
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")

        acc = mt5.account_info()
        if acc is None:
            raise RuntimeError(f"MT5 account_info failed: {mt5.last_error()}")

        if CONFIG.demo_only and not acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
            mt5.shutdown()
            raise RuntimeError(
                "MT5_DEMO_ONLY=true but account is not demo. "
                "Use a demo login or set MT5_DEMO_ONLY=false."
            )

        self._connected = True
        log.info(
            "Connected | login=%s | server=%s | balance=%.2f %s | demo=%s",
            acc.login,
            acc.server,
            acc.balance,
            acc.currency,
            acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO,
        )

    def shutdown(self) -> None:
        if self._connected:
            mt5.shutdown()
            self._connected = False

    def ensure_symbol(self, symbol: str) -> None:
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"Symbol {symbol} not found: {mt5.last_error()}")
        if not info.visible:
            if not mt5.symbol_select(symbol, True):
                raise RuntimeError(f"symbol_select failed: {mt5.last_error()}")

    def tick(self, symbol: str):
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"No tick for {symbol}: {mt5.last_error()}")
        return tick

    def spread_points(self, symbol: str) -> int:
        info = mt5.symbol_info(symbol)
        tick = self.tick(symbol)
        if info is None or info.point <= 0:
            return 9999
        return int(round((tick.ask - tick.bid) / info.point))

    def estimated_spread_cost(self, symbol: str, lot: float) -> float:
        """Round-trip spread cost in account currency (approx)."""
        info = mt5.symbol_info(symbol)
        tick = self.tick(symbol)
        if info is None:
            return CONFIG.min_profit_close
        spread = tick.ask - tick.bid
        # tick_value × (spread/point) × lot — works for forex & metals on Exness
        if info.trade_tick_size > 0 and info.trade_tick_value > 0:
            ticks = spread / info.trade_tick_size
            return abs(ticks * info.trade_tick_value * lot)
        return spread * lot * 100000 * 0.5  # rough forex fallback

    def points_to_money(self, symbol: str, points: int, lot: float) -> float:
        info = mt5.symbol_info(symbol)
        if info is None or info.point <= 0:
            return float(points)
        move = points * info.point
        if info.trade_tick_size > 0 and info.trade_tick_value > 0:
            ticks = move / info.trade_tick_size
            return abs(ticks * info.trade_tick_value * lot)
        return move * lot * 100000

    def resolve_symbol(self, primary: str, fallbacks: list[str]) -> str:
        for sym in [primary] + [s.strip() for s in fallbacks if s.strip()]:
            info = mt5.symbol_info(sym)
            if info is not None:
                return sym
        raise RuntimeError(
            f"Symbol not found. Tried {primary} and fallbacks. "
            "Open Exness MT5 Market Watch and copy exact symbol name."
        )

    def positions(self, symbol: str | None = None) -> list:
        if symbol:
            pos = mt5.positions_get(symbol=symbol)
        else:
            pos = mt5.positions_get()
        if pos is None:
            err = mt5.last_error()
            if err[0] == 1:  # no results
                return []
            raise RuntimeError(f"positions_get failed: {err}")
        return [p for p in pos if p.magic == CONFIG.magic]

    def position_profit(self, ticket: int) -> float:
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return 0.0
        p = pos[0]
        return float(p.profit + p.swap + p.commission)

    def position_points(self, ticket: int) -> int:
        pos = mt5.positions_get(ticket=ticket)
        info = mt5.symbol_info(pos[0].symbol) if pos else None
        if not pos or info is None or info.point <= 0:
            return 0
        p = pos[0]
        if p.type == mt5.POSITION_TYPE_BUY:
            move = mt5.symbol_info_tick(p.symbol).bid - p.price_open
        else:
            move = p.price_open - mt5.symbol_info_tick(p.symbol).ask
        return int(round(move / info.point))

    # MQL5 symbol filling_mode bit flags (not exported as mt5.SYMBOL_FILLING_* in Python)
    _FILL_FOK = 1
    _FILL_IOC = 2
    _FILL_RETURN = 4

    def _filling_candidates(self, symbol: str) -> list[int]:
        """Order types to try for this symbol/broker (Exness often uses RETURN or FOK)."""
        info = mt5.symbol_info(symbol)
        if info is None:
            return [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
        mode = int(info.filling_mode)
        candidates: list[int] = []
        if mode & self._FILL_IOC:
            candidates.append(mt5.ORDER_FILLING_IOC)
        if mode & self._FILL_FOK:
            candidates.append(mt5.ORDER_FILLING_FOK)
        if mode & self._FILL_RETURN:
            candidates.append(mt5.ORDER_FILLING_RETURN)
        if not candidates:
            candidates = [
                mt5.ORDER_FILLING_RETURN,
                mt5.ORDER_FILLING_FOK,
                mt5.ORDER_FILLING_IOC,
            ]
        return candidates

    def _send(self, request: dict):
        symbol = request["symbol"]
        last_result = None
        for filling in self._filling_candidates(symbol):
            request["type_filling"] = filling
            result = mt5.order_send(request)
            if result is None:
                log.error("order_send returned None: %s", mt5.last_error())
                continue
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                return result
            last_result = result
            # Wrong filling mode — try next
            if result.retcode in (
                10030,  # invalid fill
                10016,  # invalid stops (not filling — stop retrying fills)
            ):
                if result.retcode == 10016:
                    break
                continue
        return last_result

    def open_market(
        self,
        symbol: str,
        side: str,
        lot: float,
        sl_points: int | None = None,
        comment: str = "micro",
    ) -> int | None:
        self.ensure_symbol(symbol)
        info = mt5.symbol_info(symbol)
        tick = self.tick(symbol)
        if side == "buy":
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
            sl = price - sl_points * info.point if sl_points else 0.0
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
            sl = price + sl_points * info.point if sl_points else 0.0

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": order_type,
            "price": price,
            "sl": sl or 0.0,
            "tp": 0.0,
            "deviation": 20,
            "magic": CONFIG.magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
        }
        result = self._send(request)
        if result is None:
            return None
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            log.warning(
                "Open %s failed | ret=%s | %s",
                side,
                result.retcode,
                result.comment,
            )
            return None
        log.info(
            "OPEN %s | ticket=%s | lot=%.2f | price=%.5f",
            side.upper(),
            result.order,
            lot,
            result.price,
        )
        return int(result.order)

    def close_position(self, ticket: int) -> bool:
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return False
        p = pos[0]
        tick = self.tick(p.symbol)
        if p.type == mt5.POSITION_TYPE_BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": p.symbol,
            "volume": p.volume,
            "type": order_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": CONFIG.magic,
            "comment": "close_profit",
            "type_time": mt5.ORDER_TIME_GTC,
        }
        profit = float(p.profit + p.swap + p.commission)
        result = self._send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            log.warning(
                "Close ticket=%s failed | ret=%s | %s",
                ticket,
                getattr(result, "retcode", None),
                getattr(result, "comment", mt5.last_error()),
            )
            return False
        log.info("CLOSE ticket=%s | profit=%.2f", ticket, profit)
        return True

    def rates_m1(self, symbol: str, count: int = 120):
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, count)
        if rates is None:
            raise RuntimeError(f"copy_rates failed: {mt5.last_error()}")
        return rates

    def today_closed_profit(self, symbol: str) -> float:
        start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        deals = mt5.history_deals_get(start, datetime.now(timezone.utc))
        if deals is None:
            return 0.0
        total = 0.0
        for d in deals:
            if d.symbol != symbol or d.magic != CONFIG.magic:
                continue
            if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT):
                total += d.profit + d.swap + d.commission
        return total

    def close_many(self, tickets: Iterable[int]) -> int:
        closed = 0
        for t in tickets:
            if self.close_position(t):
                closed += 1
        return closed
