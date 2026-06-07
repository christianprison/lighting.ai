#!/usr/bin/env bash
# Test harness for lighting.ai — runs the JS and Python characterization suites.
# Safe to run anywhere: suites whose deps are missing skip cleanly (non-fatal).
#
#   tests/run.sh            # run everything available
#
# Exit code is non-zero only if an AVAILABLE test actually fails.
set -u
cd "$(dirname "$0")/.."

fail=0

echo "── JS: integrity (node --test) ───────────────────────────"
if command -v node >/dev/null 2>&1; then
  node --test tests/js/*.test.mjs || fail=1
else
  echo "  SKIP: node not found"
fi

echo
echo "── Python: schema + reference.db + live API ──────────────"
PY=${PYTHON:-python3}
if command -v "$PY" >/dev/null 2>&1; then
  if "$PY" -c "import pytest" >/dev/null 2>&1; then
    "$PY" -m pytest -q tests/python || fail=1
  else
    echo "  pytest not installed — falling back to unittest"
    "$PY" -m unittest discover -s tests/python -p 'test_*.py' -v || fail=1
  fi
else
  echo "  SKIP: $PY not found"
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "✅ all available suites passed"
else
  echo "❌ some suites failed"
fi
exit $fail
