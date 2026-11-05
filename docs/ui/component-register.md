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
- Status: `Partial / coexisting`. The signed-in sidebar (logo, media-type links with saved-view groups, the Explore section with pinning and pinned lists, Appearance, Settings, Logout) is React-owned through `frontend/ui/Sidebar.jsx` and `mountSidebar.jsx`, fed by `src/app/sidebar_model.py` and the `sidebar_react` tag. Icons travel as parsed shapes through one shared `Icon`. Pins, pinned lists and group open states keep their existing localStorage keys, so the list pin buttons on pages still work. The mobile open and close state, the top bar and the public shell stay Alpine and Django. The onboarding banner stays server-rendered and is placed into the sidebar. The Alpine sidebar markup stays inside the host as an active fallback: it is not `x-ignore`d, binds `sidebarNavigation`, and keeps Explore, Lists and every other secondary link usable if the React island fails to mount.
- Verification: `app.tests.test_sidebar_model` (props, active page, all 95 icons parse). Chromium (built-in browser, macOS): the sidebar mounts, Movies is active, Explore opens, pinning Calendar moves it and persists, a pinned list shows under Lists, saved-view reorder mode shows handles, and finishing it saved the new order on the server. A native drag, the delete confirm dialog and a phone-width open and close were not exercised. iOS and Android not tested.
- Verification: the fallback was exercised in Chromium with the React island blocked: Explore expands and Lists reaches `/lists`; `test_sidebar_model` now follows every secondary destination. Menu/focus parity still needs browser observation.
- Validation targets: `src/app/tests/views/test_boosted_navigation.py`, `src/app/tests/test_sidebar_model.py`; menu/focus parity needs browser observation.

### SETTINGS-CARD — Shared settings card shell

- Purpose/usage: provider Connection instance/personal credentials and account setup, Import preferences/options, and Metadata library source controls.
- Shared runtime: body responses compare the retained head's loader/CSS versions
  with the current build and reload after a stale boosted navigation. This applies
  to private and public shells without changing existing controls or their owners.
