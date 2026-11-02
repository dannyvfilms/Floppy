# FORK: overlay module — extends the upstream-owned dicts in api/helpers.py
# with the fork-only media types (music, podcast, comicissue) at app-ready
# time, so upstream's files stay byte-close to feat/add-api for mergeability.
from http import HTTPStatus as HTTP  # noqa: N814

from rest_framework.response import Response

from app.collection_views import _resolve_collection_item
from app.helpers import extract_release_datetime
from app.models import (
    ComicIssue,
    MediaTypes,
    MoviePlay,
    Music,
    Podcast,
    Sources,
    Video,
)
from app.providers import services
from app.services import metadata_resolution

from . import helpers

FORK_MEDIA_MODELS = {
    MediaTypes.MUSIC.value: Music,
    MediaTypes.PODCAST.value: Podcast,
    MediaTypes.COMIC_ISSUE.value: ComicIssue,
    MediaTypes.VIDEO.value: Video,
}

FORK_VALID_SOURCES = {
    MediaTypes.MUSIC.value: [Sources.MUSICBRAINZ.value, Sources.MANUAL.value],
    MediaTypes.PODCAST.value: [
        Sources.POCKETCASTS.value,
        Sources.GPODDER.value,
        Sources.AUDIOBOOKSHELF.value,
    ],
    MediaTypes.COMIC_ISSUE.value: [
        Sources.COMICVINE.value,
        Sources.GCD.value,
        Sources.MANUAL.value,
    ],
    MediaTypes.VIDEO.value: [Sources.YOUTUBE.value],
}

# FORK: sources the fork resolves for a media type upstream *already* lists.
# Kept apart from FORK_VALID_SOURCES because that dict is applied with
# `setdefault`, which can introduce a media type but never extend one. Every
# entry here has a matching branch in `services.get_media_metadata` — keep the
# two in step, or the API will accept a source it cannot then resolve.
FORK_EXTRA_SOURCES = {
    # TVDB series, season and episode metadata. Also the source Plex writes
    # for sports and anything else TMDB does not carry.
    MediaTypes.TV.value: [Sources.TVDB.value],
    MediaTypes.SEASON.value: [Sources.TVDB.value],
    MediaTypes.EPISODE.value: [Sources.TVDB.value],
    # Anime resolves from all three: MAL natively, TMDB and TVDB through the
    # grouped-anime route.
    MediaTypes.ANIME.value: [Sources.TMDB.value, Sources.TVDB.value],
}

_MODIFIABLE_FIELDS = {
    "score", "status", "progress", "start_date", "end_date", "notes",
    "entry_source",
}


# FORK: sort vocabulary for consumption-history endpoints (upstream TODO:
# "missing sorting"). Values reuse the aggregated-sort names where they apply.
_HISTORY_SORT_KEYS = {
    "started": lambda media: (
        getattr(media, "start_date", None) is None,
        getattr(media, "start_date", None),
    ),
    "ended": lambda media: (
        getattr(media, "end_date", None) is None,
        getattr(media, "end_date", None),
    ),
    "added": lambda media: (
        getattr(media, "created_at", None) is None,
        getattr(media, "created_at", None),
    ),
    "score": lambda media: (
        getattr(media, "score", None) is None,
        getattr(media, "score", None),
    ),
}


def sort_history_results(request, results):
    """Sort consumption-history rows by the optional `sort` query param.

    Accepts `started`, `ended`, `added`, `score`, each with an optional `-`
    prefix for descending order. Returns (results, error_response).
    """
    sort = request.GET.get("sort")
    if sort in (None, ""):
        return results, None
    descending = sort.startswith("-")
    key_name = sort[1:] if descending else sort
    key = _HISTORY_SORT_KEYS.get(key_name)
    if key is None:
        valid = ", ".join(sorted(_HISTORY_SORT_KEYS))
        return None, Response(
            {"detail": f"Invalid sort. Valid values: {valid} (prefix '-' to reverse)."},
            status=HTTP.BAD_REQUEST,
        )
    return sorted(results, key=key, reverse=descending), None


# FORK: movie rewatch support (issue #577). Movies keep the pre-existing
# single-tracker-row history contract until a movie's first `watch()` call
# creates MoviePlay rows — from then on, history for that movie is served
# from MoviePlay instead, so untouched movies see zero behavior change.
def movie_plays_for_history(user_medias, media_type):
    """Return MoviePlay rows for a movie's history, or None if it has none."""
    if media_type != MediaTypes.MOVIE.value:
        return None
    movie = user_medias.first()
    if movie is None:
        return None
    plays = list(MoviePlay.objects.filter(movie=movie))
    return plays or None


