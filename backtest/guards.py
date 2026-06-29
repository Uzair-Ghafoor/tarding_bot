"""Optional extra filters discovered from loss analysis."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TradeGuards:
    min_score: int = 75
    min_adx: float = 18.0
    block_fallback: bool = False
    max_z_buy: float = 1.2
    min_z_buy: float = -2.0
    max_z_sell: float = 1.2
    rsi_buy_max: float = 65.0
    rsi_buy_min: float = 40.0
    rsi_sell_min: float = 35.0
    rsi_sell_max: float = 60.0
    max_vol_ratio: float = 2.2
    notes: list[str] = field(default_factory=list)

    def label(self) -> str:
        parts = [f"score>={self.min_score}", f"ADX>={self.min_adx:.0f}"]
        if self.block_fallback:
            parts.append("no_fallback")
        return ", ".join(parts)
