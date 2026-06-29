#!/usr/bin/env bash
# npm run dev — start dashboard + autopilot, stream logs to terminal
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SYMBOL="${PAPER_SYMBOL:-XAUUSDT}"
HOURS="${HOURS:-8}"
SCAN_SEC="${SCAN_SEC:-5}"
PRICE_SEC="${PRICE_SEC:-2}"
BASKET_PRICE_SEC="${BASKET_PRICE_SEC:-0.25}"
DASH_PORT="${DASH_PORT:-8501}"
BRAIN="${BRAIN:-rules}"
NO_SESSION="${NO_SESSION:-1}"

mkdir -p logs data

bash "$ROOT/scripts/stop.sh" 2>/dev/null || true

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 not found" >&2
  exit 1
fi
if ! command -v streamlit >/dev/null 2>&1; then
  echo "error: streamlit not found — run: pip install streamlit plotly" >&2
  exit 1
fi

echo ""
echo "  ScalpBot dev"
echo "  ─────────────────────────────────────"
echo "  Symbol     $SYMBOL"
echo "  Brain      $BRAIN"
echo "  Session    $([ "$NO_SESSION" = "1" ] && echo "24/7 (--no-session)" || echo "London+NY")"
echo "  Price      ${PRICE_SEC}s scan · ${BASKET_PRICE_SEC}s in basket"
echo "  Dashboard  http://localhost:${DASH_PORT}"
echo "  Logs       logs/autopilot.log"
echo "  ─────────────────────────────────────"
echo "  Ctrl+C to stop everything"
echo ""

streamlit run dashboard.py \
  --server.headless true \
  --server.port "$DASH_PORT" \
  >> logs/dashboard.log 2>&1 &
echo $! > logs/dashboard.pid

_cleanup() {
  echo ""
  echo "Stopping ScalpBot..."
  bash "$ROOT/scripts/stop.sh" 2>/dev/null || true
}
trap _cleanup EXIT INT TERM

export MT5_BASKET_PRICE_SEC="$BASKET_PRICE_SEC"

ARGS=(
  --hours "$HOURS"
  --symbol "$SYMBOL"
  --scan-sec "$SCAN_SEC"
  --price-sec "$PRICE_SEC"
  --brain "$BRAIN"
)
if [[ "$NO_SESSION" == "1" ]]; then
  ARGS+=(--no-session)
fi

exec python3 autopilot.py "${ARGS[@]}"
