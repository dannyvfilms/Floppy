"""Service capability map used by the first-run setup wizard.

Answers, for a given import source, which media types it's relevant to and
whether the current user already has it connected. This is additive: it
reads the same account relations the ``import_data`` view already exposes
in its template context (``src/users/views.py:import_data``) rather than
introducing a new notion of "connected", and it doesn't change
``import_data.html``, ``SOURCES_CONFIG``, or any existing import view.

The wizard opens a source's existing setup/import UI via
``import_data`` (``?open=<slug>``) rather than duplicating its forms, so
this module only needs to know *which* sources are relevant to *which*
media types and whether they're already connected — not their connect/
import URLs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.choices import MediaTypes

MOVIE = MediaTypes.MOVIE.value
TV = MediaTypes.TV.value
ANIME = MediaTypes.ANIME.value
MANGA = MediaTypes.MANGA.value
GAME = MediaTypes.GAME.value
BOARDGAME = MediaTypes.BOARDGAME.value
BOOK = MediaTypes.BOOK.value
COMIC = MediaTypes.COMIC.value
MUSIC = MediaTypes.MUSIC.value
PODCAST = MediaTypes.PODCAST.value

ALL_MEDIA_TYPES = (
    MOVIE,
    TV,
    ANIME,
    MANGA,
    GAME,
    BOARDGAME,
    BOOK,
    COMIC,
    MUSIC,
    PODCAST,
)


@dataclass(frozen=True)
class OnboardingSource:
    """One import source, as the setup wizard needs to reason about it."""

    slug: str
    media_types: tuple[str, ...]
    setup_kind: str  # oauth | api_key | host_url | credentials | upload
    account_attr: str | None = None  # request.user.<attr> if persistently connected
    recommended_import_mode: str = "new"
    tags: tuple[str, ...] = field(default_factory=tuple)  # matches import_data.html's activeMediaTag values
    integration_tag: str | None = None  # matches integrations.html's activeIntegration values
    integration_configured_attr: str | None = None  # request.user.<attr> truthy once webhook is live

    # --- Inline "Connect" step in the setup wizard (service_setup.html) ---
    # connect_url_name is the Django URL name the wizard's form posts to
    # (for uploads, the same view that both stores the file and queues the
    # import task). is_oauth sources render a single "Connect via <slug>"
    # link to that URL instead of a form. upload_field_name/upload_accept
    # only apply when setup_kind == "upload". connect_fields lists the
    # plain-text/password fields to render for every other inline kind, as
    # (name, label, input_type) tuples. Sources with inline_supported=False
    # fall back to the old "opens Settings > Import" redirect link, for
    # setup flows (e.g. Storyteller's device-code polling) that don't fit
    # a single inline form.
    connect_url_name: str | None = None
    is_oauth: bool = False
    upload_field_name: str | None = None
    upload_accept: str = ".csv"
    connect_fields: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)
    inline_supported: bool = True

    def is_connected(self, user) -> bool:
        """Whether this user already has a persistent connection for this source."""
        if not self.account_attr:
            return False
        return getattr(user, self.account_attr, None) is not None

    def has_integration(self) -> bool:
        """Whether this source has a separate realtime integration (e.g. a webhook)."""
        return self.integration_tag is not None

    def is_integration_configured(self, user) -> bool:
        """Whether the realtime integration has already received activity."""
        if not self.integration_configured_attr:
            return False
        return bool(getattr(user, self.integration_configured_attr, None))


ONBOARDING_SOURCES: tuple[OnboardingSource, ...] = (
    OnboardingSource(
        "plex",
        (MOVIE, TV, MUSIC),
        "oauth",
        "plex_account",
        tags=("screen", "music"),
        integration_tag="plex",
        integration_configured_attr="plex_webhook_last_received_at",
        connect_url_name="plex_connect",
        is_oauth=True,
    ),
    OnboardingSource(
        "radarr",
        (MOVIE,),
        "host_url",
        "radarr_account",
        tags=("screen",),
        connect_url_name="radarr_connect",
        connect_fields=(("base_url", "Base URL", "url"), ("api_key", "API Key", "password")),
    ),
    OnboardingSource(
        "sonarr",
        (TV,),
        "host_url",
        "sonarr_account",
        tags=("screen",),
        connect_url_name="sonarr_connect",
        connect_fields=(("base_url", "Base URL", "url"), ("api_key", "API Key", "password")),
    ),
    OnboardingSource(
        "stremio",
        (MOVIE, TV),
        "credentials",
        "stremio_account",
        tags=("screen",),
        connect_url_name="stremio_connect",
        connect_fields=(("email", "Email", "text"), ("password", "Password", "password")),
    ),
    OnboardingSource(
        "audiobookshelf",
        (BOOK, PODCAST),
        "host_url",
        "audiobookshelf_account",
        tags=("reading", "podcasts"),
        connect_url_name="audiobookshelf_connect",
        connect_fields=(("base_url", "Server URL", "url"), ("api_token", "API Token", "password")),
    ),
    OnboardingSource(
        "storyteller",
        (BOOK,),
        "host_url",
        "storyteller_account",
        tags=("reading",),
        inline_supported=False,  # device-code polling flow, doesn't fit a single inline form
    ),
    OnboardingSource(
        "pocketcasts",
        (PODCAST,),
        "credentials",
        "pocketcasts_account",
        tags=("podcasts",),
        connect_url_name="pocketcasts_connect",
        connect_fields=(("email", "Email", "text"), ("password", "Password", "password")),
    ),
    OnboardingSource(
        "gpodder",
        (PODCAST,),
        "credentials",
        "gpodder_account",
        tags=("podcasts",),
        connect_url_name="gpodder_connect",
        connect_fields=(
            ("server_url", "Server URL", "url"),
            ("username", "Username", "text"),
            ("password", "Password", "password"),
        ),
    ),
    OnboardingSource(
        "lastfm",
        (MUSIC,),
        "api_key",
        "lastfm_account",
        tags=("music",),
        connect_url_name="lastfm_connect",
        connect_fields=(("lastfm_username", "Last.fm Username", "text"),),
    ),
    OnboardingSource(
        "koito",
        (MUSIC,),
        "host_url",
        "koito_account",
        tags=("music",),
        connect_url_name="koito_connect",
        connect_fields=(("base_url", "Server URL", "url"), ("api_key", "API Key", "password")),
    ),
    OnboardingSource(
        "trakt",
        (MOVIE, TV),
        "oauth",
        recommended_import_mode="new",
        tags=("screen",),
        connect_url_name="trakt_oauth",
        is_oauth=True,
    ),
    OnboardingSource(
        "mdblist",
        (MOVIE, TV),
        "api_key",
        "mdblist_account",
        tags=("screen",),
        connect_url_name="import_mdblist",
        connect_fields=(("api_key", "API Key", "password"),),
    ),
    OnboardingSource(
        "simkl",
        (MOVIE, TV, ANIME),
        "oauth",
        tags=("screen", "anime_manga"),
        connect_url_name="simkl_oauth",
        is_oauth=True,
    ),
    OnboardingSource(
        "myanimelist",
        (ANIME, MANGA),
        "oauth",
        tags=("anime_manga",),
        # Not actually OAuth: MAL has no token exchange, just a public username.
        connect_url_name="import_mal",
        connect_fields=(("user", "MyAnimeList Username", "text"),),
    ),
    OnboardingSource(
        "anilist",
        (ANIME, MANGA),
        "oauth",
        tags=("anime_manga",),
        connect_url_name="import_anilist_oauth",
        is_oauth=True,
    ),
    OnboardingSource(
        "kitsu",
        (ANIME, MANGA),
        "credentials",
        tags=("anime_manga",),
        connect_url_name="import_kitsu",
        connect_fields=(("user", "Kitsu User ID", "text"),),
    ),
    OnboardingSource(
        "hltb",
        (GAME,),
        "upload",  # CSV export, not credentials
        tags=("games",),
        connect_url_name="import_hltb",
        upload_field_name="hltb_csv",
    ),
    OnboardingSource(
        "grouvee",
        (GAME,),
        "upload",
        tags=("games",),
        connect_url_name="import_grouvee",
        upload_field_name="grouvee_json",
        upload_accept=".json",
    ),
    OnboardingSource(
        "steam",
        (GAME,),
        "credentials",
        tags=("games",),
        connect_url_name="import_steam",
        connect_fields=(("user", "Steam ID", "text"),),
    ),
    OnboardingSource(
        "imdb",
        (MOVIE, TV),
        "upload",
        tags=("screen",),
        connect_url_name="import_imdb",
        upload_field_name="imdb_csv",
    ),
    OnboardingSource(
        "goodreads",
        (BOOK,),
        "upload",
        tags=("reading",),
        connect_url_name="import_goodreads",
        upload_field_name="goodreads_csv",
    ),
    OnboardingSource(
        "hardcover",
        (BOOK,),
        "upload",
        tags=("reading",),
        connect_url_name="import_hardcover",
        upload_field_name="hardcover_csv",
    ),
    OnboardingSource(
        "storygraph",
        (BOOK,),
        "upload",
        tags=("reading",),
        connect_url_name="import_storygraph",
        upload_field_name="storygraph_csv",
    ),
    OnboardingSource(
        "yamtrack",
        ALL_MEDIA_TYPES,
        "upload",
        recommended_import_mode="overwrite",
        tags=("backup", "screen", "anime_manga", "reading", "games", "podcasts", "music"),
        connect_url_name="import_yamtrack",
        upload_field_name="yamtrack_csv",
    ),
)

_SOURCES_BY_SLUG = {source.slug: source for source in ONBOARDING_SOURCES}


def get_source(slug: str) -> OnboardingSource | None:
    """Return the ``OnboardingSource`` for ``slug``, if known."""
    return _SOURCES_BY_SLUG.get(slug)


def sources_for_media_type(media_type: str) -> list[OnboardingSource]:
    """Return sources relevant to a single media type, in a stable, sensible order."""
    return [source for source in ONBOARDING_SOURCES if media_type in source.media_types]
