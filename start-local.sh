#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND="${SHORTFORGE_FRONTEND_DIR:-$ROOT/../ShortClips_Cloud}"
[[ -f "$FRONTEND/local_dev.py" ]] || { echo 'Defina SHORTFORGE_FRONTEND_DIR para o checkout local de ShortClips.' >&2; exit 1; }
exec "$FRONTEND/start-local.sh" "$@"
