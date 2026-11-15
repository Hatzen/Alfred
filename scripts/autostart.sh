#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
exec python3 -m src.main --host "${ALFRED_HOST:-0.0.0.0}" --port "${ALFRED_PORT:-8020}" --lang "${ALFRED_DEFAULT_LANGUAGE:-de}"

