#!/usr/bin/env bash
# The CodeSentinel verification gate, in the order CI runs it.
#
# Exists because the gate is easy to run incompletely (forgetting ../sandbox/, or
# ruff format --check) and even easier to read optimistically: pytest prints
# "N passed, M skipped" and the eye stops at "passed". This runs the whole thing and
# then says plainly what was and was not verified.
#
# Usage, from anywhere in the repo:
#   bash .claude/skills/codesentinel-development/scripts/gate.sh          # full gate
#   bash .../gate.sh --fast          # lint + types + unit tests only, no integration
#   bash .../gate.sh --require       # CODESENTINEL_REQUIRE_INTEGRATION=1: skips become failures
#
# Exit status is non-zero if any step fails. Skipped integration tests do NOT fail the
# run (that is the point of --require) but they are reported loudly.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
BACKEND="$REPO_ROOT/backend"

FAST=0
for arg in "$@"; do
  case "$arg" in
    --fast)    FAST=1 ;;
    --require) export CODESENTINEL_REQUIRE_INTEGRATION=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

# Prefer the project venv's interpreter; the layout differs by platform.
if   [ -x "$BACKEND/.venv/Scripts/python.exe" ]; then PY="$BACKEND/.venv/Scripts/python.exe"
elif [ -x "$BACKEND/.venv/bin/python" ];        then PY="$BACKEND/.venv/bin/python"
else PY="python"; echo "note: no .venv found, using '$PY' from PATH" >&2
fi

cd "$BACKEND" || { echo "cannot find backend/ under $REPO_ROOT" >&2; exit 2; }

FAILED=()
step() {
  local label="$1"; shift
  echo ""
  echo "── $label ──────────────────────────────────────────"
  if "$@"; then
    echo "   ok"
  else
    echo "   FAILED"
    FAILED+=("$label")
  fi
}

step "ruff check backend"          "$PY" -m ruff check .
step "ruff format --check backend" "$PY" -m ruff format --check .
step "mypy app/"                   "$PY" -m mypy app/
# CI lints sandbox/ too: it is our code even though it lives outside the package.
step "ruff check sandbox"          "$PY" -m ruff check ../sandbox/
step "ruff format --check sandbox" "$PY" -m ruff format --check ../sandbox/

echo ""
echo "── pytest ──────────────────────────────────────────"
PYTEST_ARGS=(-rs)
[ "$FAST" -eq 1 ] && PYTEST_ARGS+=(tests/unit)
PYTEST_OUT="$("$PY" -m pytest "${PYTEST_ARGS[@]}" 2>&1)"
PYTEST_STATUS=$?
echo "$PYTEST_OUT"
[ $PYTEST_STATUS -ne 0 ] && FAILED+=("pytest")

SUMMARY="$(printf '%s\n' "$PYTEST_OUT" | grep -E '^=+ .*(passed|failed|error)' | tail -1)"
SKIPPED="$(printf '%s\n' "$PYTEST_OUT" | grep -cE '^SKIPPED')"

echo ""
echo "════════════════════════════════════════════════════"
echo " GATE RESULT"
echo "════════════════════════════════════════════════════"
[ -n "$SUMMARY" ] && echo " pytest: $SUMMARY"

if [ "${SKIPPED:-0}" -gt 0 ]; then
  echo ""
  echo " ⚠  $SKIPPED test(s) SKIPPED — those behaviours were NOT verified."
  echo "    Report them as unverified rather than as passing. Reasons:"
  printf '%s\n' "$PYTEST_OUT" | grep -E '^SKIPPED' | sed 's/^/      /'
  echo ""
  echo "    Locally this is expected when Docker or PostgreSQL is absent; CI is the"
  echo "    acceptance authority for anything they cover. To make skips fail here,"
  echo "    re-run with --require."
fi

if [ ${#FAILED[@]} -gt 0 ]; then
  echo ""
  echo " ✗ FAILED: ${FAILED[*]}"
  exit 1
fi

echo ""
if [ "${SKIPPED:-0}" -gt 0 ]; then
  echo " ✓ every step passed, but the run is INCOMPLETE — see the skips above."
elif [ "$FAST" -eq 1 ]; then
  echo " ✓ fast gate passed (unit tests only — integration not run)."
else
  echo " ✓ full gate passed with nothing skipped."
fi
