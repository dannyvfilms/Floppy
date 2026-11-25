"""Writes to tracking rows that skip model signals, and how each is announced.

A single ``save()`` or ``delete()`` of a tracked row fires the model signals
that clear the library view caches, mark Statistics days and refresh History.
``QuerySet.update``, ``bulk_create``, ``bulk_update``, raw SQL and blocks inside
``suppress_media_change_side_effects()`` skip them. Every such site is listed
here with what it changes and how each reader learns about it:

* ``view_caches``: the media list, Home rows and the TV time-left order
  (``cache_utils.clear_library_view_caches``, docs/architecture/view-caches.md).
* ``statistics``: dirty days or the aggregate (``statistics_sync``,
  docs/architecture/statistics-sync.md).
* ``history``: the History day payloads and index (``history_cache``,
  docs/architecture/history-memory.md).
* ``watch_state``: the canonical watched-state projection
  (``app.services.watch_state``).

"Not needed, because ..." is an allowed answer and must say why.

``app.tests.test_bulk_write_refresh`` scans the tree (``app.tests.bulk_write_scan``)
and fails when a write is missing here or a row no longer matches a write. Keys
are (module, function, model); ``?`` is a queryset whose model the scan cannot
name, and ``<suppress_media_change_side_effects>`` is a suppressed block.

Out of scope: rows that are not tracking (lists, Home rows and their items,
credits, catalogue items). The bulk item creation in ``users/home_screen.py``
writes Home items, not trackers.
"""

from __future__ import annotations

from dataclasses import dataclass

READERS = ("view_caches", "statistics", "history", "watch_state")


@dataclass(frozen=True)
class Refresh:
    """What a write changes and how each reader learns about it."""

    changes: str
    view_caches: str
    statistics: str
    history: str
    watch_state: str


# -- shared answers ------------------------------------------------------------

_WS_SCOPED = (
    "The tracker managers are ImportScopedQuerySet, which runs the write inside "
    "sync_lock.tracking_mutation: touched items are re-projected, or the "
    "watch-state repair is re-armed when the user has no sync feed."
)
_WS_REPROJECTED = (
    "Re-projected explicitly with project_watch_state for every touched item."
)
_NO_HISTORY_STATUS = (
    "Not needed: a show or season status is not a History entry; the plays "
    "History lists are unchanged."
)

INSIDE_SHOW_SAVE = Refresh(
    changes="A show's or season's status (and its seasons or episodes) while "
    "a TV, Season or Episode row is being saved.",
    view_caches="The save that runs it ends in clear_library_view_caches "
    "(TV.save, Season.save) or fires its own post_save signal, which clears "
    "for the user (Episode.save).",
    statistics="The surrounding save's signal marks the user's change; a "
    "status is an aggregate, and any mark makes every range re-read it.",
    history=_NO_HISTORY_STATUS,
    watch_state=_WS_SCOPED,
)

FAN_OUT_EPISODES = Refresh(
    changes="Episodes (and seasons) created when a show or season is marked Completed.",
    view_caches="The TV.save or Season.save that runs it ends in "
    "clear_library_view_caches.",
    statistics="statistics_sync.mark_rows on the created episodes.",
    history="signals.invalidate_bulk_episode_history on the created episodes, "
    "after commit.",
    watch_state=_WS_SCOPED,
)

SEASON_STATUS_HELPER = Refresh(
    changes="One season's status or rewatch start (and possibly its show's "
    "status), from a view, Home or another save.",
    view_caches="tv._announce_status_write runs signals._handle_media_cache_change "
    "(the refresh a save runs), which calls clear_library_view_caches.",
    statistics="The same call marks the aggregate (status reaches every range).",
    history=_NO_HISTORY_STATUS,
    watch_state=_WS_SCOPED,
)

IMPORTER = Refresh(
    changes="Tracking rows written by an importer running in the import task.",
    view_caches="The import task clears them once for the user when the run "
    "imported anything (integrations/tasks/_media_imports.py).",
    statistics="The import task publishes: helpers.publish_bulk_rows for the "
    "rows noted with note_bulk_rows (DAY_SCOPED_IMPORTERS), otherwise "
    "publish_everything; the durable Trakt path marks each chunk and "
    "publishes in durable.publish_pending.",
    history="Same publish step as Statistics (publish_bulk_rows or "
    "publish_everything).",
    watch_state=_WS_SCOPED + " The import also projects in bulk "
    "(project_imported_watch_state).",
)

