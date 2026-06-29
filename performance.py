"""Load basket history and compute Kelly, EV, profit factor."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from quant import expected_value, kelly_fraction, profit_factor


@dataclass
class BasketStats:
    baskets: int = 0
    wins: int = 0
    losses: int = 0
    gross_wins: float = 0.0
    gross_losses: float = 0.0
    net_pnl: float = 0.0
    win_pnls: list[float] = field(default_factory=list)
    loss_pnls: list[float] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return self.wins / self.baskets if self.baskets else 0.0

    @property
    def avg_win(self) -> float:
        return self.gross_wins / self.wins if self.wins else 0.0

    @property
    def avg_loss(self) -> float:
        return self.gross_losses / self.losses if self.losses else 0.0

    @property
    def expectancy(self) -> float:
        if not self.baskets:
            return 0.0
        return expected_value(self.win_rate, self.avg_win, self.avg_loss)

    @property
    def pf(self) -> float:
        return profit_factor(self.gross_wins, self.gross_losses)

    @property
    def half_kelly(self) -> float:
        if self.baskets < 5:
            return 0.0
        return kelly_fraction(self.win_rate, self.avg_win, self.avg_loss, fraction=0.5)

    @property
    def reward_risk(self) -> float:
        if self.avg_loss <= 0:
            return 0.0
        return self.avg_win / self.avg_loss


def load_basket_stats(path: str | None = None) -> BasketStats:
    base = os.path.dirname(__file__)
    path = path or os.path.join(base, "data", "trades.jsonl")
    stats = BasketStats()
    if not os.path.isfile(path):
        return stats

    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("event") != "close_basket":
                continue
            pnl = float(row.get("total_profit", 0))
            stats.baskets += 1
            stats.net_pnl += pnl
            if pnl >= 0:
                stats.wins += 1
                stats.gross_wins += pnl
                stats.win_pnls.append(pnl)
            else:
                stats.losses += 1
                stats.gross_losses += abs(pnl)
                stats.loss_pnls.append(abs(pnl))
    return stats
