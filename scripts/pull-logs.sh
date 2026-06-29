#!/usr/bin/env bash
# Pull paper logs from VPS to Mac — set PAPER_HOST=ubuntu@YOUR_IP
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${PAPER_HOST:-}"
DEST="${PAPER_PULL_DIR:-$ROOT/pulled}"
REMOTE_DIR="${PAPER_REMOTE_DIR:-~/scalpbot}"

if [[ -z "$HOST" ]]; then
  if [[ -f "$ROOT/.env" ]]; then
    # shellcheck disable=SC1090
    source <(grep -E '^PAPER_HOST=' "$ROOT/.env" | sed 's/^/export /')
    HOST="${PAPER_HOST:-}"
  fi
fi

if [[ -z "$HOST" ]]; then
  echo "error: set PAPER_HOST=ubuntu@YOUR_VPS_IP" >&2
  echo "  export PAPER_HOST=ubuntu@1.2.3.4 && npm run pull-logs" >&2
  exit 1
fi

mkdir -p "$DEST/data" "$DEST/logs"

echo "Pulling from $HOST:$REMOTE_DIR → $DEST"
rsync -avz --progress \
  "$HOST:$REMOTE_DIR/data/" "$DEST/data/" \
  "$HOST:$REMOTE_DIR/logs/" "$DEST/logs/" \
  2>/dev/null || {
  echo "rsync failed — trying scp..."
  scp -r "$HOST:$REMOTE_DIR/data/"* "$DEST/data/" 2>/dev/null || true
  scp -r "$HOST:$REMOTE_DIR/logs/"* "$DEST/logs/" 2>/dev/null || true
}

# Latest bundle if present
rsync -avz "$HOST:$REMOTE_DIR/logs/bundle-latest.tar.gz" "$DEST/logs/" 2>/dev/null || true

echo ""
python3 "$ROOT/scripts/paper-status.py" "$DEST/data"
echo ""
echo "Pulled to $DEST"
echo "  tail -f $DEST/logs/autopilot.log"
echo "  open dashboard: PAPER_PULL_DIR=$DEST streamlit run dashboard.py"
