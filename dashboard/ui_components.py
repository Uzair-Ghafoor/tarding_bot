"""Dashboard UI builders — panels, gates, charts, themes."""

from __future__ import annotations

import html
import time
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go

from agent.metrics import gate_checklist
from agent.snapshot import build_snapshot
from backtest.guards import TradeGuards
from config import CONFIG
from dashboard.helpers import (
    basket_pnl_gauge,
    readiness_pct,
    score_waterfall,
    why_waiting,
)
from paper.feed import build_frames

THEMES = {
    "dark": {
        "bg": "#0a0e1a",
        "panel": "#111827",
        "panel2": "#1a2236",
        "border": "#243049",
        "text": "#e8ecf4",
        "muted": "#7b8ba8",
        "dim": "#4a5568",
        "green": "#34d399",
        "red": "#f87171",
        "blue": "#38bdf8",
        "cyan": "#22d3ee",
        "amber": "#fbbf24",
        "purple": "#a78bfa",
        "gold": "#fcd34d",
    },
    "light": {
        "bg": "#f4f6fa",
        "panel": "#ffffff",
        "panel2": "#eef2f8",
        "border": "#d5dce8",
        "text": "#1a2236",
        "muted": "#5c6b82",
        "dim": "#94a3b8",
        "green": "#059669",
        "red": "#dc2626",
        "blue": "#0284c7",
        "cyan": "#0891b2",
        "amber": "#d97706",
        "purple": "#7c3aed",
        "gold": "#ca8a04",
    },
}


