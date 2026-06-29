"""AI decision brain — Claude API with quant-rules fallback."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from agent.types import Action, Decision

SYSTEM_PROMPT = """You are the autonomous brain of a forex basket scalping bot ($30 account, 10x0.01 lots).

You receive a JSON market snapshot each cycle. Decide ONE action:
- open_buy / open_sell — only if quant_ok AND guards_pass are true
- skip — no trade this cycle (weak setup, bad flow, chop, or risk-off)
- hold — keep existing basket open (only when basket.active is true)
- close — exit basket early (only when basket.active and mark_pnl clearly deteriorating)

Hard rules you MUST follow:
1. NEVER open_buy/open_sell if quant_ok is false or guards_pass is false
2. Prefer skip in low ADX, ATR spikes, or when reasons include ADX_weak / ATR_spike
3. Be selective — quality over quantity; skipping is normal
4. Respond with ONLY valid JSON, no markdown:

{"action":"skip","confidence":0.0,"reasoning":"one short sentence"}
"""


def _parse_decision(raw: str) -> Decision | None:
    text = raw.strip()
    if "```" in text:
        m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if m:
            text = m.group(0)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None

    action = str(data.get("action", "skip")).lower().replace("-", "_")
    valid: list[Action] = ["open_buy", "open_sell", "skip", "hold", "close"]
    if action not in valid:
        return None
    return Decision(
        action=action,  # type: ignore[arg-type]
        confidence=float(data.get("confidence", 0.5)),
        reasoning=str(data.get("reasoning", ""))[:300],
        source="claude",
    )


def _call_claude(snapshot: MarketSnapshot) -> Decision | None:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None

    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    payload = {
        "model": model,
        "max_tokens": 256,
        "system": SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": f"Market snapshot:\n{snapshot.to_prompt()}\n\nYour JSON decision:",
            }
        ],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            body = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
        return None

    blocks = body.get("content") or []
    text = ""
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            text += block.get("text", "")
    return _parse_decision(text)


def _rules_decide(snapshot: MarketSnapshot) -> Decision:
    basket = snapshot.basket or {}
    if basket.get("active"):
        mark = float(basket.get("mark_pnl", 0))
        tp = float(basket.get("tp", 0))
        sl = float(basket.get("sl", 0))
        if mark >= tp * 0.95:
            return Decision("hold", 0.9, "Near basket target", "rules")
        if mark <= -sl * 0.85:
            return Decision("close", 0.85, "Basket drawdown elevated", "rules")
        return Decision("hold", 0.7, "Managing open basket", "rules")

    if not snapshot.in_session:
        return Decision("skip", 1.0, "Outside trading session", "rules")

    if not snapshot.guards_pass or not snapshot.quant_ok:
        reasons = snapshot.setup.get("reasons") or ["no setup"]
        return Decision("skip", 0.8, ", ".join(reasons[:3]), "rules")

    side = snapshot.quant_signal
    if side == "buy":
        return Decision("open_buy", 0.75, f"Quant confluence score={snapshot.setup.get('score')}", "rules")
    if side == "sell":
        return Decision("open_sell", 0.75, f"Quant confluence score={snapshot.setup.get('score')}", "rules")
    return Decision("skip", 0.5, "No directional signal", "rules")


def _enforce_safety(snapshot: MarketSnapshot, decision: Decision) -> Decision:
    """Hard rails: AI cannot open without quant approval."""
    basket_active = bool((snapshot.basket or {}).get("active"))

    if decision.action in ("open_buy", "open_sell"):
        if not snapshot.guards_pass or not snapshot.quant_ok:
            return Decision(
                "skip",
                decision.confidence,
                f"Blocked: guards/quant failed ({decision.reasoning})",
                decision.source,
                vetoed_quant=True,
            )
        expected = "open_buy" if snapshot.quant_signal == "buy" else "open_sell"
        if decision.action != expected:
            return Decision(
                expected,  # type: ignore[arg-type]
                decision.confidence,
                f"Aligned to quant side ({decision.reasoning})",
                decision.source,
            )

    if decision.action in ("hold", "close") and not basket_active:
        return Decision("skip", decision.confidence, "No basket to manage", decision.source)

    if not snapshot.in_session and decision.action.startswith("open_"):
        return Decision("skip", 1.0, "Outside session", decision.source)

    return decision


def decide(snapshot: MarketSnapshot, *, use_claude: bool = True) -> Decision:
    decision: Decision | None = None
    if use_claude:
        decision = _call_claude(snapshot)
    if decision is None:
        decision = _rules_decide(snapshot)
    return _enforce_safety(snapshot, decision)
