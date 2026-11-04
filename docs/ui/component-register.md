# UI component register

Use the [architecture and parity gates](../architecture/ui-modernization.md) and
[complete source ownership map](source-map.md). IDs identify behavior families,
not individual HTML elements. Slots, cells and small includes belong to their
parent family unless they acquire an independent contract. Paths below are entry
points; the map enumerates every member. Existing backend contracts remain authoritative.

## Status and maintenance

`architecture-registry.json` records universal files, platform-specific files,
shared logic and the frozen legacy baseline. Its component names and individual
web, iOS and Android evidence are checked against this register and the source
map. Use the independent acceptance criteria in
[`ui-modernization.md`](../architecture/ui-modernization.md#separate-acceptance-and-evidence):
web ownership, native candidacy, each runtime verification and production
readiness are different claims. Never infer platform verification from a build.

Every agent edit to a UI component, including copy or styling, upgrades that
component to the shared React pattern with visual and behavioral parity. Reuse or
extend shared components first. This incrementally prepares shared presentation
for eventual native iOS and Android apps and reduces a future bulk migration.
Every changed component must record ownership/migration state for each affected
surface and update the source map. An external blocker leaves the affected work
incomplete; record evidence, attempted solutions and a reopening condition and
report it explicitly.

A component is migrated on every surface that uses it, public pages (public lists,
auth and error screens) and signed-in pages alike. Check both shells (`base.html` and
`base_public.html`) and the `public_view` paths before marking a surface done, and
record any public consumer that is left behind.

- `Existing`: current implementation, not migrated.
- `Ready`: foundation validated and component assessed for migration.
- `Web Migrated`: accepted browser replacement; native verification stays separate.
- `Cross-Platform Verified`: shared implementation passed recorded web, iOS and Android checks.
- `Exception`: historical platform-specific or blocked work; descriptive only,
  never a waiver from the architecture checks or evidence that work is complete.

**Defaults for every entry below:** Status `Existing`; verification is static source
inspection only, browser migration not performed, native not tested. Test references
are available regression targets, **not executed test results**. Related work and
recurring deferrals: none recorded; attach real issue/PR links when known. The
settings-card shell is the first authorized browser pilot; native runtime verification remains open.
Ordinary unassessed components stay `Existing` rather than prematurely becoming exceptions.

When a component changes, update affected paths/contracts and add explicit fields:
`Status`, `Verification` (commands/results, surfaces, platforms/versions and limits),
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
and blockers to find remaining work. For churn, aggregate paths from
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
- Verification: `app.tests.test_sidebar_model` (props, active page, all 95 icons parse). Chromium (built-in browser, macOS): the sidebar mounts, Movies is active, Explore opens, pinning Calendar moves it and persists, a pinned list shows under Lists, saved-view reorder mode shows handles, and finishing it saved the new order on the server. A native drag, the delete confirm dialog and a phone-width open and close were not exercised. iOS and Android not tested.
- Validation targets: `src/app/tests/views/test_boosted_navigation.py`; menu/focus parity needs browser observation.

### SETTINGS-CARD — Shared settings card shell

- Purpose/usage: provider Connection instance/personal credentials and account setup, Import preferences/options, and Metadata library source controls.
- Shared runtime: body responses compare the retained head's loader/CSS versions
  with the current build and reload after a stale boosted navigation. This applies
  to private and public shells without changing existing controls or their owners.
- Implementation: universal `frontend/settings/SettingsCard.jsx` and `frontend/settings/Chip.jsx`; browser link and palette adapter `Chip.web.jsx`; `mount.jsx`, `index.js`, `webPalette.js`, `settings-card.css`; `src/users/templatetags/ui_tags.py` and `src/templates/users/components/settings_card.html`. See [usage and ownership](settings-cards.md).
- Contract: one title/badge/help/frame pattern with editable/read-only/neutral and public API tones. `Chip` shares passive/action/link styling across status badges, media pills and the provider-key link, with consistent hover/focus highlights and no text underline. `Chip.web.jsx` keeps native anchors, new-tab attributes and the CSS-variable palette while the shared chip owns action semantics. AniList supplies React-owned children; retained partial consumers keep their server body outside the header root. Existing backend permissions and CSRF remain authoritative.
- Data: presentation-only `json_script`; no credentials, server body HTML or transport in the shared React API. Shared source uses React Native primitives; `Chip.web.jsx` and `webPalette.js` supply browser links, DOM events and theme values.
- Status: `Web Migrated` shared card/chip presentation; native presentation is registered but runtime-unverified. AniList uses full React composition; Audiobookshelf uses reusable account connection and manual-import islands. Other providers retain Django body slots and setup/restore dialogs until their controls are ported. This does not migrate `FORM-CONTROLS` as a whole.
- Native mapping: `SettingsCard` takes a title, badge/info chip and React-owned children; `Chip` takes a concrete palette, optional `onPress` action and accessibility props. Links remain a web-adapter concern.
- Native placement: `ported` in `native-proof/app/surfaces/SettingsCardSlot.jsx`; it renders a provider connection card and chip on the Settings screen. Placement completion is separate from runtime evidence: iOS and Android remain unverified.
- Verification: production assets build and collect through Django; targeted Django/theme tests and Chromium focus/link checks cover the shared card and chip. Actual iOS/Android runtime remains unverified; Expo export is a compile check, not runtime evidence.
- Related work: [#1793](https://github.com/dannyvfilms/Floppy/issues/1793); user-authorized first React browser component pilot.
- Deferrals: server-owned form bodies retire through scoped control ports after parity checks; native acceptance awaits actual iOS/Android runs and a native theme/transport boundary. Broader performance evidence remains required before larger component adoption.

### FORM-CONTROLS — Fields, popovers, dialogs and feedback

- Purpose/usage: repeated buttons, inputs/selectors/tabs, confirmations, help/errors and notifications across forms, settings, filters and modals.
- Implementation: [app-wide React controls](react-components.md), `frontend/ui/controls.jsx` and `controls.css`, consumed by provider Overview/Connection/Import/Activity. Legacy consumers include inline templates, `src/templates/users/components/info_tip.html`, `form_save_bar.html`, allauth fields, base modal/toast infrastructure and `src/static/js/keepPopupsOnScreen.js`.
- Contract: labels, selected/disabled/busy states, errors/CSRF, click-away/Escape and existing focus behavior, viewport-safe popups, dirty-save live announcements. A universal modal focus trap is not established.
- Data: owning Django forms/errors/messages, Alpine state and response events; feature endpoints retain action semantics.
- Reuse/blockers: use shared `SelectField` for preference forms and `FilterDropdown` for Lists-style filter toolbars. Both share keyboard/typeahead/dismissal behavior but retain distinct appearances. Legacy dropdowns remain inline until their UI is reworked; native behavior still needs proof.
- Scrolling rows: `ScrollRow` in `controls.jsx` is the one horizontal scroll container for tabs and chip filters (no wrap, hidden scrollbar, a fade on the side with more to see, the selected child scrolled into view). `Tabs` (provider pages) and `FilterChips` (Discover media types, mounted by `mountFilterChips.jsx` from the page's Alpine `selectedMedia` and `switchMedia`) both use it. Other wrapping chip rows (details, person and studio pages, tags) are not migrated and keep their markup.
- Validation targets: owning feature tests, `src/users/tests/views/test_preferences.py`; general accessibility interaction coverage unverified.
- Status: `Web Migrated` for shared React buttons (see BUTTON for the template adapter and its remaining consumers), labeled fields/selects, chips/toggle chips, tabs, dialogs and card grids, used throughout AniList. Other consumers retain legacy controls until reworked. Reuse these components by element, without requiring a whole provider/page port. Provider-specific authentication and transport remain in feature code.
- Verification: both provider Connection dialogs opened and dismissed with Escape, including focus return and setup-dialog Tab/Shift+Tab wrapping, in Chromium 151 on macOS at 1440×1000 and 390×844 in system light and dark. Native and assistive-technology testing not performed.
- Verification: 17 Chromium tests pass across all AniList tabs, six theme states and phone/tablet/desktop widths. Public/private switching via pointer and keyboard preserves entered username and existing credential gating; surface borders, inset arrows and purple actions are checked in light/dark. Shared toggle/dialog/link chips show focus rings for keyboard navigation only; dialog focus restoration is preserved. Native and assistive-technology verification remain pending.
- Related work: [provider consolidation #1793](https://github.com/dannyvfilms/Floppy/issues/1793). Broader legacy adoption follows component redesigns; the shared browser controls are available now.

### TOKENS — Theme, typography, motion and icons

- Purpose/usage: all surfaces' visual system.
- Implementation: `src/static/css/input.css`, generated `main.css`, `src/templates/app/icons/`, bundled fonts, `src/users/appearance.py`; Tailwind 4/CSS variables.
- Contract: explicit presets/custom and system light/dark, accent contrast, responsive layout and reduced motion; follow [theming](../architecture/theming.md).
- Data: user appearance configuration, media vocabulary in `src/app/config.py`, existing Tailwind build.
- Reuse/blockers: share semantic values; native font metrics, SVG, CSS units/selectors and safe areas require explicit equivalents. No independent palette.
- Validation targets: `src/app/tests/test_theme_tokens.py`, `src/users/tests/views/test_appearance.py`; native visual/accessibility checks outstanding.

### ARTWORK-LOADING — Image loading and fallback

- Purpose/usage: cards, rails, posters/backdrops and detail images.
- Implementation: `src/static/js/artwork-loading.js`, `image-fallback.js`, lazySizes; `src/templates/app/components/home_artwork_poller.html` is the deferred shelf consumer.
- Contract: no blank/broken art, preserved aspect/fallback provenance, lazy/deferred refresh; display fallback does not overwrite stored artwork.
- Data: server artwork projection/cache URLs and Home cover state in `src/app/views.py`.
- Reuse/blockers: image states/geometry reusable; observers/error hooks/polling are web adapters. Preserve [cover security](../architecture/local-covers.md).
- Validation targets: `src/app/tests/test_media_card_contract.py`, `src/app/tests/test_game_artwork.py`; native caching unverified.

### ASYNC-STATE — Cache/loading refresh lifecycle

- Purpose/usage: Discover, History and Statistics refresh/pending/error state.
- Implementation: `src/static/js/cache-updater.js`, owning inline template pollers/HTMX fragments.
- Contract: bounded retries/timeouts, offline/online recovery, exit cleanup and useful stale/error/loading display without duplicate pollers.
- Data: cache-status endpoint in `src/app/views.py`, feature task/cache state.
- Reuse/blockers: potentially share transitions; browser lifecycle/task transport need adapters. This is not offline synchronization.
- Validation targets: `src/static/js/cache-updater.selfcheck.mjs`, owning feature tests; native background behavior unverified.

### SPINNER — Loading ring

- Purpose/usage: the small spinning ring shown while an HTMX search, infinite-scroll page or library lookup is in flight.
- Status: `React-owned` for the existing ring consumers, with Django fallback retained. Browser verification for this implementation: Chromium on macOS at phone width exercised real public and private Django list pages, visible rotating indicators during delayed HTMX search, and successful swaps. An isolated host also checked 12/20px sizes, thin/regular borders, muted/white/accent colors including Tailwind oklch, animation, theme mutation, decorative `aria-hidden`, and synthetic HTMX load/cleanup events. On the private desktop list, boosted navigation cleaned up the root and back navigation remounted it. Other browser engines were not exercised in this revision. iOS: Expo Go on iPhone 15 Pro iOS 17.2 simulator rendered 12/16/20 point rings in three colors and separate frames showed movement; VoiceOver and reduced motion were not exercised. Android: Expo Go 58.0.5 on a Pixel 7 Android 15 API 35 arm64 emulator rendered 12/16/20 dp white, accent and muted rings; separate frames showed movement. Accessibility-tree capture was killed twice and the accessibility service dump timed out; TalkBack, reduced motion and exact animation timing were not exercised.
- Implementation: universal `Spinner` in `frontend/ui/Spinner.jsx` takes a concrete color and size; `frontend/ui/SpinnerTheme.web.jsx` translates the existing size and tone interface and observes document theme changes. The web ring is decorative, and `.ui-spinner` in `controls.css` preserves the Django fallback; `frontend/ui/mountSpinner.jsx` web adapter registered as `data-spinner-root` in `frontend/settings/index.js`, and the `{% spinner size tone %}` tag (`users/templatetags/ui_tags.py`, `users/components/spinner.html`). The server markup inside the host preserves the ring as a fallback if the module fails. The host is `display: contents`, so it adds no box. A host nested inside another island (the header search form) is skipped by the loader; that island renders its own `Spinner`.
- Consumers: Movies/library list, Collection list, Person filmography, List detail (search indicators and load-more), Smart list detail, Custom lists hub, Smart rules builder, Add item, Recommend item, Library move panel and its results, header barcode scan (React `GlobalSearch` and `base.html` fallback), and the React `ListsForm` loading states. Public list pages use `base_public.html`, which loads the same island bundle.
- Left on legacy, with reopening condition: `users/about.html` (SVG ring with its own look; reopen when About is migrated), `progress_changer.html` (icon swapped by `htmx-indicator`; reopen with the quick progress bar), and the Alpine `:class="{ 'animate-spin': loading }"` refresh icons in detail action buttons, music album/artist pages and Statistics (they rotate an icon, not a ring; reopen when those buttons are ported).
- Native mapping: the shared animated ring takes a size and concrete theme color; native callers supply their palette.
- Validation: `users.tests.test_spinner_tag`, `users.tests.test_spinner_browser` (Playwright), `lists.tests.test_list_detail_filters` (fast schema), architecture checks and tests, web asset build/check, and Expo web/iOS/Android export. The export does not verify native runtime behavior.

### BADGE — Pill label

- Shared migration: `Badge` in `frontend/ui/Badge.jsx` is shared presentation;
  `BadgeTheme.web.jsx` adapts existing web tones, sizes and navigation. Existing
  Django fallback and unrelated legacy pills remain. Native nowrap measures full
  text so narrow containers do not truncate it.

- Purpose/usage: the small rounded label for genres, release types, statuses and flags.
- Status: `Partial / coexisting`: the 21 static pill sites use the shared Badge; other handwritten pills below remain. Chromium compared all four sizes and 11 tones, plus a narrow nowrap link, against the fallback in 13 theme states; geometry and rendered colors matched within test tolerances, and keyboard focus, hover, link targets and synthetic HTMX cleanup/remount were checked. A real podcast detail page mounted its genre badge at phone width. iOS 17.2 simulator and Android 15 Pixel 7 emulator rendered all four sizes, switched light/dark palettes, preserved a full narrow nowrap label and activated a link. iOS exposed a link in its accessibility tree; Android exposed a focusable clickable action and one full label after the animated spinner examples were hidden. VoiceOver and TalkBack were not exercised; native testing used indigo and outline palettes, not every production tone.
- Implementation: shared `Badge` in `frontend/ui/Badge.jsx` with web theme/link adapter `BadgeTheme.web.jsx`, re-exported by `controls.jsx`. The Django tag and `mountBadge.jsx` retain the same contract and fallback classes in `controls.css`; label data stays plain text and Django restricts `href` to local paths or queries. The host remains `display: contents`; nested hosts keep their server fallback.
- Consumers: genre tags on podcast show, music artist, album and track detail, episode details and the detail secondary content block (links); the library table Genres cell (links, `nowrap`); music album type, year and media-type pills; list add and recommend previews (violet genres); arr library request status; Seerr request status; release notes Installed and Newer than yours; onboarding Metadata suggestion badge; metadata mapping status (Mapped, Mapping needed).
- Left on legacy, with reopening condition: music album codec, bitrate and channels pills (they hold an SVG icon, which cannot be passed as props; reopen when `Badge` gets an icon slot from the shared icon set); `media_metadata_panel.html` source pill (11px, `py-0.5`, one site; reopen with the metadata panel port); `calendar_list.html` Today pill (`text-sm` with `px-2`, one site; reopen with Calendar); person and studio filter links, `tag_index.html` and `discover.html` chips (links or buttons that belong to the filter chip family); `episode_row`, `detail_episode_track_button`, `detail_episode_collection_button` (action buttons); `detail_tag_preview.html` (tag colours come from stored tag data as class strings); `game_lengths_section.html` (hover and tracked-letter variant); `episode_ordering.html` and `match_fix.html` (state-dependent classes); `oauth_applications.html`, `progress_breakdown.html` (uppercase micro-label), `appearance.html` (segmented buttons). Each reopens when its page is ported or when its variant is added to `Badge`.
- Native mapping: shared `Text` and accessible `Pressable`; caller supplies palette styles and an `onPress` navigation action.
- Validation: `users.tests.test_badge_tag`, `users.tests.test_badge_browser`, architecture checks and tests, UI assets, and Expo web/iOS/Android exports.

### BUTTON — Solid action button

- Purpose/usage: the solid indigo (primary) or red (danger) button, the surface "Load more" button and the red text button that templates used to write by hand for form saves, submits and the odd htmx action.
- Status: `Partial / coexisting`. 65 sites in 22 templates are on the shared `Button` (61 plain or form-submit, 4 htmx: the two History Load more branches and two podcast history Delete buttons); about 156 hand-written solid indigo or red `<button>` tags remain in 80 templates, plus roughly 1,000 other buttons of other looks. The shared tag now mounts universal presentation through a browser platform implementation. The older `Button` in `frontend/ui/controls.jsx` and its React-island consumers remain legacy (see below). Browser verification: not re-run after this port; the web implementation is built by esbuild but was not compared in a browser. Native iOS and Android: not verified; the Expo export is a build check only.
- Implementation: universal `frontend/ui/Button.jsx` uses React Native `Pressable`/`Text` with `label`, `tone` (primary, danger-solid, danger-deep, surface, ghost-danger), `size`, `width`, `disabled`, `busy`, `onPress`, `accessibilityLabel` and concrete palette values. Browser behavior stays in `frontend/ui/Button.web.jsx`: it renders the real `<button>` or `<a>` with the existing `.ui-button` classes, form submit types, links and allowed attributes. `frontend/ui/Button.native.jsx` exposes the same contract through the universal component. `frontend/ui/mountButton.jsx` mounts the web implementation as `data-button-root` from `frontend/settings/index.js`; the `{% button label tone size width submit= disabled= %}` tag (`users/templatetags/ui_tags.py`, `users/components/button.html`) and its server fallback are unchanged. The label is plain text, translated with `_("...")`. Allowed attributes pass through unchanged: `id`, `name`, `value`, `form`, `formaction`, `title` and any `hx_*`, `data_*` or `aria_*` (written with `_`, rendered with `-`; `hx-on*` is refused because it runs inline script). The server markup inside the host is the same `<button>`, so a form submit still submits and htmx still works if the script fails. The host is `display: contents`, so it adds no box. When React replaces the button it calls `htmx.process` on the host so htmx binds the new node. A host nested inside another island is skipped by the loader and keeps the server button. Radius follows `--theme-radius` and transition timing follows the theme motion tokens, as the old utility classes did. Keyboard focus keeps the browser's default ring, as the old buttons did; the shared 2px indigo ring stays on the AniList and provider buttons.
- Consumers: Account (authenticator and recovery codes, delete account), Media Cards settings, Custom lists (Trakt credentials, import), Provider settings bodies (`provider_import.html`: Connect, Sync now, Disconnect, Save and add-instance forms), Jellyfin and MAL sync, instance and personal credentials, TMDB proxy, reading-server modal, media type provider modal, onboarding (media types, metadata, import status, connect Trakt), OAuth device, match fix, collection modal and entry summary, music track notes, History "Load more" (htmx), podcast history Delete (htmx, ghost red).
- Left on legacy, with reopening condition:
  - `frontend/ui/controls.jsx`'s `Button` and its React-island consumers (`mountBulkToolbar.jsx`, `mountBulkActions.jsx`, `ListsForm.jsx`, `providers/Activity.jsx`, `Directory.jsx`, `FileImport.jsx`, `SettingsForm.jsx`, `Import.jsx`, `Credentials.jsx`, `AccountConnection.jsx`, `SetupGuide.jsx`, `Metadata.jsx`, `ImportPreferences.jsx`). Its `Dialog` close button is a frozen legacy statement, so the module cannot replace the export with a same-name re-export without changing another legacy declaration. Reopen when `Dialog` moves to shared presentation and the module can re-export the registered Button.
  - Buttons with Alpine bindings (`@click`, `x-show`, `:class`, `:disabled`; about 880 tags): the host carries `x-ignore`, and Alpine attribute names such as `@click` cannot be set from React. Reopen when the owning dialog or toolbar is ported so its state lives in React, or when the adapter gets an event contract.
  - Buttons that htmx swaps in place of themselves (`hx-swap="outerHTML"` on the button: the list and tag Add/Remove toggles): htmx would replace a React-managed node. Reopen with a React toggle that owns its own request.
  - Buttons with an SVG or an included icon (about 26 solid ones, plus every icon-only button): an icon cannot be passed as props. Reopen when `Button` gets an icon slot from the shared icon set.
  - Buttons whose attribute values need template composition (`formaction="{% url ... %}?next=..."` in the album, artist and podcast track modals and list form, `form=` in the episode watch row) or whose label is state-dependent markup (`{% if tracker %}Update{% else %}Add{% endif %}`, "Add instance" and "Sync now" variants in `provider_import.html`, `fill_track.html`, `fill_track_song.html`, onboarding services): reopen when the adapter accepts composed attributes, or when those forms are ported.
  - Look variants not yet in `Button`: sizes with `h-10`, `w-48` or `flex-1` (Connect buttons in `provider_import.html`), `rounded-lg` with `hover:bg-indigo-500`, `text-xs` compact buttons, the tracker Delete (red when a tracker exists, grey when not), the segmented buttons in `appearance.html`, tab and chip buttons. Each reopens when its variant is added or its page is ported.
  - Links styled as buttons: the browser implementation covers `href`; no template site has moved yet.
- Native mapping: the universal `Button` uses `Pressable` and `Text`; callers supply concrete palette values and an `onPress` action instead of transport. `native-proof/app/surfaces/ButtonSlot.jsx` renders the primary Save, surface Load more and solid danger actions in the Settings and Library screens.
- Native placement: `ported` in `native-proof/app/surfaces/ButtonSlot.jsx`. The placement is complete for the three tones it demonstrates; browser, iOS and Android runtime behavior remain unverified.
- Validation: `users.tests.test_button_tag`, `npm run check:ui-architecture`, `npm run test:ui-architecture`, `npm run check:ui`, and the Expo export. Browser and device runtime were not exercised.

### WEB-UTILITIES — Clipboard, installation and static service worker

- Purpose/usage: copy controls, install feedback and cached static assets.
- Implementation: `src/static/js/copy-item.js`, `serviceworker.js`, install hooks in `base.html` and `users/about.html`.
- Contract: feedback/availability, cache version/cleanup and request/auth boundaries. Static caching does not provide offline tracking.
- Data: DOM values, browser capabilities, service worker route in `src/app/views.py`.
- Reuse/blockers: copy intent shareable; install/service worker stay web-specific. Assess explicit exceptions when migrating a consumer.
- Validation targets: `src/app/tests/views/test_service_worker.py`, `src/users/tests/views/test_about_install_integration.py`.

### ERRORS-DOCS — Error/recovery and API documentation pages

- Purpose/usage: 400/403/CSRF/404/500 and API documentation surfaces.
- Implementation: root error templates, `src/templates/includes/error_report_panel.html`, `src/templates/api/docs.html`.
- Contract: safe diagnostic/report text, useful recovery links, permission boundaries and usable error documents without normal context or loaded app JS.
- Data: `src/app/error_views.py`, error context and API schema routes.
- Reuse/blockers: error presentation shareable; server error documents/API explorer are web surfaces.
- Validation targets: error view tests under `src/app/tests/`; interactive/native parity unverified.

## Library, discovery and media presentation

### MEDIA-CARD — Canonical card and metadata lines

- Native implementation: `frontend/ui/MediaCardView.jsx` is the universal native card shell:
  poster, square, landscape and row layouts, artwork with a fallback chain, status
  and media-type chips, corner chips, progress, title and alternative title,
  subtitle lines, score and a rating affordance, plus read-only and selectable
  states. `MediaCardActions` adds the action overlay and row buttons (track,
  lists, history, Discover plan/hide action specs and list reorder controls) with
  explicit `onAction`, `onReorder` and reveal callbacks; `MediaCardActionRow` and
  `MediaCardActionButton` are its named exports. `MediaCardActionHost` is the
  native popup shell for that callback contract. It consumes the same
  `card_model` shape, action specs and labels as the web card.
  `native-proof/app/surfaces/MediaCardSlot.jsx` renders it with realistic demo
  library items on Home, Discover and Library.
- Native status: `in_progress`. The existing web `MediaCard.jsx`,
  `mountMediaCard.jsx` and `ModalHost.jsx` remain the active browser adapter and
  popup host. The universal action presentation and callback contract are in
  place, including touch/hover reveal and selection rendering. Still outstanding:
  native Track and Add-to-lists form bodies with their server transport and CSRF,
  Discover plan/hide and list-reorder writes (the drag handle is visual only; a
  native drag gesture is not ported), the shared bulk-selection store and toolbar,
  and real iOS/Android runtime evidence. Expo exported web, iOS and
  Android bundles, but no native runtime was exercised in this change.

- Purpose/usage: library, Home, related, search, Discover, lists, collection, credits and tier/group surfaces.
- Implementation: `src/templates/app/components/media_card.html`, `card_lines.html`, `media_card_list.html`, `src/app/card_surfaces.py`, template tags.
- Contract: declared surface/tag, viewer rating/status, aspect ratios, obfuscation, hover/touch actions, public/read-only/bulk states and stable OOB status wrappers.
- Data: `media_list_entries_for_items`, surface flags, card configuration and server projections.
- Reuse/blockers: highest leverage; [media-card contract](../architecture/media-card.md) authoritative. Replace consumers and response slots, never create an unrelated second card system.
- Status: `React-owned` for every card the `media_card` tag, `history_card_react` and `media_row_react` render. All 14 surfaces in `card_surfaces.py` set `react_card=True`; History (`history_card.html`) and the Search list row (`media_card_list.html`) use the same `MediaCard.jsx` (poster, square, landscape and `layout: row`). The artwork link, corner chips, progress bar, title and alternate-title tooltip, subtitle lines (including a credit's role line), status chip, rating button with its star popup, hover buttons (track, lists, history, Discover plan and hide, list reorder and drag handle), touch tap-to-reveal and bulk-select checkbox are all React (`MediaCard.jsx`, `mountMediaCard.jsx`, model in `media_card_model.py`). The track and lists popups open in the page's one React host (`ModalHost.jsx`); the cards carry no Alpine and no popup markup. `media_card.html` is now a shell: the card wrapper classes (themes and title settings still key off them), the props `<script>`, and a first-paint poster and title link inside the React host that React replaces on mount. The legacy server body, its Alpine fallback and the empty status, overlay and rating slots are deleted. `app.tests.test_media_card_contract.MediaCardInventoryTest` fails if a surface opts out of React, if the template regrows a legacy body, or if any template draws `media-card` markup that is neither the tag nor a documented exception.
- Remaining consumers and retirement: (1) Bulk select is still read from the page's Alpine scope (`selectMode`, `isItemSelected`, `toggleItemSelected`) by `mountMediaCard.jsx`. It retires when the Library bulk toolbar (`bulkSelection.js`, `mountBulkToolbar.jsx`, owned by another change in flight) publishes selection through a shared store; reopen then. (2) The save and score responses still send server fragments out of band (`media_card_status_chip.html`, `media_card_rating_oob.html`) for pages that render those slots; a React card ignores the swap (`data-react-owned`) and updates from `floppyCardUpdate`. They retire with the detail-page chips. (3) Documented exceptions that are different kinds of card, not this one: person and cast cards, Statistics highlights and the repeat-player strip, Now Playing, list index cards, and the music album and artist grids (they need an Album or Artist, not an Item). They are listed with reasons in `DOCUMENTED_EXCEPTIONS` in the contract test; reopen if a media item is ever drawn there. (4) The Search list row keeps its `meta` slot (server-rendered per-type metadata) inside the React host.
- Native blockers: the action presentation is ported, but the session-backed Track and Add-to-lists forms, Discover plan/hide and list-reorder transport (including a native drag gesture),
  the bulk-selection store/toolbar and iOS/Android runtime evidence remain. An Expo export is only a compile check. The web DOM card remains the behavior source until those adapters exist.
- Fixed while proving it: a credit card lost its role line (for example "Developer, Publisher") once React took over; the track popup was unmounted the moment its form submitted, so htmx fired the save response (card refresh, toast) from a detached form and cards never updated after a tracker save (`ModalHost.jsx` now waits for the request); and a touch card hid its buttons again after its own popup was used.
- Browser verification (Chromium, built-in browser pane and Playwright, macOS, throwaway database and test login): Library grid (movie, game, book), Home, History, Collection, custom list grid, tier board and list table at desktop (1024 and 1280) and phone (375 and 390) widths, light and dark (system theme driven by the OS setting, plus the explicit `light` and `dark` classes). Before and after builds compared on 36 surface, width and theme combinations: 0.0% differing pixels and identical card geometry on all 36; the only DOM differences are the removed empty slot wrappers and the timing of the async release-year fill. Interactions exercised: tracker popup open and save with live card refresh, lists popup add, rating popup and score change, touch tap-to-reveal, bulk select, status chip and no native `<select>` in any card. Not exercised in a browser (no provider network in the test setup): Search (card and list row), Discover and hidden Discover, detail-page related and seasons cards, credit and group surfaces, modal search picker, list recommendations, smart lists, the media-type chip and alternative-title tooltip on a real title. Those are covered by `app.tests.test_media_card_contract` and `test_media_card_model`, which render every surface. Other theme presets (Dracula, Nord, Gruvbox, OLED, Glass, Custom) were not opened. iOS and Android: not tested.
- Validation targets: `src/app/tests/test_media_card_contract.py`, `src/app/tests/test_media_card_model.py`; complete native/consumer matrix outstanding.

### POPUP-HOST — Shared popup host, Add-to-lists form and Track form

- Purpose/usage: one host (`ModalHost.jsx`, mounted once from `base.html`) opens the popups that tracking actions need. Callers send a `floppy-open-modal` event with `{modal, url, vals, target, labels}`.
- Implementation: `frontend/ui/ModalHost.jsx`, `ListsForm.jsx`, `modal-forms.css`; `lists_modal_spec` in `src/app/media_card_model.py`; the `lists_modal_click` template tag in `app_tags.py`.
- Contract: `lists_modal` answers `?format=json` with a form model (item, lists with `hasItem` and tags, tag list, toggle URL, CSRF token); `list_item_toggle` with `format=json` answers `{success, hasItem}` or `{success:false, error}` (403 smart list, 404 stranger, 500/503 failure). Permissions, smart-list rule, retries, activity log and error text stay in the views. Labels travel in the open event, translated by the server.
- Status, Add-to-lists form: `React-owned` (`ListsForm.jsx` with `SelectField`, `Button`, `Spinner`; its own overlay with `role=dialog`, Escape, overlay click, focus into the dialog and back). Consumers moved to the host: the card hover button (grid, History, Search row) and 10 legacy buttons (`detail_action_buttons`, `detail_row_actions`, `detail_music_album`, `detail_music_track_actions`, `music_album_detail`, `episode_details`, `comic_issue_details`, `podcast_episode_list`, `history_card`, `media_card_list`). Their private Alpine `listsOpen` popups are deleted.
- Status, Track form: `Legacy`, not migrated in this change. Blocker (evidence): the Track popup is not one form. `fill_track.html` is a seven-tab shell (General, Tags, Metadata, Collection, Episode plays, Status history, Discover) built from Django model forms that differ by media type, with three more variants (`fill_track_song.html` 13 KB, `fill_track_episode.html`, `fill_track_episode_bulk.html`), roughly 83 KB of included Alpine templates (date-time picker 11 KB, metadata panel 34 KB, collection fields, notes editor), a 1,461-line builder (`track_modal_views.py`) and 2,399 lines of tests. Its save views answer with htmx out-of-band fragments (status pill, score chip, progress card, notes) and `HX-Trigger` events, so a React form must keep posting through htmx. About 34 templates still own a `trackOpen` popup.
- Reopening condition and plan: port in this order, each its own change with browser proof: (1) a generic Django-form-to-JSON model for the General tab fields plus React date-time picker and notes editor, submitting with `htmx.ajax` so the existing responses keep working; (2) song and episode variants; (3) Tags, Collection, Episode plays, Status history, Discover tab bodies; (4) replace the `trackOpen` popups. Reopen when someone can take step 1.
- Remaining consumers and retirement: `fill_lists.html` is still returned for non-JSON requests; it retires with the existing `ListsModalViewTests` HTML assertions once the Track form leaves htmx popups, or sooner if no caller needs it. `list_item_button.html` is the same.
- Browser verification (Chromium, built-in browser pane, macOS, throwaway database and test login): opened from a Movies grid card (desktop, dark) and a movie detail page (phone width, light); added a list (spinner, then "On 1 list" and Remove), filtered by tag, forced a network failure (inline error, list unchanged), Escape closed it. Not checked: history/episode/table-row entry points, other theme states beyond dark and light, a screen reader. iOS and Android: not verified.
- Validation targets: `lists.tests.test_views.ListsModalViewTests`, `ListItemToggleTests`, `app.tests.test_media_card_contract`.

### RATING — Score display and picker

- Purpose/usage: cards, details, children and music scores.
- Status: `Partial / coexisting`. The detail personal score chip and its rating popup are React-owned through the shared `RatingChip` and `RatingStars`. The media card's rating button and popup are also React-owned (`CardRating`). Episode/track/row rating buttons, music artist/album pages, the comic issue page and the provider score chips (TMDB/Trakt/IMDb/MAL/IGDB/OpenCritic) remain legacy Alpine/HTMX. Native iOS and Android: not verified. Browser: not exercised in this change; the Expo export and web bundle compile.
- Implementation: shared RNW `frontend/ui/RatingChip.jsx` and `frontend/ui/RatingStars.jsx`, the web adapters `frontend/ui/mountRatingChip.jsx` and `frontend/ui/mountRatingStars.jsx`, `frontend/ui/RatingStarIcon.web.jsx` / `.native.jsx`, the `rating_chip` and `rating_stars` tags (`users/templatetags/ui_tags.py`), `rating_chip.html`, `rating_stars.html` and `rating_picker.html` (Alpine wrapper for the remaining consumers). The detail chip keeps its existing server markup as a progressive fallback; the web adapter hides it on mount. Legacy: `detail_episode_rating_chip.html`, `detail_row_rating_button.html`, `media_card_rate_button.html`, `media_card_rating.html`, OOB/score-chip/derived-TV fragments and provider score chips.
- Native placement: `ported` in `native-proof/app/surfaces/RatingSlot.jsx`, which renders the detail score chip and popup. Placement is complete for that surface; iOS and Android runtime evidence remains unverified.
- Detail chip consumer: `detail_score_chip.html` mounts the shared chip with the viewer scale, the manual and derived-TV values, coverage, the existing CSRF token and the existing `update_media_score` / `update_podcast_show_score` endpoint. The adapter posts through `htmx.ajax` so the server's out-of-band chip and card swaps still apply. The universal chip also renders the carousel card layout; the web adapter chooses it from the existing responsive/carousel state.
- Picker consumers still legacy: media card rate button markup returned for OOB swaps, episode/track/row rating buttons, music artist/album pages and the comic issue page. They keep the Alpine popup wrapper and the shared star-row island until each surface is ported.
- Podcasts rate per show: chip and list cards post to `update_podcast_show_score` (tracker id), not `update_media_score` (episode plays) (#1830).
- Provider score chips are a different subfamily: read-only provider values and source links, not the viewer's personal score. They stay legacy and are not covered by this port.
- Retirement: the Alpine popup wrappers and direct-rating stars in `detail_score_chip.html` retire when the remaining consumers move to `RatingChip`. The server fallback in the detail chip is intentional progressive enhancement and retires only with the fallback policy.
- Contract: viewer scale (5/10), empty/edit states, hover preview, toggle-to-clear, pressed/focused styles, CSRF writes, popup keyboard Escape and click-away dismissal, and OOB/events; derived score/coverage differs from direct score.
- Data: `src/app/score_views.py` and server score projections.
- Verification targets: `src/app/tests/views/test_score_views.py`, `src/app/tests/test_podcast_show_rating.py`, `src/app/tests/test_derived_tv_ratings.py`, card contract tests.

### LIBRARY — Result composition and media grouping

- Purpose/usage: media library grid/table and game/artist/album groups.
- Migration state: server-owned results coexist with the fully React-owned ALPHABET
  sibling; internal grids/cards/tables retain their existing ownership and behavior.
- Implementation: `src/templates/app/media_list.html`, `src/templates/app/components/media_grid_items.html`, grouped-game fragments.
- Contract: bounded pagination, sort/group/view selection, statusless rows, public sharing and refresh with distinct item/tracking identity.
- Data: `src/app/media_list_views.py`, `media_list_entry_grouping_views.py`, `src/app/library_query/`.
- Reuse/blockers: share result model; keep page-specific composition and bounded server queries. REST serializers require separate parity checks.
- Validation targets: `src/app/tests/views/test_media_list_entry_grouping.py`, `src/api/tests/test_media_list_page_cost.py`; [query contract](../architecture/library-query.md).

### ALPHABET — Starting-character filter

- Status: `Web Migrated` across the surfaces below. Native iOS and Android are not verified.
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

### FILTERS — Filter state, menus and saved views

- Purpose/usage: library/lists, History, Calendar and Home configuration where included.
- Implementation: universal `frontend/ui/FilterBar.jsx` (media type, status, sort, view, range and saved-view sheets); browser intent bridge `frontend/ui/mountFilterBar.jsx`; server toolbar `src/templates/app/components/filter_menu.html`, `filter_form.html`, `filter_toolbar.html`, `filter_range_panel.html`, `filter_toolbar_scripts.html`, `sidebar_saved_views.html`; state `src/static/js/libraryFilterState.js`, `savedViews.js`.
- Contract: normalized rules, clear/default/relative/multi-value ranges, selected/disabled/busy states, accessible trigger and option labels, responsive sheet layout, sort direction, layout view and saved-view selection. `FilterBar` receives normalized state and options and emits intents; it does not parse URLs or own transport. The browser adapter mirrors the page's Alpine state, writes intents into the existing hidden form and refreshes through `applyFilterChange`, preserving the server fallback and one runtime owner.
- Data: owning view catalogs, shared library query, authoritative `src/app/media_list_filters.py` parser, `src/lists/smart_rules.py`, saved-view endpoints in `src/users/views.py`. The shared parser is not duplicated in JavaScript.
- Status: `Partial / coexisting`. `FilterBar` is the native-compatible presentation and is rendered on the Library screen of the native shell; web library/list/History/Calendar toolbars remain the existing server/Alpine implementation. No web consumer was replaced because browser parity for the full menu surface is not yet proven.
- Reuse/blockers: strong state reuse; preserve per-surface availability. URL/history, forms, focus management, localStorage and SortableJS remain web boundaries. Retirement requires mounting the browser adapter on a surface, proving menu/range/saved-view parity in a browser, and then removing that surface's Alpine panes while retaining the server fallback.
- Verification: Expo export --platform all compiles the shared bar through the native shell; no simulator/emulator run was performed. The browser adapter and Expo web export compile; no browser interaction pass was performed. `app.tests.test_media_list_filter_parser`, `lists.tests.test_list_detail_filters` and `lists.tests.test_smart_list_semantics` cover the authoritative parser and list filtering.
- Validation targets: `src/app/tests/test_media_list_filter_parser.py`, `src/lists/tests/test_list_detail_filters.py`, `test_smart_list_semantics.py`.

### TABLES — Configurable media tables and cells

- Purpose/usage: library/list/collection tables and artist/album variants.
- Implementation: `src/templates/app/components/table_items.html`, column menu/config scripts, `cells/`; list/collection row consumers in map.
- Contract: selected/order/persisted columns, sort, score/status/units, responsive scrolling/actions and bounded rows.
- Data: `src/app/columns.py`, result projections and column preference endpoints.
- Reuse/blockers: descriptors/formatting shared; accessible desktop tables and native list presentation may remain separate. Cells are child implementations, not independent units.
- Validation targets: `src/app/tests/test_columns.py`, `test_media_list_columns_browser.py` (slow/browser gates).

### BULK — Multi-item selection and actions

- Purpose/usage: library and lists.
- Implementation: `src/static/js/bulkSelection.js`, `src/templates/app/components/bulk_selection_toolbar.html`, list bulk controls.
- Contract: identity/count/mode, eligibility, busy/error/reset/refresh and per-user permission checks.
- Data: `src/app/bulk_action_views.py`, `bulk_actions.py`, list action handlers.
- Reuse/blockers: selection/toolbar reusable; action capabilities differ by surface. Public views must stay read-only.
- Validation targets: `src/app/tests/views/test_bulk_actions.py`, `src/lists/tests/test_bulk_actions.py`.

### SEARCH — Global autocomplete, results and barcode input

- Purpose/usage: header/page search and parent TV/season selection.
- Implementation: universal `frontend/ui/GlobalSearch.jsx`; browser adapter `frontend/ui/GlobalSearch.web.jsx`; mount `frontend/ui/mountGlobalSearch.jsx` and `global-search.css`; server props from `app_tags.global_search_react`; JSON suggestion contract in `search_views.search_suggestions` (`format=json`). `src/templates/app/search.html`, search parent fragments, `searchAutocomplete.js`, `searchShortcut.js` and `barcode-scanner.js` remain the results, fallback and browser-decoding paths. Native placement is `native-proof/app/surfaces/SearchSlot.jsx`.
- Contract: input, media-type menu, loading/empty/error suggestion states, active-descendant Arrow/Enter navigation, the search-online footer and two-character minimum. The web adapter keeps the GET search action, URL/history, session cookies and the file-picker/ZXing barcode flow; the universal component exposes barcode entry as a platform callback. The no-JS `<form>` fallback stays inside the host.
- Data: the JSON path returns `{suggestions: [{id, title, subtitle, image, url}]}` only; presentation labels arrive through the existing `json_script` props. No server HTML reaches universal presentation.
- Reuse/blockers: result pages, parent TV/season pickers and provider result contracts remain legacy. A native camera/photo adapter is still required before native barcode scanning works; the shell reports that entry point as unavailable.
- Status: `Web Migrated`. The header search form, media-type menu and saved-library suggestion list are React-owned through the shared component; the server form and htmx suggestion fragment remain only as the no-JS/fallback path. Search result pages and parent selection are unchanged.
- Verification: `app.tests.test_search_suggestions` (13 tests), `app.tests.test_global_search_props`, `app.tests.views.test_media_search` (37 tests), `node src/static/js/barcode-scanner.selfcheck.mjs`, `npm run build:ui`, `npm run check:ui`, `npm run check:ui-architecture`, `npm run test:ui-architecture` and `uv run --no-sync ruff check src` passed. Chromium via Playwright on macOS exercised signed-in Discover at 1280×900 and 390×844: the form mounted, JSON suggestions and the active descendant worked, the type menu opened, choosing a type submitted the matching GET URL, a suggestion opened its detail route, the book barcode picker opened, and an unreadable image showed and dismissed the error toast. Light and dark system palettes resolved distinct colors. The Expo export compiled web/iOS/Android; no iOS or Android runtime was exercised.
- Retirement condition: delete the server form and htmx suggestion binding when the no-JS fallback is no longer required; the results page retires when its own bounded data contract is ported.
- Validation targets: `src/app/tests/test_search_suggestions.py`, `src/app/tests/views/test_media_search.py`, barcode selfcheck.

### RAILS — Horizontal scrolling and load more

- Purpose/usage: Home, cast, recommendations and related rows.
- Implementation: `frontend/ui/Rail.jsx` is the universal rail and `frontend/ui/Rail.web.jsx` is its browser behavior adapter. `src/templates/app/components/_scrollable_row.html`, `_scrollable_row_js.html` and `src/static/js/horizontal-scroll.js` remain the web implementation. The native shell renders demo rails in `native-proof/app/surfaces/RailsSlot.jsx`.
- Contract: heading/collapse state, arrows/drag/touch, suppress post-drag clicks, bounded load-more, stable art anchors and listener cleanup. `Rail` takes `items`, `renderItem(item, index)`, a stable `itemWidth`, `onLoadMore`/`hasMore`/`loadingMore`, heading and accessibility labels; the browser adapter keeps pointer drag, click suppression, keyboard arrows and focus behavior.
- Data: row descriptors/fragment URL/item template from owning view. The web path still swaps server fragments through HTMX; the shared rail accepts already-resolved items and a renderer.
- Reuse/blockers: row/item values shared; scrolling/observer/pointer/persistence adapters required. The native shell currently renders demo tiles because the native media card action layer is still in progress, so the rail's item slot is proven only with demo renderers.
- Status: `Partial / coexisting`. The universal `Rail` and browser adapter are registered; no production web call site was replaced. Home, detail cast/crew/recommendations, person strips, collection rows and statistics still use `_scrollable_row.html` because parity depends on server HTML fragments and the native media card's action layer is still in progress.
- Native placement: `ported` in `native-proof/app/surfaces/RailsSlot.jsx`, which renders two production-shaped shelves with headings, sort direction, load more and a note. Placement completion is separate from runtime evidence: browser, iOS and Android behavior of the new rail remains unverified.
- Retirement condition: a bounded Django row adapter passes resolved items and a ported card renderer to `Rail`, and the HTMX load-more path is replaced by the bounded callback with equivalent scroll, retry, exhaustion and cleanup behavior.
- Verification: `app.tests.test_horizontal_scroll`, `src/static/js/horizontal-scroll.selfcheck.mjs`, `npm run build:ui`, `npm run check:ui`, UI architecture checks and `expo export --platform all`. Browser, iOS and Android runtime behavior of the new rail is **unverified**; only the static contracts and the native bundle compile were checked.
- Validation targets: `src/app/tests/test_horizontal_scroll.py`, `src/static/js/horizontal-scroll.selfcheck.mjs`.

### HOME — Shelves, deferred groups and cover refresh

- Purpose/usage: personalized Home composition.
- Implementation: `src/templates/app/home.html`, Home group/grid/deferred/artwork-poller components.
- Contract: configured sections, up-next semantics, deferred/coalesced cover polling, canonical cards/rails and progress actions.
- Data: Home row/artwork handlers in `src/app/views.py`, user configuration and server projections.
- Reuse/blockers: composition/data shareable; preserve per-user bounded queries; depends on cards/rails/preferences.
- Validation targets: `src/app/tests/views/test_home.py`, `test_home_screen_season_status.py`.

### PLAYBACK — Now Playing and check-in

- Purpose/usage: Home playback card and detail check-in state.
- Implementation: `src/templates/app/components/active_playback_card.html`, `detail_checkin_state.html`, Home inline polling/interpolation.
- Contract: art/status/progress, stop versus cancel, current token/offset identity, request replacement/order and stale-state handling.
- Data: playback fragment in `src/app/views.py`, `src/app/checkin_views.py`, server integration events/services.
- Reuse/blockers: display/control intent shareable; server live integrations/refresh are not standalone capabilities.
- Validation targets: `src/app/tests/test_playback_polling.py`, `test_checkin.py`, `test_checkin_session.py`, `test_live_playback.py`.

### DISCOVER — Recommendations and feedback

- Purpose/usage: Discover tabs/rows/hidden/preview and RSS row preview.
- Implementation: `src/templates/app/discover.html`, Discover row/card/tab/preview components.
- Contract: enabled types, hide/unhide/planning, stale/empty/refresh states and bounded fragments; cards retain declared surfaces.
- Data: `src/app/discover_views.py`, `src/app/discover/` feedback/caches, separate REST recommendation contract.
- Reuse/blockers: candidate/feedback values shared; poller/HTML response replacement require adapters.
- Validation targets: `src/app/tests/discover/test_views.py`, `test_action_row_partial.py`, `src/api/tests/test_fork_discover.py`.

## Detail, tracking and ownership

### DETAIL — Detail composition and metadata

- Purpose/usage: general and medium-specific detail pages.
- Implementation: `src/templates/app/media_details.html`, detail title/mobile/synopsis/section/slot fragments in map.
- Contract: responsive art/title/meta, configurable sections, public/auth actions, lazy carousels and notes/history/rating refresh boundaries. Preserve the provider Series Graph's color-coded season/episode score grid, source link, deferred loading and dialog dismissal.
- Data: `src/app/media_details_views.py`, `season_details_views.py`, detail builders and user layout configuration.
- Reuse/blockers: share typed sections while preserving medium composition and swaps; template contexts are not portable APIs.
- Validation targets: `src/app/tests/views/test_media_details.py`, `test_save_response_fragments.py`, `src/app/tests/views/test_trakt_series_graph.py`, `src/app/tests/test_detail_builders.py`.
- Book format links: a "Format" fact in the Details card of Book pages that joins the formats the viewer tracks, e.g. "Book, Audiobook", each name a link except the page being viewed. It replaces the provider's own Format fact when the viewer tracks another format of the same work; several audiobooks are told apart by narrator. Status: legacy, not migrated. Blocker: the Details card is a server-rendered fact list with no shared React equivalent, and porting it is a whole-card migration, not part of this change. Reopen when the DETAIL sidebar facts get a shared React component; this row moves with it. Data: `build_book_formats` (ISBN, or title plus author, among the viewer's own tracked books; never merges Items). Verification: browser only; no iOS/Android.
- Book narrator: a "Narrator" fact in the same Details card for Audiobookshelf audiobooks (`Item.narrators`, filled by the ABS importer, carried in the generic details payload). Status: legacy, same blocker and reopening condition as Book format links. Verification: browser only; no iOS/Android.
- Audiobook listening sessions: each Audiobookshelf listening session is a dated entry (date, time, duration, and where listening stopped) in the activity history modal and the History page, through the existing `session_history_row.html` row (one new "stopped at" fragment in that legacy template), so no new component. Status: legacy row, coexisting; the row has no shared React counterpart yet, and it moves when the history rows do. Data: `BookListeningSession` rows written by the Audiobookshelf importer, emitted by `history_cache_day_builder` and indexed by `history_cache_index`. Counted in Statistics as a separate "Listening Time" figure, never added to page totals. Verification: browser only; no iOS/Android.
- Book page history: a page-based (non-audiobook) book gets one dated entry per day its progress rose, built from its change log ("52 pages · at page 212 / 480"), in the same activity history modal and History page through the same `session_history_row.html` row (a new "at page" fragment in that legacy template). A book's first change-log row is a baseline and dates nothing, so a current page or percentage alone never produces history. Status: legacy row, coexisting. Blocker: the history row and the Statistics reading section are server-rendered Django templates with no shared React counterpart, and porting either is a whole-surface migration. Reopen when History rows or the Statistics reading cards get a shared React component. Data: `build_book_page_entries` over `HistoricalBook`, indexed by `history_cache_index`. Verification: browser only; no iOS/Android.
- Statistics "Listening Time": a stat card at the top of the Books Activity Overview (`reading_consumption_section.html`, `data-listening-time`) showing audiobook listening minutes for the range, kept apart from page counts (audiobook progress no longer feeds "pages", top items, completed-length chart or reading genres). Status: legacy, not migrated; same blocker and reopening condition as Book page history. Data: `BookListeningSession` minutes summed per day in `statistics_day_builder` (`totals.listening_minutes`), marked dirty by the session signal. Verification: browser only; no iOS/Android.

### CHILDREN — Seasons, episodes and issue rows

- Purpose/usage: episode/season/comic detail and child lists.
- Implementation: `src/templates/app/episode_details.html`, `comic_issue_details.html`, episode/issue/season/action/obfuscation/scroll fragments.
- Contract: ordering, watch/unwatch/drop, score/ownership/history, spoiler obfuscation and correct row/hero/scroll restoration.
- Data: detail/save/score handlers and source/media/season/episode coordinates.
- Reuse/blockers: shared row/actions; medium operations/order explicit. Depends on tracking/rating/collection parity.
- Validation targets: `src/app/tests/views/test_episode_history_poll.py`, `test_episode_score_invalidation.py`, `test_season_status_pill_sync.py`.

### TRACKING — Add/edit/repeat/bulk logging

- Purpose/usage: dialogs and manual creation.
- Implementation: `src/templates/app/create_entry.html`, fill-track/music/podcast modals, metadata panel; `src/static/js/mediaStatusDateHandler.js`, `episodeBulkTrackForm.js`.
- Contract: medium fields/repeat identity, date/status/progress coupling, notes/errors/delete/events; bulk range/add modes/date distribution remain supported.
- Data: `src/app/track_modal_views.py`, `save_views.py`, Django forms and music/podcast handlers.
- Backend normalization: season modals use the tracked item's coordinate; missing
  provider season lists disable the optional episode domain rather than failing
  the modal. Existing dialog presentation remains legacy and unchanged.
- Reuse/blockers: share fields, preserve distinct operations/server validation. HTML forms do not imply REST write parity.
- Validation targets: `src/app/tests/views/test_track_modal.py`, `test_episode_bulk_save.py`, `test_music_bulk_save.py`, `test_rewatch.py`.

### DATE-TIME — Field picker and activity calendar

- Purpose/usage: tracking dates and session history, distinct from release calendar.
- Status: `Partial / coexisting`. The shared React Native `DateTimePicker` owns the field, quick actions, month/year navigation, six-week grid, optional 12/24-hour time, marked/selectable days, hidden value contract and dismiss/focus behavior. The browser adapter mounts it into the static tracking fields and keeps the hidden input, htmx input events, status autofill, paired start/end dates, copy/clear and saved week-start/12-hour preferences. Bulk episode forms whose suggestion dates are Alpine expressions keep the frozen `date_time_picker_legacy.html` include.
- Shared logic exports: `pad2`, `dateKey`, `parseDateValue`, `normalizeValue`, `formatValue`, `valueFromDate`, `formatDisplayText`, `monthLabel`, `monthShortLabel`, `weekdayLabels`, `monthWeeks`, `yearPage`, `isSameDay`, `isToday`, `displayHour`, `meridiem`, `hour24FromDisplay`, `stepHour`, `stepMinute`, `stepSecond`, `isMarkedDay`, `isSelectableDay`, `nowParts`.
- Implementation: universal `frontend/ui/DateTimePicker.jsx` with shared calculations in `frontend/ui/dateTime.js`; browser adapter `frontend/ui/mountDateTimePicker.jsx`; host template `src/templates/app/components/date_time_picker_react.html` and the `date_time_picker` tag in `src/users/templatetags/ui_tags.py`. Legacy consumers: `src/templates/app/components/date_time_picker_legacy.html`, `calendar.html`, `src/static/js/dateTimePicker.js`, `calendar.js`, and the activity calendar in `session_history_modal.html`.
- Contract: clear/current/release/copy, optional time, 12/24h/week-start/locale supplied explicitly, six-week grid/month/year, marked/selectable days, hidden values/events and Escape. The shared presentation uses the value and callbacks only; the browser adapter owns form and Alpine integration.
- Data: owning field/history configuration, user week-start and time-format preferences, suggestion/runtime values and copy source.
- Reuse/blockers: the React picker is native placement complete in the proof app; the React web path is limited to static tracking fields until expression-driven suggestions become explicit events. The release calendar grid is `RELEASE-CALENDAR`, not this port. Timezone-specific behavior and the remaining activity-calendar web surface are not verified.
- Verification: targeted tracking/modal and history tests plus `npm run build:ui`, architecture checks and Expo export. Browser interaction, iOS and Android runtime remain unverified.
- Validation targets: `src/app/tests/views/test_track_modal.py`, `test_episode_bulk_save.py`, `test_music_bulk_save.py`, `src/app/tests/views/test_history.py`, `src/events/tests/test_views.py`; independent keyboard/timezone coverage unverified.
- Retirement: `date_time_picker_legacy.html` and `dateTimePicker.js` retire when expression-driven suggestions are passed as data/events (bulk episode forms). The activity calendar retires with its own `HISTORY` port; the release calendar grid with `RELEASE-CALENDAR`.

### NOTES — Markdown editing and display

- Purpose/usage: detail/media forms/music track notes.
- Implementation: markdown/detail-note/music-note fragments; `src/static/js/markdown-editor.js` and marked.
- Contract: Write/Preview, toolbar/selection, safe rendering, initialization after full/HTMX loads and save errors.
- Data: bound note fields and music note handler in `src/app/music_views.py`.
- Reuse/blockers: text/formatting intent shared; textarea selection and HTML preview need platform implementation/content safety review.
- Validation targets: `src/app/tests/views/test_music_track_notes.py`; general editor interactions unverified.

### PROGRESS — Adjustment and repeat breakdown

- Purpose/usage: Home/detail progress.
- Status: `Partial / coexisting`. The quick +/- controls on Home in-progress cards are React-owned by the shared `ProgressChanger`. The detail progress card and its Alpine modal shell remain legacy, but the season/episode breakdown rendered inside that modal is React-owned through the shared `ProgressBreakdown`. Native card and breakdown presentation exist but are unverified on iOS and Android. Browser verification is not claimed for the mounted breakdown.
- Implementation: universal `frontend/ui/ProgressBar.jsx`, `ProgressCard.jsx` and `ProgressBreakdown.jsx` take explicit values, season/episode view models, labels, palette, expansion state and callbacks. `ProgressBreakdownTheme.web.jsx` and `mountProgressBreakdown.jsx` mount the shared breakdown into the htmx-rendered modal body, keep theme resolution and season/episode navigation, and hide the server fallback. The legacy modal header keeps the htmx `cancel_progress_rewatch` form. `ProgressChanger` continues to use `frontend/ui/ProgressChanger.jsx`, `ProgressChangerTheme.web.jsx` and `mountProgressChanger.jsx`. `src/templates/app/components/progress_breakdown.html` keeps its Alpine/HTMX markup as the fallback; `detail_progress_card_slot.html` and `progress_changer.html` remain their own owners.
- Contract: card title/subtitle, watched-once percentage and bar, current-pass glow and label, info tooltip, open-breakdown intent; breakdown totals, minutes left, catalogue-unavailable notice, expand/collapse all, per-season dropped/not-aired/percentage and rewatch lines, episode watched/unwatched/upcoming rows with again-watched glow, cancel-rewatch intent, loading/error/empty states, progressbar accessibility values and focus/escape dismissal in the owning shell. Progress values, percentages and server operations remain authoritative in Django.
- Data: `src/app/progress_views.py`, `progress_edit` in `src/app/views.py`, `BasicMedia` progress properties, `watch_operation_id` and `app.services.progress_breakdown`.
- Consumers: Home in-progress cards through `home_grid.html` and the `progress_edit` response remain `ProgressChanger`. Show and season detail breakdowns render `ProgressBreakdown` on mount while the legacy `detail_progress_card_slot.html` keeps the Alpine card, teleported modal, htmx GET refresh, out-of-band card refresh and server fallback. The detail card is the remaining legacy Home/detail consumer.
- Retirement: the legacy button/value markup inside the progress-changer fallback retires when the island is considered universal. The legacy detail card and modal shell retire when card parity, tooltip placement, focus restoration and htmx refresh behavior have a proven React adapter. The server fallback remains intentionally for progressive enhancement.
- Native mapping: React Native `Pressable`/`Text`/`View`/`Modal`, the shared `ProgressBar`, `ProgressChanger` and `Spinner`; callers supply concrete palette values and callbacks instead of transport.
- Verification: `users.tests.test_progress_changer_tag` covers the adjustment controls. `app.tests.views.test_progress`, `app.tests.test_progress_breakdown` and `app.tests.test_rewatch_progress` cover the card, fragment, writes and rewatch rules. The web adapter, Expo export and bundles compile; the mounted breakdown was not exercised in a browser in this change. iOS and Android were not exercised; earlier `ProgressChanger` and `Spinner` runtime evidence does not verify this card or breakdown.
- Validation targets: `src/app/tests/views/test_progress.py`, `src/app/tests/test_progress_breakdown.py`, `src/app/tests/test_rewatch_progress.py`, `users.tests.test_progress_changer_browser` (slow/Playwright).

### OWNERSHIP — Collection browser and copy editor

- Purpose/usage: collection page, detail/tracking ownership controls.
- Implementation: `src/templates/app/collection_list.html`, collection modal/form/summary/grid/row fragments.
- Contract: grid/row/table/filter/sort, completeness, multiple copies/labels, medium fields, season cascades and owner-only mutation.
- Data: `src/app/collection_views.py`, forms/models; canonical collection card surface.
- Reuse/blockers: copy editor/summaries shared; collection ownership differs from list membership. Depends on cards/filters/fields.
- Validation targets: `src/app/tests/views/test_collection.py`, `test_collection_copy_labels.py`, `src/app/tests/test_collection_season_cascade.py`.

### CUSTOM-FIELDS — Collection definitions and values

- Purpose/usage: collection editor, summaries, filters/sort.
- Implementation: collection custom-fields/inputs fragments, `src/static/js/collectionCustomFields.js`, SortableJS.
- Contract: type/options/edit/delete/order, JSON saves, typed values/errors; do not duplicate importer resolution rules in UI.
- Data: collection definitions/values and endpoints in `src/app/collection_views.py`.
- Reuse/blockers: schema/field rendering shareable; native reorder and persisted ownership validation required.
- Validation targets: `src/app/tests/views/test_collection_custom_fields.py`, `src/app/tests/test_collection_custom_field_values.py`.

### ARTWORK — Cover and edition selection

- Purpose/usage: detail/tracking image replacement and book editions.
- Implementation: image picker/tiles/cover-change/edition/Hardcover result fragments.
- Contract: candidate/file/URL, preview/reset/save/return, accepted formats/provider identity, authorization and safe outbound fetch.
- Data: `src/app/cover_views.py`, edition routes; [local covers](../architecture/local-covers.md).
- Reuse/blockers: selection state shared; file/drag/blob/camera/native caching need adapters.
- Validation targets: `src/app/tests/test_local_covers.py`, `src/app/tests/views/test_hardcover_edition_views.py`.

### MUSIC — Artist/album/track and podcast composition

- Purpose/usage: artist relations/discography, album tracks, show/episode detail.
- Implementation: `src/templates/app/music_album_detail.html`, `podcast_show_detail.html`, music/artist/album/podcast components in map.
- Contract: hierarchy/deferred art, per-track actions/history/notes/scores, episode filter/pagination, repeats and show tracking.
- Data: `src/app/music_views.py`, `music_album_views.py`, `podcast_views.py`; web episode JSON/HTML is not proven native API parity.
- Reuse/blockers: consume shared cards/rows/tracking; preserve hierarchy/feed behavior and explicit playback boundaries.
- Validation targets: `src/app/tests/views/test_music_release_views.py`, `test_podcast_show_detail.py`, `test_podcast_detail_rss_refresh.py`.

### PEOPLE — People/studios, credits and medium extras

- Purpose/usage: person/studio pages and detail cast/trailers/game-length/reading sections.
- Implementation: `src/templates/app/person_detail.html`, `studio_detail.html`, cast/filmography/carousel/YouTube/extra fragments.
- Contract: internal/external links, role credits, bounded rails, carousel/lightbox/playback and medium metadata.
- Data: `src/app/people_views.py`, provider/detail projections.
- Reuse/blockers: presentation/data shared; embeds/playback/semantic navigation need platform decisions. Person cards intentionally differ from tracked media cards.
- Validation targets: `src/app/tests/views/test_person_detail.py`, `test_studio_detail.py`, `src/app/tests/test_detail_builders_game_credits.py`.

### TAGS — Management and assignment

- Purpose/usage: tag index, detail/library/bulk tagging and settings tag filters.
- Implementation: `src/templates/app/tag_index.html`, fill/tag-button/detail-preview fragments, `src/templates/users/components/media_tag_filter.html`.
- Contract: search/select/add/remove, item/bulk identity, confirmed library-wide delete and consistent filter semantics.
- Data: `src/app/tag_views.py`, user-owned tag relations/library query.
- Reuse/blockers: chip/selection model shared; destructive/ownership checks stay server-enforced.
- Validation targets: `src/app/tests/views/test_tags.py`, `src/users/tests/views/test_settings_media_tag_filters.py`.

### METADATA-REVIEW — Episode order, provider switch and remap

- Purpose/usage: explicit review/correction workflows.
- Implementation: `src/templates/app/episode_ordering.html`, `tv_provider_switch.html`, remap/library-move results, `src/static/js/episodeOrderReview.js`.
- Contract: matched/suggested/manual/archived choices, source/episode coordinates, confirmations/errors and preserved user tracking.
- Data: `src/app/episode_order_views.py`, metadata-sync/detail routes and domain services.
- Reuse/blockers: selection/review patterns shared; mutation semantics need explicit API audit.
- Validation targets: `src/app/tests/test_episode_ordering.py`, `test_tv_provider_switch.py`.

### DETAIL-RELATED — Related-media sections and Steam DLC cards

- Purpose/usage: game/media detail related sections (IGDB DLCs, expansions, remakes) plus display-only Steam DLC cards when IGDB lists none.
- Implementation: legacy Django template `src/templates/app/components/detail_secondary_content.html`; heading via `related_section_label` in `src/app/templatetags/app_tags.py`; data from `app.providers.igdb.get_steam_dlcs`.
- Contract: Steam DLC cards are untracked links to the Steam store (title, header image, URL); IGDB DLCs remain tracked media cards.
- Status: legacy (not React-owned). Deferred: the section is Alpine-driven and shares one `x-data` grid with the media card; porting needs the shared media card island first. Reopen when `media_card` ships as a React component.
- Validation: `app.tests.providers.test_metadata` (`get_steam_dlcs`), `app.tests.test_templatetags`. Browser/iOS/Android verification: none.

## Feature interfaces

### HISTORY — Feed, edits and activity dialog

- Purpose/usage: global history and per-item sessions/repeats.
- Implementation: `src/templates/app/history.html`, history day/card/edit and session modal/day/row fragments, `src/static/js/sessionHistory.js`.
- Contract: filters/modes/days, bounded fragments/refresh notice, edit/delete/units, marked dates/day jumps, close-button focus and nested refresh.
- Data: `src/app/history_views.py`, `src/events/history_feed.py`; [memory contract](../architecture/history-memory.md).
- Reuse/blockers: day/session values shared; date/filter dependencies. Never client-load whole history.
- Validation targets: `src/app/tests/views/test_history.py`, `src/app/tests/test_history_item_projection.py`, `test_history_day_cache_lifecycle.py`.

### STATISTICS — Dashboard, charts and taste/talent

- Purpose/usage: statistics, comparison, activity/highlights and featured repeats.
- Implementation: `src/templates/app/statistics.html`, statistics/taste/role/studio/featured fragments; `src/static/js/statistics-charts.js`, `stats-media-merge.js`, `date-range.js`, Chart.js/datalabels.
- Contract: media/range/comparison, dates/units, charts/heatmaps/order, refresh/errors and teardown; avoid drift in server/JS media visual mappings.
- Data: `src/app/statistics_views.py`, snapshots/[statistics sync](../architecture/statistics-sync.md).
- Reuse/blockers: transforms/tokens shared; canvas needs native renderer. Keep expensive computation server-owned.
- Validation targets: `src/app/tests/views/test_statistics.py`, `src/app/tests/test_statistics_sync.py`, `test_statistics_media_merge_js.py`; browser layout checks are slow.

### RELEASE-CALENDAR — Upcoming releases and subscriptions

- Purpose/usage: release calendar page, not `DATE-TIME`.
- Status: `Partial / coexisting`. The gear menu (Go to Today, Fetch New Releases, Download Calendar, Week starts on Monday/Sunday) is React-owned through the shared `ActionMenu` (now with an icon trigger, link items and a pressed state on inline actions). The month grid, agenda, list, filters and toolbar remain legacy Alpine/server templates. Browser verification: menu, week-start switch and agenda labels exercised in the built-in browser. Native iOS and Android: not verified.
- Implementation: `src/templates/events/calendar.html`, calendar grid/list components; mostly inline Alpine. Gear menu: `frontend/ui/mountCalendarMenu.jsx` + `ActionMenu` in `frontend/ui/controls.jsx`; props from `events.views._calendar_menu_props`. The week start saves through the existing `update_statistics_preferences` endpoint (same `week_start_day` the date pickers and Statistics read), then reloads.
- Episode labels: grid agenda and list share `Event.season_episode_label` ("S39E170"); a season's title drops a trailing "Season N" so the label carries it once.
- Contract: month/today/grid/list, media/status/release/tag filters, persisted view, grouped dates/media, ICS/download/subscription/reload and empty states. Redesign needs explicit requirements.
- Data: `src/events/views.py`, `src/events/calendar/`, tasks; [reload contract](../architecture/calendar-reload.md), REST parity unverified.
- Retirement: the Alpine toolbar/grid retire as the filter menu and day grid are ported. The server-rendered "Go to Today" link inside the menu host is the no-JS fallback.
- Reuse/blockers: date/filter/group values shared; layout/ICS/browser subscription adapters explicit.
- Validation targets: `src/events/tests/test_views.py`, `test_release_semantics.py`, `calendar/test_main.py`, `src/api/tests/test_calendar.py`.

### LISTS — Lists, memberships, public profiles and collaboration

- Purpose/usage: list browser/detail/activity/profile/forms and membership popup.
- Status: `Partial / coexisting`. The lists hub and list detail header are React-owned through the shared `ListCard` and `ListHeader` components. The hub renders list cards with visibility, role, member counts, smart-list indicator, item/completion metadata, search, tags, create/edit entry points and empty/loading states. The list detail header renders the list name, counts, visibility/collaborator badges and actions. The list detail result grid remains server-rendered. The web list pages remain server-owned; the React components are mounted in the native shell.
- Migration state by surface: manual-list grid/table/tiers and public detail pages consume the fully React-owned ALPHABET sibling. Existing list headers, toolbars, cards/tables and editing controls retain legacy ownership on web; migrate each when edited. The native shell now renders the shared hub and header.
- Implementation: `frontend/ui/ListCard.jsx` and `frontend/ui/ListHeader.jsx` (shared universal components); `src/templates/lists/custom_lists.html`, `list_detail.html`, `user_profile.html`, `list_activity.html`, list grid/form/visibility/membership/table components remain web-owned.
- Contract: manual/smart/source-backed distinction, search/tags/roles, public/unlisted/private, membership/pins/feed/export/sync and public read-only rendering.
- Data: `src/lists/views.py`, browse/action/helper views, models/forms; REST parity separately assessed.
- Reuse/blockers: list card/editor/membership shared; consume canonical media/filter/table systems; collection ownership is separate. The native hub/header are runtime-unverified; the web list pages still own their legacy header/toolbar.
- Validation targets: `src/lists/tests/test_views.py`, `test_forms.py`, `test_rss_feed.py`, `test_csv_export_import.py`.

### SMART-RULES — Rule editing and results

- Purpose/usage: smart-list detail/editor/summary.
- Migration state by surface: smart-list grid/table detail pages consume the fully
  React-owned ALPHABET sibling; rule editing, summaries and result components remain
  legacy. Alphabet view state does not alter their saved rule or permission contracts.
- Implementation: `src/templates/lists/smart_list_detail.html`, smart rules builder/summary components.
- Contract: initial JSON/live editing/save/errors, results/sort/bulk and shared rule semantics.
- Data: `src/lists/views_smart_list.py`, `smart_rules.py`, library query engine.
- Reuse/blockers: normalized filter state/schema shared; never fork evaluation for native/Home.
- Validation targets: `src/lists/tests/test_smart_list_semantics.py`, `test_smart_list_sync_deferral.py`.

### LIST-CURATION — Search, add and recommend

- Purpose/usage: add/recommend/approval pages and preview dialogs.
- Implementation: `src/templates/lists/add_item.html`, `recommend_item.html`, `list_recommendations.html`, search/preview components.
- Contract: provider/type/query/pagination, preview/add/recommend/approve/deny and role-specific permissions.
- Data: `src/lists/views_add_reorder.py`, `views_recommendations.py` and distinct actions.
- Reuse/blockers: parallel search/preview presentation can consolidate; do not merge authorization/submission semantics. Depends on search/cards/dialogs.
- Validation targets: `src/lists/tests/test_views.py`, `test_item_rank.py`, `test_integration.py`.

### TIERS — Board, order and export

- Purpose/usage: editable/public list tier boards.
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
- Implementation: `src/templates/users/base.html`, `sidebar.html`, media-type picker/order-script components.
- Contract: current-page semantics/responsive collapse, enabled types/Discover/order and boosted navigation.
- Data: `src/users/views.py` sidebar/preferences handlers and user config.
- Reuse/blockers: navigation/selection model shared; routing/HTMX/native navigation remain platform boundaries.
- Validation targets: `src/users/tests/views/test_settings_media_tag_filters.py`, `src/users/tests/views/test_onboarding.py`.

### SET-PREFERENCES — Preferences and save states

- Purpose/usage: locale/date/time/title/region/general behavior settings.
- Implementation: `src/templates/users/preferences.html`, inline selectors/help, shared save bar.
- Contract: unsaved/disabled/selected/error states, validation, dirty tracking and polite announcements.
- Data: preferences handler in `src/users/views.py`, `src/users/forms.py` and user fields.
- Reuse/blockers: fields/selection/save model shared; repeated dropdowns consolidate when feasible. Mobile preferences parity unverified.
- Validation targets: `src/users/tests/views/test_preferences.py`.

### SET-APPEARANCE — Theme and detail layout editor

- Purpose/usage: swatches/custom effects and detail-family section enable/order.
- Implementation: `src/templates/users/appearance.html`, inline `appearanceEditor()`/JSON-script config.
- Contract: selection/custom validation, tabs/zones/order and persisted settings.
- Data: `src/users/appearance.py`, appearance handler in `src/users/views.py`.
- Reuse/blockers: tokens/editor state shared; CSS runtime/reorder need platform implementations.
- Validation targets: `src/users/tests/views/test_appearance.py`, `src/app/tests/test_theme_tokens.py`.

### SET-CARDS — Card configuration and preview

- Purpose/usage: per-media line selection/reorder/live preview.
- Implementation: `src/templates/users/cards.html`, `cards_preview.html`, inline `cardsEditor()`.
- Contract: per-type values/default/order and previews consistent with canonical projection.
- Data: `src/users/card_metadata.py`, card settings/preview handlers.
- Reuse/blockers: shared schema/state with card; server preview HTML needs adapter.
- Validation targets: `src/users/tests/views/test_cards.py`, `src/users/tests/test_card_metadata.py`.

### SET-HOME — Home section/shelf editor

- Purpose/usage: Home rows/filter/sort/list-backed sections.
- Implementation: `src/templates/users/home_screen.html`, inline `homeScreenSettings()`, Alpine/SortableJS.
- Contract: nested order/labels/colors/collapse/menus, owned/collaborator/smart-list search, validation and payload.
- Data: `src/users/home_screen.py`, Home config/search/filter handlers.
- Reuse/blockers: editor model/filters shared; native reorder/drag-versus-click need proof.
- Validation targets: `src/users/tests/views/test_home_screen.py`, `test_home_screen_menus.py`.

### SET-PROVIDERS — Catalog and capability tabs

- Purpose/usage: current provider browser/detail and status cards.
- Implementation: `frontend/providers/Directory.jsx` and shared catalog/toolbar controls; `src/templates/users/providers.html` and provider result/card templates provide the server fallback. `provider_detail.html` and provider status/row components retain other consumers. The former Alpine filter-dropdown template has no active directory consumer.
- Contract: query/capability/media, 300ms search/URL/history, supported tabs and connection health.
- Data: `src/users/provider_views.py`, `provider_catalog.py`, `provider_ui.directory_page`; HTML fallback and authenticated private/no-store JSON with explicit presentation fields only.
- Reuse/blockers: catalog/status values shared; do not assume services available standalone.
- Validation targets: `src/users/tests/views/test_provider_navigation.py`, `test_provider_catalog.py`, `test_provider_integration_sections.py`.
- Status: `Web Migrated` for the Providers directory and every provider's header, media chips, tabs and Overview. All use `ProviderPage` and data-driven shared cards; AniList also owns Connection, Import and Activity bodies. Other tab bodies remain server-owned siblings with partial shared card consumers. The directory reuses app-wide catalog and filter controls. The server `header_fallback.html` shares the React header's classes (`provider-identity`, `provider-media-chip`, `ui-tabs`) so the mount causes no reflow; media chips sit in the title row itself (wrapping among themselves, never below the title); React-owned tab bodies and unmounted island roots stay hidden until mount (4s CSS reveal as the failure fallback); the activity loader placeholders use the same `settings_card` shell as the loaded partial. Browser-verified only; iOS/Android not verified. See [provider-page ownership and data](provider-pages.md).
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
- Status: `Web Migrated` for every Metadata tab through `Metadata.jsx`, with inline shared source/default forms, anime format, fixed/supplemental explanations, migration actions and TMDB proxy settings. AniList owns instance/personal credential forms and its permission dialog; other credential bodies remain Django forms with shared React headings. Preserve editable/read-only/environment locks; saved values and previews never enter page models.
- Verification: 78 targeted provider, metadata, sync and import tests passed with `FLOPPY_TEST_FAST_DB=1` (migrations not replayed); Chromium 151 on macOS, system light/dark at 1440×1000 and 390×844, including permission dialog focus and Escape. Native and assistive-technology testing not performed.
- Related work: [#1793](https://github.com/dannyvfilms/Floppy/issues/1793). Deferral: the legacy metadata template retains its modal for compatibility; retire that consumer when the retained legacy template is removed. Native credential transport and secure storage await separate design and the foundation proof.

### SET-IMPORT — Connect, upload and schedule

- Purpose/usage: provider import tabs, reading-server dialogs/schedules.
- Source inventory: shared file import is `frontend/providers/FileImport.jsx`;
  `clz_import_fallback.html` is its retained server fallback. Their ownership is
  recorded here; this alphabet change does not alter their migration state.
- Migration status (Playwright and server-render checked; iOS/Android unverified): single-file and
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
  connect and settings). Hardcover sync, KOReader (Connection tab) and MDBList (Connection tab) now use `SettingsForm.jsx`/
  `FileImport.jsx` inline instead of a modal. Plex's Connection tab is now the shared webhook card (`SetupGuide.jsx` with a primary copy
  field, status badge/tooltip and collapsed steps; `provider_guides._plex_webhook_badge`) above the shared account
  card (`AccountConnection.jsx` with badges and a single full-width card); the "Set up account access here /
  Open connection setup" header and button no longer render on provider pages. Jellyfin's Connection tab now matches it: one webhook card (primary copy field, status tag) with the two plugin
  setups (official, unofficial) as two side-by-side cards below it (one fold each, stacked on phones), and every folded `SetupGuide.jsx` guide
  (Plex, Jellyfin, Emby, Seerr) now renders as two cards, status and copy field first, steps second, with a 1rem gap
  (`.ui-guide-stack`, and a margin between separate guide roots). Emby's and Seerr's guides are folded with a primary copy field (the Jellyfin official
  guide shows a "Needs update" badge when the template is outdated; no last-received badge because Floppy stores no
  Jellyfin webhook timestamp, so adding one needs a user-model migration), above the shared
  `AccountConnection.jsx` card (`provider_views`, new `editable` flag: connected accounts get an "Edit connection"
  toggle that re-submits server URL, API key and username, prefilled from non-secret fields; the API key is never
  serialized). Status: React-owned on browser (Connection tab), verified in the browser only; iOS and Android not
  verified. Remaining legacy, with blockers: Jellyfin Import/Sync/Tracking cards and the Emby/Kodi Sync push forms
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
- Status: `Web Migrated` for AniList preferences, serialized auto-save, public username import and credential-gated private OAuth form. Uses app-wide fields/selects/buttons/card grid and a reusable Public/Private `ToggleChip`; provider code retains authentication semantics. Other providers share the React import-preferences island while their provider-specific forms remain Django-owned; data management retains its restore dialog. Activity lists use bounded scrolling and provider pins are persisted per user. Native verification remains pending.
- Verification: targeted provider catalog and import tests cover scheduling, credentials, uploads and scoped activity; Chromium on macOS checked AniList, Pocket Casts and Playnite at desktop and phone widths in dark mode. Native not tested.
- Related work: [#1793](https://github.com/dannyvfilms/Floppy/issues/1793). Deferral: native upload, scheduling and server-job adapters await the foundation proof and separately authorized client work.

### SET-ACTIVITY — Import and operational activity

- Purpose/usage: activity/run details/cancel/rollback/cleanup/outbound status.
- Implementation: `frontend/providers/Activity.jsx` and shared settings cards, alongside `src/templates/users/provider_activity.html`, import loader/activity/cleanup and integration/outbound activity components. Provider activity uses React card headers with Django-owned body slots until those controls are migrated.
- Contract: five-second polling pauses swaps while `[data-keep-open=true]` details are expanded and preserves bounded list scroll positions; preserve pending/running/result/error, copying and action permissions. Task history and import runs are separate records; runs expose counts and undo where supported.
- Data: provider activity handler, ImportRun/tasks and cancel/rollback/cleanup handlers.
- Reuse/blockers: status/activity presentation shared; transport/job control adapters must not erase user work on refresh.
- Validation targets: `src/users/tests/views/test_cancel_import_run.py`, `test_cancel_pending_import.py`, `test_rollback_import_run.py`.
- Status: `Web Migrated` for AniList scoped schedules, paged history, run actions and source cleanup. React owns polling and preserves expanded diagnostics. Other provider/central Activity surfaces retain their current records/actions and templates.
- Verification: scoped JSON tests cover exact ownership, pagination and token exclusion; existing cancel/undo/source cleanup tests pass. Chromium 151/macOS checks polling pause, error details and schedule removal returning to Activity. Native not tested.
- Related work: [#1793](https://github.com/dannyvfilms/Floppy/issues/1793). Deferral: native activity transport and job controls await separate client work and the foundation proof.

### SET-SYNC — Integrations, outbound sync and health

- Purpose/usage: provider integration/sync/service tabs.
- Implementation: `src/templates/users/providers/integration_content.html`, service integration/MAL/outbound fragments, sync/scrobble/conflict/status/modals.
- Contract: webhook/library/user choices, connected/broken distinction, directions/conflicts/kill switches and provider instructions.
- Data: `src/users/views.py`, `src/integrations/state/settings_view.py`, integration actions; connection-health contract applies.
- Reuse/blockers: status/fields shared; background integrations require server capabilities and distinct provider semantics.
- Validation targets: `src/integrations/tests/test_sync_settings.py`, `src/users/tests/views/test_provider_sync_templates.py`.
- Status: `Existing`. Watched-state configuration is on the supported media server Sync tabs; Activity surfaces conflicts when present. Provider-scoped MAL and outbound sections use the provider shell's surface.
- Verification: the 78 targeted tests above include `test_provider_sync_templates`; Chromium 151 on macOS at desktop and phone widths in system light/dark covered the disconnected MAL Sync page, but not a connected outbound account. Native not tested.
- Related work: [#1793](https://github.com/dannyvfilms/Floppy/issues/1793). Deferral: native sync settings and server integration adapters await the foundation proof.

### SET-DATA — Export/restore, danger zone and RSS

- Purpose/usage: data management and RSS builder/preview.
- Implementation: `src/templates/users/data_management.html`, `rss.html`, export/danger controls; retained export pages.
- Contract: content eligibility/schedules/download history/restore/repair, destructive confirmation/ownership; RSS copy/preview skips planning/collected filters.
- Data: provider data-management and export/delete/RSS handlers in `src/users/views.py`.
- Reuse/blockers: selection/warning/status shared; download/clipboard/feed/restore are platform/server boundaries.
- Validation targets: `src/users/tests/views/test_export_schedule.py`, `test_bulk_delete_by_import_source.py`, `test_rss.py`.
- Backup status (#1627): the destination/freshness paragraphs of `export_controls.html` are React-owned (`frontend/settings/BackupStatus.jsx`, partial/coexisting — the schedule form and the rest of the page stay legacy). Server fallback retained inside `data-backup-status-root`; sections are built and translated by `users.views.backup_panel_props`. Retirement: when the export form itself is ported. Browser verification: Chromium via the isolated bench server, empty-history state mounted and rendered both sections; failure and PostgreSQL states covered by unit tests only. iOS/Android: not tested.

### SET-ACCESS — Tokens, grants and OAuth approval

- Purpose/usage: access settings, application/device authorization.
- Implementation: access-token/integration-token/catalog-grant components, `src/templates/integrations/oauth_applications.html`, `oauth_device.html`.
- Contract: one-time secret, scope/expiry/copy/revoke, grants and device approve/deny.
- Data: token/grant handlers, `src/integrations/oauth_management.py`, `oauth_device.py`.
- Reuse/blockers: fields/status shared; secure native storage/auth lifecycle separately designed, never credentials in shared presentation.
- Validation targets: `src/users/tests/views/test_integration_tokens.py`, `src/integrations/tests/test_oauth_device_flow.py`.

### AUTH — Authentication and account security

- Purpose/usage: login/signup/social/password/TOTP/recovery/deletion.
- Implementation: `src/templates/account/`, `allauth/`, `socialaccount/`, `users/account.html`, `password_recover.html`; allauth/inline password visibility.
- Contract: errors/redirects/social connections, password/QR/recovery codes, identity-confirmed deletion/demo/last-superuser guards; no email/SMS recovery implied.
- Data: allauth, `src/users/forms.py`, signup/account/recovery handlers.
- Reuse/blockers: accessible fields shared; browser sessions/CSRF/allauth do not establish native auth.
- Validation targets: `src/users/tests/views/test_signup.py`, `src/users/tests/test_delete_account.py`, `test_demo_account_guard.py`.

### SET-NOTIFICATIONS — Notification preferences/exclusions

- Purpose/usage: release/premiere/digest/test and media exclusion list.
- Implementation: `src/templates/users/notifications.html`, search-results/excluded-items components.
- Contract: save/choice/error/test feedback, 300ms search and include/exclude refresh.
- Data: notification/test/search/exclusion handlers and delivery jobs.
- Reuse/blockers: selection/search/exclusion shared; delivery/scheduling remains server capability.
- Validation targets: `src/users/tests/views/test_notifications.py`.

### ONBOARDING — Resumable first-run setup

- Purpose/usage: media/metadata/services wizard, connection/upload/OAuth/Trakt variants/banner.
- Implementation: `src/templates/users/onboarding/`, onboarding-banner component; shared media-type picker.
- Contract: persisted resume/restart/skip/next, connect/import status, Plex instructions and device fallback.
- Data: `src/users/onboarding_views.py`, `src/integrations/onboarding.py`, user state/ImportRun.
- Reuse/blockers: wizard/controls shared; standalone onboarding needs separately approved capabilities.
- Validation targets: `src/users/tests/views/test_onboarding.py`, `src/integrations/tests/test_onboarding.py`.

### SET-SYSTEM — Advanced, About, updates and install

- Purpose/usage: administration/server info/release/install feedback.
- Implementation: `src/templates/users/advanced.html`, `about.html`, server-port/update-banner/whats-new components.
- Contract: cache/image controls/confirmations/log download/port restrictions, deferred releases and install/API links.
- Data: advanced/about/release handlers, `src/users/server_port_views.py`.
- Reuse/blockers: mostly web/server composition; share action/warning/status primitives rather than whole admin screens.
- Validation targets: `src/users/tests/views/test_server_port.py`, `src/users/tests/views/test_image_cache.py`, `src/users/tests/views/test_about.py`.

### MATCH-REVIEW — Integration match correction

- Purpose/usage: unmatched/incorrect media review.
- Implementation: `src/templates/integrations/match_fix.html`, `src/static/js/matchFixReview.js`.
- Contract: filters/candidates/chosen identity, POST/error and retained tracking semantics.
- Data: integration views and `src/integrations/match_corrections.py`.
- Reuse/blockers: shared selection/review pattern; distinct correction semantics and permissions remain explicit.
- Validation targets: `src/integrations/tests/test_matching_and_corrections.py`.

### INTEGRATION-PANELS — Library/download and Seerr requests

- Purpose/usage: detail Arr/Seerr status/request actions.
- Implementation: `src/templates/integrations/library_panel.html`, `seerr_request.html`, `seerr_status.html`.
- Contract: nearest-panel replacement, instance/media/season/episode, copy feedback, per-season request/status, permissions/provider errors and parent modal close state.
- Data: `src/integrations/arr_library.py` and integration handlers.
- Reuse/blockers: status/actions shared; parent Alpine/HTMX coupling must be removed deliberately; server capabilities required.
- Validation targets: owning integration view tests; browser/native lifecycle unverified.

### DEVICE-CONNECT — Trakt/device-code connection

- Purpose/usage: provider connection and onboarding handoff.
- Implementation: `src/templates/integrations/trakt_device_code.html`, onboarding Trakt consumer.
- Contract: start/poll/code/expiry/redirect and useful errors.
- Data: device-code handlers in `src/integrations/views.py`, account state.
- Reuse/blockers: display/state shared; system browser/deep link/native credentials require explicit design.
- Validation targets: provider/device tests; native handoff unverified.

### STREMIO — Standalone addon configuration

- Purpose/usage: configuration outside standard shell.
- Implementation: `src/templates/integrations/stremio_configure.html`, imperative inline script/independent HTML.
- Contract: publish toggles, reorder/accessible labels and generated configuration.
- Data: addon configuration context/endpoints.
- Reuse/blockers: assess explicit web-only exception when touched; do not omit or force into native shell assumptions.
- Validation targets: Stremio integration tests; browser/native parity unverified.

### BULK_ACTIONS — Select Items toolbar, dialogs and job dock

- Purpose/usage: the Select Items bar on media lists, custom lists and smart lists, plus the Update Status confirmation and Add Plays to History for TV and anime. Slow work runs as a job in a docked card, so the page stays usable.
- Status: `Partial / coexisting`. React owns the toolbar (Library group: Update Status, Add to List, Add to Collection, Apply Tag; History group: Add Plays to History), the two dialogs and the job dock. Selection state, select-mode and the card checkboxes remain legacy Alpine (`bulkSelection.js`, media cards). Browser verification: toolbar, menus, dock review, background progress across navigation and partial failure exercised in the built-in browser. Native iOS and Android: not verified.
- Implementation: `frontend/ui/mountBulkToolbar.jsx` (per list page, reads `window.__bulkSelection`), `frontend/ui/mountBulkActions.jsx` (mounted once in `base.html` for signed-in users), and the new shared `ActionMenu` in `frontend/ui/controls.jsx` (styles in `controls.css`). Alpine and React talk through window events: `bulk-selection-change`, `bulk-actions-open`, `bulk-actions-done`, `bulk-actions-clear`, `bulk-job-finished`. Add Plays jobs persist in localStorage (`floppy-bulk-jobs`) and resume after navigation or reload.
- Data/transport: `app/bulk_action_views.py` (`bulk_status_update`, `bulk_show_plays_start`, `bulk_show_plays_status`, quick list/collection/tag endpoints unchanged), `app/services/bulk_show_plays.py`, `bulk_show_plays_task` on the default `celery` queue. Writes go through `apply_bulk_episode_plays`, the single-show Episode Plays path.
- Retirement: Alpine select-mode and card checkboxes retire when the media card selection is ported (see the media card entry). Legacy toolbar markup is removed.
- Reuse/blockers: no server fallback for the toolbar; if the island fails to mount, selection works but no actions show. Reopen if a no-JS path is required. Add Plays to History shows on non-TV lists and reports those items as skipped.
