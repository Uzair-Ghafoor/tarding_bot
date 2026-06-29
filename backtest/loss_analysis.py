"""Analyze losing trades and derive filters that would have blocked them."""

from __future__ import annotations

import pandas as pd

from backtest.engine import BacktestResult
from backtest.guards import TradeGuards


def trades_to_df(result: BacktestResult) -> pd.DataFrame:
    rows = []
    for i, t in enumerate(result.trades):
        rows.append(
            {
                "pair": result.pair,
                "trade_id": i + 1,
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
                "side": t.side,
                "pnl": t.pnl,
                "win": t.pnl >= 0,
                "reason": t.reason,
                "score": t.score,
                "adx": t.adx,
                "rsi": t.rsi,
                "z_score": t.z_score,
                "vol_ratio": t.vol_ratio,
                "used_fallback": t.used_fallback,
                "reasons": ", ".join(t.reasons[:5]),
            }
        )
    return pd.DataFrame(rows)


def all_trades_df(results: list[BacktestResult]) -> pd.DataFrame:
    parts = [trades_to_df(r) for r in results if r.trades]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def loss_patterns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    losers = df[~df["win"]]
    winners = df[df["win"]]
    rows = []
    for col in ("score", "adx", "rsi", "z_score", "vol_ratio"):
        rows.append(
            {
                "feature": col,
                "losers_avg": losers[col].mean(),
                "winners_avg": winners[col].mean(),
                "losers_med": losers[col].median(),
                "winners_med": winners[col].median(),
            }
        )
    fb_loss = losers["used_fallback"].mean() * 100 if len(losers) else 0
    fb_win = winners["used_fallback"].mean() * 100 if len(winners) else 0
    rows.append(
        {
            "feature": "fallback_pct",
            "losers_avg": fb_loss,
            "winners_avg": fb_win,
            "losers_med": fb_loss,
            "winners_med": fb_win,
        }
    )
    return pd.DataFrame(rows)


def exit_reason_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    return df.groupby(["win", "reason"]).size().reset_index(name="count")


def suggest_guards(df: pd.DataFrame, base: TradeGuards | None = None) -> TradeGuards:
    """Tune guards only where losers differ meaningfully from winners."""
    g = base or TradeGuards()
    if df.empty or len(df) < 20:
        g.notes.append("Not enough trades for auto-tuning")
        return g

    losers = df[~df["win"]]
    winners = df[df["win"]]

    # Score rarely separates when both cluster at 100
    if len(winners) >= 15 and len(losers) >= 15:
        gap = winners["score"].median() - losers["score"].median()
        if gap >= 8:
            proposed = max(g.min_score, int(winners["score"].quantile(0.20)))
            proposed = min(proposed, 85)
            g.min_score = proposed
            g.notes.append(f"min_score={proposed} (winners score higher)")
        else:
            g.notes.append("Score similar on wins/losses — not raising min_score")

    # Weak ADX more common in losses?
    if len(losers) >= 10:
        weak_loss = (losers["adx"] < 22).mean()
        weak_win = (winners["adx"] < 22).mean() if len(winners) else 0
        if weak_loss > weak_win + 0.06:
            g.min_adx = max(g.min_adx, 22.0)
            g.notes.append(f"ADX min 22 ({weak_loss:.0%} weak-trend losses)")

    # M5 fallback
    fb_loss = losers["used_fallback"].mean()
    fb_win = winners["used_fallback"].mean()
    if fb_loss > fb_win + 0.04 and fb_loss > 0.10:
        trial = TradeGuards(**{**g.__dict__, "block_fallback": True})
        cf = counterfactual_saved(df, trial)
        if cf["saved_loss"].sum() > cf["blocked_win"].sum():
            g.block_fallback = True
            g.notes.append(f"Block M5 fallback ({fb_loss:.0%} losses vs {fb_win:.0%} wins)")
        else:
            g.notes.append("Keep M5 fallback (blocks more wins than it saves)")

    # Buy RSI chase: losers buy higher RSI
    buy_loss = losers[losers["side"] == "buy"]
    buy_win = winners[winners["side"] == "buy"]
    if len(buy_loss) >= 8 and len(buy_win) >= 8:
        if buy_loss["rsi"].median() > buy_win["rsi"].median() + 2:
            cap = min(g.rsi_buy_max, max(55.0, buy_win["rsi"].quantile(0.70)))
            g.rsi_buy_max = round(cap, 1)
            g.notes.append(f"RSI buy cap {cap:.0f} (losers chased higher RSI)")

    # Extended Z on buys
    if len(buy_loss) >= 8:
        hot_loss = (buy_loss["z_score"] > 0.85).mean()
        hot_win = (buy_win["z_score"] > 0.85).mean() if len(buy_win) else 0
        if hot_loss > hot_win + 0.08:
            g.max_z_buy = min(g.max_z_buy, 0.85)
            g.notes.append("Z buy cap 0.85 (extended entries lost more)")

    # Volatility spikes
    if len(losers) >= 10 and losers["vol_ratio"].median() > winners["vol_ratio"].median() + 0.12:
        g.max_vol_ratio = min(g.max_vol_ratio, 1.85)
        g.notes.append("Cap vol_ratio 1.85")

    return g


