# UI component register

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

- `Existing`: current implementation, not migrated.
- `Ready`: foundation validated and component assessed for migration.
- `Web Migrated`: accepted browser replacement; native verification stays separate.
- `Cross-Platform Verified`: shared implementation passed recorded web, iOS and Android checks.
- `Exception`: intentionally platform-specific, unsuitable or blocked; document reason and reconsideration condition.

**Defaults for every entry below:** Status `Existing`; verification is static source
inspection only, browser migration not performed, native not tested. Test references
are available regression targets, **not executed test results**. Related work and
recurring deferrals: none recorded; attach real issue/PR links when known. The
settings-card shell is the first authorized browser pilot; native proof remains open.
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
- Verification: production assets build and collect through Django; targeted Django/theme tests passed. Chromium 151/macOS browser checks cover initial/HTMX/back-forward lifecycle, focus, real CSRF submissions, fallback, responsive widths and six theme states. iOS/Android not tested; no native compatibility claim.
- Related work: [#1793](https://github.com/dannyvfilms/Floppy/issues/1793); user-authorized first React browser component pilot.
- Deferrals: server-owned form bodies retire through scoped control ports after parity checks; native acceptance awaits actual iOS/Android runs and a native theme/transport boundary. Broader performance evidence remains required before larger component adoption.

### FORM-CONTROLS — Fields, popovers, dialogs and feedback

- Purpose/usage: repeated buttons, inputs/selectors/tabs, confirmations, help/errors and notifications across forms, settings, filters and modals.
- Implementation: [app-wide React controls](react-components.md), `frontend/ui/controls.jsx` and `controls.css`, consumed by provider Overview/Connection/Import/Activity. Legacy consumers include inline templates, `src/templates/users/components/info_tip.html`, `form_save_bar.html`, allauth fields, base modal/toast infrastructure and `src/static/js/keepPopupsOnScreen.js`.
- Contract: labels, selected/disabled/busy states, errors/CSRF, click-away/Escape and existing focus behavior, viewport-safe popups, dirty-save live announcements. A universal modal focus trap is not established.
- Data: owning Django forms/errors/messages, Alpine state and response events; feature endpoints retain action semantics.
- Reuse/blockers: use shared `SelectField` for preference forms and `FilterDropdown` for Lists-style filter toolbars. Both share keyboard/typeahead/dismissal behavior but retain distinct appearances. Legacy dropdowns remain inline until their UI is reworked; native behavior still needs proof.
- Validation targets: owning feature tests, `src/users/tests/views/test_preferences.py`; general accessibility interaction coverage unverified.
- Status: `Web Migrated` for shared React buttons, labeled fields/selects, chips/toggle chips, tabs, dialogs and card grids, used throughout AniList. Other consumers retain legacy controls until reworked. Reuse these components by element, without requiring a whole provider/page port. Provider-specific authentication and transport remain in feature code.
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

- Purpose/usage: library, Home, related, search, Discover, lists, collection, credits and tier/group surfaces.
- Implementation: `src/templates/app/components/media_card.html`, `card_lines.html`, `media_card_list.html`, `src/app/card_surfaces.py`, template tags.
- Contract: declared surface/tag, viewer rating/status, aspect ratios, obfuscation, hover/touch actions, public/read-only/bulk states and stable OOB status wrappers.
- Data: `media_list_entries_for_items`, surface flags, card configuration and server projections.
- Reuse/blockers: highest leverage; [media-card contract](../architecture/media-card.md) authoritative. Replace consumers and response slots, never create an unrelated second card system.
- Validation targets: `src/app/tests/test_media_card_contract.py`; complete native/consumer matrix outstanding.

### RATING — Score display and picker

- Purpose/usage: cards, details, children and music scores.
- Implementation: `src/templates/app/components/rating_picker.html`, `media_card_rating.html`, `media_card_rate_button.html`, OOB/score-chip/derived-TV fragments.
- Contract: viewer scale, empty/read-only states, hover preview, toggle-to-clear, CSRF writes, teleported popup and OOB/events; derived score/coverage differs from direct score.
- Data: `src/app/score_views.py` and server score projections.
- Reuse/blockers: read-only presentation recommended first proof; interactive picker needs later portal/focus/write proof. Do not infer keyboard support from pointer behavior.
- Validation targets: `src/app/tests/views/test_score_views.py`, `src/app/tests/test_derived_tv_ratings.py`, card contract tests.

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
- Migration state: existing menus/toolbars remain legacy on library and list surfaces;
  the adjacent alphabet filter is fully React-owned (ALPHABET).
- Implementation: `src/templates/app/components/filter_menu.html`, `filter_form.html`, toolbar/range/scripts, `sidebar_saved_views.html`; `src/static/js/libraryFilterState.js`, `savedViews.js`.
- Contract: normalized rules, clear/default/range/relative/multi-value handling, URL/history/sort, saved-view expand/reorder; refresh after Alpine flush avoids one-click lag.
- Data: owning view catalogs, shared library query, `src/lists/smart_rules.py`, saved-view endpoints in `src/users/views.py`.
- Reuse/blockers: strong state reuse; preserve per-surface availability. URL/forms/SortableJS remain web boundaries.
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
- Implementation: `src/templates/app/search.html`, search suggestion/parent fragments; `src/static/js/searchAutocomplete.js`, `searchShortcut.js`, `barcode-scanner.js`.
- Contract: type/local-All/provider queries, pagination/matched titles, two-character suggestions, active-descendant arrows/Enter, shortcut ignores editing, photo ISBN/error/manual fallback.
- Data: `src/app/search_views.py`, provider services, manual artist/album routes; API search parity unverified.
- Reuse/blockers: result/selection values shared; browser keyboard/file/blob and ZXing decoding need native camera equivalents.
- Validation targets: `src/app/tests/test_search_suggestions.py`, `src/app/tests/views/test_media_search.py`, barcode selfcheck.

### RAILS — Horizontal scrolling and load more

- Purpose/usage: Home, cast, recommendations and related rows.
- Implementation: `src/templates/app/components/_scrollable_row.html`, `_scrollable_row_js.html`, `src/static/js/horizontal-scroll.js`.
- Contract: heading/collapse state, arrows/drag/touch, suppress post-drag clicks, bounded load-more, stable art anchors and listener cleanup.
- Data: row descriptors/fragment URL/item template from owning view.
- Reuse/blockers: row/item values shared; scrolling/observer/pointer/persistence adapters required.
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
- Book format links: an "Other Formats" fact (eBook, Audiobook, each a link) in the Details card of Book pages, shown only when the viewer tracks another format of the same work. Status: legacy, not migrated. Blocker: the Details card is a server-rendered fact list with no shared React equivalent, and porting it is a whole-card migration, not part of this change. Reopen when the DETAIL sidebar facts get a shared React component; this row moves with it. Data: `build_other_book_formats` (ISBN, or title plus author, among the viewer's own tracked books; never merges Items). Verification: browser only; no iOS/Android.

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
- Implementation: `src/templates/app/components/date_time_picker.html`, `calendar.html`, `src/static/js/dateTimePicker.js`, `calendar.js`.
- Contract: clear/current/release/copy, optional time, 12/24h/week-start/locale, six-week grid/month/year, marked/selectable days, hidden values/events and Escape.
- Data: owning field/history configuration and user preferences.
- Reuse/blockers: calculations shareable; native field/popup, timezone and focus semantics need proof.
- Validation targets: owning tracking/history tests; comprehensive independent keyboard/timezone coverage unverified.

### NOTES — Markdown editing and display

- Purpose/usage: detail/media forms/music track notes.
- Implementation: markdown/detail-note/music-note fragments; `src/static/js/markdown-editor.js` and marked.
- Contract: Write/Preview, toolbar/selection, safe rendering, initialization after full/HTMX loads and save errors.
- Data: bound note fields and music note handler in `src/app/music_views.py`.
- Reuse/blockers: text/formatting intent shared; textarea selection and HTML preview need platform implementation/content safety review.
- Validation targets: `src/app/tests/views/test_music_track_notes.py`; general editor interactions unverified.

### PROGRESS — Adjustment and repeat breakdown

- Purpose/usage: Home/detail progress.
- Implementation: progress changer/breakdown/detail slot fragments.
- Contract: +/-/zero disabled state, spinner/live announcement, medium units/max, TV/season breakdown and run-specific cancel/refresh.
- Data: `src/app/progress_views.py`, progress handler in `src/app/views.py`, domain operations.
- Reuse/blockers: display/buttons shared; preserve authoritative server progress and operation identity.
- Validation targets: `src/app/tests/views/test_progress.py`, `test_rewatch.py`.

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
- Implementation: `src/templates/events/calendar.html`, calendar grid/list components; primarily inline Alpine.
- Contract: month/today/grid/list, media/status/release/tag filters, persisted view, grouped dates/media, ICS/download/subscription/reload and empty states. Redesign needs explicit requirements.
- Data: `src/events/views.py`, `src/events/calendar/`, tasks; [reload contract](../architecture/calendar-reload.md), REST parity unverified.
- Reuse/blockers: date/filter/group values shared; layout/ICS/browser subscription adapters explicit.
- Validation targets: `src/events/tests/test_views.py`, `test_release_semantics.py`, `calendar/test_main.py`, `src/api/tests/test_calendar.py`.

### LISTS — Lists, memberships, public profiles and collaboration

- Purpose/usage: list browser/detail/activity/profile/forms and membership popup.
- Migration state by surface: manual-list grid/table/tiers and public detail pages
  consume the fully React-owned ALPHABET sibling. Existing list headers, toolbars,
  cards/tables and editing controls retain legacy ownership; migrate each when edited.
- Implementation: `src/templates/lists/custom_lists.html`, `list_detail.html`, `user_profile.html`, `list_activity.html`, list grid/form/visibility/membership/table components.
- Contract: manual/smart/source-backed distinction, search/tags/roles, public/unlisted/private, membership/pins/feed/export/sync and public read-only rendering.
- Data: `src/lists/views.py`, browse/action/helper views, models/forms; REST parity separately assessed.
- Reuse/blockers: list card/editor/membership shared; consume canonical media/filter/table systems; collection ownership is separate.
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
  `FileImport.jsx` inline instead of a modal. Remaining legacy, each with a concrete blocker: Plex
  libraries picker and webhook sharing (live library fetch, per-share Alpine state); Jellyfin account/push controls (conditional per-tab
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
