#!/usr/bin/env bash
# AI Engineering Nest — deterministic, configurable verification gate.
# Usage: bash scripts/verify.sh [--suite SUITE | --list]
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo 'ERROR: Python 3.11+ is required to run AI Nest verification.' >&2
  exit 2
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/verify.py" "$@"
