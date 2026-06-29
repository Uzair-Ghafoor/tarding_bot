"""Matplotlib charts for backtest results."""

from __future__ import annotations

import os

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

from backtest.engine import BacktestResult

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def _ensure_out() -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    return OUTPUT_DIR


def plot_pair(result: BacktestResult) -> str:
    out = _ensure_out()
    path = os.path.join(out, f"{result.pair}_report.png")

    fig, axes = plt.subplots(3, 1, figsize=(14, 11), gridspec_kw={"height_ratios": [2, 1, 1]})
    fig.suptitle(
        f"{result.pair} backtest | {result.start.date()} → {result.end.date()}",
        fontsize=14,
        fontweight="bold",
    )

    # Equity curve
    ax = axes[0]
    if not result.equity_curve.empty:
        eq = result.equity_curve
        ax.plot(eq.index, eq.values, color="#2563eb", linewidth=1.5, label="Equity")
        ax.axhline(result.initial_balance, color="#94a3b8", linestyle="--", linewidth=1)
        ax.fill_between(
            eq.index,
            result.initial_balance,
            eq.values,
            where=eq.values >= result.initial_balance,
            alpha=0.15,
            color="#22c55e",
        )
        ax.fill_between(
            eq.index,
            result.initial_balance,
            eq.values,
            where=eq.values < result.initial_balance,
            alpha=0.15,
            color="#ef4444",
        )
    ax.set_ylabel("Balance ($)")
    ax.set_title("Equity curve")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)

    # Drawdown
    ax = axes[1]
    if not result.equity_curve.empty:
        eq = result.equity_curve
        peak = eq.cummax()
        dd = (eq - peak) / peak * 100
        ax.fill_between(dd.index, dd.values, 0, color="#ef4444", alpha=0.4)
        ax.plot(dd.index, dd.values, color="#b91c1c", linewidth=1)
    ax.set_ylabel("Drawdown %")
    ax.set_title("Drawdown")
    ax.grid(True, alpha=0.3)

    # Trade P/L bars
    ax = axes[2]
    if result.trades:
        pnls = [t.pnl for t in result.trades]
        colors = ["#22c55e" if p >= 0 else "#ef4444" for p in pnls]
        ax.bar(range(len(pnls)), pnls, color=colors, width=1.0)
        ax.axhline(0, color="#64748b", linewidth=0.8)
    ax.set_xlabel("Trade #")
    ax.set_ylabel("Basket P/L ($)")
    ax.set_title("Per-basket profit/loss")

    # Stats box
    stats = (
        f"Net P/L: ${result.net_pnl:+.2f}\n"
        f"Return: {result.net_pnl / result.initial_balance * 100:+.1f}%\n"
        f"Trades: {len(result.trades)}\n"
        f"Win rate: {result.win_rate * 100:.1f}%\n"
        f"Expectancy: ${result.expectancy:.3f}\n"
        f"Profit factor: {result.pf:.2f}\n"
        f"Max DD: {result.max_drawdown_pct:.1f}%"
    )
    fig.text(
        0.02, 0.02, stats, fontsize=10, family="monospace",
        bbox=dict(boxstyle="round", facecolor="#f1f5f9", edgecolor="#cbd5e1"),
    )

    plt.tight_layout(rect=[0, 0.06, 1, 0.96])
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def plot_summary(results: list[BacktestResult]) -> str:
    out = _ensure_out()
    path = os.path.join(out, "ALL_PAIRS_summary.png")

    names = [r.pair for r in results]
    net = [r.net_pnl for r in results]
    wr = [r.win_rate * 100 for r in results]
    trades = [len(r.trades) for r in results]
    colors = ["#22c55e" if n >= 0 else "#ef4444" for n in net]

    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    fig.suptitle("Multi-pair backtest summary (quant basket strategy)", fontsize=14, fontweight="bold")

    ax = axes[0, 0]
    bars = ax.barh(names, net, color=colors)
    ax.axvline(0, color="#64748b")
    ax.set_xlabel("Net P/L ($)")
    ax.set_title("Net profit/loss per pair")
    for b, v in zip(bars, net):
        ax.text(v + (0.3 if v >= 0 else -0.3), b.get_y() + b.get_height() / 2,
                f"${v:+.1f}", va="center", ha="left" if v >= 0 else "right", fontsize=9)

    ax = axes[0, 1]
    ax.bar(names, wr, color="#6366f1")
    ax.set_ylabel("Win rate %")
    ax.set_title("Win rate")
    ax.set_ylim(0, 100)

    ax = axes[1, 0]
    ax.bar(names, trades, color="#0ea5e9")
    ax.set_ylabel("Basket trades")
    ax.set_title("Number of baskets")

    ax = axes[1, 1]
    for r in results:
        if r.equity_curve.empty:
            continue
        norm = (r.equity_curve / r.initial_balance - 1) * 100
        ax.plot(norm.index, norm.values, label=r.pair, linewidth=1.2)
    ax.axhline(0, color="#94a3b8", linestyle="--")
    ax.set_ylabel("Return %")
    ax.set_title("Normalized equity (all pairs)")
    ax.legend(fontsize=8, loc="best")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def print_table(results: list[BacktestResult]) -> None:
    print("\n" + "=" * 88)
    print(f"{'Pair':<10} {'From':<12} {'To':<12} {'Trades':>7} {'WR%':>7} {'Net$':>9} {'EV':>8} {'PF':>6} {'MaxDD%':>7}")
    print("-" * 88)
    for r in results:
        pf = r.pf if r.pf != float("inf") else 99.9
        print(
            f"{r.pair:<10} {str(r.start.date()):<12} {str(r.end.date()):<12} "
            f"{len(r.trades):>7} {r.win_rate * 100:>6.1f}% "
            f"{r.net_pnl:>+8.2f} {r.expectancy:>+7.3f} {pf:>6.2f} {r.max_drawdown_pct:>6.1f}%"
        )
    total = sum(r.net_pnl for r in results)
    print("-" * 88)
    print(f"{'TOTAL':<10} {'':<12} {'':<12} {'':<7} {'':<7} {total:>+8.2f}")
    print("=" * 88)
