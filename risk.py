"""Risk controls — Kelly cap, expectancy gate, loss pause."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from config import CONFIG
from performance import BasketStats, load_basket_stats
from quant import kelly_fraction


@dataclass
class RiskState:
    consecutive_losses: int = 0
    paused_until: float = 0.0
    wins: int = 0
    losses: int = 0
    session_wins: float = 0.0
    session_losses: float = 0.0
    stats: BasketStats = field(default_factory=load_basket_stats)

    def refresh_stats(self) -> None:
        self.stats = load_basket_stats()

    def record_close(self, profit: float) -> None:
        if profit >= 0:
            self.wins += 1
            self.session_wins += profit
            self.consecutive_losses = 0
        else:
            self.losses += 1
            self.session_losses += abs(profit)
            self.consecutive_losses += 1
            if self.consecutive_losses >= CONFIG.max_consecutive_losses:
                self.paused_until = time.time() + CONFIG.loss_pause_seconds
        self.refresh_stats()

    def can_trade(self) -> bool:
        return time.time() >= self.paused_until

    def pause_remaining(self) -> int:
        return max(0, int(self.paused_until - time.time()))

    @property
    def win_rate(self) -> float:
        total = self.wins + self.losses
        return self.wins / total if total else self.stats.win_rate

    def expectancy_ok(self) -> bool:
        """Block new entries when historical EV is negative (enough samples)."""
        if not CONFIG.use_ev_gate:
            return True
        s = self.stats
        if s.baskets < CONFIG.min_baskets_for_ev:
            return True
        return s.expectancy >= CONFIG.min_expectancy

    def kelly_risk_cap(self) -> float:
        """
        Max fraction of reference balance to risk per basket (half-Kelly cap).
        Returns CONFIG.risk_per_basket_pct if insufficient history.
        """
        s = self.stats
        if s.baskets < CONFIG.min_baskets_for_kelly:
            return CONFIG.risk_per_basket_pct
        k = kelly_fraction(s.win_rate, s.avg_win, s.avg_loss, CONFIG.kelly_fraction)
        if k <= 0:
            return CONFIG.risk_per_basket_pct * 0.5
        return min(CONFIG.risk_per_basket_pct, k)

    def profit_factor(self) -> float:
        return self.stats.pf
