# UI source ownership map

[Component contracts and statuses](component-register.md) explain each stable ID.
Each path has one primary owner; cross-family consumption is described in the
register. Ownership does not mean every member can share one native renderer.
Inline scripts/styles belong to their owning template.

This map covers application HTML/text templates, the frontend component/build sources, JavaScript modules/selfchecks,
vendored scripts/localizations, and CSS. Template SVG icons, fonts, logos, favicons
and the web manifest belong to `TOKENS`/`WEB-UTILITIES` as assets, not independent
components. Translation catalogs, generated staticfiles, third-party admin templates
and uploaded media are outside this application-source map. Vendored library source
was identified by dependency/use, not audited internally.

Update a file's owner here when adding, moving or removing it, and update its affected
contract. Shared includes are owned once; record consumers in the register. Add an ID
only for an independently meaningful behavioral contract.

## Lightweight consistency check

Run from the repository root after inventory/path changes. This checks missing/stale
paths, duplicate ownership and unknown IDs; it cannot validate behavior or decide
whether a new component needs its own entry. No new CI/build tooling is needed.

```bash
rtk proxy python - <<'PY'
from collections import Counter
from pathlib import Path
import re

register = Path("docs/ui/component-register.md").read_text()
source_map = Path("docs/ui/source-map.md").read_text()
ids = set(re.findall(r"^### ([A-Z][A-Z-]+) —", register, re.M))
patterns = re.findall(r"^- `((?:src|frontend|scripts)/[^`]+)`$", source_map, re.M)
paths = []
for pattern in patterns:
    if "*" in pattern:
        paths.extend([str(p) for p in Path(".").glob(pattern)] or [pattern])
    else:
        paths.append(pattern)
expected = set()
for root, suffixes in [("src/templates", {".html", ".txt"}),
                       ("src/static/js", {".js", ".mjs"}),
                       ("src/static/css", {".css"}),
                       ("src/static/ui", {".js", ".css"}),
                       ("frontend", {".js", ".jsx", ".css"})]:
    expected.update(str(p) for p in Path(root).rglob("*")
                    if p.is_file() and p.suffix in suffixes)
expected.add("scripts/build_ui.mjs")
missing = sorted(expected - set(paths))
stale = sorted(set(paths) - expected)
duplicates = sorted(p for p, count in Counter(paths).items() if count > 1)
headings = re.findall(r"^## ([A-Z][A-Z-]+)$", source_map, re.M)
unknown = sorted(set(headings) - ids)
assert not (missing or stale or duplicates or unknown), (missing, stale, duplicates, unknown)
print(f"Covered {len(expected)} source files; {len(ids)} component families; no path/ID drift.")
PY
```

## SHELL

- `src/static/js/libraries/alpinejs-3.14.9.min.js`
- `src/static/js/libraries/htmx-2.0.4.min.js`
- `src/static/js/safari-rail.js`
- `src/templates/app/components/sidebar_navigation_items.html`
- `src/templates/app/components/sidebar_pin_menu.html`
- `src/templates/base.html`
- `frontend/ui/Sidebar.jsx`, `frontend/ui/mountSidebar.jsx`, `frontend/ui/sidebar.css`, `src/app/sidebar_model.py` (signed-in sidebar inside `base.html`; the onboarding banner stays a server slot)
- `frontend/ui/Icon.jsx`, `src/app/icon_specs.py` (shared icon shapes for React; used by the sidebar and the card hover buttons)
- `frontend/ui/ModalHost.jsx`, `frontend/ui/mountModalHost.jsx` (shared popup host, mounted from `base.html`; the card hover buttons and the legacy Add-to-lists buttons open it through `floppy-open-modal`; the Add-to-lists body is shared presentation in `frontend/ui/ListsFormView.jsx` through the `frontend/ui/ListsForm.web.jsx` adapter with `modal-forms.css`; the Track body is still the server form, see POPUP-HOST in the register)
- `src/app/card_events.py` (the floppyCardUpdate event sent by `media_save` and the score views so React cards refresh their status chip and rating)
- `frontend/ui/mountFilterChips.jsx`, `ScrollRow` and `FilterChips` in `frontend/ui/controls.jsx` (Discover media-type row; `Tabs` shares `ScrollRow`)
- `src/templates/base_public.html`

## SETTINGS-CARD

Shared `SettingsCard` and `Chip` use native presentation. `Chip.web.jsx` is the
browser link and palette adapter; `controls.jsx` keeps its web wrapper and the
server fallback classes remain in `settings-card.css`.

- `frontend/settings/Chip.jsx`
- `frontend/settings/Chip.web.jsx`

- `frontend/settings/SettingsCard.jsx`
- `frontend/settings/index.js`
- `frontend/settings/mount.jsx`
- `frontend/settings/root.jsx`
- `frontend/settings/webPalette.js`
- `frontend/settings/settings-card.css`
- `native-proof/app/surfaces/SettingsCardSlot.jsx` (native placement on the Settings screen)
- `src/templates/app/components/ui_asset_refresh.html`
- `scripts/build_ui.mjs`
- `src/static/ui/*.js`
- `src/static/ui/*.css`
- `src/templates/users/components/settings_card.html`
- `src/templates/users/components/settings_link_chip.html`
- `src/templates/app/components/detail_secondary_content.html` (Book "Format" and "Narrator" facts)

The generated UI subtree belongs to this island runtime; globs cover content-hashed
chunks without renaming ownership records on every build. License notices are
build artifacts. The Python composition tag is documented in the register.

## FORM-CONTROLS

- `frontend/ui/controls.jsx`
- `frontend/ui/controls.css`
- `src/static/css/libraries/select2-4.1.0.min.css`
- `src/static/js/i18n/de.js`
- `src/static/js/i18n/en.js`
- `src/static/js/i18n/fr.js`
- `src/static/js/keepPopupsOnScreen.js`
- `src/static/js/libraries/jquery-3.7.1.min.js`
- `src/static/js/libraries/select2-4.1.0.min.js`
- `src/static/js/libraries/sortablejs-1.15.3.min.js`
- `src/templates/users/components/form_save_bar.html`
- `src/templates/users/components/info_tip.html`

## TOKENS

- `src/static/css/input.css`
- `src/static/css/main.css`

## ARTWORK-LOADING

- `src/static/js/artwork-loading.js`
- `src/static/js/image-fallback.js`
- `src/static/js/libraries/lazysizes-5.3.2.min.js`

## ASYNC-STATE

- `src/static/js/cache-updater.js`
- `src/static/js/cache-updater.selfcheck.mjs`

## SPINNER

Shared `Spinner` uses native primitives; the web adapter resolves theme colors. `controls.jsx` re-exports the web interface for `GlobalSearch` and `ListsForm`. Server fallback styling remains in `controls.css` until Django fallback is retired; template consumers are mapped under their own families. The native shell renders the shared component directly; the register records separate browser, iOS and Android runtime evidence and limitations.

- `frontend/ui/Spinner.jsx`
- `frontend/ui/SpinnerTheme.web.jsx`

- `frontend/ui/mountSpinner.jsx`
- `src/templates/users/components/spinner.html`
- `src/users/tests/test_spinner_browser.py`


## BADGE

Shared `Badge` uses native presentation; `controls.jsx` re-exports its web adapter.
Fallback styling remains in `controls.css`; templates are mapped under their own families.

- `frontend/ui/Badge.jsx`
- `frontend/ui/BadgeTheme.web.jsx`

- `frontend/ui/mountBadge.jsx`
- `src/users/tests/test_badge_browser.py`
- `src/templates/users/components/badge.html`
- `src/users/templatetags/ui_tags.py` (`{% badge %}`)
- Consumers: `app/podcast_show_detail.html`, `app/episode_details.html`, `app/music_album_detail.html`, `app/components/detail_music_artist.html`, `detail_music_album.html`, `detail_music_track.html`, `detail_secondary_content.html`, `cells/media_genres_cell.html`, `media_metadata_panel.html`, `lists/components/add_item_preview_modal.html`, `recommend_preview_modal.html`, `integrations/library_panel.html`, `integrations/seerr_status.html`, `users/components/whats_new.html`, `users/onboarding/metadata.html`

## BUTTON

Universal `Button` lives in `frontend/ui/Button.jsx`; the browser platform implementation is `frontend/ui/Button.web.jsx` (`.ui-button` in `controls.css`) and the native counterpart is `frontend/ui/Button.native.jsx`. The legacy `Button` in `frontend/ui/controls.jsx` still serves its own frozen `Dialog` and `ActionMenu` statements and the React islands that import it through `controls`.

- `frontend/ui/Button.jsx`
- `frontend/ui/Button.web.jsx`
- `frontend/ui/Button.native.jsx`
- `frontend/ui/mountButton.jsx`
- `native-proof/app/surfaces/ButtonSlot.jsx` (native placement in the Settings save bar and Library load-more/danger actions; status `ported`)
- `src/templates/users/components/button.html`
- `src/users/templatetags/ui_tags.py` (`{% button %}`)
- Consumers (30 templates, 78 sites): `users/account.html`, `users/cards.html`, `users/_reading_server_modal.html`, `users/components/provider_import.html`, `provider_instance_credentials.html`, `provider_personal_credentials.html`, `tmdb_proxy.html`, `tmdb_rating_sync.html`, `wetrakr_sync.html`, `media_type_provider_modal.html`, `users/providers/integrations/jellyfin.html`, `users/providers/mal_sync.html`, `users/providers/mal_connection.html`, `users/advanced.html`, `users/components/metadata_library_repair.html`, `catalog_grants.html`, `integration_tokens.html`, `sync_state_section.html`, `users/onboarding/media_types.html`, `metadata.html`, `import_status.html`, `components/connect_trakt.html`, `lists/custom_lists.html`, `integrations/oauth_device.html`, `integrations/match_fix.html`, `app/components/collection_modal.html`, `collection_entry_summary.html`, `music_track_notes.html`, `history_day.html`, `fill_track_song.html`.
- Remaining legacy: `frontend/ui/controls.jsx` Button (its frozen `Dialog`/`ActionMenu` statements and the React-island consumers that import it), 198 hand-written solid indigo or red buttons in 81 templates, Alpine-bound buttons (872 tags), in-place htmx toggles, icon buttons, composed-attribute/composed-label buttons and the look variants listed in the BUTTON register entry.

## WEB-UTILITIES

- `src/static/js/copy-item.js`
- `src/static/js/serviceworker.js`

## ERRORS-DOCS

- `src/templates/400.html`
- `src/templates/403.html`
- `src/templates/403_csrf.html`
- `src/templates/404.html`
- `src/templates/500.html`
- `src/templates/api/docs.html`
- `src/templates/includes/error_report_panel.html`

## MEDIA-CARD

- `frontend/ui/MediaCardView.jsx` (universal native card shell: layouts, artwork fallback, chips, progress, title/lines, rating affordance and read-only/selectable states; presentation only)
- `frontend/ui/MediaCardActions.jsx` (universal action overlay, row buttons and list-reorder controls; explicit action/reorder/reveal callbacks, no transport)
- `frontend/ui/MediaCardActionHost.jsx` (universal popup shell for the card action callback contract; the browser ModalHost remains the web host)
- `frontend/ui/MediaCardFormControls.jsx` (`FormHeader`, `FormField`, `FormTextField`, `FormSelect`, `FormStatus` and `FormError` for the shared action forms; presentation only)
- `frontend/ui/ListsFormView.jsx` (universal `ListsForm`: tag filter, count, Add/Remove rows, loading/error/empty states and accessible header; presentation only)
- `frontend/ui/ListsForm.web.jsx` (browser transport adapter: JSON list model, CSRF toggle, `floppy-list-toggled` event and errors for the shared `ListsForm`)
- `frontend/ui/TrackForm.jsx` (universal `TrackForm`: General tab fields, date-time fields, notes, validation, tab host and save/delete states; presentation only)
- `frontend/ui/TrackFormTabs.jsx` (universal `TrackTabs`: General, Tags, Metadata, Collection, Plays/Episode plays, Status history and Discover tab strip and bodies with loading, error, retry, empty and pending states; supplied labels drive the tabs and add/remove actions; presentation only)
- `frontend/ui/mediaCardForms.js` (shared lists/track form models, membership helpers, initial values and validation)
- `native-proof/app/surfaces/MediaCardSlot.jsx` (native placement with demo library items, action callbacks and popup host on Home, Discover and Library)
- `src/templates/app/components/card_lines.html`
- `src/templates/app/components/media_card.html` (shell: wrapper classes, props script and first-paint poster and title; React replaces it on mount)
- `frontend/ui/MediaCard.jsx`, `frontend/ui/mountMediaCard.jsx`, `frontend/ui/ModalHost.jsx`, `frontend/ui/media-card.css`, `src/app/media_card_model.py`, `src/app/card_surfaces.py` (the whole card is React on every surface: body, status chip, rating, hover buttons, popups host, touch reveal and bulk-select checkbox)
- `src/templates/app/components/media_card_list.html`
- `src/templates/app/components/media_card_status_chip.html` (out-of-band save fragment only; no card renders it)

The existing web `MediaCard.jsx`, `mountMediaCard.jsx` and `ModalHost.jsx` remain the active
browser adapter and popup host; `MediaCardView` and `MediaCardActions` are the native candidates
and do not yet replace that DOM card. `ListsFormView` is used on web through `ListsForm.web.jsx`
and on native through the media-card slot. `TrackForm` and `TrackTabs` render in the native action
host; the native shell's `native-proof/app/surfaces/mediaCardTransport.js` owns the `/api/v1`
transport and CSRF boundary for those forms and is not imported by universal presentation. The web
Track popup, Discover plan, list reorder, the bulk-selection store and the full
interaction/accessibility pass remain outstanding. Runtime render evidence is recorded in the
register.

## RATING

- `frontend/ui/RatingChip.jsx`
- `frontend/ui/RatingStars.jsx`
- `frontend/ui/RatingStarIcon.web.jsx`
- `frontend/ui/RatingStarIcon.native.jsx`
- `frontend/ui/mountRatingChip.jsx`
- `frontend/ui/mountRatingStars.jsx`
- `native-proof/app/surfaces/RatingSlot.jsx` (native placement on the Detail screen)
- `src/templates/app/components/rating_chip.html`
- `src/templates/app/components/rating_stars.html`
- `src/templates/app/components/derived_tv_rating_coverage.html`
- `src/templates/app/components/derived_tv_rating_detail.html`
- `src/templates/app/components/detail_episode_rating_chip.html`
- `src/templates/app/components/detail_row_rating_button.html`
- `src/templates/app/components/detail_score_and_actions.html`
- `src/templates/app/components/detail_score_chip.html`
- `src/templates/app/components/detail_score_chip_slot.html`
- `src/templates/app/components/detail_score_chips.html`
- `src/templates/app/components/media_card_rate_button.html`
- `src/templates/app/components/media_card_rating.html`
- `src/templates/app/components/media_card_rating_oob.html`
- `src/templates/app/components/rating_picker.html`

## LIBRARY

- `src/templates/app/components/_release_year_fetch_js.html`
- `src/templates/app/components/game_grouped_items.html`
- `src/templates/app/components/game_grouped_ungrouped.html`
- `src/templates/app/components/game_grouped_ungrouped_page.html`
- `src/templates/app/components/media_grid_items.html`
- `src/templates/app/components/media_settings_menu.html`
- `src/templates/app/media_list.html`

## ALPHABET

- `frontend/ui/AlphabetBar.jsx`
- `frontend/ui/mountAlphabet.jsx`
- `frontend/ui/alphabet.css`
- `src/templates/app/components/alphabet_filter.html`
- `src/templates/app/components/alphabet_results_empty.html`

## FILTERS

- `frontend/ui/FilterBar.jsx`
- `frontend/ui/mountFilterBar.jsx`
- `native-proof/app/surfaces/FiltersSlot.jsx` (native placement on the Library screen)
- `src/static/js/libraryFilterState.js`
- `src/static/js/savedViews.js`
- `src/templates/app/components/filter_form.html`
- `src/templates/app/components/filter_menu.html`
- `src/templates/app/components/filter_range_panel.html`
- `src/templates/app/components/filter_toolbar.html`
- `src/templates/app/components/filter_toolbar_scripts.html`
- `src/templates/app/components/sidebar_saved_views.html`

## TABLES

- `src/templates/app/components/cells/album_artist_cell.html`
- `src/templates/app/components/cells/album_date_added_cell.html`
- `src/templates/app/components/cells/album_image_cell.html`
- `src/templates/app/components/cells/album_release_date_cell.html`
- `src/templates/app/components/cells/album_score_cell.html`
- `src/templates/app/components/cells/album_status_cell.html`
- `src/templates/app/components/cells/album_title_cell.html`
- `src/templates/app/components/cells/artist_date_added_cell.html`
- `src/templates/app/components/cells/artist_end_date_cell.html`
- `src/templates/app/components/cells/artist_image_cell.html`
- `src/templates/app/components/cells/artist_name_cell.html`
- `src/templates/app/components/cells/artist_release_date_cell.html`
- `src/templates/app/components/cells/artist_score_cell.html`
- `src/templates/app/components/cells/artist_start_date_cell.html`
- `src/templates/app/components/cells/artist_status_cell.html`
- `src/templates/app/components/cells/critic_rating_cell.html`
- `src/templates/app/components/cells/episodes_left_cell.html`
- `src/templates/app/components/cells/last_watched_cell.html`
- `src/templates/app/components/cells/media_author_cell.html`
- `src/templates/app/components/cells/media_date_added_cell.html`
- `src/templates/app/components/cells/media_end_date_cell.html`
- `src/templates/app/components/cells/media_entry_source_cell.html`
- `src/templates/app/components/cells/media_genres_cell.html`
- `src/templates/app/components/cells/media_image_cell.html`
- `src/templates/app/components/cells/media_media_type_cell.html`
- `src/templates/app/components/cells/media_notes_cell.html`
- `src/templates/app/components/cells/media_release_date_cell.html`
- `src/templates/app/components/cells/media_score_cell.html`
- `src/templates/app/components/cells/media_start_date_cell.html`
- `src/templates/app/components/cells/media_status_cell.html`
- `src/templates/app/components/cells/media_synopsis_cell.html`
- `src/templates/app/components/cells/media_tags_cell.html`
- `src/templates/app/components/cells/media_title_cell.html`
- `src/templates/app/components/cells/next_episode_air_date_cell.html`
- `src/templates/app/components/cells/platform_cell.html`
- `src/templates/app/components/cells/popularity_cell.html`
- `src/templates/app/components/cells/progress_cell.html`
- `src/templates/app/components/cells/runtime_cell.html`
- `src/templates/app/components/cells/time_left_cell.html`
- `src/templates/app/components/cells/time_to_beat_cell.html`
- `src/templates/app/components/cells/time_watched_cell.html`
- `src/templates/app/components/cells/user_rating_cell.html`
- `src/templates/app/components/table_column_config_scripts.html`
- `src/templates/app/components/table_column_menu.html`
- `src/templates/app/components/table_items.html`

## BULK

- `src/static/js/bulkSelection.js`
- `src/templates/app/components/bulk_selection_toolbar.html`
- `src/templates/lists/components/bulk_select_button.html`

## SEARCH

- `frontend/ui/GlobalSearch.jsx`
- `frontend/ui/GlobalSearch.web.jsx`
- `frontend/ui/mountGlobalSearch.jsx`
- `frontend/ui/SearchResults.jsx`
- `frontend/ui/SearchResults.web.jsx`
- `frontend/ui/mountSearchResults.jsx`
- `frontend/ui/global-search.css`
- `native-proof/app/surfaces/SearchSlot.jsx` (native placement on Home, Discover, Library and Search)
- `native-proof/app/surfaces/SearchResultsSlot.jsx` (native search results on the Search screen)
- `src/static/js/barcode-scanner.js`
- `src/static/js/barcode-scanner.selfcheck.mjs`
- `src/static/js/libraries/zxing-library-0.21.3.min.js`
- `src/static/js/searchAutocomplete.js`
- `src/static/js/searchShortcut.js`
- `src/templates/app/components/search_local_album_cards.html`
- `src/templates/app/components/search_parent_season.html`
- `src/templates/app/components/search_parent_tv.html`
- `src/templates/app/components/search_suggestions.html`
- `src/templates/app/search.html`

## RAILS

- `frontend/ui/Rail.jsx`
- `frontend/ui/Rail.web.jsx`
- `native-proof/app/surfaces/RailsSlot.jsx` (native placement on the Home and Discover screens)
- `src/static/js/horizontal-scroll.js`
- `src/static/js/horizontal-scroll.selfcheck.mjs`
- `src/templates/app/components/_scrollable_row.html`
- `src/templates/app/components/_scrollable_row_js.html`

## HOME

- `src/templates/app/components/home_artwork_poller.html`
- `src/templates/app/components/home_deferred_groups.html`
- `src/templates/app/components/home_grid.html`
- `src/templates/app/components/home_groups.html`
- `src/templates/app/home.html`

## PLAYBACK

- `src/templates/app/components/active_playback_card.html`
- `src/templates/app/components/detail_checkin_state.html`

## DISCOVER

- `src/templates/app/components/discover_card.html`
- `src/templates/app/components/discover_row.html`
- `src/templates/app/components/discover_row_preview.html`
- `src/templates/app/components/discover_rows.html`
- `src/templates/app/components/discover_tab_content.html`
- `src/templates/app/discover.html`

## DETAIL

Shared React presentation and browser integration:

- `frontend/ui/DetailComposition.jsx`
- `frontend/ui/DetailCompositionTheme.web.jsx`
- `frontend/ui/mountDetailComposition.jsx`
- `native-proof/app/surfaces/DetailSlot.jsx` (native composition on the Detail screen)
- `src/templates/app/components/detail_composition.html`
- `src/users/templatetags/ui_tags.py` (`{% detail_composition %}`)

Server-owned detail composition retained behind the fallback:

- `src/templates/app/components/detail_action_buttons.html`
- `src/templates/app/components/detail_activity_subtitle.html`
- `src/templates/app/components/detail_activity_subtitle_slot.html`
- `src/templates/app/components/detail_mobile_meta.html`
- `src/templates/app/components/detail_notes_section.html`
- `src/templates/app/components/detail_promoted_content.html`
- `src/templates/app/components/detail_secondary_content.html`
- `src/templates/app/components/detail_synopsis.html`
- `src/templates/app/components/detail_title_block.html`
- `src/templates/app/components/detail_watch_providers.html`
- `src/templates/app/components/series_graph_tooltip.html`
- `src/templates/app/components/trakt_series_graph_fragment.html`
- `src/templates/app/components/video_details_extra.html`
- `src/templates/app/media_details.html`

## CHILDREN

- `src/templates/app/comic_issue_details.html`
- `src/templates/app/components/_episode_scroll_restore.html`
- `src/templates/app/components/detail_episode_collection_button.html`
- `src/templates/app/components/detail_episode_hero_track_button.html`
- `src/templates/app/components/detail_episode_history_line.html`
- `src/templates/app/components/detail_episode_track_button.html`
- `src/templates/app/components/detail_row_actions.html`
- `src/templates/app/components/episode_card_rating.html`
- `src/templates/app/components/episode_card_title.html`
- `src/templates/app/components/episode_row.html`
- `src/templates/app/components/issue_row.html`
- `src/templates/app/components/seasons_grid.html`
- `src/templates/app/episode_details.html`

## TRACKING

- `src/static/js/episodeBulkTrackForm.js`
- `src/static/js/mediaStatusDateHandler.js`
- `src/templates/app/components/album_track_modal.html`
- `src/templates/app/components/artist_track_modal.html`
- `src/templates/app/components/detail_track_action.html`
- `src/templates/app/components/detail_track_action_attrs.html`
- `src/templates/app/components/detail_track_open_attrs.html`
- `src/templates/app/components/detail_track_split.html`
- `src/templates/app/components/fill_track.html`
- `src/templates/app/components/fill_track_episode.html`
- `src/templates/app/components/fill_track_episode_bulk.html`
- `src/templates/app/components/fill_track_song.html`
- `src/templates/app/components/media_metadata_panel.html`
- `src/templates/app/components/podcast_show_track_modal.html`
- `src/templates/app/create_entry.html`

## DATE-TIME

Shared React Native field and its browser integration:

- `frontend/ui/DateTimePicker.jsx`
- `frontend/ui/dateTime.js`
- `frontend/ui/mountDateTimePicker.jsx`
- `native-proof/app/surfaces/DateTimeSlot.jsx` (native placement on the Calendar screen)
- `src/templates/app/components/date_time_picker.html`
- `src/templates/app/components/date_time_picker_react.html`
- `src/users/templatetags/ui_tags.py`

Legacy consumers retained until expression-driven suggestions and the activity calendar are ported:

- `src/static/js/calendar.js`
- `src/static/js/dateTimePicker.js`
- `src/templates/app/components/calendar.html`
- `src/templates/app/components/date_time_picker_legacy.html`

## NOTES

- `src/static/js/libraries/marked-12.0.2.min.js`
- `src/static/js/markdown-editor.js`
- `src/templates/app/components/detail_notes_block.html`
- `src/templates/app/components/markdown_notes.html`
- `src/templates/app/components/music_track_notes.html`
- `src/templates/app/components/music_track_notes_button.html`

## PROGRESS

The quick +/- controls are shared React presentation. The detail progress card and
modal shell remain server/Alpine-owned; the season/episode breakdown inside the
modal is shared React presentation on mount, with the server markup as fallback.

- `frontend/ui/ProgressChanger.jsx`
- `frontend/ui/ProgressBar.jsx`
- `frontend/ui/ProgressCard.jsx`
- `frontend/ui/ProgressBreakdown.jsx`
- `frontend/ui/ProgressChangerTheme.web.jsx`
- `frontend/ui/ProgressBreakdownTheme.web.jsx`
- `frontend/ui/mountProgressChanger.jsx`
- `frontend/ui/mountProgressBreakdown.jsx`
- `native-proof/app/surfaces/ProgressSlot.jsx` (native placement on the Detail screen)
- `src/templates/users/components/progress_changer.html`
- `src/templates/app/components/detail_progress_card_slot.html`
- `src/templates/app/components/progress_breakdown.html`
- `src/templates/app/components/progress_changer.html`

## OWNERSHIP

- `src/templates/app/collection_list.html`
- `src/templates/app/components/collection_entry_summary.html`
- `src/templates/app/components/collection_form_fields.html`
- `src/templates/app/components/collection_grid_rows.html`
- `src/templates/app/components/collection_items.html`
- `src/templates/app/components/collection_modal.html`
- `src/templates/app/components/collection_row_grid.html`
- `src/templates/app/components/collection_rows.html`
- `src/templates/app/components/collection_table_rows.html`

## CUSTOM-FIELDS

- `src/static/js/collectionCustomFields.js`
- `src/templates/app/components/collection_custom_field_inputs.html`
- `src/templates/app/components/collection_custom_fields.html`

## ARTWORK

- `src/templates/app/components/cover_change_section.html`
- `src/templates/app/components/edition_picker_result.html`
- `src/templates/app/components/edition_picker_results.html`
- `src/templates/app/components/hardcover_edition_results.html`
- `src/templates/app/components/image_picker.html`
- `src/templates/app/components/image_picker_tiles.html`

## MUSIC

- `src/templates/app/components/album_grid.html`
- `src/templates/app/components/album_list_grid_items.html`
- `src/templates/app/components/artist_discography_container.html`
- `src/templates/app/components/artist_discography_groups.html`
- `src/templates/app/components/artist_grid_items.html`
- `src/templates/app/components/artist_relation_grid.html`
- `src/templates/app/components/artist_relations_container.html`
- `src/templates/app/components/detail_music_album.html`
- `src/templates/app/components/detail_music_album_activity_subtitle.html`
- `src/templates/app/components/detail_music_artist.html`
- `src/templates/app/components/detail_music_track.html`
- `src/templates/app/components/detail_music_track_actions.html`
- `src/templates/app/components/detail_music_track_button.html`
- `src/templates/app/components/detail_music_track_history_line.html`
- `src/templates/app/components/podcast_episode_list.html`
- `src/templates/app/music_album_detail.html`
- `src/templates/app/podcast_show_detail.html`

## PEOPLE

- `src/templates/app/components/cast_card.html`
- `src/templates/app/components/detail_carousel_fragment.html`
- `src/templates/app/components/detail_cast_grid.html`
- `src/templates/app/components/game_lengths_section.html`
- `src/templates/app/components/person_card_inline.html`
- `src/templates/app/components/person_filmography_card.html`
- `src/templates/app/components/person_filmography_fragment.html`
- `src/templates/app/components/person_media_strip_card.html`
- `src/templates/app/components/person_media_strip_row.html`
- `src/templates/app/components/reading_consumption_section.html`
- `src/templates/app/components/youtube_player.html`
- `src/templates/app/components/youtube_watch_section.html`
- `src/templates/app/person_detail.html`
- `src/templates/app/studio_detail.html`

## TAGS

- `src/templates/app/components/detail_tag_preview.html`
- `src/templates/app/components/fill_tags.html`
- `src/templates/app/components/tag_item_button.html`
- `src/templates/app/tag_index.html`
- `src/templates/users/components/media_tag_filter.html`

## METADATA-REVIEW

- `src/static/js/episodeOrderReview.js`
- `src/templates/app/components/library_move_results.html`
- `src/templates/app/components/remap_search_results.html`
- `src/templates/app/episode_ordering.html`
- `src/templates/app/tv_provider_switch.html`

## HISTORY

- `frontend/ui/HistoryFeed.jsx`
- `frontend/ui/mountHistoryFeed.jsx`
- `native-proof/app/screens/HistoryScreen.jsx`
- `src/static/js/sessionHistory.js`
- `src/templates/app/components/fill_history.html`
- `src/templates/app/components/history_card.html`
- `src/templates/app/components/history_day.html`
- `src/templates/app/components/session_history_day.html`
- `src/templates/app/components/session_history_modal.html`
- `src/templates/app/components/session_history_row.html`
- `src/templates/app/history.html`

## STATISTICS

The summary, activity overview, highlights, states and range/media-type controls
are React-owned through `frontend/ui/StatisticsSummary.jsx` on the native
Statistics screen. The web Statistics page remains server/Alpine-owned; memory
for the media-type filter is user data, not a new presentation owner:
`statistics_default_media_types` in `src/users/models.py` and
`update_statistics_media_types` in `src/app/statistics_views.py`, read and written
by `src/static/js/date-range.js`. Chart canvases and the comparison/taste views
stay legacy until a native chart renderer is chosen.

- `frontend/ui/StatisticsSummary.jsx`
- `native-proof/app/screens/StatisticsScreen.jsx`
- `src/static/js/date-range.js`
- `src/static/js/libraries/chartjs-4.4.9.min.js`
- `src/static/js/libraries/chartjs-datalabels-2.0.0.min.js`
- `src/static/js/statistics-charts.js`
- `src/static/js/stats-media-merge.js`
- `src/static/js/stats-media-merge.selfcheck.mjs`
- `src/templates/app/components/featured_repeat_player.html`
- `src/templates/app/components/featured_repeat_player_content.html`
- `src/templates/app/components/featured_repeat_player_footer.html`
- `src/templates/app/components/role_leaders.html`
- `src/templates/app/components/role_leaders_grid.html`
- `src/templates/app/components/statistics/anime_activity_overview.html`
- `src/templates/app/components/statistics/game_activity_overview.html`
- `src/templates/app/components/statistics/highlight_set.html`
- `src/templates/app/components/statistics/movie_activity_overview.html`
- `src/templates/app/components/statistics/music_activity_overview.html`
- `src/templates/app/components/statistics/podcast_activity_overview.html`
- `src/templates/app/components/statistics/talent_section.html`
- `src/templates/app/components/statistics/tv_activity_overview.html`
- `src/templates/app/components/statistics/video_activity_overview.html`
- `src/templates/app/components/studio_footprint.html`
- `src/templates/app/components/studio_footprint_grid.html`
- `src/templates/app/components/taste_signals.html`
- `src/templates/app/components/taste_signals_decades.html`
- `src/templates/app/components/taste_signals_genres.html`
- `src/templates/app/statistics.html`

## RELEASE-CALENDAR

- `frontend/ui/ReleaseCalendar.jsx`
- `frontend/ui/mountReleaseCalendar.jsx`
- `native-proof/app/surfaces/CalendarSlot.jsx`
- `src/templates/events/calendar.html`
- `src/templates/events/components/calendar_grid.html`
- `src/templates/events/components/calendar_list.html`

## LISTS

- `frontend/ui/ListCard.jsx` (list hub card; visibility/smart and member/role metadata stay in the card body, not artwork corner chips)
- `frontend/ui/ListHeader.jsx`
- `frontend/ui/ListResults.jsx`
- `frontend/ui/ListMembership.jsx`
- `native-proof/app/data/listTransportCore.js` (shared list action contract and existing endpoint mapping)
- `native-proof/app/data/listTransport.js` (native list transport; requires an injected request, otherwise local preview)
- `native-proof/app/data/listTransport.web.js` (browser list transport; same-origin session, CSRF header and local fallback)
- `native-proof/app/screens/ListsScreen.jsx`
- `native-proof/app/screens/ListDetailScreen.jsx`
- `src/templates/lists/components/fill_lists.html`
- `src/templates/lists/components/list_cover_image.html`
- `src/templates/lists/components/list_form.html`
- `src/templates/lists/components/list_grid.html`
- `src/templates/lists/components/list_item_button.html`
- `src/templates/lists/components/list_results_summary.html`
- `src/templates/lists/components/list_table.html`
- `src/templates/lists/components/list_table_rows.html`
- `src/templates/lists/components/list_toggle_refresh_handler.html`
- `src/templates/lists/components/list_visibility_chips.html`
- `src/templates/lists/components/media_grid.html`
- `src/templates/lists/components/media_type_breakdown_button.html`
- `src/templates/lists/components/sidebar_pin_action.html`
- `src/templates/lists/custom_lists.html`
- `src/templates/lists/list_activity.html`
- `src/templates/lists/list_detail.html`
- `src/templates/lists/user_profile.html`

## SMART-RULES

- `src/templates/lists/components/smart_rules_builder.html`
- `src/templates/lists/components/smart_rules_summary.html`
- `src/templates/lists/smart_list_detail.html`

## LIST-CURATION

- `src/templates/lists/add_item.html`
- `src/templates/lists/components/add_item_preview_modal.html`
- `src/templates/lists/components/add_item_search_results.html`
- `src/templates/lists/components/recommend_preview_modal.html`
- `src/templates/lists/components/recommend_search_results.html`
- `src/templates/lists/list_recommendations.html`
- `src/templates/lists/recommend_item.html`

## TIERS

- `src/static/js/listTiers.js`
- `src/templates/lists/components/tier_board.html`
- `src/templates/lists/components/tier_tile.html`

## SET-NAV

- `src/templates/users/base.html`
- `src/templates/users/components/_media_type_order_js.html`
- `src/templates/users/components/media_type_picker.html`
- `src/templates/users/sidebar.html`

## SET-PREFERENCES

- `frontend/ui/PreferencesForm.jsx`
- `frontend/ui/SelectField.jsx`
- `frontend/ui/ToggleChip.jsx`
- `frontend/ui/FormSaveBar.jsx`
- `native-proof/app/surfaces/PreferencesSlot.jsx`
- `src/templates/users/preferences.html`
- `src/templates/users/components/form_save_bar.html`

## SET-APPEARANCE

- `src/templates/users/appearance.html`

## SET-CARDS

- `src/templates/users/cards.html`
- `src/templates/users/cards_preview.html`

## SET-HOME

- `src/templates/users/home_screen.html`

## SET-PROVIDERS

- `frontend/providers/AccountConnection.jsx`
- `frontend/providers/Activity.jsx`
- `frontend/providers/Connection.jsx`
- `frontend/providers/Directory.jsx`
- `frontend/providers/Import.jsx`
- `frontend/providers/ImportPreferences.jsx`
- `frontend/providers/Metadata.jsx`
- `frontend/providers/ProviderPage.jsx`
- `frontend/providers/mount.jsx`
- `frontend/providers/provider-page.css`
- `frontend/providers/web.jsx`
- `src/templates/users/providers/overview_fallback.html`
- `src/templates/users/providers/header_fallback.html`
- `src/templates/users/providers/content_legacy.html`
- `src/templates/users/providers/provider_legacy.html`

- `src/templates/users/components/account_connection.html`
- `src/templates/users/components/account_import_action.html`
- `src/templates/users/components/provider_card.html`
- `src/templates/users/components/provider_filter_dropdown.html`
- `src/templates/users/components/provider_results.html`
- `src/templates/users/components/provider_row.html`
- `src/templates/users/components/provider_status_badge.html`
- `src/templates/users/provider_detail.html`
- `src/templates/users/providers.html`

## SET-METADATA

- `src/templates/users/components/media_type_provider_modal.html`
- `src/templates/users/components/metadata_admin_notice.html`
- `src/templates/users/components/metadata_library_repair.html`
- `src/templates/users/components/metadata_source_card.html`
- `src/templates/users/components/provider_connection.html`
- `src/templates/users/components/provider_credential_modal.html`
- `src/templates/users/components/provider_credential_row.html`
- `src/templates/users/components/provider_credential_status.html`
- `src/templates/users/components/provider_default_shortcuts.html`
- `src/templates/users/components/provider_instance_credentials.html`
- `src/templates/users/components/provider_metadata.html`
- `src/templates/users/components/provider_personal_credentials.html`
- `src/templates/users/metadata.html`

## SET-IMPORT

- `frontend/providers/FileImport.jsx`
- `frontend/providers/Credentials.jsx`
- `frontend/providers/SetupGuide.jsx`
- `frontend/providers/SettingsForm.jsx`
- `src/users/provider_guides.py`
- `src/users/provider_forms.py`
- `src/templates/users/providers/setup_guide.html`
- `src/templates/users/providers/setup_guide_parts.html`
- `src/templates/users/components/file_import_fallback.html`
- `src/templates/users/components/clz_import_fallback.html`
- `src/templates/users/_reading_server_card.html`
- `src/templates/users/_reading_server_modal.html`
- `src/templates/users/components/game_sync_fields.html`
- `src/templates/users/components/import_schedule_fields.html`
- `src/templates/users/components/import_upload_badge.html`
- `src/templates/users/components/plex_library_selector.html`
- `src/templates/users/components/provider_import.html`
- `src/templates/users/import_data.html`

## SET-ACTIVITY

- `src/templates/users/components/import_activity.html`
- `src/templates/users/components/import_activity_loader.html`
- `src/templates/users/components/import_source_cleanup.html`
- `src/templates/users/components/outbound_service_activity.html`
- `src/templates/users/provider_activity.html`
- `src/templates/users/providers/integration_activity.html`

## SET-SYNC

- `src/templates/users/components/media_server_scrobbles.html`
- `src/templates/users/components/outbound_service_modal.html`
- `src/templates/users/components/outbound_service_status.html`
- `src/templates/users/components/outbound_services.html`
- `src/templates/users/components/stremio_catalog_status.html`
- `src/templates/users/components/sync_state_section.html`
- `src/templates/users/components/tmdb_proxy.html`
- `src/templates/users/components/tmdb_rating_sync.html`
- `src/templates/users/components/wetrakr_sync.html`
- `src/templates/users/integrations.html`
- `src/templates/users/mal_export.html`
- `src/templates/users/providers/integration_content.html`
- `src/templates/users/providers/integrations/emby.html`
- `src/templates/users/providers/integrations/jellyfin.html`
- `src/templates/users/providers/integrations/kodi.html`
- `src/templates/users/providers/integrations/navidrome.html`
- `src/templates/users/providers/integrations/nuvio.html`
- `src/templates/users/providers/integrations/plex.html`
- `src/templates/users/providers/integrations/seerr.html`
- `src/templates/users/providers/integrations/stremio.html`
- `src/templates/users/providers/mal_connection.html`
- `src/templates/users/providers/mal_sync.html`
- `src/templates/users/providers/outbound_sync.html`

## SET-DATA

- `src/templates/users/components/export_controls.html` (backup status region mounts `frontend/settings/BackupStatus.jsx`; fallback kept)
- `src/templates/users/components/library_danger_zone.html`
- `src/templates/users/data_management.html`
- `src/templates/users/export_data.html`
- `src/templates/users/rss.html`

## SET-ACCESS

- `src/templates/integrations/oauth_applications.html`
- `src/templates/integrations/oauth_device.html`
- `src/templates/users/access_tokens.html`
- `src/templates/users/components/catalog_grants.html`
- `src/templates/users/components/integration_tokens.html`
- `src/templates/users/providers/access_tokens.html`

## AUTH

- `src/templates/account/login.html`
- `src/templates/account/messages/logged_in.txt`
- `src/templates/account/messages/logged_out.txt`
- `src/templates/account/signup.html`
- `src/templates/allauth/elements/button.html`
- `src/templates/allauth/elements/button_group.html`
- `src/templates/allauth/elements/field.html`
- `src/templates/allauth/elements/fields.html`
- `src/templates/allauth/elements/form.html`
- `src/templates/allauth/elements/h1.html`
- `src/templates/allauth/elements/h2.html`
- `src/templates/allauth/elements/hr.html`
- `src/templates/allauth/elements/p.html`
- `src/templates/allauth/elements/provider.html`
- `src/templates/allauth/elements/provider_list.html`
- `src/templates/allauth/layouts/base.html`
- `src/templates/allauth/layouts/entrance.html`
- `src/templates/allauth/layouts/manage.html`
- `src/templates/socialaccount/connections.html`
- `src/templates/socialaccount/signup.html`
- `src/templates/socialaccount/snippets/login.html`
- `src/templates/socialaccount/snippets/provider_list.html`
- `src/templates/users/account.html`
- `src/templates/users/password_recover.html`

## SET-NOTIFICATIONS

- `src/templates/users/components/excluded_items.html`
- `src/templates/users/components/search_results.html`
- `src/templates/users/notifications.html`

## ONBOARDING

- `src/templates/users/components/onboarding_banner.html`
- `src/templates/users/onboarding/_layout.html`
- `src/templates/users/onboarding/components/connect_form.html`
- `src/templates/users/onboarding/components/connect_oauth.html`
- `src/templates/users/onboarding/components/connect_trakt.html`
- `src/templates/users/onboarding/components/connect_upload.html`
- `src/templates/users/onboarding/components/integration_plex.html`
- `src/templates/users/onboarding/import_status.html`
- `src/templates/users/onboarding/integration_setup.html`
- `src/templates/users/onboarding/media_types.html`
- `src/templates/users/onboarding/metadata.html`
- `src/templates/users/onboarding/service_setup.html`
- `src/templates/users/onboarding/services.html`
- `src/templates/users/onboarding/services_summary.html`

## SET-SYSTEM

- `src/templates/users/about.html`
- `src/templates/users/advanced.html`
- `src/templates/users/components/server_port.html`
- `src/templates/users/components/update_banner.html`
- `src/templates/users/components/whats_new.html`

## MATCH-REVIEW

- `src/static/js/matchFixReview.js`
- `src/templates/integrations/match_fix.html`

## INTEGRATION-PANELS

- `src/templates/integrations/library_panel.html`
- `src/templates/integrations/seerr_request.html`
- `src/templates/integrations/seerr_status.html`

## DEVICE-CONNECT

- `src/templates/integrations/trakt_device_code.html`

## STREMIO

- `src/templates/integrations/stremio_configure.html`
- `src/templates/app/components/session_history_row.html` (audiobook "stopped at" and book "at page" fragments)
- `src/templates/app/components/reading_consumption_section.html` (Books "Listening Time" card)

## BULK_ACTIONS

- `frontend/ui/BulkActions.jsx` (universal `BulkToolbar`, `BulkActionDialog`, `BulkOptionRow`)
- `frontend/ui/mountBulkActions.jsx` (web job dialog and dock, legacy)
- `frontend/ui/mountBulkToolbar.jsx` (web toolbar, legacy)
- `native-proof/app/surfaces/BulkSlot.jsx` (native Library selection, cards, toolbar and dialogs)
- `src/templates/base.html` (dock mount)
- `src/app/bulk_action_views.py`
- `src/app/services/bulk_show_plays.py`
