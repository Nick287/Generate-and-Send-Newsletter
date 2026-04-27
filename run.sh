#!/usr/bin/env bash
# Wrapper for the enhanced v5 newsletter pipeline.
# Loads optional .env, then runs generate.py with any args passed through.
# Usage: ./run.sh [--dry-run] [--fetch-only] [--compose-only] [--legacy] [--to addr]
#   --legacy   Force legacy single-model mode (ignores APIM dual-model config)
set -euo pipefail
cd "$(dirname "$0")"

if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

# Optional venv
if [[ -d .venv ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

exec python3 generate.py "$@"
