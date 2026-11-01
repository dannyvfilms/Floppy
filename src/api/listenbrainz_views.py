# FORK: ListenBrainz-compatible endpoints. Mounted at the root under
# /apis/listenbrainz/1/ rather than /api/v1/ so that any client accepting a
# custom ListenBrainz URL (Multi-Scrobbler, Navidrome, Pano Scrobbler, ...) can
# point at Floppy's base URL unmodified. Receive-only: Floppy never submits
# listens outward. Besides ingest, it serves the token owner's own history and
# statistics back, for clients that build recommendations from them. URL wiring
# lives in listenbrainz_urls.py.
import logging
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from http import HTTPStatus as HTTP  # noqa: N814

from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import views as drf_views
from rest_framework.response import Response

from api.authentication import ListenBrainzTokenAuthentication
from api.contract_serializers import (
    DetailErrorSerializer,
    ListenBrainzErrorSerializer,
    ListenBrainzGenreActivitySerializer,
    ListenBrainzListensSerializer,
    ListenBrainzStatusSerializer,
    ListenBrainzTokenSerializer,
    ListenBrainzUserArtistsSerializer,
    ListenBrainzUserRecordingsSerializer,
    ListenBrainzUserReleaseGroupsSerializer,
)
from app.metadata_utils import normalize_genres
from app.models import Music
from integrations.webhooks.listenbrainz import ListenBrainzScrobbleProcessor

logger = logging.getLogger(__name__)

# "single" and "import" are recorded; "playing_now" is accepted but not stored.
_RECORDED_LISTEN_TYPES = ("single", "import")
_LISTEN_TYPES = (*_RECORDED_LISTEN_TYPES, "playing_now")

MAX_LISTENS_PER_SUBMISSION = 1000
DEFAULT_LISTENS_PAGE_SIZE = 25
MAX_LISTENS_PAGE_SIZE = 1000

# The ranges ListenBrainz accepts on its user statistics. The "this_*" ranges
# run to now; the others are the last complete period, as ListenBrainz does.
STATS_RANGES = (
    "this_week",
    "this_month",
    "this_year",
    "week",
    "month",
    "quarter",
    "half_yearly",
    "year",
    "all_time",
)
DEFAULT_STATS_RANGE = "all_time"
DEFAULT_STATS_PAGE_SIZE = 25
MAX_STATS_PAGE_SIZE = 100

# Clients look these identifiers up on MusicBrainz, so only real MBIDs go out.
_MBID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
)


def _error(message, status=HTTP.BAD_REQUEST):
    """Return a ListenBrainz-shaped error response."""
    return Response({"code": int(status), "error": message}, status=status)


def _mbid(value):
    """Return a MusicBrainz identifier, or None when the value is not one."""
    value = (value or "").strip().lower()
    return value if _MBID_PATTERN.match(value) else None


def _user_play_rows(user):
    """History rows of the user's completed plays.

    A play is one (entry, end_date) pair; several history rows can carry it
    when the entry is edited afterwards, so callers deduplicate on that pair.
    """
    return Music.history.model.objects.filter(
        id__in=Music.objects.filter(user=user).values("id"),
        end_date__isnull=False,
    )


def _optional_int(params, name):
    """Return an integer query parameter, or None when it is absent."""
    raw = params.get(name)
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _listen_metadata(music, origin_url):
    """Build the track metadata for one historical play."""
    track = music.track
    album = music.album
    artist = music.artist or (album.artist if album else None)

    track_name = track.title if track else music.item.title
    metadata = {
        "artist_name": artist.name if artist else "",
        "track_name": track_name,
    }
    if album:
        metadata["release_name"] = album.title

    additional = {}
    if track and track.musicbrainz_recording_id:
        additional["recording_mbid"] = track.musicbrainz_recording_id
    if album and album.musicbrainz_release_id:
        additional["release_mbid"] = album.musicbrainz_release_id
    if album and album.musicbrainz_release_group_id:
        additional["release_group_mbid"] = album.musicbrainz_release_group_id
    if artist and artist.musicbrainz_id:
        additional["artist_mbids"] = [artist.musicbrainz_id]
    if track and track.duration_ms:
        additional["duration_ms"] = track.duration_ms
    if track and track.track_number:
        additional["tracknumber"] = track.track_number
    if origin_url:
        additional["origin_url"] = origin_url
    if additional:
        metadata["additional_info"] = additional
    return metadata


