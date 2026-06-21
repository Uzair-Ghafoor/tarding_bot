"""Trading session filter — trade only liquid Exness hours (UTC)."""

from __future__ import annotations

from datetime import datetime, timezone

from config import CONFIG


def in_trading_session(now: datetime | None = None) -> bool:
    if not CONFIG.use_session_filter:
        return True
    now = now or datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60.0
    for start, end in CONFIG.session_windows_utc:
        if start <= hour < end:
            return True
    return False
