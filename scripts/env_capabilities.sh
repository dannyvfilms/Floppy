#!/usr/bin/env bash
# Report what this machine can run for UI verification, and optionally make a
# fresh (cloud) checkout match a local one. Nothing here installs system
# packages, boots devices or spends money.
#
#   scripts/env_capabilities.sh              Discover and print capabilities
#   scripts/env_capabilities.sh --bootstrap  Also install locked JS/Python deps
#   scripts/env_capabilities.sh --refresh    Ignore the cached report
#
# The report is cached in .floppy/env-capabilities.txt so a session discovers
# once. Delete it (or pass --refresh) when the environment changes.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

bootstrap=0
refresh=0
for arg in "$@"; do
  case "$arg" in
    --bootstrap) bootstrap=1 ;;
    --refresh) refresh=1 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

cache=.floppy/env-capabilities.txt
mkdir -p .floppy

if [ "$bootstrap" = 1 ]; then
  echo "[bootstrap] python deps"
  command -v uv >/dev/null && uv sync --locked --all-packages --all-extras
  echo "[bootstrap] web deps (root)"
  [ -f package-lock.json ] && npm ci --no-audit --no-fund
  echo "[bootstrap] Expo deps (native-proof)"
  [ -f native-proof/package-lock.json ] && npm ci --prefix native-proof --no-audit --no-fund
  refresh=1
fi

if [ -f "$cache" ] && [ "$refresh" = 0 ]; then
  cat "$cache"
  exit 0
fi

have() { command -v "$1" >/dev/null 2>&1; }
line() { printf '%-22s %s\n' "$1" "$2"; }

{
  echo "== Floppy environment capabilities ($(date -u +%Y-%m-%dT%H:%MZ)) =="

  kind=cloud
  if [ "$(uname -s)" = Darwin ] && [ -z "${CLAUDE_CODE_REMOTE:-}" ]; then kind=local-mac; fi
  line environment "$kind ($(uname -s) $(uname -m))"

  # Toolchain
  for t in uv node npm redis-server gh; do
    if have "$t"; then line "$t" "yes"; else line "$t" "MISSING"; fi
  done
  [ -d .venv ] && line python-venv "present" || line python-venv "missing (run --bootstrap)"
  [ -d node_modules ] && line web-node_modules "present" || line web-node_modules "missing (run --bootstrap)"
  [ -d native-proof/node_modules ] && line expo-node_modules "present" || line expo-node_modules "missing (run --bootstrap)"

  # Browser evidence (Expo Web and web screenshots)
  chromium=none
  [ -x /opt/pw-browsers/chromium ] && chromium=/opt/pw-browsers/chromium
  for d in "$HOME"/Library/Caches/ms-playwright/chromium* "$HOME"/.cache/ms-playwright/chromium*; do [ -d "$d" ] && chromium=playwright-cache; done
  line playwright-chromium "$chromium"

  # iOS: level 1 evidence needs a booted simulator
  if have xcodebuild && have xcrun; then
    line xcode "$(xcodebuild -version 2>/dev/null | head -1)"
    booted=$(xcrun simctl list devices booted 2>/dev/null | grep -c Booted)
    avail=$(xcrun simctl list devices available 2>/dev/null | grep -c -E '\(Shutdown\)|\(Booted\)')
    line ios-simulators "$avail available, $booted booted"
  else
    line ios-simulators "none (no Xcode)"
  fi

  # Android: level 1 evidence needs a running emulator
  if have adb; then
    line android-devices "$(adb devices -l 2>/dev/null | tail -n +2 | grep -c .) attached/running"
  else
    line android-devices "none (no adb)"
  fi
  if have emulator; then
    line android-avds "$(emulator -list-avds 2>/dev/null | grep -c .) defined"
  else
    line android-avds "none (no emulator)"
  fi

  # Hosted / scripted native runtimes (never started or billed from here)
  for t in maestro eas; do
    if have "$t"; then line "$t" "installed"; else line "$t" "not installed"; fi
  done
  if [ -n "${EXPO_TOKEN:-}" ]; then line expo-token "set (hosted runtimes may be reachable; confirm cost first)"; else line expo-token "not set"; fi

  echo
  echo "Best evidence available:"
  if [ "$kind" = local-mac ] && have xcodebuild; then
    echo "  iOS: start a simulator (or Expo Device Hub) and run the real app -> level 1"
  else
    echo "  iOS: no simulator here -> level 2 (Expo Web + native logic tests) at best"
  fi
  if have adb && have emulator; then
    echo "  Android: start an AVD and run the real app -> level 1"
  else
    echo "  Android: no emulator here -> level 2 at best"
  fi
  echo "  Web: Chromium via scripts/review_screenshots.py"
} | tee "$cache"
