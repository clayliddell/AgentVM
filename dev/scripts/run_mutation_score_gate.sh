#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN=".venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python"
fi

if ! "$PYTHON_BIN" - <<'PY'
from pathlib import Path
has_src = any(Path("src").rglob("*.py"))
has_tests = Path("tests/unit").exists()
raise SystemExit(0 if has_src and has_tests else 1)
PY
then
  echo "Skipping mutation score gate: source files or unit tests missing"
  exit 0
fi

MUTMUT_BIN=".venv/bin/mutmut"
if [ ! -x "$MUTMUT_BIN" ]; then
  MUTMUT_BIN="mutmut"
fi

"$MUTMUT_BIN" run --paths-to-mutate=src/

STATS="$($MUTMUT_BIN export-cicd-stats)"

"$PYTHON_BIN" - <<'PY' "$STATS"
from __future__ import annotations

import json
import sys

raw = sys.argv[1].strip()
if not raw:
    raise SystemExit("mutmut did not produce CI stats output")

data = json.loads(raw)

score = None
for key in ("mutation_score", "mutationScore", "score", "mutationScorePercent"):
    if key in data:
        score = float(data[key])
        break

if score is None:
    raise SystemExit(f"unable to locate mutation score in stats keys: {sorted(data.keys())}")

if score <= 1.0:
    score *= 100.0

if score < 90.0:
    raise SystemExit(f"mutation score {score:.2f}% is below required 90%")

print(f"mutation score gate passed: {score:.2f}%")
PY
