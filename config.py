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
    # ----- Exness MT5 login -----
    login: int = _env_int("MT5_LOGIN", 0)
    password: str = os.getenv("MT5_PASSWORD", "")
    server: str = os.getenv("MT5_SERVER", "")  # copy from Exness PA e.g. Exness-MT5Trial9
    terminal_path: str = os.getenv(
        "MT5_PATH",
        r"C:\Program Files\MetaTrader 5\terminal64.exe",
    )

    # ----- Symbol (Exness: often EURUSDm or XAUUSDm — check Market Watch) -----
    symbol: str = os.getenv("MT5_SYMBOL", "EURUSDm")
    symbol_fallbacks: list[str] = field(
        default_factory=lambda: os.getenv(
            "MT5_SYMBOL_FALLBACKS", "EURUSD,XAUUSDm,XAUUSD"
        ).split(",")
    )
    lot_size: float = _env_float("MT5_LOT", 0.01)
    magic: int = _env_int("MT5_MAGIC", 880001)

    # ----- Basket mode: open N at once, close ALL on combined profit -----
    basket_size: int = _env_int("MT5_BASKET_SIZE", 10)
    basket_min_profit: float = _env_float("MT5_BASKET_MIN_PROFIT", 0.60)
    basket_max_loss: float = _env_float("MT5_BASKET_MAX_LOSS", 2.0)
    batch_open_delay: float = _env_float("MT5_BATCH_OPEN_DELAY", 0.4)

    # Legacy names — kept in sync with basket_size
    min_open_trades: int = _env_int("MT5_MIN_TRADES", 0)  # 0 = use basket_size
    max_open_trades: int = _env_int("MT5_MAX_TRADES", 0)
    entry_cooldown_seconds: int = _env_int("MT5_ENTRY_COOLDOWN", 15)

    # Per-ticket fallback (only if basket disabled)
    min_profit_close: float = _env_float("MT5_MIN_PROFIT_CLOSE", 0.12)
    min_profit_points: int = _env_int("MT5_MIN_PROFIT_POINTS", 0)
    spread_profit_multiplier: float = _env_float("MT5_SPREAD_PROFIT_MULT", 2.5)

    stop_loss_points: int = _env_int("MT5_STOP_LOSS_POINTS", 120)
    max_hold_seconds: int = _env_int("MT5_MAX_HOLD_SECONDS", 600)
    max_spread_points: int = _env_int("MT5_MAX_SPREAD_POINTS", 20)

    max_daily_loss: float = _env_float("MT5_MAX_DAILY_LOSS", 3.0)
    max_consecutive_losses: int = _env_int("MT5_MAX_CONSEC_LOSSES", 3)
    loss_pause_seconds: int = _env_int("MT5_LOSS_PAUSE_SECONDS", 1800)

    # ----- M15 trend filter -----
    trend_ema_fast: int = 20
    trend_ema_slow: int = 50
    trend_min_gap_pct: float = 0.0008
    trend_min_strength: float = 0.25

    # ----- M1 entry -----
    rsi_period: int = 7
    rsi_buy: float = 40.0
    rsi_sell: float = 60.0
    ema_period: int = 9

    # ----- Session (UTC) — London + NY overlap on Exness -----
    use_session_filter: bool = _env_bool("MT5_USE_SESSION", True)
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


CONFIG = MT5Config()