FLUSHED = Refresh(
    changes="Plays logged in bulk inside suppress_media_change_side_effects().",
    view_caches="flush_media_change_side_effects after the block clears them "
    "(through _handle_media_cache_change).",
    statistics="flush_media_change_side_effects marks the affected days.",
    history="flush_media_change_side_effects invalidates the affected days.",
    watch_state=_WS_SCOPED,
)

MIGRATION = Refresh(
    changes="A show moved between libraries or providers (seasons, episodes "
    "and the tracker rehomed), all inside one suppressed block.",
    view_caches="On commit, _reconcile_caches / _reconcile_committed_migration "
    "call clear_library_view_caches.",
    statistics="On commit, signals._invalidate_episode_history_changes marks "
    "the episode days.",
    history="On commit, signals._invalidate_episode_history_changes "
    "invalidates the episode days.",
    watch_state=_WS_SCOPED,
)

CATALOGUE_RELINK = Refresh(
    changes="Points a user's rows at a merged or deduplicated catalogue record "
    "(album, artist, podcast episode, season). Dates, status and score do not "
    "change.",
    view_caches="Not cleared: the entries show the same title and expire "
    "within their cache lifetime (view-caches.md); the Statistics doc treats "
    "catalogue duplicate mappings the same way.",
    statistics="Not needed: nothing Statistics counts changes. Music track "
    "relinks that do move counts mark explicitly (enrich_music_library_task).",
    history="Not needed: the same days and titles.",
    watch_state=_WS_SCOPED,
)

SUPPRESS_NO_TRACKING = Refresh(
    changes="A suppressed block around credit rows or the watch-state backfill; "
    "it writes no tracking rows.",
    view_caches="Not needed: no tracked row changes.",
    statistics="Not needed for tracking. Credit changes reach person "
    "statistics through request_credits_statistics_refresh.",
    history="Not needed: no tracked row changes.",
    watch_state="Not needed, or the block is the projection itself "
    "(backfill_user_watch_state).",
)


def _not_tracking(what):
    reason = f"Not needed: writes {what}, not tracking rows."
    return Refresh(
        changes=what,
        view_caches=reason,
        statistics=reason,
        history=reason,
        watch_state=reason,
    )


IMPORT_MECHANISM = Refresh(
    changes="ImportScopedQuerySet itself: the manager every tracker uses for "
    "update, bulk_create and bulk_update.",
    view_caches="Not here: the caller announces (this table lists each caller).",
    statistics="Not here: the caller announces.",
    history="Not here: the caller announces.",
    watch_state="sync_lock.tracking_mutation, for every caller.",
)

SEASON = "Season"
TV = "TV"
EPISODE = "Episode"
SUPPRESS = "<suppress_media_change_side_effects>"
UNKNOWN = "?"

