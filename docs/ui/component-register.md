# UI component register

For Expo versus PWA page status and remaining work, see the
[Expo parity audit](expo-parity-audit.md).

Use the [architecture and parity gates](../architecture/ui-modernization.md) and
[complete source ownership map](source-map.md). IDs identify behavior families,
not individual HTML elements. Slots, cells and small includes belong to their
parent family unless they acquire an independent contract. Paths below are entry
points; the map enumerates every member. Existing backend contracts remain authoritative.

## Status and maintenance

Every agent edit to a UI component, including copy or styling, upgrades that
component to the shared React pattern with visual and behavioral parity. Reuse or
extend shared components first. This incrementally prepares shared presentation
for eventual native iOS and Android apps and reduces a future bulk migration.
Every changed component must record ownership/migration state for each affected
surface and update the source map. Only evidenced compatibility blockers permit
deferral; record their reopening condition and report them explicitly.

A component is migrated on every surface that uses it, public pages (public lists,
auth and error screens) and signed-in pages alike. Check both shells (`base.html` and
`base_public.html`) and the `public_view` paths before marking a surface done, and
record any public consumer that is left behind.

Every entry has exactly one `- Status:` line that starts with one of these terms in
backticks (`scripts/check_ui_docs.py` enforces it and `docs/ui/source-map.md` repeats it):

- `Legacy`: server templates, Alpine and HTMX own the component. It may draw shared
  React pieces (media cards, `Button`, `Badge`, `Spinner`); the status line names them.
  No React component belongs to the family itself. Open for anyone to take.
- `Partial / coexisting`: a React component owned by this family is mounted on at least
  one surface and the rest of the family is still legacy. The status line says which is which.
- `Web Migrated`: React owns the family on every web surface that uses it. Anything left
  is a different kind of component and is listed with a reason.
- `Deferred (blocker)`: legacy, with an evidenced blocker and a reopening condition
  recorded in the entry. Not open until the condition is met.
- `Existing (no UI work needed)`: a shared foundation (design tokens), not a component to port.

