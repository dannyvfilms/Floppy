import logging

from celery import shared_task
from django.contrib.auth import get_user_model

from integrations.tasks._import_helpers import (
    ERROR_TITLE,
    GOODREADS_IMPORT_TASK_NAME,
    LEGACY_GOODREADS_IMPORT_TASK_NAMES,
    _coerce_uploaded_file,
    _is_expected_plex_lookup_error,
    format_import_message,
    format_media_type_display,
    format_watchlist_sync_message,
)
from integrations.tasks._koito import (
    KOITO_PARTIAL_SYNC_ERROR,
    KOITO_POLL_TASK_NAME,
    _run_incremental_koito_sync,
    import_koito_history,
    poll_all_koito_accounts,
    poll_koito_for_user,
)
from integrations.tasks._lastfm import (
    LASTFM_PARTIAL_SYNC_ERROR,
    _enqueue_lastfm_music_enrichment,
    _refresh_lastfm_statistics,
    _run_incremental_lastfm_sync,
    import_lastfm_history,
    poll_all_lastfm_scrobbles,
    poll_lastfm_for_user,
)
from integrations.tasks._media_imports import (
    _queue_post_import_collection_update,
    _run_arr_import,
    import_anilist,
    import_audiobookshelf,
    import_audiobookshelf_recurring,
    import_goodreads,
    import_goodreads_dotted,
    import_goodreads_legacy,
    import_gpodder,
    import_gpodder_recurring,
    import_grouvee,
    import_hardcover,
    import_hltb,
    import_imdb,
    import_kitsu,
    import_mal,
    import_mdblist,
    import_media,
    import_plex,
    import_pocketcasts,
    import_pocketcasts_history,
    import_psn,
    import_psn_recurring,
    import_radarr,
    import_radarr_recurring,
    import_simkl,
    import_sonarr,
    import_sonarr_recurring,
    import_steam,
    import_storygraph,  # noqa: F401 - re-exported for tasks.import_storygraph
    import_storyteller,
    import_storyteller_recurring,
    import_stremio,
    import_stremio_recurring,
    import_trakt,
    import_trakt_collection_csv,
    import_trakt_export,
    import_xbox,
    import_xbox_recurring,
    import_yamtrack,
    push_jellyfin_watched,
    sync_plex_watchlist,
)
from integrations.tasks._plex_collection import (
    _aggregate_tv_show_collection_metadata,
    _find_plex_rating_key_for_item,
    fetch_collection_metadata_for_item,
    update_collection_metadata_from_plex,
    update_collection_metadata_from_plex_webhook,
)
from integrations.tasks._webhook import (
    WEBHOOK_PROCESSORS,
    _webhook_history_user,
    process_stremio_webhook,
    process_webhook,
)

logger = logging.getLogger(__name__)


@shared_task(name="Scheduled backup export")
def scheduled_backup_export(
    user_id,
    media_types=None,
    include_lists=True,
    include_collection=True,
):
    """Celery task for exporting a CSV backup to the backup directory."""
    from integrations import exports

    user_model = get_user_model()
    user = user_model.objects.get(id=user_id)
    filepath = exports.write_backup(
        user,
        media_types=media_types,
        include_lists=include_lists,
        include_collection=include_collection,
    )
    return f"Backup saved to {filepath}"


__all__ = [
    "ERROR_TITLE",
    "GOODREADS_IMPORT_TASK_NAME",
    "KOITO_PARTIAL_SYNC_ERROR",
    "KOITO_POLL_TASK_NAME",
    "LASTFM_PARTIAL_SYNC_ERROR",
    "LEGACY_GOODREADS_IMPORT_TASK_NAMES",
    "WEBHOOK_PROCESSORS",
    "_aggregate_tv_show_collection_metadata",
    "_coerce_uploaded_file",
    "_enqueue_lastfm_music_enrichment",
    "_find_plex_rating_key_for_item",
    "_is_expected_plex_lookup_error",
    "_queue_post_import_collection_update",
    "_refresh_lastfm_statistics",
    "_run_arr_import",
    "_run_incremental_koito_sync",
    "_run_incremental_lastfm_sync",
    "_webhook_history_user",
    "fetch_collection_metadata_for_item",
    "format_import_message",
    "format_media_type_display",
    "format_watchlist_sync_message",
    "import_anilist",
    "import_audiobookshelf",
    "import_audiobookshelf_recurring",
    "import_goodreads",
    "import_goodreads_dotted",
    "import_goodreads_legacy",
    "import_gpodder",
    "import_gpodder_recurring",
    "import_grouvee",
    "import_hardcover",
    "import_hltb",
    "import_imdb",
    "import_kitsu",
    "import_koito_history",
    "import_lastfm_history",
    "import_mal",
    "import_mdblist",
    "import_media",
    "import_plex",
    "import_pocketcasts",
    "import_pocketcasts_history",
    "import_psn",
    "import_psn_recurring",
    "import_radarr",
    "import_radarr_recurring",
    "import_simkl",
    "import_sonarr",
    "import_sonarr_recurring",
    "import_steam",
    "import_storyteller",
    "import_storyteller_recurring",
    "import_stremio",
    "import_stremio_recurring",
    "import_trakt",
    "import_trakt_collection_csv",
    "import_trakt_export",
    "import_xbox",
    "import_xbox_recurring",
    "import_yamtrack",
    "poll_all_koito_accounts",
    "poll_all_lastfm_scrobbles",
    "poll_koito_for_user",
    "poll_lastfm_for_user",
    "process_stremio_webhook",
    "process_webhook",
    "push_jellyfin_watched",
    "sync_plex_watchlist",
    "update_collection_metadata_from_plex",
    "update_collection_metadata_from_plex_webhook",
]
