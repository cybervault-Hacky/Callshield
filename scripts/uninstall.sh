#!/usr/bin/env bash
# CALLSHIELD uninstaller — Phase 7.
#
# By default this removes the wrapper command and stops the daemon, but keeps
# the user database/logs. Pass --purge to remove all state as well.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

info()  { printf '\033[1;36m[*]\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m[+]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }

PURGE=0
for arg in "$@"; do
    case "${arg}" in
        --purge|-f|--force) PURGE=1 ;;
        -h|--help)
            echo "Usage: scripts/uninstall.sh [--purge]"
            echo "  --purge   also remove database, logs, configuration"
            exit 0
            ;;
    esac
done

PYTHON_BIN="$(command -v python3 || true)"
STATE_DIR="${CALLSHIELD_HOME:-${HOME}/.callshield}"
DATA_DIR="${STATE_DIR}/data"
LOG_DIR="${STATE_DIR}/logs"

# ---- Stop running daemon if possible ----
if [ -n "${PYTHON_BIN}" ] && [ -d "${PROJECT_ROOT}" ]; then
    if CALLSHIELD_DATA_DIR="${DATA_DIR}" CALLSHIELD_LOG_DIR="${LOG_DIR}" \
        PYTHONPATH="${PROJECT_ROOT}" "${PYTHON_BIN}" -m callshield stop >/dev/null 2>&1; then
        ok "Stopped running CALLSHIELD engine."
    fi
fi

# ---- Remove wrapper ----
if [ -n "${PREFIX:-}" ] && [ -f "${PREFIX}/bin/callshield" ]; then
    rm -f "${PREFIX}/bin/callshield" && ok "Removed ${PREFIX}/bin/callshield"
fi
rm -f "${HOME}/.local/bin/callshield" "${HOME}/bin/callshield" 2>/dev/null || true

if [ "${PURGE}" -eq 1 ]; then
    warn "Purging all user data in ${STATE_DIR}"
    rm -rf "${STATE_DIR}"
    ok "Removed ${STATE_DIR}"
else
    echo
    echo "User data preserved in ${STATE_DIR}."
    echo "Run with --purge to remove the database, logs, and configuration:"
    echo "    bash scripts/uninstall.sh --purge"
fi

ok "CALLSHIELD uninstalled."
