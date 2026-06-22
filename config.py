"""MT5 Exness bot configuration. Secrets live in .env (local only)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val not in (None, "") else default


def _env_float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val not in (None, "") else default


@dataclass
class MT5Config:
    login: int = _env_int("MT5_LOGIN", 0)
    password: str = os.getenv("MT5_PASSWORD", "")
    server: str = os.getenv("MT5_SERVER", "")
    terminal_path: str = os.getenv(
        "MT5_PATH",
        r"C:\Program Files\MetaTrader 5\terminal64.exe",
    )

    symbol: str = os.getenv("MT5_SYMBOL", "XAUUSDm")
    symbol_fallbacks: list[str] = field(
        default_factory=lambda: os.getenv(
            "MT5_SYMBOL_FALLBACKS", "EURUSD,XAUUSDm,XAUUSD"
        ).split(",")
    )
    lot_size: float = _env_float("MT5_LOT", 0.01)
    magic: int = _env_int("MT5_MAGIC", 880001)

    # ----- $30-style demo testing -----
    # Exness demo may show $500k — we SIZE risk as if account were reference_balance
    reference_balance: float = _env_float("MT5_REFERENCE_BALANCE", 30.0)

    # Basket: open N trades together, close ALL on combined basket P/L only
    basket_size: int = _env_int("MT5_BASKET_SIZE", 10)
    basket_min_profit: float = _env_float("MT5_BASKET_MIN_PROFIT", 0.0)
    basket_max_loss: float = _env_float("MT5_BASKET_MAX_LOSS", 0.0)
    batch_open_delay: float = _env_float("MT5_BATCH_OPEN_DELAY", 0.4)
    entry_cooldown_seconds: int = _env_int("MT5_ENTRY_COOLDOWN", 30)

    min_open_trades: int = _env_int("MT5_MIN_TRADES", 0)
    max_open_trades: int = _env_int("MT5_MAX_TRADES", 0)

    stop_loss_points: int = _env_int("MT5_STOP_LOSS_POINTS", 250)
    max_hold_seconds: int = _env_int("MT5_MAX_HOLD_SECONDS", 1200)
    max_spread_points: int = _env_int("MT5_MAX_SPREAD_POINTS", 65)

    # 0 = disabled (demo testing)
    max_daily_loss: float = _env_float("MT5_MAX_DAILY_LOSS", 0.0)
    use_loss_pause: bool = _env_bool("MT5_USE_LOSS_PAUSE", False)
    max_consecutive_losses: int = _env_int("MT5_MAX_CONSEC_LOSSES", 3)
    loss_pause_seconds: int = _env_int("MT5_LOSS_PAUSE_SECONDS", 1800)

    # ----- Chart analysis / confluence -----
    min_confluence_score: int = _env_int("MT5_MIN_SCORE", 65)
    allow_m5_fallback: bool = _env_bool("MT5_M5_FALLBACK", True)
    trend_ema_fast: int = 20
    trend_ema_slow: int = 50
    trend_min_gap_pct: float = 0.0008
    m5_ema_period: int = 21

    rsi_period: int = 7
    rsi_buy: float = 45.0
    rsi_sell: float = 55.0
    rsi_no_sell_above: float = 55.0   # block shorts when RSI high (bounce)
    rsi_no_buy_below: float = 45.0
    ema_period: int = 9

    use_session_filter: bool = _env_bool("MT5_USE_SESSION", False)
    session_windows_utc: list[tuple[float, float]] = field(
        default_factory=lambda: [(7.0, 11.0), (12.0, 17.0)]
    )

    poll_seconds: float = _env_float("MT5_POLL_SECONDS", 0.5)
    demo_only: bool = _env_bool("MT5_DEMO_ONLY", True)

    def __post_init__(self) -> None:
        if not self.min_open_trades:
            self.min_open_trades = self.basket_size
        if not self.max_open_trades:
            self.max_open_trades = self.basket_size
        # Auto-scale basket targets from $30 reference if not set in .env
        if self.basket_min_profit <= 0:
            self.basket_min_profit = round(self.reference_balance * 0.015, 2)  # 1.5% = $0.45
        if self.basket_max_loss <= 0:
            self.basket_max_loss = round(self.reference_balance * 0.03, 2)  # 3% = $0.90


CONFIG = MT5Config()
