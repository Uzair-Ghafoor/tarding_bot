"""Trading session filter — trade only liquid Exness hours (UTC)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config import CONFIG

PKT = ZoneInfo("Asia/Karachi")

# (UTC start, UTC end, label, PKT label)
SESSION_WINDOWS = [
    (7.0, 11.0, "London", "12:00–16:00 PKT"),
    (12.0, 17.0, "New York", "17:00–22:00 PKT"),
]


def in_trading_session(now: datetime | None = None) -> bool:
    if not CONFIG.use_session_filter:
        return True
    now = now or datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60.0
    for start, end in CONFIG.session_windows_utc:
        if start <= hour < end:
            return True
    return False


def active_session_name(now: datetime | None = None) -> str | None:
    now = now or datetime.now(timezone.utc)
    hour = now.hour + now.minute / 60.0
    for start, end, name, _ in SESSION_WINDOWS:
        if start <= hour < end:
            return name
    return None


def session_status(now: datetime | None = None) -> dict:
    """Market session info for UI — independent of bot filter setting."""
    now = now or datetime.now(timezone.utc)
    now_pkt = now.astimezone(PKT)
    hour = now.hour + now.minute / 60.0
    active = active_session_name(now)
    in_window = active is not None

    next_open: datetime | None = None
    next_label = ""
    if not in_window:
        for start, _, name, pkt in SESSION_WINDOWS:
            candidate = now.replace(hour=int(start), minute=int((start % 1) * 60), second=0, microsecond=0)
            if candidate <= now:
                candidate += timedelta(days=1)
            if next_open is None or candidate < next_open:
                next_open = candidate
                next_label = f"{name} ({pkt})"

    return {
        "utc": now.strftime("%H:%M UTC"),
        "pkt": now_pkt.strftime("%H:%M PKT"),
        "active_name": active,
        "market_open": in_window,
        "next_open_utc": next_open.strftime("%H:%M UTC") if next_open else "",
        "next_open_pkt": next_open.astimezone(PKT).strftime("%H:%M PKT") if next_open else "",
        "next_label": next_label,
        "windows": [
            {"name": n, "pkt": p, "active": n == active}
            for _, _, n, p in SESSION_WINDOWS
        ],
    }

