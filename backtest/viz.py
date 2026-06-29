"""Interactive Plotly dashboards — opens in browser, no PNG required."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from backtest.engine import BacktestResult
from backtest.guards import TradeGuards
from backtest.loss_analysis import all_trades_df, counterfactual_saved, trades_to_df


def _drawdown_series(equity: pd.Series) -> pd.Series:
    peak = equity.cummax()
    return (equity - peak) / peak.replace(0, pd.NA) * 100


def show_pair_dashboard(result: BacktestResult, label: str = "baseline") -> None:
    df = trades_to_df(result)
    fig = make_subplots(
        rows=3,
        cols=2,
        subplot_titles=(
            "Equity curve",
            "Drawdown %",
            "Per-trade P/L",
            "Win rate by exit reason",
            "Entry score (wins vs losses)",
            "ADX at entry (wins vs losses)",
        ),
        vertical_spacing=0.08,
        specs=[[{}, {}], [{}, {}], [{}, {}]],
    )

    if not result.equity_curve.empty:
        eq = result.equity_curve
        fig.add_trace(
            go.Scatter(x=eq.index, y=eq.values, name="Equity", line=dict(color="#2563eb")),
            row=1,
            col=1,
        )
        fig.add_hline(
            y=result.initial_balance,
            line_dash="dash",
            line_color="#94a3b8",
            row=1,
            col=1,
        )
        dd = _drawdown_series(eq)
        fig.add_trace(
            go.Scatter(x=dd.index, y=dd.values, fill="tozeroy", name="DD", line=dict(color="#ef4444")),
            row=1,
            col=2,
        )

    if not df.empty:
        colors = ["#22c55e" if w else "#ef4444" for w in df["win"]]
        fig.add_trace(
            go.Bar(x=df["trade_id"], y=df["pnl"], marker_color=colors, name="P/L"),
            row=2,
            col=1,
        )
        reason_wr = df.groupby("reason")["win"].mean() * 100
        fig.add_trace(
            go.Bar(x=reason_wr.index.astype(str), y=reason_wr.values, name="WR% by reason"),
            row=2,
            col=2,
        )
        for win, color, name in [(True, "#22c55e", "Wins"), (False, "#ef4444", "Losses")]:
            sub = df[df["win"] == win]
            fig.add_trace(
                go.Histogram(x=sub["score"], name=name, marker_color=color, opacity=0.7),
                row=3,
                col=1,
            )
        for win, color, name in [(True, "#22c55e", "Wins"), (False, "#ef4444", "Losses")]:
            sub = df[df["win"] == win]
            fig.add_trace(
                go.Histogram(x=sub["adx"], name=f"ADX {name}", marker_color=color, opacity=0.7),
                row=3,
                col=2,
            )

    pf = result.pf if result.pf != float("inf") else 99.9
    title = (
        f"{result.pair} [{label}] | Net ${result.net_pnl:+.2f} | "
        f"WR {result.win_rate * 100:.1f}% | PF {pf:.2f} | "
        f"Trades {len(result.trades)}"
    )
    fig.update_layout(height=900, title_text=title, barmode="overlay", showlegend=True)
    fig.show()


def show_comparison(
    baseline: list[BacktestResult],
    improved: list[BacktestResult],
) -> None:
    bmap = {r.pair: r for r in baseline}
    imap = {r.pair: r for r in improved}
    pairs = sorted(set(bmap) | set(imap))

    wr_b, wr_i, net_b, net_i = [], [], [], []
    for p in pairs:
        wr_b.append(bmap[p].win_rate * 100 if p in bmap else 0)
        wr_i.append(imap[p].win_rate * 100 if p in imap else 0)
        net_b.append(bmap[p].net_pnl if p in bmap else 0)
        net_i.append(imap[p].net_pnl if p in imap else 0)

    fig = make_subplots(rows=1, cols=2, subplot_titles=("Win rate %", "Net P/L $"))
    fig.add_trace(go.Bar(name="Baseline", x=pairs, y=wr_b, marker_color="#6366f1"), row=1, col=1)
    fig.add_trace(go.Bar(name="Improved", x=pairs, y=wr_i, marker_color="#22c55e"), row=1, col=1)
    fig.add_trace(go.Bar(name="Baseline", x=pairs, y=net_b, marker_color="#6366f1"), row=1, col=2)
    fig.add_trace(go.Bar(name="Improved", x=pairs, y=net_i, marker_color="#22c55e"), row=1, col=2)
    fig.update_layout(
        height=500,
        title_text="Baseline vs improved (loss-analysis filters)",
        barmode="group",
    )
    fig.show()


def show_loss_deep_dive(df: pd.DataFrame, guards: TradeGuards) -> None:
    if df.empty:
        print("No trades for loss deep-dive.")
        return

    cf = counterfactual_saved(df, guards)
    losers = cf[~cf["win"]]

    fig = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=(
            "RSI at entry (losses)",
            "Z-score at entry (losses)",
            "Fallback: wins vs losses",
            "Score at entry (losses)",
        ),
    )
    fig.add_trace(go.Histogram(x=losers["rsi"], marker_color="#ef4444", name="RSI"), row=1, col=1)
    fig.add_trace(go.Histogram(x=losers["z_score"], marker_color="#ef4444", name="Z"), row=1, col=2)

    fb_labels, fb_vals, fb_colors = [], [], []
    for win, label in [(True, "Win+FB"), (True, "Win noFB"), (False, "Loss+FB"), (False, "Loss noFB")]:
        use_fb = "FB" in label and "noFB" not in label
        n = len(df[(df["win"] == win) & (df["used_fallback"] == use_fb)])
        if n:
            fb_labels.append(label)
            fb_vals.append(n)
            fb_colors.append("#22c55e" if win else "#ef4444")
    fig.add_trace(go.Bar(x=fb_labels, y=fb_vals, marker_color=fb_colors), row=2, col=1)
    fig.add_trace(go.Histogram(x=losers["score"], marker_color="#f59e0b", name="Score"), row=2, col=2)

    blocked_n = int(losers["would_block"].sum())
    fig.update_layout(
        height=700,
        title_text=f"Loss deep-dive | guards would block {blocked_n}/{len(losers)} losses",
    )
    fig.show()

    print("\n--- Losers that guards WOULD have blocked ---")
    blocked_losses = losers[losers["would_block"]]
    if blocked_losses.empty:
        print("(none)")
    else:
        print(
            blocked_losses[
                ["pair", "entry_time", "side", "pnl", "score", "adx", "rsi", "z_score", "used_fallback"]
            ].to_string(index=False)
        )

    print("\n--- Losers that STILL slip through ---")
    remain = losers[~losers["would_block"]]
    if remain.empty:
        print("(none)")
    else:
        print(
            remain[
                ["pair", "entry_time", "side", "pnl", "reason", "score", "adx", "rsi", "z_score"]
            ].head(20).to_string(index=False)
        )


def show_equity_overlay(baseline: list[BacktestResult], improved: list[BacktestResult]) -> None:
    fig = go.Figure()
    for r in baseline:
        if r.equity_curve.empty:
            continue
        norm = (r.equity_curve / r.initial_balance - 1) * 100
        fig.add_trace(
            go.Scatter(x=norm.index, y=norm.values, name=f"{r.pair} base", line=dict(dash="dot"))
        )
    for r in improved:
        if r.equity_curve.empty:
            continue
        norm = (r.equity_curve / r.initial_balance - 1) * 100
        fig.add_trace(go.Scatter(x=norm.index, y=norm.values, name=f"{r.pair} improved"))
    fig.update_layout(title="Return % — baseline (dotted) vs improved (solid)", height=500)
    fig.show()
