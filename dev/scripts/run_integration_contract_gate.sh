#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN=".venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python"
fi

if [ ! -d "tests/integration" ]; then
  echo "Skipping integration contract gate: tests/integration not found"
  exit 0
fi

if ! "$PYTHON_BIN" - <<'PY'
from pathlib import Path
has_tests = any(Path("tests/integration").rglob("test_*.py"))
raise SystemExit(0 if has_tests else 1)
PY
then
  echo "Skipping integration contract gate: no integration tests found"
  exit 0
fi

"$PYTHON_BIN" -m pytest tests/integration -m integration -k contract