def css_block(c: dict) -> str:
    return f"""
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] {{ font-family: 'Inter', sans-serif; }}
.stApp {{ background: {c['bg']}; }}
.block-container {{ padding: 0.8rem 1.4rem 1rem; max-width: 100%; }}
#MainMenu, footer, header {{ visibility: hidden; }}
[data-testid="stAppViewContainer"], .main, .stApp {{
    transition: none !important; animation: none !important;
}}
[data-testid="stVerticalBlock"] > div {{ transition: none !important; animation: none !important; }}
.stPlotlyChart, .stPlotlyChart iframe {{ transition: none !important; animation: none !important; }}
[data-testid="stMarkdownContainer"] {{ content-visibility: auto; contain-intrinsic-size: auto 50px; }}
section[data-testid="stSidebar"] {{ background: {c['panel']}; border-right: 1px solid {c['border']}; }}
.mono {{ font-family: 'JetBrains Mono', monospace; }}
.t-label {{ color: {c['muted']}; font-size: 10px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; }}
.t-val {{ font-family: 'JetBrains Mono', monospace; font-size: 20px; font-weight: 600; color: {c['text']}; }}
.stat-grid {{ display: grid; grid-template-columns: repeat(7, 1fr); gap: 8px; margin-bottom: 10px; }}
@media (max-width: 1100px) {{ .stat-grid {{ grid-template-columns: repeat(4, 1fr); }} }}
@media (max-width: 700px) {{ .stat-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
.stat-box {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 10px 12px; }}
.bias-row {{ display: flex; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }}
.bias-tile {{ flex: 1; min-width: 100px; text-align: center; padding: 10px 8px; border-radius: 8px;
    background: {c['panel2']}; border: 1px solid {c['border']}; }}
.bias-tile.bull {{ border-color: rgba(52,211,153,0.45); background: rgba(52,211,153,0.07); }}
.bias-tile.bear {{ border-color: rgba(248,113,113,0.45); background: rgba(248,113,113,0.07); }}
.basket-panel {{ background: rgba(56,189,248,0.06); border: 1px solid rgba(56,189,248,0.28);
    border-radius: 10px; padding: 14px 16px; margin-bottom: 10px; }}
.blocker {{ background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.35);
    border-radius: 8px; padding: 12px 14px; margin-bottom: 10px; }}
.blocker-ready {{ background: rgba(52,211,153,0.1); border-color: rgba(52,211,153,0.45); }}
.badge {{ display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 10px; font-weight: 700; }}
.b-live {{ background: rgba(52,211,153,0.15); color: {c['green']}; border: 1px solid rgba(52,211,153,0.35); }}
.b-scan {{ background: rgba(56,189,248,0.12); color: {c['blue']}; border: 1px solid rgba(56,189,248,0.3); }}
.b-ready {{ background: rgba(52,211,153,0.2); color: {c['green']}; border: 1px solid rgba(52,211,153,0.5); }}
.b-wait {{ background: rgba(251,191,36,0.1); color: {c['amber']}; }}
.tag-live {{ font-size: 8px; padding: 2px 5px; border-radius: 4px; background: rgba(52,211,153,0.2);
    color: {c['green']}; font-weight: 700; margin-left: 4px; }}
.tag-bar {{ font-size: 8px; padding: 2px 5px; border-radius: 4px; background: rgba(123,139,168,0.2);
    color: {c['muted']}; font-weight: 700; margin-left: 4px; }}
.health-strip {{ display: flex; gap: 16px; flex-wrap: wrap; padding: 8px 12px; margin-bottom: 10px;
    background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 8px; font-size: 11px; color: {c['muted']}; }}
.health-item b {{ color: {c['text']}; }}
.health-dot {{ display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: {c['green']}; margin-right: 4px; }}
.why-panel {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 8px;
    padding: 12px 14px; margin-bottom: 10px; }}
.why-row {{ font-size: 12px; margin: 4px 0; color: {c['muted']}; }}
.why-row b {{ color: {c['text']}; }}
.gate-bar-track {{ height: 6px; background: {c['border']}; border-radius: 3px; margin-top: 6px; overflow: hidden; }}
.gate-bar-fill {{ height: 100%; border-radius: 3px; }}
.waterfall {{ font-family: 'JetBrains Mono', monospace; font-size: 11px; background: {c['panel2']};
    border: 1px solid {c['border']}; border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; }}
.wf-row {{ display: flex; justify-content: space-between; padding: 3px 0; color: {c['muted']}; }}
.wf-row.blocked {{ color: {c['red']}; }}
.wf-row.total {{ border-top: 1px solid {c['border']}; margin-top: 6px; padding-top: 6px; color: {c['text']}; font-weight: 600; }}
.watch-row {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }}
.watch-chip {{ padding: 6px 12px; border-radius: 20px; font-size: 11px; font-weight: 600;
    background: {c['panel2']}; border: 1px solid {c['border']}; color: {c['muted']}; cursor: pointer; }}
.watch-chip.active {{ border-color: {c['blue']}; color: {c['blue']}; background: rgba(56,189,248,0.1); }}
.pnl-gauge {{ margin-top: 10px; }}
.pnl-track {{ height: 10px; background: {c['border']}; border-radius: 5px; position: relative; overflow: hidden; }}
.pnl-fill {{ position: absolute; top: 0; height: 100%; }}
.pnl-marker {{ position: absolute; top: -4px; width: 3px; height: 18px; background: {c['text']}; border-radius: 2px; }}
.live-dot {{ display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: {c['green']}; margin-right: 6px; }}
.price-up {{ color: {c['green']}; }} .price-down {{ color: {c['red']}; }} .price-flat {{ color: {c['text']}; }}
.gate-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-bottom: 8px; }}
.gate-bar-cell {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 8px; }}
.gate-bar-cell.ok {{ border-color: rgba(52,211,153,0.45); background: rgba(52,211,153,0.06); }}
.panel-h {{ color: {c['muted']}; font-size: 11px; font-weight: 600; text-transform: uppercase; margin-bottom: 8px; }}
.feed {{ max-height: 160px; overflow-y: auto; border: 1px solid {c['border']}; border-radius: 6px; background: {c['panel2']}; }}
.feed-item {{ font-family: 'JetBrains Mono', monospace; font-size: 11px; padding: 6px 10px;
    border-bottom: 1px solid {c['border']}; color: {c['muted']}; }}
"""


