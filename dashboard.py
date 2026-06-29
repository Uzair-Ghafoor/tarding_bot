#!/usr/bin/env python3
"""Live trading dashboard — streamlit run dashboard.py"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import streamlit.components.v1 as components

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from agent.metrics import gate_checklist
from agent.snapshot import build_snapshot
from backtest.pairs import PAIRS
from config import CONFIG
from dashboard.helpers import (
    basket_pnl_gauge,
    notify_mac,
    open_basket_state,
    readiness_pct,
    score_waterfall,
    tf_bias_strip,
    trade_markers,
    why_waiting,
)
from dashboard.ui_components import (
    THEMES,
    css_block,
    gate_cell_html,
    gate_progress_html,
    health_strip_html,
    keyboard_shortcuts_html,
    pair_readiness_cached,
    skip_timeline_chart,
    sparkline_svg_html,
    stat_box,
    waterfall_html,
    why_panel_html,
)
from paper.feed import build_frames, fetch_tick_price, refresh_live_bars, refresh_tick_only
from run_backtest import LIVE_GUARDS
from session import session_status

DATA_DIR = os.path.join(ROOT, "data")
LOG_DIR = os.path.join(ROOT, "logs")
PAPER_LOG = os.path.join(DATA_DIR, "paper_trades.jsonl")
AGENT_LOG = os.path.join(DATA_DIR, "agent_decisions.jsonl")
AUTO_LOG = os.path.join(LOG_DIR, "autopilot.log")
RUNTIME_FILE = os.path.join(DATA_DIR, "runtime.json")
STATUS_FILE = os.path.join(DATA_DIR, "status.json")
PAIR_TAB_ORDER = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD", "XAUUSDT"]
WATCH_PAIRS = [p for p in PAIR_TAB_ORDER if p in PAIRS]


def _read_status() -> dict:
    try:
        with open(STATUS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _bot_live_state(pair: str | None = None) -> dict:
    """What autopilot is actually doing — per pair in multi mode."""
    out = {"in_basket": False, "source": "none", "mark_pnl": None, "side": None}
    status = _read_status()
    if status:
        try:
            ts = datetime.fromisoformat(str(status.get("ts", "")).replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            if age < 120:
                if status.get("mode") == "multi" and pair:
                    ps = (status.get("pairs") or {}).get(pair, {})
                    if ps:
                        out["in_basket"] = bool(ps.get("in_basket"))
                        out["source"] = "status.json"
                        out["mark_pnl"] = ps.get("mark_pnl")
                        out["side"] = ps.get("side")
                        return out
                if not pair or status.get("pair") == pair:
                    out["in_basket"] = bool(status.get("in_basket"))
                    out["source"] = "status.json"
                    out["mark_pnl"] = status.get("mark_pnl")
                    out["side"] = status.get("side")
                    return out
        except (TypeError, ValueError):
            pass

    if not os.path.isfile(AUTO_LOG):
        return out
    try:
        with open(AUTO_LOG, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-200:]
        saw_open = False
        for line in reversed(lines):
            if "EXEC CLOSE" in line:
                out["in_basket"] = False
                out["source"] = "log"
                return out
            if "HOLD |" in line and "Managing open basket" in line:
                out["in_basket"] = True
                out["source"] = "log"
                m = re.search(r"mark=\$([+-]?[\d.]+)", line)
                if m:
                    out["mark_pnl"] = float(m.group(1))
                m2 = re.search(r"HOLD \| (\w+)", line)
                if m2:
                    out["side"] = m2.group(1)
                return out
            if "EXEC OPEN |" in line:
                saw_open = True
            if "SCAN #" in line and "OPEN=NO" in line and not saw_open:
                out["in_basket"] = False
                out["source"] = "log"
                return out
            if "SCAN #" in line and "OPEN=YES" in line:
                out["in_basket"] = True
                out["source"] = "log"
                return out
    except OSError:
        pass
    return out


def _c() -> dict:
    theme = st.session_state.get("theme", "dark")
    return THEMES.get(theme, THEMES["dark"])


st.set_page_config(page_title="ScalpBot", layout="wide", initial_sidebar_state="collapsed")


def _read_jsonl(path: str) -> list[dict]:
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def _read_runtime() -> dict:
    try:
        with open(RUNTIME_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _latest_scan_meta(pair: str | None = None) -> tuple[int, float]:
    if not os.path.isfile(AUTO_LOG):
        return 0, 999.0
    try:
        with open(AUTO_LOG, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-600:]
        for line in reversed(lines):
            if pair and f"| {pair} @" not in line and f"[{pair}]" not in line:
                if "SCAN #" in line and " | " in line:
                    continue
            m = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*SCAN #(\d+)", line)
            if m:
                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                age = (datetime.now() - ts).total_seconds()
                return int(m.group(2)), max(0.0, age)
    except OSError:
        pass
    return 0, 999.0


def _analyze_decisions(rows: list[dict]) -> dict:
    if not rows:
        return {"total": 0, "skips": 0, "executed": 0, "reasons": {}, "timeline": pd.DataFrame()}
    reasons = Counter(r.get("reasoning", "?") for r in rows)
    return {
        "total": len(rows),
        "skips": sum(1 for r in rows if r.get("action") == "skip"),
        "executed": sum(1 for r in rows if r.get("executed")),
        "reasons": dict(reasons.most_common(8)),
    }


@st.cache_data(ttl=90)
def _load_history(pair: str):
    return build_frames(pair, history_max_age_sec=90)


@st.cache_data(ttl=45)
def _cached_readiness(pair: str, use_session: bool) -> float:
    return pair_readiness_cached(pair, use_session, LIVE_GUARDS)


def _trades_since_session(trades: list[dict]) -> list[dict]:
    from paper.basket_state import trades_since_session
    return trades_since_session(trades)


def _trade_stats(trades: list[dict], *, pair: str | None = None) -> dict:
    rows = _trades_since_session(trades)
    if pair:
        rows = [r for r in rows if not r.get("pair") or r.get("pair") == pair]
    bal, start = CONFIG.reference_balance, CONFIG.reference_balance
    opens = closes = wins = 0
    equity, closed = [{"ts": datetime.now(timezone.utc), "balance": bal}], []
    for r in rows:
        if r.get("event") == "open_basket":
            opens += 1
        elif r.get("event") == "close_basket":
            closes += 1
            pnl = float(r.get("total_profit", 0))
            bal = float(r.get("balance", bal + pnl))
            wins += int(pnl >= 0)
            closed.append(r)
            equity.append({"ts": r.get("ts"), "balance": bal})
    return {
        "balance": bal, "pnl": bal - start, "opens": opens, "closes": closes,
        "wins": wins, "wr": (wins / closes * 100) if closes else 0,
        "equity": pd.DataFrame(equity), "closed": closed,
    }


def _push_history(adx: float, rsi: float, gates: int, *, score: int = 0, ready: bool = False, pair: str = "") -> pd.DataFrame:
    key = f"_hist_{pair}" if pair else "_hist"
    if key not in st.session_state:
        st.session_state[key] = []
    st.session_state[key].append({
        "ts": datetime.now(), "adx": float(adx), "rsi": float(rsi),
        "gates": int(gates), "score": int(score), "ready": int(ready),
    })
    st.session_state[key] = st.session_state[key][-120:]
    return pd.DataFrame(st.session_state[key])


def _push_tick(price: float) -> list[float]:
    buf = st.session_state.setdefault("_tick_buf", [])
    buf.append(price)
    st.session_state._tick_buf = buf[-60:]
    return st.session_state._tick_buf


def _check_alerts(pair: str, ready: bool, basket: dict | None, opens: int, closes: int, prefs: dict) -> None:
    alerts = st.session_state.setdefault("_alerts", {"ready": False, "opens": 0, "closes": 0})
    now = datetime.now().strftime("%H:%M:%S")
    if not prefs.get("enabled", True):
        return
    if prefs.get("ready") and ready and not alerts["ready"]:
        notify_mac("ScalpBot READY", f"{pair} — all gates passed", sound="Glass")
        st.session_state._last_alert = f"Ready · {now}"
    alerts["ready"] = ready
    if prefs.get("open") and opens > alerts["opens"]:
        notify_mac("ScalpBot", f"New basket on {pair}", sound="Glass")
        st.session_state._last_alert = f"Open · {now}"
    alerts["opens"] = opens
    if prefs.get("close") and closes > alerts["closes"]:
        notify_mac("ScalpBot", f"Basket closed on {pair}", sound="Hero")
        st.session_state._last_alert = f"Close · {now}"
    alerts["closes"] = closes
    if basket and prefs.get("near_tp"):
        pnl = basket["mark_pnl"]
        if pnl >= basket["tp"] * 0.9 and not alerts.get("near_tp"):
            notify_mac("ScalpBot", f"Near TP · ${pnl:+.2f}", sound="Pop")
            st.session_state._last_alert = f"Near TP · {now}"
            alerts["near_tp"] = True
        if pnl <= -basket["sl"] * 0.85 and not alerts.get("near_sl"):
            notify_mac("ScalpBot", f"Near SL · ${pnl:+.2f}", sound="Basso")
            st.session_state._last_alert = f"Near SL · {now}"
            alerts["near_sl"] = True
    elif not basket:
        alerts["near_tp"] = alerts["near_sl"] = False


def _bias_tile(tf: str, info: dict, c: dict) -> str:
    side = info.get("side")
    cls = "bull" if side == "buy" else ("bear" if side == "sell" else "flat")
    col = c["green"] if side == "buy" else (c["red"] if side == "sell" else c["muted"])
    return (
        f'<div class="bias-tile {cls}"><div class="bias-tf">{tf}</div>'
        f'<div class="mono" style="font-size:15px;font-weight:700;color:{col}">{info["label"]}</div>'
        f'<div style="font-size:10px;color:{c["muted"]}">{(side or "—").upper()}</div></div>'
    )


def _ring(pct: float, label: str, sub: str, color: str, c: dict) -> str:
    deg = int(min(1, pct) * 360)
    return (
        f'<div style="text-align:center"><div style="width:82px;height:82px;border-radius:50%;margin:0 auto;'
        f'background:conic-gradient({color} {deg}deg,{c["border"]} {deg}deg);display:flex;align-items:center;justify-content:center;">'
        f'<div style="width:62px;height:62px;border-radius:50%;background:{c["panel"]};display:flex;flex-direction:column;'
        f'align-items:center;justify-content:center;"><span class="mono" style="font-size:16px;font-weight:700">{label}</span>'
        f'<span style="font-size:8px;color:{c["muted"]}">{sub}</span></div></div></div>'
    )


def _price_decimals(pair: str) -> int:
    return 2 if pair in ("XAUUSDT", "XAUUSD") else 5


def _fmt_price(pair: str, price: float) -> str:
    return f"{price:.{_price_decimals(pair)}f}"


def _price_html(pair: str, price: float, prev: float | None, tick_at: str, c: dict) -> str:
    if prev is not None:
        if price > prev:
            cls, arrow = "price-up", "▲"
        elif price < prev:
            cls, arrow = "price-down", "▼"
        else:
            cls, arrow = "price-flat", "·"
    else:
        cls, arrow = "price-flat", ""
    return (
        f'<div style="text-align:right">'
        f'<span style="color:{c["muted"]};font-size:11px"><span class="live-dot"></span>LIVE · {tick_at}</span><br>'
        f'<span class="mono {cls}" style="font-size:30px;font-weight:700">{_fmt_price(pair, price)}</span>'
        f'<span style="font-size:14px;color:{c["muted"]}"> {arrow}</span></div>'
    )


def _price_block_html(pair: str, price: float, prev: float | None, tick_at: str, c: dict,
                      spark: list[float] | None = None) -> str:
    body = _price_html(pair, price, prev, tick_at, c)
    if spark and len(spark) >= 2:
        body += sparkline_svg_html(spark, c)
    return body


def _all_gates_html(g: dict, guards, use_session: bool, c: dict) -> str:
    side = g["side"]
    z_ok = g["gates"]["z_score"] if side else False
    rsi_ok = g["gates"]["rsi"] if side else False
    sess_ok = g["gates"]["session"] if use_session else True

    if not side:
        rsi_cell = gate_cell_html("RSI", f'{g["rsi"]:.0f} · need side', False, c)
        z_cell = gate_cell_html("Z", f'{g["z"]:.2f} · need side', False, c)
    elif side == "sell":
        z_cell = gate_progress_html(
            "Z", abs(g["z"]), guards.max_z_sell, ok=z_ok, higher_is_good=False, c=c,
        )
        rsi_cell = gate_progress_html(
            "RSI", g["rsi"], guards.rsi_sell_max,
            ok=rsi_ok, higher_is_good=True, c=c,
        )
    else:
        z_cell = gate_progress_html(
            "Z", abs(g["z"]), guards.max_z_buy, ok=z_ok, higher_is_good=False, c=c,
        )
        rsi_cell = gate_progress_html(
            "RSI", g["rsi"], guards.rsi_buy_max,
            ok=rsi_ok, higher_is_good=True, c=c,
        )

    return (
        f'<div class="gate-grid">'
        f'{gate_progress_html("ADX", g["adx"], guards.min_adx, ok=g["gates"]["adx"], higher_is_good=True, c=c)}'
        f'{gate_progress_html("Score", g["score"], guards.min_score, ok=g["gates"]["score"], higher_is_good=True, c=c)}'
        f'{rsi_cell}'
        f'{z_cell}'
        f'{gate_progress_html("ATR", g["vol"], guards.max_vol_ratio, ok=g["gates"]["atr_spike"], higher_is_good=False, c=c)}'
        f'{gate_cell_html("Sess", "24/7" if not use_session else "L/NY", sess_ok, c)}'
        f'{gate_cell_html("Side", (side or "—").upper(), g["gates"]["side"], c)}'
        f'{gate_cell_html("Fallback", "off" if guards.block_fallback else "allow", g["gates"]["fallback"], c)}'
        f'</div>'
    )


def _main_chart(m5: pd.DataFrame, pair: str, price: float, basket: dict | None, markers: list[dict], c: dict) -> go.Figure:
    t = m5.tail(100)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28], vertical_spacing=0.02)
    fig.add_trace(go.Candlestick(
        x=t.index, open=t["open"], high=t["high"], low=t["low"], close=t["close"],
        increasing_line_color=c["green"], decreasing_line_color=c["red"], name="OHLC",
    ), row=1, col=1)
    if basket:
        for y, lbl, col, dash in [(basket["entry"], "Entry", c["blue"], "solid"), (price, "Mark", c["amber"], "dot")]:
            fig.add_hline(y=y, line_color=col, line_dash=dash, line_width=1, row=1, col=1,
                          annotation_text=lbl, annotation_position="right")
    if "volume" in t.columns:
        vc = [c["green"] if cl >= o else c["red"] for o, cl in zip(t["open"], t["close"])]
        fig.add_trace(go.Bar(x=t.index, y=t["volume"], marker_color=vc, opacity=0.5), row=2, col=1)
    fig.update_layout(template="plotly_dark", paper_bgcolor=c["bg"], plot_bgcolor=c["panel"],
                      height=480, margin=dict(l=0, r=8, t=8, b=0), xaxis_rangeslider_visible=False,
                      showlegend=False, uirevision="scalpbot")
    return fig


def _indicator_chart(hist: pd.DataFrame, guards, c: dict) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.55, 0.45], vertical_spacing=0.06)
    if not hist.empty:
        fig.add_trace(go.Scatter(x=hist["ts"], y=hist["adx"], line=dict(color=c["amber"], width=2)), row=1, col=1)
        fig.add_trace(go.Scatter(x=hist["ts"], y=hist["rsi"], line=dict(color=c["purple"], width=2)), row=2, col=1)
    fig.add_hline(y=guards.min_adx, line_dash="dash", line_color=c["green"], opacity=0.5, row=1, col=1)
    fig.update_layout(template="plotly_dark", paper_bgcolor=c["bg"], plot_bgcolor=c["panel"], height=180,
                      margin=dict(l=0, r=0, t=28, b=0), showlegend=False, uirevision="scalpbot",
                      title=dict(text="ADX · RSI", font=dict(size=11, color=c["muted"])))
    return fig


def _equity_chart(equity: pd.DataFrame, c: dict) -> go.Figure:
    fig = go.Figure()
    if not equity.empty and len(equity) > 1:
        df = equity.copy()
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        fig.add_trace(go.Scatter(x=df["ts"], y=df["balance"], fill="tozeroy",
                                 line=dict(color=c["green"], width=2), fillcolor="rgba(52,211,153,0.1)"))
    fig.update_layout(template="plotly_dark", paper_bgcolor=c["bg"], plot_bgcolor=c["panel"], height=220,
                      margin=dict(l=0, r=0, t=28, b=0), title=dict(text="Equity curve", font=dict(size=11, color=c["muted"])))
    return fig


def _gather_state(pair: str, frames: dict, use_session: bool) -> dict:
    snap = build_snapshot(pair, frames, use_session=use_session)
    guards = LIVE_GUARDS
    g = gate_checklist(snap, guards)
    trades = _read_jsonl(PAPER_LOG)
    tstats = _trade_stats(trades, pair=pair)
    session_trades = _trades_since_session(trades)
    all_decisions = _read_jsonl(AGENT_LOG)
    decisions = [d for d in all_decisions if d.get("pair") == pair]
    da = _analyze_decisions(decisions)
    scan_n, scan_age = _latest_scan_meta(pair)
    status = _read_status()
    if status.get("mode") == "multi":
        ps = (status.get("pairs") or {}).get(pair, {})
        if ps.get("scans"):
            scan_n = int(ps["scans"])
    if not scan_n:
        scan_n = da["total"]
    sess = session_status()
    basket = open_basket_state(session_trades, pair, snap.price)
    bot_live = _bot_live_state(pair)
    stale_basket = bool(basket and not bot_live["in_basket"])
    if stale_basket:
        basket = None
    reasons = snap.setup.get("reasons", [])
    bias = tf_bias_strip(reasons)
    hist = _push_history(g["adx"], g["rsi"], g["passed"], score=g["score"], ready=g["ready"], pair=pair)
    ready_pct = readiness_pct(g["passed"], g["total"], g["adx"], guards.min_adx, g["score"], guards.min_score)
    ww = why_waiting(reasons, g["score"], guards.min_score, g["ready"])
    wf = score_waterfall(reasons, g["score"], g["adx"], guards.min_score)
    return {
        "snap": snap, "g": g, "guards": guards, "tstats": tstats, "da": da, "scan_n": scan_n,
        "scan_age": scan_age, "sess": sess, "basket": basket, "bias": bias, "hist": hist,
        "ready_pct": ready_pct, "decisions": decisions, "markers": trade_markers(session_trades, pair),
        "reasons": reasons, "why": ww, "waterfall": wf, "bot_live": bot_live, "stale_basket": stale_basket,
    }


def _recent_trades_html(closed: list[dict], c: dict) -> str:
    if not closed:
        return ""
    rows = "".join(
        f'<div class="feed-item" style="color:{c["green"] if float(t.get("total_profit", 0)) >= 0 else c["red"]}">'
        f'{(t.get("ts") or "")[11:19]} <b>{(t.get("side") or "").upper()}</b> '
        f'{t.get("reason", "")} · ${float(t.get("total_profit", 0)):+.2f}</div>'
        for t in reversed(closed[-5:])
    )
    return f'<div style="margin-top:10px"><div class="panel-h">Recent trades (session)</div><div class="feed">{rows}</div></div>'


def _badge_html(g: dict, use_session: bool, sess: dict) -> str:
    if g["ready"]:
        return '<span class="badge b-ready">OPEN READY</span>'
    if not use_session:
        return '<span class="badge b-scan">24/7 SCAN</span>'
    if sess["market_open"]:
        return f'<span class="badge b-live">{sess["active_name"].upper()}</span>'
    return '<span class="badge b-wait">MARKET CLOSED</span>'


def _paint_live(slots: dict, pair: str, use_session: bool, state: dict, c: dict, *,
                tick_ms: float | None, runtime: dict) -> None:
    g, guards, tstats, da, scan_n = state["g"], state["guards"], state["tstats"], state["da"], state["scan_n"]
    sess, basket, bias, ready_pct = state["sess"], state["basket"], state["bias"], state["ready_pct"]
    decisions, ww, wf = state["decisions"], state["why"], state["waterfall"]
    brain = runtime.get("brain", "rules")
    mode = "PAPER" if not runtime.get("live") else "LIVE"
    sess_label = "24/7" if not use_session else "London+NY"

    slots["health"].markdown(
        health_strip_html(tick_ms=tick_ms, scan_n=scan_n, scan_age_s=state["scan_age"],
                          mode=f"{mode} · {sess_label}", brain=brain, c=c),
        unsafe_allow_html=True,
    )
    slots["header"].markdown(
        f'<span style="font-size:24px;font-weight:700">{pair}</span> {_badge_html(g, use_session, sess)} '
        f'<span style="color:{c["muted"]};font-size:12px">· {sess["pkt"]} · scan #{scan_n:,} · ready {ready_pct}%</span>',
        unsafe_allow_html=True,
    )
    slots["why"].markdown(why_panel_html(ww, c), unsafe_allow_html=True)
    slots["waterfall"].markdown(waterfall_html(wf, g["score"], guards.min_score, c), unsafe_allow_html=True)
    slots["bias"].markdown(
        f'<div class="bias-row">{"".join(_bias_tile(tf, bias[tf], c) for tf in ("H1", "M15", "M5"))}</div>',
        unsafe_allow_html=True,
    )

    if basket:
        pnl_c = c["green"] if basket["mark_pnl"] >= 0 else c["red"]
        held = f"{basket['held_sec']//60}m {basket['held_sec']%60}s"
        slots["basket"].markdown(
            f'<div class="basket-panel"><div style="color:{c["blue"]};font-weight:700">OPEN BASKET · {basket["side"].upper()} · bot live</div>'
            f'<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-top:10px">'
            f'<div><div class="t-label">Entry</div><div class="mono">{_fmt_price(pair, basket["entry"])}</div></div>'
            f'<div><div class="t-label">Mark P/L</div><div class="mono" style="color:{pnl_c}">${basket["mark_pnl"]:+.2f}</div></div>'
            f'<div><div class="t-label">Target</div><div class="mono" style="color:{c["green"]}">+${basket["tp"]:.2f}</div></div>'
            f'<div><div class="t-label">Stop</div><div class="mono" style="color:{c["red"]}">-${basket["sl"]:.2f}</div></div>'
            f'<div><div class="t-label">Held</div><div class="mono">{held}</div></div></div>'
            f'{basket_pnl_gauge(basket, c)}</div>',
            unsafe_allow_html=True,
        )
    elif state.get("stale_basket"):
        slots["basket"].markdown(
            f'<div class="basket-panel" style="border-color:{c["amber"]}">'
            f'<div style="color:{c["amber"]};font-weight:700">BOT FLAT — no live trade</div>'
            f'<div style="margin-top:8px;color:{c["muted"]};font-size:13px">'
            f'The dashboard was showing profit on an <b>already closed</b> trade. '
            f'Only autopilot closes baskets (every 0.25s when live). '
            f'Restart: <code>npm run stop && npm run dev</code></div></div>',
            unsafe_allow_html=True,
        )
    else:
        slots["basket"].empty()

    blk_cls = "blocker blocker-ready" if g["ready"] else "blocker"
    top_reason = next(iter(da["reasons"]), "—")
    blocker_text = "ALL GATES PASS" if g["ready"] else f"{da['total']:,} scans · {top_reason}"
    slots["blocker"].markdown(
        f'<div class="{blk_cls}"><div style="font-weight:700;color:{c["green"] if g["ready"] else c["amber"]}">'
        f'{blocker_text}</div></div>',
        unsafe_allow_html=True,
    )

    bal_s = f"${tstats['balance']:.2f}"
    pnl_s = f"${tstats['pnl']:+.2f}"
    pnl_col = c["green"] if tstats["pnl"] >= 0 else c["red"]
    closed_s = str(tstats["closes"])
    wins_s = f"{tstats['wins']}W"
    wr_s = f"{tstats['wr']:.0f}%"
    adx_s = f"{g['adx']:.1f}"
    rsi_s = f"{g['rsi']:.1f}"
    slots["stats"].markdown(
        f'<div class="stat-grid">'
        f'{stat_box("Balance", bal_s, None, c)}'
        f'{stat_box("P/L", pnl_s, None, c, pnl_col)}'
        f'{stat_box("Closed", closed_s, wins_s, c)}'
        f'{stat_box("Win rate", wr_s, None, c)}'
        f'{stat_box("Ready", f"{ready_pct}%", None, c)}'
        f'{stat_box("Scans", f"{scan_n:,}", None, c)}'
        f'{stat_box("ADX", adx_s, "bar", c)}'
        f'{stat_box("RSI", rsi_s, "live", c)}'
        f'</div>'
        + (_recent_trades_html(tstats.get("closed") or [], c) if tstats.get("closed") else ""),
        unsafe_allow_html=True,
    )

    gates_html = _all_gates_html(g, guards, use_session, c)
    gp, gt = g["passed"], g["total"]
    feed = '<div class="feed">'
    for d in reversed(decisions[-12:]):
        cls = "feed-open" if d.get("executed") else ""
        feed += f'<div class="feed-item {cls}">{d.get("ts","")[11:19]} <b>{d.get("action","").upper()}</b> · {d.get("reasoning","")}</div>'
    feed += "</div>"
    adx_v, adx_t = g["adx"], guards.min_adx
    slots["sidebar"].markdown(
        f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:4px;margin-bottom:10px">'
        f'{_ring(gp/gt, f"{gp}/{gt}", "gates", c["blue"], c)}'
        f'{_ring(min(1, adx_v/adx_t), f"{adx_v:.1f}", f"/{adx_t:.0f}", c["amber"], c)}'
        f'{_ring(ready_pct/100, f"{ready_pct:.0f}%", "ready", c["green"], c)}</div>'
        f'<div class="panel-h">Gates ({gp}/{gt})</div>{gates_html}'
        f'<div class="panel-h" style="margin-top:10px">Feed</div>{feed}',
        unsafe_allow_html=True,
    )


def _paint_charts(slots: dict, pair: str, frames: dict, state: dict, c: dict) -> None:
    cfg = {"displayModeBar": False}
    slots["main_chart"].plotly_chart(
        _main_chart(frames["m5"], pair, state["snap"].price, state["basket"], state["markers"], c),
        width="stretch", config=cfg,
    )
    slots["ind_chart"].plotly_chart(_indicator_chart(state["hist"], state["guards"], c), width="stretch", config=cfg)
    slots["skip_chart"].plotly_chart(skip_timeline_chart(state["decisions"], c), width="stretch", config=cfg)


def _render_journal(trades: list[dict], tstats: dict, c: dict) -> None:
    st.plotly_chart(_equity_chart(tstats["equity"], c), width="stretch", config={"displayModeBar": False})
    closed = tstats["closed"]
    if not closed:
        st.info("No closed baskets yet.")
        return
    rows = []
    for t in reversed(closed[-50:]):
        rows.append({
            "Time": (t.get("ts") or "")[:19],
            "Side": (t.get("side") or "").upper(),
            "P/L": f"${float(t.get('total_profit', 0)):+.2f}",
            "Reason": t.get("reason", ""),
            "Balance": f"${float(t.get('balance', 0)):.2f}",
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def _frames_key(pair: str) -> str:
    return f"_frames_{pair}"


def _render_pair_live(
    pair: str,
    *,
    use_session: bool,
    runtime: dict,
    alert_prefs: dict,
    tick_sec: float,
    chart_sec: float,
    c: dict,
) -> None:
    fk = _frames_key(pair)
    try:
        if st.session_state.get(fk) is None or st.session_state.get("_pair_loaded") != pair:
            st.session_state[fk] = _load_history(pair)
            st.session_state._pair_loaded = pair
            st.session_state._prev_price = None
        frames = st.session_state[fk]
    except Exception as e:
        st.error(f"{pair}: {e}")
        return

    health_slot = st.empty()
    h1, h2 = st.columns([2.5, 1])
    with h1:
        header_slot = st.empty()
    with h2:
        price_slot = st.empty()

    why_slot = st.empty()
    wf_slot = st.empty()
    bias_slot = st.empty()
    basket_slot = st.empty()
    blocker_slot = st.empty()
    stats_slot = st.empty()
    col_chart, col_sig = st.columns([1.75, 1])
    with col_chart:
        main_chart_slot = st.empty()
        ind_chart_slot = st.empty()
        skip_chart_slot = st.empty()
    with col_sig:
        sidebar_slot = st.empty()

    slots = {
        "health": health_slot, "header": header_slot, "why": why_slot, "waterfall": wf_slot,
        "bias": bias_slot, "basket": basket_slot, "blocker": blocker_slot, "stats": stats_slot,
        "sidebar": sidebar_slot, "main_chart": main_chart_slot, "ind_chart": ind_chart_slot,
        "skip_chart": skip_chart_slot,
    }
    slot_key = f"_slots_{pair}"
    st.session_state[slot_key] = slots

    def _refresh_signals() -> None:
        fr = st.session_state[fk]
        refresh_tick_only(fr, pair)
        state = _gather_state(pair, fr, use_session)
        tick_ms = st.session_state.get(f"_tick_ms_{pair}")
        _check_alerts(pair, state["g"]["ready"], state["basket"],
                      state["tstats"]["opens"], state["tstats"]["closes"], alert_prefs)
        _paint_live(slots, pair, use_session, state, c, tick_ms=tick_ms, runtime=runtime)

    def _paint_charts_once() -> None:
        lock_key = f"_charts_locked_{pair}"
        if st.session_state.get(lock_key):
            return
        fr = st.session_state[fk]
        state = _gather_state(pair, fr, use_session)
        _paint_charts(slots, pair, fr, state, c)
        st.session_state[lock_key] = True

    price_slot.markdown(
        _price_block_html(pair, frames["last_price"], st.session_state.get(f"_prev_price_{pair}"),
                          datetime.now().strftime("%H:%M:%S"), c,
                          st.session_state.get(f"_tick_buf_{pair}", [])),
        unsafe_allow_html=True,
    )

    paint_key = f"_painted_{pair}"
    if not st.session_state.get(paint_key):
        refresh_live_bars(st.session_state[fk], pair)
        _refresh_signals()
        _paint_charts_once()
        st.session_state[paint_key] = True

    force_key = f"_force_refresh_{pair}"
    if st.session_state.pop(force_key, None):
        refresh_live_bars(st.session_state[fk], pair)
        st.session_state[f"_charts_locked_{pair}"] = False
        _refresh_signals()
        _paint_charts_once()

    @st.fragment(run_every=timedelta(seconds=0.25))
    def _live_tick() -> None:
        try:
            fr = st.session_state.get(fk)
            if fr is None:
                return
            trades = _read_jsonl(PAPER_LOG)
            session_trades = _trades_since_session(trades)
            basket = open_basket_state(session_trades, pair, fr.get("last_price", 0))
            closes_n = sum(1 for t in session_trades if t.get("event") == "close_basket" and t.get("pair") == pair)
            min_iv = CONFIG.basket_price_sec if basket else tick_sec
            now = time.time()
            closes_key = f"_closes_n_{pair}"
            last_tick_key = f"_last_tick_at_{pair}"
            stats_due = closes_n != st.session_state.get(closes_key, 0)
            if not stats_due and now - st.session_state.get(last_tick_key, 0) < min_iv:
                return
            st.session_state[last_tick_key] = now
            st.session_state[closes_key] = closes_n
            t0 = time.time()
            prev = st.session_state.get(f"_prev_price_{pair}")
            price = fetch_tick_price(pair)
            st.session_state[f"_tick_ms_{pair}"] = (time.time() - t0) * 1000
            st.session_state[f"_prev_price_{pair}"] = price
            fr["last_price"] = price
            buf_key = f"_tick_buf_{pair}"
            if buf_key not in st.session_state:
                st.session_state[buf_key] = []
            buf = st.session_state[buf_key]
            buf.append(price)
            st.session_state[buf_key] = buf[-40:]
            price_slot.markdown(
                _price_block_html(pair, price, prev, datetime.now().strftime("%H:%M:%S"), c, buf),
                unsafe_allow_html=True,
            )
            sl = st.session_state.get(slot_key)
            if sl and (basket or stats_due):
                state = _gather_state(pair, fr, use_session)
                _paint_live(sl, pair, use_session, state, c,
                            tick_ms=st.session_state.get(f"_tick_ms_{pair}"), runtime=runtime)
                if stats_due:
                    st.session_state[f"_charts_locked_{pair}"] = False
                    _paint_charts(sl, pair, fr, state, c)
                    st.session_state[f"_charts_locked_{pair}"] = True
        except Exception:
            pass

    @st.fragment(run_every=timedelta(seconds=chart_sec))
    def _live_data() -> None:
        if st.session_state.get(slot_key) is None:
            return
        try:
            _refresh_signals()
        except Exception:
            pass

    _live_tick()
    _live_data()


def main() -> None:
    runtime = _read_runtime()
    pair = st.session_state.get("watch_pair") or runtime.get("pair", WATCH_PAIRS[0])
    if pair not in WATCH_PAIRS:
        pair = WATCH_PAIRS[0]
    use_session = runtime.get("session_filter") is True
    if "theme" not in st.session_state:
        st.session_state.theme = "dark"

    c = _c()
    st.markdown(f"<style>{css_block(c)}</style>", unsafe_allow_html=True)
    components.html(keyboard_shortcuts_html(), height=0)

    with st.sidebar:
        st.markdown("### ScalpBot")
        theme = st.radio("Theme", ["dark", "light"], index=0 if st.session_state.theme == "dark" else 1, horizontal=True)
        if theme != st.session_state.theme:
            st.session_state.theme = theme
            st.rerun()
        pair = st.selectbox("Symbol (journal)", WATCH_PAIRS, index=WATCH_PAIRS.index(pair) if pair in WATCH_PAIRS else 0)
        st.session_state.watch_pair = pair
        use_session = st.radio("Bot mode", ["24/7 scan", "London+NY"], index=1 if use_session else 0) == "London+NY"
        tick_sec = st.slider("Price tick (sec)", 0.25, 3.0, 1.0, step=0.25)
        chart_sec = st.slider("Signal refresh (sec)", 3, 30, 5)
        st.caption(f"Basket open: price every {CONFIG.basket_price_sec}s (bot)")
        st.markdown("**Alerts**")
        alert_prefs = {
            "enabled": st.checkbox("Mac notifications", value=True, key="al_en"),
            "ready": st.checkbox("Ready to trade", value=True, key="al_ready"),
            "open": st.checkbox("Basket opened", value=True, key="al_open"),
            "close": st.checkbox("Basket closed", value=True, key="al_close"),
            "near_tp": st.checkbox("Near TP / SL", value=True, key="al_near"),
        }
        last_al = st.session_state.get("_last_alert", "—")
        st.caption(f"Last alert: {last_al}")
        if st.button("Force refresh", key="btn_refresh"):
            for wp in WATCH_PAIRS:
                st.session_state[f"_force_refresh_{wp}"] = True
        if st.button("Toggle sidebar", key="btn_sidebar"):
            st.session_state._sidebar_hidden = not st.session_state.get("_sidebar_hidden", False)

    if st.session_state.get("_sidebar_hidden"):
        st.markdown("<style>section[data-testid='stSidebar']{display:none}</style>", unsafe_allow_html=True)

    tab_live, tab_journal = st.tabs(["Live", "Journal"])

    with tab_live:
        tab_labels = []
        for wp in WATCH_PAIRS:
            rp = _cached_readiness(wp, use_session)
            status = _read_status()
            ps = (status.get("pairs") or {}).get(wp, {}) if status.get("mode") == "multi" else {}
            open_mark = " ●" if ps.get("in_basket") else ""
            tab_labels.append(f"{wp}{open_mark} {rp:.0f}%")

        pair_tabs = st.tabs(tab_labels)
        for ptab, wp in zip(pair_tabs, WATCH_PAIRS):
            with ptab:
                st.session_state.watch_pair = wp
                _render_pair_live(
                    wp,
                    use_session=use_session,
                    runtime=runtime,
                    alert_prefs=alert_prefs,
                    tick_sec=tick_sec,
                    chart_sec=chart_sec,
                    c=c,
                )

        st.caption(
            f"6 pairs · price {tick_sec}s idle · {CONFIG.basket_price_sec}s in basket · signals {chart_sec}s"
        )

    with tab_journal:
        journal_slot = st.empty()

        @st.fragment(run_every=timedelta(seconds=2))
        def _journal_refresh() -> None:
            trades = _read_jsonl(PAPER_LOG)
            pair_f = st.session_state.get("watch_pair") or pair
            tstats = _trade_stats(trades, pair=pair_f)
            with journal_slot.container():
                _render_journal(trades, tstats, _c())

        _journal_refresh()


if __name__ == "__main__":
    main()
