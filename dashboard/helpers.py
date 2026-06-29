"""Dashboard helpers — bias strip, basket state, notifications, UI logic."""

from __future__ import annotations

from datetime import datetime, timezone

from paper.fees import paper_pnl_spread
from backtest.engine import _pnl_at_price
from backtest.guards import TradeGuards
from backtest.pairs import PAIRS
from config import CONFIG
from paper.alerts import notify_mac

__all__ = [
    "notify_mac",
    "tf_bias_strip",
    "readiness_pct",
    "open_basket_state",
    "trade_markers",
    "why_waiting",
    "score_waterfall",
    "basket_pnl_gauge",
]

_BLOCKERS = {
    "ATR_spike": ("Volatility spike — ATR above max", "Wait for vol ratio to drop below cap"),
    "ADX_weak": ("Trend too weak", "ADX must rise above minimum threshold"),
    "H1_flat": ("H1 bias flat", "Price needs clear H1 direction vs EMA"),
    "H1_bearish": ("H1 bearish vs sell fallback", "Bullish H1 candle + M15 uptrend, or clean aligned sell"),
    "H1_bullish": ("H1 bullish but setup incomplete", "M15 trend + M5 pullback entry must confirm"),
    "H1_conflict": ("H1 vs entry side conflict", "M15/M5 side must match H1 bias"),
    "M15_no_trend": ("No M15 trend", "Wait for M15 EMA alignment and slope"),
    "M5_sell_relaxed": ("M5 sell relaxed (paper tune)", "Mild downtrend entry — step 1 filters"),
    "M5_reject": ("M5 entry rejected", "Need confirming H1 candle + fast/slow EMA alignment"),
    "M5_up_fallback": ("M5 buy fallback active", "Confirm bullish H1 bar + price above slow EMA"),
    "M5_down_fallback": ("M5 sell fallback active", "Confirm bearish H1 bar + price below slow EMA"),
    "guard_reject": ("Guard filter rejected", "RSI, Z-score, or score below threshold"),
    "warmup": ("Warming up indicators", "Need more history bars"),
}

_NEED_DEFAULT = "Aligned H1 + M15 + M5 pullback with score ≥ 75 and all gates pass"


def why_waiting(reasons: list[str], score: int, min_score: int, ready: bool) -> dict:
    if ready:
        return {
            "blocker": "None — all gates pass",
            "need": "Bot will open on next brain confirm",
            "score_gap": f"{score} / {min_score} ✓",
        }
    rs = reasons or []
    primary = next((r for r in rs if r in _BLOCKERS), rs[0] if rs else "waiting")
    blocker, need = _BLOCKERS.get(primary, (primary.replace("_", " ").title(), _NEED_DEFAULT))
    gap = max(0, min_score - score)
    score_gap = f"{score} → {min_score} (+{gap} needed)" if gap else f"{score} / {min_score}"
    return {"blocker": blocker, "need": need, "score_gap": score_gap}


def score_waterfall(reasons: list[str], score: int, adx: float, min_score: int) -> list[dict]:
    """Approximate score path from setup reasons (mirrors signals.py stages)."""
    rs = set(reasons or [])
    rows: list[dict] = []

    adx_pts = 10 if adx >= CONFIG.adx_strong else 5
    rows.append({"label": "ADX base", "pts": adx_pts})

    if "H1_bullish" in rs or "H1_bearish" in rs:
        rows.append({"label": "H1 bias", "pts": 15})
    elif "H1_flat" in rs:
        rows.append({"label": "H1 bias", "pts": 0, "blocked": True})
    else:
        rows.append({"label": "H1 bias", "pts": 0})

    m15_pts = 0
    if "M15_up" in rs or "M15_down" in rs:
        m15_pts = 30
        if any(r in rs for r in ("M15_above_fast",)):
            m15_pts += 10
        if any(x in rs for x in ("M15_up", "M15_down")):
            m15_pts = min(m15_pts + 18, 58)
        rows.append({"label": "M15 trend", "pts": min(m15_pts, 58)})
    elif "M15_no_trend" in rs:
        rows.append({"label": "M15 trend", "pts": 0, "blocked": True})
    else:
        rows.append({"label": "M15 trend", "pts": 0})

    if "M5_up_fallback" in rs or "M5_down_fallback" in rs:
        rows.append({"label": "M5 fallback", "pts": 15})
    if "M5_reject" in rs:
        rows.append({"label": "M5 entry confirm", "pts": None, "blocked": True})
    elif "M5_up_fallback" in rs or "M5_down_fallback" in rs:
        rows.append({"label": "M5 entry confirm", "pts": 15})

    # Remaining points inferred
    accounted = sum(r["pts"] for r in rows if r.get("pts") is not None and not r.get("blocked"))
    remainder = max(0, score - accounted)
    if remainder > 0:
        rows.append({"label": "Z / RSI / M1", "pts": remainder})
    elif score > accounted and not any(r.get("blocked") for r in rows):
        rows.append({"label": "Z / RSI / M1 (pending)", "pts": 0})

    if "ATR_spike" in rs:
        rows = [{"label": "ATR spike", "pts": None, "blocked": True}]
    if "ADX_weak" in rs:
        rows = [{"label": "ADX weak", "pts": None, "blocked": True}]
    if "H1_conflict" in rs:
        rows.append({"label": "H1 conflict", "pts": None, "blocked": True})

    return rows