@extend_schema_view(
    get=extend_schema(
        operation_id="getListenBrainzUserListens",
        summary="Get listens for a user (ListenBrainz-compatible)",
        description=(
            "Returns recorded plays newest first, so ListenBrainz clients such as "
            "Multi-Scrobbler can check what has already reached Floppy before "
            "submitting a play. Only the token owner's listens are available."
        ),
        parameters=[
            OpenApiParameter(
                name="username",
                type=str,
                location=OpenApiParameter.PATH,
                description="The token owner's Floppy username.",
            ),
            OpenApiParameter(
                name="count",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Maximum listens to return (default 25).",
            ),
            OpenApiParameter(
                name="min_ts",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Exclusive lower bound on listened_at (Unix seconds).",
            ),
            OpenApiParameter(
                name="max_ts",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Exclusive upper bound on listened_at (Unix seconds).",
            ),
        ],
        responses={
            200: ListenBrainzListensSerializer,
            400: ListenBrainzErrorSerializer,
            401: DetailErrorSerializer,
            404: ListenBrainzErrorSerializer,
        },
    )
)
class UserListensView(drf_views.APIView):
    """ListenBrainz `user/<username>/listens` endpoint."""

    authentication_classes = [ListenBrainzTokenAuthentication]

    def get(self, request, username):
        """Return the token owner's plays in the requested time window."""
        if username.lower() != request.user.username.lower():
            return _error("User not found.", status=HTTP.NOT_FOUND)

        count = _optional_int(request.query_params, "count")
        if count is None:
            count = DEFAULT_LISTENS_PAGE_SIZE
        if count < 1:
            return _error("count must be a positive integer.")
        count = min(count, MAX_LISTENS_PAGE_SIZE)

        min_ts = _optional_int(request.query_params, "min_ts")
        max_ts = _optional_int(request.query_params, "max_ts")
        for name, value in (("min_ts", min_ts), ("max_ts", max_ts)):
            if request.query_params.get(name) not in (None, "") and value is None:
                return _error(f"{name} must be an integer Unix timestamp.")

        rows = _user_play_rows(request.user)
        if min_ts is not None:
            rows = rows.filter(
                end_date__gt=datetime.fromtimestamp(min_ts, tz=UTC),
            )
        if max_ts is not None:
            rows = rows.filter(
                end_date__lt=datetime.fromtimestamp(max_ts, tz=UTC),
            )

        plays = []
        seen = set()
        for row in rows.order_by("-end_date", "-history_id").iterator():
            key = (row.id, row.end_date)
            if key in seen:
                continue
            seen.add(key)
            plays.append(row)
            if len(plays) >= count:
                break

        music_by_id = Music.objects.filter(
            user=request.user,
            id__in={row.id for row in plays},
        ).select_related("item", "artist", "album", "track")
        music_by_id = {music.id: music for music in music_by_id}

        listens = []
        for row in plays:
            music = music_by_id.get(row.id)
            if music is None:
                continue
            listened_at = int(row.end_date.timestamp())
            listens.append(
                {
                    "listened_at": listened_at,
                    "track_metadata": _listen_metadata(
                        music,
                        row.origin_url or music.origin_url,
                    ),
                }
            )

        timestamps = [listen["listened_at"] for listen in listens]
        return Response(
            {
                "payload": {
                    "count": len(listens),
                    "listens": listens,
                    "latest_listen_ts": max(timestamps, default=0),
                    "oldest_listen_ts": min(timestamps, default=0),
                },
            },
            status=HTTP.OK,
        )


