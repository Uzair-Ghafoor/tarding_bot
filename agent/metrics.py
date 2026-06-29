"""Human-readable scan metrics vs entry thresholds."""

from __future__ import annotations

from backtest.guards import TradeGuards
from config import CONFIG
from agent.snapshot import MarketSnapshot


def _tick(ok: bool) -> str:
    return "OK" if ok else "NO"


def gate_checklist(snapshot: MarketSnapshot, guards: TradeGuards) -> dict:
    s = snapshot.setup
    side = s.get("side")
    adx = float(s.get("adx", 0))
    score = int(s.get("score", 0))
    rsi = float(s.get("rsi", 50))
    z = float(s.get("z_score", 0))
    vol = float(s.get("vol_ratio", 1))

    adx_ok = adx >= guards.min_adx
    score_ok = score >= guards.min_score
    side_ok = bool(side)
    vol_ok = vol <= guards.max_vol_ratio
    session_ok = snapshot.in_session

    rsi_ok = True
    z_ok = True
    if side == "buy":
        rsi_ok = guards.rsi_buy_min <= rsi <= guards.rsi_buy_max
        z_ok = guards.min_z_buy <= z <= guards.max_z_buy
    elif side == "sell":
        rsi_ok = guards.rsi_sell_min <= rsi <= guards.rsi_sell_max
        z_ok = z >= -guards.max_z_sell

    rsi_state = "—" if not side else _tick(rsi_ok)
    z_state = "—" if not side else _tick(z_ok)

    fallback_ok = not (guards.block_fallback and s.get("used_fallback"))
    reasons = s.get("reasons") or []

    gates = {
        "session": session_ok,
        "adx": adx_ok,
        "score": score_ok,
        "side": side_ok,
        "rsi": rsi_ok if side else False,
        "z_score": z_ok if side else False,
        "atr_spike": vol_ok,
        "fallback": fallback_ok,
    }
    passed = sum(1 for v in gates.values() if v)
    total = len(gates)

    return {
        "gates": gates,
        "passed": passed,
        "total": total,
        "ready": snapshot.quant_ok and snapshot.guards_pass,
        "reasons": reasons,
        "side": side,
        "adx": adx,
        "score": score,
        "rsi": rsi,
        "z": z,
        "vol": vol,
        "rsi_state": rsi_state,
        "z_state": z_state,
    }


def format_scan_metrics(snapshot: MarketSnapshot, guards: TradeGuards, *, scan_n: int) -> str:
    c = gate_checklist(snapshot, guards)
    side = c["side"] or "—"
    rsi_rng = f"{guards.rsi_buy_min:.0f}-{guards.rsi_buy_max:.0f}" if side == "buy" else (
        f"{guards.rsi_sell_min:.0f}-{guards.rsi_sell_max:.0f}" if side == "sell" else "40-60"
    )
    z_need = f"≤{guards.max_z_buy}" if side == "buy" else (f"≥-{guards.max_z_sell}" if side == "sell" else f"≤{guards.max_z_buy}")

    lines = [
        f"SCAN #{scan_n} | {snapshot.pair} @ {snapshot.price:.5f}",
        (
            f"  side={side} | score={c['score']}/{guards.min_score} {_tick(c['gates']['score'])}"
            f" | ADX={c['adx']:.1f}/{guards.min_adx:.0f} {_tick(c['gates']['adx'])}"
        ),
        (
            f"  RSI={c['rsi']:.1f} need {rsi_rng} {c['rsi_state']}"
            f" | Z={c['z']:.2f} need {z_need} {c['z_state']}"
        ),
        (
            f"  ATR×={c['vol']:.2f} max {guards.max_vol_ratio} {_tick(c['gates']['atr_spike'])}"
            f" | session {_tick(c['gates']['session'])}"
            f" | H1+M15+M5 {_tick(c['gates']['side'] and c['gates']['score'])}"
        ),
        f"  gates {c['passed']}/{c['total']} | OPEN={'YES' if c['ready'] else 'NO'} | {', '.join(c['reasons'][:4]) or 'waiting'}",
    ]
    return "\n".join(lines)


def format_scan_one_line(snapshot: MarketSnapshot, guards: TradeGuards, *, scan_n: int) -> str:
    """Compact single line for watch tail."""
    c = gate_checklist(snapshot, guards)
    side = c["side"] or "—"
    return (
        f"SCAN #{scan_n} | {snapshot.pair} {snapshot.price:.5f} | "
        f"side={side} score={c['score']}/{guards.min_score} ADX={c['adx']:.1f}/{guards.min_adx:.0f} "
        f"RSI={c['rsi']:.1f} Z={c['z']:.2f} ATR×={c['vol']:.2f} | "
        f"gates={c['passed']}/{c['total']} OPEN={'YES' if c['ready'] else 'NO'} | "
        f"{', '.join(c['reasons'][:3]) or 'wait'}"
    )
