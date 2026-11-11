# Expo ↔ PWA parity audit

Scope: `native-proof/` (Expo) versus the Django/React PWA.

## Current readiness

Expo is a working development baseline, but is **not ready for PWA parity acceptance**.
Shared imports, a successful bundle and a page opening do not establish feature or
visual parity. The following are known gaps from the owner's manual Expo review;
the closed iPhone Duo is the reported viewport for the Library grid issue.

| Surface | Observed behavior | Remaining work |
| --- | --- | --- |
| Discover | Layout could plausibly match the PWA, but no content feeds through. | Investigate content loading, then compare the populated layout. |
| Library / media lists | Lists load. Grid stops at two columns on the closed Duo, where three are expected. | Match the PWA's three-column grid at that viewport and check other widths. |
| Calendar | Loads the correct layout. | Detailed interaction and state parity remain unverified. |
| Collection | Loads, but needs work; Custom does little. | Compare Collection and Custom behavior with the PWA before defining the fixes. |
| History | Loads. | Detailed visual and interaction parity remain unverified. |
| Lists | Overview loads but needs work. Individual list layouts also load but need tweaks. | Compare overview and detail layouts and behavior with the PWA. |
| Statistics | Loads and is a useful starting point, but needs tweaks. | Identify specific differences in a PWA comparison. |
| Tags | Close, but needs tweaks. | Identify specific differences in a PWA comparison. |
| Settings | Appearance, Media Cards, Home Screen, Providers, Data Management, Access & Tokens, Advanced and About do not load. | Diagnose each destination and restore loading before assessing parity. |

Other Settings destinations are not established as working by the native report.

### Accepted direction

- Home, Sidebar, Search and the Track modal must retain the current `latest`
  presentation and behavior. Similar screenshots do not prove all underlying
  changes have been retained.
- History is accepted by the owner on web, and functions in Expo.
- Statistics is accepted as a starting point, with polish remaining.
- Neither web Collection implementation is the accepted visual target. Both put
  titles below posters, unlike Library's overlaid titles. At a 390px browser width,
  both PWAs show two Collection columns versus three Library columns. This is an
  existing inconsistency, not a newly observed branch regression. The owner's
  observation that native Collection looks closer still needs a matched native
  comparison.

Matched browser captures show close initial-view layouts on the two working
checkouts. The Track dialog differs slightly in its status chevron, and opening
it raises a `fallbackId` browser exception on both checkouts even though the form
renders. Saving, date shortcuts and keyboard behavior are not established by those
captures. Data Management's backup paths and recorded backup history differ with
the preview environment; those differences are not evidence of a design change.

The owner's current uncommitted Home polish has not been confirmed as completely
ported into this branch. Historical acceptance below must not be read as complete
acceptance of the merged branch.

### Evidence and acceptance limits

- **Web:** Runtime evidence from inspected Chromium captures of the working PWA
  and candidate PWA, at desktop and 390px phone widths in the current theme.
  Captures cover initial views and selected menus/dialogs, not every state or
  theme. Both checkouts' generated browser bundles match their source. Previous
  Expo Web spot-checks opened Home, Search, Media Details, Statistics and Calendar.
  A complete PWA-versus-native screenshot comparison remains outstanding.
- **iOS:** owner-reported manual Expo findings above, including the closed Duo grid
  issue. No screenshots were captured or inspected for this report, so it does not
  establish a new formal Runtime evidence level or visual parity acceptance.
- **Android:** unverified for this branch review; no Android rendering evidence was
  collected. The same loading, layout and interaction checks remain necessary.

Continue development from this baseline. Prioritize the Settings loading failures
and Discover's missing content, then the Library grid and the remaining page
comparisons. Causes of the reported failures are not yet diagnosed. No platform
carve-out or feature loss is accepted by documenting these gaps.

## Historical structural baseline

