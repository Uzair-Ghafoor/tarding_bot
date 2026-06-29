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

    symbol: str = os.getenv("MT5_SYMBOL", "XAUUSDT")
    symbol_fallbacks: list[str] = field(
        default_factory=lambda: os.getenv(
            "MT5_SYMBOL_FALLBACKS", "XAUUSDT,XAUUSDTm,XAUUSD,XAUUSDm"
        ).split(",")
    )
    lot_size: float = _env_float("MT5_LOT", 0.01)
    magic: int = _env_int("MT5_MAGIC", 880001)

    reference_balance: float = _env_float("MT5_REFERENCE_BALANCE", 30.0)

    basket_size: int = _env_int("MT5_BASKET_SIZE", 10)
    basket_min_profit: float = _env_float("MT5_BASKET_MIN_PROFIT", 0.0)
    basket_max_loss: float = _env_float("MT5_BASKET_MAX_LOSS", 0.0)
    batch_open_delay: float = _env_float("MT5_BATCH_OPEN_DELAY", 0.5)
    entry_cooldown_seconds: int = _env_int("MT5_ENTRY_COOLDOWN", 90)
    post_basket_cooldown_seconds: int = _env_int("MT5_POST_BASKET_COOLDOWN", 120)
    basket_fill_timeout_seconds: int = _env_int("MT5_BASKET_FILL_TIMEOUT", 45)

    min_open_trades: int = _env_int("MT5_MIN_TRADES", 0)
    max_open_trades: int = _env_int("MT5_MAX_TRADES", 0)

    stop_loss_points: int = _env_int("MT5_STOP_LOSS_POINTS", 0)
    max_hold_seconds: int = _env_int("MT5_MAX_HOLD_SECONDS", 900)
    max_spread_points: int = _env_int("MT5_MAX_SPREAD_POINTS", 45)

    max_daily_loss: float = _env_float("MT5_MAX_DAILY_LOSS", 0.0)
    use_loss_pause: bool = _env_bool("MT5_USE_LOSS_PAUSE", False)
    max_consecutive_losses: int = _env_int("MT5_MAX_CONSEC_LOSSES", 3)
    loss_pause_seconds: int = _env_int("MT5_LOSS_PAUSE_SECONDS", 1800)

    min_confluence_score: int = _env_int("MT5_MIN_SCORE", 75)
    min_score_m5_fallback: int = _env_int("MT5_MIN_SCORE_FALLBACK", 85)
    allow_m5_fallback: bool = _env_bool("MT5_M5_FALLBACK", True)
    require_h1_bias: bool = _env_bool("MT5_REQUIRE_H1", True)

    h1_ema_period: int = 50
    trend_ema_fast: int = 20
    trend_ema_slow: int = 50
    m5_ema_fast: int = 8
    m5_ema_slow: int = 21
    m5_ema_period: int = 21

    atr_period: int = 14
    atr_spike_mult: float = _env_float("MT5_ATR_SPIKE", 1.85)
    atr_tp_mult: float = _env_float("MT5_ATR_TP_MULT", 0.35)
    atr_sl_mult: float = _env_float("MT5_ATR_SL_MULT", 0.70)
    use_atr_targets: bool = _env_bool("MT5_USE_ATR_TARGETS", True)

    adx_period: int = 14
    adx_min: float = _env_float("MT5_ADX_MIN", 22.0)
    adx_strong: float = _env_float("MT5_ADX_STRONG", 25.0)

    bb_period: int = 20
    bb_std: float = _env_float("MT5_BB_STD", 2.0)
    zscore_max_buy: float = _env_float("MT5_ZSCORE_MAX", 0.85)
    zscore_min_buy: float = _env_float("MT5_ZSCORE_MIN", -2.0)
    zscore_max_sell: float = _env_float("MT5_ZSCORE_MAX_SELL", 1.8)
    # M5 sell entry relax (0=strict, 1=mild downtrend bypass)
    m5_sell_relax: int = _env_int("MT5_M5_SELL_RELAX", 0)
    m5_sell_ema_tol_pct: float = _env_float("MT5_M5_SELL_EMA_TOL", 0.0)
    m5_sell_relax_z_floor: float = _env_float("MT5_M5_SELL_RELAX_Z_FLOOR", -2.0)
    post_sl_cooldown_seconds: int = _env_int("MT5_POST_SL_COOLDOWN", 75)
    startup_warmup_scans: int = _env_int("MT5_STARTUP_WARMUP_SCANS", 3)
    atr_sl_vol_threshold: float = _env_float("MT5_ATR_SL_VOL_THRESHOLD", 1.75)
    atr_sl_vol_boost: float = _env_float("MT5_ATR_SL_VOL_BOOST", 1.25)
    slope_period: int = 20

    rsi_period: int = 14
    rsi_buy_min: float = 40.0
    rsi_buy_max: float = 60.0
    rsi_sell_min: float = 35.0
    rsi_sell_max: float = 60.0
    ema_period: int = 9

    # Quant risk math
    risk_per_basket_pct: float = _env_float("MT5_RISK_PCT", 0.03)
    kelly_fraction: float = _env_float("MT5_KELLY_FRAC", 0.5)
    min_baskets_for_kelly: int = _env_int("MT5_MIN_BASKETS_KELLY", 8)
    min_baskets_for_ev: int = _env_int("MT5_MIN_BASKETS_EV", 6)
    min_expectancy: float = _env_float("MT5_MIN_EV", 0.0)
    use_ev_gate: bool = _env_bool("MT5_USE_EV_GATE", True)

    use_session_filter: bool = _env_bool("MT5_USE_SESSION", True)
    session_windows_utc: list[tuple[float, float]] = field(
        default_factory=lambda: [(7.0, 11.0), (12.0, 17.0)]
    )

    poll_seconds: float = _env_float("MT5_POLL_SECONDS", 0.5)
    basket_price_sec: float = _env_float("MT5_BASKET_PRICE_SEC", 0.25)
    demo_only: bool = _env_bool("MT5_DEMO_ONLY", True)

    def __post_init__(self) -> None:
        if not self.min_open_trades:
            self.min_open_trades = self.basket_size
        if not self.max_open_trades:
            self.max_open_trades = self.basket_size
        if self.basket_min_profit <= 0:
            self.basket_min_profit = round(self.reference_balance * 0.015, 2)
        if self.basket_max_loss <= 0:
            self.basket_max_loss = round(self.reference_balance * 0.03, 2)


CONFIG = MT5Config()
