#!/usr/bin/env bash
# Convenience wrapper. The installer lives in scripts/install.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${ROOT}/scripts/install.sh" "$@"