The sections below retain the 2026-11-08 static audit and its subsequently recorded
acceptances. Counts, source footprints and implementation-gap descriptions have
**not been refreshed against the merged branch**. Use Current readiness above for
known runtime gaps, and rerun the existing inventory checks before quoting counts.
The original audit used static analysis without a simulator or device pass.

This document is the contributor-facing answer to two questions:

1. **How many components are migrated to React?**
2. **How many Expo pages have visual parity with the PWA?**

It also lists what remains, in an order people can pick up. Read
[component-register.md](component-register.md) for per-component ownership and
[../plans/expo-web-parity.md](../plans/expo-web-parity.md) for the target architecture.

## Headline

| Question | Answer |
| --- | --- |
| Register entries migrated on web (`Web Migrated`) | **4 of 71** (MEDIA-CARD, SETTINGS-CARD, SPINNER, ALPHABET) |
| Register entries partially migrated | 32 |
| Register entries still legacy | 33 (+1 deferred) |
| Register-weighted share (Web Migrated = 1, Partial = 0.5) | **28.6%** (20.0 of 70) |
| Templates hosting any React island | 197 of 435 (45%); 154 substantive (35%) |
| React share of UI lines (low-end estimate) | 48% |
| Universal (shared RN) presentation files | 155, with 0 frozen legacy files |
| Pages the registry labels `shared` | 26 of 32 |
| **Expo pages verified at visual parity with the PWA** | **1 of 32** (Home, iOS only; see the note below the table) |
| **Shared shell components accepted at parity (iOS)** | Sidebar and the Search media type menu with its suggestions panel; Search results are not (see below) |
| Page views with any iOS runtime evidence | 2 of 32 (Home, Settings Cards) |
| Page views with any Android runtime evidence | 0 of 32 |
| Components verified on both iOS and Android | 4 of 155 (Spinner, Badge, ProgressChanger, GlobalSearch) |

Numbers come from `python3 scripts/ui_migration_metrics.py`, `node scripts/check_page_parity.mjs`
and `docs/ui/architecture-registry.json`. Re-run them rather than trusting this table.
Note `docs/plans/rn-migration-status.md` still says 5 components are verified on both
platforms; the registry currently shows 4, so that file is stale.

### Why "26 of 32 shared" is not a parity number

`check_page_parity.mjs` marks a page `shared` when the web adapter and the native
screen both **import the same view file**. It does not check that:

- the web page is actually rendered by that view (most web pages are still server
  templates with React islands inside them);
- the native output looks like the web page;
- the native page has the same sections, controls and states.

So `shared` means "one file is imported twice", not "the two apps look alike". Treat
it as the *floor* of the work, not the finish line. No existing automated gate
compares native pixels, section order or copy with the PWA.

## Worked example: Media details

Media details is labelled `shared` and no longer serves demo data, but is not close to
the PWA. Evidence:

- `frontend/pages/DetailView.jsx` says so in its own header: the web detail page "is
  server-owned"; the browser mounts only the `header` and `synopsis` parts over the
  server fallback. The page body on web comes from `src/templates/app/media_details.html`
  and ~16 included components (secondary content alone is 624 lines), not from `DetailView`.
- Native `DetailScreen` renders `DetailView part="full"`: hero, header, actions, score
  chips, links, synopsis, a rating control, seasons/episodes, cast/crew and related.
  Several other sections arrive as read-only text lists.
- These are **not wired into the native screen**: `DetailTrackingSlot`, `NotesSlot`,
  `DetailChildrenSlot`, `DetailRelatedSlot` have no importer; `ProgressSlot`,
  `ArtworkSlot`, `DateTimeSlot` are referenced only by `surfaces/inventory.js`. The
  component register marks TRACKING as `Deferred (blocker)` and NOTES, PROGRESS,
  ARTWORK, DATE-TIME as `Legacy`.
- Verification for `DetailView.jsx`: web, iOS and Android all `unverified`.

