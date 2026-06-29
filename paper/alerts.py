"""Sound alerts and live console banners for paper trading."""

from __future__ import annotations

import subprocess
import sys


def notify_mac(title: str, message: str, sound: str = "Glass") -> None:
    """macOS notification banner."""
    if sys.platform != "darwin":
        return
    safe_t = title.replace('"', "'")[:60]
    safe_m = message.replace('"', "'")[:200]
    try:
        subprocess.Popen(
            ["osascript", "-e", f'display notification "{safe_m}" with title "{safe_t}" sound name "{sound}"'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def play_sound(event: str, pnl: float | None = None, enabled: bool = True) -> None:
    """Play a short alert. Mac uses afplay; others use terminal bell."""
    if not enabled:
        return
    if sys.platform == "darwin":
        if event == "open":
            name = "Glass.aiff"
        elif event == "close":
            name = "Hero.aiff" if (pnl is not None and pnl >= 0) else "Basso.aiff"
        else:
            name = "Pop.aiff"
        path = f"/System/Library/Sounds/{name}"
        try:
            subprocess.Popen(
                ["afplay", path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            print("\a", end="", flush=True)
    else:
        print("\a", end="", flush=True)


def banner_open(pair: str, side: str, price: float, score: int, adx: float, rsi: float, tp: float, sl: float) -> None:
    bar = "=" * 62
    print(f"\n{bar}", flush=True)
    print(f"  >>> PAPER BASKET OPEN  |  {pair}  {side.upper()}  @ {price:.5f}", flush=True)
    print(f"  score={score}  ADX={adx:.0f}  RSI={rsi:.0f}  |  TP +${tp:.2f}  SL -${sl:.2f}", flush=True)
    print(f"{bar}\n", flush=True)


def banner_close(side: str, reason: str, pnl: float, balance: float) -> None:
    bar = "=" * 62
    tag = "WIN" if pnl >= 0 else "LOSS"
    print(f"\n{bar}", flush=True)
    print(f"  <<< PAPER BASKET CLOSE [{tag}]  |  {side.upper()}  |  {reason}", flush=True)
    print(f"  P/L ${pnl:+.2f}  |  balance ${balance:.2f}", flush=True)
    print(f"{bar}\n", flush=True)
