#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN=".venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python"
fi

if [ ! -f ".secrets.baseline" ]; then
  echo "Skipping secrets baseline gate: .secrets.baseline not found"
  exit 0
fi

"$PYTHON_BIN" - <<'PY'
from __future__ import annotations

import json
from pathlib import Path

baseline_path = Path(".secrets.baseline")
data = json.loads(baseline_path.read_text(encoding="utf-8"))
results = data.get("results", {})

entries: list[tuple[str, int, bool]] = []
for filename, findings in results.items():
    for finding in findings:
        line_number = int(finding.get("line_number", 0))
        is_verified = bool(finding.get("is_verified", False))
        entries.append((filename, line_number, is_verified))

if not entries:
    print("secrets baseline gate passed: baseline has no findings")
    raise SystemExit(0)

detail = "\n".join(
    f"- {filename}:{line_number} (verified={is_verified})"
    for filename, line_number, is_verified in entries
)
raise SystemExit(
    "secrets baseline gate failed: baseline contains findings. "
    "Resolve or audit and remove false positives before commit:\n"
    f"{detail}"
)
PY
