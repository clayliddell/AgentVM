#!/usr/bin/env bash
set -euo pipefail

PIP_AUDIT_BIN=".venv/bin/pip-audit"
if [ ! -x "$PIP_AUDIT_BIN" ]; then
  PIP_AUDIT_BIN="pip-audit"
fi

if [ -f "requirements-dev.txt" ]; then
  "$PIP_AUDIT_BIN" -r requirements-dev.txt
  exit 0
fi

if [ -f "requirements.txt" ]; then
  "$PIP_AUDIT_BIN" -r requirements.txt
  exit 0
fi

echo "Skipping pip-audit gate: no requirements file found"
