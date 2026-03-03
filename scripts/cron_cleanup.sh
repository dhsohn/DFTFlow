#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCK_FILE="$ROOT/.cron_cleanup.lock"
LOG_DIR="$ROOT/logs"
LOG_FILE="$LOG_DIR/cron_cleanup_$(date +%Y%m%d_%H%M%S).log"
CONFIG_PATH="${PYSCF_AUTO_CONFIG:-$ROOT/config/pyscf_auto.yaml}"

[[ -f "$HOME/.pyscf_auto_env" ]] && source "$HOME/.pyscf_auto_env"

exec 200>"$LOCK_FILE"
flock -n 200 || { echo "[cron_cleanup] Already running, exiting." >&2; exit 0; }

mkdir -p "$LOG_DIR"

echo "[cron_cleanup] Started at $(date -Iseconds)" | tee -a "$LOG_FILE"
echo "[cron_cleanup] config=$CONFIG_PATH" | tee -a "$LOG_FILE"

"$ROOT/bin/pyscf_auto" --config "$CONFIG_PATH" cleanup --apply --json \
  2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}
echo "[cron_cleanup] Finished at $(date -Iseconds) with exit code $EXIT_CODE" | tee -a "$LOG_FILE"
exit "$EXIT_CODE"
