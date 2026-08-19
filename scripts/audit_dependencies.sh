#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

audit_input="$(mktemp)"
trap 'rm -f "$audit_input"' EXIT

uv export --locked --no-default-groups --no-emit-local -o "$audit_input" >/dev/null
uv run --no-sync pip-audit -r "$audit_input"
