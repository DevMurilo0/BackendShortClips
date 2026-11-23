#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${SHORTFORGE_FRONTEND_DIR:-$ROOT/../ShortClips_Cloud}/stop-local.sh" "$@"