Functional gaps against the PWA detail page: add/edit/repeat tracking, check-in, progress
adjustment, notes editing, cover/edition selection, activity calendar, collection
entry editing and the popup/dialog host. Visual gaps still need a screenshot pass (see
"What it takes to finish the audit").

## Page-by-page status

Legend, from least to most complete:

- **Native-owned**: registry `legacy`; the native screen builds its own composition.
- **Shared view, server-owned web page**: both import one view but the web page is a
  server template; parity is hand-matched and unproven.
- **Shared view, island-level web mount**: web mounts the view as an island inside a
  server page.
- **Verified**: has recorded runtime evidence. Nothing is "visually at parity" yet.

Server footprint is the size of the web template that still renders the page outside
React (lines / Alpine+htmx attributes). Native demo refs are occurrences of
`demo|fixture|sample|mock` in the Expo screen, a rough indicator of leftover hand-written
data; each needs a manual look.

| Page | Web route | Registry | Web server footprint | Native screen (lines) | Native demo refs | Verified (web / iOS / Android) |
| --- | --- | --- | --- | --- | --- | --- |
| Home | `/` | shared | 139 L / 6 | HomeScreen (506) | 29 (`demoRowDefs`, `/demo/…` hrefs) | web / **iOS parity** / – |
| Discover | `/discover` | **legacy** | 577 L / 12 | DiscoverScreen (14) | 1 | – / – / – |
| Library | `/medialist/<type>` | shared | 276 L / 6 | LibraryScreen (472) | 7 | – |
| Search | `/search` | shared | 398 L / 0 | SearchScreen (29) | 0 | – |
| Detail | `/details/…` | shared (header + synopsis only on web) | 154 L + 624 L secondary / 15 | DetailScreen (203) | 0 | – |
| People / studios | `/people/…` | shared (hero, cast, extras parts) | 275 L / 4 | PeopleScreen (514) | 24 (`DEMO_PERSON`, `DEMO_STUDIO`, `'demo'` mode) | – |
| Music / podcasts | album, artist, show | shared (albums part) | 398 L / 30 | MusicScreen (800) | 4 (+ `musicDemo.js`, 232 L) | – |
| Collection | `/collection` | shared | 589 L / 181 | CollectionScreen (662) | 8 (owner demo bar) | – |
| Lists | `/lists` | shared | – | ListsScreen (726) | 6 | – |
| List detail (tiers, smart rules) | `/lists/<id>` | shared | – | ListDetailScreen (1,159) | 7 (`DEMO_TIER_ASSIGNMENTS`, `DEMO_SMART_RULES`) | – |
| Tags | `/tags` | shared | 71 L / 6 | TagsScreen (97) | 3 | – |
| History | `/history` | shared | 842 L / 32 | HistoryScreen (746) | 27 (`demoEntries()`) | web only |
| Statistics | `/statistics` | shared | **2,512 L** / 103 | StatisticsScreen (**1,658**) | 30 (hard-coded `/demo/…` rows) | web only |
| Calendar | `/calendar` | shared | 142 L / 14 | CalendarScreen (227) | 2 | web only |
| Settings root | `/settings` | shared | – | SettingsScreen (70) | 1 | – |
| Settings: Account, Preferences, Notifications, Appearance, Home, Data, Access, Users, About, Advanced | `/settings/*` | shared | – | SettingsAdvancedScreen (258) + slots | 2 | Cards only: iOS |
| Settings: Cards | `/settings/cards` | shared | – | slot | – | – / **iOS** / – |
| Settings: Sidebar | `/settings/sidebar` | **legacy** | – | none | – | – |
| Providers / integrations | `/settings/providers…` | **legacy** | server tabs | IntegrationsScreen (220), ConnectionsScreen (128) | 1 | – |
| Auth / account security | `/accounts/…` | **legacy** | – | AuthScreen (804) | 10 | – |
| Onboarding | `/setup/…` | **legacy** | – | OnboardingScreen (780) | 2 | – |
| Errors / API docs | error routes | shared | – | ErrorDocsScreen (305) | 3 | – |
| Utilities (export, import, RSS, install, clipboard) | various | **legacy** | – | WebUtilitiesScreen (99) | 1 | – |