Every `Partial / coexisting` or `Web Migrated` entry also has one `- Native readiness:`
line that starts with one of these terms in backticks. Status says how much of the web
UI React owns; this line says whether that React could also run on iOS and Android
(rules and measurements: [From React on the web to native
apps](../architecture/ui-modernization.md#from-react-on-the-web-to-native-apps)). A
`Web Migrated` entry can be `DOM`: React on the web is not native readiness.

- `DOM`: the presentation is React DOM (HTML tags and CSS classes). A rewrite to
  `react-native` primitives and tokens is still owed before it can run on a phone.
- `Primitives`: the presentation uses `react-native` primitives and no browser API, so
  it renders through react-native-web today. Not run on iOS or Android; its data may
  still arrive only through server-rendered props.
- `Ready`: primitives, no browser API, a JSON data path, and the same source verified
  on both iOS and Android with the result recorded. No entry is `Ready`.
- `Web-only`: a web implementation by nature (charts, camera, drag-and-drop); the line
  names what a native screen would use instead.
- `n/a`: no presentation of its own.

Native iOS and Android are not verified for any entry; `Verification` lines say exactly
what was run. A status is decided from the code, not from older prose: an entry is
`Partial / coexisting` or better only if a React component that the family owns is
mounted by the loader (`frontend/settings/index.js`). To re-check a status run
`python3 scripts/ui_migration_metrics.py --entries`, which lists the React islands that each
entry's own templates mount, then read the mounted component's file. How the migration
percentage is measured is in [migration-measurement.md](migration-measurement.md).

**Defaults for every entry below:** verification is static source inspection only,
browser migration not performed, native not tested. Test references are available
regression targets, **not executed test results**. Related work and recurring
deferrals: none recorded; attach real issue/PR links when known. The settings-card
shell is the first authorized browser pilot; native proof remains open. Ordinary
unassessed components stay `Legacy` rather than prematurely becoming exceptions.

When a component changes, update affected paths/contracts and add or refresh the
explicit fields: `Status`, `Verification` (commands/results, surfaces, platforms/versions and limits),
`Related work`, and `Deferrals` (reason and reopening condition). These override the
defaults. Keep implementation and verification distinct. For partial migrations,
name migrated/legacy consumers and retirement conditions; one migrated variant does
not verify the whole family. Retain retired IDs with replacement references. Check
only affected records for small changes, not the whole inventory.

### Finding work and partially modernized pages

High shared leverage: `MEDIA-CARD`, `RATING`, `FILTERS`, `RAILS`, `DATE-TIME`,
`FORM-CONTROLS`. Parallel presentation worth assessing: add/recommend search previews,
inline settings dropdowns, shell controls, card/table metadata and media-type visual
mappings in `date-range.js` versus `app/config.py`. Consolidate only matching contracts.

Page composition index (existing stack except shared card shells and the full AniList provider region):

- Home: `SHELL`, `HOME`, `RAILS`, `MEDIA-CARD`, `PLAYBACK`, `PROGRESS`.
- Library/search/discover: `LIBRARY`, `FILTERS`, `TABLES`, `BULK`, `SEARCH`, `DISCOVER`, `MEDIA-CARD`.
- Detail: `DETAIL`, `CHILDREN`, `RATING`, `TRACKING`, `NOTES`, `ARTWORK`, `MUSIC`, `PEOPLE`, `PROGRESS`, `INTEGRATION-PANELS`.
- History/statistics/calendar: `HISTORY`, `STATISTICS`, `RELEASE-CALENDAR`, `DATE-TIME`, `FILTERS`.
- Collection/tags/lists: `OWNERSHIP`, `CUSTOM-FIELDS`, `TAGS`, `LISTS`, `SMART-RULES`, `LIST-CURATION`, `TIERS`; shared cards/filters/tables.
- Settings: `SET-*`, `FORM-CONTROLS`, `AUTH`, `ONBOARDING`; integration routes also use `MATCH-REVIEW`, `DEVICE-CONNECT`, `STREMIO`.

Use constituent IDs and explicit consumer overrides to find partial pages; use status
and blockers to find remaining work: `Legacy` entries are open, `Deferred (blocker)`
entries need their reopening condition met first. For churn, aggregate paths from
`git log --format= --name-only --since='90 days ago' -- src/templates src/static/js`
before printing bounded results, then join paths to map IDs. No churn ranking is
asserted here. Record recurring deferrals so frequently touched legacy components
can inform a focused completion pass.

## Structure and shared presentation

### SHELL — Application and public shells

- Purpose/usage: app navigation/header/sidebar/mobile overlay; distinct public/auth shell; settings uses the app shell.
- Alphabet composition: both shells expose an empty body-level slot outside animated
  content so the fixed rail stays viewport-bound; the public shell uses the same
  lazy island loader. Shell navigation/controls remain legacy and visually unchanged.
- Implementation: `src/templates/base.html`, `src/templates/base_public.html`, `src/templates/app/components/sidebar_navigation_items.html`, `src/static/js/safari-rail.js`; Django, inline Alpine and HTMX boost.
- Contract: enabled/pinned links, responsive menu/safe areas, public/auth differences, auth redirects, history cache safety, shared modal targets and response events.
- Data: request/user/context, template tags and navigation preferences in `src/users/views.py`.
- Reuse/blockers: share navigation values/tokens; document layout, history and Safari rail need platform adapters. Do not merge distinct public/auth semantics.
- Status: `Partial / coexisting`. The signed-in sidebar (logo, media-type links with saved-view groups, the Explore section with pinning and pinned lists, Appearance, Settings, Logout) is React-owned through `frontend/ui/Sidebar.jsx` and `mountSidebar.jsx`, fed by `src/app/sidebar_model.py` and the `sidebar_react` tag. Icons travel as parsed shapes through one shared `Icon`. Pins, pinned lists and group open states keep their existing localStorage keys, so the list pin buttons on pages still work. The mobile open and close state, the top bar and the public shell stay Alpine and Django. The onboarding banner stays server-rendered and is placed into the sidebar. The Alpine sidebar markup stays inside the host as the fallback.
- The iOS side rail adds Back on non-Home routes using the app navigation history; Home has no Back. Its canvas omits the bottom safe-area inset when the system rail is present. The menu toggle is the first button below the Wi-Fi indicator in the system side-rail toolbar; a modal replaces it with an X in the same slot.
- Expo iOS uses `NativeShell` as the platform adapter around shared `Sidebar` and search: the native rail toggles an animated, non-modal sidebar, with larger sidebar rows on a supported foldable or vertical rail. Native reserved regions or Expo Go's system arrangement provide the partially folded layout. Expo Android and browser retain the existing `Shell`/`MobileNav` path. On a physical iOS 27.2 Duo in Expo Go, the folded rail toggle, authenticated sidebar, search type picker and partial/full-open layouts were exercised. On the browser Home page, Explore expanded and collapsed. Accessibility, responsive browser states and Android runtime remain unverified for this change. Retirement of the web fallback remains dependent on its existing parity and accessibility checks.
- Corner audit: `ReleaseCalendar` floating filter/menu dialogs use a uniform 12-point radius; compact bottom sheets retain rounded tops and square bottoms. Native screenshot verification of those dialogs remains pending.
- Current native refinement: the iOS canvas changes its target frame with the drawer toggle and uses one native layout animation for both the drawer and canvas. Shared mobile Sidebar hides Appearance on native and browser; shared `Reveal` retains its children through height transitions, while the Explore panel overlays media-type rows within the sidebar viewport so its options can use the full available height and scroll when needed. Opening Explore does not scroll the underlying navigation. Native Sidebar uses 44-point rows and a 25-point top inset; the search field centers on the camera cutout and the Home highlight shares its vertical position. `NativeRoot` measures horizontal insets at the native screen while retaining the navigator's vertical insets. The foreground shell applies those insets to the drawer, Search and page content. Sidebar's 16-point margin and Search and Screen's 22-point margin subtract the corresponding safe-area inset, avoiding extra padding beside the rail while retaining spacing at the opposite edge. The edge trait and fold posture drive rail presentation; reserved regions remain for fold layout. On a physical iOS 27.2 Duo in Expo Go, the screen-scoped insets changed from 84/0 to 0/84 and back to 84/0 as Floppy moved between sides, and the open/closed sidebar and Search were inspected against Claude. The partially open and closed poses were observed; a direct side swap without the intermediate full-screen state and separate portrait/landscape interaction checks remain unverified. Browser interaction for this change, Android runtime, VoiceOver and Android theme adaptation remain unverified.
- Fold transitions: the iOS shell animates drawer and canvas geometry in either direction between fully and partially open, respecting Reduce Motion. On a physical Duo in Expo Go, both posture changes triggered the animation and reached their expected layouts; motion accessibility was not exercised. Browser and Android runtime were not exercised for this refinement.
- Explore overlay: the shared Sidebar gives unpinned entries a separate layer above the primary navigation, sized to its contents and capped to the available height with scrolling. It closes when the last entry is pinned. The chevron points up when closed and down when open. On a physical iOS 27.2 Duo in Expo Go, all seven entries were visible and the content-sized panel left navigation visible above it; browser and Android interaction and screen-reader checks remain outstanding.
- Native readiness: `Primitives`. The shared `Sidebar` and `TopBar` use React Native presentation; platform adapters provide navigation behavior. The Expo iOS toolbar and adaptive layout remain subject to the runtime checks above.
- Verification: `app.tests.test_sidebar_model` (props, active page, all 95 icons parse). Chromium (built-in browser, macOS): the sidebar mounts, Movies is active, Explore opens, pinning Calendar moves it and persists, a pinned list shows under Lists, saved-view reorder mode shows handles, and finishing it saved the new order on the server. A native drag, the delete confirm dialog and a phone-width open and close were not exercised. iOS and Android not tested. Chromium at 375px: the loader selector must list every root the templates emit (`[data-sidebar-root]`, `[data-global-search-root]`, statistics, track form); an omitted root stays hidden by `island-reveal.css` until its 4s failsafe, so the hamburger opened a blank sidebar. Restored; the sidebar mounts at load and shows its links on open. iOS and Android: not verified.
- Validation targets: `src/app/tests/views/test_boosted_navigation.py`; menu/focus parity needs browser observation.

### SETTINGS-CARD — Shared settings card shell

- Purpose/usage: provider Connection instance/personal credentials and account setup, Import preferences/options, and Metadata library source controls.
- Shared runtime: body responses compare the retained head's loader/CSS versions
  with the current build and reload after a stale boosted navigation. This applies
  to private and public shells without changing existing controls or their owners.
- Implementation: `frontend/settings/SettingsCard.jsx`, shared `Chip.jsx`, `mount.jsx`, `index.js`, `settings-card.css`; `src/users/templatetags/ui_tags.py` and `src/templates/users/components/settings_card.html`. See [usage and ownership](settings-cards.md).
- Contract: one title/badge/help/frame pattern with editable/read-only/neutral and public API tones. `Chip` shares passive/action/link styling across status badges, media pills and the provider-key link, with consistent hover/focus highlights and no text underline. AniList supplies React-owned children; retained partial consumers keep their server body outside the header root. Existing backend permissions and CSRF remain authoritative.
- Data: presentation-only `json_script`; no credentials, server body HTML or transport in the shared React API. Shared source uses React Native primitives; the web adapter supplies DOM events and browser theme values.
- Status: `Web Migrated` shared card presentation. AniList uses full React composition; Audiobookshelf uses reusable account connection and manual-import islands. Other providers retain Django body slots and setup/restore dialogs until their controls are ported. This does not migrate `FORM-CONTROLS` as a whole.
- Native readiness: `Primitives`. `Chip.jsx`, `SettingsCard.jsx` use `react-native` primitives with no browser API; browser behavior is in `mount.jsx`. Not run on iOS or Android; its data still arrives as server-rendered props, not from the API.
- Verification: production assets build and collect through Django; targeted Django/theme tests passed. Chromium 151/macOS browser checks cover initial/HTMX/back-forward lifecycle, focus, real CSRF submissions, fallback, responsive widths and six theme states. iOS/Android not tested; no native compatibility claim.
- Related work: [#1793](https://github.com/dannyvfilms/Floppy/issues/1793); user-authorized first React browser component pilot.
- Deferrals: server-owned form bodies retire through scoped control ports after parity checks; native acceptance awaits actual iOS/Android runs and a native theme/transport boundary. Broader performance evidence remains required before larger component adoption.

### FORM-CONTROLS — Fields, popovers, dialogs and feedback

- Modal presentation is React-owned through shared `Modal` and `ModalCloseButton`, with `RailModalProvider` and `RailModalHost` in the Duo shell. Existing shared dialogs, action hosts, pickers, filters, calendar/statistics sheets, sidebar menus, media/collection/history/list forms, bulk menus, tooltips, the barcode scanner and music dialogs consume this boundary. On a supported iOS rail device, dialogs stay inside the app canvas, the rail menu action becomes Close for the topmost dialog, and their header X is hidden. Other iOS devices, Android and web retain RN Modal and their inline close controls. Existing body ownership and retirement conditions remain unchanged; this does not port missing forms or transport. Runtime verification for the new modal path is pending.

- Purpose/usage: repeated buttons, inputs/selectors/tabs, confirmations, help/errors and notifications across forms, settings, filters and modals.
- Implementation: [app-wide React controls](react-components.md), `frontend/ui/controls` and `controls.css`, consumed by provider Overview/Connection/Import/Activity. Legacy consumers include inline templates, `src/templates/users/components/info_tip.html`, `form_save_bar.html`, allauth fields, base modal/toast infrastructure and `src/static/js/keepPopupsOnScreen.js`.
- The shared `TextField` keeps URL fields on one line, supports a configurable trailing-control inset, and does not force a line-height on large native inputs so placeholder and entered text use the platform's natural vertical metrics. The auth server field uses one trailing action: local discovery when the address is empty, connection check when it is present, and clear when it has an error. Discovery reports searching, unavailable, and no-results states visibly. In Remote mode, its info control sits beside the Server address label, with the smaller field-group gap used by other form rows.
- Contract: labels, selected/disabled/busy states, errors/CSRF, click-away/Escape and existing focus behavior, viewport-safe popups, dirty-save live announcements. A universal modal focus trap is not established.
- Data: owning Django forms/errors/messages, Alpine state and response events; feature endpoints retain action semantics.
- Reuse/blockers: use shared `SelectField` for preference forms and `FilterDropdown` for Lists-style filter toolbars. Both share keyboard/typeahead/dismissal behavior but retain distinct appearances. Legacy dropdowns remain inline until their UI is reworked; native behavior still needs proof.
- Scrolling rows: `ScrollRow` in `controls.jsx` is the one horizontal scroll container for tabs and chip filters (no wrap, hidden scrollbar, a fade on the side with more to see, the selected child scrolled into view). `Tabs` (provider pages) and `FilterChips` (Discover media types, mounted by `mountFilterChips.jsx` from the page's Alpine `selectedMedia` and `switchMedia`) both use it. Other wrapping chip rows (details, person and studio pages, tags) are not migrated and keep their markup.
- Validation targets: owning feature tests, `src/users/tests/views/test_preferences.py`; general accessibility interaction coverage unverified.
- Status: `Partial / coexisting`. The shared React controls (buttons, labeled fields/selects, chips/toggle chips, tabs, dialogs, card grids, `Spinner`, `Badge`, `ActionMenu`, `ScrollRow`) are mounted throughout the provider pages and AniList; see BUTTON, BADGE and SPINNER for their template adapters and remaining consumers. Every other consumer (inline templates, `info_tip.html`, `form_save_bar.html`, allauth fields, base modal and toast infrastructure) keeps legacy controls until reworked. Reuse these components by element, without requiring a whole provider/page port. Provider-specific authentication and transport remain in feature code.
- Native readiness: `DOM`. Its presentation (`controls.jsx`, 377 lines) is React DOM with CSS classes and has 24 browser-API references; a rewrite to `react-native` primitives is owed before native.
- Verification: both provider Connection dialogs opened and dismissed with Escape, including focus return and setup-dialog Tab/Shift+Tab wrapping, in Chromium 151 on macOS at 1440×1000 and 390×844 in system light and dark. Native and assistive-technology testing not performed.
- Verification: 17 Chromium tests pass across all AniList tabs, six theme states and phone/tablet/desktop widths. Public/private switching via pointer and keyboard preserves entered username and existing credential gating; surface borders, inset arrows and purple actions are checked in light/dark. Shared toggle/dialog/link chips show focus rings for keyboard navigation only; dialog focus restoration is preserved. Native and assistive-technology verification remain pending.
- Related work: [provider consolidation #1793](https://github.com/dannyvfilms/Floppy/issues/1793). Broader legacy adoption follows component redesigns; the shared browser controls are available now.

### TOKENS — Theme, typography, motion and icons

- Purpose/usage: all surfaces' visual system.
- Status: `Existing (no UI work needed)`. Shared theme, typography, motion and icon foundation that every React and legacy surface reads; not a component to port.
- Implementation: `src/static/css/input.css`, generated `main.css`, `src/templates/app/icons/`, bundled fonts, `src/users/appearance.py`; Tailwind 4/CSS variables.
- Contract: explicit presets/custom and system light/dark, accent contrast, responsive layout and reduced motion; follow [theming](../architecture/theming.md).
- Data: user appearance configuration, media vocabulary in `src/app/config.py`, existing Tailwind build.
- Reuse/blockers: share semantic values; native font metrics, SVG, CSS units/selectors and safe areas require explicit equivalents. No independent palette.
- Validation targets: `src/app/tests/test_theme_tokens.py`, `src/users/tests/views/test_appearance.py`; native visual/accessibility checks outstanding.

### ARTWORK-LOADING — Image loading and fallback

- Purpose/usage: cards, rails, posters/backdrops and detail images.
- Status: `Legacy`. Image loading is plain JavaScript (`artwork-loading.js`, lazySizes); no React component.
- Implementation: `src/static/js/artwork-loading.js`, `image-fallback.js`, lazySizes; `src/templates/app/components/home_artwork_poller.html` is the deferred shelf consumer.
- Contract: no blank/broken art, preserved aspect/fallback provenance, lazy/deferred refresh; display fallback does not overwrite stored artwork.
- Data: server artwork projection/cache URLs and Home cover state in `src/app/views.py`.
- Reuse/blockers: image states/geometry reusable; observers/error hooks/polling are web adapters. Preserve [cover security](../architecture/local-covers.md).
- Validation targets: `src/app/tests/test_media_card_contract.py`, `src/app/tests/test_game_artwork.py`; native caching unverified.

### ASYNC-STATE — Cache/loading refresh lifecycle

- Purpose/usage: Discover, History and Statistics refresh/pending/error state.
- Status: `Legacy`. Plain JavaScript pollers and HTMX fragments; no React component.
- Implementation: `src/static/js/cache-updater.js`, owning inline template pollers/HTMX fragments.
- Contract: bounded retries/timeouts, offline/online recovery, exit cleanup and useful stale/error/loading display without duplicate pollers.
- Data: cache-status endpoint in `src/app/views.py`, feature task/cache state.
- Reuse/blockers: potentially share transitions; browser lifecycle/task transport need adapters. This is not offline synchronization.
- Validation targets: `src/static/js/cache-updater.selfcheck.mjs`, owning feature tests; native background behavior unverified.

### SPINNER — Loading ring

- Purpose/usage: the small spinning ring shown while an HTMX search, infinite-scroll page or library lookup is in flight.
- Status: `Web Migrated` on every consumer that used the legacy `animate-spin rounded-full border-b-2` ring (16 `{% spinner %}` sites in 12 templates, plus the React header search). Browser verification: built-in browser at desktop and phone width, light and dark, on the list page (3 rings) and the Movies library page; ring size, colour, border, position and 1s linear animation compared numerically with the legacy markup; HTMX-swapped markup mounts. Native iOS and Android: not verified.
- Native readiness: `DOM`. Its presentation (`controls.jsx`, 377 lines) is React DOM with CSS classes and has 24 browser-API references; a rewrite to `react-native` primitives is owed before native.
- Implementation: shared `Spinner` in `frontend/ui/controls` (`.ui-spinner` in `controls.css`; `size` in px, `tone` accent, muted or white; decorative, `aria-hidden`), `frontend/ui/mountSpinner.jsx` web adapter registered as `data-spinner-root` in `frontend/settings/index.js`, and the `{% spinner size tone %}` tag (`users/templatetags/ui_tags.py`, `users/components/spinner.html`). The server markup inside the host is the same ring, so it is the fallback if the module fails. The host is `display: contents`, so it adds no box. A host nested inside another island (the header search form) is skipped by the loader; that island renders its own `Spinner`.
- Consumers: Movies/library list, Collection list, Person filmography, List detail (search indicators and load-more), Smart list detail, Custom lists hub, Smart rules builder, Add item, Recommend item, Library move panel and its results, header barcode scan (React `GlobalSearch` and `base.html` fallback). Public list pages use `base_public.html`, which loads the same island bundle.
- Left on legacy, with reopening condition: `users/about.html` (SVG ring with its own look; reopen when About is migrated), `progress_changer.html` (icon swapped by `htmx-indicator`; reopen with the quick progress bar), and the Alpine `:class="{ 'animate-spin': loading }"` refresh icons in detail action buttons, music album/artist pages, Discover and Statistics (they rotate an icon, not a ring; reopen when those buttons are ported).
- Native mapping: `ActivityIndicator`; the contract is `size` and `tone` only.
- Validation: `users.tests.test_spinner_tag`, `lists`, targeted template views.

### BADGE — Pill label

- Purpose/usage: the small rounded label for genres, release types, statuses and flags.
- Status: `Partial / coexisting`. 21 static pill sites in 15 templates listed under Consumers are on the shared `Badge`; the remaining legacy pills below stay hand-written. Browser verification: built-in browser, 14 legacy variants rendered beside the shared badge in a throwaway comparison page across all 12 theme states (system, light, dark, Catppuccin Mocha, Dracula, Nord, Gruvbox, OLED, Glass, Plex, Projector, Video Store): 0 style differences (background, text colour, border, padding, font size, line height, weight, wrapping), size within 0.03 px, same position. Real pages checked at desktop and phone width in light, dark, Glass and Catppuccin Mocha: Movies table Genres column and onboarding Metadata. Not seen on screen: release notes (needs GitHub), music album detail, podcast show, track and secondary genre blocks, add/recommend previews, the arr library panel, Seerr request status and the metadata mapping panel (covered by the comparison page and the tag tests only). Native iOS and Android: not verified.
- Native readiness: `DOM`. Its presentation (`controls.jsx`, 377 lines) is React DOM with CSS classes and has 24 browser-API references; a rewrite to `react-native` primitives is owed before native.
- Implementation: shared `Badge` in `frontend/ui/controls` (`.ui-badge` in `controls.css`; `size` xs, sm, md or tag; `tone` indigo, rose, violet, neutral, outline, tint, genre, green-soft, indigo-soft, emerald-soft or amber-soft; plain-text `label`; optional local `href` for genre links; `nowrap`), `frontend/ui/mountBadge.jsx` web adapter registered as `data-badge-root` in `frontend/settings/index.js`, and the `{% badge label size tone href= nowrap= %}` tag (`users/templatetags/ui_tags.py`, `users/components/badge.html`). The label is text only, never markup; `href` is accepted only when it starts with `/` or `?`. The server markup inside the host is the same pill, so it is the fallback if the module fails. The host is `display: contents`, so it adds no box (a consumer that needs a layout class on the pill, such as `ml-auto`, wraps the tag in its own element). A host nested inside another island is skipped by the loader and keeps the server pill.
- Consumers: genre tags on podcast show, music artist, album and track detail, episode details and the detail secondary content block (links); the library table Genres cell (links, `nowrap`); music album type, year and media-type pills; list add and recommend previews (violet genres); arr library request status; Seerr request status; release notes Installed and Newer than yours; onboarding Metadata suggestion badge; metadata mapping status (Mapped, Mapping needed).
- Left on legacy, with reopening condition: music album codec, bitrate and channels pills (they hold an SVG icon, which cannot be passed as props; reopen when `Badge` gets an icon slot from the shared icon set); `media_metadata_panel.html` source pill (11px, `py-0.5`, one site; reopen with the metadata panel port); `calendar_list.html` Today pill (`text-sm` with `px-2`, one site; reopen with Calendar); person and studio filter links, `tag_index.html` and `discover.html` chips (links or buttons that belong to the filter chip family); `episode_row`, `detail_episode_track_button`, `detail_episode_collection_button` (action buttons); `detail_tag_preview.html` (tag colours come from stored tag data as class strings); `game_lengths_section.html` (hover and tracked-letter variant); `episode_ordering.html` and `match_fix.html` (state-dependent classes); `oauth_applications.html`, `progress_breakdown.html` (uppercase micro-label), `appearance.html` (segmented buttons). Each reopens when its page is ported or when its variant is added to `Badge`.
- Native mapping: a `View` with `Text`; the contract is `label`, `size`, `tone`.
- Validation: `users.tests.test_badge_tag`, `app.tests.test_music_genres`, `app.tests.views.test_podcast_show_detail`, `app.tests.views.test_music_release_views`, `app.tests.views.test_media_details`, `users.tests.test_release_notes`, `users.tests.views.test_onboarding`, `integrations.tests.test_arr_library`, `lists.tests.test_views`, `app.tests.test_templatetags`, `npm run check:ui`.

### BUTTON — Solid action button

- Purpose/usage: the solid indigo (primary) or red (danger) button, the surface "Load more" button and the red text button that templates used to write by hand for form saves, submits and the odd htmx action.
- Status: `Partial / coexisting`. 65 sites in 22 templates are on the shared `Button` (61 plain or form-submit, 4 htmx: the two History Load more branches and two history Delete buttons in the song and podcast track modal, `fill_track_song.html`); 211 hand-written solid indigo or red `<button>` tags remain in 87 templates, among 1,125 `<button>` tags in all (counted by `python3 scripts/ui_migration_metrics.py`). Browser verification: built-in browser against an isolated database, with the pre-change build served from a clean checkout of HEAD on another port. Eight legacy variants were rendered next to the shared tag output and mounted by React in all 13 theme states (system, light, dark, Catppuccin Mocha, Dracula, Nord, Gruvbox, OLED, Glass, Plex, Projector, Video Store, custom): 0 differences in background, text colour, border width, radius, padding, font, line height, weight, cursor, width or height. Real pages at 1280 px and 390 px: Media Cards (Save), Account, Lists and History compared button by button with the old build (same position and size to 0.01 px). Clicked on screen: the migrated History Load more (htmx `GET /history/day/...` 200, the day swapped exactly as on the old build) and the Media Cards Save (a form submit: `POST /settings/cards/tv` 302). Not seen on screen: every modal or tab-state button (the Authenticator and recovery codes forms in Account, the Trakt, Jellyfin, MAL, reading-server and provider credential forms, onboarding steps, collection, track notes, match fix, OAuth device), the track-modal history Delete buttons, which are covered by the tag tests and the template tests only. Native iOS and Android: not verified.
- Native readiness: `DOM`. Its presentation (`controls.jsx`, 377 lines) is React DOM with CSS classes and has 24 browser-API references; a rewrite to `react-native` primitives is owed before native.
- Implementation: shared `Button` in `frontend/ui/controls` (`.ui-button` in `controls.css`; the existing `danger` and `secondary` props are unchanged; new `tone` danger-solid, danger-deep, surface or ghost-danger, `small` for text-sm, `auto` to fit the label and `flat` for no border), `frontend/ui/mountButton.jsx` web adapter registered as `data-button-root` in `frontend/settings/index.js`, and the `{% button label tone size width submit= disabled= %}` tag (`users/templatetags/ui_tags.py`, `users/components/button.html`). The label is plain text, translated with `_("...")`. Allowed attributes pass through unchanged: `id`, `name`, `value`, `form`, `formaction`, `title` and any `hx_*`, `data_*` or `aria_*` (written with `_`, rendered with `-`; `hx-on*` is refused because it runs inline script). The server markup inside the host is the same `<button>`, so a form submit still submits and htmx still works if the script fails. The host is `display: contents`, so it adds no box. When React replaces the button it calls `htmx.process` on the host so htmx binds the new node. A host nested inside another island is skipped by the loader and keeps the server button. Radius follows `--theme-radius` and transition timing follows the theme motion tokens, as the old utility classes did. Keyboard focus keeps the browser's default ring, as the old buttons did; the shared 2px indigo ring stays on the AniList and provider buttons.
- Consumers: Account (authenticator and recovery codes, delete account), Media Cards settings, Custom lists (Trakt credentials, import), Provider settings bodies (`provider_import.html`: Connect, Sync now, Disconnect, Save and add-instance forms), Jellyfin and MAL sync, instance and personal credentials, TMDB proxy, reading-server modal, media type provider modal, onboarding (media types, metadata, import status, connect Trakt), OAuth device, match fix, collection modal and entry summary, music track notes, History "Load more" (htmx), track-modal history Delete in `fill_track_song.html` (htmx, ghost red).
- Left on legacy, with reopening condition:
  - Buttons with Alpine bindings (`@click`, `x-show`, `:class`, `:disabled`; 872 tags): the host carries `x-ignore`, and Alpine attribute names such as `@click` cannot be set from React. Reopen when the owning dialog or toolbar is ported so its state lives in React, or when the adapter gets an event contract.
  - Buttons that htmx swaps in place of themselves (`hx-swap="outerHTML"` on the button: the list and tag Add/Remove toggles): htmx would replace a React-managed node. Reopen with a React toggle that owns its own request.
  - Buttons with an SVG or an included icon (solid ones and every icon-only button): an icon cannot be passed as props. Reopen when `Button` gets an icon slot from the shared icon set.
  - Buttons whose attribute values need template composition (`formaction="{% url ... %}?next=..."` in the album, artist and podcast track modals and list form, `form=` in the episode watch row) or whose label is state-dependent markup (`{% if tracker %}Update{% else %}Add{% endif %}`, "Add instance" and "Sync now" variants in `provider_import.html`, `fill_track.html`, `fill_track_song.html`, onboarding services): reopen when the adapter accepts composed attributes, or when those forms are ported.
  - Look variants not yet in `Button`: sizes with `h-10`, `w-48` or `flex-1` (Connect buttons in `provider_import.html`), `rounded-lg` with `hover:bg-indigo-500`, `text-xs` compact buttons, the tracker Delete (red when a tracker exists, grey when not), the segmented buttons in `appearance.html`, tab and chip buttons. Each reopens when its variant is added or its page is ported.
  - Links styled as buttons: none migrated; `Button` already renders an anchor when given `href`.
- Native mapping: a `Pressable` with a `Text`; the contract is `label`, `tone`, `size`, `width`, `submit` and `disabled`.
- Validation: `users.tests.test_button_tag`, the targeted template views listed in the change summary, `npm run check:ui`.

### WEB-UTILITIES — Clipboard, installation and static service worker

- Purpose/usage: copy controls, install feedback and cached static assets.
- Status: `Legacy`. The copy control, install hooks and service worker are plain JavaScript and web-only by nature; no React component.
- Implementation: `src/static/js/copy-item.js`, `serviceworker.js`, install hooks in `base.html` and `users/about.html`.
- Contract: feedback/availability, cache version/cleanup and request/auth boundaries. Static caching does not provide offline tracking.
- Data: DOM values, browser capabilities, service worker route in `src/app/views.py`.
- Reuse/blockers: copy intent shareable; install/service worker stay web-specific. Assess explicit exceptions when migrating a consumer.
- Validation targets: `src/app/tests/views/test_service_worker.py`, `src/users/tests/views/test_about_install_integration.py`.

### ERRORS-DOCS — Error/recovery and API documentation pages

- Purpose/usage: 400/403/CSRF/404/500 and API documentation surfaces.
- Status: `Legacy`. Server-rendered error and API documentation pages that must work without the app's JavaScript; no React component.
- Implementation: root error templates, `src/templates/includes/error_report_panel.html`, `src/templates/api/docs.html`.
- Contract: safe diagnostic/report text, useful recovery links, permission boundaries and usable error documents without normal context or loaded app JS.
- Data: `src/app/error_views.py`, error context and API schema routes.
- Reuse/blockers: error presentation shareable; server error documents/API explorer are web surfaces.
- Validation targets: error view tests under `src/app/tests/`; interactive/native parity unverified.

## Library, discovery and media presentation

### MEDIA-CARD — Canonical card and metadata lines

- Purpose/usage: library, Home, related, search, Discover, lists, collection, credits and tier/group surfaces.
- Implementation: `src/templates/app/components/media_card.html`, `card_lines.html`, `media_card_list.html`, `src/app/card_surfaces.py`, template tags.
- Contract: declared surface/tag, viewer rating/status, aspect ratios, obfuscation, hover/touch actions, public/read-only/bulk states and stable OOB status wrappers.
- Data: `media_list_entries_for_items`, surface flags, card configuration and server projections.
- Reuse/blockers: highest leverage; [media-card contract](../architecture/media-card.md) authoritative. Replace consumers and response slots, never create an unrelated second card system.
- Status: `Web Migrated` for every card the `media_card` tag, `history_card_react` and `media_row_react` render. All 15 surfaces in `card_surfaces.py` set `react_card=True`; History (`history_card.html`) and the Search list row (`media_card_list.html`) use the same `MediaCard.jsx` (poster, square, landscape and `layout: row`). The artwork link, corner chips, progress bar, title and alternate-title tooltip, subtitle lines (including a credit's role line), status chip, rating button with its star popup, hover buttons (track, lists, history, Discover plan and hide, list reorder and drag handle), touch tap-to-reveal and bulk-select checkbox are all React (`MediaCard.jsx`, `mountMediaCard.jsx`, model in `media_card_model.py`). The track and lists popups open in the page's one React host (`ModalHost.jsx`); the cards carry no Alpine and no popup markup. `media_card.html` is a shell: the card wrapper classes (themes and title settings still key off them), the props `<script>`, and a first-paint poster and title link inside the React host that React replaces on mount. The legacy server body, its Alpine fallback and the empty status, overlay and rating slots are deleted. `app.tests.test_media_card_contract.MediaCardInventoryTest` fails if a surface opts out of React, if the template regrows a legacy body, or if any template draws `media-card` markup that is neither the tag nor a documented exception.
- Playback uses the shared list-item MediaCard with a 16:9 artwork area. Its section heading and manual-check-in controls sit above the card; the title is the show/movie and one subtitle line carries the episode title and current play time. `mediaCardGridWidth` and `playbackCardWidth` provide responsive sizing: three compact mobile cards use the shared 110 pt width plus two 16 pt Home-rail gaps; comfortable mobile uses two 168 pt cards plus a 12 pt gap; desktop uses two library-grid cards plus a 12 pt gap. The native card scrim uses a continuous SVG gradient rather than stepped opacity bands.
- Now Playing uses the same indigo fill as standard MediaCards for both playing and paused/stale states, so its progress color does not switch to the playback warning color. The latest color change has not been verified in a reloaded Device Hub build; browser and Android runtime verification remain pending.
- Native readiness: `Primitives`. The native presentation in `MediaCard.jsx` uses React Native primitives and takes card data/handlers as props; browser transport, htmx, and legacy DOM slot behavior stay in `MediaCard.web.jsx` and its mount adapters. Native poster cards now use the server-projected `actions.clickable` preference: hidden actions make the first touch open the card, while shown actions retain tap-to-reveal. The `shouldRevealMediaCardActions` policy is shared logic. Expo Settings > Media Card reads and writes the same `clickable_media_cards` account preference; per-type native profile editing remains local demo state. Device Hub iOS 27.2 / Expo Go runtime opened Settings > Media Cards and showed both touch-action choices; with the local proof card's `actions.clickable: true`, the first tap opened its detail. The Expo proof session had no server account, so preference load/save and the `clickable: false` reveal-then-open path remain unverified on device. Android runtime remains unverified.
- Corner chip sizing: the play/status badge and next-episode chip now share an explicit 24px height on native and web. The iPhone Duo compact Home view was checked after hot reload and shows both chips at matching heights. Compact behavior remains `Next` on narrow cards and `Next ep` on wider cards; the next-episode link keeps its full `Jump to next episode` accessible name. Browser runtime and Android verification for this sizing adjustment remain pending.
- Remaining consumers and retirement: (1) Bulk select is read from the page's Alpine scope (`selectMode`, `isItemSelected`, `toggleItemSelected`) by `mountMediaCard.jsx`. The bulk toolbar and dialogs are React (BULK) but still read the same Alpine selection state (`bulkSelection.js`, published as `window.__bulkSelection`). It retires when selection moves into a shared store that both the cards and the toolbar read; reopen when someone takes that. (2) The save and score responses still send server fragments out of band (`media_card_status_chip.html`, `media_card_rating_oob.html`) for pages that render those slots; a React card ignores the swap (`data-react-owned`) and updates from `floppyCardUpdate`. They retire with the detail-page chips. (3) Documented exceptions that are different kinds of card, not this one: person and cast cards, Statistics highlights and the repeat-player strip, the server-rendered Now Playing fallback, list index cards, and the music album and artist grids (they need an Album or Artist, not an Item). They are listed with reasons in `DOCUMENTED_EXCEPTIONS` in the contract test; reopen if a media item is ever drawn there. (4) The Search list row keeps its `meta` slot (server-rendered per-type metadata) inside the React host.
- Browser verification (Chromium, built-in browser pane and Playwright, macOS, throwaway database and test login): Library grid (movie, game, book), Home, History, Collection, custom list grid, tier board and list table at desktop (1024 and 1280) and phone (375 and 390) widths, light and dark (system theme driven by the OS setting, plus the explicit `light` and `dark` classes). Before and after builds compared on 36 surface, width and theme combinations: 0.0% differing pixels and identical card geometry on all 36; the only DOM differences are the removed empty slot wrappers and the timing of the async release-year fill. Interactions exercised: tracker popup open and save with live card refresh, lists popup add, rating popup and score change, touch tap-to-reveal, bulk select, status chip and no native `<select>` in any card. Not exercised in a browser (no provider network in the test setup): Search (card and list row), Discover and hidden Discover, detail-page related and seasons cards, credit and group surfaces, modal search picker, list recommendations, smart lists, the media-type chip and alternative-title tooltip on a real title. Those are covered by `app.tests.test_media_card_contract` and `test_media_card_model`, which render every surface. Other theme presets (Dracula, Nord, Gruvbox, OLED, Glass, Custom) were not opened. This native preference change does not alter the browser adapter; browser runtime for this revision was not rerun. Device Hub iOS 27.2 / Expo Go: Settings > Media Cards rendered with both choices; a local proof card with `actions.clickable: true` opened detail on first tap. No server session was available, so native preference load/save and the false-value reveal-then-open path were not device-verified. Android runtime remains unverified.
- Update 2026-11-09: native status chips draw the web's SVG shapes through the shared `Icon` contract (`frontend/ui/statusChipIcons.js`) instead of text glyphs, so they centre and match the web; Home cards now carry the status colour class; the poster no longer lifts on hover; the poster progress bar honours the always-visible setting on the React card.
- Validation targets: `src/app/tests/test_media_card_contract.py`, `src/app/tests/test_media_card_model.py`; complete native/consumer matrix outstanding.

### POPUP-HOST — Shared popup host, Add-to-lists form and Track form

- Purpose/usage: one host (`ModalHost.jsx`, mounted once from `base.html`) opens the popups that tracking actions need. Callers send a `floppy-open-modal` event with `{modal, url, vals, target, labels}`.
- Implementation: `frontend/ui/ModalHost.web.jsx`, `ListsForm.jsx`, `modal-forms.css`; `lists_modal_spec` in `src/app/media_card_model.py`; the `lists_modal_click` template tag in `app_tags.py`.
- Contract: `lists_modal` answers `?format=json` with a form model (item, lists with `hasItem` and tags, tag list, toggle URL, CSRF token); `list_item_toggle` with `format=json` answers `{success, hasItem}` or `{success:false, error}` (403 smart list, 404 stranger, 500/503 failure). Permissions, smart-list rule, retries, activity log and error text stay in the views. Labels travel in the open event, translated by the server.
- Status: `Partial / coexisting`. The Add-to-lists form is React-owned (`ListsForm.jsx` with `SelectField`, `Button`, `Spinner`; its own overlay with `role=dialog`, Escape, overlay click, focus into the dialog and back). Consumers moved to the host: the card hover button (grid, History, Search row) and 10 legacy buttons (`detail_action_buttons`, `detail_row_actions`, `detail_music_album`, `detail_music_track_actions`, `music_album_detail`, `episode_details`, `comic_issue_details`, `podcast_episode_list`, `history_card`, `media_card_list`). Their private Alpine `listsOpen` popups are deleted. The Track form is still legacy (below).
- Native readiness: `DOM`. Its presentation (`ListsForm.jsx`, `ModalHost.jsx`, 196 lines) is React DOM with CSS classes and has 25 browser-API references; a rewrite to `react-native` primitives is owed before native.
- Track form (`Deferred (blocker)`): not migrated. Blocker (evidence): the Track popup is not one form. `fill_track.html` is a seven-tab shell (General, Tags, Metadata, Collection, Episode plays, Status history, Discover) built from Django model forms that differ by media type, with three more variants (`fill_track_song.html` 13 KB, `fill_track_episode.html`, `fill_track_episode_bulk.html`), roughly 83 KB of included Alpine templates (date-time picker 11 KB, metadata panel 34 KB, collection fields, notes editor), a 1,461-line builder (`track_modal_views.py`) and 2,399 lines of tests. Its save views answer with htmx out-of-band fragments (status pill, score chip, progress card, notes) and `HX-Trigger` events, so a React form must keep posting through htmx. About 34 templates still own a `trackOpen` popup.
- Reopening condition and plan: port in this order, each its own change with browser proof: (1) a generic Django-form-to-JSON model for the General tab fields plus React date-time picker and notes editor, submitting with `htmx.ajax` so the existing responses keep working; (2) song and episode variants; (3) Tags, Collection, Episode plays, Status history, Discover tab bodies; (4) replace the `trackOpen` popups. Reopen when someone can take step 1.
- Remaining consumers and retirement: `fill_lists.html` is still returned for non-JSON requests; it retires with the existing `ListsModalViewTests` HTML assertions once the Track form leaves htmx popups, or sooner if no caller needs it. `list_item_button.html` is the same.
- Browser verification (Chromium, built-in browser pane, macOS, throwaway database and test login): opened from a Movies grid card (desktop, dark) and a movie detail page (phone width, light); added a list (spinner, then "On 1 list" and Remove), filtered by tag, forced a network failure (inline error, list unchanged), Escape closed it. Not checked: history/episode/table-row entry points, other theme states beyond dark and light, a screen reader. iOS and Android: not verified.
- Validation targets: `lists.tests.test_views.ListsModalViewTests`, `ListItemToggleTests`, `app.tests.test_media_card_contract`.

### RATING — Score display and picker

- Purpose/usage: cards, details, children and music scores.
- Status: `Partial / coexisting`. The star-row picker is React-owned on every consumer; chips, card rate buttons, popup wrappers and derived-TV fragments remain legacy Alpine/HTMX. Browser verification: see below. Native iOS and Android: not verified.
- Native readiness: `Primitives`. `RatingStars.jsx` uses `react-native` primitives with no browser API; browser behavior is in `mountRatingStars.jsx`. Not run on iOS or Android; its data still arrives as server-rendered props, not from the API.
- Implementation: shared RNW `frontend/ui/RatingStars.jsx` with the `mountRatingStars.jsx` web adapter, the `rating_stars` tag (`users/templatetags/ui_tags.py`) and `rating_picker.html` (Alpine wrapper). Legacy: `media_card_rating.html`, `media_card_rate_button.html`, OOB/score-chip/derived-TV fragments.
- Picker consumers: detail score chip (podcast shows, movies, TV, etc.), media card rate button, episode/track/row rating buttons, music artist/album pages, comic issue page. The adapter publishes writes through `htmx.ajax` so server OOB chip/card swaps still apply, and signals the Alpine wrapper with `rating-select`. Alpine publishes the current score through the wrapper's `data-rating`.
- Podcasts rate per show: chip and list cards post to `update_podcast_show_score` (tracker id), not `update_media_score` (episode plays) (#1830).
- Card consumer: the media card's rating button and its popup are React-owned (`CardRating`, using the shared `RatingStars`); detail chips, episode and track rows and music pages keep the Alpine popup wrapper.
- Retirement: the Alpine popup wrappers and direct-rating stars in `detail_score_chip.html` retire when the chip and card rate button are ported with a portal/focus proof.
- Contract: viewer scale, empty/read-only states, hover preview, toggle-to-clear, CSRF writes, teleported popup and OOB/events; derived score/coverage differs from direct score.
- Data: `src/app/score_views.py` and server score projections.
- Reuse/blockers: read-only presentation recommended first proof; interactive picker needs later portal/focus/write proof. Do not infer keyboard support from pointer behavior.
- Validation targets: `src/app/tests/views/test_score_views.py`, `src/app/tests/test_podcast_show_rating.py`, `src/app/tests/test_derived_tv_ratings.py`, card contract tests.

### LIBRARY — Result composition and media grouping

- Purpose/usage: media library grid/table and game/artist/album groups.
- Status: `Legacy`. Result composition, grouping, grids and the table view are server templates. They use shared React pieces: media cards (`media_card` in the grids), the React alphabet rail (ALPHABET) and `Spinner`.
- Implementation: `src/templates/app/media_list.html`, `src/templates/app/components/media_grid_items.html`, grouped-game fragments.
- Contract: bounded pagination, sort/group/view selection, statusless rows, public sharing and refresh with distinct item/tracking identity.
- Data: `src/app/media_list_views.py`, `media_list_entry_grouping_views.py`, `src/app/library_query/`.
- Reuse/blockers: share result model; keep page-specific composition and bounded server queries. REST serializers require separate parity checks.
- Validation targets: `src/app/tests/views/test_media_list_entry_grouping.py`, `src/api/tests/test_media_list_page_cost.py`; [query contract](../architecture/library-query.md).

### ALPHABET — Starting-character filter

- Status: `Web Migrated` across the surfaces below. Native iOS and Android are not verified.
- Native readiness: `Primitives`. `AlphabetBar.jsx` uses `react-native` primitives with no browser API; browser behavior is in `mountAlphabet.jsx`. Not run on iOS or Android; its data still arrives as server-rendered props, not from the API.
- Purpose/usage: desktop media library grid/table (including grouped games, artists,
  albums and podcast shows), manual lists (grid/table/tiers), and smart lists (grid/table).
- Implementation: shared RNW Pressable/Text navigation in `frontend/ui/AlphabetBar.jsx`,
  `mountAlphabet.jsx` web adapter, alphabet template tags and server fallback. The
  filtered empty state reuses the shared Chip for its clear action.
- State by surface: alphabet rail and filtered empty state are fully React-owned on
  every listed surface; Django fallbacks work before mounting or if import fails.
  Mobile has no rail. Surrounding library/list pages, result cards, tables and
  existing filter toolbars remain legacy siblings, not partially owned descendants.
- Contract: All/#/A–Z/representative other glyph; literal displayed-title initial, URL view state,
  filtering/count/group/pagination before hydration, independent cache variants.
  A 32px rail uses muted unboxed letters with an accent for the selection. Its
  links divide the available height so the full alphabet fits without scrolling;
  its top follows the first poster (or the result region when there is no artwork),
  with a safe header offset when scrolling. Numbers appear before A. The final
  glyph comes from an authorized title, using the viewer's title preference; no
  other-glyph entry appears when that bucket is empty unless it is selected. Missing titles use an
  ellipsis. The web adapter optically centers glyph ink with font bounds so
  full-width punctuation does not look offset. Mobile has no rail. Smart-list
  membership rules and permissions are unchanged.
- Coexistence/retirement: fallback HTML is intentional progressive enhancement;
  migrate the remaining result/filter components when they are edited, preserving
  their contracts. No compatibility deferral applies to the alphabet component.
- Verification: `scripts/test.sh app.tests.test_alphabet_filter_browser --tag slow
  --parallel 1` passes in Chromium 151.0.7922.34. Desktop grid/table, anonymous public
  lists, six basic theme/host combinations, fallback/mounted screenshots, keyboard,
  Back navigation, live form state and HTMX association/remount pass at 1440×1000;
  poster alignment and complete-rail fitting are checked at 1024×600/480/360, and mobile exclusion/no horizontal
  overflow passes at 390×844. Result bounds differ by less than one pixel on mount.
  Targeted library/list/provider tests pass; actual native iOS/Android and a live
  PostgreSQL execution have not been performed. Browser iteration builds the test
  schema from models; the normal fast suite separately exercises migrations.
  Stale-head asset coverage reproduces the unstyled horizontal fallback from an
  already-open pre-build page and verifies recovery on boosted sidebar navigation.
  Glyph centering additionally checks visible screenshot ink against the link's
  center, rather than checking only the Unicode text box.
  The representative glyph adds one narrow title lookup to full SQL list pages;
  the page's existing query scope is reused, including provider deduplication.
  Query-budget pins explicitly account for that fixed lookup and pass.
- Related work: none recorded. Deferrals: none for the browser component.
- Components: `AlphabetBar`, `AlphabetEmpty`.

### FILTERS — Filter state, menus and saved views

- Purpose/usage: library/lists, History, Calendar and Home configuration where included.
- Status: `Legacy`. The filter menu and toolbars are Alpine templates on library and list surfaces (`filter_menu.html` is 1,636 lines). The adjacent alphabet rail is React (ALPHABET) and Discover's media-type chips use the shared `FilterChips` (FORM-CONTROLS).
- Implementation: `src/templates/app/components/filter_menu.html`, `filter_form.html`, toolbar/range/scripts, `sidebar_saved_views.html`; `src/static/js/libraryFilterState.js`, `savedViews.js`.
- Contract: normalized rules, clear/default/range/relative/multi-value handling, URL/history/sort, saved-view expand/reorder; refresh after Alpine flush avoids one-click lag.
- Data: owning view catalogs, shared library query, `src/lists/smart_rules.py`, saved-view endpoints in `src/users/views.py`.
- Reuse/blockers: strong state reuse; preserve per-surface availability. URL/forms/SortableJS remain web boundaries.
- Validation targets: `src/app/tests/test_media_list_filter_parser.py`, `src/lists/tests/test_list_detail_filters.py`, `test_smart_list_semantics.py`.

### TABLES — Configurable media tables and cells

- Purpose/usage: library/list/collection tables and artist/album variants.
- Status: `Legacy`. Server table templates; only the Genres cell draws a shared React `Badge`.
- Implementation: `src/templates/app/components/table_items.html`, column menu/config scripts, `cells/`; list/collection row consumers in map.
- Contract: selected/order/persisted columns, sort, score/status/units, responsive scrolling/actions and bounded rows.
- Data: `src/app/columns.py`, result projections and column preference endpoints.
- Reuse/blockers: descriptors/formatting shared; accessible desktop tables and native list presentation may remain separate. Cells are child implementations, not independent units.
- Validation targets: `src/app/tests/test_columns.py`, `test_media_list_columns_browser.py` (slow/browser gates).

### BULK — Multi-item selection and actions

- Purpose/usage: the Select Items bar on media lists, custom lists and smart lists, the Update Status confirmation and Add Plays to History for TV and anime. Slow work runs as a job in a docked card, so the page stays usable. (Formerly two entries, `BULK` and `BULK_ACTIONS`.)
- Status: `Partial / coexisting`. React owns the toolbar (Library group: Update Status, Add to List, Add to Collection, Apply Tag; History group: Add Plays to History), the two dialogs and the job dock. Selection state, select mode and the card checkboxes are still legacy Alpine (`bulkSelection.js`, and `mountMediaCard.jsx` reading the same Alpine scope). Browser verification: toolbar, menus, dock review, background progress across navigation and partial failure exercised in the built-in browser. Native iOS and Android: not verified.
- Native readiness: `DOM`. Its presentation (`controls.jsx`, `mountBulkActions.jsx`, `mountBulkToolbar.jsx`, 711 lines) is React DOM with CSS classes and has 52 browser-API references; a rewrite to `react-native` primitives is owed before native.
- Implementation: `frontend/ui/mountBulkToolbar.jsx` (per list page, mounted from `src/templates/app/components/bulk_selection_toolbar.html`, reads `window.__bulkSelection`), `frontend/ui/mountBulkActions.jsx` (mounted once in `base.html` for signed-in users), the shared `ActionMenu` in `frontend/ui/controls` (styles in `controls.css`), `src/static/js/bulkSelection.js` and the list select button `src/templates/lists/components/bulk_select_button.html`. Alpine and React talk through window events: `bulk-selection-change`, `bulk-actions-open`, `bulk-actions-done`, `bulk-actions-clear`, `bulk-job-finished`. Add Plays jobs persist in localStorage (`floppy-bulk-jobs`) and resume after navigation or reload.
- Contract: identity/count/mode, eligibility, busy/error/reset/refresh and per-user permission checks. Add Plays to History shows on non-TV lists and reports those items as skipped.
- Data/transport: `src/app/bulk_action_views.py` (`bulk_status_update`, `bulk_show_plays_start`, `bulk_show_plays_status`, quick list/collection/tag endpoints), `src/app/services/bulk_show_plays.py`, `bulk_show_plays_task` on the default `celery` queue. Writes go through `apply_bulk_episode_plays`, the single-show Episode Plays path.
- Retirement: the Alpine select mode and card checkboxes retire when selection moves into a shared store that the cards and toolbar both read (see MEDIA-CARD).
- Reuse/blockers: no server fallback for the toolbar; if the island fails to mount, selection works but no actions show. Reopen if a no-JS path is required. Public views stay read-only.
- Validation targets: `src/app/tests/views/test_bulk_actions.py`, `src/lists/tests/test_bulk_actions.py`.

### SEARCH — Global autocomplete, results and barcode input

- Search icon: shared `SearchIcon` in `Icon.jsx` supplies the same connected SVG magnifier to global search, its suggestions, CollectionBrowser and the provider directory fallback. Server-provided icons and remaining template consumers share `app/icons/magnifying-glass.svg`. Native and web keep their existing SVG rendering adapters; the control owners and retirement conditions are unchanged.

- Purpose/usage: header/page search and parent TV/season selection.
- Implementation: `src/templates/app/search.html`, search suggestion/parent fragments; `src/static/js/searchAutocomplete.js`, `searchShortcut.js`, `barcode-scanner.js`.
- Contract: type/local-All/provider queries, pagination/matched titles, two-character suggestions, active-descendant arrows/Enter, shortcut ignores editing, photo ISBN/error/manual fallback.
- Data: `src/app/search_views.py`, provider services, manual artist/album routes; API search parity unverified.
- Reuse/blockers: result/selection values shared; browser keyboard/file/blob and ZXing decoding need native camera equivalents.
- Status: `Partial / coexisting`. The header search form (input, media-type menu, barcode button and its error toast) is React-owned through `frontend/ui/GlobalSearch.jsx` and `mountGlobalSearch.jsx`, fed by the `global_search_react` tag in `app_tags.py`. It appears on every signed-in page. The suggestions list is still a server fragment that htmx swaps into `#search-suggestions`, and `searchAutocomplete.js` and `searchShortcut.js` still drive its keyboard handling through the same element ids. The Alpine form stays inside the host as the fallback. Search results pages are unchanged.
- Native readiness: `Primitives`. `GlobalSearch` uses shared React Native presentation, with `SearchSlot` supplying native transport and scanner behavior. The iOS shell places it across the content width and removes the blue outline on focus.
- This change: the iOS 27.2 Duo in Expo Go displayed the search type picker and an empty-result suggestion on the fully open screen. The search field was also observed beside the open sidebar. VoiceOver, barcode, Android runtime and browser interactions specific to this change were not tested.
- Verification: `app.tests.test_global_search_props`. Chromium (built-in browser, macOS) on `/discover`: form mounts with the right placeholder, typing shows suggestions, the type menu opens with 12 options, picking Books submits `/search?q=matrix&media_type=book`. The barcode scan flow (camera, decode, error toast) was ported but not exercised, and nothing was checked on a phone or in other themes. iOS and Android not tested.
- Barcode scope: the camera shows for All, Book, Manga, Comic and Comic Issue (`barcodeTypes` in `global_search_react` and `SearchSlot.jsx`; the server fallback renders it only for those scopes and keeps its spinner hidden). In All scope a typed or scanned checksum-valid ISBN also searches saved Barcode fields and each barcode-capable type in the user's search menu with its default provider (`_all_scope_barcode_groups` in `search_views.py`); results are grouped by type on the existing results page and a failing provider drops only its group. No new endpoint. Status stays `Partial / coexisting` (server fallback and HTMX suggestions remain). Verified: `app.tests.views.test_media_search` (All-scope fan-out). Browser, iOS and Android runtime not yet verified for this change.
- Validation targets: `src/app/tests/test_search_suggestions.py`, `src/app/tests/views/test_media_search.py`, barcode selfcheck.

### RAILS — Horizontal scrolling and load more

- Purpose/usage: Home, cast, recommendations and related rows.
- Status: `Legacy`. Alpine and HTMX scrolling rows; the cards they hold are drawn by the shared React media card, the row container is not React.
- Implementation: `src/templates/app/components/_scrollable_row.html`, `_scrollable_row_js.html`, `src/static/js/horizontal-scroll.js`.
- Contract: heading/collapse state, arrows/drag/touch, suppress post-drag clicks, bounded load-more, stable art anchors and listener cleanup.
- Data: row descriptors/fragment URL/item template from owning view.
- Reuse/blockers: row/item values shared; scrolling/observer/pointer/persistence adapters required.
- Validation targets: `src/app/tests/test_horizontal_scroll.py`, `src/static/js/horizontal-scroll.selfcheck.mjs`.

### HOME — Shelves, deferred groups and cover refresh

- Purpose/usage: personalized Home composition.
- Status: `Partial / coexisting`. Page composition and server data remain Django templates and Alpine; the shared `HomeShelves` component owns shelf rows on browser and native surfaces, with the canonical shared React media cards inside each row. Phone cards use a 110 pt width so three cards fill the visible row; poster cards grow proportionally taller.
- Native readiness: `Primitives`. `HomeShelves` uses shared React Native presentation on web and Expo; Home data and actions remain in the browser and native adapters. The user reports extensive native Home use in Expo Go on an iPhone Duo; Android remains unverified.
- Implementation: `src/templates/app/home.html`, `frontend/ui/HomeShelves.jsx`, Home group/grid/deferred/artwork-poller components.
- Contract: configured sections, up-next semantics, deferred/coalesced cover polling, canonical cards/rails and progress actions.
- Data: Home row/artwork handlers in `src/app/views.py`, user configuration and server projections.
- Reuse/blockers: composition/data shareable; preserve per-user bounded queries; depends on cards/rails/preferences. Browser owns its Django/Alpine fallbacks; the native Home screen supplies the shared component from its adapter.
- Remaining consumers and retirement: Django/Alpine still owns page composition, settings navigation, deferred markup and the browser polling fallback; retire the coexisting Home surface only when those server-owned responsibilities are replaced with equivalent shared presentation and data adapters, preserving the server fallback and per-user query bounds.
- Verification: The user reports extensive use of the native Home page in Expo Go on an iPhone Duo and considers Home done for the current milestone; follow-up issues will be handled as individual bug reports. The OS and Expo Go versions and specific interaction coverage were not recorded, so this is user-reported iOS acceptance rather than a complete interaction checklist. Separately, Device Hub iOS 27.2 hot-reloaded the shared sizing change; three poster cards now fill the visible row and are slightly taller. Browser and Android runtime verification remain pending.
- Update 2026-11-09 (shared `HomeShelves.jsx`, `Rail.jsx`; native `authTransportCore.js`): one-line row header with the sort name collapsing to its arrow when it does not fit; the sort arrow flips at once with a dimmed row and spinner; failed rows retry three times before offering a tap; one early-artwork policy on web and Expo (a small budget of the covers a sort flip will show, sent by the server as `oppositeArtwork`). Device-specific carve-outs, each commented in code: native mounts only cards near the visible window (`WINDOWED_CARDS` in `Rail.jsx`; web already lazy-loads `<img>`), and Expo sends its cookies by hand with `credentials: 'omit'` because iOS joins repeated `Set-Cookie` values with a comma. Evidence: web runtime (Chromium pane, signed in to a real dev library, cold-load covers timed) and Expo iOS runtime (Device Hub, iOS 27.2, PWA beside Expo Go); Android unverified.
- Validation targets: `src/app/tests/views/test_home.py`, `test_home_screen_season_status.py`.

### PLAYBACK — Now Playing and check-in

- Purpose/usage: Home playback card and detail check-in state.
- Status: `Partial / coexisting`. `PlaybackCard` presents the shared list-item `MediaCard`; web mounts it through `PlaybackTheme.web.jsx`, and Expo uses the same component through `PlaybackSlot.jsx`. The web server fragment remains the fallback and owns refresh/action replacement; the native Home card uses a session-only JSON transport for all active cards and validated Pause/Stop or Stop/Cancel actions.
- Implementation: `frontend/ui/PlaybackCard.jsx`, `frontend/ui/MediaCard.jsx`, `frontend/ui/MediaCard.web.jsx`, `frontend/ui/PlaybackTheme.web.jsx`, `native-proof/app/surfaces/PlaybackSlot.jsx`, `native-proof/app/data/playbackTransport.js`, `src/api/fork_views_playback.py`, `src/templates/app/components/active_playback_card.html`, `detail_checkin_state.html`.
- Contract: 16:9 artwork spanning two regular media cards plus their gap on desktop, three on compact mobile, or two on comfortable mobile; show/movie title; one episode/progress subtitle; Pause/Stop for eligible manual check-ins and Stop/Cancel for session check-ins; current control identity, request replacement/order and stale-state handling.
- Data: playback fragment in `src/app/views.py`, `src/app/checkin_views.py`, server integration events/services.
- Reuse/blockers: presentation is shared and uses the canonical media-card visual model; permissions and current check-in resolution remain server-owned. Native detail check-in state is still a local demo. Browser verification remains pending. Device Hub on iPhone Duo (iOS 27.2) visually confirmed the Now Playing card fits the configured compact mobile span with its right edge visible; actions were not exercised. Android runtime verification remains pending.
- Native readiness: `Primitives`. `PlaybackCard.jsx` composes React Native MediaCard and action primitives; platform transport remains in adapters. The compact mobile layout had a visual iOS runtime check; comfortable mobile, desktop and Android remain unverified.
- Validation targets: `src/app/tests/test_playback_polling.py`, `test_checkin.py`, `test_checkin_session.py`, `test_live_playback.py`.

### DISCOVER — Recommendations and feedback

- Purpose/usage: Discover tabs/rows/hidden/preview and RSS row preview.
- Status: `Legacy`. Uses shared React pieces: media cards on every row and the shared `FilterChips` for the media-type row (`mountFilterChips.jsx`). Tabs, rows, hide/plan actions, previews and refresh banners are Alpine and HTMX.
- Implementation: `src/templates/app/discover.html`, Discover row/card/tab/preview components.
- Contract: enabled types, hide/unhide/planning, stale/empty/refresh states and bounded fragments; cards retain declared surfaces.
- Data: `src/app/discover_views.py`, `src/app/discover/` feedback/caches, separate REST recommendation contract.
- Reuse/blockers: candidate/feedback values shared; poller/HTML response replacement require adapters.
- Validation targets: `src/app/tests/discover/test_views.py`, `test_action_row_partial.py`, `src/api/tests/test_fork_discover.py`.

## Detail, tracking and ownership

### DETAIL — Detail composition and metadata

- Purpose/usage: general and medium-specific detail pages.
- Status: `Legacy`. Layout, hero, sections, facts and sidebar are server templates and Alpine. They use shared React pieces: media cards (related items), `Badge`, the rating picker (RATING) and the Add-to-lists form (POPUP-HOST). The Details-card facts below have no React equivalent yet.
- Implementation: `src/templates/app/media_details.html`, detail title/mobile/synopsis/section/slot fragments in map.
- Contract: responsive art/title/meta, configurable sections, public/auth actions, lazy carousels and notes/history/rating refresh boundaries. Preserve the provider Series Graph's color-coded season/episode score grid, source link, deferred loading and dialog dismissal.
- Data: `src/app/media_details_views.py`, `season_details_views.py`, detail builders and user layout configuration.
- Reuse/blockers: share typed sections while preserving medium composition and swaps; template contexts are not portable APIs.
- Validation targets: `src/app/tests/views/test_media_details.py`, `test_save_response_fragments.py`, `src/app/tests/views/test_trakt_series_graph.py`, `src/app/tests/test_detail_builders.py`.
- Book format links: a "Format" fact in the Details card of Book pages that joins the formats the viewer tracks, e.g. "Book, Audiobook", each name a link except the page being viewed. It replaces the provider's own Format fact when the viewer tracks another format of the same work; several audiobooks are told apart by narrator. Status: legacy, not migrated. Blocker: the Details card is a server-rendered fact list with no shared React equivalent, and porting it is a whole-card migration. Reopen when the DETAIL sidebar facts get a shared React component; this row moves with it. Data: `build_book_formats` (ISBN, or title plus author, among the viewer's own tracked books; never merges Items). Verification: browser only; no iOS/Android.
- Book narrator: a "Narrator" fact in the same Details card for Audiobookshelf audiobooks (`Item.narrators`, filled by the ABS importer, carried in the generic details payload). Status: legacy, same blocker and reopening condition as Book format links. Verification: browser only; no iOS/Android.
- Audiobook listening sessions: each Audiobookshelf listening session is a dated entry (date, time, duration, and where listening stopped) in the activity history modal and the History page, through the existing `session_history_row.html` row (one new "stopped at" fragment in that legacy template), so no new component. Status: legacy row, coexisting; the row has no shared React counterpart yet, and it moves when the history rows do. Data: `BookListeningSession` rows written by the Audiobookshelf importer, emitted by `history_cache_day_builder` and indexed by `history_cache_index`. Counted in Statistics as a separate "Listening Time" figure, never added to page totals. Verification: browser only; no iOS/Android.
- Book page history: a page-based (non-audiobook) book gets one dated entry per day its progress rose, built from its change log ("52 pages · at page 212 / 480"), in the same activity history modal and History page through the same `session_history_row.html` row (a new "at page" fragment in that legacy template). A book's first change-log row is a baseline and dates nothing, so a current page or percentage alone never produces history. Status: legacy row, coexisting. Blocker: the history row and the Statistics reading section are server-rendered Django templates with no shared React counterpart, and porting either is a whole-surface migration. Reopen when History rows or the Statistics reading cards get a shared React component. Data: `build_book_page_entries` over `HistoricalBook`, indexed by `history_cache_index`. Verification: browser only; no iOS/Android.
- Statistics "Listening Time": a stat card at the top of the Books Activity Overview (`reading_consumption_section.html`, `data-listening-time`) showing audiobook listening minutes for the range, kept apart from page counts (audiobook progress no longer feeds "pages", top items, completed-length chart or reading genres). Status: legacy, not migrated; same blocker and reopening condition as Book page history. Data: `BookListeningSession` minutes summed per day in `statistics_day_builder` (`totals.listening_minutes`), marked dirty by the session signal. Verification: browser only; no iOS/Android.

### CHILDREN — Seasons, episodes and issue rows

- Purpose/usage: episode/season/comic detail and child lists.
- Status: `Legacy`. Season, episode and issue rows are server templates and Alpine; they use shared React media cards (seasons), `Badge`, the rating picker and the Add-to-lists form.
- Implementation: `src/templates/app/episode_details.html`, `comic_issue_details.html`, episode/issue/season/action/obfuscation/scroll fragments.
- Contract: ordering, watch/unwatch/drop, score/ownership/history, spoiler obfuscation and correct row/hero/scroll restoration.
- Data: detail/save/score handlers and source/media/season/episode coordinates.
- Reuse/blockers: shared row/actions; medium operations/order explicit. Depends on tracking/rating/collection parity.
- Validation targets: `src/app/tests/views/test_episode_history_poll.py`, `test_episode_score_invalidation.py`, `test_season_status_pill_sync.py`.

### TRACKING — Add/edit/repeat/bulk logging

- Purpose/usage: dialogs and manual creation.
- Status: `Deferred (blocker)`. The Track popup and manual-entry forms are server forms with htmx out-of-band responses. The blocker, port order and reopening condition are recorded under POPUP-HOST (Track form). A few includes use `Button`, `Spinner` and `Badge`.
- Implementation: `src/templates/app/create_entry.html`, fill-track/music/podcast modals, metadata panel; `src/static/js/mediaStatusDateHandler.js`, `episodeBulkTrackForm.js`. Create Custom Entry now also offers an optional RSS Feed URL for custom podcasts; it is stored on `PodcastShow` and queues the existing RSS import. The React track-form island mirrors the legacy `[data-track-modal-root]` Alpine open state (`frontend/ui/mountTrackForm.jsx`), so its portal dialog stays hidden until the user opens the legacy popup instead of covering the page from first paint.
- Contract: medium fields/repeat identity, date/status/progress coupling, notes/errors/delete/events; bulk range/add modes/date distribution remain supported.
- Data: `src/app/track_modal_views.py`, `save_views.py`, Django forms and music/podcast handlers.
- Backend normalization: season modals use the tracked item's coordinate; missing
  provider season lists disable the optional episode domain rather than failing
  the modal. Existing dialog presentation remains legacy and unchanged.
- Reuse/blockers: share fields, preserve distinct operations/server validation. HTML forms do not imply REST write parity.
- Validation targets: `src/app/tests/views/test_track_modal.py`, `test_episode_bulk_save.py`, `test_music_bulk_save.py`, `test_rewatch.py`.

### DATE-TIME — Field picker and activity calendar

- Purpose/usage: tracking dates and session history, distinct from release calendar.
- Status: `Legacy`. Alpine date-time picker and activity calendar; no React component.
- Implementation: `src/templates/app/components/date_time_picker.html`, `calendar.html`, `src/static/js/dateTimePicker.js`, `calendar.js`.
- Contract: clear/current/release/copy, optional time, 12/24h/week-start/locale, six-week grid/month/year, marked/selectable days, hidden values/events and Escape.
- Data: owning field/history configuration and user preferences.
- Reuse/blockers: calculations shareable; native field/popup, timezone and focus semantics need proof.
- Validation targets: owning tracking/history tests; comprehensive independent keyboard/timezone coverage unverified.

### NOTES — Markdown editing and display

- Purpose/usage: detail/media forms/music track notes.
- Status: `Legacy`. Plain JavaScript markdown editor; one include uses `Button`.
- Contract: Write/Preview, toolbar/selection, safe rendering, initialization after full/HTMX loads and save errors.
- Data: bound note fields and music note handler in `src/app/music_views.py`.
- Reuse/blockers: text/formatting intent shared; textarea selection and HTML preview need platform implementation/content safety review.
- Validation targets: `src/app/tests/views/test_music_track_notes.py`; general editor interactions unverified.

### PROGRESS — Adjustment and repeat breakdown

- Purpose/usage: Home/detail progress.
- Status: `Legacy`. Alpine and HTMX progress controls; no React component.
- Implementation: progress changer/breakdown/detail slot fragments.
- Contract: +/-/zero disabled state, spinner/live announcement, medium units/max, TV/season breakdown and run-specific cancel/refresh.
- Data: `src/app/progress_views.py`, progress handler in `src/app/views.py`, domain operations.
- Reuse/blockers: display/buttons shared; preserve authoritative server progress and operation identity.
- Validation targets: `src/app/tests/views/test_progress.py`, `test_rewatch.py`.

### OWNERSHIP — Collection browser and copy editor

- Purpose/usage: collection page, detail/tracking ownership controls.
- Status: `Legacy`. Collection page and copy editor are server templates and Alpine; they use shared React media cards, `Button` and `Spinner`.
- Implementation: `src/templates/app/collection_list.html`, collection modal/form/summary/grid/row fragments.
- Contract: grid/row/table/filter/sort, completeness, multiple copies/labels, medium fields, season cascades and owner-only mutation.
- Data: `src/app/collection_views.py`, forms/models; canonical collection card surface.
- Reuse/blockers: copy editor/summaries shared; collection ownership differs from list membership. Depends on cards/filters/fields.
- Validation targets: `src/app/tests/views/test_collection.py`, `test_collection_copy_labels.py`, `src/app/tests/test_collection_season_cascade.py`.

### CUSTOM-FIELDS — Collection definitions and values

- Purpose/usage: collection editor, summaries, filters/sort.
- Status: `Legacy`. Server fragments with plain JavaScript and SortableJS; no React component.
- Implementation: collection custom-fields/inputs fragments, `src/static/js/collectionCustomFields.js`, SortableJS.
- Contract: type/options/edit/delete/order, JSON saves, typed values/errors; do not duplicate importer resolution rules in UI.
- Data: collection definitions/values and endpoints in `src/app/collection_views.py`.
- Reuse/blockers: schema/field rendering shareable; native reorder and persisted ownership validation required.
- Validation targets: `src/app/tests/views/test_collection_custom_fields.py`, `src/app/tests/test_collection_custom_field_values.py`.

### ARTWORK — Cover and edition selection

- Purpose/usage: detail/tracking image replacement and book editions.
- Status: `Legacy`. Server fragments with Alpine; no React component.
- Implementation: image picker/tiles/cover-change/edition/Hardcover result fragments.
- Contract: candidate/file/URL, preview/reset/save/return, accepted formats/provider identity, authorization and safe outbound fetch.
- Data: `src/app/cover_views.py`, edition routes; [local covers](../architecture/local-covers.md).
- Reuse/blockers: selection state shared; file/drag/blob/camera/native caching need adapters.
- Validation targets: `src/app/tests/test_local_covers.py`, `src/app/tests/views/test_hardcover_edition_views.py`.

### MUSIC — Artist/album/track and podcast composition

- Purpose/usage: artist relations/discography, album tracks, show/episode detail.
- Status: `Partial / coexisting`. The artist discography album grid and relation grid are React islands over Django fallbacks; album and track details, podcast pages and episode rows remain server-rendered/Alpine, with the manual-show episode manager tracked separately under `PODCAST-EPISODES`.
- Native readiness: `Primitives`. `MusicView`, `MusicAlbumCard` and `MusicRelationCard` use React Native primitives; native runtime verification remains unperformed.
- Implementation: `frontend/ui/MusicAlbumCard.jsx` maps the server album URL into the shared card model; `frontend/ui/mountMusicAlbums.jsx` owns browser navigation and the Django-rendered grid remains the no-JavaScript fallback. Artist relations use `MusicRelationCard.jsx` and `mountMusicRelations.jsx`. Album/track/podcast components remain in the source map. Podcast episode rows render an optional description and an empty state.
- Contract: hierarchy/deferred art, per-track actions/history/notes/scores, episode filter/pagination, repeats and show tracking.
- Data: `src/app/music_views.py`, `music_album_views.py`, `podcast_views.py`; web episode JSON/HTML is not proven native API parity.
- Reuse/blockers: remaining server consumers retire as their detail and episode components migrate; keep their current hierarchy/feed behavior and explicit playback boundaries. The album grid uses shared `MusicAlbumCard`/`MediaCard` and keeps its server fallback.
- Validation targets: `src/app/tests/views/test_music_release_views.py`, `test_podcast_show_detail.py`, `test_podcast_detail_rss_refresh.py`.
- Verification: Browser: local artist page island mounted and both album cover/title links opened their album pages after the href mapping fix. iOS and Android runtime verification not performed; registry status remains unverified.

### PODCAST-EPISODES — Manual podcast episode management

- Purpose/usage: add, edit and delete episodes on a podcast show created through Create Custom Entry.
- Status: `Partial / coexisting`. React owns the manager trigger, dialog, episode list, form and inline delete confirmation through `PodcastEpisodeManager.jsx`; the episode rows, detail header and no-JavaScript management page remain server-rendered.
- Native readiness: `Primitives`. The dialog and form use React Native primitives, shared `Button`, `FormTextField`, `FormError`, `FormStatus` and `Dialog`; it is not mounted in the native shell.
- Implementation: `frontend/ui/PodcastEpisodeManager.jsx`, `frontend/ui/mountPodcastEpisodeManager.jsx`, `src/templates/app/podcast_episodes_manage.html`. The manager trigger is mounted from `src/templates/app/components/detail_secondary_content.html` and `src/templates/app/podcast_show_detail.html`.
- Contract: manual shows only (the viewer must track the show); create/edit submit the existing Django form and return field errors as JSON; delete asks for confirmation; duration accepts minutes, mm:ss or h:mm:ss; manual episodes reuse the normal PodcastEpisode catalog so episode tracking, playback progress, history and statistics keep working. Provider-backed shows keep their feed-owned catalog.
- Data: `src/app/podcast_views.py` (`podcast_episodes_manage`, `podcast_episode_add`, `podcast_episode_edit`, `podcast_episode_delete`), `src/app/forms.py` (`PodcastEpisodeForm`), `src/app/models/podcast.py` (`description`, `image`), migration `0223_podcastepisode_description_podcastepisode_image`. Create Custom Entry can also store an optional RSS feed and queue the existing RSS import.
- Reuse/blockers: remaining legacy consumers are the episode list rows, the standalone show page and the no-JavaScript fallback page. They move when the MUSIC episode-row family is ported; the manager no longer depends on them.
- Verification: Django tests (`app.tests.views.test_manual_podcast_episodes`, `test_entry`, `test_podcast_show_detail`, `test_podcast_rss_refresh`, `test_music_genres`), `npm run check:ui`, `npm run check:ui-architecture` and `python3 scripts/check_ui_docs.py` pass. Headless Chromium against a local manual show verified the trigger, add, edit, delete and the normal episode track modal. iOS and Android were not run.
- Related work: #1719.
- Deferrals: none.

### PEOPLE — People/studios, credits and medium extras

- Purpose/usage: person/studio pages and detail cast/trailers/game-length/reading sections.
- Status: `Legacy`. Person, studio and cast pages are server templates; credits draw shared React media cards and `Spinner`. Person and cast cards are separate hand-built components (see MEDIA-CARD exceptions).
- Implementation: `src/templates/app/person_detail.html`, `studio_detail.html`, cast/filmography/carousel/YouTube/extra fragments.
- Contract: internal/external links, role credits, bounded rails, carousel/lightbox/playback and medium metadata.
- Data: `src/app/people_views.py`, provider/detail projections.
- Reuse/blockers: presentation/data shared; embeds/playback/semantic navigation need platform decisions. Person cards intentionally differ from tracked media cards.
- Validation targets: `src/app/tests/views/test_person_detail.py`, `test_studio_detail.py`, `src/app/tests/test_detail_builders_game_credits.py`.

### TAGS — Management and assignment

- Purpose/usage: tag index, detail/library/bulk tagging and settings tag filters.
- Status: `Legacy`. Server fragments with Alpine; no React component.
- Implementation: `src/templates/app/tag_index.html`, fill/tag-button/detail-preview fragments, `src/templates/users/components/media_tag_filter.html`.
- Contract: search/select/add/remove, item/bulk identity, confirmed library-wide delete and consistent filter semantics.
- Data: `src/app/tag_views.py`, user-owned tag relations/library query.
- Reuse/blockers: chip/selection model shared; destructive/ownership checks stay server-enforced.
- Validation targets: `src/app/tests/views/test_tags.py`, `src/users/tests/views/test_settings_media_tag_filters.py`.

### METADATA-REVIEW — Episode order, provider switch and remap

- Purpose/usage: explicit review/correction workflows.
- Status: `Legacy`. Server templates with a plain JavaScript review script; one include uses `Spinner`.
- Implementation: `src/templates/app/episode_ordering.html`, `tv_provider_switch.html`, remap/library-move results, `src/static/js/episodeOrderReview.js`.
- Contract: matched/suggested/manual/archived choices, source/episode coordinates, confirmations/errors and preserved user tracking.
- Data: `src/app/episode_order_views.py`, metadata-sync/detail routes and domain services.
- Reuse/blockers: selection/review patterns shared; mutation semantics need explicit API audit.
- Validation targets: `src/app/tests/test_episode_ordering.py`, `test_tv_provider_switch.py`.

### DETAIL-RELATED — Related-media sections and Steam DLC cards

- Purpose/usage: game/media detail related sections (IGDB DLCs, expansions, remakes) plus display-only Steam DLC cards when IGDB lists none.
- Implementation: legacy Django template `src/templates/app/components/detail_secondary_content.html`; heading via `related_section_label` in `src/app/templatetags/app_tags.py`; data from `app.providers.igdb.get_steam_dlcs`.
- Contract: Steam DLC cards are untracked links to the Steam store (title, header image, URL); IGDB DLCs remain tracked media cards.
- Status: `Legacy`. The IGDB related cards already draw through the React media card (`{% media_card "related" %}`, surface `related`); the section shell, its expand and collapse grid and the Steam DLC link cards are Alpine and hand-written HTML in `detail_secondary_content.html`. Nothing blocks porting the section.
- Validation: `app.tests.providers.test_metadata` (`get_steam_dlcs`), `app.tests.test_templatetags`. Browser/iOS/Android verification: none.

## Feature interfaces

### HISTORY — Feed, edits and activity dialog

- Purpose/usage: global history and per-item sessions/repeats.
- Status: `Legacy`. Day feed, filters, edit forms and the session dialog are server templates. They use shared React pieces: the media card in History layout (`history_card_react`) and `Button` (Load more).
- Implementation: `src/templates/app/history.html`, history day/card/edit and session modal/day/row fragments, `src/static/js/sessionHistory.js`.
- Contract: filters/modes/days, bounded fragments/refresh notice, edit/delete/units, marked dates/day jumps, close-button focus and nested refresh.
- Data: `src/app/history_views.py`, `src/events/history_feed.py`; [memory contract](../architecture/history-memory.md).
- Reuse/blockers: day/session values shared; date/filter dependencies. Never client-load whole history.
- Validation targets: `src/app/tests/views/test_history.py`, `src/app/tests/test_history_item_projection.py`, `test_history_day_cache_lifecycle.py`.

### STATISTICS — Dashboard, charts and taste/talent

- Purpose/usage: statistics, comparison, activity/highlights and featured repeats.
- Status: `Legacy`. Server templates with Chart.js and plain JavaScript; no React component.
- Implementation: `src/templates/app/statistics.html`, statistics/taste/role/studio/featured fragments; `src/static/js/statistics-charts.js`, `stats-media-merge.js`, `date-range.js`, Chart.js/datalabels.
- Contract: media/range/comparison, dates/units, charts/heatmaps/order, refresh/errors and teardown; avoid drift in server/JS media visual mappings.
- Data: `src/app/statistics_views.py`, snapshots/[statistics sync](../architecture/statistics-sync.md).
- Reuse/blockers: transforms/tokens shared; canvas needs native renderer. Keep expensive computation server-owned.
- Validation targets: `src/app/tests/views/test_statistics.py`, `src/app/tests/test_statistics_sync.py`, `test_statistics_media_merge_js.py`; browser layout checks are slow.

### RELEASE-CALENDAR — Upcoming releases and subscriptions

- Purpose/usage: release calendar page, not `DATE-TIME`.
- Status: `Partial / coexisting`. The gear menu (Go to Today, Fetch New Releases, Download Calendar, Week starts on Monday/Sunday) is React-owned through the shared `ActionMenu` (now with an icon trigger, link items and a pressed state on inline actions). The month grid, agenda, list, filters and toolbar remain legacy Alpine/server templates. Browser verification: menu, week-start switch and agenda labels exercised in the built-in browser. Native iOS and Android: not verified.
- Native readiness: `DOM`. Its presentation (`controls.jsx`, 377 lines) is React DOM with CSS classes and has 24 browser-API references; a rewrite to `react-native` primitives is owed before native.
- Implementation: `src/templates/events/calendar.html`, calendar grid/list components; mostly inline Alpine. Gear menu: `frontend/ui/mountCalendarLinks.jsx` + `ActionMenu` in `frontend/ui/controls`; props from `events.views._calendar_menu_props`. The week start saves through the existing `update_statistics_preferences` endpoint (same `week_start_day` the date pickers and Statistics read), then reloads.
- Episode labels: grid agenda and list share `Event.season_episode_label` ("S39E170"); a season's title drops a trailing "Season N" so the label carries it once.
- Contract: month/today/grid/list, media/status/release/tag filters, persisted view, grouped dates/media, ICS/download/subscription/reload and empty states. Redesign needs explicit requirements.
- Data: `src/events/views.py`, `src/events/calendar/`, tasks; [reload contract](../architecture/calendar-reload.md), REST parity unverified.
- Retirement: the Alpine toolbar/grid retire as the filter menu and day grid are ported. The server-rendered "Go to Today" link inside the menu host is the no-JS fallback.
- Reuse/blockers: date/filter/group values shared; layout/ICS/browser subscription adapters explicit.
- Validation targets: `src/events/tests/test_views.py`, `test_release_semantics.py`, `calendar/test_main.py`, `src/api/tests/test_calendar.py`.

### LISTS — Lists, memberships, public profiles and collaboration

- Purpose/usage: list browser/detail/activity/profile/forms and membership popup.
- Status: `Legacy`. Manual-list grid/table/tiers and public detail pages use the React alphabet rail (ALPHABET), media cards, `Spinner` and `Button`. List headers, toolbars, tables and editing controls retain legacy ownership; migrate each when edited.
- Implementation: `src/templates/lists/custom_lists.html`, `list_detail.html`, `user_profile.html`, `list_activity.html`, list grid/form/visibility/membership/table components.
- Contract: manual/smart/source-backed distinction, search/tags/roles, public/unlisted/private, membership/pins/feed/export/sync and public read-only rendering.
- Data: `src/lists/views.py`, browse/action/helper views, models/forms; REST parity separately assessed.
- Reuse/blockers: list card/editor/membership shared; consume canonical media/filter/table systems; collection ownership is separate.
- Validation targets: `src/lists/tests/test_views.py`, `test_forms.py`, `test_rss_feed.py`, `test_csv_export_import.py`.

### SMART-RULES — Rule editing and results

- Purpose/usage: smart-list detail/editor/summary.
- Status: `Legacy`. Smart-list grid/table detail pages use the React alphabet rail (ALPHABET) and `Spinner`; rule editing, summaries and result components remain legacy. Alphabet view state does not alter their saved rule or permission contracts.
- Implementation: `src/templates/lists/smart_list_detail.html`, smart rules builder/summary components.
- Contract: initial JSON/live editing/save/errors, results/sort/bulk and shared rule semantics.
- Data: `src/lists/views_smart_list.py`, `smart_rules.py`, library query engine.
- Reuse/blockers: normalized filter state/schema shared; never fork evaluation for native/Home.
- Validation targets: `src/lists/tests/test_smart_list_semantics.py`, `test_smart_list_sync_deferral.py`.

### LIST-CURATION — Search, add and recommend

- Purpose/usage: add/recommend/approval pages and preview dialogs.
- Status: `Legacy`. Add, recommend and approval pages are server templates; they use shared React media cards, `Spinner` and `Badge`.
- Implementation: `src/templates/lists/add_item.html`, `recommend_item.html`, `list_recommendations.html`, search/preview components.
- Contract: provider/type/query/pagination, preview/add/recommend/approve/deny and role-specific permissions.
- Data: `src/lists/views_add_reorder.py`, `views_recommendations.py` and distinct actions.
- Reuse/blockers: parallel search/preview presentation can consolidate; do not merge authorization/submission semantics. Depends on search/cards/dialogs.
- Validation targets: `src/lists/tests/test_views.py`, `test_item_rank.py`, `test_integration.py`.

### TIERS — Board, order and export

- Purpose/usage: editable/public list tier boards.
- Status: `Legacy`. Tier board, drag-and-drop and export are server templates, plain JavaScript and SortableJS; tiles draw shared React media cards.
- Implementation: tier board/tile components, `src/static/js/listTiers.js`, SortableJS.
- Contract: moves/order/colors/unranked/fill-from-ratings/undo/export/truncation; editable only for authorized manual non-smart lists.
- Data: `src/lists/views_tiers.py`, `tiers.py`, `tier_export.py`, transactional ordering.
- Reuse/blockers: board state/media values shared; accessible reorder/native export need adapters.
- Validation targets: `src/lists/tests/test_tiers.py`, `test_tier_fill.py`, `test_tier_export.py`, `test_item_rank.py`.

## Settings, identity and integrations

Current settings use `src/users/provider_views.py`/`provider_catalog.py`.
`legacy_settings()` in `src/users/provider_views.py`, wired by `src/users/urls.py`,
redirects old metadata/import/integration/
export/MAL routes to current provider/data/access/activity pages. Retained page
templates are compatibility/composition sources, not equally active parallel pages.

### SET-NAV — Settings layout and media-type preferences

- Purpose/usage: settings sidebar/mobile menu, media-type selection/order.
- Status: `Legacy`. Server settings layout and media-type picker; no React component.
- Implementation: `src/templates/users/base.html`, `sidebar.html`, media-type picker/order-script components.
- Contract: current-page semantics/responsive collapse, enabled types/Discover/order and boosted navigation.
- Data: `src/users/views.py` sidebar/preferences handlers and user config.
- Reuse/blockers: navigation/selection model shared; routing/HTMX/native navigation remain platform boundaries.
- Validation targets: `src/users/tests/views/test_settings_media_tag_filters.py`, `src/users/tests/views/test_onboarding.py`.

### SET-PREFERENCES — Preferences and save states

- Purpose/usage: locale/date/time/title/region/general behavior settings.
- Status: `Legacy`. Server form with inline selectors and the shared save bar; no React component.
- Implementation: `src/templates/users/preferences.html`, inline selectors/help, shared save bar.
- Contract: unsaved/disabled/selected/error states, validation, dirty tracking and polite announcements.
- Data: preferences handler in `src/users/views.py`, `src/users/forms.py` and user fields.
- Reuse/blockers: fields/selection/save model shared; repeated dropdowns consolidate when feasible. Mobile preferences parity unverified.
- Validation targets: `src/users/tests/views/test_preferences.py`.

### SET-APPEARANCE — Theme and detail layout editor

- Purpose/usage: swatches/custom effects and detail-family section enable/order.
- Status: `Legacy`. Server template with an inline Alpine editor; no React component.
- Implementation: `src/templates/users/appearance.html`, inline `appearanceEditor()`/JSON-script config.
- Contract: selection/custom validation, tabs/zones/order and persisted settings.
- Data: `src/users/appearance.py`, appearance handler in `src/users/views.py`.
- Reuse/blockers: tokens/editor state shared; CSS runtime/reorder need platform implementations.
- Validation targets: `src/users/tests/views/test_appearance.py`, `src/app/tests/test_theme_tokens.py`.

### SET-CARDS — Card configuration and preview

- Purpose/usage: per-media line selection/reorder/live preview.
- Status: `Partial / coexisting`. Browser settings remain the server template with its inline Alpine editor. Expo Settings uses the shared React Native `CardsEditor`; its touch-action preference is server-backed, while native per-type profiles remain a local preview.
- Native readiness: `Primitives`. Expo `CardsEditor` uses React Native components; touch-action preference transport is server-backed, while per-type profile persistence remains a local preview.
- Implementation: `src/templates/users/cards.html`, `cards_preview.html`, inline `cardsEditor()`; `frontend/pages/SettingsCardsView.jsx`, `frontend/settings/CardsEditor.jsx`, `native-proof/app/surfaces/CardsSettingsSlot.jsx`.
- Contract: per-type values/default/order and previews consistent with canonical projection.
- Data: `src/users/card_metadata.py`, card settings/preview handlers; `native-proof/app/data/settingsTransport.js` reads and writes `clickable_media_cards` through `/api/v1/user/preferences/`.
- Reuse/blockers: shared schema/state with card; server preview HTML needs adapter.
- Remaining consumers and retirement: the browser keeps the Django/Alpine per-type editor and server preview. Native per-type profile values remain demo-only until a server read/write contract exists; the touch-action preference is already persisted server-side.
- Validation targets: `src/users/tests/views/test_cards.py`, `src/users/tests/test_card_metadata.py`, `native-proof/app/data/transportRoutes.test.mjs`.

### SET-HOME — Home section/shelf editor

- Purpose/usage: Home rows/filter/sort/list-backed sections.
- Status: `Legacy`. Server template with an Alpine and SortableJS editor; no React component.
- Implementation: `src/templates/users/home_screen.html`, inline `homeScreenSettings()`, Alpine/SortableJS.
- Contract: nested order/labels/colors/collapse/menus, owned/collaborator/smart-list search, validation and payload.
- Data: `src/users/home_screen.py`, Home config/search/filter handlers.
- Reuse/blockers: editor model/filters shared; native reorder/drag-versus-click need proof.
- Validation targets: `src/users/tests/views/test_home_screen.py`, `test_home_screen_menus.py`.

### SET-PROVIDERS — Catalog and capability tabs

- Purpose/usage: current provider browser/detail and status cards.
- Implementation: `frontend/providers/ProviderDirectoryView.jsx` and shared catalog/toolbar controls; `src/templates/users/providers.html` and provider result/card templates provide the server fallback. `provider_detail.html` and provider status/row components retain other consumers. The former Alpine filter-dropdown template has no active directory consumer.
- Contract: query/capability/media, 300ms search/URL/history, supported tabs and connection health.
- Data: `src/users/provider_views.py`, `provider_catalog.py`, `provider_ui.directory_page`; HTML fallback and authenticated private/no-store JSON with explicit presentation fields only.
- Reuse/blockers: catalog/status values shared; do not assume services available standalone.
- Validation targets: `src/users/tests/views/test_provider_navigation.py`, `test_provider_catalog.py`, `test_provider_integration_sections.py`.
- Status: `Partial / coexisting`. `Web Migrated` for the Providers directory and every provider's header, media chips, tabs and Overview. All use `ProviderPage` and data-driven shared cards; AniList also owns Connection, Import and Activity bodies. Other tab bodies remain server-owned siblings with partial shared card consumers. The directory reuses app-wide catalog and filter controls. The server `header_fallback.html` shares the React header's classes (`provider-identity`, `provider-media-chip`, `ui-tabs`) so the mount causes no reflow; media chips sit in the title row itself (wrapping among themselves, never below the title); React-owned tab bodies and unmounted island roots stay hidden until mount (4s CSS reveal as the failure fallback); the activity loader placeholders use the same `settings_card` shell as the loaded partial. Browser-verified only; iOS/Android not verified. See [provider-page ownership and data](provider-pages.md).
- Native readiness: `DOM`. Its presentation (`Directory.jsx`, 105 lines) is React DOM with CSS classes and has 10 browser-API references; a rewrite to `react-native` primitives is owed before native.
- Verification: 184 targeted provider/credential/model/import/action/OAuth tests and 15 Chromium 151/macOS browser checks passed. The browser checks exercise all four AniList tabs at phone/tablet/desktop widths and six theme states, form submissions, activity diagnostics/actions, fallback and navigation lifecycle. Native not tested.
- Directory verification: 51 targeted Django tests and all 21 provider Chromium checks pass. Directory checks cover container-based columns, combined filters, capability-specific links, Connection status icons, empty results, Back navigation and bundle-failure native form submission. Shared preference/filter menu appearances, typeahead, Escape/click-away and focus return are checked. Desktop dark/mobile light screenshots were reviewed. Native not tested.
- Shared provider structure verification: 121 targeted view/import/model tests and 22 Chromium checks pass. Every catalog Overview is checked against the common model and supported tab links; browser checks compare BoardGameGeek, AniList and a file-only provider, then verify retained credential forms mount beside the shared header. Overview reads stored task state without refreshing or writing it. Native not tested.
- Metadata verification: 131 targeted metadata/default-selection/resolution tests and 24 provider browser checks pass. All Metadata tabs use the shared inline model; fixed primary-source activity, personal-key-only source selection, shared defaults across provider pages and exclusion of stored proxy values are covered. Overview and directory column counts match at phone/intermediate/desktop widths.
- Metadata contribution refinement: shared `FeatureList` rows describe consumed outputs and local activity, including unsupported game outputs for comparison. 74 targeted provider/credential tests and 25 browser checks pass; coverage includes missing/personal artwork keys, public Steam artwork, ScreenScraper instance access without a member login, simplified settings text and responsive feature rows. Native not tested.
- Related work: [#1793](https://github.com/dannyvfilms/Floppy/issues/1793). Deferral: provider-specific forms and navigation remain legacy until scoped ports; native verification remains open.

### SET-METADATA — Credentials, defaults and repair

- Purpose/usage: provider connection/metadata/admin repair.
- Implementation: provider connection/metadata/credential row/modal/status/default/repair components; instance, personal and default shortcut fields are shared by inline Connection and the retained legacy modal in `src/templates/users/metadata.html`.
- Contract: personal/server scope, set/clear/return destination, media defaults/admin checks; never expose existing secrets for convenient display.
- Data: `src/users/metadata_views.py`, credential services/repair handlers.
- Reuse/blockers: field/status reusable; authorization/secrets remain server-owned, mobile endpoint/secret audit required.
- Validation targets: `src/users/tests/views/test_metadata_settings.py`.
- Status: `Partial / coexisting`. `Web Migrated` for every Metadata tab through `Metadata.jsx`, with inline shared source/default forms, anime format, fixed/supplemental explanations, migration actions and TMDB proxy settings. AniList owns instance/personal credential forms and its permission dialog; other credential bodies remain Django forms with shared React headings. Preserve editable/read-only/environment locks; saved values and previews never enter page models.
- Native readiness: `DOM`. Its presentation (`Metadata.jsx`, 79 lines) is React DOM with CSS classes and has 0 browser-API references; a rewrite to `react-native` primitives is owed before native.
- Verification: 78 targeted provider, metadata, sync and import tests passed with `FLOPPY_TEST_FAST_DB=1` (migrations not replayed); Chromium 151 on macOS, system light/dark at 1440×1000 and 390×844, including permission dialog focus and Escape. Native and assistive-technology testing not performed.
- Related work: [#1793](https://github.com/dannyvfilms/Floppy/issues/1793). Deferral: the legacy metadata template retains its modal for compatibility; retire that consumer when the retained legacy template is removed. Native credential transport and secure storage await separate design and the foundation proof.

### SET-IMPORT — Connect, upload and schedule

- Purpose/usage: provider import tabs, reading-server dialogs/schedules.
- Source inventory: shared file import is `frontend/providers/ProviderFileImportView.jsx`;
  `clz_import_fallback.html` is its retained server fallback. Their ownership is
  recorded here; this alphabet change does not alter their migration state.
- Inventory (Playwright and server-render checked; iOS/Android unverified): single-file and
  small upload forms use `FileImport.jsx` through `provider_ui.FILE_IMPORTS` (Yamtrack/Floppy, HLTB,
  Playnite, Grouvee, IMDb, Goodreads, StoryGraph, YouTube, WeTrakr, Hardcover, TV Time, MDBList), with
  `file_import_fallback.html` as the hidden-until-mount fallback. Credentials on every provider
  Connection tab use `Credentials.jsx` (`provider_ui.provider_credentials`). Account-style connections use
  `AccountConnection.jsx` via `provider_views.ACCOUNT_CONNECTIONS` / `INSTANCE_CONNECTIONS` (Kapowarr,
  Mylar, Radarr, Sonarr, GPodder, Pocket Casts, Koito, Last.fm, PSN, Storyteller, Kavita, Komga, Xbox,
  Stremio sign-in, MAL authorize). Webhook setup instructions use `SetupGuide.jsx`
  (`provider_guides.py`: Emby, Kodi, Navidrome, Nuvio, both Jellyfin guides, the Seerr and global Seerr
  guides, the Stremio addon steps; token-bearing URLs and links are read from the server fallback, never
  serialized). Small integration settings forms use `SettingsForm.jsx` (`provider_forms.py`:
  Plex usernames and mark-watched, Jellyfin webhook events, Seerr automation and connection, KOReader
  connect and settings). Hardcover sync, KOReader (Connection tab) and MDBList (Connection tab) use `SettingsForm.jsx`/
  `FileImport.jsx` inline instead of a modal. Plex's Connection tab is the shared webhook card (`SetupGuide.jsx` with a primary copy
  field, status badge/tooltip and collapsed steps; `provider_guides._plex_webhook_badge`) above the shared account
  card (`AccountConnection.jsx` with badges and a single full-width card); the "Set up account access here /
  Open connection setup" header and button no longer render on provider pages. Jellyfin's Connection tab matches it: one webhook card (primary copy field, status tag) with the two plugin
  setups (official, unofficial) as two side-by-side cards below it (one fold each, stacked on phones), and every folded `SetupGuide.jsx` guide
  (Plex, Jellyfin, Emby, Seerr) now renders as two cards, status and copy field first, steps second, with a 1rem gap
  (`.ui-guide-stack`, and a margin between separate guide roots). Emby's and Seerr's guides are folded with a primary copy field (the Jellyfin official
  guide shows a "Needs update" badge when the template is outdated and warns KefinTweaks users that its watchlist
  rating of 1 is not a real rating, so they should remove the Rating field from the template; no last-received
  badge because Floppy stores no Jellyfin webhook timestamp, so adding one needs a user-model migration), above the shared
  `AccountConnection.jsx` card (`provider_views`, new `editable` flag: connected accounts get an "Edit connection"
  toggle that re-submits server URL, API key and username, prefilled from non-secret fields; the API key is never
  serialized). Status: React-owned on browser (Connection tab), verified in the browser only; iOS and Android not
  verified. The KefinTweaks copy addition is covered by the server-render guide test; it changes no layout or styling.
  Remaining legacy, with blockers: Jellyfin Import/Sync/Tracking cards and the Emby/Kodi Sync push forms
  (per-tab conditional flags share one POST that must preserve the other tab's flags, covered by
  `test_provider_integration_sections`; reopen when those flags move to `provider_forms`); Kodi, Navidrome and Nuvio
  guides stay expanded (their URL sits mid-step, not a plain "set the URL" step; reopen when the step copy is split). Remaining legacy, each with a
  concrete blocker: Plex libraries picker and webhook sharing (Tracking/Import tabs; live library fetch,
  per-share Alpine state); Jellyfin account/push controls (conditional per-tab
  states); Stremio addon catalog grants (htmx status); the same-tab modal copies of upload and connection forms used outside provider pages. Retire each by moving it to a `provider_forms` or
  `provider_guides` entry. Masked credential previews are not serialized to React; the fallback still
  shows them.
- Implementation: provider-import/schedule/game-sync/Plex-selector/upload-badge components, `users/_reading_server_card.html`, `_reading_server_modal.html`; retained import page.
- Contract: connect/disconnect/import/upload/schedule, provider-specific fields/library/content kinds, errors/busy state.
- Data: import context/settings in `src/users/views.py`, `src/integrations/views.py`, account/task records.
- Reuse/blockers: field/status/schedule primitives; keep distinct provider flows/server-required jobs.
- Validation targets: `src/users/tests/views/test_import_data.py`, `src/integrations/tests/test_plex_import_views.py`.
- Status: `Partial / coexisting`. `Web Migrated` for AniList preferences, serialized auto-save, public username import and credential-gated private OAuth form. Uses app-wide fields/selects/buttons/card grid and a reusable Public/Private `ToggleChip`; provider code retains authentication semantics. Other providers share the React import-preferences island while their provider-specific forms remain Django-owned; data management retains its restore dialog. Activity lists use bounded scrolling and provider pins are persisted per user. Native verification remains pending.
- Native readiness: `DOM`. Its presentation (`AccountConnection.jsx`, `Credentials.jsx`, `FileImport.jsx`, `SettingsForm.jsx`, `SetupGuide.jsx`, 333 lines) is React DOM with CSS classes and has 8 browser-API references; a rewrite to `react-native` primitives is owed before native.
- Verification: targeted provider catalog and import tests cover scheduling, credentials, uploads and scoped activity; Chromium on macOS checked AniList, Pocket Casts and Playnite at desktop and phone widths in dark mode. Native not tested.
- Related work: [#1793](https://github.com/dannyvfilms/Floppy/issues/1793). Deferral: native upload, scheduling and server-job adapters await the foundation proof and separately authorized client work.

### SET-ACTIVITY — Import and operational activity

- Purpose/usage: activity/run details/cancel/rollback/cleanup/outbound status.
- Implementation: `frontend/providers/ProviderActivityView.jsx` and shared settings cards, alongside `src/templates/users/provider_activity.html`, import loader/activity/cleanup and integration/outbound activity components. Provider activity uses React card headers with Django-owned body slots until those controls are migrated.
- Contract: five-second polling pauses swaps while `[data-keep-open=true]` details are expanded and preserves bounded list scroll positions; preserve pending/running/result/error, copying and action permissions. Task history and import runs are separate records; runs expose counts and undo where supported.
- Data: provider activity handler, ImportRun/tasks and cancel/rollback/cleanup handlers.
- Reuse/blockers: status/activity presentation shared; transport/job control adapters must not erase user work on refresh.
- Validation targets: `src/users/tests/views/test_cancel_import_run.py`, `test_cancel_pending_import.py`, `test_rollback_import_run.py`.
- Status: `Partial / coexisting`. `Web Migrated` for AniList scoped schedules, paged history, run actions and source cleanup. React owns polling and preserves expanded diagnostics. Other provider/central Activity surfaces retain their current records/actions and templates.
- Native readiness: `DOM`. Its presentation (`Activity.jsx`, 114 lines) is React DOM with CSS classes and has 2 browser-API references; a rewrite to `react-native` primitives is owed before native.
- Verification: scoped JSON tests cover exact ownership, pagination and token exclusion; existing cancel/undo/source cleanup tests pass. Chromium 151/macOS checks polling pause, error details and schedule removal returning to Activity. Native not tested.
- Related work: [#1793](https://github.com/dannyvfilms/Floppy/issues/1793). Deferral: native activity transport and job controls await separate client work and the foundation proof.

### SET-SYNC — Integrations, outbound sync and health

- Purpose/usage: provider integration/sync/service tabs.
- Implementation: `src/templates/users/providers/integration_content.html`, service integration/MAL/outbound fragments, sync/scrobble/conflict/status/modals.
- Contract: webhook/library/user choices, connected/broken distinction, directions/conflicts/kill switches and provider instructions.
- Data: `src/users/views.py`, `src/integrations/state/settings_view.py`, integration actions; connection-health contract applies.
- Reuse/blockers: status/fields shared; background integrations require server capabilities and distinct provider semantics.
- Validation targets: `src/integrations/tests/test_sync_settings.py`, `src/users/tests/views/test_provider_sync_templates.py`.
- Status: `Partial / coexisting`. The small integration settings forms (Plex usernames and mark-watched, Jellyfin webhook events, Seerr automation and connection) are React `SettingsForm` islands, inventoried under SET-IMPORT; the Sync, Tracking and Import tab bodies and the MAL and outbound sections stay Django. Watched-state configuration is on the supported media server Sync tabs; Activity surfaces conflicts when present. Provider-scoped MAL and outbound sections use the provider shell's surface.
- Native readiness: `n/a`. No React presentation of its own; it composes the components of other entries.
- Verification: the 78 targeted tests above include `test_provider_sync_templates`; Chromium 151 on macOS at desktop and phone widths in system light/dark covered the disconnected MAL Sync page, but not a connected outbound account. Native not tested.
- Related work: [#1793](https://github.com/dannyvfilms/Floppy/issues/1793). Deferral: native sync settings and server integration adapters await the foundation proof.

### SET-DATA — Export/restore, danger zone and RSS

- Purpose/usage: data management and RSS builder/preview.
- Status: `Partial / coexisting`. The backup destination and freshness paragraphs of `export_controls.html` are React-owned (`frontend/settings/BackupStatus.jsx`, see the backup bullet below); the schedule form, export, danger zone, RSS and the rest of the page stay legacy.
- Native readiness: `DOM`. Its presentation (`BackupStatus.jsx`, 17 lines) is React DOM with CSS classes and has 0 browser-API references; a rewrite to `react-native` primitives is owed before native.
- Implementation: `src/templates/users/data_management.html`, `rss.html`, export/danger controls; retained export pages.
- Contract: content eligibility/schedules/download history/restore/repair, destructive confirmation/ownership; RSS copy/preview skips planning/collected filters.
- Data: provider data-management and export/delete/RSS handlers in `src/users/views.py`.
- Reuse/blockers: selection/warning/status shared; download/clipboard/feed/restore are platform/server boundaries.
- Validation targets: `src/users/tests/views/test_export_schedule.py`, `test_bulk_delete_by_import_source.py`, `test_rss.py`.
- Backup status (#1627): the destination/freshness paragraphs of `export_controls.html` are React-owned (`frontend/settings/BackupStatus.jsx`, partial/coexisting — the schedule form and the rest of the page stay legacy). Server fallback retained inside `data-backup-status-root`; sections are built and translated by `users.views.backup_panel_props`. Retirement: when the export form itself is ported. Browser verification: Chromium via the isolated bench server, empty-history state mounted and rendered both sections; failure and PostgreSQL states covered by unit tests only. iOS/Android: not tested.

### SET-ACCESS — Tokens, grants and OAuth approval

- Purpose/usage: access settings, application/device authorization.
- Status: `Legacy`. Server templates; one include uses `Button`.
- Implementation: access-token/integration-token/catalog-grant components, `src/templates/integrations/oauth_applications.html`, `oauth_device.html`.
- Contract: one-time secret, scope/expiry/copy/revoke, grants and device approve/deny.
- Data: token/grant handlers, `src/integrations/oauth_management.py`, `oauth_device.py`.
- Reuse/blockers: fields/status shared; secure native storage/auth lifecycle separately designed, never credentials in shared presentation.
- Validation targets: `src/users/tests/views/test_integration_tokens.py`, `src/integrations/tests/test_oauth_device_flow.py`.

### AUTH — Authentication and account security

- Purpose/usage: login/signup/social/password/TOTP/recovery/deletion.
- Status: `Partial / coexisting`. Browser authentication and account security remain server-rendered allauth/account templates. The native-proof sign-in and account screen use shared `AuthView`, `AuthEntrance` and account cards.
- Native readiness: `Primitives`. Shared auth presentation uses React Native primitives; server discovery, auth transport and secure session storage stay in native/platform adapters. DNS-SD runtime has not been exercised on iOS or Android.
- Implementation: `frontend/auth/AuthEntrance.jsx`, `frontend/pages/AuthView.jsx`, `native-proof/app/screens/AuthScreen.jsx`, platform server-discovery adapters, and `src/templates/account/`, `allauth/`, `socialaccount/`, `users/account.html`, `password_recover.html`.
- Contract: errors/redirects/social connections, password/QR/recovery codes, identity-confirmed deletion/demo/last-superuser guards; no email/SMS recovery implied.
- Data: allauth, `src/users/forms.py`, signup/account/recovery handlers, public `/accounts/auth-config/` check for discovered Floppy services.
- Reuse/blockers: native sign-in separates server selection/check/discovery from credentials, then shows the chosen address with a Change action. Manual entry remains available; Local/Remote mode toggles without changing the entered address and suggests `http://floppy.local:8000` locally or `floppy.example.com` remotely. Expo Go shows a brief notice because it cannot browse DNS-SD. Local discovery scans `_http._tcp` advertisements marked as Floppy, then verifies candidates through the public auth-config endpoint. The server-side advertiser is an opt-in Linux Docker host-network sidecar; other deployment modes keep manual entry.
- Remaining consumers/retirement: all browser auth/account templates and allauth controls stay server-owned. Revisit their migration only when browser auth presentation is separately authorized and parity-ready.
- Verification: browser auth remains the existing server-rendered implementation. Earlier Expo Go checks on iOS 27.2 covered the single address action, clear behavior, brief Expo Go discovery notice, Local/Remote suggestions, and compact Remote info control. The two-step server/credentials flow compiles in the iOS Expo export but remains unverified at runtime because Device Hub continued showing the previous bundle after reload and the Expo server reports networking disabled. Native DNS-SD discovery and Android runtime verification remain pending.
- Validation targets: `src/app/tests/test_discovery_advertiser.py`, `native-proof/app/data/serverDiscoveryCore.test.mjs`, `native-proof/app/data/authTransportCore.test.mjs`, `src/users/tests/views/test_signup.py`, `src/users/tests/test_delete_account.py`, `test_demo_account_guard.py`.

### SET-NOTIFICATIONS — Notification preferences/exclusions

- Purpose/usage: release/premiere/digest/test and media exclusion list.
- Status: `Legacy`. Server template with HTMX search; no React component.
- Implementation: `src/templates/users/notifications.html`, search-results/excluded-items components.
- Contract: save/choice/error/test feedback, 300ms search and include/exclude refresh.
- Data: notification/test/search/exclusion handlers and delivery jobs.
- Reuse/blockers: selection/search/exclusion shared; delivery/scheduling remains server capability.
- Validation targets: `src/users/tests/views/test_notifications.py`.

### ONBOARDING — Resumable first-run setup

- Purpose/usage: media/metadata/services wizard, connection/upload/OAuth/Trakt variants/banner.
- Status: `Legacy`. Server wizard templates; they use `Button` and `Badge`.
- Implementation: `src/templates/users/onboarding/`, onboarding-banner component; shared media-type picker.
- Contract: persisted resume/restart/skip/next, connect/import status, Plex instructions and device fallback.
- Data: `src/users/onboarding_views.py`, `src/integrations/onboarding.py`, user state/ImportRun.
- Reuse/blockers: wizard/controls shared; standalone onboarding needs separately approved capabilities.
- Validation targets: `src/users/tests/views/test_onboarding.py`, `src/integrations/tests/test_onboarding.py`.

### SET-SYSTEM — Advanced, About, updates and install

- Purpose/usage: administration/server info/release/install feedback.
- Status: `Legacy`. Server templates; the release notes use `Badge`.
- Implementation: `src/templates/users/advanced.html`, `about.html`, server-port/update-banner/whats-new components.
- Contract: cache/image controls/confirmations/log download/port restrictions, deferred releases and install/API links.
- Data: advanced/about/release handlers, `src/users/server_port_views.py`.
- Reuse/blockers: mostly web/server composition; share action/warning/status primitives rather than whole admin screens.
- Validation targets: `src/users/tests/views/test_server_port.py`, `src/users/tests/views/test_image_cache.py`, `src/users/tests/views/test_about.py`.

### MATCH-REVIEW — Integration match correction

- Purpose/usage: unmatched/incorrect media review.
- Status: `Legacy`. Server template with a plain JavaScript review script; uses `Button`.
- Implementation: `src/templates/integrations/match_fix.html`, `src/static/js/matchFixReview.js`.
- Contract: filters/candidates/chosen identity, POST/error and retained tracking semantics.
- Data: integration views and `src/integrations/match_corrections.py`.
- Reuse/blockers: shared selection/review pattern; distinct correction semantics and permissions remain explicit.
- Logs card: `LogsCard` in `frontend/settings/AdvancedSettings.jsx` (React-owned, shared with `native-proof/app/screens/SettingsAdvancedScreen.jsx`) shows Download Sanitized Logs to superusers and Download Diagnostic Report to every signed-in user. Server contract: `src/users/diagnostics.py`, `export_diagnostics`. Browser verification of the new button: pending. iOS/Android: not verified; the native screen is a stub that waits and shows a message.
- Validation targets: `src/integrations/tests/test_matching_and_corrections.py`.

### INTEGRATION-PANELS — Library/download and Seerr requests

- Purpose/usage: detail Arr/Seerr status/request actions.
- Status: `Legacy`. Server panels with HTMX swaps; Arr and Seerr status use `Badge`.
- Implementation: `src/templates/integrations/library_panel.html`, `seerr_request.html`, `seerr_status.html`.
- Contract: nearest-panel replacement, instance/media/season/episode, copy feedback, per-season request/status, permissions/provider errors and parent modal close state.
- Data: `src/integrations/arr_library.py` and integration handlers.
- Reuse/blockers: status/actions shared; parent Alpine/HTMX coupling must be removed deliberately; server capabilities required.
- Validation targets: owning integration view tests; browser/native lifecycle unverified.

### DEVICE-CONNECT — Trakt/device-code connection

- Purpose/usage: provider connection and onboarding handoff.
- Status: `Legacy`. Server template with inline polling; no React component.
- Implementation: `src/templates/integrations/trakt_device_code.html`, onboarding Trakt consumer.
- Contract: start/poll/code/expiry/redirect and useful errors.
- Data: device-code handlers in `src/integrations/views.py`, account state.
- Reuse/blockers: display/state shared; system browser/deep link/native credentials require explicit design.
- Validation targets: provider/device tests; native handoff unverified.

### STREMIO — Standalone addon configuration

- Purpose/usage: configuration outside standard shell.
- Status: `Legacy`. Standalone server page with an imperative inline script; no React component. Assess a web-only exception when it is next touched.
- Implementation: `src/templates/integrations/stremio_configure.html`, imperative inline script/independent HTML.
- Contract: publish toggles, reorder/accessible labels and generated configuration.
- Data: addon configuration context/endpoints.
- Reuse/blockers: assess explicit web-only exception when touched; do not omit or force into native shell assumptions.
- Validation targets: Stremio integration tests; browser/native parity unverified.

### MIGRATION — Page compositions and adapters awaiting cataloguing

- Status: `Partial / coexisting`
- Native readiness: `Primitives` for the page views; platform adapters stay per-platform.
- Purpose/usage: shared page compositions, native transports and page-level adapters added while the page families converge on the web compositions. This entry keeps every file discoverable in the source map; it is not a claim that every listed file has finished native runtime verification.
- Catalogued components: AboutOverviewCard, AboutVersionFooter, AccessTokenCard, AccountSecurityView, AccountSettings, AccountTypeCard, ActivityList, AlphabetEmpty, ApiCheatSheet, ApiDocCommand, ApiDocs, ApiDocsView, ApiGlossary, ApiSchemaLinks, AppTokensCard, AppearanceEditor, ArrLibraryPanels, ArtworkImage, ArtworkPicker, AttributionsCard, AuthEntrance, AuthNotice, AuthView, AuthenticatorCard, AuthorizedApplicationsCard, BulkActionBar, BulkActionDialog, BulkActionRow, BulkEpisodeForm, BulkFieldRow, BulkJobCard, BulkJobDock, BulkJobMessage, BulkJobProblems, BulkJobProgress, BulkJobSummary, BulkNote, BulkOptionRow, CacheManagementCard, CacheStatusCard, CalendarView, CardScrim, CardsEditor, CatalogCard, CatalogGrantsCard, CatalogGrid, CheckInState, CollectionBrowser, CollectionCopyDialog, CollectionCopyEditor, CollectionCopySummary, CollectionFieldManager, CollectionFieldValueInputs, CollectionSeasonCascade, CollectionView, ComboField, ConfirmDialog, ConnectionSettings, ConnectionsCard, CopyBlock, CopyField, CreditCard, DateTimePicker, DeleteAccountCard, DetailActions, DetailChildren, DetailComposition, DetailCompositionTheme, DetailEpisodeRow, DetailHeader, DetailHistoryDialog, DetailIssueRow, DetailRelated, DetailRelatedTheme, DetailSeasonList, DetailSeasonRow, DetailSection, DetailSynopsis, DetailView, DeveloperSpecsCard, DeviceConnectCard, Dialog, DiscoverFeedback, DiscoverHidden, DiscoverPreview, DiscoverRow, DiscoverRows, DiscoverScreen, DiscoverState, DiscoverTabs, DiscoverView, EditionPicker, EpisodeOrdering, ErrorRecovery, ErrorReportPanel, ErrorStatusSelector, ErrorsView, ExcludedMediaCard, ExportHistoryCard, ExportScheduleCard, FilePicker, FilterBar, FilterToolbar, FormError, FormField, FormHeader, FormProvider, FormSaveBar, FormSelect, FormStatus, FormTextField, HistoryActivityDialog, HistoryActivitySummary, HistoryDayGroup, HistoryDaySummary, HistoryDeleteDialog, HistoryEditDialog, HistoryEntryRow, HistoryFeed, HistoryFilterPanel, HistoryState, HistoryView, HomeScreenEditor, HomeShelves, HomeView, ImageCacheCard, ImportPreferencesCard, ImportSettings, InstallCard, InstallPromptCard, LibraryPageView, LicenseCard, LightboxDialog, ListBulkBar, ListCard, ListDetailPageView, ListEmptyState, ListForm, ListHeader, ListItemPreview, ListItemSearch, ListMembershipPopup, ListMembershipSection, ListRecommendations, ListResultGrid, ListResultTable, ListResults, ListShareLinks, ListsPageView, LogsCard, MarkdownNotes, MarkdownPreview, MediaCardActionButton, MediaCardActionHost, MediaCardActionRow, MediaCardActions, MediaColumnMenu, MediaGallery, MediaIcon, MediaTable, MediaTableCell, MediumExtras, MetadataMatchResults, MobileNav, MusicAlbumCard, MusicAlbumGrid, MusicRelationCard, MusicRelationGrid, MusicView, NotificationPreferencesCard, OnboardingCompleteStep, OnboardingImportStatusStep, OnboardingIntegrationStep, OnboardingMediaTypesStep, OnboardingMetadataStep, OnboardingNotice, OnboardingServiceSetupStep, OnboardingServicesStep, OnboardingSummaryStep, OnboardingView, OnboardingWizard, PageHeading, PageSection, PageState, ParentPicker, PasswordCard, PeopleView, PersonCard, PersonHero, PlaybackCard, PreferencesForm, ProfileCard, ProgressBar, ProgressBreakdown, ProgressCard, ProgressChanger, ProgressDialog, ProjectResourcesCard, ProviderActivityPage, ProviderContext, ProviderMetadataView, ProviderPageView, ProviderProvider, ProviderSettingsFormView, ProviderSettingsView, ProvidersView, Rail, RatingChip, RatingStarIcon, RecoveryCodesCard, RefreshNotice, ReleaseCalendar, ReleaseUpdateBanner, RestoreBackupCard, Reveal, RssFeedCard, ScheduledExportsCard, SearchPageView, SearchResultCard, SearchResults, SeerrRequestDialog, SeerrRequestsCard, SeerrStatusBadge, ServerPortCard, SettingsAboutView, SettingsAccessView, SettingsAccountView, SettingsAdvancedView, SettingsAppearanceView, SettingsCardsView, SettingsDataView, SettingsHomeView, SettingsNav, SettingsNavLink, SettingsNotificationsView, SettingsPage, SettingsPreferencesView, SettingsUsersView, SettingsView, SmartRuleBuilder, SmartRuleSummary, SocialProviders, StatisticsActivityOverview, StatisticsCharts, StatisticsComparison, StatisticsCompletionChart, StatisticsFeaturedRepeat, StatisticsHeatmapChart, StatisticsHero, StatisticsHighlights, StatisticsHoursByMediaTypeChart, StatisticsHoursChart, StatisticsMediaTypeOverview, StatisticsMediaTypeOverviews, StatisticsRatingDistributionChart, StatisticsRhythmChart, StatisticsRoleLeaders, StatisticsState, StatisticsStatusBreakdownChart, StatisticsStatusCompositionChart, StatisticsStudioFootprint, StatisticsSummary, StatisticsSummaryCards, StatisticsTalentSection, StatisticsTasteSignals, StatisticsToolbar, StatisticsView, StremioAddonConfigurator, StudioHero, TagAssignmentDialog, TagBulkDialog, TagIndex, TagMediaFilter, TagPreview, TagsPageView, TextField, TierBoard, Tooltip, TopBar, TrackDialog, TrackTabs, TvProviderSwitch, UsersManagement, UtilitiesView, WhatsNewCard, applyListToggle, applyMarkdownAction, copyText, dateKey, displayHour, formatDisplayText, formatValue, getCacheStatus, getInstallState, hour24FromDisplay, initialTrackValues, inlineMarkdown, isMarkedDay, isSameDay, isSelectableDay, isToday, listsCount, listsCountLabel, listsMembership, markdownBlocks, meridiem, monthLabel, monthShortLabel, monthWeeks, normalizeListsModel, normalizeSelection, normalizeTrackForm, normalizeValue, nowParts, openInstallGuide, pad2, parseDateValue, prefixMarkdownLines, requestBarcode, requestInstall, safeMarkdownHref, stepHour, stepMinute, stepSecond, subscribeInstallState, useProvider, validateTrackValues, valueFromDate, visibleLists, weekdayLabels, wrapMarkdownSelection, yearPage.

### PAGE — Page composition chrome

- Status: `Partial / coexisting`
- Native readiness: `Primitives` for the shared controls; browser adapters stay per-platform.
- Purpose/usage: Shared page chrome, headings and page-level adapters.

### SET-USERS — User management

- Status: `Partial / coexisting`
- Native readiness: `Primitives` for the shared controls; browser adapters stay per-platform.
- Purpose/usage: User list, create/edit/password and delete surfaces.

### BULK_ACTIONS — Bulk actions and job dock

- Status: `Partial / coexisting`
- Native readiness: `Primitives` for the shared controls; browser adapters stay per-platform.
- Purpose/usage: Bulk selection actions, toolbar and background job dock.

### CONTROL-KIT — Shared control kit

- Status: `Partial / coexisting`
- Native readiness: `Primitives` for the shared controls; browser adapters stay per-platform.
- Purpose/usage: Shared control primitives for forms, dialogs, menus and catalog surfaces.
- DateTimePicker: the open and clear controls are drawn from shared views, not the letters `v` and `x`. Browser verified in the Track dialog; iOS and Android not verified.
- TrackForm / TrackTabs / TrackDialog: restored the v26.10.29 modal layout (title bar, icon sidebar with the General tab, two-column General grid, dropdown selects, markdown notes, Delete / Rewatch + Since / Update footer). Tab icons come from the server's `file_icon` specs. Browser verified; iOS and Android not verified. Still different from v26.10.29: the Score spinner buttons and the Just Finished chip inside the date field.
- Track modal tabs (Tags plain list, Collection copy fields, Status history, Discover visibility) and the shared SelectField chevron now follow the v26.10.29 layout. Browser verified against the old build; iOS and Android not verified.
