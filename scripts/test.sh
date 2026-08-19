#!/usr/bin/env bash
# Tiered test runner. Default is the fast suite (excludes @tag("slow")
# benchmark/Playwright tests) with bounded output via --buffer.
#
# Usage:
#   scripts/test.sh                       Fast suite (default; use this)
#   scripts/test.sh <label> [...]         Targeted run, e.g. app.tests.test_query_counts
#   scripts/test.sh --full                Full suite incl. slow tests (20+ min,
#                                         needs `playwright install`)
#   scripts/test.sh --slow                Only @tag("slow") tests
#   scripts/test.sh --network             Only @tag("network") tests (needs API
#                                         keys and internet; excluded by default
#                                         because they are slow and flaky)
#
# Extra manage.py test flags (e.g. -v 2, --failfast) pass through after the mode.
set -euo pipefail

cd "$(dirname "$0")/.."

# "config" holds the settings, the startup integrity check and the recovery
# page. Leaving it out let a helper that nothing called, and a report that
# always raised, both ship under a green suite (PR #780).
APPS=(app users integrations lists events api config)
COMMON=(--parallel --buffer)

case "${1:-}" in
  --full)
    shift
    exec env FLOPPY_TEST_ALLOW_NETWORK=1 \
      uv run --no-sync python src/manage.py test "${APPS[@]}" "${COMMON[@]}" "$@"
    ;;
  --slow)
    shift
    exec uv run --no-sync python src/manage.py test "${APPS[@]}" "${COMMON[@]}" "$@" --tag slow
    ;;
  --network)
    shift
    exec env FLOPPY_TEST_ALLOW_NETWORK=1 \
      uv run --no-sync python src/manage.py test "${APPS[@]}" "${COMMON[@]}" "$@" --tag network
    ;;
  "")
    exec uv run --no-sync python src/manage.py test "${APPS[@]}" "${COMMON[@]}" \
      --exclude-tag slow --exclude-tag network
    ;;
  *)
    exec uv run --no-sync python src/manage.py test "${COMMON[@]}" "$@"
    ;;
esac
