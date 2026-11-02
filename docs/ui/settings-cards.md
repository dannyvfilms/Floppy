# Shared settings cards

Provider Connection and Import use the first authorized React browser pilot.
This is the pattern for incremental UI work: every component creation or edit,
including copy or styling, includes its React port in the same task. Reuse shared
pieces, preserve appearance and behavior, and update migration state per surface
in the register. Deferral requires an evidenced compatibility blocker, a reopening
condition and explicit reporting; task size is not an exemption.
Preserve the [architecture boundaries](../architecture/ui-modernization.md).

## Ownership and usage

There are now two accepted composition modes. AniList uses the shared card with
React-owned children inside a [full provider page](provider-pages.md). Its forms,
dialogs and activity belong to React. Other providers retain the partial shell
described below while their body controls await scoped ports. Use a full React
subtree when the task calls for the complete component; a header-only island is
not a completed control or page migration.

The `settings_card` Django block tag in `users/templatetags/ui_tags.py` composes
one card with a React presentation root and a **sibling server-owned body**:

```django
{% load i18n ui_tags %}
{% translate "Personal credentials" as title %}
{% settings_card title=title %}
  {% include "users/components/provider_personal_credentials.html" %}
{% endsettings_card %}
```

Presentation options are `title`, `tone` (`neutral`, `info`, `warning`), `badge`,
`info_label` and `info_title`. `enabled=False` emits only the body, preserving the
existing Connection setup/restore dialogs that share Import templates.
Translate text before passing it. A unique `json_script` contains presentation
props only: no keys, provider context, raw HTML, action URLs or form state.

The shared `frontend/settings/SettingsCard.jsx` uses React Native primitives.
`mount.jsx` is the web adapter: it uses React DOM, supplies browser theme tokens,
and renders the component without its own frame because Django's outer section
contains both the React header and the server body. Future React-owned children
can use the framed component directly. The web slot is not a portable form API.
Neither React hydration nor `dangerouslySetInnerHTML` is used.

`settings-card.css` owns the browser frame, semantic palette mapping and useful
server-rendered fallback. React owns heading/badge/help descendants exclusively;
`x-ignore` prevents Alpine from initializing them. Django/Alpine/HTMX keep ownership
of body fields, CSRF, validation, submits, provider-specific options and dialogs.
Port these controls deliberately later; do not move their HTML into React or let
two frameworks own the same subtree. Credential help dispatches the bounded
`settings-card:info` event to the existing dialog; it carries only the trigger
element so closing the dialog can restore focus. Permission checks remain server-side.

## Shared chips

`frontend/settings/Chip.jsx` is the shared primitive for card status badges,
Read-only actions, provider-key links and media pills. It owns typography, border,
padding, shape and hover/focus feedback. Use the browser `ProviderChip` wrapper
when a chip needs a standalone tone; card badges inherit their card's palette.
Links retain native anchor/new-tab behavior through RNW's web `href`/`hrefAttrs`;
actions use `onPress`, and passive chips have no interactive role. Web adapters
suppress text underlining and outline animation while preserving theme motion.
The `pill` option preserves rounded media-identity chips. Native link behavior
remains separately unverified.

## Build and deployment

```sh
npm ci --ignore-scripts
npm run build:ui
npm run check:ui
```

Dependencies are exact-pinned with `package-lock.json`. esbuild aliases
`react-native` to RNW and emits a small ES-module loader, CSS, hashed lazy React
chunks and third-party license notices under `src/static/ui`. Commit source,
lockfile and generated assets together. CI checks byte-for-byte output. There is
one shared runtime and no CDN, dev server, new web application or Node production
process. Django serves/collects these files through the existing static path;
the container copies the committed output. Top-level assets use the existing
static mtime query, and lazy chunks use content hashes.

The loader is installed once by `base.html`, so navigation from an unrelated page
can discover cards. Pages without cards do not load React. It mounts idempotently
on initial load, `htmx:load` and `pageshow`; it unmounts before HTMX cleanup and on
ordinary `pagehide`. A persisted browser back/forward-cache document keeps its valid
roots and form state while frozen; `pageshow` is idempotent. Pending imports check
connectivity and duplicate roots. Unmount restores
the fallback before ordinary removal; persisted bfcache documents keep their live UI. Failed lazy imports retain
the server heading, help trigger and working body and can retry on a later insertion.

Rebuilding assets requires reloading the browser; there is no hot-reload pipeline.
Both shells render a body-level asset-version guard. Boosted navigation retains
the head, so a response with a newer loader/CSS version triggers a full navigation
to that response's URL instead of showing new islands against an older build.
This also covers a previously opened page whose loader cannot recognize a new island.
After a component changes, run the build and update its register/source-map entries.

## Verification and limits

Browser acceptance budgets for this pilot: under 110 KiB gzip for the one-time
React/RNW renderer, under 3 KiB gzip for the expanded global loader/CSS, no card-induced horizontal
overflow, no lost form nodes/state, and zero retained mounted roots after DOM cleanup. A persisted bfcache page deliberately retains its still-valid roots. Reference desktop execution is bounded
at 150 ms from renderer fetch completion to mounting both cards, layout shift below
0.02, and retained-heap growth below 5 MiB after 40 cleanup/remount cycles. The browser
regression uses a looser one-second execution guard to avoid making shared CI
runner scheduling a flaky performance test.
The initial card-only build was approximately 95 KiB gzip for the renderer and
1.4 KiB gzip for loader/CSS/shared bootstrap helper. The full AniList port adds about
6 KiB gzip of page code, shares the same React runtime, and brings global loader/CSS
to about 2.5 KiB gzip. This is a significant one-time cost for a small shell;
future components must reuse that runtime. The original card-only Chromium 151 macOS reference run measured 62 ms to mount, 0.0014 total layout shift,
and about 0.5 MiB heap growth across 40 cycles. These are headless desktop reference
results, not measurements on physical mobile devices. Broader rollout should measure
real device performance before accepting larger units.

Targeted checks:

```sh
SECRET=test-only scripts/test.sh users.tests.test_ui_tags users.tests.views.test_metadata_settings users.tests.views.test_provider_catalog users.tests.views.test_import_data
SECRET=test-only scripts/test.sh users.tests.test_settings_cards_browser --parallel 1
```

The browser proof uses the repository’s serial Django live test server and local static assets in Chromium 151,
with provider network access blocked. It covers initial mount, partial replacements,
boosted body swaps, back/forward lifecycle events, read-only help/keyboard focus,
CSRF-protected personal-key and preference submissions, private-import gating,
failed bundle fallback, phone/tablet/desktop and six theme states. It does not call
provider APIs, run real OAuth, or replace provider-specific integration tests.

For providers other than AniList, only the card shell is migrated; forms and
provider-specific import controls retain their legacy owners. Their retirement condition is a scoped control
port with equivalent permissions, validation and interactions, not removal of a
fallback or an automatic conversion of every provider at once.

iOS and Android are **not verified**. No Expo application or native transport has
been added. Native consumers must supply concrete theme values and React-owned
children; CSS variables, server body slots and DOM dialog events stay in the web
adapter. Do not label this component Cross-Platform Verified until both platforms
have been exercised and recorded. The broader native architecture proof remains open.
