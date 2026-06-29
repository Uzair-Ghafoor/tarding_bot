#!/usr/bin/env bash
# Stop autopilot + dashboard (used by npm run stop and dev cleanup)
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

_stop_pid() {
  local file="$1"
  if [[ -f "$file" ]]; then
    local pid
    pid="$(cat "$file")"
    kill "$pid" 2>/dev/null || true
    rm -f "$file"
  fi
}

_stop_pid "$ROOT/logs/dashboard.pid"
_stop_pid "$ROOT/logs/autopilot.pid"

pkill -f "autopilot.py" 2>/dev/null || true
pkill -f "streamlit run dashboard.py" 2>/dev/null || true