def counterfactual_saved(df: pd.DataFrame, guards: TradeGuards) -> pd.DataFrame:
    if df.empty:
        return df

    def blocked(row) -> bool:
        if row["score"] < guards.min_score:
            return True
        if row["adx"] < guards.min_adx:
            return True
        if guards.block_fallback and row["used_fallback"]:
            return True
        if row["vol_ratio"] > guards.max_vol_ratio:
            return True
        if row["side"] == "buy":
            if row["rsi"] > guards.rsi_buy_max or row["rsi"] < guards.rsi_buy_min:
                return True
            if row["z_score"] > guards.max_z_buy or row["z_score"] < guards.min_z_buy:
                return True
        else:
            if row["rsi"] < guards.rsi_sell_min or row["rsi"] > guards.rsi_sell_max:
                return True
            if row["z_score"] < -guards.max_z_sell:
                return True
        return False

    out = df.copy()
    out["would_block"] = out.apply(blocked, axis=1)
    out["saved_loss"] = out.apply(
        lambda r: -r["pnl"] if (not r["win"] and r["would_block"]) else 0.0, axis=1
    )
    out["blocked_win"] = out.apply(
        lambda r: r["pnl"] if (r["win"] and r["would_block"]) else 0.0, axis=1
    )
    return out


def print_loss_report(df: pd.DataFrame, guards: TradeGuards) -> None:
    if df.empty:
        print("No trades to analyze.")
        return

    losers = df[~df["win"]]
    print("\n" + "=" * 70)
    print("LOSING TRADE ANALYSIS")
    print("=" * 70)
    print(f"Total trades: {len(df)} | Losses: {len(losers)} | WR: {df['win'].mean() * 100:.1f}%")
    print("\nWhy losses exit:")
    if not losers.empty:
        print(losers["reason"].value_counts().to_string())
    print(f"\nM5 fallback in losses: {losers['used_fallback'].mean() * 100:.1f}%")
    print(f"M5 fallback in wins:   {df[df['win']]['used_fallback'].mean() * 100:.1f}%")

    print("\nLosers vs winners (averages):")
    pat = loss_patterns(df)
    if not pat.empty:
        print(pat.to_string(index=False, float_format=lambda x: f"{x:.2f}"))

    print("\nWorst 12 losses:")
    cols = ["pair", "entry_time", "side", "pnl", "reason", "score", "adx", "rsi", "z_score", "used_fallback"]
    if not losers.empty:
        print(losers.nsmallest(12, "pnl")[cols].to_string(index=False))

    cf = counterfactual_saved(df, guards)
    saved = cf["saved_loss"].sum()
    blocked_wins = cf["blocked_win"].sum()
    n_bl = int(((~cf["win"]) & cf["would_block"]).sum())
    n_bw = int((cf["win"] & cf["would_block"]).sum())
    print(f"\nProposed fixes: {guards.label()}")
    for note in guards.notes:
        print(f"  • {note}")
    print(f"\nIf we had these rules historically:")
    print(f"  Block {n_bl} losing trades → save ${saved:.2f}")
    print(f"  Block {n_bw} winning trades → miss ${blocked_wins:.2f}")
    print(f"  Net counterfactual swing: ${saved - blocked_wins:+.2f}")
