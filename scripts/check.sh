#!/usr/bin/env bash
# One-command local quality gate: locked dependencies, the Django fast suite,
# the MCP server suite (including dispatcher-level tool calls), and Ruff for
# both source roots. Every gate runs; the exit code is non-zero if any failed.
#
# Usage:
#   scripts/check.sh                     Full gate (sync + Django + MCP + ruff)
#   scripts/check.sh <label> [...]       Django targeted tests instead of the
#                                        fast suite (same labels as test.sh)
#   CHECK_SKIP_SYNC=1 scripts/check.sh   Assume .venv is already synced
#   CHECK_SKIP_DJANGO=1 scripts/check.sh Only MCP + ruff
#
# The gate commands are overridable (UV/PYTHON/RUFF/TEST_SH) so the failure
# paths can be tested without touching the real toolchain. Output ends with
# one summary line and a final PASS/FAIL line.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

started=$(date +%s)
declare -a gate_names=()
declare -a gate_codes=()

UV_BIN="${UV:-uv}"
PYTHON_BIN="${PYTHON:-.venv/bin/python}"
RUFF_BIN="${RUFF:-.venv/bin/ruff}"
TEST_SH="${TEST_SH:-scripts/test.sh}"

note() { printf '[check.sh] %s\n' "$*" >&2; }
log_dir="$(mktemp -d "${TMPDIR:-/tmp}/floppy-check.XXXXXX")" || exit 1
note "logs: $log_dir"

run_gate() {
  local name="$1"
  shift
  gate_names+=("$name")
  note "── $name: $*"
  "$@" >"$log_dir/$name.log" 2>&1
  local code=$?
  gate_codes+=("$code")
  if [ "$code" -ne 0 ]; then
    note "$name FAILED (exit $code); last output:"
    tail -c 4000 "$log_dir/$name.log" | sed 's/^/    /' >&2
  fi
  return 0
}

if [ "${CHECK_SKIP_SYNC:-0}" != "1" ]; then
  run_gate sync "$UV_BIN" sync --locked --all-packages --all-extras
fi

if [ "${CHECK_SKIP_DJANGO:-0}" != "1" ]; then
  if [ "$#" -gt 0 ]; then
    run_gate django bash "$TEST_SH" "$@"
  else
    run_gate django bash "$TEST_SH"
  fi
fi

run_gate mcp "$PYTHON_BIN" -m pytest -c mcp_server/pyproject.toml mcp_server/tests -q
run_gate ruff "$RUFF_BIN" check src mcp_server

failed=0
summary=""
for index in "${!gate_names[@]}"; do
  name="${gate_names[$index]}"
  code="${gate_codes[$index]}"
  if [ "$code" -ne 0 ]; then
    summary+="${name}=FAIL(${code}) "
    failed=1
  else
    summary+="${name}=ok "
  fi
done

elapsed=$(( $(date +%s) - started ))
mode="fast-db(schema-from-models)"
if [ "${FLOPPY_TEST_FAST_DB:-}" != "1" ]; then
  mode="migrations-replayed"
fi
network_mode="network-excluded"
case "${1:-}" in
  --network|--full) network_mode="network-enabled" ;;
esac
if [ "${CHECK_SKIP_DJANGO:-0}" = "1" ]; then
  mode="skipped"
  network_mode="not-run"
fi
note "summary: ${summary% } | django-mode=${mode} | django-workers=${FLOPPY_TEST_PARALLEL:-1} | ${network_mode} | ${elapsed}s"
if [ "$failed" -ne 0 ]; then
  note "RESULT: FAIL"
  exit 1
fi
note "RESULT: PASS"
