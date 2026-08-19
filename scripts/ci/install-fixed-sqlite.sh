#!/usr/bin/env bash
# Install the SQLite library used by CPython in controlled Linux CI.
set -euo pipefail

SQLITE_VERSION="3.53.4"
SQLITE_ARCHIVE_VERSION="3530400"
SQLITE_SHA3_256="454e45f61c6bd75b7420e7190732dea03ce6639c63ada47bbc592f67fc340338"
SQLITE_URL="https://sqlite.org/2026/sqlite-autoconf-${SQLITE_ARCHIVE_VERSION}.tar.gz"

work_root="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/floppy-sqlite-${SQLITE_VERSION}"
archive="${work_root}/sqlite.tar.gz"
source_dir="${work_root}/src"
prefix="${work_root}/install"

mkdir -p "${work_root}"

if [[ ! -f "${archive}" ]]; then
  SQLITE_URL="${SQLITE_URL}" ARCHIVE="${archive}" python - <<'PY'
import os
import urllib.request

request = urllib.request.Request(
    os.environ["SQLITE_URL"],
    headers={"User-Agent": "Floppy CI SQLite installer"},
)
with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed HTTPS origin plus digest verification below
    payload = response.read()
with open(os.environ["ARCHIVE"], "wb") as archive:
    archive.write(payload)
PY
fi

SQLITE_ARCHIVE="${archive}" SQLITE_SHA3_256="${SQLITE_SHA3_256}" python - <<'PY'
import hashlib
import os
from pathlib import Path

archive = Path(os.environ["SQLITE_ARCHIVE"])
actual = hashlib.sha3_256(archive.read_bytes()).hexdigest()
expected = os.environ["SQLITE_SHA3_256"]
if actual != expected:
    raise SystemExit(
        f"SQLite source digest mismatch: expected {expected}, got {actual}"
    )
PY

rm -rf "${source_dir}" "${prefix}"
mkdir -p "${source_dir}" "${prefix}"
tar -xzf "${archive}" --strip-components=1 -C "${source_dir}"

(
  cd "${source_dir}"
  ./configure --prefix="${prefix}" --disable-static --enable-shared >/dev/null
  make -j"$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)" >/dev/null
  make install >/dev/null
)

export LD_LIBRARY_PATH="${prefix}/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
export PATH="${prefix}/bin:${PATH}"

if [[ -n "${GITHUB_ENV:-}" ]]; then
  printf 'LD_LIBRARY_PATH=%s\n' "${LD_LIBRARY_PATH}" >>"${GITHUB_ENV}"
fi
if [[ -n "${GITHUB_PATH:-}" ]]; then
  printf '%s\n' "${prefix}/bin" >>"${GITHUB_PATH}"
fi

python - <<'PY'
import sqlite3

minimum = (3, 51, 3)
if sqlite3.sqlite_version_info < minimum:
    raise SystemExit(
        "CI Python is still linked to unsafe SQLite "
        f"{sqlite3.sqlite_version}; expected >= {'.'.join(map(str, minimum))}"
    )
print(f"CI Python SQLite: {sqlite3.sqlite_version}")
PY
