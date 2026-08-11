#!/usr/bin/env bash
# CALLSHIELD installer (Termux / Linux) — Phase 4.
#
# - Verifies Python 3.8+
# - Creates state directories under ~/.callshield (override with CALLSHIELD_HOME)
# - Installs a `callshield` wrapper on PATH
# - Initializes the SQLite database (idempotent; existing data preserved)
# - Runs the unit-test suite as a self-test
#
# Does NOT require root. Does NOT install Android Studio. Does NOT
# transmit any data off-device.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

info()  { printf '\033[1;36m[*]\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m[+]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
err()   { printf '\033[1;31m[-]\033[0m %s\n' "$*" >&2; }

# ---- Python check ----
if ! command -v python3 >/dev/null 2>&1; then
    err "Python 3 not found. On Termux run:  pkg install python"
    exit 1
fi
PYTHON_BIN="$(command -v python3)"
PY_VER="$("${PYTHON_BIN}" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PY_MAJOR="$("${PYTHON_BIN}" -c 'import sys; print(sys.version_info[0])')"
PY_MINOR="$("${PYTHON_BIN}" -c 'import sys; print(sys.version_info[1])')"
if [ "${PY_MAJOR}" -lt 3 ] || { [ "${PY_MAJOR}" -eq 3 ] && [ "${PY_MINOR}" -lt 8 ]; }; then
    err "Python 3.8+ required, found: ${PY_VER}"
    exit 1
fi
info "Python: ${PYTHON_BIN} (${PY_VER})"

# ---- State dirs ----
STATE_DIR="${CALLSHIELD_HOME:-${HOME}/.callshield}"
DATA_DIR="${STATE_DIR}/data"
LOG_DIR="${STATE_DIR}/logs"
RUN_DIR="${STATE_DIR}/run"
STATE_SUBDIR="${STATE_DIR}/state"
mkdir -p "${DATA_DIR}" "${LOG_DIR}" "${RUN_DIR}" "${STATE_SUBDIR}"
chmod 700 "${STATE_DIR}" "${DATA_DIR}" "${LOG_DIR}" "${RUN_DIR}" "${STATE_SUBDIR}" 2>/dev/null || true
ok "State directory: ${STATE_DIR}"

# ---- Bin dir ----
if [ -n "${PREFIX:-}" ] && [ -d "${PREFIX}/bin" ]; then
    BIN_DIR="${PREFIX}/bin"   # Termux convention
elif [ -d "${HOME}/.local/bin" ]; then
    BIN_DIR="${HOME}/.local/bin"
else
    # Prefer ~/.local/bin (created if missing) as it is commonly on PATH on Linux
    if [ -d "${HOME}/.local" ] || mkdir -p "${HOME}/.local/bin" 2>/dev/null; then
        BIN_DIR="${HOME}/.local/bin"
    else
        BIN_DIR="${HOME}/bin"
    fi
fi
mkdir -p "${BIN_DIR}"

# ---- Write wrapper ----
WRAPPER="${BIN_DIR}/callshield"
cat > "${WRAPPER}" <<EOF
#!/usr/bin/env bash
# CALLSHIELD launcher (installed by scripts/install.sh)
export CALLSHIELD_DATA_DIR="${DATA_DIR}"
export CALLSHIELD_LOG_DIR="${LOG_DIR}"
export PYTHONPATH="${PROJECT_ROOT}\${PYTHONPATH:+:\$PYTHONPATH}"
exec "${PYTHON_BIN}" -m callshield "\$@"
EOF
chmod 700 "${WRAPPER}"
ok "Command installed: ${WRAPPER}"

# Also try to ensure a wrapper on a PATH directory for non-Termux desktops
if [ "${BIN_DIR}" != "${HOME}/.local/bin" ] && [ -d "${HOME}/.local/bin" ]; then
    ln -sf "${WRAPPER}" "${HOME}/.local/bin/callshield" 2>/dev/null || true
fi
if ! echo ":${PATH}:" | grep -q ":${BIN_DIR}:"; then
    warn "${BIN_DIR} is not on your PATH. Add this to your shell rc file:"
    warn "    export PATH=\"${BIN_DIR}:\$PATH\""
fi
# Ensure PATH for current session if we just created ~/.local/bin
if [ -d "${HOME}/.local/bin" ] && ! echo ":${PATH}:" | grep -q ":${HOME}/.local/bin:"; then
    export PATH="${HOME}/.local/bin:${PATH}"
    warn "Added ${HOME}/.local/bin to PATH for this session."
fi

# ---- Initialize DB (idempotent) ----
info "Initializing database..."
CALLSHIELD_DATA_DIR="${DATA_DIR}" \
CALLSHIELD_LOG_DIR="${LOG_DIR}" \
PYTHONPATH="${PROJECT_ROOT}" \
"${PYTHON_BIN}" -m callshield status >/dev/null
ok "Database ready: ${DATA_DIR}/callshield.db"

# ---- Self-test ----
info "Running self-test..."
if (cd "${PROJECT_ROOT}" && CALLSHIELD_DATA_DIR="${DATA_DIR}" CALLSHIELD_LOG_DIR="${LOG_DIR}" \
    "${PYTHON_BIN}" -m unittest discover -q) ; then
    ok "All tests pass."
else
    warn "Some tests failed. Check Python version and file permissions."
fi

echo
echo "CALLSHIELD installed."
echo
echo "  callshield --help"
echo "  callshield status"
echo "  callshield scan +919876543210"
echo "  callshield metrics"
echo "  callshield event test +919876543210"
echo "  callshield screening status"
echo
echo "Phase 1 is a local fraud-number analysis and protection foundation. It does not directly intercept or reject live phone calls."
echo "Phase 2 runs locally and offline. It does NOT intercept or reject"
echo "live phone calls."
echo "Phase 4 adds a DRY_RUN Android screening bridge. Recommendations may be BLOCK; every applied action remains ALLOW."
