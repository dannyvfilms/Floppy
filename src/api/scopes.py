"""Scope vocabulary and the view scope map enforced by :class:`api.authentication.HasScope`.

Scopes constrain what an ``IntegrationToken`` may reach. The map is keyed by the
view's ``module.ClassName`` so a new endpoint is invisible to scoped tokens until
it is named here; ``api.tests.test_fork_scope_enforcement`` fails the build when a
routed view is missing, so the omission cannot ship silently.

Legacy ``User.token`` credentials and session logins are unaffected: they carry no
token object and keep full access.
"""

# Any authenticated credential may reach the endpoint. Used for endpoints that
# carry no user data of their own, or that a client needs before it knows its
# own grants.
ANY_SCOPE = "*any*"

# No scoped token may reach the endpoint, whatever it holds. Reserved for
# credential management, which a scoped token must never be able to escalate
# through.
NEVER = "*never*"

SCOPE_DESCRIPTIONS = {
    "scrobble:write": "Submit playback events.",
    "progress:read": "Read resume positions and the now-playing state.",
    "progress:write": "Create, update, and clear resume positions.",
    "watchlist:read": "Read saved items, watched state, and consumption history.",
    "watchlist:write": "Change saved items, watched state, tags, and history.",
    "catalog:read": "Read Discover rows, the home surface, search, and the calendar.",
    "catalog:write": "Refresh Discover and the calendar, and hide Discover items.",
    "metadata:read": "Read provider preferences and item metadata.",
    "metadata:write": "Change item metadata, artwork, and provider preferences.",
    "lists:read": "Read lists, list items, collaborators, and list activity.",
    "lists:write": "Change lists, list membership, ordering, and recommendations.",
    "music:read": "Read artists, albums, and tracks.",
    "music:write": "Change music library entries and plays.",
    "podcasts:read": "Read podcast shows and episodes.",
    "podcasts:write": "Change podcast subscriptions and play state.",
    "statistics:read": "Read statistics.",
    "statistics:write": "Trigger a statistics recomputation.",
    "imports:read": "Read import activity.",
    "imports:write": "Start imports.",
    "exports:read": "Download exports.",
    "sync:read": "Read sync connections, change feeds, and conflicts.",
    "sync:write": "Resolve sync conflicts.",
    "user:read": "Read preferences, sidebar, and notification settings.",
    "user:write": "Change preferences, sidebar, and notification settings.",
}

ALL_SCOPES = frozenset(SCOPE_DESCRIPTIONS)

# The preset a tracking client (Nuvio, Stremio, Kodi) needs and no more. Kept in
# step with ``integrations.models.DEFAULT_INTEGRATION_SCOPES``.
TRACKING_PRESET = (
    "scrobble:write",
    "progress:read",
    "progress:write",
    "watchlist:read",
    "watchlist:write",
    "catalog:read",
    "sync:read",
)

_R = "watchlist:read"
_W = "watchlist:write"

