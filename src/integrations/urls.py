from django.urls import path, re_path

from integrations import views

urlpatterns = [
    path("import/trakt-oauth", views.trakt_oauth, name="trakt_oauth"),
    path(
        "import/trakt/private",
        views.import_trakt_private,
        name="import_trakt_private",
    ),
    path("import/trakt/public", views.import_trakt_public, name="import_trakt_public"),
    path(
        "import/trakt/export",
        views.import_trakt_export_file,
        name="import_trakt_export_file",
    ),
    # Legacy route kept working for anything still pointing at the CSV-only URL.
    path(
        "import/trakt/collection-csv",
        views.import_trakt_export_file,
        name="import_trakt_collection_csv",
    ),
    path("import/mdblist", views.import_mdblist, name="import_mdblist"),
    path("import/plex/connect", views.plex_connect, name="plex_connect"),
    path("import/plex/callback", views.plex_callback, name="plex_callback"),
    path("import/plex/disconnect", views.plex_disconnect, name="plex_disconnect"),
    path(
        "import/plex/watchlist/disable",
        views.plex_disable_watchlist,
        name="plex_disable_watchlist",
    ),
    path("import/plex", views.import_plex, name="import_plex"),
    path("import/simkl-oauth", views.simkl_oauth, name="simkl_oauth"),
    path(
        "import/simkl_private",
        views.import_simkl_private,
        name="import_simkl_private",
    ),
    path("import/mal", views.import_mal, name="import_mal"),
    path("import/anilist/oauth", views.anilist_oauth, name="import_anilist_oauth"),
    path(
        "import/anilist/private",
        views.import_anilist_private,
        name="import_anilist_private",
    ),
    path(
        "import/anilist/public",
        views.import_anilist_public,
        name="import_anilist_public",
    ),
    path("import/kitsu", views.import_kitsu, name="import_kitsu"),
    path("import/yamtrack", views.import_yamtrack, name="import_yamtrack"),
    path("import/hltb", views.import_hltb, name="import_hltb"),
    path("import/grouvee", views.import_grouvee, name="import_grouvee"),
    path("import/steam", views.import_steam, name="import_steam"),
    path("import/radarr/connect", views.radarr_connect, name="radarr_connect"),
    path("import/radarr/disconnect", views.radarr_disconnect, name="radarr_disconnect"),
    path("import/radarr", views.import_radarr, name="import_radarr"),
    path("import/sonarr/connect", views.sonarr_connect, name="sonarr_connect"),
    path("import/sonarr/disconnect", views.sonarr_disconnect, name="sonarr_disconnect"),
    path("import/sonarr", views.import_sonarr, name="import_sonarr"),
    path("jellyfin/connect", views.jellyfin_connect, name="jellyfin_connect"),
    path("jellyfin/disconnect", views.jellyfin_disconnect, name="jellyfin_disconnect"),
    path("jellyfin/settings", views.jellyfin_settings, name="jellyfin_settings"),
    path("jellyfin/push", views.jellyfin_push_now, name="jellyfin_push_now"),
    path(
        "jellyfin/playback-reporting/import",
        views.jellyfin_playback_reporting_import,
        name="jellyfin_playback_reporting_import",
    ),
    path("import/imdb", views.import_imdb, name="import_imdb"),
    path("import/goodreads", views.import_goodreads, name="import_goodreads"),
    path("import/hardcover", views.import_hardcover, name="import_hardcover"),
    path("import/storygraph", views.import_storygraph, name="import_storygraph"),
    path(
        "import/audiobookshelf/connect",
        views.audiobookshelf_connect,
        name="audiobookshelf_connect",
    ),
    path(
        "import/audiobookshelf/disconnect",
        views.audiobookshelf_disconnect,
        name="audiobookshelf_disconnect",
    ),
    path(
        "import/audiobookshelf",
        views.import_audiobookshelf,
        name="import_audiobookshelf",
    ),
    path(
        "import/storyteller/connect",
        views.storyteller_connect,
        name="storyteller_connect",
    ),
    path("import/storyteller/poll", views.storyteller_poll, name="storyteller_poll"),
    path(
        "import/storyteller/cancel", views.storyteller_cancel, name="storyteller_cancel"
    ),
    path(
        "import/storyteller/disconnect",
        views.storyteller_disconnect,
        name="storyteller_disconnect",
    ),
    path("import/storyteller", views.import_storyteller, name="import_storyteller"),
    path("import/stremio/connect", views.stremio_connect, name="stremio_connect"),
    path(
        "import/stremio/disconnect", views.stremio_disconnect, name="stremio_disconnect"
    ),
    path("import/stremio", views.import_stremio, name="import_stremio"),
    path("import/xbox/connect", views.xbox_connect, name="xbox_connect"),
    path("import/xbox/disconnect", views.xbox_disconnect, name="xbox_disconnect"),
    path("import/xbox", views.import_xbox, name="import_xbox"),
    path("import/psn/connect", views.psn_connect, name="psn_connect"),
    path("import/psn/disconnect", views.psn_disconnect, name="psn_disconnect"),
    path("import/psn", views.import_psn, name="import_psn"),
    path(
        "import/pocketcasts/connect",
        views.pocketcasts_connect,
        name="pocketcasts_connect",
    ),
    path(
        "import/pocketcasts/disconnect",
        views.pocketcasts_disconnect,
        name="pocketcasts_disconnect",
    ),
    path("import/pocketcasts", views.import_pocketcasts, name="import_pocketcasts"),
    path("import/gpodder/connect", views.gpodder_connect, name="gpodder_connect"),
    path(
        "import/gpodder/disconnect", views.gpodder_disconnect, name="gpodder_disconnect"
    ),
    path("import/gpodder", views.import_gpodder, name="import_gpodder"),
    path("import/lastfm/connect", views.lastfm_connect, name="lastfm_connect"),
    path("import/lastfm/disconnect", views.lastfm_disconnect, name="lastfm_disconnect"),
    path(
        "import/lastfm/history",
        views.import_lastfm_history_manual,
        name="import_lastfm_history",
    ),
    path("import/lastfm/poll", views.poll_lastfm_manual, name="poll_lastfm_manual"),
    path("import/koito/connect", views.koito_connect, name="koito_connect"),
    path("import/koito/disconnect", views.koito_disconnect, name="koito_disconnect"),
    path(
        "import/koito/history",
        views.import_koito_history_manual,
        name="import_koito_history",
    ),
    path("import/koito/poll", views.poll_koito_manual, name="poll_koito_manual"),
    path("export/csv", views.export_csv, name="export_csv"),
    path(
        "export/csv/letterboxd",
        views.export_csv_letterboxd,
        name="export_csv_letterboxd",
    ),
    path(
        "import/yamtrack/template",
        views.import_template_csv,
        name="import_template_csv",
    ),
    path(
        "webhook/jellyfin/<str:token>",
        views.jellyfin_webhook,
        name="jellyfin_webhook",
    ),
    path(
        "webhook/plex/<str:token>",
        views.plex_webhook,
        name="plex_webhook",
    ),
    path(
        "webhook/emby/<str:token>",
        views.emby_webhook,
        name="emby_webhook",
    ),
    # kept: URL path/name unchanged — renaming breaks already-configured Seerr/Jellyseerr webhook URLs
    path(
        "webhook/jellyseerr/<str:token>",
        views.jellyseerr_webhook,
        name="jellyseerr_webhook",
    ),
    path(
        "webhook/seerr/global/",
        views.seerr_global_webhook,
        name="seerr_global_webhook",
    ),
    path(
        "webhook/kodi/<str:token>",
        views.kodi_webhook,
        name="kodi_webhook",
    ),
    path(
        "stremio-addon/<str:token>/manifest.json",
        views.stremio_addon_manifest,
        name="stremio_addon_manifest",
    ),
    re_path(
        r"^stremio-addon/(?P<token>[^/]+)/catalog/"
        r"(?P<media_type>movie|series)/"
        r"(?P<catalog_id>[^/]+?)(?:/(?P<extra>[^/]*))?\.json$",
        views.stremio_addon_catalog,
        name="stremio_addon_catalog",
    ),
    re_path(
        r"^stremio-addon/(?P<token>[^/]+)/subtitles/"
        r"(?P<media_type>movie|series)/(?P<media_id>[^/]+?)(?:/[^/]*)?\.json$",
        views.stremio_addon_subtitles,
        name="stremio_addon_subtitles",
    ),
]
