#!/usr/bin/env bash
set -euo pipefail

PIP_AUDIT_BIN=".venv/bin/pip-audit"
if [ ! -x "$PIP_AUDIT_BIN" ]; then
  PIP_AUDIT_BIN="pip-audit"
fi

ran_audit=0

if [ -f "requirements-dev.txt" ]; then
  "$PIP_AUDIT_BIN" -r requirements-dev.txt
  ran_audit=1
fi

if [ -f "requirements.txt" ]; then
  "$PIP_AUDIT_BIN" -r requirements.txt
  ran_audit=1
fi

if [ "$ran_audit" -eq 0 ]; then
  echo "Skipping pip-audit gate: no requirements file found"
fi
