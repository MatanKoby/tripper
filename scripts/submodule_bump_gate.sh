#!/usr/bin/env bash
# Submodule-bump verification gate (spec/agents.md -> "Submodule-bump gate").
#
# Tripper may advance a vendored agent's submodule pointer, but before that bump is
# trusted it must pass three checks:
#   1. compile-check the submodule            (python -m compileall)
#   2. the submodule's own non-e2e tests      (no live LLM round-trip)
#   3. tripper's adapter/contract tests for that agent
# On any failure the pointer is rolled back to the previously recorded commit and
# nothing is committed. On green the bump is committed on its own.
#
# Two modes:
#   (local, default)  Validate the currently checked-out submodule commit; on pass,
#                     stage + commit the pointer on its own; on fail, roll it back.
#   --check-only      Validate only. No git mutation either way. Used by CI, which
#                     runs against a pointer change that is already committed/pushed,
#                     so there is nothing to roll back or commit; the job just goes
#                     red when the checks fail.
#
# Usage:
#   scripts/submodule_bump_gate.sh [--check-only] [<submodule-path>]
#
# Env overrides:
#   PYTHON                 Python interpreter (default: ./.venv/bin/python if present, else python3).
#   SUBMODULE_TEST_CMD     Command run inside the submodule for check 2
#                          (default: "<python> -m pytest -m 'not e2e' -q").
#   TRIPPER_TEST_ARGS      Args for check 3's pytest from the repo root
#                          (default: -k "adapter or contract").
#   BUMP_COMMIT_PREFIX     Commit-message prefix for the bump commit (default: "meta").
set -uo pipefail

DEFAULT_SUB="vendor/agents/hotel-finder-agent"

CHECK_ONLY=0
SUB=""
while [ $# -gt 0 ]; do
  case "$1" in
    --check-only) CHECK_ONLY=1 ;;
    -h | --help)
      sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    -*)
      echo "gate: unknown option: $1" >&2
      exit 2
      ;;
    *) SUB="$1" ;;
  esac
  shift
