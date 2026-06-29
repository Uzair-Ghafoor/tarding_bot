#!/usr/bin/env bash
# On VPS: pack all logs for download. Cron: 0 */6 * * * ~/scalpbot/scripts/bundle-logs.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs data

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="logs/bundle-$STAMP.tar.gz"

tar -czf "$OUT" \
  data/status.json \
  data/events.jsonl \
  data/paper_trades.jsonl \
  data/agent_decisions.jsonl \
  data/runtime.json \
  logs/autopilot.log \
  logs/dashboard.log \
  2>/dev/null || tar -czf "$OUT" data/*.jsonl data/status.json logs/*.log 2>/dev/null || true

ln -sf "$(basename "$OUT")" logs/bundle-latest.tar.gz
echo "Created $OUT"
