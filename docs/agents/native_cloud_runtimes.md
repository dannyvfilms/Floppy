# Native screenshots (iOS and Android)

Real iOS and Android frames are evidence level 1 (see "Cross-platform by default" in
`AGENTS.md`). Two ways to get them. The local path needs no Expo account and no cost.

## Local: Mac with Xcode and an Android SDK (tested)

`scripts/env_capabilities.sh` lists what is installed. The real app runs in Expo Go, so no
native build is needed. Use the no-auth preview routes (they render the real shared
components without signing in):

```bash
# 1. Start Metro once for the preview route, from native-proof/
cd native-proof
EXPO_PUBLIC_SEARCH_PREVIEW=1 npx expo start --port 8091      # add --ios or --android to open it

# 2. Boot devices if none are running (first Expo Go open installs it automatically)
xcrun simctl boot "iPhone 16 Pro"                             # or any name from: xcrun simctl list devices available
emulator -avd Floppy_Android_API_35 -no-audio &               # names: emulator -list-avds

# 3. Open the app: press i / a in the Metro terminal, or
xcrun simctl openurl booted exp://localhost:8091
npx expo start --android --port 8091                          # installs and opens Expo Go on the emulator

# 4. Record frames from every booted device into .floppy/review-shots/<label>/
scripts/native_shots.sh before-search
```

Tips:

- Run `scripts/native_shots.sh before-<x>` on the merge base and `after-<x>` on your change.
  Look at the images before you report anything.
- Another route is another env var (`EXPO_PUBLIC_RAIL_PREVIEW=1`) or a new preview route in
  `native-proof/app/routes/`. Restart Metro when you change the variable.
- The first open can time out while Expo Go installs and bundles; open it again.
- Capture light and dark: `xcrun simctl ui booted appearance dark`, and
  `adb shell cmd uimode night yes` on Android.
- Expo Go has no custom native modules. A change that needs `expo-hinge`, `zeroconf` or
  another native module needs a development build instead (`npx expo run:ios`), which is
  slower and not covered here. Say so in the PR if that applies.
- iPhone Duo simulators exist on Xcode 27 (`xcrun simctl list devices available | grep Duo`).
  Use one for hinge and posture changes instead of a browser viewport.
- `scripts/review_screenshots.py --ios` adds a simulator frame to its web report; it does not
  launch or drive the app.

Report level 1 for a platform only when the real app was on screen in the image.

## Hosted: an Expo account (opt-in, not used by the project)

Nothing here runs in CI and nothing is billed to the project. A contributor with their own
Expo account can use it when they have no Mac. Hosted builds and tests draw on that person's
EAS plan, and the hosted Simulator service is a waitlisted preview that is not on the free
tier; check expo.dev/pricing first.

- `native-proof/eas.json`: a `native-preview` profile that builds the search preview as an iOS
  Simulator build and an Android APK.
- `native-proof/.maestro/search-preview.yaml`: a Maestro flow that launches the build, checks the
  screen and takes a screenshot (`maestro test .maestro/search-preview.yaml` also works
  locally against a build installed on a running simulator).

```bash
cd native-proof
npx eas-cli login && npx eas-cli init       # first time only
npx eas-cli build --profile native-preview --platform ios      # or android
```

EAS Workflows can run Maestro flows on cloud devices after a build (Expo's "e2e tests"
workflow docs). Write that workflow in your own fork. There is deliberately no `.eas/workflows`
file or CI job in this repository.
