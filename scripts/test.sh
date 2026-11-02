#!/usr/bin/env bash
# Tiered test runner. Default is the fast suite (excludes @tag("slow")
# benchmark/Playwright tests) with bounded output via --buffer.
#
# Usage:
#   scripts/test.sh                       Fast suite (default; use this)
#   scripts/test.sh <label> [...]         Targeted run, e.g. app.tests.test_query_counts
#                                         (skips @tag("network"); run those with
#                                         --network <label>)
#   scripts/test.sh --full                Full suite incl. slow tests (20+ min,
#                                         needs `playwright install`)
#   scripts/test.sh --slow                Only @tag("slow") tests
#   scripts/test.sh --network             Only @tag("network") tests (needs API
#                                         keys and internet; excluded by default
#                                         because they are slow and flaky)
#   scripts/test.sh --affected            Tests that executed the changed lines,
#                                         from .floppy/affected.coverage when
#                                         that map exists. Otherwise the import
#                                         walk. The fast suite for templates,
#                                         static, the lockfile, settings, and
#                                         the runner.
#   scripts/test.sh --affected --include-slow
#                                         Same selection. A full fallback keeps
#                                         @tag("slow"), matching CI.
#   scripts/test.sh --affected-record     Record the map: the CI suite (slow
#                                         included, network excluded) under
#                                         coverage, written to
#                                         .floppy/affected.coverage.
#
# Extra manage.py test flags (e.g. -v 2, --failfast) pass through after the mode.
set -euo pipefail

cd "$(dirname "$0")/.."

# "config" holds the settings, the startup integrity check and the recovery
# page. Leaving it out let a helper that nothing called, and a report that
# always raised, both ship under a green suite (PR #780).
APPS=(app users integrations lists events api config)
COMMON=(--parallel --buffer)

FLOPPY_TEST_TIMEOUT="${FLOPPY_TEST_TIMEOUT:-2700}"

# Dump every thread's stack shortly before the timeout kills the run, so a
# lost-result hang leaves evidence instead of just a non-zero exit. Only worth
# arming when the timeout leaves room for it.
if [ -z "${FLOPPY_TEST_WATCHDOG:-}" ] && [ "$FLOPPY_TEST_TIMEOUT" != "0" ] \
  && [ "$FLOPPY_TEST_TIMEOUT" -gt 180 ] 2>/dev/null; then
  export FLOPPY_TEST_WATCHDOG=$((FLOPPY_TEST_TIMEOUT - 120))
fi

if [ "$FLOPPY_TEST_TIMEOUT" != "0" ] && command -v timeout >/dev/null 2>&1; then
  # SIGTERM first so the runner can tear its databases down, SIGKILL 30s later
  # if it is wedged hard enough to ignore that.
  RUNNER=(timeout --kill-after=30s "$FLOPPY_TEST_TIMEOUT" uv run --no-sync python)
else
  RUNNER=(uv run --no-sync python)
fi

if [ "${FLOPPY_TEST_FAST_DB:-}" = "1" ]; then
  echo "[test.sh] FLOPPY_TEST_FAST_DB=1: schema built from models, migrations NOT replayed." >&2
fi

case "${1:-}" in
  --full)
    shift
    exec env FLOPPY_TEST_ALLOW_NETWORK=1 \
      "${RUNNER[@]}" src/manage.py test "${APPS[@]}" "${COMMON[@]}" "$@"
    ;;
  --slow)
    shift
    exec "${RUNNER[@]}" src/manage.py test "${APPS[@]}" "${COMMON[@]}" "$@" --tag slow
    ;;
  --network)
    shift
    exec env FLOPPY_TEST_ALLOW_NETWORK=1 \
      "${RUNNER[@]}" src/manage.py test "${APPS[@]}" "${COMMON[@]}" "$@" --tag network
    ;;
  --affected-record)
    shift
    mkdir -p .floppy
    rm -f .coverage .coverage.* .floppy/affected.coverage
    # A failing test still executed lines. Keep the map, then propagate the
    # suite's exit status.
    set +e
    env COVERAGE_CORE=ctrace "${RUNNER[@]}" -m coverage run \
      src/manage.py test "${APPS[@]}" --parallel "$@" --exclude-tag network
    status=$?
    set -e
    uv run --no-sync coverage combine
    cp .coverage .floppy/affected.coverage
    echo "[test.sh] wrote .floppy/affected.coverage" >&2
    exit "$status"
    ;;
  --affected)
    shift
    include_slow=0
    if [ "${1:-}" = "--include-slow" ]; then
      include_slow=1
      shift
    fi
    # Run the file, not `python -m config.affected_tests`. Importing the
    # config package executes config/__init__.py, which boots Celery.
    selection="$(PYTHONPATH=src "${RUNNER[@]}" src/config/affected_tests.py)"
    mode="${selection%%$'\n'*}"
    case "$mode" in
      none)
        exit 0
        ;;
      full)
        if [ "$include_slow" -eq 1 ]; then
          exec "${RUNNER[@]}" src/manage.py test "${APPS[@]}" "${COMMON[@]}" "$@" \
            --exclude-tag network
        fi
        exec "${RUNNER[@]}" src/manage.py test "${APPS[@]}" "${COMMON[@]}" "$@" \
          --exclude-tag slow --exclude-tag network
        ;;
      labels)
        labels=()
        rest="${selection#*$'\n'}"
        if [ "$rest" = "$selection" ]; then
          rest=""
        fi
        while IFS= read -r line; do
          if [ -n "$line" ]; then
            labels+=("$line")
          fi
        done <<EOF
$rest
EOF
        if [ "${#labels[@]}" -eq 0 ]; then
          echo "[test.sh] --affected produced no labels" >&2
          exit 0
        fi
        exec "${RUNNER[@]}" src/manage.py test "${COMMON[@]}" "${labels[@]}" "$@" \
          --exclude-tag network
        ;;
      *)
        echo "[test.sh] --affected: unexpected selector output" >&2
        exit 1
        ;;
    esac
    ;;
  "")
    exec "${RUNNER[@]}" src/manage.py test "${APPS[@]}" "${COMMON[@]}" \
      --exclude-tag slow --exclude-tag network
    ;;
  *)
    # Network tests cannot pass here: the offline guard is installed unless
    # FLOPPY_TEST_ALLOW_NETWORK is set, so a targeted run of a module holding
    # them failed for reasons unrelated to the change. Use --network <label>.
    exec "${RUNNER[@]}" src/manage.py test "${COMMON[@]}" "$@" --exclude-tag network
    ;;
esac