def resolve_consumption_entry(user_medias, media_type, consumption_id):
    """Resolve an entry id the same way `.../history/` lists it.

    Once a movie has MoviePlay rows its history is served only from those
    rows, so only a MoviePlay id is valid then. Movie and MoviePlay use
    independent id sequences and can collide, so checking the Movie row first
    let an entry id resolve to the movie and delete it. Untouched movies keep
    the single tracker row.
    """
    if media_type == MediaTypes.MOVIE.value:
        movie = user_medias.first()
        if movie is not None and MoviePlay.objects.filter(movie=movie).exists():
            return MoviePlay.objects.filter(movie=movie, id=consumption_id).first()
    return user_medias.filter(id=consumption_id).first()


def get_or_create_provider_item(
    media_type,
    source,
    media_id,
    *,
    user=None,
    season_number=None,
    episode_number=None,
    library_media_type=None,
):
    """Return ``(item, error_response)`` for a provider id.

    An item Floppy has never seen is created from provider metadata, the same
    way the web UI creates one, so an external client can address a title by
    its provider id without tracking it first. Metadata is fetched in the
    user's preferred language.
    """
    item = helpers.resolve_item_queryset(
        media_id,
        source,
        media_type,
        season_number=season_number,
        episode_number=episode_number,
        library_media_type=library_media_type,
    ).first()
    if item is not None:
        return item, None

    not_found = Response({"detail": "Media not found."}, status=HTTP.NOT_FOUND)
    if source == Sources.MANUAL.value or metadata_resolution.is_grouped_anime_route(
        media_type,
        source=source,
    ):
        # Grouped anime is stored as TV in the anime bucket, which the
        # list and collection lookups by "anime" cannot find, so it is not
        # created on demand.
        return None, not_found

    try:
        metadata = services.get_media_metadata(
            media_type,
            media_id,
            source,
            [season_number] if season_number is not None else None,
            episode_number=episode_number,
            language=metadata_resolution.metadata_language_default(user),
        )
    except services.ProviderAPIError as error:
        if error.status_code == HTTP.NOT_FOUND:
            return None, not_found
        return None, Response(
            {"detail": f"Could not reach {error.provider_label}."},
            status=HTTP.BAD_GATEWAY,
        )
    if not metadata:
        return None, not_found

    item, _ = _resolve_collection_item(
        source,
        media_type,
        media_id,
        season_number,
        episode_number,
        metadata=metadata,
    )
    # A client matches titles by year and by cross-provider ids, so store both
    # now instead of waiting for a later metadata refresh.
    release_datetime = extract_release_datetime(metadata)
    if release_datetime and item.release_datetime is None:
        item.release_datetime = release_datetime
        item.save(update_fields=["release_datetime"])
    if season_number is None and episode_number is None:
        metadata_resolution.upsert_provider_links(
            item,
            metadata,
            provider=source,
            provider_media_type=media_type,
        )
    return item, None


def install_fork_media_types():
    """Register fork media types in the upstream lookup tables (idempotent)."""
    helpers.MEDIA_TYPE_MODEL_MAP.update(FORK_MEDIA_MODELS)
    helpers.MEDIA_TYPE_COMPLETE_MODEL_MAP.update(FORK_MEDIA_MODELS)
    # The VALID_LISTs are module-level list objects imported by name elsewhere;
    # mutate them in place so every importer sees the additions.
    helpers.MEDIA_TYPE_VALID_LIST[:] = list(helpers.MEDIA_TYPE_MODEL_MAP)
    helpers.MEDIA_TYPE_COMPLETE_VALID_LIST[:] = list(
        helpers.MEDIA_TYPE_COMPLETE_MODEL_MAP,
    )
    for media_type in FORK_MEDIA_MODELS:
        helpers.MEDIA_MODIFIABLE_FIELDS.setdefault(media_type, set(_MODIFIABLE_FIELDS))
    for media_type, sources in FORK_VALID_SOURCES.items():
        helpers.VALID_SOURCES.setdefault(media_type, list(sources))
    # Extend the entries upstream already owns, rather than defaulting them.
    # The lists are mutated in place for the same reason MEDIA_TYPE_VALID_LIST
    # is: they are module-level objects other modules hold references to.
    for media_type, extra in FORK_EXTRA_SOURCES.items():
        valid = helpers.VALID_SOURCES.setdefault(media_type, [])
        valid.extend(source for source in extra if source not in valid)
    # Episodes support the shared tracker fields plus the legacy dropped flag.
    helpers.MEDIA_MODIFIABLE_FIELDS[MediaTypes.EPISODE.value] |= _MODIFIABLE_FIELDS | {
        "dropped"
    }
