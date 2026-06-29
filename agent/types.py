from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Action = Literal["open_buy", "open_sell", "skip", "hold", "close"]


@dataclass
class Decision:
    action: Action
    confidence: float
    reasoning: str
    source: str  # claude | rules
    vetoed_quant: bool = False


@dataclass
class BasketState:
    active: bool = False
    side: str | None = None
    entry_price: float = 0.0
    mark_pnl: float = 0.0
    tp: float = 0.0
    sl: float = 0.0
    held_sec: int = 0


@dataclass
class SessionStats:
    scans: int = 0
    decisions: int = 0
    opens: int = 0
    closes: int = 0
    skips: int = 0
    balance: float = 0.0
    session_pnl: float = 0.0
    recent_trades: list[dict] = field(default_factory=list)