def gate_cell_html(name: str, val: str, ok: bool, c: dict) -> str:
    cls = "ok" if ok else ""
    tick = "✓" if ok else "·"
    return (
        f'<div class="gate-bar-cell {cls}"><div class="t-label">{name}</div>'
        f'<div class="mono" style="font-size:12px;color:{c["text"]}">{tick} {val}</div></div>'
    )


def sparkline_svg_html(prices: list[float], c: dict, *, width: int = 220, height: int = 36) -> str:
    if len(prices) < 2:
        return ""
    lo, hi = min(prices), max(prices)
    rng = hi - lo or 1.0
    pts = []
    for i, p in enumerate(prices):
        x = i / (len(prices) - 1) * width
        y = height - 4 - (p - lo) / rng * (height - 8)
        pts.append(f"{x:.1f},{y:.1f}")
    col = c["green"] if prices[-1] >= prices[0] else c["red"]
    return (
        f'<svg width="100%" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="display:block;margin-top:6px" preserveAspectRatio="none">'
        f'<polyline fill="none" stroke="{col}" stroke-width="1.5" points="{" ".join(pts)}"/>'
        f'</svg>'
    )


def gate_progress_html(name: str, current: float, target: float, *, ok: bool, higher_is_good: bool, c: dict) -> str:
    if higher_is_good:
        pct = min(1.0, current / target) if target else 0
    else:
        pct = min(1.0, target / current) if current else 0
    fill = c["green"] if ok else c["amber"]
    bars = int(pct * 10)
    bar_vis = "█" * bars + "░" * (10 - bars)
    cls = "ok" if ok else ""
    if not higher_is_good:
        label = f"{current:.2f}/{target:.1f}"
    elif target >= 10:
        label = f"{current:.0f}/{target:.0f}"
    elif target >= 1:
        label = f"{current:.1f}/{target:.0f}"
    else:
        label = f"{current:.2f}/{target:.2f}"
    return (
        f'<div class="gate-bar-cell {cls}"><div style="display:flex;justify-content:space-between">'
        f'<span class="t-label">{name}</span><span class="mono" style="font-size:11px">{bar_vis} {label}</span></div>'
        f'<div class="gate-bar-track"><div class="gate-bar-fill" style="width:{pct*100:.0f}%;background:{fill}"></div></div></div>'
    )


def why_panel_html(ww: dict, c: dict) -> str:
    return (
        f'<div class="why-panel">'
        f'<div class="why-row"><b>Blocker:</b> {html.escape(ww["blocker"])}</div>'
        f'<div class="why-row"><b>Need:</b> {html.escape(ww["need"])}</div>'
        f'<div class="why-row"><b>Score gap:</b> <span style="color:{c["amber"]}">{ww["score_gap"]}</span></div>'
        f'</div>'
    )


def waterfall_html(rows: list[dict], total: int, min_score: int, c: dict) -> str:
    lines = ['<div class="waterfall"><div class="panel-h">Score breakdown</div>']
    for r in rows:
        cls = "wf-row blocked" if r.get("blocked") else "wf-row"
        pts = r.get("pts")
        pts_s = "—" if pts is None else (f"+{pts}" if pts >= 0 else str(pts))
        suffix = " (blocked)" if r.get("blocked") else ""
        lines.append(f'<div class="{cls}"><span>{html.escape(r["label"])}{suffix}</span><span>{pts_s}</span></div>')
    lines.append(f'<div class="wf-row total"><span>Total</span><span>{total} / {min_score} needed</span></div></div>')
    return "".join(lines)


def health_strip_html(*, tick_ms: float | None, scan_n: int, scan_age_s: float, mode: str, brain: str, c: dict) -> str:
    tick_s = f"{tick_ms:.0f}ms" if tick_ms is not None else "—"
    scan_s = f"#{scan_n:,} · {scan_age_s:.0f}s ago" if scan_n else "—"
    return (
        f'<div class="health-strip">'
        f'<span class="health-item"><span class="health-dot"></span>Binance tick: <b>{tick_s}</b></span>'
        f'<span class="health-item">Last scan: <b>{scan_s}</b></span>'
        f'<span class="health-item">Bot: <b>{mode} · {brain}</b></span>'
        f'</div>'
    )


