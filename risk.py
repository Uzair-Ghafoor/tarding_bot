"""Risk controls — daily loss, consecutive losses, session limits."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from config import CONFIG


@dataclass
class RiskState:
    consecutive_losses: int = 0
    paused_until: float = 0.0
    wins: int = 0
    losses: int = 0

    def record_close(self, profit: float) -> None:
        if profit >= 0:
            self.wins += 1
            self.consecutive_losses = 0
        else:
            self.losses += 1
            self.consecutive_losses += 1
            if self.consecutive_losses >= CONFIG.max_consecutive_losses:
                self.paused_until = time.time() + CONFIG.loss_pause_seconds

    def can_trade(self) -> bool:
        return time.time() >= self.paused_until

    def pause_remaining(self) -> int:
        return max(0, int(self.paused_until - time.time()))

    @property
    def win_rate(self) -> float:
        total = self.wins + self.losses
        return self.wins / total if total else 0.0
