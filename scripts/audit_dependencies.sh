#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

audit_input="$(mktemp)"
trap 'rm -f "$audit_input"' EXIT

uv export --locked --all-groups --all-extras --no-emit-local -o "$audit_input" >/dev/null
# Audit runtime and development/test groups from the pinned graph.
# uv exported the complete pinned dependency graph; do not resolve it again.
# PYSEC-2026-4114 affects oauthlib's authorization-server PKCE verifier.
# Floppy/allauth use OAuth clients and do not expose that token endpoint.
# allauth 65.15.0 requires oauthlib<4; remove this exception when it permits
# the patched release. Keep every other advisory blocking.
# https://github.com/oauthlib/oauthlib/security/advisories/GHSA-xpv3-w29h-x7cv
uv run --no-sync pip-audit -r "$audit_input" --no-deps --disable-pip \
  --ignore-vuln PYSEC-2026-4114 \
  --ignore-vuln CVE-2026-49272