def _shift_months(month_start, months):
    """Move a first-of-the-month datetime by whole months."""
    index = month_start.year * 12 + month_start.month - 1 + months
    return month_start.replace(year=index // 12, month=index % 12 + 1)


def _stats_window(range_, now):
    """Return the (start, end) bounds of a statistics range, None when open."""
    if range_ == "all_time":
        return None, None
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week = today - timedelta(days=today.weekday())
    month = today.replace(day=1)
    year = month.replace(month=1)
    quarter = month.replace(month=3 * ((month.month - 1) // 3) + 1)
    half = month.replace(month=1 if month.month <= 6 else 7)  # noqa: PLR2004
    return {
        "this_week": (week, now),
        "this_month": (month, now),
        "this_year": (year, now),
        "week": (week - timedelta(days=7), week),
        "month": (_shift_months(month, -1), month),
        "quarter": (_shift_months(quarter, -3), quarter),
        "half_yearly": (_shift_months(half, -6), half),
        "year": (_shift_months(year, -12), year),
    }[range_]


def _stats_query(request, username):
    """Validate a statistics request.

    Returns (range, start, end, now), or an error Response to send back.
    """
    if username.lower() != request.user.username.lower():
        return _error("User not found.", status=HTTP.NOT_FOUND)
    range_ = request.query_params.get("range") or DEFAULT_STATS_RANGE
    if range_ not in STATS_RANGES:
        return _error(f"Invalid range. Must be one of: {', '.join(STATS_RANGES)}.")
    now = datetime.now(tz=UTC)
    return (range_, *_stats_window(range_, now), now)


def _plays_in(user, start, end):
    """Return the user's plays in [start, end) as (entry id, end_date) pairs."""
    rows = _user_play_rows(user)
    if start is not None:
        rows = rows.filter(end_date__gte=start)
    if end is not None:
        rows = rows.filter(end_date__lt=end)
    return set(rows.values_list("id", "end_date"))


def _entries_for(user, plays):
    """Load the music entries behind a set of plays, keyed by id."""
    entries = Music.objects.filter(
        user=user,
        id__in={entry_id for entry_id, _ in plays},
    ).select_related("item", "artist", "album__artist", "track")
    return {entry.id: entry for entry in entries}


def _entry_artist(music):
    """Return the entry's artist, falling back to its album's artist."""
    return music.artist or (music.album.artist if music.album else None)


def _artist_fields(music):
    """Return the artist fields repeated on album and recording stats."""
    artist = _entry_artist(music)
    mbid = _mbid(artist.musicbrainz_id) if artist else None
    return {
        "artist_mbids": [mbid] if mbid else [],
        "artist_name": artist.name if artist else "",
    }


def _entry_genres(music):
    """Return a play's genres: its track's, else its album's, else its artist's."""
    artist = _entry_artist(music)
    for genres in (
        getattr(music.track, "genres", None),
        getattr(music.album, "genres", None),
        getattr(artist, "genres", None),
    ):
        names = normalize_genres(genres)
        if names:
            return list(dict.fromkeys(name.lower() for name in names))
    return []


class _UserStatsView(drf_views.APIView):
    """Shared body of the `stats/user/<username>/<entity>` endpoints.

    Ranks the token owner's plays like ListenBrainz does. Subclasses name the
    payload keys and say which entity a play counts towards.
    """

    authentication_classes = [ListenBrainzTokenAuthentication]
    entity = ""
    total_key = ""
    name_field = ""

    def describe(self, music):
        """Return (key, fields) of the entity a play counts towards, or None."""
        raise NotImplementedError

    def get(self, request, username):
        """Return one page of the ranking for the requested range."""
        query = _stats_query(request, username)
        if isinstance(query, Response):
            return query
        range_, start, end, now = query

        params = request.query_params
        page = {"count": DEFAULT_STATS_PAGE_SIZE, "offset": 0}
        for name in list(page):
            if params.get(name) in (None, ""):
                continue
            page[name] = _optional_int(params, name)
            if page[name] is None:
                return _error(f"{name} must be an integer.")
        count, offset = page["count"], page["offset"]
        if count < 1 or offset < 0:
            return _error("count must be positive and offset not negative.")
        count = min(count, MAX_STATS_PAGE_SIZE)

        plays = _plays_in(request.user, start, end)
        entries = _entries_for(request.user, plays)
        ranked = {}
        for entry_id, listens in Counter(entry_id for entry_id, _ in plays).items():
            music = entries.get(entry_id)
            described = self.describe(music) if music else None
            if described is None:
                continue
            key, fields = described
            stat = ranked.setdefault(key, {**fields, "listen_count": 0})
            stat["listen_count"] += listens
        ranking = sorted(
            ranked.values(),
            key=lambda stat: (-stat["listen_count"], stat[self.name_field].lower()),
        )
        page = ranking[offset : offset + count]

        first_play = min((end_date for _, end_date in plays), default=now)
        return Response(
            {
                "payload": {
                    self.entity: page,
                    "count": len(page),
                    "offset": offset,
                    "range": range_,
                    f"total_{self.total_key}_count": len(ranking),
                    "from_ts": int((start or first_play).timestamp()),
                    "to_ts": int((end or now).timestamp()),
                    "last_updated": int(now.timestamp()),
                    "user_id": request.user.username,
                },
            },
            status=HTTP.OK,
        )


def _stats_parameters(entity):
    """OpenAPI parameters shared by the user statistics endpoints."""
    return [
        OpenApiParameter(
            name="username",
            type=str,
            location=OpenApiParameter.PATH,
            description="The token owner's Floppy username.",
        ),
        OpenApiParameter(
            name="range",
            type=str,
            location=OpenApiParameter.QUERY,
            required=False,
            enum=list(STATS_RANGES),
            description=f"Time range of the statistics (default {DEFAULT_STATS_RANGE}).",
        ),
        OpenApiParameter(
            name="count",
            type=int,
            location=OpenApiParameter.QUERY,
            required=False,
            description=(
                f"Maximum {entity} to return (default {DEFAULT_STATS_PAGE_SIZE}, "
                f"at most {MAX_STATS_PAGE_SIZE})."
            ),
        ),
        OpenApiParameter(
            name="offset",
            type=int,
            location=OpenApiParameter.QUERY,
            required=False,
            description=f"Number of top {entity} to skip.",
        ),
    ]


def _stats_schema(operation_id, entity, serializer):
    """OpenAPI description of one user statistics endpoint."""
    return extend_schema_view(
        get=extend_schema(
            operation_id=operation_id,
            summary=f"Get top {entity} for a user (ListenBrainz-compatible)",
            description=(
                f"Ranks the token owner's {entity} by recorded plays, in "
                "ListenBrainz's response shape, so clients that build "
                "recommendations from ListenBrainz statistics can read them from "
                "Floppy. A range without plays returns an empty ranking."
            ),
            parameters=_stats_parameters(entity),
            responses={
                200: serializer,
                400: ListenBrainzErrorSerializer,
                401: DetailErrorSerializer,
                404: ListenBrainzErrorSerializer,
            },
        )
    )


@_stats_schema(
    "getListenBrainzUserArtists", "artists", ListenBrainzUserArtistsSerializer
)
class UserArtistsView(_UserStatsView):
    """ListenBrainz `stats/user/<username>/artists` endpoint."""

    entity = "artists"
    total_key = "artist"
    name_field = "artist_name"

    def describe(self, music):
        """Count a play towards its artist."""
        artist = _entry_artist(music)
        if artist is None:
            return None
        return artist.id, {
            "artist_mbid": _mbid(artist.musicbrainz_id),
            "artist_name": artist.name,
        }


@_stats_schema(
    "getListenBrainzUserReleaseGroups",
    "release groups",
    ListenBrainzUserReleaseGroupsSerializer,
)
class UserReleaseGroupsView(_UserStatsView):
    """ListenBrainz `stats/user/<username>/release-groups` endpoint."""

    entity = "release_groups"
    total_key = "release_group"
    name_field = "release_group_name"

    def describe(self, music):
        """Count a play towards its album's release group."""
        album = music.album
        if album is None:
            return None
        release_group = _mbid(album.musicbrainz_release_group_id)
        return release_group or f"album:{album.id}", {
            **_artist_fields(music),
            "release_group_mbid": release_group,
            "release_group_name": album.title,
            "caa_id": None,
            "caa_release_mbid": _mbid(album.musicbrainz_release_id),
        }


@_stats_schema(
    "getListenBrainzUserRecordings", "recordings", ListenBrainzUserRecordingsSerializer
)
class UserRecordingsView(_UserStatsView):
    """ListenBrainz `stats/user/<username>/recordings` endpoint."""

    entity = "recordings"
    total_key = "recording"
    name_field = "track_name"

    def describe(self, music):
        """Count a play towards its recording."""
        track, album = music.track, music.album
        return f"track:{track.id}" if track else f"item:{music.item_id}", {
            **_artist_fields(music),
            "recording_mbid": _mbid(track.musicbrainz_recording_id) if track else None,
            "release_mbid": _mbid(album.musicbrainz_release_id) if album else None,
            "release_name": album.title if album else None,
            "track_name": track.title if track else music.item.title,
        }


@extend_schema_view(
    get=extend_schema(
        operation_id="getListenBrainzUserGenreActivity",
        summary="Get genre activity for a user (ListenBrainz-compatible)",
        description=(
            "Counts the token owner's plays per genre and hour of the day. A "
            "play's genres are its track's, else its album's, else its artist's."
        ),
        parameters=_stats_parameters("genres")[:2],
        responses={
            200: ListenBrainzGenreActivitySerializer,
            400: ListenBrainzErrorSerializer,
            401: DetailErrorSerializer,
            404: ListenBrainzErrorSerializer,
        },
    )
)
class UserGenreActivityView(drf_views.APIView):
    """ListenBrainz `stats/user/<username>/genre-activity` endpoint."""

    authentication_classes = [ListenBrainzTokenAuthentication]

    def get(self, request, username):
        """Return play counts per genre and local hour of the day."""
        query = _stats_query(request, username)
        if isinstance(query, Response):
            return query
        _range, start, end, _now = query

        plays = _plays_in(request.user, start, end)
        entries = _entries_for(request.user, plays)
        activity = Counter()
        for entry_id, end_date in plays:
            music = entries.get(entry_id)
            if music is None:
                continue
            hour = timezone.localtime(end_date).hour
            for genre in _entry_genres(music):
                activity[genre, hour] += 1

        return Response(
            {
                "result": [
                    {"genre": genre, "hour": hour, "listen_count": listens}
                    for (genre, hour), listens in sorted(
                        activity.items(),
                        key=lambda item: (-item[1], item[0]),
                    )
                ],
            },
            status=HTTP.OK,
        )


@extend_schema_view(
    post=extend_schema(
        operation_id="submitListenBrainzListens",
        summary="Submit listens (ListenBrainz-compatible)",
        description=(
            "Accepts scrobbles from any ListenBrainz-compatible client. "
            "Authenticate with `Authorization: Token <your API token>`. "
            "`playing_now` submissions are accepted but not recorded."
        ),
        request={
            "application/json": {
                "type": "object",
                "required": ["listen_type", "payload"],
                "properties": {
                    "listen_type": {
                        "type": "string",
                        "enum": list(_LISTEN_TYPES),
                    },
                    "payload": {"type": "array", "items": {"type": "object"}},
                },
            },
        },
        responses={
            200: ListenBrainzStatusSerializer,
            400: ListenBrainzErrorSerializer,
            401: DetailErrorSerializer,
            403: ListenBrainzErrorSerializer,
        },
    )
)
class SubmitListensView(drf_views.APIView):
    """ListenBrainz `submit-listens` endpoint."""

    authentication_classes = [ListenBrainzTokenAuthentication]

    def post(self, request):
        """Validate a submission and record its listens."""
        data = request.data
        if not isinstance(data, dict):
            return _error("JSON document must be a single object.")

        listen_type = data.get("listen_type")
        if listen_type not in _LISTEN_TYPES:
            return _error(
                f"Invalid listen_type. Must be one of: {', '.join(_LISTEN_TYPES)}.",
            )

        payload = data.get("payload")
        if not isinstance(payload, list):
            return _error("JSON document must contain a 'payload' list.")

        if len(payload) > MAX_LISTENS_PER_SUBMISSION:
            return _error(
                f"Too many listens in one submission "
                f"(maximum {MAX_LISTENS_PER_SUBMISSION}).",
            )

        if listen_type == "single" and len(payload) != 1:
            return _error(
                "Submission of type 'single' must contain exactly one listen."
            )

        # Accept and drop now-playing pings: recording one would mean creating
        # catalog rows for a track the user may never finish.
        if listen_type == "playing_now":
            return Response({"status": "ok"}, status=HTTP.OK)

        if not getattr(request.user, "music_enabled", False):
            return _error(
                "Music tracking is disabled for this account.",
                status=HTTP.FORBIDDEN,
            )

        if not payload:
            return Response({"status": "ok"}, status=HTTP.OK)

        stats = ListenBrainzScrobbleProcessor().process_listens(payload, request.user)
        self._refresh_statistics(request.user, stats["affected_day_keys"])

        logger.info(
            "ListenBrainz submission for %s: processed=%s skipped=%s errors=%s",
            request.user.username,
            stats["processed"],
            stats["skipped"],
            stats["errors"],
        )
        return Response({"status": "ok"}, status=HTTP.OK)

    def _refresh_statistics(self, user, day_keys):
        """Invalidate cached statistics for the affected days."""
        if not day_keys:
            return
        try:
            from app import statistics_cache

            statistics_cache.invalidate_statistics_days(
                user.id,
                day_values=list(day_keys),
                reason="listenbrainz_submission",
            )
            statistics_cache.schedule_all_ranges_refresh(user.id)
        except Exception:
            logger.exception(
                "Failed to refresh statistics after ListenBrainz submission"
            )


@extend_schema_view(
    get=extend_schema(
        operation_id="validateListenBrainzToken",
        summary="Validate token (ListenBrainz-compatible)",
        description=(
            "Reports whether the supplied token is valid. ListenBrainz clients call "
            "this on startup to confirm the connection."
        ),
        responses={200: ListenBrainzTokenSerializer, 401: DetailErrorSerializer},
    )
)
class ValidateTokenView(drf_views.APIView):
    """ListenBrainz `validate-token` endpoint."""

    authentication_classes = [ListenBrainzTokenAuthentication]

    def get(self, request):
        """Confirm the presented token is valid."""
        return Response(
            {
                "code": int(HTTP.OK),
                "message": "Token valid.",
                "valid": True,
                "user_name": request.user.username,
            },
            status=HTTP.OK,
        )
