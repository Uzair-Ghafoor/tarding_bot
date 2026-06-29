"""Build a compact market snapshot for the AI brain."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from backtest.guards import TradeGuards
from backtest.pairs import PAIRS
from backtest.signals import BarSetup, evaluate_at
from config import CONFIG
from run_backtest import LIVE_GUARDS
from session import in_trading_session

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
AGENT_LOG = os.path.join(DATA_DIR, "agent_decisions.jsonl")


@dataclass
class MarketSnapshot:
    ts: str
    pair: str
    price: float
    bar_time: str
    in_session: bool
    setup: dict
    quant_signal: str | None
    quant_ok: bool
    guards_pass: bool
    flow: dict
    basket: dict
    session: dict
    guards_label: str = field(default_factory=lambda: LIVE_GUARDS.label())

    def to_prompt(self) -> str:
        return json.dumps(
            {
                "pair": self.pair,
                "price": self.price,
                "bar_time": self.bar_time,
                "in_session": self.in_session,
                "quant_signal": self.quant_signal,
                "quant_ok": self.quant_ok,
                "guards_pass": self.guards_pass,
                "setup": self.setup,
                "flow": self.flow,
                "basket": self.basket,
                "session": self.session,
                "rules": {
                    "min_score": CONFIG.min_confluence_score,
                    "min_adx": CONFIG.adx_min,
                    "only_open_if_guards_pass": True,
                    "actions": ["open_buy", "open_sell", "skip", "hold", "close"],
                },
            },
            indent=2,
        )


def _align_last(m15, h1, d1):
    m_idx = len(m15) - 1
    ts = m15.index[m_idx]
    h_idx = h1.index.searchsorted(ts, side="right") - 1
    d_idx = d1.index.searchsorted(ts, side="right") - 1
    return max(0, h_idx), m_idx, max(0, d_idx)


def _flow_metrics(m5) -> dict:
    if m5 is None or len(m5) < 20:
        return {"vol_spike": False, "m5_change_pips": 0.0, "bars": 0}
    tail = m5.tail(12)
    vol = float(tail["volume"].iloc[-1]) if "volume" in tail else 0.0
    vol_avg = float(tail["volume"].mean()) if "volume" in tail else 1.0
    chg = float(tail["close"].iloc[-1] - tail["close"].iloc[0])
    return {
        "vol_spike": vol > vol_avg * 1.8 if vol_avg > 0 else False,
        "m5_change_pips": round(chg, 5),
        "bars": len(tail),
        "last_vol_ratio": round(vol / vol_avg, 2) if vol_avg > 0 else 1.0,
    }


def _load_recent_trades(limit: int = 8) -> list[dict]:
    path = os.path.join(DATA_DIR, "paper_trades.jsonl")
    if not os.path.isfile(path):
        return []
    rows: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("event") in ("open_basket", "close_basket"):
                rows.append(row)
    return rows[-limit:]


def build_snapshot(
    pair: str,
    frames: dict,
    *,
    guards: TradeGuards | None = None,
    basket: dict | None = None,
    stats: dict | None = None,
    use_session: bool = True,
) -> MarketSnapshot:
    guards = guards or LIVE_GUARDS
    m15, h1, d1, m5 = frames["m15"], frames["h1"], frames["d1"], frames["m5"]
    price = float(frames["last_price"])
    h_idx, m_idx, d_idx = _align_last(m15, h1, d1)
    setup: BarSetup = evaluate_at(h1, m15, d1, h_idx, m_idx, d_idx, guards=guards)
    quant_ok = setup.passes_guards(guards) and bool(setup.side)

    return MarketSnapshot(
        ts=datetime.now(timezone.utc).isoformat(),
        pair=pair,
        price=price,
        bar_time=str(m5.index[-1]),
        in_session=not use_session or in_trading_session(),
        setup={
            "side": setup.side,
            "score": setup.score,
            "reasons": setup.reasons[:6],
            "adx": round(setup.adx, 1),
            "rsi": round(setup.rsi, 1),
            "z_score": round(setup.z_score, 2),
            "vol_ratio": round(setup.vol_ratio, 2),
            "used_fallback": setup.used_fallback,
        },
        quant_signal=setup.side,
        quant_ok=quant_ok,
        guards_pass=setup.passes_guards(guards),
        flow=_flow_metrics(m5),
        basket=basket or {"active": False},
        session={
            **(stats or {}),
            "recent_trades": _load_recent_trades(),
            "reference_balance": CONFIG.reference_balance,
            "pair_pip": PAIRS[pair].pip_size,
        },
        guards_label=guards.label(),
    )
