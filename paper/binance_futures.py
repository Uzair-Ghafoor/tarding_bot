"""Binance USDT-M futures client — testnet or live signed REST."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from config import CONFIG
from paper.feed import _ssl_ctx
from paper.fees import paper_qty_oz

LIVE_BASE = "https://fapi.binance.com"
TESTNET_BASE = "https://testnet.binancefuture.com"


@dataclass
class FillResult:
    symbol: str
    side: str
    qty: float
    avg_price: float
    order_id: int
    realized_pnl: float = 0.0
    commission: float = 0.0

    @property
    def net_pnl(self) -> float:
        return self.realized_pnl - self.commission


@dataclass
class PositionInfo:
    symbol: str
    side: str  # buy | sell
    qty: float
    entry_price: float
    unrealized_pnl: float


class BinanceFuturesClient:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        testnet: bool = True,
        leverage: int = 5,
    ) -> None:
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.base = TESTNET_BASE if testnet else LIVE_BASE
        self.leverage = max(1, leverage)
        self._lot_rules: dict[str, dict[str, float]] = {}
        self._ctx = _ssl_ctx()

    def _sign(self, params: dict[str, Any]) -> str:
        query = urllib.parse.urlencode(params)
        sig = hmac.new(
            self.api_secret.encode(),
            query.encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"{query}&signature={sig}"

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        signed: bool = False,
    ) -> Any:
        params = dict(params or {})
        url = f"{self.base}{path}"
        headers = {"X-MBX-APIKEY": self.api_key}
        data: bytes | None = None

        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = 10000
            body = self._sign(params)
            if method == "GET":
                url = f"{url}?{body}"
            else:
                data = body.encode()
                headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15, context=self._ctx) as resp:
                raw = resp.read().decode()
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return raw
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()
            raise RuntimeError(f"Binance {method} {path} failed ({exc.code}): {detail}") from exc

    def load_symbol_rules(self, symbol: str) -> dict[str, float]:
        if symbol in self._lot_rules:
            return self._lot_rules[symbol]
        data = self._request("GET", "/fapi/v1/exchangeInfo")
        for item in data.get("symbols", []):
            if item["symbol"] != symbol:
                continue
            rules = {"step": 0.001, "min_qty": 0.001, "min_notional": 5.0}
            for filt in item.get("filters", []):
                if filt["filterType"] == "LOT_SIZE":
                    rules["step"] = float(filt["stepSize"])
                    rules["min_qty"] = float(filt["minQty"])
                elif filt["filterType"] == "MIN_NOTIONAL":
                    rules["min_notional"] = float(filt.get("notional", 5))
            self._lot_rules[symbol] = rules
            return rules
        raise ValueError(f"Symbol {symbol} not found on Binance futures")

    def round_qty(self, symbol: str, qty: float) -> float:
        rules = self.load_symbol_rules(symbol)
        step = rules["step"]
        precision = max(0, len(str(step).rstrip("0").split(".")[-1]) if "." in str(step) else 0)
        rounded = (int(qty / step)) * step
        rounded = round(rounded, precision)
        return max(rounded, rules["min_qty"])

    def basket_qty(self, symbol: str, price: float) -> float:
        qty = paper_qty_oz(price)
        qty = self.round_qty(symbol, qty)
        rules = self.load_symbol_rules(symbol)
        if qty * price < rules["min_notional"]:
            qty = self.round_qty(symbol, rules["min_notional"] / price * 1.01)
        return qty

    def ensure_leverage(self, symbol: str) -> None:
        try:
            self._request(
                "POST",
                "/fapi/v1/leverage",
                {"symbol": symbol, "leverage": self.leverage},
                signed=True,
            )
        except RuntimeError:
            pass

    def sign_tradfi_agreement(self) -> None:
        """Required once per account before trading XAUUSDT and other TradFi perps."""
        self._request("POST", "/fapi/v1/stock/contract", {}, signed=True)

    def _fill_pnl(self, symbol: str, order_id: int) -> tuple[float, float]:
        rows = self._request(
            "GET", "/fapi/v1/userTrades",
            {"symbol": symbol, "orderId": order_id},
            signed=True,
        )
        realized = sum(float(r.get("realizedPnl", 0)) for r in rows)
        commission = sum(float(r.get("commission", 0)) for r in rows)
        return realized, commission

    def get_usdt_balance(self) -> float:
        rows = self._request("GET", "/fapi/v2/balance", signed=True)
        for row in rows:
            if row.get("asset") == "USDT":
                return float(row.get("balance", 0))
        return 0.0

    def get_position(self, symbol: str) -> PositionInfo | None:
        rows = self._request("GET", "/fapi/v2/positionRisk", {"symbol": symbol}, signed=True)
        for row in rows:
            if row.get("symbol") != symbol:
                continue
            amt = float(row.get("positionAmt", 0))
            if abs(amt) < 1e-9:
                return None
            side = "buy" if amt > 0 else "sell"
            return PositionInfo(
                symbol=symbol,
                side=side,
                qty=abs(amt),
                entry_price=float(row.get("entryPrice", 0)),
                unrealized_pnl=float(row.get("unRealizedProfit", 0)),
            )
        return None

    def _fmt_qty(self, symbol: str, qty: float) -> str:
        rules = self.load_symbol_rules(symbol)
        step = rules["step"]
        prec = max(0, len(str(step).rstrip("0").split(".")[-1]) if "." in str(step) else 0)
        return f"{qty:.{prec}f}"

    def open_market(self, symbol: str, side: str, price: float) -> FillResult:
        self.ensure_leverage(symbol)
        qty = self.basket_qty(symbol, price)
        order_side = "BUY" if side == "buy" else "SELL"
        data = self._request(
            "POST",
            "/fapi/v1/order",
            {
                "symbol": symbol,
                "side": order_side,
                "type": "MARKET",
                "quantity": self._fmt_qty(symbol, qty),
            },
            signed=True,
        )
        order_id = int(data["orderId"])
        realized, commission = self._fill_pnl(symbol, order_id)
        return FillResult(
            symbol=symbol,
            side=side,
            qty=float(data.get("executedQty", qty)),
            avg_price=float(data.get("avgPrice", price)),
            order_id=order_id,
            realized_pnl=realized,
            commission=commission,
        )

    def close_market(self, symbol: str) -> FillResult | None:
        pos = self.get_position(symbol)
        if pos is None:
            return None
        close_side = "SELL" if pos.side == "buy" else "BUY"
        data = self._request(
            "POST",
            "/fapi/v1/order",
            {
                "symbol": symbol,
                "side": close_side,
                "type": "MARKET",
                "quantity": self._fmt_qty(symbol, pos.qty),
                "reduceOnly": "true",
            },
            signed=True,
        )
        order_id = int(data["orderId"])
        realized, commission = self._fill_pnl(symbol, order_id)
        return FillResult(
            symbol=symbol,
            side=pos.side,
            qty=float(data.get("executedQty", pos.qty)),
            avg_price=float(data.get("avgPrice", 0)),
            order_id=order_id,
            realized_pnl=realized,
            commission=commission,
        )


def create_binance_client(log) -> BinanceFuturesClient | None:
    if not CONFIG.binance_testnet:
        return None
    key = CONFIG.binance_api_key
    secret = CONFIG.binance_api_secret
    if not key or not secret:
        log.warning("BINANCE_TESTNET=true but BINANCE_API_KEY/SECRET missing — paper simulation only")
        return None
    client = BinanceFuturesClient(
        key,
        secret,
        testnet=True,
        leverage=CONFIG.binance_leverage,
    )
    client.load_symbol_rules(CONFIG.binance_symbol)
    try:
        client.sign_tradfi_agreement()
        log.info("BINANCE | TradFi-Perps agreement signed")
    except RuntimeError as exc:
        if "-4411" not in str(exc) and "SUCCESS" not in str(exc):
            log.warning("BINANCE | TradFi agreement: %s", exc)
    bal = client.get_usdt_balance()
    log.info(
        "BINANCE TESTNET | %s | leverage=%sx | wallet=$%.2f (display as $%.2f account)",
        CONFIG.binance_symbol,
        CONFIG.binance_leverage,
        bal,
        CONFIG.reference_balance,
    )
    return client