def basket_pnl_gauge(basket: dict, c: dict) -> str:
    pnl = basket["mark_pnl"]
    tp, sl = basket["tp"], basket["sl"]
    # Map P/L from -sl..+tp to 0..100%
    if pnl >= 0:
        pct = 50 + min(50, (pnl / max(tp, 0.01)) * 50)
        fill_col = c["green"]
    else:
        pct = 50 - min(50, (abs(pnl) / max(sl, 0.01)) * 50)
        fill_col = c["red"]
    pnl_c = c["green"] if pnl >= 0 else c["red"]
    return (
        f'<div class="pnl-gauge">'
        f'<div style="display:flex;justify-content:space-between;font-size:11px;color:{c["muted"]};margin-bottom:4px">'
        f'<span>SL -${sl:.2f}</span><span style="color:{pnl_c};font-weight:700">Mark ${pnl:+.2f}</span><span>TP +${tp:.2f}</span></div>'
        f'<div class="pnl-track">'
        f'<div class="pnl-fill" style="left:0;width:{pct}%;background:{fill_col};opacity:0.5"></div>'
        f'<div class="pnl-marker" style="left:calc({pct}% - 1px)"></div>'
        f'</div></div>'
    )


def tf_bias_strip(reasons: list[str]) -> dict[str, dict]:
    """H1 / M15 / M5 bias tiles from setup reasons."""
    rs = set(reasons or [])

    def _h1():
        if any(r in rs for r in ("H1_bullish",)):
            return "buy", "BULL", True
        if any(r in rs for r in ("H1_bearish",)):
            return "sell", "BEAR", True
        return None, "FLAT", False

    def _m15():
        if any(r in rs for r in ("M15_up", "M15_above_fast", "M15_slope_up")):
            return "buy", "UP", True
        if any(r in rs for r in ("M15_down", "M15_below_fast", "M15_slope_down")):
            return "sell", "DOWN", True
        return None, "FLAT", False

    def _m5():
        if any(r in rs for r in ("M5_up_fallback",)):
            return "buy", "PULLBACK", True
        if any(r in rs for r in ("M5_down_fallback",)):
            return "sell", "PULLBACK", True
        if "M5_reject" in rs:
            return None, "REJECT", False
        if any(s for s in rs if s.startswith("M15")):
            return "buy" if "M15_up" in rs else ("sell" if "M15_down" in rs else None), "SIGNAL", True
        return None, "WAIT", False

    h1s, h1l, h1ok = _h1()
    m15s, m15l, m15ok = _m15()
    m5s, m5l, m5ok = _m5()
    return {
        "H1": {"side": h1s, "label": h1l, "ok": h1ok},
        "M15": {"side": m15s, "label": m15l, "ok": m15ok},
        "M5": {"side": m5s, "label": m5l, "ok": m5ok},
    }


def readiness_pct(gates_passed: int, gates_total: int, adx: float, adx_min: float, score: int, score_min: int) -> float:
    gate_part = gates_passed / max(gates_total, 1)
    adx_part = min(1.0, adx / adx_min) if adx_min else 0
    score_part = min(1.0, score / score_min) if score_min else 0
    return round((gate_part * 0.5 + adx_part * 0.3 + score_part * 0.2) * 100, 1)


from paper.basket_state import find_open_row


def open_basket_state(trades: list[dict], pair: str, price: float) -> dict | None:
    """Return open basket only if the latest open for this pair has no matching close."""
    ob = find_open_row(trades, pair)
    if ob is None:
        return None
    spec = PAIRS.get(pair, PAIRS["XAUUSDT"])
    side = ob.get("side", "buy")
    entry = float(ob.get("price", price))
    tp = float(ob.get("tp", CONFIG.basket_min_profit))
    sl = float(ob.get("sl", CONFIG.basket_max_loss))
    spread = paper_pnl_spread(spec, CONFIG.basket_size)
    mark = _pnl_at_price(spec, side, entry, price, CONFIG.basket_size, spread)
    open_fees = float(ob.get("fees", 0))
    mark -= open_fees
    try:
        opened = datetime.fromisoformat(ob["ts"].replace("Z", "+00:00"))
        held = int((datetime.now(timezone.utc) - opened).total_seconds())
    except (KeyError, ValueError):
        held = 0
    return {
        "side": side,
        "entry": entry,
        "tp": tp,
        "sl": sl,
        "mark_pnl": mark,
        "held_sec": held,
        "score": ob.get("score", 0),
        "ts": ob.get("ts", ""),
    }


def trade_markers(trades: list[dict], pair: str) -> list[dict]:
    markers = []
    for t in trades:
        ev = t.get("event")
        if ev not in ("open_basket", "close_basket"):
            continue
        if t.get("pair") and t.get("pair") != pair:
            continue
        markers.append({
            "ts": t.get("ts"),
            "event": ev,
            "side": t.get("side", ""),
            "price": float(t.get("price", t.get("total_profit", 0)) or 0),
            "pnl": float(t.get("total_profit", 0)) if ev == "close_basket" else None,
            "reason": t.get("reason", ""),
        })
    return markers[-20:]