Reading the table:

- **0 pages** have the evidence required by `docs/plans/expo-web-parity.md` gate 4
  (native visual comparison at the same fixture state on iPhone, iPad and Duo).
- **6 pages** are explicitly native-owned (`legacy`): Discover, Settings Sidebar,
  Providers, Auth, Onboarding, Utilities.
- **Home is at parity with the PWA on iOS** (2026-11-09): the owner accepted it after
  side-by-side use of the PWA and Expo Go in Device Hub (iOS 27.2, iPhone Duo): cards, status
  chips, artwork, row headers, sort direction and loading. The few deliberate differences are
  device-specific carve-outs, each documented with a short comment in code (native card
  windowing in `Rail.jsx`; cookies sent by hand in `authTransportCore.js`). Android is
  unverified, so this is iOS parity, not all-platform parity.
- **Sidebar and the Search menu are at parity with the PWA on iOS** (2026-11-09): the owner
  validated both on the iPhone Duo in Device Hub: saved views with the always-visible arrow, row
  options as an anchored dropdown, the menu running through the side rail, the media type menu
  and the suggestions panel, whose window resizes with the keyboard. The suggestions panel is
  the dropdown part only: the Search *results* page is not at parity and is being rebuilt from
  Home's row components. Deliberate differences are commented carve-outs (arrow always shown on
  touch, web-only z-index lift above the phone drawer). Android is unverified.
- **8 pages** still carry hand-written demo content in the native screen (Home,
  People, Statistics, History, ListDetail, Collection, Music, Tags). Check each one:
  some demo paths are a loading fallback, others are the displayed content.
- The heaviest remaining items are **Statistics** (web template 2,512 lines, native
  screen 1,658 lines), **Collection**, **History** and **Detail**.

## Component-level status

### Register (web ownership)

By status: 4 `Web Migrated`, 32 `Partial / coexisting`, 33 `Legacy`, 1 `Deferred`,
1 `Existing`. Native readiness of the 36 migrated or partial entries: 23 `Primitives`,
12 `DOM`, 1 n/a. A `DOM` component is React on web but cannot render on iOS or Android
until it is rewritten on React Native primitives.

Legacy entries that block Expo page parity (open for anyone):

| Area | Legacy register entries |
| --- | --- |
| Detail | ARTWORK, NOTES, PROGRESS, DATE-TIME, OWNERSHIP, CUSTOM-FIELDS, METADATA-REVIEW, INTEGRATION-PANELS, **TRACKING (deferred)** |
| Shared | RAILS, ASYNC-STATE, ARTWORK-LOADING |
| Pages | DISCOVER, PEOPLE, TAGS, HISTORY, STATISTICS, LISTS, SMART-RULES, LIST-CURATION, TIERS |
| Settings | SET-NAV, SET-PREFERENCES, SET-APPEARANCE, SET-HOME, SET-ACCESS, SET-NOTIFICATIONS, SET-SYSTEM |
| Integrations / onboarding | ONBOARDING, MATCH-REVIEW, DEVICE-CONNECT, STREMIO |
| Utilities | WEB-UTILITIES, ERRORS-DOCS |

Some register entries (e.g. HISTORY, STATISTICS, PEOPLE) are `Legacy` while the
registry marks their pages `shared`; the two sources disagree because they measure
different things (component ownership versus a shared import). Reconcile them when you
touch the page.

### Verification (runtime evidence)

From `architecture-registry.json`, 155 universal presentation files:

| Platform | Verified | Unverified |
| --- | ---: | ---: |
| Web | 14 | 141 |
| iOS | 11 | 144 |
| Android | 13 | 142 |
| Both iOS and Android | 4 | – |