# module.ClassName -> {HTTP method: scope}
VIEW_SCOPES: dict[str, dict[str, str]] = {
    "api.fork_views.CollectionView": {"GET": _R, "POST": _W},
    "api.fork_views.CollectionEntryView": {"GET": _R, "PATCH": _W, "DELETE": _W},
    "api.fork_views.MediaProgressView": {"POST": "progress:write"},
    "api.fork_views.TaskStatusView": {"GET": ANY_SCOPE},
    "api.fork_views_discover.CollectionStatusView": {"GET": _R},
    "api.fork_views_discover.CollectionSeasonView": {"DELETE": _W},
    "api.fork_views_discover.DiscoverRowsView": {"GET": "catalog:read"},
    "api.fork_views_discover.DiscoverRefreshView": {"POST": "catalog:write"},
    "api.fork_views_discover.DiscoverHiddenView": {
        "GET": "catalog:read",
        "POST": "catalog:write",
    },
    "api.fork_views_discover.HomeView": {"GET": "catalog:read"},
    "api.fork_views_integrations.ImportDispatchView": {"POST": "imports:write"},
    "api.fork_views_integrations.ImportActivityView": {"GET": "imports:read"},
    "api.fork_views_integrations.ExportCsvView": {"GET": "exports:read"},
    "api.fork_views_integrations.ExportTemplateView": {"GET": "exports:read"},
    "api.fork_views_lists.ListSmartRulesView": {
        "GET": "lists:read",
        "PUT": "lists:write",
    },
    "api.fork_views_lists.ListSmartSyncView": {"POST": "lists:write"},
    "api.fork_views_lists.ListCollaboratorsView": {
        "GET": "lists:read",
        "PUT": "lists:write",
    },
    "api.fork_views_lists.ListItemsReorderView": {"POST": "lists:write"},
    "api.fork_views_lists.ListItemsOrderView": {"PUT": "lists:write"},
    "api.fork_views_lists.ListRecommendationsView": {
        "GET": "lists:read",
        "POST": "lists:write",
    },
    "api.fork_views_lists.ListRecommendationDecisionView": {"POST": "lists:write"},
    "api.fork_views_lists.ListActivityView": {"GET": "lists:read"},
    "api.fork_views_metadata.ItemImageView": {"PATCH": "metadata:write"},
    "api.fork_views_metadata.ItemMetadataView": {
        "GET": "metadata:read",
        "PATCH": "metadata:write",
    },
    "api.fork_views_metadata.MediaProviderPreferenceView": {
        "GET": "metadata:read",
        "PUT": "metadata:write",
    },
    "api.fork_views_metadata.MediaEpisodeScoreView": {"PATCH": _W},
    "api.fork_views_music.MusicArtistsView": {
        "GET": "music:read",
        "POST": "music:write",
    },
    "api.fork_views_music.MusicArtistDetailView": {
        "GET": "music:read",
        "PATCH": "music:write",
        "DELETE": "music:write",
    },
    "api.fork_views_music.MusicArtistSyncView": {"POST": "music:write"},
    "api.fork_views_music.MusicArtistPlaysView": {"DELETE": "music:write"},
    "api.fork_views_music.MusicAlbumsView": {
        "GET": "music:read",
        "POST": "music:write",
    },
    "api.fork_views_music.MusicAlbumDetailView": {
        "GET": "music:read",
        "PATCH": "music:write",
        "DELETE": "music:write",
    },
    "api.fork_views_music.MusicAlbumTracksView": {"GET": "music:read"},
    "api.fork_views_music.MusicAlbumPlaysView": {"DELETE": "music:write"},
    "api.fork_views_music.MusicSongPlayView": {"POST": "music:write"},
    "api.fork_views_music.MusicTrackScoreView": {"PATCH": "music:write"},
    "api.fork_views_music.MusicBulkPlaysView": {"POST": "music:write"},
    "api.fork_views_playback.PlaybackProgressView": {
        "GET": "progress:read",
        "PUT": "progress:write",
        "DELETE": "progress:write",
    },
    "api.fork_views_playback.NowPlayingView": {"GET": "progress:read"},
    "api.fork_views_podcast.PodcastShowsView": {
        "GET": "podcasts:read",
        "POST": "podcasts:write",
    },
    "api.fork_views_podcast.PodcastLookupView": {"GET": "podcasts:read"},
    "api.fork_views_podcast.PodcastShowDetailView": {
        "GET": "podcasts:read",
        "PATCH": "podcasts:write",
        "DELETE": "podcasts:write",
    },
    "api.fork_views_podcast.PodcastShowEpisodesView": {"GET": "podcasts:read"},
    "api.fork_views_podcast.PodcastMarkAllPlayedView": {"POST": "podcasts:write"},
    "api.fork_views_podcast.PodcastEpisodePlayView": {"POST": "podcasts:write"},
    "api.fork_views_scrobble.ScrobbleView": {"POST": "scrobble:write"},
    "api.fork_views_statistics.StatisticsOverviewView": {"GET": "statistics:read"},
    "api.fork_views_statistics.StatisticsRefreshView": {"POST": "statistics:write"},
    "api.fork_views_tracking.MediaEpisodeWatchView": {"POST": _W, "DELETE": _W},
    "api.fork_views_tracking.MediaMovieWatchView": {"POST": _W, "DELETE": _W},
    "api.fork_views_tracking.MediaEpisodeDropView": {"POST": _W},
    "api.fork_views_tracking.MediaEpisodeBulkView": {"POST": _W},
    "api.fork_views_tracking.TagsView": {"GET": _R, "POST": _W},
    "api.fork_views_tracking.TagDetailView": {"PATCH": _W, "DELETE": _W},
    "api.fork_views_tracking.MediaTagsView": {"GET": _R, "PUT": _W},
    "api.fork_views_tracking.HistoryView": {"GET": _R},
    "api.fork_views_tracking.HistoryRecordView": {"DELETE": _W},
    "api.fork_views_watched_state.WatchedStateView": {"GET": _R, "PUT": _W},
    "api.fork_views_watched_state.WatchedStateChangeFeedView": {"GET": "sync:read"},
    "api.fork_views_progress_changes.ProgressChangeFeedView": {"GET": "sync:read"},
    "api.fork_views_watched_state.SyncConnectionsView": {"GET": "sync:read"},
    "api.fork_views_watched_state.SyncConflictsView": {"GET": "sync:read"},
    "api.fork_views_watched_state.SyncConflictResolveView": {"POST": "sync:write"},
    "api.fork_views_users.UserPreferencesView": {
        "GET": "user:read",
        "PATCH": "user:write",
    },
    "api.fork_views_users.UserSidebarView": {
        "GET": "user:read",
        "PUT": "user:write",
    },
    "api.fork_views_users.UserNotificationsView": {
        "GET": "user:read",
        "PATCH": "user:write",
    },
    "api.fork_views_users.UserNotificationExclusionsView": {
        "GET": "user:read",
        "POST": "user:write",
        "DELETE": "user:write",
    },
    "api.fork_views_users.UserNotificationTestView": {"POST": "user:write"},
    # Rotating the account token would let a scoped token mint an unscoped one.
    "api.fork_views_users.UserTokenRegenerateView": {"POST": NEVER},
    "api.listenbrainz_views.SubmitListensView": {"POST": "scrobble:write"},
    # A client must be able to check its own credential before it knows its grants.
    "api.listenbrainz_views.ValidateTokenView": {"GET": ANY_SCOPE},
    "api.schema.LiveSchemaView": {"GET": ANY_SCOPE},
    "api.views.HealthView": {"GET": ANY_SCOPE},
    "api.views.InfoView": {"GET": ANY_SCOPE},
    "api.views.CalendarView": {"GET": "catalog:read"},
    "api.views.CalendarUpdateView": {"POST": "catalog:write"},
    "api.views.SearchProviderView": {"GET": "catalog:read"},
    "api.views.StatisticsView": {"GET": "statistics:read"},
    "api.views.MediaListView": {"GET": _R},
    "api.views.MediaTypeListView": {"GET": _R, "POST": _W},
    "api.views.MediaDetailView": {"GET": _R, "PATCH": _W, "DELETE": _W},
    "api.views.MediaSeasonsView": {"GET": _R},
    "api.views.MediaSeasonDetailView": {"GET": _R, "PATCH": _W, "DELETE": _W},
    "api.views.MediaSeasonEpisodesView": {"GET": _R},
    "api.views.MediaEpisodeDetailView": {"GET": _R, "PATCH": _W, "DELETE": _W},
    "api.views.MediaRecommendationsView": {"GET": "catalog:read"},
    "api.views.MediaChangesHistoryView": {"GET": _R},
    "api.views.MediaSeasonChangesHistoryView": {"GET": _R},
    "api.views.MediaEpisodeChangesHistoryView": {"GET": _R},
    "api.views.MediaTypeChangesHistoryDetailView": {"GET": _R, "DELETE": _W},
    "api.views.MediaConsumptionHistoryView": {"GET": _R},
    "api.views.MediaConsumptionEntryDetailView": {
        "GET": _R,
        "PATCH": _W,
        "DELETE": _W,
    },
    "api.views.MediaSeasonConsumptionHistoryView": {"GET": _R},
    "api.views.MediaSeasonConsumptionEntryDetailView": {
        "GET": _R,
        "PATCH": _W,
        "DELETE": _W,
    },
    "api.views.MediaEpisodeConsumptionHistoryView": {"GET": _R},
    "api.views.MediaEpisodeConsumptionEntryDetailView": {
        "GET": _R,
        "PATCH": _W,
        "DELETE": _W,
    },
    # Sync refreshes provider metadata for the item.
    "api.views.MediaSyncView": {"POST": "metadata:write"},
    "api.views.MediaSeasonSyncView": {"POST": "metadata:write"},
    "api.views.MediaEpisodeSyncView": {"POST": "metadata:write"},
    "api.views.ListsView": {"GET": "lists:read", "POST": "lists:write"},
    "api.views.ListDetailView": {
        "GET": "lists:read",
        "PATCH": "lists:write",
        "DELETE": "lists:write",
    },
    "api.views.ListItemsView": {"GET": "lists:read"},
    "api.views.ListItemView": {"GET": "lists:read", "DELETE": "lists:write"},
    "api.views.MediaListsView": {"GET": "lists:read"},
    "api.views.MediaListDetailView": {"PUT": "lists:write", "DELETE": "lists:write"},
    "api.views.MediaSeasonListsView": {"GET": "lists:read"},
    "api.views.MediaSeasonListDetailView": {
        "PUT": "lists:write",
        "DELETE": "lists:write",
    },
    "api.views.MediaEpisodeListsView": {"GET": "lists:read"},
    "api.views.MediaEpisodeListDetailView": {
        "PUT": "lists:write",
        "DELETE": "lists:write",
    },
}


def view_key(view) -> str:
    """Return the ``module.ClassName`` key used by :data:`VIEW_SCOPES`."""
    cls = type(view)
    return f"{cls.__module__}.{cls.__name__}"


def resolve_required_scope(view, method: str) -> str | None:
    """Return the scope a scoped token needs for ``method`` on ``view``.

    Returns :data:`ANY_SCOPE` when any valid token is enough, :data:`NEVER` when
    no scoped token may pass, and ``None`` when the endpoint is unmapped. An
    unmapped endpoint is denied to scoped tokens; see the module docstring.
    """
    explicit = getattr(view, "required_scopes", None)
    if explicit:
        return explicit.get(method.upper())
    single = getattr(view, "required_scope", None)
    if single:
        return single
    mapped = VIEW_SCOPES.get(view_key(view))
    if mapped is None:
        return None
    return mapped.get(method.upper())
