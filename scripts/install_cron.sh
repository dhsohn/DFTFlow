#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MARKER_START="# PYSCF_AUTO_CRON_START"
MARKER_END="# PYSCF_AUTO_CRON_END"

BLOCK="${MARKER_START}
0 0 * * 6 ${ROOT}/scripts/cron_organize.sh
0 0 * * 0 ${ROOT}/scripts/cron_cleanup.sh
${MARKER_END}"

chmod +x "$ROOT/scripts/cron_organize.sh" "$ROOT/scripts/cron_cleanup.sh"

EXISTING="$(crontab -l 2>/dev/null || true)"
CLEANED="$(echo "$EXISTING" | sed "/${MARKER_START}/,/${MARKER_END}/d")"

printf '%s\n%s\n' "$CLEANED" "$BLOCK" | crontab -

echo "[install_cron] Cron entries installed:"
echo "  organize: Saturday midnight (0 0 * * 6)"
echo "  cleanup:  Sunday midnight (0 0 * * 0)"
echo
echo "Current crontab:"
crontab -l
echo
echo "Telegram notifications (optional):"
echo "  create ~/.pyscf_auto_env with:"
echo "    export PYSCF_AUTO_TELEGRAM_BOT_TOKEN='...'"
echo "    export PYSCF_AUTO_TELEGRAM_CHAT_ID='...'"