The Expo export is a compile check only. Until a simulator or device pass records
evidence, "migrated" does not mean "works on a phone".

### Server-owned page regions

195+ templates still compose page structure in Django templates, Alpine and htmx, and
13 provider integration families (Plex, Jellyfin, Emby, Kodi, Navidrome, Nuvio,
Seerr, Stremio, MAL, Trakt, WeTrakr, Last.fm, PSN) are server-rendered
(`providers/content_legacy.html`). They need serializable view models and action
descriptors before they can share a native composition.

## What it takes to finish the audit

This audit establishes ownership and gaps from code. It has **not** compared pixels.
To make "visual parity" a measured claim, someone needs to:

1. **Capture the PWA baseline.** Run the release web build with a fixed fixture user,
   locale and theme; take full-page screenshots at 1440, 768 and 390 for every page in
   the table. `docs/plans/visual-parity-audit.md` and
   `docs/plans/expo-page-parity/` hold earlier captures but cover only Search and
   Tags.
2. **Capture the Expo equivalent.** Same fixture server, Expo on iPhone, iPad and
   iPhone Duo (and Android emulator), using `xcrun simctl io <udid> screenshot` after
   the page settles. No iOS Simulator was booted when this audit ran.
3. **Score each page** on: section order, copy, card shapes and spacing, controls
   present, empty/loading/error states, responsive behaviour. Record a verdict per
   page rather than a pixel percentage.
4. **Write the result into** `architecture-registry.json` (`verification.ios` /
   `android`) so the existing checks report it.
5. **Add a real gate.** Extend `scripts/check_page_parity.mjs` so `shared` also
   requires an entry saying the web side renders the same composition (not just
   fragments), plus a checked-in section/copy manifest per page.
6. **Fix the metric drift** noted above (stale numbers in `rn-migration-status.md`,
   the `AREAS` table in `ui_migration_metrics.py` mismatching six register IDs:
   BULK_ACTIONS, CONTROL-KIT, MIGRATION, PAGE, PODCAST-EPISODES, SET-USERS).

## Suggested order of work

Follows `docs/plans/expo-web-parity.md` and the gaps above.

1. **Baseline first** (items 1–4 above). Nothing else is measurable without it.
2. **Detail**: wire tracking, progress, notes, artwork and check-in into
   `DetailScreen`; unblock TRACKING; decide whether the web detail page adopts the
   full `DetailView` or the native screen stays a documented adaptation.
3. **Remove demo fallbacks** from Home, People, History, Statistics, List detail,
   Collection and Tags, or move them behind an explicit demo mode generated from the
   page model.
4. **Library, Search, Home, Collection, People/Music**: composition and live data
   already shared; the work is matching layout and states.
5. **Statistics, History, Calendar, Discover**: data heavy; Discover is still
   native-owned.
6. **Settings and providers**: replace the native launcher with the real settings
   navigation, then give provider families view models.
7. **Auth, onboarding, utilities, shell navigation.**
8. **Platform verification** on iOS and Android for every shared view.

## Picking up work

- Start from `docs/ui/component-register.md` (`Legacy` entries are open) and
  `docs/ui/source-map.md` for files.
- Declare in your PR which platforms you actually ran; a compile or Expo export is
  not verification.
- When you finish a page or component, update its register entry, the source map and
  its `verification` block in `architecture-registry.json`, and run:

```bash
npm run check:ui-architecture
python3 scripts/check_ui_docs.py
node scripts/check_page_parity.mjs
python3 scripts/ui_migration_metrics.py
```

## Limits of this audit

- Counts of `demo`-like strings are a pointer, not proof of fake data.
- Server footprint figures count template lines and Alpine/htmx attributes; they
  indicate how much page structure is outside React, not how much differs visually.
- No screenshots, simulator or device runs were performed. Every statement about
  look and feel above is inferred from code until step 1–3 of the finishing plan are done.