done

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SUB="${SUB:-$DEFAULT_SUB}"
SUB="${SUB%/}"
case "$SUB" in
  /*) SUB_ABS="$SUB" ;;
  *) SUB_ABS="$ROOT/$SUB" ;;
esac

# Pick an interpreter: caller override, else the repo venv, else python3.
if [ -z "${PYTHON:-}" ]; then
  if [ -x "$ROOT/.venv/bin/python" ]; then
    PYTHON="$ROOT/.venv/bin/python"
  else
    PYTHON="python3"
  fi
fi

say() { printf '%s\n' "$*"; }
hr() { printf '%s\n' "----------------------------------------------------------------------"; }

# --- Preflight ------------------------------------------------------------------
if [ ! -d "$SUB_ABS" ] || [ -z "$(ls -A "$SUB_ABS" 2>/dev/null)" ]; then
  if [ "$CHECK_ONLY" -eq 1 ]; then
    say "gate: submodule '$SUB' is absent or not checked out; nothing to gate. Skipping."
    exit 0
  fi
  say "gate: submodule '$SUB' is absent or not checked out." >&2
  say "      Run: git submodule update --init -- '$SUB'" >&2
  exit 2
fi

# Record the pointer we would roll back to (only meaningful for the local flow).
BEFORE=""
CURRENT=""
if [ "$CHECK_ONLY" -eq 0 ]; then
  BEFORE="$(git -C "$ROOT" rev-parse "HEAD:$SUB" 2>/dev/null || true)"
  CURRENT="$(git -C "$SUB_ABS" rev-parse HEAD 2>/dev/null || true)"
fi

# --- Checks ---------------------------------------------------------------------
# Each check prints a header, runs, and appends PASS/FAIL to RESULTS.
FAILED=0
RESULTS=""

record() { # $1: name  $2: rc-based verdict string
  RESULTS="${RESULTS}${1}: ${2}"$'\n'
}

hr
say "Submodule bump gate"
say "  submodule : $SUB"
say "  python    : $PYTHON"
say "  mode      : $([ "$CHECK_ONLY" -eq 1 ] && echo check-only || echo "validate + commit")"
[ -n "$CURRENT" ] && say "  at commit : $CURRENT"
hr

# 1. Compile-check the submodule.
say ">> [1/3] compile-check (python -m compileall)"
if "$PYTHON" -m compileall -q "$SUB_ABS"; then
  record "compile-check" "PASS"
else
  record "compile-check" "FAIL"
  FAILED=1
fi

# 2. The submodule's own non-e2e tests.
say ">> [2/3] submodule non-e2e tests"
sub_rc=0
if [ -n "${SUBMODULE_TEST_CMD:-}" ]; then
  ( cd "$SUB_ABS" && eval "$SUBMODULE_TEST_CMD" ) || sub_rc=$?
else
  ( cd "$SUB_ABS" && "$PYTHON" -m pytest -m "not e2e" -q ) || sub_rc=$?
fi
if [ "$sub_rc" -eq 0 ]; then
  record "submodule-tests" "PASS"
elif [ "$sub_rc" -eq 5 ]; then
  record "submodule-tests" "PASS (no tests collected)"
else
  record "submodule-tests" "FAIL (rc=$sub_rc)"
  FAILED=1
fi

# 3. Tripper's adapter/contract tests for the agent.
say ">> [3/3] tripper adapter/contract tests"
trip_rc=0
if [ -n "${TRIPPER_TEST_ARGS:-}" ]; then
  ( cd "$ROOT" && eval "\"\$PYTHON\" -m pytest $TRIPPER_TEST_ARGS -q" ) || trip_rc=$?
else
  ( cd "$ROOT" && "$PYTHON" -m pytest -k "adapter or contract" -q ) || trip_rc=$?
fi
if [ "$trip_rc" -eq 0 ]; then
  record "tripper-tests" "PASS"
elif [ "$trip_rc" -eq 5 ]; then
  record "tripper-tests" "PASS (no tests matched)"
else
  record "tripper-tests" "FAIL (rc=$trip_rc)"
  FAILED=1
fi

hr
say "Results:"
printf '%s' "$RESULTS" | sed 's/^/  /'
hr

# --- Outcome --------------------------------------------------------------------
if [ "$FAILED" -ne 0 ]; then
  say "GATE FAILED."
  if [ "$CHECK_ONLY" -eq 1 ]; then
    exit 1
  fi
  # Local flow: roll the pointer back and commit nothing.
  say "Rolling the submodule pointer back to the recorded commit..."
  git -C "$ROOT" restore --staged -- "$SUB" 2>/dev/null || git -C "$ROOT" reset -q HEAD -- "$SUB" 2>/dev/null || true
  if git -C "$ROOT" submodule update --init --checkout -- "$SUB" 2>/dev/null; then
    NOW="$(git -C "$SUB_ABS" rev-parse HEAD 2>/dev/null || true)"
    if [ -n "$BEFORE" ] && [ "$NOW" = "$BEFORE" ]; then
      say "Rolled back to $BEFORE."
    else
      say "WARNING: submodule is at ${NOW:-unknown}; expected ${BEFORE:-unknown}. Check manually." >&2
    fi
  else
    say "WARNING: could not auto-roll-back the submodule; check 'git status' manually." >&2
  fi
  exit 1
fi

say "GATE PASSED."
if [ "$CHECK_ONLY" -eq 1 ]; then
  exit 0
fi

# Local flow: commit the validated bump on its own.
git -C "$ROOT" add -- "$SUB"
if git -C "$ROOT" diff --cached --quiet -- "$SUB"; then
  say "Submodule pointer unchanged; nothing to commit."
  exit 0
fi
SHORT="$(git -C "$SUB_ABS" rev-parse --short HEAD 2>/dev/null || echo "$CURRENT")"
PREFIX="${BUMP_COMMIT_PREFIX:-meta}"
MSG="${PREFIX}: bump ${SUB} to ${SHORT}"
git -C "$ROOT" commit -q -m "$MSG" -- "$SUB"
say "Committed: $MSG"
exit 0
