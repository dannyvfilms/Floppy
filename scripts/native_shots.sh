#!/usr/bin/env bash
# Screenshot every booted iOS Simulator and every running Android emulator or
# device into .floppy/review-shots/<label>/, named <label>-ios-<device>.png and
# <label>-android-<serial>.png. Runtime evidence (level 1) only if the real app
# is on screen; this script just records frames, it does not drive the app.
#
#   scripts/native_shots.sh before-search
#   scripts/native_shots.sh after-search
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

label="${1:?usage: scripts/native_shots.sh <label>}"
out=".floppy/review-shots/$label"
mkdir -p "$out"
count=0

if command -v xcrun >/dev/null 2>&1; then
  while IFS='|' read -r udid name; do
    [ -n "$udid" ] || continue
    slug=$(printf '%s' "$name" | tr -c 'A-Za-z0-9' '-' | sed 's/-*$//')
    xcrun simctl io "$udid" screenshot "$out/$label-ios-$slug.png" >/dev/null 2>&1 \
      && { echo "ios     $name -> $out/$label-ios-$slug.png"; count=$((count + 1)); }
  done < <(xcrun simctl list devices booted | sed -nE 's/^ *(.*) \(([0-9A-F-]{36})\) \(Booted\).*/\2|\1/p')
fi

if command -v adb >/dev/null 2>&1; then
  while read -r serial state _; do
    [ "$state" = device ] || continue
    adb -s "$serial" exec-out screencap -p > "$out/$label-android-$serial.png" \
      && { echo "android $serial -> $out/$label-android-$serial.png"; count=$((count + 1)); }
  done < <(adb devices | tail -n +2)
fi

[ "$count" -gt 0 ] || { echo "No booted simulator or emulator found. Run scripts/env_capabilities.sh" >&2; exit 1; }