- Implementation: universal `frontend/settings/SettingsCard.jsx` and `frontend/settings/Chip.jsx`; browser link and palette adapter `Chip.web.jsx`; `mount.jsx`, `index.js`, `webPalette.js`, `settings-card.css`; `src/users/templatetags/ui_tags.py` and `src/templates/users/components/settings_card.html`. See [usage and ownership](settings-cards.md).
- Contract: one title/badge/help/frame pattern with editable/read-only/neutral and public API tones. `Chip` shares passive/action/link styling across status badges, media pills and the provider-key link, with consistent hover/focus highlights and no text underline. `Chip.web.jsx` keeps native anchors and new-tab attributes, uses a caller-supplied palette for React-owned cards and falls back to the scoped CSS-variable palette for server card wrappers. AniList supplies React-owned children; retained partial consumers keep their server body outside the header root. Existing backend permissions and CSRF remain authoritative.
- Data: presentation-only `json_script`; no credentials, server body HTML or transport in the shared React API. Shared source uses React Native primitives; `Chip.web.jsx` and `webPalette.js` supply browser links, DOM events and theme values.
- Status: `Web Migrated` shared card/chip presentation; native presentation is registered and rendered on Android, with iOS and interaction evidence still open. AniList uses full React composition; Audiobookshelf uses reusable account connection and manual-import islands. Other providers retain Django body slots and setup/restore dialogs until their controls are ported. This does not migrate `FORM-CONTROLS` as a whole.
- Native mapping: `SettingsCard` takes a title, badge/info chip and React-owned children; `Chip` takes a concrete palette, optional `onPress` action and accessibility props. Links remain a web-adapter concern.
- Native placement: `ported` in `native-proof/app/surfaces/SettingsCardSlot.jsx`; it renders a provider connection card and chip on the Settings screen. Android 15 Pixel 7 AVD rendered the shared card and chip; the help dialog, links, TalkBack/VoiceOver and iOS remain unverified.
- Verification: production assets build and collect through Django; targeted Django/theme tests and Chromium focus/link checks cover the shared card and chip. Android 15 Pixel 7 AVD rendered the shared card and chip on Settings; the help dialog, links, iOS and accessibility were not exercised. Expo export is a compile check, not runtime evidence.
- Related work: [#1793](https://github.com/dannyvfilms/Floppy/issues/1793); user-authorized first React browser component pilot.
- Deferrals: server-owned form bodies retire through scoped control ports after parity checks; native acceptance awaits full interaction/accessibility runs on both platforms and a native theme/transport boundary. Broader performance evidence remains required before larger component adoption.

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
- Left on legacy, with reopening condition: music album codec, bitrate and channels pills (they hold an SVG icon, which cannot be passed as props; reopen when `Badge` gets an icon slot from the shared icon set); `media_metadata_panel.html` source pill (11px, `py-0.5`, one site; reopen with the metadata panel port); `calendar_list.html` Today pill (server list fallback; the React calendar list uses `Badge`); person and studio filter links, `tag_index.html` and `discover.html` chips (links or buttons that belong to the filter chip family); `episode_row`, `detail_episode_track_button`, `detail_episode_collection_button` (action buttons); `detail_tag_preview.html` (tag colours come from stored tag data as class strings); `game_lengths_section.html` (hover and tracked-letter variant); `episode_ordering.html` and `match_fix.html` (state-dependent classes); `oauth_applications.html`, `progress_breakdown.html` (uppercase micro-label), `appearance.html` (segmented buttons). Each reopens when its page is ported or when its variant is added to `Badge`.
- Native mapping: shared `Text` and accessible `Pressable`; caller supplies palette styles and an `onPress` navigation action.
- Validation: `users.tests.test_badge_tag`, `users.tests.test_badge_browser`, architecture checks and tests, UI assets, and Expo web/iOS/Android exports.

### BUTTON — Solid action button

- Purpose/usage: the solid indigo (primary) or red (danger) button, the surface "Load more" button and the red text button that templates used to write by hand for form saves, submits and the odd htmx action.
- Status: `Partial / coexisting`. 78 sites in 30 templates are on the shared `Button` (74 plain or form-submit, 4 htmx: the two History Load more branches and two podcast history Delete buttons); 198 hand-written solid indigo or red `<button>` tags remain in 81 templates, plus roughly 1,000 other buttons of other looks (872 carry Alpine bindings). The shared tag mounts universal presentation through a browser platform implementation. The older `Button` in `frontend/ui/controls.jsx` and its React-island consumers remain legacy: the frozen `Dialog` and `ActionMenu` statements still use the local component, and the architecture checker forbids changing a legacy file's imports, so those consumers cannot switch imports without migrating those statements first (see below). Browser verification: the web bundle was built by `npm run build:ui`; no browser comparison was run. Native: Android 15 Pixel 7 AVD rendered the primary, surface and danger actions on Settings and Library; iOS, press/disabled behavior and accessibility remain unverified.
- Implementation: universal `frontend/ui/Button.jsx` uses React Native `Pressable`/`Text` with `label`, `tone` (primary, danger-solid, danger-deep, surface, ghost-danger), `size`, `width`, `disabled`, `busy`, `onPress`, `accessibilityLabel` and concrete palette values. Browser behavior stays in `frontend/ui/Button.web.jsx`: it renders the real `<button>` or `<a>` with the existing `.ui-button` classes, form submit types, links and allowed attributes. `frontend/ui/Button.native.jsx` exposes the same contract through the universal component. `frontend/ui/mountButton.jsx` mounts the web implementation as `data-button-root` from `frontend/settings/index.js`; the `{% button label tone size width submit= disabled= %}` tag (`users/templatetags/ui_tags.py`, `users/components/button.html`) and its server fallback are unchanged. The label is plain text, translated with `_("...")`. Allowed attributes pass through unchanged: `id`, `name`, `value`, `form`, `formaction`, `title` and any `hx_*`, `data_*` or `aria_*` (written with `_`, rendered with `-`; `hx-on*` is refused because it runs inline script). The server markup inside the host is the same `<button>`, so a form submit still submits and htmx still works if the script fails. The host is `display: contents`, so it adds no box. When React replaces the button it calls `htmx.process` on the host so htmx binds the new node. A host nested inside another island is skipped by the loader and keeps the server button. Radius follows `--theme-radius` and transition timing follows the theme motion tokens, as the old utility classes did. Keyboard focus keeps the browser's default ring, as the old buttons did; the shared 2px indigo ring stays on the AniList and provider buttons.
- Consumers: Account (authenticator and recovery codes, delete account), Media Cards settings, Custom lists (Trakt credentials, import), Provider settings bodies (`provider_import.html`: Connect, Sync now, Disconnect, Save and add-instance forms), Jellyfin and MAL sync (including the Connection tab's update and Disconnect forms), instance and personal credentials, TMDB proxy and rating sync, WeTrakr connect/save, reading-server modal, media type provider modal, onboarding (media types, metadata, import status, connect Trakt), OAuth device, match fix, collection modal and entry summary, music track notes, History "Load more" (htmx), podcast history Delete (htmx, ghost red), Advanced settings save, metadata duplicate repair, catalog grants, integration tokens, sync conflict resolution and the MyAnimeList connection forms.
- Left on legacy, with reopening condition:
  - `frontend/ui/controls.jsx`'s `Button` and its React-island consumers (`mountBulkToolbar.jsx`, `mountBulkActions.jsx`, `ListsForm.jsx`, `providers/Activity.jsx`, `Directory.jsx`, `FileImport.jsx`, `SettingsForm.jsx`, `Import.jsx`, `Credentials.jsx`, `AccountConnection.jsx`, `SetupGuide.jsx`, `Metadata.jsx`, `ImportPreferences.jsx`). The module's own frozen `Dialog` close button and `ActionMenu` trigger are the only remaining local uses. The checker allows a same-name re-export only from a registered universal or web implementation, so the export cannot move until both statements move to shared presentation; changing the consumers' imports directly is also frozen. Reopen when `Dialog` and `ActionMenu` move to shared presentation and the module can re-export the registered Button.
  - Buttons with Alpine bindings (`@click`, `x-show`, `:class`, `:disabled`; 872 tags): the host carries `x-ignore`, and Alpine attribute names such as `@click` cannot be set from React. Reopen when the owning dialog or toolbar is ported so its state lives in React, or when the adapter gets an event contract.
  - Buttons that htmx swaps in place of themselves (`hx-swap="outerHTML"` on the button: the list and tag Add/Remove toggles): htmx would replace a React-managed node. Reopen with a React toggle that owns its own request.
  - Buttons with an SVG or an included icon (about 26 solid ones, plus every icon-only button): an icon cannot be passed as props. Reopen when `Button` gets an icon slot from the shared icon set.
  - Buttons whose attribute values need template composition (`formaction="{% url ... %}?next=..."` in the album, artist and podcast track modals, list form and book image picker, `form=` in the episode watch row) or whose class, label or disabled state is chosen by template conditionals (`{% if tracker %}Update{% else %}Add{% endif %}`, "Add instance", "Sync now"/"Schedule Sync", TMDb Reconnect, onboarding Next/Continue, the split-button Radarr/Mylar3/Sonarr forms): reopen when the adapter accepts composed attributes, or when those forms are ported.
  - Look variants not yet in `Button`: sizes with `h-10`, `w-48`, `h-full` or `flex-1` (Connect and list credentials buttons), `rounded-r-md` split buttons, `rounded-lg` with `hover:bg-indigo-500`, `text-xs` compact buttons (`remap_search_results.html`, the `sync_state_section.html` conflict buttons), the tracker Delete (red when a tracker exists, grey when not), the segmented buttons in `appearance.html`, tab and chip buttons. Each reopens when its variant is added or its page is ported.
  - Links styled as buttons: the browser implementation covers `href`; no template site has moved yet.
- Native mapping: the universal `Button` uses `Pressable` and `Text`; callers supply concrete palette values and an `onPress` action instead of transport. `native-proof/app/surfaces/ButtonSlot.jsx` renders the primary Save, surface Load more and Sync now, and solid danger Delete and Disconnect actions in the Settings and Library screens.
- Native placement: `ported` in `native-proof/app/surfaces/ButtonSlot.jsx`. The slot renders the primary Save, surface Load more and Sync now, and solid danger Delete and Disconnect actions; the family remains partial while the controls.jsx islands and 198 hand-written solid buttons remain. Android rendered the actions; iOS, press/disabled behavior and accessibility remain unverified.
- Validation: `users.tests.test_button_tag`, `users.tests.views.test_provider_sync_templates`, `users.tests.views.test_provider_navigation`, `users.tests.views.test_advanced`, `users.tests.views.test_image_cache`, `users.tests.views.test_server_port`, `users.tests.test_settings_cards_browser`, `app.tests.test_anime_library_repair`, `npm run build:ui`, `npm run check:ui`, `npm run check:ui-architecture`, `npm run test:ui-architecture`, and the Expo export. Android rendered the actions; browser and iOS runtime were not exercised.

- Implementation: universal `frontend/ui/Button.jsx` uses React Native `Pressable`/`Text` with `label`, `tone` (primary, danger-solid, danger-deep, surface, ghost-danger), `size`, `width`, `disabled`, `busy`, `onPress`, `accessibilityLabel` and concrete palette values. Browser behavior stays in `frontend/ui/Button.web.jsx`: it renders the real `<button>` or `<a>` with the existing `.ui-button` classes, form submit types, links and allowed attributes. `frontend/ui/Button.native.jsx` exposes the same contract through the universal component. `frontend/ui/mountButton.jsx` mounts the web implementation as `data-button-root` from `frontend/settings/index.js`; the `{% button label tone size width submit= disabled= %}` tag (`users/templatetags/ui_tags.py`, `users/components/button.html`) and its server fallback are unchanged. The label is plain text, translated with `_("...")`. Allowed attributes pass through unchanged: `id`, `name`, `value`, `form`, `formaction`, `title` and any `hx_*`, `data_*` or `aria_*` (written with `_`, rendered with `-`; `hx-on*` is refused because it runs inline script). The server markup inside the host is the same `<button>`, so a form submit still submits and htmx still works if the script fails. The host is `display: contents`, so it adds no box. When React replaces the button it calls `htmx.process` on the host so htmx binds the new node. A host nested inside another island is skipped by the loader and keeps the server button. Radius follows `--theme-radius` and transition timing follows the theme motion tokens, as the old utility classes did. Keyboard focus keeps the browser's default ring, as the old buttons did; the shared 2px indigo ring stays on the AniList and provider buttons.
- Consumers: Account (authenticator and recovery codes, delete account), Media Cards settings, Custom lists (Trakt credentials, import), Provider settings bodies (`provider_import.html`: Connect, Sync now, Disconnect, Save and add-instance forms), Jellyfin and MAL sync (including the Connection tab's update and Disconnect forms), instance and personal credentials, TMDB proxy and rating sync, WeTrakr connect/save, reading-server modal, media type provider modal, onboarding (media types, metadata, import status, connect Trakt), OAuth device, match fix, collection modal and entry summary, music track notes, History "Load more" (htmx), podcast history Delete (htmx, ghost red), Advanced settings save, metadata duplicate repair, catalog grants, integration tokens, sync conflict resolution and the MyAnimeList connection forms.
- Left on legacy, with reopening condition:
  - `frontend/ui/controls.jsx`'s `Button` and its React-island consumers (`mountBulkToolbar.jsx`, `mountBulkActions.jsx`, `ListsForm.jsx`, `providers/Activity.jsx`, `Directory.jsx`, `FileImport.jsx`, `SettingsForm.jsx`, `Import.jsx`, `Credentials.jsx`, `AccountConnection.jsx`, `SetupGuide.jsx`, `Metadata.jsx`, `ImportPreferences.jsx`). The module's own frozen `Dialog` close button and `ActionMenu` trigger are the only remaining local uses. The checker allows a same-name re-export only from a registered universal or web implementation, so the export cannot move until both statements move to shared presentation; changing the consumers' imports directly is also frozen. Reopen when `Dialog` and `ActionMenu` move to shared presentation and the module can re-export the registered Button.
  - Buttons with Alpine bindings (`@click`, `x-show`, `:class`, `:disabled`; 872 tags): the host carries `x-ignore`, and Alpine attribute names such as `@click` cannot be set from React. Reopen when the owning dialog or toolbar is ported so its state lives in React, or when the adapter gets an event contract.
  - Buttons that htmx swaps in place of themselves (`hx-swap="outerHTML"` on the button: the list and tag Add/Remove toggles): htmx would replace a React-managed node. Reopen with a React toggle that owns its own request.
  - Buttons with an SVG or an included icon (about 26 solid ones, plus every icon-only button): an icon cannot be passed as props. Reopen when `Button` gets an icon slot from the shared icon set.
  - Buttons whose attribute values need template composition (`formaction="{% url ... %}?next=..."` in the album, artist and podcast track modals, list form and book image picker, `form=` in the episode watch row) or whose class, label or disabled state is chosen by template conditionals (`{% if tracker %}Update{% else %}Add{% endif %}`, "Add instance", "Sync now"/"Schedule Sync", TMDb Reconnect, onboarding Next/Continue, the split-button Radarr/Mylar3/Sonarr forms): reopen when the adapter accepts composed attributes, or when those forms are ported.
  - Look variants not yet in `Button`: sizes with `h-10`, `w-48`, `h-full` or `flex-1` (Connect and list credentials buttons), `rounded-r-md` split buttons, `rounded-lg` with `hover:bg-indigo-500`, `text-xs` compact buttons (`remap_search_results.html`, the `sync_state_section.html` conflict buttons), the tracker Delete (red when a tracker exists, grey when not), the segmented buttons in `appearance.html`, tab and chip buttons. Each reopens when its variant is added or its page is ported.
  - Links styled as buttons: the browser implementation covers `href`; no template site has moved yet.
- Native mapping: the universal `Button` uses `Pressable` and `Text`; callers supply concrete palette values and an `onPress` action instead of transport. `native-proof/app/surfaces/ButtonSlot.jsx` renders the primary Save, surface Load more and Sync now, and solid danger Delete and Disconnect actions in the Settings and Library screens.
- Native placement: `ported` in `native-proof/app/surfaces/ButtonSlot.jsx`. The slot renders the main tones and provider actions; the family remains partial while the controls.jsx islands and 198 hand-written solid buttons remain. Android 15 Pixel 7 AVD rendered the actions; iOS, press/disabled behavior and accessibility remain unverified.
- Validation: `users.tests.test_button_tag`, `users.tests.views.test_provider_sync_templates`, `users.tests.views.test_provider_navigation`, `users.tests.views.test_advanced`, `users.tests.views.test_image_cache`, `users.tests.views.test_server_port`, `users.tests.test_settings_cards_browser`, `app.tests.test_anime_library_repair`, `npm run build:ui`, `npm run check:ui`, `npm run check:ui-architecture`, `npm run test:ui-architecture`, and the Expo export. Android rendered the actions; browser and iOS runtime were not exercised.

### WEB-UTILITIES — Clipboard, installation and static service worker

- Purpose/usage: copy controls, install feedback and cached static assets.
- Implementation: `src/static/js/copy-item.js`, `serviceworker.js`, install hooks in `base.html` and `users/about.html`.
- Contract: feedback/availability, cache version/cleanup and request/auth boundaries. Static caching does not provide offline tracking.
- Data: DOM values, browser capabilities, service worker route in `src/app/views.py`.
- Reuse/blockers: copy intent shareable; install/service worker stay web-specific. Assess explicit exceptions when migrating a consumer.
- Validation targets: `src/app/tests/views/test_service_worker.py`, `src/users/tests/views/test_about_install_integration.py`, `src/app/tests/test_error_views.py`.
- Native shared presentation: `frontend/ui/CopyField.jsx` exports `CopyField` (selectable value, copy action, copied/error feedback and the shared recovery dialog); `frontend/ui/InstallPromptCard.jsx` exports `InstallPromptCard` (install availability, accepted/dismissed/failed copy, launch/installed state and platform steps); `frontend/ui/CacheStatusCard.jsx` exports `CacheStatusCard` (service-worker registration, controller, scope and floppy cache names, with honest not-applicable native copy). They reuse `SettingsCard`, `Chip`, `Button` and `ConfirmDialog`; clipboard, install prompt, guide launch and cache reads stay in platform adapters.
- Native adapters: `frontend/ui/clipboard.web.js` keeps the async Clipboard API plus the legacy selection/execCommand fallback (`copyText`); `frontend/ui/clipboard.native.js` uses the React Native Clipboard (`copyText`). `frontend/ui/installPrompt.web.js` reads the base.html prompt capture, consumes the one-use prompt and opens the guide (`getInstallState`, `subscribeInstallState`, `requestInstall`, `openInstallGuide`); `frontend/ui/installPrompt.native.js` reports the installed app and opens the guide in the platform browser. `frontend/ui/serviceWorkerStatus.web.js` reads the registration, controller and floppy caches (`getCacheStatus`); `frontend/ui/serviceWorkerStatus.native.js` reports web-only.
- Native placement: `native-proof/app/screens/WebUtilitiesScreen.jsx` renders copy fields, a diagnostic report, install/launch feedback and the static-cache card. Expo export is a compile check, not runtime verification.
- Status: `Partial / coexisting`. The browser keeps `copy-item.js`, the About install control and the base.html service-worker registration; the native screen uses the shared components and platform adapters with demo data. Physical-device clipboard, install/guide launch, cache reads, recovery dialog and accessibility remain unverified.

### ERRORS-DOCS — Error/recovery and API documentation pages

- Purpose/usage: 400/403/CSRF/404/500 and API documentation surfaces.
- Components: `ErrorStatusSelector`, `ErrorRecovery`, `ErrorReportPanel`, `ApiDocCommand`, `ApiCheatSheet`, `ApiGlossary`, `ApiSchemaLinks`, `ApiDocs`, `CopyBlock`.
- Universal implementation: `frontend/errors/ErrorRecovery.jsx` owns the status selector, error hero, quick checks, provider support note, recovery actions and traceback panel; `frontend/errors/ApiDocs.jsx` owns the task index, first-request and workflow commands, cheat sheet, status/media vocabularies, domain glossary and schema links; `frontend/ui/CopyBlock.jsx` owns the copyable report/command block and copied feedback. All take plain status/heading/message/checks/support/report/model props and concrete theme values; platform copy and link intents arrive as callbacks.
- Native placement: `native-proof/app/screens/ErrorDocsScreen.jsx` renders the five error variants with demo diagnostics, actual clipboard copy through the shell, report-issue and recovery intents, and the API documentation index. Status `ported`: the native screen renders the finished demo error and API content; iOS and Android runtime have not been exercised.
- Contract: safe diagnostic/report text, useful recovery links, permission boundaries and usable error documents without normal context or loaded app JS. The presentation never owns permissions, request data, credentials or navigation; the host supplies sanitized report text and intents.
- Data: `src/app/error_views.py`, error context and API schema routes.
- Remaining legacy: `src/templates/400.html`, `src/templates/403.html`, `src/templates/403_csrf.html`, `src/templates/404.html`, `src/templates/500.html`, `src/templates/includes/error_report_panel.html` and `src/templates/api/docs.html` remain the browser/server fallback. No web adapter mounts the shared presentation.
- Retirement: the server error documents and `api/docs.html` retire only when a browser adapter mounts the shared presentation with equivalent safe diagnostics, CSRF/login/recovery behavior, API links and a no-JS fallback. Keep the server fallback until then.
- Validation targets: `src/app/tests/test_error_views.py`, `src/app/tests/views/test_service_worker.py`, `src/app/tests/test_api_contracts.py`, `src/api/tests/test_public_endpoints.py`, `npm run build:ui`, `npm run check:ui`, `npm run check:ui-architecture`, `npm run test:ui-architecture` and the Expo export. Browser, iOS and Android runtime parity are unverified.

## Library, discovery and media presentation

### MEDIA-CARD — Canonical card and metadata lines

- Native implementation: `frontend/ui/MediaCardView.jsx` is the universal native card shell:
  poster, square, landscape and row layouts, artwork with a fallback chain, status
  and media-type chips, corner chips, progress, title and alternative title,
  subtitle lines, score and a rating affordance, plus read-only and selectable
  states. `MediaCardActions` adds the action overlay and row buttons (track,
  lists, history, Discover plan/hide action specs and list reorder controls) with
  explicit `onAction`, `onReorder`, `onReorderDrag` and reveal callbacks;
  `MediaCardActionRow` and `MediaCardActionButton` are its named exports. The
  reorder drag handle uses a native `PanResponder`, exposes `adjustable`
  increment/decrement accessibility actions and keeps the step buttons as the
  keyboard and screen-reader equivalent. `MediaCardActionHost` is the native
  popup shell for that callback contract. It consumes the same `card_model`
  shape, action specs and labels as the web card.
  `native-proof/app/surfaces/MediaCardSlot.jsx` renders it with realistic demo
  library items on Home, Discover and Library.
- Native action forms: `frontend/ui/ListsFormView.jsx` exports `ListsForm` and
  `frontend/ui/TrackForm.jsx` exports `TrackForm`, both presentation-only React
  Native forms with explicit loading, error, disabled, busy and validation states.
  `frontend/ui/MediaCardFormControls.jsx` provides `FormHeader`, `FormField`,
  `FormTextField`, `FormSelect`, `FormStatus` and `FormError`, with labels,
  descriptions, `radio` options, live-region messages and focus styles for the
  shared dialogs. `frontend/ui/mediaCardForms.js` holds the renderer-independent
  form models: `normalizeListsModel`, `listsMembership`, `listsCount`,
  `listsCountLabel`, `visibleLists`, `applyListToggle`, `normalizeTrackForm`,
  `initialTrackValues` and `validateTrackValues`. The lists form sends its toggle
  through `frontend/ui/ListsForm.web.jsx`, which owns the JSON fetch, CSRF header,
  `floppy-list-toggled` event and translated error state. `frontend/ui/TrackFormTabs.jsx`
  (`TrackTabs`) is the shared tab strip and body for Tags, Metadata, Collection,
  Plays/Episode plays, Status history and Discover, with per-tab loading, error,
  retry, empty and pending states. The native shell owns the transport:
  `native-proof/app/surfaces/mediaCardTransport.js` is a native-only adapter for
  the existing `/api/v1` media, state, tags, collection, history and Discover
  routes. It carries bearer-token or session/CSRF headers, joins the base URL
  from in-memory configuration, normalizes API payloads into the shared models
  and falls back to the demo models when no server is configured. The Track
  General body saves through `PATCH /api/v1/media/{type}/{source}/{id}/` for a
  tracked row and `POST /api/v1/media/{type}/` for a new one; Lists toggles
  through `PUT`/`DELETE /api/v1/media/{type}/{source}/{id}/lists/{list}/`.
  Drag drops persist the whole order through
  `PUT /api/v1/lists/{id}/items/order/`, and Discover planning/dismiss sends the
  full candidate payload to `discover/action`. Transport is not imported by
  universal presentation.
- Native status: `in_progress`. The existing web `MediaCard.jsx`,
  `mountMediaCard.jsx` and `ModalHost.jsx` remain the active browser card and
  popup host. The universal action presentation and callback contract are in
  place, including touch/hover reveal and selection rendering. Add-to-lists is
  now shared presentation on both web and native: `ListsForm.jsx` re-exports the
  registered `ListsForm.web.jsx` adapter, so the existing `ModalHost` keeps its
  JSON load, CSRF toggle, permissions, errors and `floppy-list-toggled` event.
  The Track body is shared presentation on native only; the web Track popup stays
  on the server-rendered htmx form. The native Track body loads live state,
  tags, metadata, collection copies, consumption history, status changes and the
  Discover hidden flag from the API, and writes the General form, tag membership,
  artwork URL, card score and Discover hide/unhide through the same transport. Its song and
  episode variants now share the same `TrackForm`: an episode uses the watch/drop
  routes and a music or podcast episode records a listen/play with its own date
  field. Discover planning and dismiss post through the server's existing
  `discover/action` route with the complete candidate payload and remove the
  candidate from the native grid; the Track Discover tab hide/unhide action
  publishes the same card-change event. Card reorder posts through the list
  reorder API, and every card mutation publishes a shared media-card change event
  that refreshes matching cards, including the bulk status refresh. The native
  drag gesture is in place; the web Track popup replacement and a full
  interaction/accessibility pass remain outstanding.
  iOS 17.2 simulator and Android 15 Pixel 7 AVD rendered the shared cards on Home
  and Library (and Detail on Android); Android demo images did not load, and no
  action overlay, form popup, variant form, drag, bulk refresh or
  TalkBack/VoiceOver pass was exercised.

- Purpose/usage: library, Home, related, search, Discover, lists, collection, credits and tier/group surfaces.
- Implementation: `src/templates/app/components/media_card.html`, `card_lines.html`, `media_card_list.html`, `src/app/card_surfaces.py`, template tags.
- Contract: declared surface/tag, viewer rating/status, aspect ratios, obfuscation, hover/touch actions, public/read-only/bulk states and stable OOB status wrappers.
- Data: `media_list_entries_for_items`, surface flags, card configuration and server projections.
- Reuse/blockers: highest leverage; [media-card contract](../architecture/media-card.md) authoritative. Replace consumers and response slots, never create an unrelated second card system.
- Status: `React-owned` for every card the `media_card` tag, `history_card_react` and `media_row_react` render. All 14 surfaces in `card_surfaces.py` set `react_card=True`; History (`history_card.html`) and the Search list row (`media_card_list.html`) use the same `MediaCard.jsx` (poster, square, landscape and `layout: row`). The artwork link, corner chips, progress bar, title and alternate-title tooltip, subtitle lines (including a credit's role line), status chip, rating button with its star popup, hover buttons (track, lists, history, Discover plan and hide, list reorder and drag handle), touch tap-to-reveal and bulk-select checkbox are all React (`MediaCard.jsx`, `mountMediaCard.jsx`, model in `media_card_model.py`). The track and lists popups open in the page's one React host (`ModalHost.jsx`); the cards carry no Alpine and no popup markup. `media_card.html` is now a shell: the card wrapper classes (themes and title settings still key off them), the props `<script>`, and a first-paint poster and title link inside the React host that React replaces on mount. The legacy server body, its Alpine fallback and the empty status, overlay and rating slots are deleted. `app.tests.test_media_card_contract.MediaCardInventoryTest` fails if a surface opts out of React, if the template regrows a legacy body, or if any template draws `media-card` markup that is neither the tag nor a documented exception.
- Remaining consumers and retirement: (1) Bulk select is still read from the page's Alpine scope (`selectMode`, `isItemSelected`, `toggleItemSelected`) by `mountMediaCard.jsx`. It retires when the Library bulk toolbar (`bulkSelection.js`, `mountBulkToolbar.jsx`, owned by another change in flight) publishes selection through a shared store; reopen then. (2) The save and score responses still send server fragments out of band (`media_card_status_chip.html`, `media_card_rating_oob.html`) for pages that render those slots; a React card ignores the swap (`data-react-owned`) and updates from `floppyCardUpdate`. They retire with the detail-page chips. (3) Documented exceptions that are different kinds of card, not this one: person and cast cards, Statistics highlights and the repeat-player strip, Now Playing, list index cards, and the music album and artist grids (they need an Album or Artist, not an Item). They are listed with reasons in `DOCUMENTED_EXCEPTIONS` in the contract test; reopen if a media item is ever drawn there. (4) The Search list row keeps its `meta` slot (server-rendered per-type metadata) inside the React host.
- Native blockers: the action presentation, Lists form, tabbed Track body,
  song/episode variants, drag reorder and Discover plan/hide are ported; the
  shared Track body is not yet wired into the web popup because the web save
  responses are htmx OOB fragments. A full interaction/accessibility pass remains.
  The shell's demo items are not a live account. Drag drops use the demo ordering's
  item-id map for the full-order endpoint; a live list model must carry the list's
  item ids for arbitrary drops, otherwise the adapter falls back to the
  first/back/next/last endpoint. Lists load the API's current page and the API list
  serializer does not expose list tags, so the tag filter is hidden in live mode;
  paged and tagged list loading remains. Render evidence is recorded above; an Expo
  export is only a compile check. The web DOM card remains the behavior source
  until those adapters exist.
- Fixed while proving it: a credit card lost its role line (for example "Developer, Publisher") once React took over; the track popup was unmounted the moment its form submitted, so htmx fired the save response (card refresh, toast) from a detached form and cards never updated after a tracker save (`ModalHost.jsx` now waits for the request); and a touch card hid its buttons again after its own popup was used.
- Browser verification (Chromium, built-in browser pane and Playwright, macOS, throwaway database and test login): Library grid (movie, game, book), Home, History, Collection, custom list grid, tier board and list table at desktop (1024 and 1280) and phone (375 and 390) widths, light and dark (system theme driven by the OS setting, plus the explicit `light` and `dark` classes). Before and after builds compared on 36 surface, width and theme combinations: 0.0% differing pixels and identical card geometry on all 36; the only DOM differences are the removed empty slot wrappers and the timing of the async release-year fill. Interactions exercised before this change: tracker popup open and save with live card refresh, the legacy lists popup add, rating popup and score change, touch tap-to-reveal, bulk select, status chip and no native `<select>` in any card. The shared Lists form was not exercised in a browser after this migration. Not exercised in a browser (no provider network in the test setup): Search (card and list row), Discover and hidden Discover, detail-page related and seasons cards, credit and group surfaces, modal search picker, list recommendations, smart lists, the media-type chip and alternative-title tooltip on a real title. Those are covered by `app.tests.test_media_card_contract` and `test_media_card_model`, which render every surface. Other theme presets (Dracula, Nord, Gruvbox, OLED, Glass, Custom) were not opened. iOS and Android: not tested.
- Validation targets: `src/app/tests/test_media_card_contract.py`, `src/app/tests/test_media_card_model.py`; complete native/consumer matrix outstanding.
- This change's verification: `scripts/test.sh app.tests.test_media_card_contract app.tests.test_media_card_model app.tests.views.test_track_modal api.tests.test_fork_lists lists.tests.test_views` (301 tests), `npm run build:ui`, `npm run check:ui`, `npm run check:ui-architecture`, `npm run test:ui-architecture` and `cd native-proof && npm run export -- --platform all` pass. No browser, simulator or device interaction pass was run; the Expo export is a compile check. Drag reorder, Discover plan/hide and bulk refresh are compiled but not exercised on a device; runtime evidence remains unverified.

### POPUP-HOST — Shared popup host, Add-to-lists form and Track form

- Purpose/usage: one host (`ModalHost.jsx`, mounted once from `base.html`) opens the popups that tracking actions need. Callers send a `floppy-open-modal` event with `{modal, url, vals, target, labels}`.
- Implementation: `frontend/ui/ModalHost.jsx`, `frontend/ui/ListsForm.jsx` (re-export of `frontend/ui/ListsForm.web.jsx`), `modal-forms.css`; `lists_modal_spec` in `src/app/media_card_model.py`; the `lists_modal_click` template tag in `app_tags.py`.
- Contract: `lists_modal` answers `?format=json` with a form model (item, lists with `hasItem` and tags, tag list, toggle URL, CSRF token); `list_item_toggle` with `format=json` answers `{success, hasItem}` or `{success:false, error}` (403 smart list, 404 stranger, 500/503 failure). Permissions, smart-list rule, retries, activity log and error text stay in the views. Labels travel in the open event, translated by the server.
- Status, Add-to-lists form: `Web Migrated` to shared presentation through
  `frontend/ui/ListsFormView.jsx` (`ListsForm`) and its browser transport adapter
  `frontend/ui/ListsForm.web.jsx`. The adapter keeps the JSON load, CSRF toggle,
  `floppy-list-toggled` event and error text; the view owns the dialog header,
  tag filter, count, Add/Remove rows, loading/error states and accessible close.
  Consumers remain the card hover button (grid, History, Search row) and 10 legacy
  buttons (`detail_action_buttons`, `detail_row_actions`, `detail_music_album`,
  `detail_music_track_actions`, `music_album_detail`, `episode_details`,
  `comic_issue_details`, `podcast_episode_list`, `history_card`, `media_card_list`).
  Their private Alpine `listsOpen` popups are deleted.
- Status, Track form: `Partial / coexisting`. The shared `TrackForm` renders the
  General tab body with explicit fields, dates, notes and validation inside the
  native `MediaCardActionHost`, with `TrackTabs` supplying Tags, Metadata,
  Collection, Plays/Episode plays, Status history and Discover bodies.
  `frontend/ui/mediaCardForms.js` supplies the model, initial values and
  validation. `native-proof/app/surfaces/mediaCardTransport.js` loads those tabs
  and writes General, tag membership, artwork URL, card score and Discover hide/unhide
  through the `/api/v1` bearer-token or session/CSRF boundary. The same form
  renders the song and episode variants: a date-only watch body with Drop for an
  episode, and a date-only listen/play body for a music or podcast episode.
  Every native save, delete, Discover action, reorder and bulk selection publishes
  a media-card change through `mediaCardEvents.js`, so matching native cards
  refresh without a page reload. The web popup remains the server-rendered
  `fill_track.html` htmx form, so this port does not yet replace the browser path.
  Blocker (evidence): the Track popup is not one form. `fill_track.html` is a
  seven-tab shell (General, Tags, Metadata, Collection, Episode plays, Status
  history, Discover) built from Django model forms that differ by media type, with
  three more variants (`fill_track_song.html` 13 KB, `fill_track_episode.html`,
  `fill_track_episode_bulk.html`), roughly 83 KB of included Alpine templates
  (date-time picker 11 KB, metadata panel 34 KB, collection fields, notes editor),
  a 1,461-line builder (`track_modal_views.py`) and 2,399 lines of tests. Its save
  views answer with htmx out-of-band fragments (status pill, score chip, progress
  card, notes) and `HX-Trigger` events, so the web adapter must keep posting
  through htmx. About 34 templates still own a `trackOpen` popup. The native
  change event refreshes native cards in the same shell; it cannot refresh a web
  card in another runtime, and the browser path still needs the htmx adapter.
- Reopening condition and plan: (1) the native General, Tags, Metadata, Collection,
  Plays, Status history and Discover bodies are ported and use the API adapter;
  (2) the song and episode variants share the same General body and transport;
  (3) Discover plan/hide, card reorder and the shared card-change event are wired;
  (4) the remaining web step is a Django-form-to-JSON model and a
  `TrackForm.web.jsx` adapter that submits with `htmx.ajax` so the existing
  responses keep working, then the `trackOpen` popups can be replaced. The web
  Track adapter is the next blocker.
- Remaining consumers and retirement: `fill_lists.html` is still returned for non-JSON requests; it retires with the existing `ListsModalViewTests` HTML assertions once the Track form leaves htmx popups, or sooner if no caller needs it. `list_item_button.html` is the same.
- Browser verification before this change (Chromium, built-in browser pane, macOS, throwaway database and test login): the legacy `ListsForm` opened from a Movies grid card (desktop, dark) and a movie detail page (phone width, light); added a list (spinner, then "On 1 list" and Remove), filtered by tag, forced a network failure (inline error, list unchanged), Escape closed it. The shared `ListsForm`/`ListsForm.web.jsx` replacement was not exercised in a browser during this change. Not checked: history/episode/table-row entry points, other theme states beyond dark and light, a screen reader. iOS and Android: not verified.
- Validation targets: `lists.tests.test_views.ListsModalViewTests`, `ListItemToggleTests`, `app.tests.test_media_card_contract`.

### RATING — Score display and picker

- Purpose/usage: cards, details, children and music scores.
- Status: `Partial / coexisting`. The detail personal score chip and its rating popup are React-owned through the shared `RatingChip` and `RatingStars`. The media card's rating button and popup are also React-owned (`CardRating`). Episode/track/row rating buttons, music artist/album pages, the comic issue page and the provider score chips (TMDB/Trakt/IMDb/MAL/IGDB/OpenCritic) remain legacy Alpine/HTMX. Android 15 Pixel 7 AVD rendered the shared chip on Detail; iOS is not verified, and the popup, selection and accessibility interactions were not exercised. Browser: not exercised in this change; the Expo export and web bundle compile.
- Implementation: shared RNW `frontend/ui/RatingChip.jsx` and `frontend/ui/RatingStars.jsx`, the web adapters `frontend/ui/mountRatingChip.jsx` and `frontend/ui/mountRatingStars.jsx`, `frontend/ui/RatingStarIcon.web.jsx` / `.native.jsx`, the `rating_chip` and `rating_stars` tags (`users/templatetags/ui_tags.py`), `rating_chip.html`, `rating_stars.html` and `rating_picker.html` (Alpine wrapper for the remaining consumers). The detail chip keeps its existing server markup as a progressive fallback; the web adapter hides it on mount. Legacy: `detail_episode_rating_chip.html`, `detail_row_rating_button.html`, `media_card_rate_button.html`, `media_card_rating.html`, OOB/score-chip/derived-TV fragments and provider score chips.
- Native placement: `ported` in `native-proof/app/surfaces/RatingSlot.jsx`, which renders the detail score chip and popup. Android 15 Pixel 7 AVD rendered the shared chip on Detail; the popup, selection, TalkBack/VoiceOver and iOS remain unverified.
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

- Purpose/usage: library/lists, History and Home configuration where included.
- Implementation: universal `frontend/ui/FilterBar.jsx` (media type, status, sort, view, range and saved-view sheets); browser intent bridge `frontend/ui/mountFilterBar.jsx`; server toolbar `src/templates/app/components/filter_menu.html`, `filter_form.html`, `filter_toolbar.html`, `filter_range_panel.html`, `filter_toolbar_scripts.html`, `sidebar_saved_views.html`; state `src/static/js/libraryFilterState.js`, `savedViews.js`.
- Contract: normalized rules, clear/default/relative/multi-value ranges, selected/disabled/busy states, accessible trigger and option labels, responsive sheet layout, sort direction, layout view and saved-view selection. `FilterBar` receives normalized state and options and emits intents; it does not parse URLs or own transport. The browser adapter mirrors the page's Alpine state, writes intents into the existing hidden form and refreshes through `applyFilterChange`, preserving the server fallback and one runtime owner.
- Data: owning view catalogs, shared library query, authoritative `src/app/media_list_filters.py` parser, `src/lists/smart_rules.py`, saved-view endpoints in `src/users/views.py`. The shared parser is not duplicated in JavaScript.
- Status: `Partial / coexisting`. `FilterBar` is the native-compatible presentation and is rendered on the Library screen of the native shell; web library/list/History toolbars remain the existing server/Alpine implementation. No web consumer was replaced because browser parity for the full menu surface is not yet proven.
- Native placement: `ported` in `native-proof/app/surfaces/FiltersSlot.jsx`. Android 15 Pixel 7 AVD rendered the shared bar on Library; iOS and a full filter/range/saved-view interaction pass remain unverified.
- Reuse/blockers: strong state reuse; preserve per-surface availability. URL/history, forms, focus management, localStorage and SortableJS remain web boundaries. Retirement requires mounting the browser adapter on a surface, proving menu/range/saved-view parity in a browser, and then removing that surface's Alpine panes while retaining the server fallback.
- Verification: Expo export --platform all compiles the shared bar through the native shell. Android 15 Pixel 7 AVD rendered the shared bar on Library; no filter, range or saved-view interaction was exercised, and no browser interaction pass was performed. `app.tests.test_media_list_filter_parser`, `lists.tests.test_list_detail_filters` and `lists.tests.test_smart_list_semantics` cover the authoritative parser and list filtering.
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
- Native placement: `native-proof/app/surfaces/BulkSlot.jsx` renders selection, cards, toolbar, dialogs and the Add Plays review/job dock with shared `Button`, `MediaCardView` selection state and the shared `BulkJobCard`/`BulkJobProgress`/`BulkJobSummary`/`BulkJobProblems` presentation. A finished status or plays action publishes a media-card change for the selected identities, so a card grid mounted afterwards reflects it through the shared native event bus. Server writes and the browser's real Add Plays transport remain web-owned.
- Validation targets: `src/app/tests/views/test_bulk_actions.py`, `src/lists/tests/test_bulk_actions.py`.

### SEARCH — Global autocomplete, results, parent pickers and barcode input

- Purpose/usage: header/page search, media-type and provider-source scope, result cards/list rows, matched titles, paging/load-more, empty/loading/error states, parent TV show/season and music album selection, and barcode input.
- Implementation: universal `frontend/ui/GlobalSearch.jsx`, `frontend/ui/SearchResults.jsx` and `frontend/ui/ParentPicker.jsx`; browser adapters `frontend/ui/GlobalSearch.web.jsx`, `frontend/ui/SearchResults.web.jsx`, `frontend/ui/ParentPicker.web.jsx` and `frontend/ui/barcodeEntry.web.js`; native barcode boundary `frontend/ui/barcodeEntry.native.js`; mounts `frontend/ui/mountGlobalSearch.jsx`, `frontend/ui/mountSearchResults.jsx` and `frontend/ui/mountParentPicker.jsx`; server props from `app_tags.global_search_react`, `app_tags.search_results_react` and `app_tags.parent_picker_react`; JSON suggestion contract in `search_views.search_suggestions` (`format=json`) and parent rows from the existing `search_parent_tv`/`search_parent_season` endpoints (`format=json`). `src/templates/app/search.html`, search parent fragments, `searchAutocomplete.js`, `searchShortcut.js`, `searchParentFallback.js` and `barcode-scanner.js` remain the results fallback and browser-decoding paths. Native placement is `native-proof/app/surfaces/SearchSlot.jsx` for the form, `SearchResultsSlot.jsx` for paged results and source scope, and `SearchParentSlot.jsx` for the TV show/season and music album pickers.
- Contract: input, media-type menu, loading/empty/error suggestion states, active-descendant Arrow/Enter navigation, the search-online footer and two-character minimum. `SearchResults` renders provider-source scope, grid/list layout, local and online headings, matched titles, counts, empty/loading/error states, bounded paging or load more, the per-group online-search action and an optional parent-picker panel. `ParentPicker` accepts a query, rows, selected id, ready/loading/empty/error state, labels, palette and select/retry callbacks. `barcodeEntry` exposes one `requestBarcode({ labels })` contract: the web adapter runs the existing file-picker/ZXing flow; the native adapter reports `unavailable` until a camera module can decode book barcodes. The web adapters keep the GET search action, URL/history, session cookies, card/modal actions and rating writes; the universal components expose those as platform callbacks. The no-JS `<form>` and server-rendered results stay inside their hosts as fallbacks.
- Data: the JSON suggestion path returns `{suggestions: [{id, title, subtitle, image, url}]}` only; presentation labels arrive through the existing `json_script` props. The results payload contains plain card models, section descriptors, source/layout URLs and paging descriptors; no server HTML reaches universal presentation. Parent pickers receive plain row descriptors; the create-entry adapter reads rows from the existing htmx endpoints and writes the hidden parent input, while the server fragments keep the fallback select behavior.
- Reuse/blockers: the results surface reuses `MediaCardView` for grid and row results and `RatingStars` through the web/native platform boundary. Local and online music artist/album cards use the same card model. The universal `ParentPicker` is placed on the native Search screen for parent TV shows, seasons and music albums and now owns the create-entry web TV-show and season fields through `ParentPicker.web.jsx`; the server fragments remain a no-React fallback, and the web create-entry form has no music parent field. Native barcode scanning still needs a camera/barcode module that decodes EAN/ISBN on both platforms; the shell reports the entry point as unavailable instead of faking a scan.
- Status: `Web Migrated` for the search form and results page. The header form, suggestions, media-type menu, result scope, source/layout controls, result cards and rows, empty state, paging and online-search actions are React-owned through the shared components; the server markup remains only as the no-JS/fallback path. The universal parent picker is now adopted by the create-entry web TV-show and season fields; the native music album picker remains native-only because the web form has no music parent field. Native placement is `in_progress` in the search surfaces; Android previously rendered the form and results, iOS previously rendered the form, and paging, parent pickers, barcode entry, interaction and accessibility remain unverified at runtime. `barcodeEntry.web.js` preserves the browser flow; `barcodeEntry.native.js` is an honest unavailable result.
- Verification: `app.tests.views.test_media_search`, `app.tests.test_search_suggestions`, `app.tests.views.test_search_parent`, `node src/static/js/barcode-scanner.selfcheck.mjs`, `npm run build:ui`, `npm run check:ui`, `npm run check:ui-architecture`, `npm run test:ui-architecture` and `cd native-proof && npm run export -- --platform all` pass. Expo export is a compile check, not runtime evidence. Android and iOS runtime behavior for the new paging, parent pickers and barcode boundary was not exercised in this pass; the create-entry parent picker was not exercised in a browser either.
- Retirement condition: delete the server form and htmx suggestion binding when the no-JS fallback is no longer required; retire the server results markup when the no-JS fallback is no longer required. Retire `searchParentFallback.js` and the server parent fragments when the no-JS fallback is no longer required. Register a native camera/barcode module and record iOS/Android scans before claiming native barcode entry.
- Validation targets: `src/app/tests/test_search_suggestions.py`, `src/app/tests/views/test_media_search.py`, `src/app/tests/views/test_search_parent.py`, barcode selfcheck.


### RAILS — Horizontal scrolling and load more

- Purpose/usage: Home, cast, recommendations and related rows.
- Implementation: `frontend/ui/Rail.jsx` is the universal rail and `frontend/ui/Rail.web.jsx` is its browser behavior adapter. `src/templates/app/components/_scrollable_row.html`, `_scrollable_row_js.html` and `src/static/js/horizontal-scroll.js` remain the web implementation. The native shell renders demo rails in `native-proof/app/surfaces/RailsSlot.jsx`.
- Contract: heading/collapse state, arrows/drag/touch, suppress post-drag clicks, bounded load-more, stable art anchors and listener cleanup. `Rail` takes `items`, `renderItem(item, index)`, a stable `itemWidth`, `onLoadMore`/`hasMore`/`loadingMore`, heading and accessibility labels; the browser adapter keeps pointer drag, click suppression, keyboard arrows and focus behavior.
- Data: row descriptors/fragment URL/item template from owning view. The web path still swaps server fragments through HTMX; the shared rail accepts already-resolved items and a renderer.
- Reuse/blockers: row/item values shared; scrolling/observer/pointer/persistence adapters required. The native shell currently renders demo tiles because the native media card action layer is still in progress, so the rail's item slot is proven only with demo renderers.
- Status: `Partial / coexisting`. The universal `Rail` and browser adapter are registered; no production web call site was replaced. Home, detail cast/crew/recommendations, person strips, collection rows and statistics still use `_scrollable_row.html` because parity depends on server HTML fragments and the native media card's action layer is still in progress.
- Native placement: `ported` in `native-proof/app/surfaces/RailsSlot.jsx`, which renders two production-shaped shelves with headings, sort direction, load more and a note. iOS 17.2 simulator rendered the shared rail on Home; scroll, load-more, Android and VoiceOver interaction remain unverified.
- Retirement condition: a bounded Django row adapter passes resolved items and a ported card renderer to `Rail`, and the HTMX load-more path is replaced by the bounded callback with equivalent scroll, retry, exhaustion and cleanup behavior.
- Verification: `app.tests.test_horizontal_scroll`, `src/static/js/horizontal-scroll.selfcheck.mjs`, `npm run build:ui`, `npm run check:ui`, UI architecture checks and `expo export --platform all`. iOS 17.2 simulator rendered the shared rail on Home; browser, Android, scroll/load-more interaction and accessibility remain **unverified**.
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
- Status: `Partial / coexisting`. The shared `DetailComposition` owns the native detail composition: hero artwork, title/subtitle, year/runtime/facts, synopsis, primary actions, configurable sections and public/read-only states. On the web, `DetailCompositionTheme.web.jsx` mounts the shared synopsis over the server fallback; the title block, activity subtitle, primary/secondary actions, score chips, poster/carousel, lazy carousels and secondary sections stay server-owned so permissions, htmx dialogs and section configuration are unchanged. Android 15 Pixel 7 AVD rendered the shared composition on Detail; iOS, interaction and accessibility remain unverified, and this change did not run a browser.
- Implementation: universal `frontend/ui/DetailComposition.jsx` (`DetailComposition`, `DetailHeader`, `DetailSynopsis`, `DetailActions`, `DetailSection`), the browser adapter `frontend/ui/DetailCompositionTheme.web.jsx`, `frontend/ui/mountDetailComposition.jsx`, the `detail_composition` tag in `src/users/templatetags/ui_tags.py` and `src/templates/app/components/detail_composition.html`. The tag serializes presentation values only; it never passes server HTML, forms or credentials. The legacy synopsis in `media_details.html` remains the progressive fallback.
- Contract: responsive artwork/title/facts, expandable synopsis, primary actions, ordered/configurable sections, and public/read-only states. Preserve the existing server section order and visibility, lazy carousel loading, score-chip and notes/history refresh boundaries, and the provider Series Graph's color-coded season/episode score grid, source link, deferred loading and dialog dismissal.
- Data: `src/app/media_details_views.py`, `season_details_views.py`, detail builders and user layout configuration.
- Native mapping: React Native `View`/`Text`/`Image`/`Pressable` with the shared `Badge` and `Button`; callers supply concrete palette values and action callbacks. Tracking transport, dialogs, provider graphs and child rows are not part of this component.
- Native placement: `ported` in `native-proof/app/surfaces/DetailSlot.jsx`; the native Detail screen renders it above the existing rating, progress and children sections. Android 15 Pixel 7 AVD rendered the shared composition; actions, synopsis expansion, TalkBack/VoiceOver and iOS remain unverified.
- Consumers: the native Detail screen and the web detail synopsis. The web title block, activity subtitle, action row (tracking, links, tags, notes, lists, history, sync, Seerr), score chips, poster/carousel and secondary content remain legacy.
- Retirement: the legacy synopsis fallback retires with the progressive-enhancement policy. The web title/facts, action row and carousel retire when their htmx dialogs, season navigation, lazy fragment and activity-subtitle refresh have proven shared adapters; child rows, tracking dialogs and the provider graph remain separate ports.
- Verification: `app.tests.views.test_media_details`, `app.tests.test_detail_builders` and `app.tests.views.test_save_response_fragments` cover the server fallback and fragments; `npm run build:ui`, architecture checks and the Expo export compile the shared files. Android 15 Pixel 7 AVD rendered the shared composition on Detail; browser, iOS, action/synopsis interaction and accessibility were not exercised.
- Validation targets: `src/app/tests/views/test_media_details.py`, `test_save_response_fragments.py`, `src/app/tests/views/test_trakt_series_graph.py`, `src/app/tests/test_detail_builders.py`.
- Book format links: a "Format" fact in the Details card of Book pages that joins the formats the viewer tracks, e.g. "Book, Audiobook", each name a link except the page being viewed. It replaces the provider's own Format fact when the viewer tracks another format of the same work; several audiobooks are told apart by narrator. Status: legacy, not migrated. Blocker: the Details card is a server-rendered fact list with no shared React equivalent, and porting it is a whole-card migration, not part of this change. Reopen when the DETAIL sidebar Details card gets a shared React component; the hero facts are now shared but this sidebar fact list is still server-rendered, so this row moves with the card. Data: `build_book_formats` (ISBN, or title plus author, among the viewer's own tracked books; never merges Items). Verification: browser only; no iOS/Android.
- Book narrator: a "Narrator" fact in the same Details card for Audiobookshelf audiobooks (`Item.narrators`, filled by the ABS importer, carried in the generic details payload). Status: legacy, same blocker and reopening condition as Book format links. Verification: browser only; no iOS/Android.
- Audiobook listening sessions: each Audiobookshelf listening session is a dated entry (date, time, duration, and where listening stopped) in the activity history modal and the History page, through the existing `session_history_row.html` row (one new "stopped at" fragment in that legacy template), so no new component. Status: legacy row, coexisting; the row has no shared React counterpart yet, and it moves when the history rows do. Data: `BookListeningSession` rows written by the Audiobookshelf importer, emitted by `history_cache_day_builder` and indexed by `history_cache_index`. Counted in Statistics as a separate "Listening Time" figure, never added to page totals. Verification: browser only; no iOS/Android.
- Book page history: a page-based (non-audiobook) book gets one dated entry per day its progress rose, built from its change log ("52 pages · at page 212 / 480"), in the same activity history modal and History page through the same `session_history_row.html` row (a new "at page" fragment in that legacy template). A book's first change-log row is a baseline and dates nothing, so a current page or percentage alone never produces history. Status: legacy row, coexisting. Blocker: the history row and the Statistics reading section are server-rendered Django templates with no shared React counterpart, and porting either is a whole-surface migration. Reopen when History rows or the Statistics reading cards get a shared React component. Data: `build_book_page_entries` over `HistoricalBook`, indexed by `history_cache_index`. Verification: browser only; no iOS/Android.
- Statistics "Listening Time": a stat card at the top of the Books Activity Overview (`reading_consumption_section.html`, `data-listening-time`) showing audiobook listening minutes for the range, kept apart from page counts (audiobook progress no longer feeds "pages", top items, completed-length chart or reading genres). Status: legacy, not migrated; same blocker and reopening condition as Book page history. Data: `BookListeningSession` minutes summed per day in `statistics_day_builder` (`totals.listening_minutes`), marked dirty by the session signal. Verification: browser only; no iOS/Android.

### CHILDREN — Seasons, episodes and issue rows

- Purpose/usage: episode/season/comic detail and child lists.
- Implementation: universal `frontend/ui/DetailChildren.jsx` (`DetailChildren`, `DetailSeasonList`, `DetailSeasonRow`, `DetailEpisodeRow`, `DetailIssueRow`, `DetailHistoryDialog`) rendered by `native-proof/app/surfaces/DetailChildrenSlot.jsx`. The web keeps `src/templates/app/episode_details.html`, `comic_issue_details.html`, the episode/issue/season/action/obfuscation/scroll fragments and `src/templates/app/components/detail_secondary_content.html`.
- Contract: the shared presentation renders server-ordered seasons/episodes/issues with the shared `MediaCardView` row, season progress and status, episode/issue scores through `RatingStars`, watch/unwatch/read/unread/drop/restore/check-in and history actions, spoiler obfuscation with per-row reveal, an optional ordering control and a history dialog. It receives data, palette, labels and explicit action/rate/history intents; it does not own tracking transport, permissions, HTMX swaps, scroll restoration or the server row markup.
- Data: `src/app/media_details_views.py`, `season_details_views.py`, detail/save/score handlers and source/media/season/episode coordinates. Server permissions, ordering, obfuscation preference, row/watched state and history remain authoritative on the web.
- Reuse/blockers: reuses `MEDIA-CARD` rows, `RATING` stars/chip, `BUTTON`, `BADGE` and the shared progress bar; the detail progress card is `PROGRESS`. The web child rows are server/HTMX-owned until a browser adapter maps equal intents, so browser parity is not proven. Native check-in is presentation only; the row Track action opens the shared `TRACKING` dialog with demo data and still does not write through a transport.
- Status: `Partial / coexisting`. The native Detail screen renders realistic season, episode and issue rows with local watch/unwatch, read, drop, check-in, score, spoiler reveal, ordering and history-dialog state. The web detail and episode pages remain server-rendered and keep their permissions, HTMX tracking semantics, season-status polling and server fallback.
- Native placement: `ported` in `native-proof/app/surfaces/DetailChildrenSlot.jsx`. No iOS or Android runtime pass was performed in this change; the Expo export is a compile check only.
- Verification: `app.tests.views.test_media_details`, `test_episode_history_poll`, `test_episode_score_invalidation`, `test_season_status_pill_sync`, `npm run build:ui`, architecture checks and the Expo export. Browser, iOS, Android, interaction and accessibility were not exercised.
- Validation targets: `src/app/tests/views/test_episode_history_poll.py`, `test_episode_score_invalidation.py`, `test_season_status_pill_sync.py`, `test_media_details.py`.
- Retirement: the server episode/issue/season row templates retire when a browser adapter mounts the shared rows with equivalent ordering, permissions, obfuscation, history, scroll restoration and HTMX response fragments; keep the server fallback until then.

### TRACKING — Add/edit/repeat/bulk logging

- Purpose/usage: detail and episode tracking dialogs, repeat logging and manual creation.
- Implementation: universal `frontend/ui/TrackDialog.jsx` (`TrackDialog`) hosts the shared `TrackForm`, `TrackTabs`, `MediaCardFormControls`, `DateTimePicker` and `RatingStars`; `frontend/ui/TrackForm.jsx` now also renders rating fields and secondary repeat actions. Native placement is `native-proof/app/surfaces/DetailTrackingSlot.jsx`, opened from the native Detail tracking action and from episode/issue row Track actions. The web keeps `src/templates/app/components/fill_track.html`, `media_metadata_panel.html`, the episode/music/podcast modals, `src/static/js/mediaStatusDateHandler.js`, `episodeBulkTrackForm.js` and `fill_track_episode_bulk.html` as the server-owned path.
- Contract: General, Tags, Metadata, Collection, Episode plays and Status history tabs; status/start/end/progress coupling; notes; delete; repeat identity (save as new entry, rewatch start/end); client validation, busy, loading, retry and server-error presentation. The dialog receives the model, values, tabs, labels, palette and explicit change/save/delete/retry/tag/artwork/repeat intents; it does not parse URLs, own permissions or write through a transport. Django forms, ownership checks, OOB fragments and redirects remain authoritative on the web.
- Data: `src/app/track_modal_views.py`, `save_views.py`, Django forms, music/podcast handlers and `src/app/services/tracking_hydration.py`.
- Status: `Partial / coexisting`. The native Detail screen renders the shared tracking dialog with realistic demo data, local tab/asset/tag/repeat state and no transport. The web detail and episode pages remain server-rendered and keep their htmx swap, OOB refresh, CSRF, permissions, delete/rewatch routes and progressive fallback.
- Native placement: `ported` in `native-proof/app/surfaces/DetailTrackingSlot.jsx`; the native Detail tracking action opens the show form and episode/issue Track actions open the repeat form.
- Reuse/blockers: reuses `MEDIA-CARD` controls, `DATE-TIME`, `RATING` stars and the shared `Button`; no parallel form or card system was added. The web Track popup has no browser adapter yet, native writes are demo-only, and duration progress coupling applies where the server model exposes a text duration rather than episode/page counts.
- Verification: `app.tests.views.test_track_modal`, `test_media_details` and `test_rewatch` cover the server form, detail page and repeat semantics; `npm run build:ui`, `npm run check:ui`, architecture checks and the Expo export compile the shared files. Browser, iOS, Android, interaction and accessibility were not exercised in this change.
- Validation targets: `src/app/tests/views/test_track_modal.py`, `test_episode_bulk_save.py`, `test_music_bulk_save.py`, `test_rewatch.py`.
- Retirement: the server track modals retire when a browser adapter mounts the shared dialog with equivalent htmx/OOB fields, permissions, repeat identity, tag/artwork/collection operations and save-error behavior; keep the server fallback until then.

### DATE-TIME — Field picker and activity calendar

- Purpose/usage: tracking dates and session history, distinct from release calendar.
- Status: `Partial / coexisting`. The shared React Native `DateTimePicker` owns the field, quick actions, month/year navigation, six-week grid, optional 12/24-hour time, marked/selectable days, hidden value contract and dismiss/focus behavior. The browser adapter mounts it into the static tracking fields and keeps the hidden input, htmx input events, status autofill, paired start/end dates, copy/clear and saved week-start/12-hour preferences. Bulk episode forms whose suggestion dates are Alpine expressions keep the frozen `date_time_picker_legacy.html` include.
- Shared logic exports: `pad2`, `dateKey`, `parseDateValue`, `normalizeValue`, `formatValue`, `valueFromDate`, `formatDisplayText`, `monthLabel`, `monthShortLabel`, `weekdayLabels`, `monthWeeks`, `yearPage`, `isSameDay`, `isToday`, `displayHour`, `meridiem`, `hour24FromDisplay`, `stepHour`, `stepMinute`, `stepSecond`, `isMarkedDay`, `isSelectableDay`, `nowParts`.
- Implementation: universal `frontend/ui/DateTimePicker.jsx` with shared calculations in `frontend/ui/dateTime.js`; browser adapter `frontend/ui/mountDateTimePicker.jsx`; host template `src/templates/app/components/date_time_picker_react.html` and the `date_time_picker` tag in `src/users/templatetags/ui_tags.py`. Legacy consumers: `src/templates/app/components/date_time_picker_legacy.html`, `calendar.html`, `src/static/js/dateTimePicker.js`, `calendar.js`, and the activity calendar in `session_history_modal.html`.
- Contract: clear/current/release/copy, optional time, 12/24h/week-start/locale supplied explicitly, six-week grid/month/year, marked/selectable days, hidden values/events and Escape. The shared presentation uses the value and callbacks only; the browser adapter owns form and Alpine integration.
- Data: owning field/history configuration, user week-start and time-format preferences, suggestion/runtime values and copy source.
- Reuse/blockers: the React picker is native placement complete in the shell; the React web path is limited to static tracking fields until expression-driven suggestions become explicit events. The release calendar grid is `RELEASE-CALENDAR`, not this port. Timezone-specific behavior and the remaining activity-calendar web surface are not verified.
- Native placement: `ported` in `native-proof/app/surfaces/DateTimeSlot.jsx`. Android 15 Pixel 7 AVD rendered the shared field on Calendar; no picker, time or timezone interaction was exercised, and iOS is unverified.
- Verification: targeted tracking/modal and history tests plus `npm run build:ui`, architecture checks and Expo export. Android 15 Pixel 7 AVD rendered the shared date-time field on Calendar; browser interaction, picker interaction, timezone behavior, iOS and accessibility remain unverified.
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
- Status: `Partial / coexisting`. The quick +/- controls on Home in-progress cards are React-owned by the shared `ProgressChanger`. The detail progress card and its Alpine modal shell remain legacy, but the season/episode breakdown rendered inside that modal is React-owned through the shared `ProgressBreakdown`. Native card and breakdown presentation exist; Android 15 Pixel 7 AVD rendered the card on Detail, but the breakdown was not opened and iOS is unverified. Browser verification is not claimed for the mounted breakdown.
- Native placement: `ported` in `native-proof/app/surfaces/ProgressSlot.jsx`; it renders the card and an expandable breakdown. Only the card render is runtime-verified (Android), not the breakdown or its interactions.
- Implementation: universal `frontend/ui/ProgressBar.jsx`, `ProgressCard.jsx` and `ProgressBreakdown.jsx` take explicit values, season/episode view models, labels, palette, expansion state and callbacks. `ProgressBreakdownTheme.web.jsx` and `mountProgressBreakdown.jsx` mount the shared breakdown into the htmx-rendered modal body, keep theme resolution and season/episode navigation, and hide the server fallback. The legacy modal header keeps the htmx `cancel_progress_rewatch` form. `ProgressChanger` continues to use `frontend/ui/ProgressChanger.jsx`, `ProgressChangerTheme.web.jsx` and `mountProgressChanger.jsx`. `src/templates/app/components/progress_breakdown.html` keeps its Alpine/HTMX markup as the fallback; `detail_progress_card_slot.html` and `progress_changer.html` remain their own owners.
- Contract: card title/subtitle, watched-once percentage and bar, current-pass glow and label, info tooltip, open-breakdown intent; breakdown totals, minutes left, catalogue-unavailable notice, expand/collapse all, per-season dropped/not-aired/percentage and rewatch lines, episode watched/unwatched/upcoming rows with again-watched glow, cancel-rewatch intent, loading/error/empty states, progressbar accessibility values and focus/escape dismissal in the owning shell. Progress values, percentages and server operations remain authoritative in Django.
- Data: `src/app/progress_views.py`, `progress_edit` in `src/app/views.py`, `BasicMedia` progress properties, `watch_operation_id` and `app.services.progress_breakdown`.
- Consumers: Home in-progress cards through `home_grid.html` and the `progress_edit` response remain `ProgressChanger`. Show and season detail breakdowns render `ProgressBreakdown` on mount while the legacy `detail_progress_card_slot.html` keeps the Alpine card, teleported modal, htmx GET refresh, out-of-band card refresh and server fallback. The detail card is the remaining legacy Home/detail consumer.
- Retirement: the legacy button/value markup inside the progress-changer fallback retires when the island is considered universal. The legacy detail card and modal shell retire when card parity, tooltip placement, focus restoration and htmx refresh behavior have a proven React adapter. The server fallback remains intentionally for progressive enhancement.
- Native mapping: React Native `Pressable`/`Text`/`View`/`Modal`, the shared `ProgressBar`, `ProgressChanger` and `Spinner`; callers supply concrete palette values and callbacks instead of transport.
- Verification: `users.tests.test_progress_changer_tag` covers the adjustment controls. `app.tests.views.test_progress`, `app.tests.test_progress_breakdown` and `app.tests.test_rewatch_progress` cover the card, fragment, writes and rewatch rules. The web adapter, Expo export and bundles compile; the mounted breakdown was not exercised in a browser in this change. Android 15 Pixel 7 AVD rendered the shared progress card on Detail but did not open the breakdown or exercise expand/cancel-rewatch; iOS was not exercised. Earlier `ProgressChanger` and `Spinner` runtime evidence does not verify this card or breakdown.
- Validation targets: `src/app/tests/views/test_progress.py`, `src/app/tests/test_progress_breakdown.py`, `src/app/tests/test_rewatch_progress.py`, `users.tests.test_progress_changer_browser` (slow/Playwright).

### OWNERSHIP — Collection browser and copy editor

- Purpose/usage: collection page, detail/tracking ownership controls.
- Implementation: universal `frontend/ui/CollectionBrowser.jsx` (`CollectionBrowser`), browser adapter `frontend/ui/mountCollectionBrowser.jsx`, and `frontend/ui/CollectionCopies.jsx` (`CollectionCopySummary`, `CollectionCopyEditor`, `CollectionSeasonCascade`, `CollectionCopyDialog`), rendered by `native-proof/app/screens/CollectionScreen.jsx`. The web grid mounts the shared browser over the server-built item/card model through `data-collection-browser-root` and renders each item with the existing shared `MediaCard`, so hover actions and the tooltip host stay; the server toolbar, grouped rows, table layout, collection modal/form/summary fragments, `collectionCustomFields.js` and the Django/HTMX ownership routes remain. Bounded later pages come from the `?json=1` contract.
- Contract: grid/row/table/filter/sort, completeness, multiple copies/labels, medium fields, season cascades and owner-only mutation. `CollectionBrowser` receives filtered item descriptions, filter state/options and intents; it reuses `FilterBar`, `MediaCardView` and `Badge`, and does not parse URLs, own transport or write collection rows. `CollectionCopyDialog` receives copy values, medium-field descriptors, scope/seasons, validation errors and explicit save/edit/remove intents; it renders read-only when the caller lacks owner permission. Django forms, permissions, season expansion and redirects remain authoritative on the web.
- Data: `src/app/collection_views.py`, forms/models and the canonical collection card surface. Copy labels, completeness and custom values travel as plain descriptors; credentials and raw server HTML do not.
- Reuse/blockers: copy editor/summaries are shared; collection ownership differs from list membership. Depends on cards/filters/fields. The web grid uses the existing server card model and bounded JSON pages, but `CollectionBrowser` has no grouped-row load-more contract and its table lacks the server table's columns, so those layouts stay on the server fallback. The collection modal keeps its inline edit forms, season audit and scope semantics because the shared dialog's episode/season cascade is not a match for the server expansion rules.
- Status: `Partial / coexisting`. The native Collection screen renders the full demo browser in grid, grouped rows and table views with the shared filter bar, copy summaries, medium fields, season scope and owner/read-only states. On the web, the shared browser owns the ungrouped grid and its load-more pages while the server toolbar, grouped rows, table, tracking-modal copy editor and no-JS fallback remain. The surface stays `in_progress`.
- Native placement: `native-proof/app/screens/CollectionScreen.jsx`; URL-driven paging, live HTMX swaps and runtime interaction remain unverified.
- Verification: `npm run check:ui-architecture`, `npm run test:ui-architecture`, `npm run build:ui` and the Expo export compile the shared browser and adapter. `app.tests.views.test_collection` covers the browser props, server fallbacks and JSON next-page contract; targeted copy-label, season-cascade and form tests cover the server-owned modal. The web grid mount, card parity, load-more and theme behavior were not exercised in a browser; no simulator, device, VoiceOver or TalkBack pass was performed.
- Validation targets: `src/app/tests/views/test_collection.py`, `test_collection_copy_labels.py`, `src/app/tests/test_collection_season_cascade.py`, `src/app/tests/test_collection_forms.py`.

### CUSTOM-FIELDS — Collection definitions and values

- Purpose/usage: collection editor, summaries, filters/sort.
- Implementation: universal `frontend/ui/CollectionCustomFields.jsx` (`CollectionFieldValueInputs`, `CollectionFieldManager`), rendered by `native-proof/app/screens/CollectionScreen.jsx`. The web keeps `src/templates/app/components/collection_custom_fields.html`, `collection_custom_field_inputs.html`, `src/static/js/collectionCustomFields.js`, SortableJS and the JSON save endpoint.
- Contract: type/options/edit/delete/order, JSON saves, typed values/errors; do not duplicate importer resolution rules in UI. The shared value inputs render text, number, date, select and checkbox fields for the fields applicable to the item media type. The manager edits group/field names, types, options, media types and order through explicit intents and exposes up/down move controls as the native reorder affordance; it hides mutation and shows an owner-only notice when the caller lacks permission. Django still validates required names, at least one media type, select options, field/group ids and ownership on save.
- Data: collection definitions/values and endpoints in `src/app/collection_views.py`, `collection_fields.py`; the shared components receive plain groups, values, field-type/media-type choices and validation errors.
- Reuse/blockers: schema/field rendering is shared; the browser adapter and native drag reorder remain unimplemented. The web manager keeps SortableJS drag order and the HTML-fragment JSON save response, while the shared manager reverses that with up/down reorder, so parity is not proven. Do not duplicate importer resolution rules in UI.
- Status: `Partial / coexisting`. Native values and definitions render against realistic demo data with local save/validation feedback; the Django modal, `collectionCustomFields.js` JSON save and SortableJS remain the web owner. The surface stays `in_progress` until a browser adapter preserves ownership validation, field ids, drag reorder and the returned fragment.
- Native placement: `native-proof/app/screens/CollectionScreen.jsx`; persisted ownership validation and runtime reorder are unverified.
- Verification: `npm run check:ui-architecture` and `npm run test:ui-architecture` pass; `npm run build:ui` compiles with the pre-existing missing `frontend/users/UsersManagement.jsx` supplied temporarily, while a clean `npm run check:ui` is blocked by that unrelated baseline. Targeted custom-field validation/value Django tests pass with `FLOPPY_TEST_FAST_DB=1`, and the Expo web/iOS/Android export compiles. No browser, simulator, device or assistive-technology pass was performed for this change.
- Validation targets: `src/app/tests/views/test_collection_custom_fields.py`, `src/app/tests/test_collection_custom_field_values.py`, `src/app/tests/test_collection_field_import.py`.

### ARTWORK — Cover and edition selection

- Purpose/usage: detail/tracking image replacement and book editions.
- Implementation: image picker/tiles/cover-change/edition/Hardcover result fragments.
- Contract: candidate/file/URL, preview/reset/save/return, accepted formats/provider identity, authorization and safe outbound fetch.
- Data: `src/app/cover_views.py`, edition routes; [local covers](../architecture/local-covers.md).
- Reuse/blockers: selection state shared; file/drag/blob/camera/native caching need adapters.
- Validation targets: `src/app/tests/test_local_covers.py`, `src/app/tests/views/test_hardcover_edition_views.py`.

### MUSIC — Artist/album/track and podcast composition

- Purpose/usage: artist relations/discography, album tracks, show/episode detail.
- Implementation: `src/templates/app/music_album_detail.html`, `podcast_show_detail.html`, music/artist/album/podcast components in map. Native composition is `native-proof/app/screens/MusicScreen.jsx` with presentational pieces in `native-proof/app/components/MusicParts.jsx`, transport under `native-proof/app/data/musicTransport*.js` and realistic demo data in `native-proof/app/data/musicDemo.js`. The shared `MusicRelationCard`/`MusicRelationGrid` (universal `frontend/ui/MusicRelationCard.jsx`, browser adapter `frontend/ui/mountMusicRelations.jsx`) render artist relations on web and native. It reuses the shared `MediaCardView` rows/cards, `RatingChip`/`RatingStars`, `ProgressBar`, `Button`, `Badge` and `DateTimePicker`.
- Contract: hierarchy/deferred art, per-track actions/history/notes/scores, episode filter/pagination, repeats and show tracking. The native screen composes artist relations and discography, album detail with per-track listen/notes/history/score actions, a track page with inline notes and repeat history, and a podcast show with status/score tracking, episode filters, bounded load-more pagination and repeat plays. Callbacks own local demo state; no transport, credentials or server HTML enters presentation.
- Data: `src/app/music_views.py`, `music_album_views.py`, `podcast_views.py`; the native feature boundary maps the fork REST endpoints in `src/api/fork_views_music.py` and `src/api/fork_views_podcast.py` (artist/album/show tracking, album tracks, song and episode plays, track scores, sync and delete-plays). The screen keeps demo values until a native server identity supplies real numeric ids, then persists score/tracking/listen/episode-play changes through the injected request adapter. Track and episode notes still have no JSON write contract.
- Reuse/blockers: consume shared cards/rows/tracking; preserve hierarchy/feed behavior and explicit playback boundaries. Artist relation grids now mount the shared cards over their server fallback. The other web artist, album, track and podcast controls remain server-owned and keep their permissions, tracking writes, feed/RSS refresh, pagination fragments and progressive fallback. Note writes, membership/list actions, artwork changes and the remaining web-only controls stay outstanding, so the surface remains `in_progress`.
- Status: `Partial / coexisting`. Native artist, album, track and podcast composition renders with realistic demo state and an injectable REST transport. The artist relation grids are React-owned on web over the server fallback; the other music/podcast web controls remain legacy.
- Native placement: `in_progress` in `native-proof/app/screens/MusicScreen.jsx`. No iOS or Android runtime pass was performed; the Expo export is a compile check only. `MusicRelationCard`/`MusicRelationGrid` are registered universal presentation with browser adapter `frontend/ui/mountMusicRelations.jsx`.
- Verification: `npm run check:ui-architecture`, `npm run build:ui`, targeted music/podcast Django tests and the Expo export. Browser, iOS, Android, interaction and accessibility were not exercised for the relation grid or the other music surfaces.
- Retirement: the remaining web music and podcast templates keep ownership until browser adapters mount equivalent shared composition and the feature/data boundary maps note writes, permissions, feed refresh and metadata operations. Keep the server grid and page fallbacks until then.
- Validation targets: `src/app/tests/views/test_music_release_views.py`, `test_podcast_show_detail.py`, `test_podcast_detail_rss_refresh.py`, `test_music_track_notes.py`.

### PEOPLE — People/studios, credits and medium extras

- Purpose/usage: person/studio pages and detail cast/trailers/game-length/reading sections.
- Implementation: universal `frontend/ui/People.jsx` (`PersonHero`, `StudioHero`, `PersonCard`, `CreditCard`, `MediaGallery`, `LightboxDialog`, `MediumExtras`) composed by `native-proof/app/screens/PeopleScreen.jsx`; shared `Rail` for bounded cast/filmography/studio rails and `Badge`/`Button` for status chips and history/source actions. The browser adapter `frontend/ui/mountPeople.jsx` mounts the person and studio heroes through `people_hero` in `src/users/templatetags/ui_tags.py` and `src/templates/app/components/people_hero.html`; `src/templates/app/person_detail.html` and `studio_detail.html` keep their hero markup as the fallback. The web filmography grids keep the shared `MediaCardView` credit cards so hover/tracking actions survive, and the cast/filmography/carousel/YouTube/extra fragments remain server-owned.
- Contract: internal/external link intents, role credits, bounded rails, carousel selection with fit/play/full-size intents, an accessible lightbox, and time-to-beat, YouTube and reading metadata. Every component receives already-shaped values and explicit navigation/source/play intents; it never parses URLs, fetches providers or owns permissions. Source and website actions open exteriors; person, cast and credit opens stay internal. On the web the hero adapter resolves theme tokens, navigates history/source/website intents in the browser and leaves the server hero visible until React mounts. Server fallbacks remain the web owner.
- Data: `src/app/people_views.py`, provider/detail projections.
- Reuse/blockers: reuses `RAILS`, `BADGE` and `BUTTON`; person, cast and credit cards intentionally differ from tracked media cards. The web hero mounts are wired, but production native transport and authorization-sensitive native actions are not. The richer web filmography needs the shared media card's hover/tracking actions, so it is not replaced by `CreditCard`. Native playback delegates to an external trailer link rather than an embedded player.
- Status: `Partial / coexisting`. The person and studio heroes (name, biography, facts, counts, source/website and history links) are React-owned on the web through the browser adapter while the server markup stays as the fallback. The native People screen renders the full cast/credit/gallery/extras composition with demo values. The filmography/grid fragments remain server-owned web consumers, so the native placement stays `in_progress`.
- Remaining consumers and retirement: the server person/studio hero fallback, filter toolbar, filmography HTMX fragment, cast/filmography grids and carousel/YouTube/game-length/reading fragments stay in place until the filmography action layer, gallery/extras web consumers and native transport supply equivalent values. Retirement requires browser, iOS and Android passes; the Expo export is only a compile check.
- Validation targets: `src/app/tests/views/test_person_detail.py`, `test_studio_detail.py`, `src/app/tests/test_detail_builders_game_credits.py`; `app.tests.test_media_card_contract` for the distinct person/credit card exceptions.
- Verification: person/studio Django tests, `npm run build:ui`, `npm run check:ui`, UI architecture checks and the Expo export compile the shared presentation, the browser mount and the native screen. No browser, simulator or device interaction pass was run; iOS and Android remain unverified.

### TAGS — Management and assignment

- Purpose/usage: tag index, detail preview, detail/library/bulk tagging, track-tab assignment and settings tag filters.
- Implementation: universal `frontend/ui/TagManagement.jsx` (`TagIndex`, `TagMediaFilter`, `TagPreview`, `TagAssignmentDialog`, `TagBulkDialog`) reusing shared `Chip`, `Badge`, `TextField`, `Button`, `ConfirmDialog`, `BulkActionDialog` and `BulkOptionRow`; native placement `native-proof/app/screens/TagsScreen.jsx`. Browser adapter `frontend/ui/mountTags.jsx` mounts `TagIndex` from `src/templates/app/tag_index.html`, `TagPreview` from `src/templates/app/components/detail_tag_preview.html`, `TagAssignmentDialog` from `src/templates/app/components/fill_tags.html` in both its modal and embedded track-tab forms, and `TagMediaFilter` from `src/templates/users/components/media_tag_filter.html`. The library bulk toolbar opens the shared `TagBulkDialog` through `frontend/ui/mountBulkActions.jsx`. Server fallbacks remain inside each host and cover the no-JS path.
- Contract: case-insensitive search and name/count sorting, item assignment and creation, selected-item add/remove, global counts that stay library-wide under filtering, confirmed library-wide deletion, media-type filter choices and summary semantics, and disabled destructive actions when a tag is not owned. The preview renders server-built section titles, tones, links and empty labels without parsing HTML. The browser adapter keeps the existing `window.confirm` before deleting from the index, keeps the tag modal's and bulk dialog's confirmations, posts only server-enforced owner-scoped routes, and applies the server's OOB preview model to the mounted preview instead of replacing its React host. The track tab uses the same assignment component without a close action, so it stays inside the edit modal. The bulk action requires an explicit tag, action and dialog confirmation. The settings filter forwards its selected key to the page's Alpine `activeMediaTag`, preserving the provider filtering semantics.
- Data: `src/app/tag_views.py`, `src/app/bulk_actions.py`, user-owned tag relations/library query. The tag index, assignment and bulk views supply serialized models; native uses local demo state, and both web paths keep server-enforced ownership and writes.
- Reuse/blockers: chip/selection/preview model shared; destructive/ownership checks stay server-enforced and the web server fallbacks are retained. No iOS or Android interaction/accessibility evidence exists.
- Status: `Web Migrated` for the tag index, preview, modal and track-tab assignment, bulk dialog and settings media-type filter; the server markup inside each host is the no-JS and mount-failure fallback. Native placement is `ported` in `native-proof/app/screens/TagsScreen.jsx` with local demo state; production transport and runtime verification remain separate.
- Native placement: `ported` in `native-proof/app/screens/TagsScreen.jsx`. Expo export compiles it; no iOS or Android runtime interaction was exercised in this change.
- Verification: `app.tests.views.test_tags`, `app.tests.views.test_track_modal`, `app.tests.views.test_media_details` tag-preview cases, `users.tests.views.test_settings_media_tag_filters`, `lists.tests.test_bulk_actions`, `npm run check:ui-architecture`, `npm run test:ui-architecture`, `npm run build:ui`, `npm run check:ui` and the Expo export `--platform all`. The browser adapter was not exercised in a browser; iOS and Android were not run on a simulator or device. Build/export evidence is not runtime verification.
- Remaining consumers and retirement: the server templates (`tag_index.html`, `detail_tag_preview.html`, `fill_tags.html`, `tag_item_button.html`, `media_tag_filter.html`) stay as the no-JS/mount-failure fallback. The table's tag-names cell (`media_tags_cell.html`) is display-only and outside this component family. Retire the fallbacks only after browser interaction passes cover search/sort/delete, create/toggle/delete/preview and the settings provider filter; iOS and Android interaction passes are still required.
- Validation targets: `src/app/tests/views/test_tags.py`, `src/app/tests/views/test_track_modal.py`, `src/users/tests/views/test_settings_media_tag_filters.py`, `src/lists/tests/test_bulk_actions.py`.

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

- Purpose/usage: global history feed and per-item sessions/repeats.
- Implementation: universal `frontend/ui/HistoryFeed.jsx` (`HistoryFeed`, `HistoryDayGroup`, `HistoryEntryRow`, `HistoryDaySummary`, `HistoryActivitySummary`, `HistoryFilterPanel`, `HistoryState`, `HistoryActivityDialog`, `HistoryEditDialog`, `HistoryDeleteDialog`); browser adapter `frontend/ui/mountHistoryFeed.jsx` mounted from `data-history-feed-root`; bounded JSON day slices on `history_day_fragment` (`?format=json`); native screen `native-proof/app/screens/HistoryScreen.jsx`; server page `src/templates/app/history.html`, history day/card/edit and session modal/day/row fragments; `src/static/js/sessionHistory.js`.
- Contract: the shared feed renders bounded day groups with weekday/date headers and item/runtime day summaries; watched/read/played rows use the shared `MediaCardView` row with score, status, runtime and note expansion; activity, edit and delete actions open the shared dialogs; lazy days load one bounded day at a time; load-more reveals the next bounded slice with the remaining count; month navigation, filter sheets with the shared `DateTimePicker`, the activity summary, refresh/stale notices, pagination and loading/empty/error states are all presentation. The activity dialog reuses the shared date picker and rating stars, lists each session/repeat and exposes edit/delete. The edit dialog reuses the date picker, rating stars and status chips; delete asks for confirmation. It receives a model and emits navigation, load, open, activity, edit, delete, filter, refresh and save-view intents; it does not parse URLs or own transport. The existing server contract keeps filters/modes/days, bounded fragments/refresh notice, edit/delete/units, marked dates/day jumps, close-button focus and nested refresh.
- Data: `src/app/history_views.py`, `src/events/history_feed.py`; [memory contract](../architecture/history-memory.md).
- Status: `Partial / coexisting`. The shared feed is mounted over the web History day list and replaces it at runtime; the server-rendered day list remains the fallback inside the React host if the chunk fails. The feed receives a bounded server-built model and lazy/load-more days through `history_day_fragment?format=json`, so no client path loads whole history. The server still owns month navigation, the filter FAB and its Alpine sheet, the cache-refresh banner, filtered-view pagination and the per-item session dialog; edit opens the existing track modal through the shared `ModalHost`, and delete remains inside that modal because cached rows expose instance ids rather than history ids. The native History screen keeps its demo/local interactions and has no transport. Android 15 Pixel 7 AVD rendered the earlier shared feed; web interaction, the remaining server chrome, the dialogs, iOS and accessibility remain unverified.
- Reuse/blockers: reuses `MEDIA-CARD` row, `BADGE`, `BUTTON`, `DATE-TIME` and `RATING`; never client-load whole history. The server day-list markup now retires at runtime where the adapter mounts, but `history.html` keeps it as the fallback. Remaining web consumers are the server month navigation, Alpine filter sheet, cache banner and pagination. Retirement requires a browser pass for lazy days/load-more/edit/session dialogs and the remaining chrome, then moving those server controls into the shared feed or a registered adapter; until then the surface stays `in_progress`.
- Verification: `npm run check:ui-architecture`, `npm run test:ui-architecture`, `npm run build:ui` and Expo export `--platform all` compile the shared feed and adapter. `app.tests.views.test_history` covers the bounded feed model and JSON day slices; `test_history_item_projection` and `test_history_day_cache_lifecycle` cover memory and cache behaviour. Chromium (local gunicorn, seeded manual movies, 1280×900) mounted the adapter into `data-history-feed-root`, rendered the seeded day rows with Activity and Edit actions, and logged no console errors. Lazy days, load-more, the activity/edit dialogs, filters, cache refresh, TalkBack/VoiceOver and iOS were not exercised; local Redis cooling blocked further interaction.
- Validation targets: `src/app/tests/views/test_history.py`, `src/app/tests/test_history_item_projection.py`, `test_history_day_cache_lifecycle.py`.

### STATISTICS — Dashboard, charts and taste/talent

- Purpose/usage: statistics summary, activity overview, highlights, comparison, native charts, featured repeats, taste/talent signals, role/studio leaders and per-media-type activity overviews.
- Implementation: universal `frontend/ui/StatisticsSummary.jsx` (`StatisticsSummary`, `StatisticsToolbar`, `StatisticsActivityOverview`, `StatisticsHero`, `StatisticsHighlights`, `StatisticsSummaryCards`, `StatisticsState`), universal `frontend/ui/StatisticsCharts.jsx` (`StatisticsCharts`, `StatisticsRhythmChart`, `StatisticsHeatmapChart`, `StatisticsHoursByMediaTypeChart`, `StatisticsHoursChart`, `StatisticsStatusCompositionChart`, `StatisticsRatingDistributionChart`, `StatisticsStatusBreakdownChart`, `StatisticsCompletionChart`, `StatisticsFeaturedRepeat`) and universal `frontend/ui/StatisticsSections.jsx` (`StatisticsComparison`, `StatisticsRoleLeaders`, `StatisticsStudioFootprint`, `StatisticsTasteSignals`, `StatisticsTalentSection`, `StatisticsMediaTypeOverview`, `StatisticsMediaTypeOverviews`) rendered by `native-proof/app/screens/StatisticsScreen.jsx`. Web adapters `frontend/ui/mountStatisticsSummary.jsx` and `frontend/ui/mountStatisticsCharts.jsx` mount the shared summary overview and the overview/heatmap/hours/status chart groups over `src/templates/app/statistics.html`, which keeps its server markup as the fallback plus the statistics/taste/role/studio/featured fragments, `src/static/js/statistics-charts.js`, `stats-media-merge.js`, `date-range.js` and Chart.js/datalabels.
- Contract: the shared summary renders the hero totals/time, first/last/today highlights, completed items, average rating, most active day, current/longest streak, activity comparison, empty/loading/error states and range/media-type control intents. The native chart renderer draws activity rhythm and heatmap cells, hours by media type/month/weekday/time, status composition, rating distribution, status breakdown, completion by media type and the featured repeat ring with native `View`/`Text` primitives, accessible summaries, and loading/empty/error/theme states. `StatisticsSections` renders comparison mode choices and per-media current/comparison values, role-leader columns with Time/Titles/Plays sorting and person selection, studio footprint sorting and delta, taste signals (Top Genres and Era Spotlight) with Time/Plays sorting, and generic per-media overviews with facts, year/month charts, ranked media/artist/author/platform/genre panels and empty states. Every section receives server-shaped values and labels; it never recomputes authoritative statistics and only encodes supplied percentages for display. The web contract keeps media/range/comparison, dates/units, Chart.js charts/heatmaps/order, refresh/errors and teardown; the server taste/role/studio/overview fragments remain the web owner.
- Data: `src/app/statistics_views.py`, snapshots/[statistics sync](../architecture/statistics-sync.md). Server calculations and permissions stay authoritative.
- Reuse/blockers: the summary reuses `BADGE`, `BUTTON` and `DATE-TIME`; charts and sections reuse the shared summary state, the generic hours chart and theme tokens, render with React Native primitives only, and never use a WebView, Chart.js or a client-side statistics engine. The web adapters mount the summary overview and the chart groups whose semantics map one-to-one to the existing cards (activity rhythm, hours by media type, heatmap, hours by month/weekday/time, status composition and rating distribution). They read server-built per-type models and merge them only for the existing multi-select presentation; the server values stay authoritative. The Alpine range/media-type controls, saved media-type preference, comparison, featured repeat, taste/talent, role/studio leaders, status breakdown/completion, consumption tiles, average rating and the per-media Chart.js charts remain server-owned. The native screen holds demo data and local sort/compare/person-selection state; production transport, permissions and the saved comparison/media-type preferences remain in the feature/data boundary. The person media strip and the reading release/completed-length, game daily-average and copied stacked-hours charts have no shared presentation yet, so the surface stays `in_progress`.
- Media-type filter: the Alpine dropdown in `date-range.js` is multi-select and autosaves ticked types through `update_statistics_media_types` into `statistics_default_media_types`. The next visit without a `media-type` query starts from that preference (and seeds the URL so charts and the dropdown agree); an explicit link still wins until the user changes the filter. Clearing to All media saves an empty preference. The native summary and charts only reflect the selection intent; they do not write the preference. The trigger keeps a fixed width and the menu matches it, so changing the selection truncates the label instead of moving the menu.
- Status: `Partial / coexisting`. The summary, activity overview, chart families, comparison, taste/talent signals, role/studio leaders and per-media-type overviews are React-owned on the native Statistics screen. On the web, the shared summary overview and overview/heatmap/hours/status chart groups are mounted over their server fallback; the saved media-type preference, range controls, comparison, featured repeat, taste/talent, role/studio leaders, breakdown/completion and per-media charts still run through the existing Django/Alpine path. The native screen still uses demo values. Native placement is `in_progress` until production data transport and the remaining runtime verification land.
- Verification: `app.tests.views.test_statistics`, `app.tests.test_statistics_sync`, `app.tests.test_statistics_media_merge_js`, `npm run build:ui`, `npm run check:ui`, `npm run check:ui-architecture`, `npm run test:ui-architecture` and Expo export `--platform all` pass for the native presentation. `app.tests.test_statistics_media_type_browser` also passes its 5 Chromium tests on macOS, including selecting, reloading, clearing the remembered filter and the menu staying put as the label changes. Browser interaction for the newly mounted web summary and chart groups, iOS and Android runtime passes were not performed; an Expo export is a build check, not runtime evidence.
- Related work: [#1841](https://github.com/dannyvfilms/Floppy/issues/1841) (remember the statistics media-type filter); [#1317](https://github.com/dannyvfilms/Floppy/issues/1317) (multi-select).
- Retirement condition: retire the server summary/hero/highlight markup, chart canvases, comparison controls and the Alpine range/media-type/taste/role/studio controls only after a browser adapter mounts the shared summary, charts and sections with equivalent intents and a browser pass verifies the Chart.js and server-fragment replacement; keep the server fallback until then.
- Validation targets: `src/app/tests/views/test_statistics.py`, `src/app/tests/test_statistics_sync.py`, `test_statistics_media_merge_js.py`; browser layout checks are slow.

### RELEASE-CALENDAR — Upcoming releases and subscriptions

- Purpose/usage: release calendar page, not `DATE-TIME`.
- Status: `Web Migrated` for the month grid, agenda, list view, release/status/media/tag filters, view toolbar, calendar actions menu and the calendar links panel. The shared `ReleaseCalendar` owns the toolbar, month navigation, day cells, agenda, list, filter sheet and calendar actions menu; it renders only server-supplied weeks, day labels, release groups, filter options and labels. The shared `CalendarLinks` owns the release/history feed tabs, media/status/release-date switches, subscription URL and copy/download actions; it renders only server-supplied options, defaults and base URLs. The Django template keeps a static grid or list fallback (also the chunk-load and mount-failure state) and a static release/history subscription-link fallback for the links root. The Alpine links panel and the calendar tag-filter include are removed. Browser verification: Chromium on macOS at 1280×1000, signed into a seeded Django page, mounted both React roots and exercised the month/agenda/list views, filter persistence across reload, the week-start preference save/reload, both link feeds and their URL changes, clipboard copy, ICS download and the fetch POST/queued message with a clean console. iOS and Android remain unverified: the Expo export is a build check only.
- Implementation: universal `frontend/ui/ReleaseCalendar.jsx` and `frontend/ui/CalendarLinks.jsx`, browser adapters `frontend/ui/mountReleaseCalendar.jsx` and `frontend/ui/mountCalendarLinks.jsx`, props from `events.views._release_calendar_props` and `events.views._calendar_links_props`, and `src/templates/events/calendar.html`. The release adapter keeps saved-filter localStorage persistence, month/view/release navigation, the fetch POST, the download link and the week-start preference POST plus reload. The links adapter keeps theme tokens, clipboard copy and the filtered ICS download. Native placement: `native-proof/app/surfaces/CalendarSlot.jsx` for the calendar and `native-proof/app/screens/CalendarScreen.jsx` for the links panel and action feedback; `native-proof/app/data/calendarPreferences.js` persists filters and week start with the document file system, and `calendarPreferences.web.js` exposes the same contract through localStorage. The native screen routes fetch/download to a server-owned note without porting a delivery job. Reused shared `Badge` for the ICS mark, the universal `Button` implementation for copy/download (explicitly, because the web-only anchor variant does not accept press intents from a shared subtree) and the existing modal sheets; calendar rows are not media cards and the shared date picker is not a month navigator.
- Episode labels: grid agenda and list share `Event.season_episode_label` ("S39E170"); a season's title drops a trailing "Season N" so the label carries it once.
- Contract: month/today/grid/list, media/status/release/tag filters, persisted filter state, grouped dates/media, the region-unset Preferences notice, ICS/download/subscription/reload and empty states. The server owns event queries, month weeks, day timezone assignment, week start, release semantics, calendar tokens, link defaults and URL bases; the client only filters the supplied month data, sorts presentation rows and assembles query parameters from the server options.
- Data: `src/events/views.py`, `src/events/calendar/`, tasks; [reload contract](../architecture/calendar-reload.md), REST parity unverified.
- Retirement: the `calendarFilters()` Alpine script, `filter_menu.html` include, `filteredGridHtml` swap and calendar tag-filter include are removed. `calendar_list.html` remains the server list fallback. The static release/history subscription links replace the former Alpine calendar-links panel as the no-JS/chunk-failure fallback, and browser runtime React ownership is confirmed. The gear menu is now part of `ReleaseCalendar`; `mountCalendarMenu.jsx` is retired.
- Reuse/blockers: the grid, agenda and list consume serialized release/filter data; no calendar rule is duplicated in the client. The links panel consumes server defaults and base URLs; it does not compute delivery events, fetch jobs or feed contents. `FilterBar` is not reused because the calendar filters per-type statuses, release-date types and media-type tags with different semantics. Native saved filters and week start now persist through the shell adapter; native copy/download remain URL text and server-owned notes because the shell has no authenticated transport. Browser interaction parity is verified for pointer and keyboard dismissal of the sheets; screen-reader behavior, actual iOS and Android runtime and native persisted-filter validation remain unverified.
- Validation targets: `src/events/tests/test_views.py` (`CalendarViewTests`, including the static links fallback), `test_release_semantics.py`, `calendar/test_main.py`, `src/api/tests/test_calendar.py`; browser pass through Chromium on macOS at desktop width, and `npm run build:ui`, `npm run check:ui-architecture`, `npm run test:ui-architecture` plus Expo export for iOS and Android as build checks.

### LISTS — Lists, memberships, public profiles and collaboration

### LISTS — Lists, memberships, public profiles and collaboration

- Native hub: `frontend/ui/ListCard.jsx` maps list records onto the shared media card with visibility/smart/source state and member/role metadata in the card body lines; list-specific metadata must not use overlapping artwork corner chips or unlabelled status glyphs. The ListCard metadata placement was fixed after the first Android render.
- Native hub: `frontend/ui/ListCard.jsx` maps list records onto the shared media card with visibility/smart/source state and member/role metadata in the card body lines; list-specific metadata must not use overlapping artwork corner chips or unlabelled status glyphs. The ListCard metadata placement was fixed after the first Android render.
- Native detail: `frontend/ui/ListResults.jsx` owns the detail grid/table, sort metadata, selection, bulk status/collection/remove intents and empty states; `frontend/ui/ListMembership.jsx` owns the membership/visibility popup and the RSS/Radarr/Sonarr/CSV link rows; `frontend/ui/SmartRules.jsx` owns the smart-rule summary/editor and `frontend/ui/TierBoard.jsx` owns the tier board. Both reuse `MediaCardView`, `FilterBar`, `RatingStars`, `Badge`, `Button` and the shared `MediaCardActionHost`; the screen keeps search, filters, filters' sort/view state and navigation.
- Native forms and flows: `frontend/ui/ListFormView.jsx` owns the create/edit list form (name, description, visibility, public slug, include-notes, recommendation and smart toggles, tags, roles, delete guard). `frontend/ui/ListSearchView.jsx` owns add/recommend item search and its preview dialog; `frontend/ui/ListRecommendationsView.jsx` owns the approval/deny view. They reuse the shared form controls, cards and action dialog.
- Components: `ListResults`, `ListResultGrid`, `ListResultTable`, `ListBulkBar`, `ListEmptyState`, `ListMembershipPopup`, `ListMembershipSection`, `ListShareLinks`, `ListForm`.
- Native transport: `native-proof/app/data/listTransport.js` (native) and `listTransport.web.js` (browser) expose the same action contract; `listTransportCore.js` maps it to the existing JSON and form endpoints. Visibility and collaborators use the list PATCH, ratings and item removal use the media/list item endpoints, bulk status/collection use the Django form actions, smart rules use `list_smart_rules_update`, and tier move/save/fill/undo use the tier actions. The browser adapter uses the same-origin session and `X-CSRFToken` cookie; without that session it returns the local preview adapter instead of pretending a write succeeded. Native login/server selection/CSRF transport is still undesigned, so the native adapter requires an injected request function and otherwise keeps the local preview.

- Purpose/usage: list browser/detail/activity/profile/forms and membership popup.
- Status: `Partial / coexisting`. The lists hub, list detail header, result grid/table, bulk selection bar, membership/visibility popup, create/edit list form, add/recommend search and preview, and recommendations approval/deny are React-owned through shared components. The native detail screen routes visibility, collaborator, rating, removal and bulk status/collection actions through `listTransport`; the Lists screen renders the hub, form and curation flows in local demo state. The web list pages remain server-owned, including their result grid/table, bulk toolbar and list form.
- Migration state by surface: manual-list grid/table/tiers and public detail pages consume the fully React-owned ALPHABET sibling. Existing list headers, toolbars, cards/tables and editing controls retain legacy ownership on web; migrate each when edited. The native shell now renders the shared hub, header, results, membership popup, list form, add/recommend search/preview, recommendations approval/deny, smart-rule summary/editor and tier board. Server transport for add/recommend, smart-rule saves and tier mutations remains demo/local on native.
- Implementation: `frontend/ui/ListCard.jsx`, `ListHeader.jsx`, `ListResults.jsx`, `ListMembership.jsx`, `ListFormView.jsx`, `ListSearchView.jsx` and `ListRecommendationsView.jsx` (shared universal components); `native-proof/app/data/listTransportCore.js`, `listTransport.js` and `listTransport.web.js` (list action transport); `src/templates/lists/custom_lists.html`, `list_detail.html`, `user_profile.html`, `list_activity.html`, list grid/form/visibility/membership/table components remain web-owned.
- Contract: manual/smart/source-backed distinction, search/tags/roles, public/unlisted/private visibility and read-only link, viewer and public rendering, membership/pins/feed/export/sync. Unlisted lists are reachable by link but omitted from public profiles. Viewer shares are per installed user: they can open the list and its smart contents but every write endpoint keeps the owner/collaborator check, so a viewer POST is rejected server-side. The list form exposes both collaborator and view-only user controls; the same owner-selects-an-installed-user workflow backs the existing Plex webhook share.
- Sharing migration: the universal list form and membership popup now carry the three visibility states and a `viewer` role. The browser list form, grid, header chips and edit modal are still Django-owned and record the viewer/unlisted copy there; their React replacements (including a future reusable Plex share panel) remain partial. This change did not move Plex's server-rendered share form, so the two workflows share behavior and data shape but not yet one browser component.
- Data: `src/lists/views.py`, browse/action/helper views, models/forms; REST parity separately assessed.
- Reuse/blockers: list card/editor/membership/form/curation presentation shared; consume canonical media/filter/table systems; collection ownership is separate. Android 15 Pixel 7 AVD rendered the shared list cards in the Lists hub; the header, results, membership popup, list form, add/recommend/approval views and iOS were not opened. The native transport adapter keeps local preview state because native login, server selection and CSRF transport are not designed. Add/recommend and approval writes, add-to-list/tag pickers, add-plays jobs, CSV/RSS/Radarr/Sonarr browser/download handoff and server list hydration are not connected. Retirement condition for the web grid/table/toolbar and list form: migrate those templates to the same shared components.
- Verification: `lists.tests.test_views`, `test_list_detail_filters`, `test_bulk_actions`, `test_forms`, `test_item_rank`, `npm run build:ui`, `npm run check:ui-architecture`, `npm run test:ui-architecture` and Expo export (web, iOS, Android) are compile/regression checks only. Android rendered the Lists hub cards; the detail results, membership popup, list form, add/recommend/approval flows, smart-rule editor, tier board, browser and iOS were not exercised.
- Validation targets: `src/lists/tests/test_views.py`, `test_list_detail_filters.py`, `test_bulk_actions.py`, `test_forms.py`, `test_rss_feed.py`, `test_csv_export_import.py`, `test_list_sharing.py`.
- Validation targets: `src/lists/tests/test_views.py`, `test_list_detail_filters.py`, `test_bulk_actions.py`, `test_forms.py`, `test_rss_feed.py`, `test_csv_export_import.py`, `test_list_sharing.py`.


### SMART-RULES — Rule editing and results

- Purpose/usage: smart-list detail/editor/summary.
- Status: `Partial / coexisting`. `frontend/ui/SmartRules.jsx` owns the universal
  `SmartRuleSummary` and `SmartRuleBuilder`: filter groups for media types, status,
  rating, collection, release, tags with the Any/All/No tag operator, genres,
  years, source, language, country, platform, origin, format, author/provider,
  linked lists, search and absolute or relative date windows. The builder validates
  rating, date and relative-window input before emitting a save, preserves the
  saved `semantics_version` and sort fields, and supports an editor or a read-only
  public filtering state. It never evaluates membership or weakens permissions;
  callers save through the existing smart-rules action and the Django page remains
  the browser consumer.
- Migration state by surface: the native Lists hub shows the saved-rule summary
  for smart lists; native list detail renders the summary plus the editing/filter
  builder. The server-rendered smart-list detail page and its Alpine builder still
  own the web surface. Alphabet view state does not alter saved rules or permissions.
- Implementation: `frontend/ui/SmartRules.jsx` (`SmartRuleSummary`,
  `SmartRuleBuilder`) with `native-proof/app/screens/ListDetailScreen.jsx` and
  `native-proof/app/screens/ListsScreen.jsx`; `native-proof/app/data/listTransportCore.js`
  maps saves to `list_smart_rules_update`. The browser templates remain
  `src/templates/lists/smart_list_detail.html` and smart rules builder/summary components.
- Contract: initial JSON/live editing/save/errors, results/sort/bulk and shared rule semantics.
  The shared builder emits the same rule vocabulary the server normalizes; the
  client validates only presentation input and does not fork evaluation.
- Data: `src/lists/views_smart_list.py`, `smart_rules.py`, library query engine.
- Reuse/blockers: normalized filter state/schema shared; never fork evaluation for native/Home.
  The native smart-rule save uses local preview state because native login, server
  selection and CSRF transport remain undesigned. Browser interaction and actual
  iOS/Android runtime for the new components are unverified.
- Validation targets: `src/lists/tests/test_smart_list_semantics.py`, `test_smart_list_sync_deferral.py`.

### LIST-CURATION — Search, add and recommend

- Purpose/usage: add/recommend/approval pages and preview dialogs.
- Implementation: `frontend/ui/ListSearchView.jsx` (`ListItemSearch`, `ListItemPreview`) and `frontend/ui/ListRecommendationsView.jsx` (`ListRecommendations`) are shared universal presentation; `src/templates/lists/add_item.html`, `recommend_item.html`, `list_recommendations.html`, search/preview components remain the server-owned web consumers.
- Contract: provider/type/query/pagination, preview/add/recommend/approve/deny and role-specific permissions.
- Data: `src/lists/views_add_reorder.py`, `views_recommendations.py` and distinct actions. The native screen keeps search, preview, approval and deny state locally as demo data; transport and authorization remain server-owned.
- Reuse/blockers: parallel search/preview presentation can consolidate; do not merge authorization/submission semantics. Depends on search/cards/dialogs. The native search uses the shared media card, form controls and action dialog. Browser interaction and iOS/Android runtime for the new views remain unverified.
- Status: `Partial / coexisting`. The native Lists screen renders add/recommend search, preview and approval/deny in demo state. The Django add, recommend and recommendations pages remain server-owned.
- Verification: Expo export (web, iOS, Android) is a compile check only; the search, preview and approval views were not exercised in a browser, simulator or emulator. Targeted `src/lists` tests cover the unchanged server contracts.
- Validation targets: `src/lists/tests/test_views.py`, `test_item_rank.py`, `test_integration.py`.

### TIERS — Board, order and export

- Purpose/usage: editable/public list tier boards.
- Status: `Partial / coexisting`. `frontend/ui/TierBoard.jsx` owns the universal
  `TierBoard`: coloured tier rows, compact media tiles, unranked pool, tier
  add/edit/delete and up/down order, item move and earlier/later ordering,
  fill-from-ratings with undo, export intent, truncation notice and read-only
  public state. Every mutation is an explicit callback; the component does not
  evaluate tiers or grant edit access, and caller-supplied `canEdit`/`canFill`
  capabilities control the controls. Smart lists render the no-tier state.
- Migration state by surface: native list detail renders the tier board when the
  Tiers view is selected; the Django tier board, `listTiers.js` and SortableJS
  remain the browser owner. Drag-and-drop is replaced on native by the accessible
  move dialog and earlier/later order controls; the browser still provides drag.
- Implementation: `frontend/ui/TierBoard.jsx` (`TierBoard`) with
  `native-proof/app/screens/ListDetailScreen.jsx`; `native-proof/app/data/listTransportCore.js`
  maps move/save/fill/undo to the existing tier actions. Legacy browser files are
  tier board/tile components, `src/static/js/listTiers.js` and SortableJS.
- Contract: moves/order/colors/unranked/fill-from-ratings/undo/export/truncation;
  editable only for authorized manual non-smart lists. Server validation of tier
  ids, colours and names remains authoritative.
- Data: `src/lists/views_tiers.py`, `tiers.py`, `tier_export.py`, transactional ordering.
- Reuse/blockers: board state/media values shared; accessible reorder/native export need adapters.
  Native export is a download intent, not a rendered image adapter. The native
  board keeps demo preview state without a native request/CSRF transport. Browser
  interaction and actual iOS/Android runtime were not exercised.
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

- Purpose/usage: theme, logo, date/time, currency, grid, title/talent, locale, region, week start, tracking and automation preferences with their dirty/save state.
- Implementation: native `frontend/ui/PreferencesForm.jsx` composes the shared `frontend/ui/SelectField.jsx`, `frontend/ui/ToggleChip.jsx` and `frontend/ui/FormSaveBar.jsx`; `native-proof/app/surfaces/PreferencesSlot.jsx` places the card on Settings with local field state. The browser page remains `src/templates/users/preferences.html` with its Alpine selectors and `src/templates/users/components/form_save_bar.html`; `frontend/ui/controls.jsx` remains the frozen web-only `SelectField`/`ToggleChip` migration source and is not imported by universal code.
- Contract: selected, disabled, dirty, saving, saved and validation-error states; polite status announcements; one preference per named field with the existing option values. `PreferencesForm` accepts `values`, `initialValues`, `validate`, `onSave({ values, csrf })`, field errors and a save error. Server validation remains authoritative in `src/users/views.py`; native transport, CSRF and server persistence still need a platform data adapter.
- Data: preferences handler in `src/users/views.py` and user fields; provider-region and metadata-language choices are supplied by `tmdb` in that handler. `src/users/forms.py` has no preference form.
- Reuse/blockers: web remains server-owned and unchanged, so the shared form is not mounted in the browser bundle and browser parity relies on the existing Django/Alpine page and `users.tests.views.test_preferences`. Native runtime interaction and accessibility were not exercised; Expo export is a build check only. The legacy `controls.jsx` consumers retire when those controls migrate to the universal contracts.
- Status: `Partial / coexisting`. Native placement is `ported` in `native-proof/app/surfaces/PreferencesSlot.jsx` for the preferences family and save bar; the web page is still legacy, and native server submission/credential transport remains unimplemented.
- Validation targets: `src/users/tests/views/test_preferences.py`, `src/users/tests/views/test_statistics.py` (shared week-start and statistics preference endpoint).

### SET-APPEARANCE — Theme and detail layout editor

- Purpose/usage: swatches/custom effects and detail-family section enable/order.
- Implementation: shared `frontend/settings/AppearanceEditor.jsx` renders theme presets, custom palette/effect steppers and detail-family enable/order through the shared select and toggle controls; `native-proof/app/surfaces/AppearanceSettingsSlot.jsx` places it on native Settings with demo state. The browser page remains `src/templates/users/appearance.html` with inline `appearanceEditor()` and JSON-script config.
- Contract: selection/custom validation, family/zone enable and order, and persisted settings. The shared editor owns local validation errors, dirty detection and saving/error presentation; the caller owns the values, save transport and server response.
- Data: `src/users/appearance.py`, appearance handler in `src/users/views.py`; the native slot supplies demo presets, palette defaults and layout families. Server validation remains authoritative.
- Reuse/blockers: theme tokens and editor state are shared. Native rendering replaces range and drag affordances with steppers and move buttons; web remains unchanged. Native persistence, browser mounting and runtime interaction evidence remain open.
- Status: `Partial / coexisting`. Native placement is `in_progress` until the shared editor is mounted in a browser adapter and native runtime interaction is verified.
- Validation targets: `src/users/tests/views/test_appearance.py`, `src/app/tests/test_theme_tokens.py`.

### SET-CARDS — Card configuration and preview

- Purpose/usage: per-media line selection/reorder/live preview.
- Implementation: shared `frontend/settings/CardsEditor.jsx` renders per-type selects, title/rating options, line and field ordering, add/remove controls and a data-driven native preview; `native-proof/app/surfaces/CardsSettingsSlot.jsx` places it on native Settings with demo profiles. The browser page remains `src/templates/users/cards.html` and `cards_preview.html` with inline `cardsEditor()`.
- Contract: per-type values, defaults, line display and order, title/rating options, and a live preview. Save emits the existing `{ version: 1, types }` card-metadata payload. Native preview is drawn from the same profile rather than server HTML.
- Data: `src/users/card_metadata.py`, card settings/preview handlers; the native slot supplies a demo catalog and saved profiles. Server normalization remains authoritative.
- Reuse/blockers: shared card schema/state. The browser preview remains server-rendered HTML, so the native preview is an equivalent projection, not the server response. Drag ordering is replaced by move buttons. Native persistence and runtime evidence remain open.
- Status: `Partial / coexisting`. Native placement is `in_progress` until a browser adapter and native runtime interactions are verified.
- Validation targets: `src/users/tests/views/test_cards.py`, `src/users/tests/test_card_metadata.py`.

### SET-HOME — Home section/shelf editor

- Purpose/usage: Home rows/filter/sort/list-backed sections.
- Implementation: shared `frontend/settings/HomeScreenEditor.jsx` renders Home sections, row editing, filter fields, status, sort/direction, list selection and global header/label options; `native-proof/app/surfaces/HomeSettingsSlot.jsx` places it on native Settings with demo sections and list choices. The browser page remains `src/templates/users/home_screen.html` with inline `homeScreenSettings()` and Alpine/SortableJS.
- Contract: nested order/labels/colors/collapse, library filters, status and sort, owned/collaborator/smart-list selection, validation and the existing Home settings payload. Save emits the same `{ media_type, rows }` section array. The shared editor owns local validation and dirty/saving/error presentation; the caller owns list results, transport and persistence.
- Data: `src/users/home_screen.py`, Home config/search/filter handlers; the native slot supplies demo sections, filter fields and list choices. Server validation remains authoritative.
- Reuse/blockers: editor model and filter values are shared. Native ordering uses move buttons instead of drag; list search is caller-supplied rather than fetched in presentation. Native persistence, browser mounting and runtime interaction evidence remain open.
- Status: `Partial / coexisting`. Native placement is `in_progress` until a browser adapter and native runtime interactions are verified.
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
- Native provider forms: `frontend/ui/TextField.jsx`, `frontend/ui/SetupGuide.jsx`, `frontend/providers/ConnectionSettings.jsx`, `frontend/providers/AccountSettings.jsx` and `frontend/providers/ImportSettings.jsx` (`ImportSettings`, `ImportPreferencesCard`) extend the shared `SelectField`, `ToggleChip`, `Button` and `SettingsCard` contracts for labelled text/password fields, selects, toggles, masked credential hints, setup-guide copy fields and save/connect/disconnect intents. `native-proof/app/surfaces/ProviderSettingsSlot.jsx` places AniList credential, OAuth setup and import cards plus a Kavita account card on Settings with local edit, busy, saved and error state. Entered values stay in local component state; field metadata and masked hints are presentation only, and credentials, CSRF, permissions, token-bearing copy values and provider-specific action contracts remain in the adapters. Web provider tabs still use the legacy `controls.jsx` forms (`Credentials.jsx`, `AccountConnection.jsx`, `Import.jsx`, `ImportPreferences.jsx`, `SetupGuide.jsx`); retire each consumer when its scoped web control port lands. Native runtime interaction, accessibility and clipboard transport are unverified; Expo export is a build check only.
- Status: `Partial / coexisting`. The provider directory and provider headers/tabs/Overview remain `Web Migrated`; the native provider forms family is `ported` only as a native placement with demo data, while every browser provider tab still uses its existing server-owned or `controls.jsx` form and server fallback.
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
- Native shared presentation: `frontend/settings/DataSettings.jsx` exports `ExportScheduleCard` (frequency/time/content selection), `ScheduledExportsCard` (schedule list and destructive delete), `ExportHistoryCard` (status, timestamps and expandable errors), `RestoreBackupCard` (backup choice and typed RESTORE confirmation) and `RssFeedCard` (media/row selection, skip filters, feed URL copy and preview). `frontend/settings/ConfirmDialog.jsx` supplies the shared destructive confirmation used here and by access revocations. They compose the shared `SettingsCard`, `SelectField`, `TextField`, `ToggleChip` and `Button`. Contracts carry presentation values, masked or stored hints, and async intents only; server schedules, file download/restore execution, clipboard and RSS generation remain server or platform boundaries.
- Native placement: `native-proof/app/surfaces/DataAccessNotificationsSlot.jsx` renders the cards on Settings with demo schedules, history, restore and RSS state. Expo export is a compile check, not runtime verification.

- Status: `Partial / coexisting`. The export form, restore, schedule history, RSS builder and backup status remain server-owned on the web; the shared native cards render on Settings with demo data. Download, clipboard, file restore, feed generation and secure token storage remain platform or server boundaries.

### SET-ACCESS — Tokens, grants and OAuth approval

- Purpose/usage: access settings, application/device authorization.
- Implementation: access-token/integration-token/catalog-grant components, `src/templates/integrations/oauth_applications.html`, `oauth_device.html`.
- Contract: one-time secret, scope/expiry/copy/revoke, grants and device approve/deny.
- Data: token/grant handlers, `src/integrations/oauth_management.py`, `oauth_device.py`.
- Reuse/blockers: fields/status shared; secure native storage/auth lifecycle separately designed, never credentials in shared presentation.
- Validation targets: `src/users/tests/views/test_integration_tokens.py`, `src/integrations/tests/test_oauth_device_flow.py`.
- Native shared presentation: `frontend/settings/AccessSettings.jsx` exports `AccessTokenCard` (masked account token, copy intent and destructive regenerate), `AppTokensCard` (token list, scopes, expiry, one-time secret copy and destructive revoke), `CatalogGrantsCard` (install-credential list/create/revoke) and `AuthorizedApplicationsCard` (OAuth grant list, scope labels and revoke). Existing token values never enter presentation; `AppTokensCard` receives only a masked one-time preview and a copy intent so the adapter keeps the minted secret, matching the store-only-a-hash server rule. Revocations use the shared `ConfirmDialog`; permissions, scopes and transport stay server-owned.
- Native placement: `native-proof/app/surfaces/DataAccessNotificationsSlot.jsx` renders the access cards on Settings with demo tokens, grants and OAuth applications. Expo export is a compile check, not runtime verification.

- Status: `Partial / coexisting`. The browser access-token, install-credential and OAuth application pages remain server-owned; the shared native cards render on Settings with demo data. Token creation, revocation, OAuth authorization and secure credential storage remain server or adapter responsibilities.

### AUTH — Authentication and account security

- Purpose/usage: login/signup/social/password/TOTP/recovery/deletion.
- Implementation: shared presentation `frontend/auth/AuthEntrance.jsx` (`AuthEntrance`, `SocialProviders`, `AuthNotice`) and `frontend/auth/AccountSecurity.jsx` (`ProfileCard`, `AccountTypeCard`, `PasswordCard`, `AuthenticatorCard`, `RecoveryCodesCard`, `ConnectionsCard`, `DeleteAccountCard`) reuse `TextField`, `Button`, `Chip`, `ToggleChip`, `SettingsCard` and `ConfirmDialog`. The browser remains the server-rendered `src/templates/account/`, `allauth/`, `socialaccount/`, `users/account.html` and `password_recover.html`; no auth web adapter is mounted. The native data boundary is `native-proof/app/data/authTransportCore.js` (server URL validation, token and allauth session login, CSRF refresh, connection test, expiry/revocation/error classification), `authTransport.js` (Expo SecureStore and active request facade) and `authTransport.web.js` (no secret storage; web sign-in stays same-origin).
- Contract: login/signup/recovery modes, social provider actions, field and non-field errors, success/redirect notices, password and authenticator setup, recovery-code display/regeneration, connection management, and identity-confirmed deletion with demo and last-superuser guards. Sessions, CSRF, allauth redirects, QR secrets and credential storage stay in platform adapters; universal props carry presentation data and intents only. No email/SMS recovery is implied.
- Data: allauth, `src/users/forms.py`, signup/account/recovery handlers; native callers supply values, errors and actions from their adapter.
- Reuse/blockers: shared fields/buttons/dialog and the QR/manual-secret slots keep credentials at the platform boundary; browser sessions/CSRF/allauth do not establish native auth. Initial native demo placement is `native-proof/app/screens/AuthScreen.jsx` with guard-state chips.
- Status: `Partial / coexisting`. The native shell renders finished login, signup, recovery and account-security demo states from shared React Native presentation. The Django entrance, account and recovery pages stay server-owned and keep their fallback. The core native transport now supports server URL and credential entry, token and session login, SecureStore persistence, CSRF refresh, connection tests and expiry/revocation states; `AuthScreen` still uses demo values and is not wired to it, so the surface remains `in_progress`. Provider redirects and live TOTP/QR delivery are not implemented.
- Verification: `npm run test:transport` passes 15 Node tests covering URL/credential validation, token and session login, CSRF retry, revocation, safe error redaction, SecureStore persistence shape and media-card/list/calendar wiring. Expo export is a compile check only; no browser, iOS or Android runtime pass was performed for these shared components.
- Validation targets: `src/users/tests/views/test_signup.py`, `src/users/tests/views/test_profile.py`, `src/users/tests/views/test_password_recovery.py`, `src/users/tests/test_delete_account.py`, `test_demo_account_guard.py`.

### SET-USERS — Superuser account management

- Purpose/usage: superuser-only Settings page listing accounts, searching/filtering them, creating accounts, activating/deactivating, changing superuser access, setting a password and deleting an account with confirmation.
- Implementation: universal `frontend/users/UsersManagement.jsx`; browser mount in `frontend/settings/mount.jsx` and `frontend/settings/index.js`; page `src/templates/users/manage_users.html`; JSON writes in `src/users/views.py` and routes in `src/users/urls.py`.
- Contract: account rows show username, email, joined date, last login and role/active state. Accounts with `is_test_account` are excluded from the list and from every write endpoint, matching the normal user-picker exclusion. Superuser access is the only role this page grants; promotion also sets the Django staff flag required for admin, and demotion clears it. Create, password and delete actions are superuser-only server-side; the UI never displays an existing password. Deleting yourself or the last active superuser, and demoting/deactivating yourself or the last active superuser, are rejected. Deletion removes scheduled periodic tasks before the account cascade. Server-side permissions remain authoritative and every write is logged.
- Data: server-serialized user rows, translated labels, CSRF token and action URL templates in one `json_script`; presentation props contain no stored credentials. The browser adapter owns `fetch`, CSRF headers and URL id substitution; no raw HTML is passed to React.
- Reuse/blockers: reuses shared `SettingsCard`, `Chip`, `Button`, `TextField` and `SelectField`. The page body is React; the only server-rendered markup is the no-JavaScript fallback inside the mount host. The settings shell and navigation stay Django-owned; a native client still needs an authenticated transport and server identity.
- Status: `Web Migrated` for the page body and account actions. Settings navigation is legacy. The native slot compiles through the Expo bundle.
- Verification: Django tests cover authorization, role changes, create, privilege guards, password change, deletion and test-account exclusion. `npm run check:ui`, the architecture checks, and an Expo export compile were run; no iOS or Android interaction pass was performed in this change.
- Related work: [#1818](https://github.com/dannyvfilms/Floppy/issues/1818).
- Deferrals: native transport, authenticated native mutations and a full iOS/Android interaction pass remain open.

### SET-NOTIFICATIONS — Notification preferences/exclusions

- Purpose/usage: release/premiere/digest/test and media exclusion list.
- Implementation: `src/templates/users/notifications.html`, search-results/excluded-items components.
- Contract: save/choice/error/test feedback, 300ms search and include/exclude refresh.
- Data: notification/test/search/exclusion handlers and delivery jobs.
- Reuse/blockers: selection/search/exclusion shared; delivery/scheduling remains server capability.
- Validation targets: `src/users/tests/views/test_notifications.py`.
- Native shared presentation: `frontend/settings/NotificationSettings.jsx` exports `NotificationPreferencesCard` (Apprise/playback webhook drafts, stored-credential hints, digest/release/premiere choices, test and save states) and `ExcludedMediaCard` (bounded search, exclusions and include/exclude intents). Stored Apprise URLs and webhook secrets are represented by stored hints and blank replace fields, never by serialized values; newly entered values stay in local form state. The card reuses `SettingsCard`, `FormSaveBar`, `TextField`, `ToggleChip`, `Button` and `Spinner`.
- Native placement: `native-proof/app/surfaces/DataAccessNotificationsSlot.jsx` renders both cards on Settings with demo busy, error and success state. Expo export is a compile check, not runtime verification.

- Status: `Partial / coexisting`. The browser notifications page and Alpine exclusion search remain server-owned; the shared native cards render on Settings with demo data. Delivery, scheduling, webhook signing and stored Apprise credentials remain server responsibilities.

### ONBOARDING — Resumable first-run setup

- Purpose/usage: media/metadata/services wizard, connection/upload/OAuth/Trakt variants/banner.
- Implementation: `src/templates/users/onboarding/`, onboarding-banner component; shared media-type picker. Universal native presentation: `frontend/onboarding/OnboardingWizard.jsx` exports `OnboardingWizard`, `OnboardingNotice`, `OnboardingMediaTypesStep`, `OnboardingMetadataStep`, `OnboardingServicesStep`, `OnboardingSummaryStep`, `OnboardingServiceSetupStep`, `OnboardingIntegrationStep`, `OnboardingImportStatusStep` and `OnboardingCompleteStep`.
- Contract: persisted resume/restart/skip/next, connect/import status, Plex instructions and device fallback. The native wizard keeps `onboarding_status` and `onboarding_step` semantics: an unfinished wizard stays `in_progress`, restart reopens media types, skipping media types or finishing import completes setup, selected/skipped/connected sources are retained, and the stale `import_status` resume edge is normalised through scrobbling. Connection variants cover credential/host/API-key forms, uploads, OAuth, Trakt public/private/export profiles, and a device-code fallback for sources without an inline form. Import rows carry queued/running/done/failed status.
- Data: `src/users/onboarding_views.py`, `src/integrations/onboarding.py`, user state/ImportRun. The native shell uses `native-proof/app/data/onboardingState.js` (Expo file storage) and `onboardingState.web.js` (browser local storage) for demo resume state; secrets stay in local form state and are never persisted or passed to presentation. Server permissions and transport remain authoritative and are not reproduced in the shell.
- Reuse/blockers: wizard reuses shared `SettingsCard`, `Chip`, `Button`, `TextField`, `SelectField`, `SetupGuide` and `ConfirmDialog`. The standalone browser wizard remains server-owned; native transport, real OAuth handoff, live import progress and iOS/Android runtime verification are not implemented.
- Native placement: `native-proof/app/screens/OnboardingScreen.jsx` replaces the placeholder with the demo wizard (`ported`).
- Status: `Partial / coexisting`. Browser onboarding stays Django/Alpine; the universal wizard renders in the native shell with demo persistence. No iOS or Android runtime, interaction or assistive-technology pass was performed.
- Verification: `src/users/tests/views/test_onboarding.py`, `src/integrations/tests/test_onboarding.py`; Expo export is a compile check, not runtime evidence.
- Validation targets: `src/users/tests/views/test_onboarding.py`, `src/integrations/tests/test_onboarding.py`.

### SET-SYSTEM — Advanced, About, updates and install

- Purpose/usage: administration/server info/release/install feedback.
- Implementation: `src/templates/users/advanced.html`, `about.html`, server-port/update-banner/whats-new components; shared native cards in `frontend/settings/AdvancedSettings.jsx` (`LogsCard`, `ImageCacheCard`, `CacheManagementCard`, `ServerPortCard`) and `frontend/settings/AboutSettings.jsx` (`ReleaseUpdateBanner`, `AboutOverviewCard`, `WhatsNewCard`, `InstallCard`, `ProjectResourcesCard`, `DeveloperSpecsCard`, `AttributionsCard`, `LicenseCard`, `AboutVersionFooter`). Browser adapters are `frontend/settings/mountAdvanced.jsx` and `frontend/settings/mountAbout.jsx`.
- Contract: save/clear confirmation on image cache, per-cache and all-cache confirmations, log download and superuser gating, server port create/update/reset with environment override and config errors, update announcement, What's New rows, install guidance, project links, API specs, attributions, licence and version.
- Data: advanced/about/release handlers, `src/users/server_port_views.py`, server-built card props in `src/users/advanced_props.py`. The browser adapter reads one CSRF token and the existing action URLs; no credentials enter presentation props.
- Reuse/blockers: shared card, button, toggle, field and confirmation primitives. The Advanced page mounts all four shared cards over its server fallback. About mounts the description, What's New, install, resource, attribution, licence and version cards; its Developer & API specifications table and schema viewer remain server-owned so preview/download parity is not lost. The global `update_banner.html` also remains server-owned. Native cards receive demo port, release, image-cache and cache state; server transport and browser PWA install events stay in the adapters.
- Validation targets: `src/users/tests/views/test_server_port.py`, `src/users/tests/views/test_image_cache.py`, `src/users/tests/views/test_about.py`, `src/users/tests/views/test_about_install_integration.py`.
- Native shared presentation: the cards reuse `SettingsCard`, `Button`, `TextField`, `ToggleChip`, `Badge` and `ConfirmDialog`. Destructive image/cache actions keep explicit confirmation copy and per-cache warnings; the server port form validates 1–65535 and respects the environment override; non-superusers see read-only cache and port state. `native-proof/app/screens/SettingsAdvancedScreen.jsx` replaces the placeholder with realistic demo content.
- Native placement: Expo export is a compile check, not runtime verification. iOS and Android interaction, VoiceOver/TalkBack and real link/file behaviour remain unverified.

- Status: `Partial / coexisting`. The browser Advanced page and most About sections now mount the shared cards, while the Developer & API specifications table, schema viewer, generic update banner and all no-JS markup remain server-owned fallbacks. Native transport and iOS/Android runtime evidence remain outstanding.

### MATCH-REVIEW — Integration match correction

- Purpose/usage: unmatched/incorrect media review.
- Implementation: `src/templates/integrations/match_fix.html`, `src/static/js/matchFixReview.js`.
- Contract: filters/candidates/chosen identity, POST/error and retained tracking semantics.
- Data: integration views and `src/integrations/match_corrections.py`.
- Reuse/blockers: shared selection/review pattern; distinct correction semantics and permissions remain explicit.
- Validation targets: `src/integrations/tests/test_matching_and_corrections.py`.

### INTEGRATION-PANELS — Library/download and Seerr requests

- Purpose/usage: detail Arr/Seerr status and request actions.
- Implementation: server-owned `src/templates/integrations/library_panel.html`, `seerr_request.html` and `seerr_status.html`; universal `frontend/ui/IntegrationPanels.jsx` (`ArrLibraryPanels`, `SeerrRequestsCard`, `SeerrStatusBadge`, `SeerrRequestDialog`); native placement in `native-proof/app/screens/IntegrationsScreen.jsx`.
- Contract: nearest-panel replacement, instance/media/season/episode identity, status and queue detail, copy feedback, per-season request/status, permissions, provider errors and parent modal close state. The universal panels reuse the shared settings card, badge, button and modal dialog contracts; callers supply media context, panel data, labels and action callbacks.
- Data: `src/integrations/arr_library.py`, `src/integrations/seerr_api.py` and the integration handlers. Web transport, credentials, permissions, CSRF and HTMX replacement stay server-owned; native transport and system-browser handoff remain adapters.
- Reuse/blockers: status/actions shared; parent Alpine/HTMX coupling must be removed deliberately; server capabilities required. The native screen runs realistic show, season and episode demo data because the shell has no transport, so the live request/search/copy lifecycle is presentation-shaped but not connected.
- Status: `Partial / coexisting`. The native Integrations slot is ported and renders show, season and episode Arr panels (has file, downloading queue, missing, activity, per-instance provider error, copy feedback), Seerr request rows and a per-season request dialog. The web detail pages still use the server-rendered htmx panels, permissions and progressive fallback.
- Verification: shared presentation compiles through the Expo export and the UI architecture checks; targeted Django Arr/Seerr tests cover the server contract. No browser, simulator, device, VoiceOver or TalkBack interaction pass was performed for the universal panels.
- Validation targets: `src/integrations/tests/test_arr_library.py`, `src/integrations/tests/test_seerr_request.py`; browser/native lifecycle remains unverified.

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
- Status: `Partial / coexisting`. On the web, React owns `BulkActionBar` (one-line count, icon-only Update Status, Add to List, Add to Collection and Apply Tag actions, an ellipsis menu holding Add Plays to History, and Deselect All), the status dialog, the plays form and the job dock; the status confirmation and the dock's progress/summary/problems presentation come from the shared `BulkActionDialog`, `BulkJobCard`, `BulkJobProgress`, `BulkJobSummary` and `BulkJobProblems`. Selection state, select-mode and the card checkboxes remain legacy Alpine (`bulkSelection.js`, media cards). Browser verification from the earlier toolbar/dock port remains the evidence for the browser behavior; the shared-dialog and shared-dock swap is compile-checked only in this change. Native placement: `frontend/ui/BulkActions.jsx` exports `BulkToolbar`, `BulkActionDialog`, `BulkOptionRow`, `BulkNote`, `BulkFieldRow`, `BulkActionRow`, `BulkJobCard`, `BulkJobProgress`, `BulkJobSummary`, `BulkJobProblems` and `BulkJobMessage`; `frontend/ui/BulkJobDock.web.jsx`/`.native.jsx` own the platform dock anchor. `native-proof/app/surfaces/BulkSlot.jsx` renders Library select mode, card selection, count, Update Status, Add to List, Add to Collection, Apply Tag, Add Plays review, confirmation dialogs, job progress, busy and partial-failure results and clear/reset with realistic demo selection. Server writes remain web-owned. iOS and Android: Expo export compile only; no simulator, emulator, VoiceOver or TalkBack interaction pass.
- Implementation: `frontend/ui/BulkActionBar.web.jsx` and `BulkActionBar.native.jsx` (web icon toolbar and its native counterpart, sharing the `BulkActionBar` contract), `frontend/ui/mountBulkToolbar.jsx` (per list page, reads `window.__bulkSelection`), `frontend/ui/mountBulkActions.jsx` (a web adapter mounted once in `base.html` for signed-in users), `frontend/ui/BulkJobDock.web.jsx`/`.native.jsx` (platform dock anchor) and the `ActionMenu` in `frontend/ui/controls.jsx` (styles in `controls.css`). Alpine and React talk through window events: `bulk-selection-change`, `bulk-actions-open`, `bulk-actions-done`, `bulk-actions-clear`, `bulk-job-finished`. Add Plays jobs persist in localStorage (`floppy-bulk-jobs`) and resume after navigation or reload. Native presentation reuses `frontend/ui/Button.jsx` and `frontend/ui/MediaCardView.jsx` selection state; the demo writes stay in `BulkSlot` and the browser transport stays in the web adapter.
- Data/transport: `app/bulk_action_views.py` (`bulk_status_update`, `bulk_show_plays_start`, `bulk_show_plays_status`, quick list/collection/tag endpoints unchanged), `app/services/bulk_show_plays.py`, `bulk_show_plays_task` on the default `celery` queue. Writes go through `apply_bulk_episode_plays`, the single-show Episode Plays path.
- Retirement: Alpine select-mode and card checkboxes retire when the media card selection is ported (see the media card entry). Legacy toolbar markup is removed.
- Reuse/blockers: no server fallback for the toolbar; if the island fails to mount, selection works but no actions show. Reopen if a no-JS path is required. Add Plays to History shows on non-TV lists and reports those items as skipped.