def stat_box(label: str, value: str, tag: str | None, c: dict, color: str | None = None) -> str:
    tag_html = f'<span class="tag-{tag}">{tag.upper()}</span>' if tag else ""
    col = f' style="color:{color}"' if color else ""
    return (
        f'<div class="stat-box"><div class="t-label">{label}{tag_html}</div>'
        f'<div class="t-val"{col}>{value}</div></div>'
    )


def price_sparkline(prices: list[float], c: dict) -> go.Figure:
    fig = go.Figure()
    if len(prices) >= 2:
        col = c["green"] if prices[-1] >= prices[0] else c["red"]
        fig.add_trace(go.Scatter(
            y=prices, mode="lines", line=dict(color=col, width=1.5),
            fill="tozeroy", fillcolor=f"rgba(52,211,153,0.08)" if col == c["green"] else "rgba(248,113,113,0.08)",
        ))
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=56, margin=dict(l=0, r=0, t=0, b=0), showlegend=False,
        xaxis=dict(visible=False), yaxis=dict(visible=False), uirevision="spark",
    )
    return fig


def skip_timeline_chart(decisions: list[dict], c: dict) -> go.Figure:
    fig = go.Figure()
    if not decisions:
        return fig
    cutoff = datetime.now(timezone.utc) - pd.Timedelta(hours=1)
    rows = []
    for d in decisions:
        ts = d.get("ts")
        if not ts:
            continue
        try:
            t = pd.to_datetime(ts)
            if t.tzinfo is None:
                t = t.tz_localize("UTC")
            if t < cutoff:
                continue
            reason = (d.get("reasoning") or "other").split(",")[0].strip()
            rows.append({"time": t, "reason": reason})
        except (ValueError, TypeError):
            continue
    if rows:
        df = pd.DataFrame(rows)
        counts = df.groupby(["time", "reason"]).size().reset_index(name="n")
        for reason in counts["reason"].unique():
            sub = counts[counts["reason"] == reason]
            fig.add_trace(go.Bar(x=sub["time"], y=sub["n"], name=reason))
        fig.update_layout(barmode="stack")
    fig.update_layout(
        template="plotly_dark", paper_bgcolor=c["bg"], plot_bgcolor=c["panel"],
        height=140, margin=dict(l=0, r=0, t=24, b=0), showlegend=True,
        legend=dict(orientation="h", y=1.15, font=dict(size=9)),
        title=dict(text="Skip reasons (last hour)", font=dict(size=11, color=c["muted"])),
        uirevision="skip_tl",
    )
    return fig


def keyboard_shortcuts_html() -> str:
    return """
<script>
(function() {
  const doc = window.parent.document;
  if (doc._scalpbotKeys) return;
  doc._scalpbotKeys = true;
  doc.addEventListener('keydown', function(e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    const buttons = doc.querySelectorAll('button');
    if ((e.key === 'r' || e.key === 'R') && !e.metaKey && !e.ctrlKey) {
      for (const b of buttons) { if (b.innerText.includes('Force refresh')) { b.click(); break; } }
    }
    if ((e.key === 'd' || e.key === 'D') && !e.metaKey && !e.ctrlKey) {
      for (const b of buttons) { if (b.innerText.includes('Toggle sidebar')) { b.click(); break; } }
    }
  });
})();
</script>
"""


def pair_readiness_cached(pair: str, use_session: bool, guards: TradeGuards) -> float:
    try:
        frames = build_frames(pair, history_max_age_sec=120)
        snap = build_snapshot(pair, frames, use_session=use_session)
        g = gate_checklist(snap, guards)
        return readiness_pct(g["passed"], g["total"], g["adx"], guards.min_adx, g["score"], guards.min_score)
    except Exception:
        return 0.0
