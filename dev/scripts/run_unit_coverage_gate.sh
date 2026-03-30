#!/usr/bin/env bash
set -euo pipefail

if [ ! -d "tests/unit" ]; then
  echo "Skipping unit coverage gate: tests/unit not found"
  exit 0
fi

if ! python - <<'PY'
from pathlib import Path
raise SystemExit(0 if any(Path("src").rglob("*.py")) else 1)
PY
then
  echo "Skipping unit coverage gate: no Python files under src/"
  exit 0
fi

PYTHON_BIN=".venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python"
fi

"$PYTHON_BIN" -m pytest tests/unit --cov=src --cov-report=term-missing --cov-fail-under=95
