"""Thin wrapper around the MetaTrader5 Python package."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Iterable

import MetaTrader5 as mt5

from config import CONFIG

log = logging.getLogger("mt5bot")


def _net_profit(obj) -> float:
    """profit + swap (+ commission if present — not on all MT5 Python builds)."""
    profit = float(getattr(obj, "profit", 0.0) or 0.0)
    swap = float(getattr(obj, "swap", 0.0) or 0.0)
    commission = float(getattr(obj, "commission", 0.0) or 0.0)
    return profit + swap + commission


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
        return acc.balance

    def account_balance(self) -> float:
        acc = mt5.account_info()
        return float(acc.balance) if acc else 0.0

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
            return CONFIG.min_profit_close if hasattr(CONFIG, "min_profit_close") else 0.1
        spread = tick.ask - tick.bid
        if info.trade_tick_size > 0 and info.trade_tick_value > 0:
            ticks = spread / info.trade_tick_size
            return abs(ticks * info.trade_tick_value * lot)
        return spread * lot * 100000 * 0.5

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
            if err[0] == 1:
                return []
            raise RuntimeError(f"positions_get failed: {err}")
        return [p for p in pos if p.magic == CONFIG.magic]

    def position_profit(self, ticket: int) -> float:
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return 0.0
        return _net_profit(pos[0])

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

    _FILL_FOK = 1
    _FILL_IOC = 2
    _FILL_RETURN = 4

    def _filling_candidates(self, symbol: str) -> list[int]:
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

    def _min_stop_distance(self, symbol: str) -> float:
        info = mt5.symbol_info(symbol)
        if info is None or info.point <= 0:
            return 0.0
        level = max(int(info.trade_stops_level or 0), int(info.trade_freeze_level or 0))
        return level * info.point

    def _valid_sl(self, symbol: str, side: str, price: float, sl_points: int) -> float:
        """Return SL price or 0.0 if SL invalid / disabled."""
        if sl_points <= 0:
            return 0.0
        info = mt5.symbol_info(symbol)
        if info is None or info.point <= 0:
            return 0.0
        min_dist = max(self._min_stop_distance(symbol), sl_points * info.point)
        if side == "buy":
            return price - min_dist
        return price + min_dist

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
            if result.retcode in (10030, 10016):
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
        tick = self.tick(symbol)
        sl_pts = sl_points if sl_points is not None else CONFIG.stop_loss_points

        if side == "buy":
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid

        sl = self._valid_sl(symbol, side, price, sl_pts)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": 0.0,
            "deviation": 30,
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
            return True
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
            "deviation": 30,
            "magic": CONFIG.magic,
            "comment": "close_basket",
            "type_time": mt5.ORDER_TIME_GTC,
        }
        profit = _net_profit(p)
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

    def rates(self, symbol: str, timeframe: int, count: int = 120):
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None:
            raise RuntimeError(f"copy_rates failed: {mt5.last_error()}")
        return rates

    def rates_m1(self, symbol: str, count: int = 120):
        return self.rates(symbol, mt5.TIMEFRAME_M1, count)

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
                total += _net_profit(d)
        return total

    def close_many(self, tickets: Iterable[int], retries: int = 3) -> int:
        remaining = list(tickets)
        closed = 0
        for _ in range(retries):
            if not remaining:
                break
            still_open: list[int] = []
            for ticket in remaining:
                if self.close_position(ticket):
                    closed += 1
                else:
                    still_open.append(ticket)
            remaining = still_open
            if remaining:
                time.sleep(0.4)
        return closed

    def close_all(self, symbol: str, retries: int = 3) -> int:
        """Close every bot position on symbol; refresh list each attempt."""
        closed = 0
        for _ in range(retries):
            positions = self.positions(symbol)
            if not positions:
                return closed
            tickets = [p.ticket for p in positions]
            batch = self.close_many(tickets, retries=1)
            closed += batch
            if not self.positions(symbol):
                return closed
            time.sleep(0.5)
        return closed