BULK_WRITE_SITES = {
    # --- Check-in ---------------------------------------------------------
    ("app/checkin.py", "_restore_parents", SEASON): Refresh(
        changes="Puts back the season and show status a cancelled check-in changed.",
        view_caches="clear_library_view_caches right after the updates.",
        statistics="The check-in's own episode delete fires the Episode "
        "signal, which marks its day.",
        history="Same Episode delete signal invalidates its day.",
        watch_state=_WS_SCOPED,
    ),
    ("app/checkin.py", "_restore_parents", TV): None,  # same row as Season
    # --- Credits and other non-tracking writes ------------------------------
    ("app/credits.py", "_bulk_upsert", UNKNOWN): _not_tracking("people and studios"),
    ("app/credits.py", "_replace_person_credits", SUPPRESS): SUPPRESS_NO_TRACKING,
    ("app/services/imdb_game_credits.py", "backfill_missing_game_studios", SUPPRESS): (
        SUPPRESS_NO_TRACKING
    ),
    ("app/services/imdb_game_credits.py", "sync_game_credits_from_imdb", SUPPRESS): (
        SUPPRESS_NO_TRACKING
    ),
    ("app/tasks_credits.py", "_populate_credits_for_items", SUPPRESS): (
        SUPPRESS_NO_TRACKING
    ),
    ("app/tasks_watch_state.py", "backfill_user_watch_state", SUPPRESS): (
        SUPPRESS_NO_TRACKING
    ),
    ("app/signals.py", "deleting_account", SUPPRESS): Refresh(
        changes="Every row of a user who is being deleted.",
        view_caches="Not needed: the user and their caches' readers are gone.",
        statistics="Not needed: the user's Statistics rows are deleted with them.",
        history="Not needed: the user is deleted.",
        watch_state="Not needed: the user's projection rows cascade.",
    ),
    ("events/notifications.py", "record_failed_alerts", UNKNOWN): _not_tracking(
        "failed alert deliveries"
    ),
    ("integrations/mal_sync.py", "reconcile_stale_full_sync", UNKNOWN): _not_tracking(
        "a MyAnimeList account's sync status"
    ),
    ("integrations/mal_sync_views.py", "mal_full_sync", UNKNOWN): _not_tracking(
        "a MyAnimeList account's sync status"
    ),
    ("integrations/mal_sync_views.py", "mal_full_sync_retry_failed", UNKNOWN): _not_tracking(
        "a MyAnimeList account's sync status"
    ),
    ("integrations/oauth_models.py", "OAuthClient.revoke", UNKNOWN): _not_tracking(
        "OAuth refresh tokens"
    ),
    ("integrations/stremio_catalog.py", "touch_grant", UNKNOWN): _not_tracking(
        "a Stremio grant's last use"
    ),
    ("integrations/tmdb_views.py", "_stop_bindings", UNKNOWN): _not_tracking(
        "outbound sync deliveries"
    ),
    ("integrations/state/destinations.py", "PushDestination.stop_bindings", UNKNOWN): _not_tracking(
        "outbound sync deliveries"
    ),
    ("integrations/state/destinations.py", "PushDestination._clear_device_flow", UNKNOWN): _not_tracking(
        "a destination account's login state"
    ),
    ("integrations/state/destinations.py", "PushDestination._finish_connection", UNKNOWN): _not_tracking(
        "a destination account's login state"
    ),
    ("integrations/state/destinations.py", "PushDestination.poll", UNKNOWN): _not_tracking(
        "a destination account's login state"
    ),
    ("app/models/item.py", "ItemQuerySet.bulk_create", UNKNOWN): _not_tracking(
        "items (it only fills each item's library bucket, then defers)"
    ),
    ("app/models/item.py", "ItemQuerySet.bulk_update", UNKNOWN): _not_tracking(
        "items (it only fills each item's library bucket, then defers)"
    ),
    ("lists/models.py", "CustomListItemManager.bulk_create", UNKNOWN): _not_tracking(
        "list items (list views read them live)"
    ),
    ("integrations/imports/durable.py", "delete_overwrite", UNKNOWN): _not_tracking(
        "import run bookkeeping"
    ),
    ("integrations/imports/durable.py", "persist", UNKNOWN): _not_tracking(
        "import run bookkeeping"
    ),
    ("integrations/imports/durable.py", "publish_pending", UNKNOWN): _not_tracking(
        "import run bookkeeping (this function is the Trakt publish step)"
    ),
    ("integrations/imports/helpers.py", "bulk_resolve_items", UNKNOWN): _not_tracking(
        "catalogue items"
    ),
    # --- Podcasts ---------------------------------------------------------
    (
        "app/fork_services_podcast.py",
        "mark_all_episodes_played",
        "PodcastPlay",
    ): Refresh(
        changes="One play per episode marked played, beside the Podcast rows it saves.",
        view_caches="Each Podcast row is saved with save()/create(); its signal "
        "clears for the user.",
        statistics="The same Podcast saves mark the play days (the plays carry "
        "the same end dates).",
        history="The same Podcast saves invalidate those days.",
        watch_state="Not needed: plays have no watch-state row; the Podcast "
        "saves project the episode.",
    ),
    (
        "app/services/podcast_plays.py",
        "create_plays_for_trackers",
        "PodcastPlay",
    ): Refresh(
        changes="The plays for Podcast trackers an importer wrote in bulk.",
        view_caches=IMPORTER.view_caches,
        statistics="bulk_create_media notes the trackers (same dates) with "
        "note_bulk_rows; the import task publishes them.",
        history=IMPORTER.history,
        watch_state="Not needed: plays have no watch-state row.",
    ),
    ("app/podcast_views.py", "podcast_show_save", "Podcast"): Refresh(
        changes="Every listen's status when the show tracker's status changes.",
        view_caches="clear_library_view_caches right after the update.",
        statistics="The show tracker's own save() marks the user's change; "
        "status is an aggregate every range re-reads.",
        history=_NO_HISTORY_STATUS,
        watch_state=_WS_SCOPED,
    ),
    (
        "app/services/bulk_episode_tracking.py",
        "_apply_bulk_podcast_plays",
        SUPPRESS,
    ): FLUSHED,
    (
        "app/services/bulk_episode_tracking.py",
        "_apply_bulk_podcast_plays",
        "Podcast",
    ): FLUSHED,
    # --- Episodes, shows, seasons -------------------------------------------
    (
        "app/services/bulk_episode_tracking.py",
        "apply_bulk_episode_plays",
        SUPPRESS,
    ): FLUSHED,
    (
        "app/services/bulk_episode_tracking.py",
        "apply_bulk_episode_plays",
        EPISODE,
    ): FLUSHED,
    (
        "app/services/bulk_music_tracking.py",
        "apply_bulk_music_plays",
        SUPPRESS,
    ): FLUSHED,
    ("app/services/completion.py", "normalize_completed_entry", UNKNOWN): Refresh(
        changes="Merges a planning row's fields into a completed row written in "
        "bulk (bulk episode and podcast saves, imports).",
        view_caches="The bulk write that calls it announces (FLUSHED or IMPORTER "
        "rows here).",
        statistics="The calling bulk write marks the row's days.",
        history="The calling bulk write invalidates the row's days.",
        watch_state=_WS_SCOPED,
    ),
    ("app/models/tv.py", "Episode.save", SEASON): INSIDE_SHOW_SAVE,
    ("app/models/tv.py", "Episode.save", TV): INSIDE_SHOW_SAVE,
    ("app/models/tv.py", "Season._sync_status_after_episode_change", SEASON): Refresh(
        changes="A season's and show's status after its episodes changed.",
        view_caches="Every caller clears afterwards: Season.save, the save and "
        "history views, fork_services_history, and the bulk episode flush.",
        statistics="Every caller's episode write marks its days.",
        history=_NO_HISTORY_STATUS,
        watch_state=_WS_SCOPED,
    ),
    ("app/models/tv.py", "Season._sync_status_after_episode_change", TV): None,
    (
        "app/models/tv.py",
        "Season.finish_rewatch_if_complete",
        SEASON,
    ): SEASON_STATUS_HELPER,
    ("app/models/tv.py", "Season.promote_to_completed_if_fully_watched", SEASON): (
        SEASON_STATUS_HELPER
    ),
    ("app/models/tv.py", "Season.start_rewatch", SEASON): SEASON_STATUS_HELPER,
    ("app/models/tv.py", "Season.stop_rewatch", SEASON): SEASON_STATUS_HELPER,
    ("app/models/tv.py", "Season.save", EPISODE): FAN_OUT_EPISODES,
    ("app/models/tv.py", "Season.save", SEASON): INSIDE_SHOW_SAVE,
    ("app/models/tv.py", "Season.save", TV): INSIDE_SHOW_SAVE,
    ("app/models/tv.py", "TV._completed", EPISODE): FAN_OUT_EPISODES,
    ("app/models/tv.py", "TV._completed", SEASON): FAN_OUT_EPISODES,
    ("app/models/tv.py", "TV._handle_completed_season_inner", TV): Refresh(
        changes="A show's status once its last season completes.",
        view_caches="Its callers announce: Season.save clears, and the season "
        "helpers call tv._announce_status_write.",
        statistics="Same callers mark the change.",
        history=_NO_HISTORY_STATUS,
        watch_state=_WS_SCOPED,
    ),
    ("app/models/tv.py", "TV._mark_in_progress_seasons_as_dropped", SEASON): Refresh(
        changes="Drops a show's in-progress seasons when the show is dropped.",
        view_caches="Run by TV.save, which ends in clear_library_view_caches; "
        "the Trakt importer's call is covered by the import task (IMPORTER).",
        statistics=INSIDE_SHOW_SAVE.statistics,
        history=_NO_HISTORY_STATUS,
        watch_state=_WS_SCOPED,
    ),
    ("app/models/tv.py", "TV._pause_in_progress_seasons", SEASON): Refresh(
        changes="Pauses a show's in-progress seasons when the show goes from "
        "in progress to paused.",
        view_caches=INSIDE_SHOW_SAVE.view_caches,
        statistics=INSIDE_SHOW_SAVE.statistics,
        history=_NO_HISTORY_STATUS,
        watch_state=_WS_SCOPED,
    ),
    ("app/models/tv.py", "TV._start_next_available_season", SEASON): INSIDE_SHOW_SAVE,
    ("app/models/tv.py", "TV._start_next_available_season", TV): INSIDE_SHOW_SAVE,
    ("app/models/tv.py", "TV.start_rewatch", SEASON): SEASON_STATUS_HELPER,
    ("app/models/tv.py", "TV.start_rewatch", TV): SEASON_STATUS_HELPER,
    ("app/models/tv.py", "TV.stop_rewatch", TV): SEASON_STATUS_HELPER,
    ("app/services/episode_ordering.py", "apply_change", EPISODE): Refresh(
        changes="Remaps a show's plays onto another episode order (plays move "
        "between episodes and seasons, the show's active order changes).",
        view_caches="_announce_order_change runs signals._handle_media_cache_change, "
        "which calls clear_library_view_caches.",
        statistics="_announce_order_change: marks the days before and after the remap.",
        history="_announce_order_change: invalidates the same days (episode "
        "numbers and titles shown there change).",
        watch_state=_WS_REPROJECTED,
    ),
    ("app/services/episode_ordering.py", "apply_change", SEASON): None,
    ("app/services/episode_ordering.py", "apply_change", TV): None,
    ("app/services/episode_ordering.py", "revert_change", EPISODE): None,
    ("app/services/episode_ordering.py", "revert_change", SEASON): None,
    ("app/services/episode_ordering.py", "revert_change", TV): None,
    ("app/services/episode_scores.py", "set_episode_score", UNKNOWN): Refresh(
        changes="The score on an episode's plays (web, API and media-server "
        "rating webhooks).",
        view_caches="Not needed: library and Home cards show the show's or "
        "season's score, not an episode's.",
        statistics="Not needed: Statistics reads tracker scores; day payloads "
        "do not read episode scores.",
        history="invalidate_history_days for the plays' days.",
        watch_state="Not needed: a score is not watched state.",
    ),
    ("app/services/episode_scores.py", "rate_episode", UNKNOWN): Refresh(
        changes="The score on rating-only episode rows (not watches).",
        view_caches="Not needed: as set_episode_score.",
        statistics="Not needed: rating-only rows are not plays.",
        history="Not needed: rating-only rows are not History entries; the "
        "played rows go through set_episode_score.",
        watch_state="Not needed: rating-only rows are not watches.",
    ),
    ("app/services/tracker_fold.py", "fold_tracker_into", UNKNOWN): Refresh(
        changes="Folds a duplicate tracker's score, notes and status into the "
        "one kept when two catalogue records merge (item, album, artist).",
        view_caches="Every caller deletes the duplicate row right after the "
        "fold; that delete's signal clears for the same user.",
        statistics="The same delete signal marks the user's change, and every "
        "range re-reads status and score.",
        history="The same delete signal invalidates the duplicate's days; the "
        "kept row's plays and dates do not move.",
        watch_state=_WS_SCOPED,
    ),
    ("app/services/item_merge.py", "_absorb_season_rows", EPISODE): CATALOGUE_RELINK,
    ("app/services/item_merge.py", "_rehome_season", EPISODE): CATALOGUE_RELINK,
    # --- Migrations ---------------------------------------------------------
    (
        "app/services/anime_migration.py",
        "_create_migration_episodes",
        EPISODE,
    ): MIGRATION,
    ("app/services/anime_migration.py", "_persist_preflight_once", SUPPRESS): MIGRATION,
    ("app/services/anime_migration.py", "_persist_preflight_once", "Anime"): MIGRATION,
    ("app/services/anime_migration.py", "_persist_preflight_once", SEASON): MIGRATION,
    ("app/services/anime_migration.py", "_persist_preflight_once", TV): MIGRATION,
    ("app/services/anime_migration.py", "_season_tracker", SEASON): MIGRATION,
    ("app/services/library_migration.py", "_move_grouped", EPISODE): MIGRATION,
    ("app/services/library_migration.py", "migrate_library_item", SUPPRESS): MIGRATION,
    ("app/services/library_migration.py", "switch_tv_provider", SUPPRESS): MIGRATION,
    ("integrations/match_corrections.py", "_move_tv", EPISODE): MIGRATION,
    ("integrations/match_corrections.py", "_move_tv", SEASON): MIGRATION,
    ("integrations/match_corrections.py", "_move_tv", TV): MIGRATION,
    ("integrations/match_corrections.py", "_move_movie", "Movie"): Refresh(
        changes="Moves one user's film (and its plays) to the corrected title.",
        view_caches="_announce_movie_move runs signals._handle_media_cache_change "
        "after the move, which calls clear_library_view_caches.",
        statistics="The same call marks the film's and its plays' days.",
        history="The same call invalidates those days.",
        watch_state=_WS_SCOPED,
    ),
    ("integrations/match_corrections.py", "_move_movie", UNKNOWN): None,
    ("integrations/match_corrections.py", "_merge_scalars", UNKNOWN): Refresh(
        changes="Copies empty fields onto the kept film or show during a match "
        "correction.",
        view_caches="The correction announces once: MIGRATION (shows) or "
        "_announce_movie_move (films).",
        statistics="Same announcement.",
        history="Same announcement.",
        watch_state=_WS_SCOPED,
    ),
    ("integrations/match_corrections.py", "_move_unique_state", UNKNOWN): Refresh(
        changes="Moves playback progress and the watch-state row to the "
        "corrected title.",
        view_caches="Covered by the correction's announcement (see _move_tv, "
        "_move_movie).",
        statistics="Not needed: playback progress and watch state are not counted.",
        history="Not needed: not History entries.",
        watch_state="This is the watch-state row; apply_match_correction runs "
        "inside state_transaction and invalidates the user's sync contexts.",
    ),
    # --- Music --------------------------------------------------------------
    ("app/services/music.py", "merge_album_records", "Music"): CATALOGUE_RELINK,
    ("app/services/music.py", "merge_artist_records", "Music"): CATALOGUE_RELINK,
    (
        "app/services/music.py",
        "merge_artist_records._merge_album_into_target",
        "Music",
    ): (CATALOGUE_RELINK),
    ("app/services/music.py", "sync_album_metadata", "Music"): CATALOGUE_RELINK,
    ("app/services/music_scrobble.py", "_dedupe_albums", "Music"): CATALOGUE_RELINK,
    ("app/tasks_music.py", "enrich_albums_task", "Music"): CATALOGUE_RELINK,
    ("app/tasks_music.py", "enrich_music_library_task", "Music"): Refresh(
        changes="Relinks tracks to their album, artist and track records.",
        view_caches=CATALOGUE_RELINK.view_caches,
        statistics="statistics_sync.mark_rows on the relinked tracks.",
        history=CATALOGUE_RELINK.history,
        watch_state=_WS_SCOPED,
    ),
    (
        "integrations/imports/pocketcasts.py",
        "_cleanup_duplicate_episodes_global",
        "Podcast",
    ): (CATALOGUE_RELINK),
    # --- Background status changes -------------------------------------------
    ("app/services/auto_pause.py", "_pause_stale_media_for_type", UNKNOWN): Refresh(
        changes="Pauses a user's items that had no activity for their chosen "
        "number of weeks (daily task).",
        view_caches="signals._handle_media_cache_change after the update (the "
        "refresh a save runs), which calls clear_library_view_caches.",
        statistics="The same call marks the aggregate.",
        history=_NO_HISTORY_STATUS,
        watch_state=_WS_SCOPED,
    ),
    ("events/calendar/tv.py", "reopen_completed_tv_with_new_seasons", SEASON): Refresh(
        changes="Reopens a completed show when a new season is announced, and "
        "adds that season as Planning (calendar task).",
        view_caches="signals._handle_media_cache_change for each reopened show's "
        "user, which calls clear_library_view_caches.",
        statistics="The same call marks the aggregate.",
        history=_NO_HISTORY_STATUS,
        watch_state=_WS_SCOPED,
    ),
    ("events/calendar/tv.py", "reopen_completed_tv_with_new_seasons", TV): None,
    # --- Importers (one pattern: the import task announces) -------------------
    ("integrations/import_scope.py", "ImportScopedQuerySet.bulk_create", UNKNOWN): (
        IMPORT_MECHANISM
    ),
    ("integrations/import_scope.py", "ImportScopedQuerySet.bulk_update", UNKNOWN): (
        IMPORT_MECHANISM
    ),
    ("integrations/imports/durable.py", "persist.commit", UNKNOWN): IMPORTER,
    (
        "integrations/imports/helpers.py",
        "_backfill_completed_season_episodes",
        EPISODE,
    ): IMPORTER,
    (
        "integrations/imports/helpers.py",
        "bulk_create_media.create_media",
        UNKNOWN,
    ): IMPORTER,
    (
        "integrations/imports/helpers.py",
        "bulk_update_media.update",
        UNKNOWN,
    ): IMPORTER,
    (
        "integrations/imports/mdblist.py",
        "MDBListImporter._process_episode_rating",
        EPISODE,
    ): (IMPORTER),
    (
        "integrations/imports/mdblist.py",
        "MDBListImporter.import_data",
        SEASON,
    ): IMPORTER,
    ("integrations/imports/mdblist.py", "MDBListImporter.import_data", TV): IMPORTER,
    (
        "integrations/imports/pocketcasts.py",
        "PocketCastsImporter._sync_catalog_episode",
        "Podcast",
    ): (IMPORTER),
    ("integrations/imports/steam.py", "SteamImporter.import_data", "Game"): IMPORTER,
    (
        "integrations/imports/stremio.py",
        "StremioImporter._process_seasons_and_episodes",
        SEASON,
    ): (IMPORTER),
    (
        "integrations/imports/trakt.py",
        "TraktImporter._process_episode_attribute",
        EPISODE,
    ): (IMPORTER),
    ("integrations/imports/trakt.py", "TraktImporter.import_data", SEASON): IMPORTER,
    ("integrations/imports/trakt.py", "TraktImporter.import_data", TV): IMPORTER,
    ("integrations/imports/xbox.py", "XboxImporter.import_data", "Game"): IMPORTER,
    (
        "integrations/imports/yamtrack.py",
        "YamtrackImporter._apply_status_overrides",
        SEASON,
    ): (IMPORTER),
    (
        "integrations/imports/yamtrack.py",
        "YamtrackImporter._apply_status_overrides",
        TV,
    ): (IMPORTER),
    (
        "integrations/imports/youtube_takeout.py",
        "YouTubeTakeoutImporter._add_plays",
        "VideoPlay",
    ): (
        Refresh(
            changes="Video plays from a YouTube Takeout file.",
            view_caches=IMPORTER.view_caches,
            statistics=IMPORTER.statistics,
            history=IMPORTER.history,
            watch_state="Not needed: videos have no watch-state row.",
        )
    ),
}


def _fill_shared_rows():
    """Give a ``None`` row the answer of the row above it in the same module."""
    previous = None
    for key in list(BULK_WRITE_SITES):
        if BULK_WRITE_SITES[key] is None:
            if previous is None or previous[0][0] != key[0]:
                msg = f"{key} has no row above it in the same module to share."
                raise ValueError(msg)
            BULK_WRITE_SITES[key] = previous[1]
        previous = (key, BULK_WRITE_SITES[key])


_fill_shared_rows()
