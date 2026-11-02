"""Single-day history payload builder and cache writer."""

import logging
from datetime import datetime, timedelta

from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.db.models.functions import Coalesce, Greatest, Least
from django.utils import formats, timezone

from app import helpers
from app.history_cache_serialization import _serialize_history_day
from app.history_cache_utils import (
    HISTORY_DAY_CACHE_TIMEOUT,
    _date_from_day_key,
    _day_cache_key,
    _day_key_for_date,
    _day_key_from_value,
    _localize_datetime,
    _music_history_user_q,
    _normalize_logging_style,
    _resolve_genres,
    _resolve_music_genres,
    expand_history_media_types,
    history_deferred_item_fields,
    history_entry_sort_key,
)
from app.history_entry_builders import (
    _attach_entry_score,
    _build_episode_entry,
    _build_movie_entry,
    _build_video_play_entry,
    _entry_dates,
    _format_boardgame_plays,
    _format_game_hours,
    _get_music_runtime_minutes,
    _serialize_album,
    _serialize_item,
    _serialize_show,
    flat_anime_episode_entries,
    flat_anime_episode_watches,
)
from app.models import (
    Album,
    AlbumTracker,
    Anime,
    BoardGame,
    Book,
    Comic,
    Episode,
    Game,
    Item,
    Manga,
    MediaTypes,
    Movie,
    Music,
    Podcast,
    Track,
    VideoPlay,
)

logger = logging.getLogger(__name__)


def _span_may_touch_day(queryset, day_start, day_end):
    """Narrow games/boardgames to rows whose play span can reach this day.

    A superset of the exact per-day check the caller still runs: same span
    fallbacks, ordered either way, widened by a day so converting to local
    dates can never push a row out of the window. Without it every repeats
    day loaded the user's whole game library (#1158).
    """
    first = Coalesce("start_date", "end_date", "created_at")
    last = Coalesce("end_date", "start_date", "created_at")
    margin = timedelta(days=1)
    return (
        queryset.filter(progress__gt=0)
        .alias(span_lo=Least(first, last), span_hi=Greatest(first, last))
        .filter(span_lo__lt=day_end + margin, span_hi__gte=day_start - margin)
    )


def history_media_types_by_day(user, day_keys, logging_style):
    """Map each day key to the media types whose rows can reach that day.

    One date-only range query per media family replaces probing every family
    for every missing day. Each family's set is a superset of what
    ``build_history_day`` would find (the window is widened a day each side and
    games/boardgames mark their whole span), so passing it as ``media_types``
    only skips queries that would have returned nothing. Flat anime is always
    included: its episode dates come from the change log.
    """
    days = {}
    for key in day_keys:
        day_date = _date_from_day_key(key)
        if day_date:
            days[day_date] = key
    if not days:
        return {}
    tz = timezone.get_current_timezone()
    margin = timedelta(days=1)
    first, last = min(days), max(days)
    win_start = (
        timezone.make_aware(datetime.combine(first, datetime.min.time()), tz) - margin
    )
    win_end = (
        timezone.make_aware(datetime.combine(last, datetime.min.time()), tz)
        + margin
        + margin
    )
    touched = {key: {MediaTypes.ANIME.value} for key in days.values()}

    def mark(media_type, *values):
        for value in values:
            local = _localize_datetime(value)
            key = local and days.get(local.date())
            if key:
                touched[key].add(media_type)

    def mark_span(media_type, start, end):
        if not start or not end:
            return
        lo, hi = sorted((_localize_datetime(start).date(), _localize_datetime(end).date()))
        for day_date, key in days.items():
            if lo <= day_date <= hi:
                touched[key].add(media_type)

    point = (
        models.Q(end_date__gte=win_start, end_date__lt=win_end)
        | models.Q(start_date__gte=win_start, start_date__lt=win_end)
    )
    for row in Episode.all_objects.filter(related_season__user=user).filter(
        point
    ).values_list("end_date", "start_date"):
        mark(MediaTypes.EPISODE.value, *row)
    for media_type, model in (
        (MediaTypes.MOVIE.value, Movie),
        (MediaTypes.BOOK.value, Book),
        (MediaTypes.COMIC.value, Comic),
        (MediaTypes.MANGA.value, Manga),
    ):
        for row in model.objects.filter(user=user).filter(point).values_list(
            "end_date", "start_date"
        ):
            mark(media_type, *row)
    for row in _music_history_dates(user, win_start, win_end):
        mark(MediaTypes.MUSIC.value, row)
    HistoricalPodcast = apps.get_model("app", "HistoricalPodcast")
    for row in HistoricalPodcast.objects.filter(
        models.Q(history_user=user) | models.Q(history_user__isnull=True),
        end_date__gte=win_start,
        end_date__lt=win_end,
    ).values_list("end_date", flat=True):
        mark(MediaTypes.PODCAST.value, row)
    for row in VideoPlay.objects.filter(
        video__user=user, end_date__gte=win_start, end_date__lt=win_end
    ).values_list("end_date", flat=True):
        mark(MediaTypes.VIDEO.value, row)
    first_dt = Coalesce("start_date", "end_date", "created_at")
    last_dt = Coalesce("end_date", "start_date", "created_at")
    for media_type, model in (
        (MediaTypes.GAME.value, Game),
        (MediaTypes.BOARDGAME.value, BoardGame),
    ):
        rows = (
            model.objects.filter(user=user)
            .alias(span_lo=Least(first_dt, last_dt), span_hi=Greatest(first_dt, last_dt))
            .filter(span_lo__lt=win_end, span_hi__gte=win_start)
            .values_list("start_date", "end_date", "created_at")
        )
        for start, end, created in rows:
            if logging_style == "sessions":
                mark(media_type, start, end, created)
            else:
                mark_span(media_type, start or end or created, end or start or created)
    return {key: touched[key] for key in days.values()}


def _music_history_dates(user, win_start, win_end):
    HistoricalMusic = apps.get_model("app", "HistoricalMusic")
    return HistoricalMusic.objects.filter(
        _music_history_user_q(user),
        end_date__gte=win_start,
        end_date__lt=win_end,
    ).values_list("end_date", flat=True)


def build_history_day(
    user, day_key, logging_style_override=None, media_types=None, prefetch=None
):
    """Build a single history day payload for a user.

    ``prefetch`` (a ``HistoryRangePrefetch``) supplies this day's rows from one
    span-wide load instead of querying them here; the payload is identical.
    """
    if not day_key:
        return None
    logging_style = _normalize_logging_style(logging_style_override, user)
    if isinstance(day_key, str):
        day_date = _date_from_day_key(day_key)
    else:
        day_date = day_key
        day_key = _day_key_for_date(day_date)
    if not day_date:
        return None
    requested_media_types = expand_history_media_types(media_types)
    include_episode = (
        requested_media_types is None or "episode" in requested_media_types
    )
    include_movie = requested_media_types is None or "movie" in requested_media_types
    include_music = requested_media_types is None or "music" in requested_media_types
    include_podcast = (
        requested_media_types is None or "podcast" in requested_media_types
    )
    include_video = requested_media_types is None or "video" in requested_media_types
    include_game = requested_media_types is None or "game" in requested_media_types
    include_boardgame = (
        requested_media_types is None or "boardgame" in requested_media_types
    )

    day_start = timezone.make_aware(
        datetime.combine(day_date, datetime.min.time()),
        timezone.get_current_timezone(),
    )
    day_end = day_start + timedelta(days=1)

    entries = []

    # Episodes
    episodes = (
        Episode.all_objects.filter(related_season__user=user)
        .filter(
            models.Q(end_date__gte=day_start, end_date__lt=day_end)
            | (
                models.Q(end_date__isnull=True)
                & models.Q(start_date__gte=day_start, start_date__lt=day_end)
            ),
        )
        .select_related(
            "item",
            "related_season__item",
            "related_season__related_tv__item",
        )
        .defer(
            *history_deferred_item_fields(
                "item",
                "related_season__item",
                "related_season__related_tv__item",
            ),
        )
        .order_by("-end_date", "-start_date")
        if include_episode
        else Episode.all_objects.none()
    )
    if prefetch:
        episodes = prefetch.episodes(day_date) if include_episode else []
        episode_title_map = prefetch.episode_titles
    else:
        episodes = list(episodes)
        episode_title_map = {}
    if episodes and not prefetch:
        episode_keys = []
        for ep in episodes:
            ep_item = getattr(ep, "item", None)
            if not ep_item:
                continue
            if (
                ep_item.media_id
                and ep_item.source
                and ep_item.season_number is not None
                and ep_item.episode_number is not None
            ):
                episode_keys.append(
                    (
                        ep_item.media_id,
                        ep_item.source,
                        ep_item.season_number,
                        ep_item.episode_number,
                        ep_item.library_media_type,
                    ),
                )
        if episode_keys:
            media_ids = {k[0] for k in episode_keys}
            sources = {k[1] for k in episode_keys}
            season_numbers = {k[2] for k in episode_keys}
            episode_numbers = {k[3] for k in episode_keys}
            library_media_types = {k[4] for k in episode_keys}
            titles_qs = (
                Item.objects.filter(
                    media_type=MediaTypes.EPISODE.value,
                    media_id__in=media_ids,
                    source__in=sources,
                    season_number__in=season_numbers,
                    episode_number__in=episode_numbers,
                    library_media_type__in=library_media_types,
                )
                .exclude(title__isnull=True)
                .exclude(title="")
            )
            for item in titles_qs.iterator(chunk_size=500):
                key = (
                    item.media_id,
                    item.source,
                    item.season_number,
                    item.episode_number,
                    item.library_media_type,
                )
                if key not in episode_title_map:
                    episode_title_map[key] = item.title

    for episode in episodes:
        entry = _build_episode_entry(episode, episode_title_map)
        if entry:
            entries.append(entry)
    # Entries contain serialized data; release the episode model graph before
    # building the other media sections of a busy day.
    del episodes, episode_title_map

    # Movies
    movies_qs = (
        Movie.objects.filter(user=user)
        .filter(
            models.Q(end_date__isnull=False) | models.Q(start_date__isnull=False),
        )
        .select_related("item")
        .defer(*history_deferred_item_fields("item"))
        if include_movie
        else Movie.objects.none()
    )

    if prefetch:
        movies = prefetch.movies(day_date) if include_movie else []
        movie_play_map = prefetch.movie_play_map
    else:
        movies = list(
            movies_qs.filter(
                models.Q(end_date__gte=day_start, end_date__lt=day_end)
                | (
                    models.Q(end_date__isnull=True)
                    & models.Q(start_date__gte=day_start, start_date__lt=day_end)
                ),
            ).order_by("-end_date")
        )
        movie_play_map = {}

    # Play counts only for this day's titles, not the user's whole library.
    if movies and not prefetch:
        movie_play_counts = (
            movies_qs.filter(
                item__media_id__in={movie.item.media_id for movie in movies},
                item__source__in={movie.item.source for movie in movies},
            )
            .values("item__media_id", "item__source")
            .annotate(play_count=models.Count("id"))
            .order_by()
        )
        movie_play_map = {
            (row["item__media_id"], row["item__source"]): row["play_count"]
            for row in movie_play_counts
        }

    for movie in movies:
        entry = _build_movie_entry(movie)
        if not entry:
            continue
        key = (movie.item.media_id, movie.item.source)
        annotated = movie_play_map.get(key)
        repeat_attr = getattr(movie, "repeats", None)
        entry["play_count"] = annotated or repeat_attr or 1
        entries.append(entry)

    # Reading (books, comics, manga) and flat anime — single tracking records
    # anchored on their completion/activity day, mirroring movies. These appear
    # in both logging styles since they have no per-session/repeat semantics.
    for media_type_value, model in (
        (MediaTypes.BOOK.value, Book),
        (MediaTypes.COMIC.value, Comic),
        (MediaTypes.MANGA.value, Manga),
        (MediaTypes.ANIME.value, Anime),
    ):
        if (
            requested_media_types is not None
            and media_type_value not in requested_media_types
        ):
            continue
        record_on_day = models.Q(end_date__gte=day_start, end_date__lt=day_end) | (
            models.Q(end_date__isnull=True)
            & models.Q(start_date__gte=day_start, start_date__lt=day_end)
        )
        day_filter = record_on_day
        if model is Anime:
            # A flat anime's episodes are dated by its change log, so an entry
            # can have episodes on a day its own dates are not on.
            day_filter |= models.Q(
                id__in=apps.get_model("app", "HistoricalAnime")
                .objects.filter(
                    models.Q(history_date__gte=day_start, history_date__lt=day_end)
                    | models.Q(end_date__gte=day_start, end_date__lt=day_end),
                )
                .values("id"),
            )
        if prefetch:
            records = (
                prefetch.anime(day_date)
                if model is Anime
                else prefetch.reading(media_type_value, day_date)
            )
            episode_watches = prefetch.anime_watches if model is Anime else {}
        else:
            records = list(
                model.objects.filter(user=user)
                .filter(day_filter)
                .select_related("item")
                .defer(*history_deferred_item_fields("item"))
            )
            episode_watches = (
                flat_anime_episode_watches(records) if model is Anime else {}
            )
        for record in records:
            item = getattr(record, "item", None)
            if not item:
                continue
            watches = [
                (number, watched_at)
                for number, watched_at in episode_watches.get(record.id, [])
                if day_start <= watched_at < day_end
            ]
            record_date = record.end_date or record.start_date
            if not watches and not (
                record.id not in episode_watches
                and record_date
                and day_start <= record_date < day_end
            ):
                continue
            played_at_local = _localize_datetime(record_date)
            entry = {
                "media_type": media_type_value,
                "item": _serialize_item(item),
                "poster": item.image or settings.IMG_NONE,
                "title": item.title,
                "display_title": item.title,
                "status": record.status,
                "episode_label": None,
                "episode_code": None,
                "played_at_local": played_at_local,
                **_entry_dates(record),
                "runtime_minutes": 0,
                "runtime_display": None,
                "instance_id": record.id,
                "entry_key": f"{media_type_value}-{record.id}",
            }
            _attach_entry_score(entry, record)
            genres = _resolve_genres(item)
            if genres:
                entry["genres"] = genres
            if watches:
                entries.extend(
                    flat_anime_episode_entries(
                        entry,
                        watches,
                        episode_watches[record.id][-1][0],
                    ),
                )
            else:
                entries.append(entry)

    # Music (HistoricalMusic for the day)
    music_history = []
    if include_music and prefetch:
        music_history = prefetch.music(day_date)
    elif include_music:
        HistoricalMusic = apps.get_model("app", "HistoricalMusic")
        music_history = list(
            HistoricalMusic.objects.filter(
                _music_history_user_q(user),
                end_date__gte=day_start,
                end_date__lt=day_end,
            ).values("id", "end_date", "album_id", "track_id")
        )
    if music_history:
        album_ids = {
            record["album_id"] for record in music_history if record["album_id"]
        }
        track_ids = {
            record["track_id"] for record in music_history if record["track_id"]
        }
        music_ids = {record["id"] for record in music_history if record["id"]}

        if prefetch:
            album_map = prefetch.album_map
            track_map = prefetch.track_map
            music_map = prefetch.music_map
            track_duration_cache = prefetch.track_durations
            album_scores = prefetch.album_scores
        else:
            album_map = (
                {
                    album.id: album
                    for album in Album.objects.filter(id__in=album_ids).select_related(
                        "artist"
                    )
                }
                if album_ids
                else {}
            )
            track_map = (
                {track.id: track for track in Track.objects.filter(id__in=track_ids)}
                if track_ids
                else {}
            )
            music_map = (
                {
                    music.id: music
                    for music in Music.objects.filter(
                        id__in=music_ids, user=user
                    )
                    .select_related("item", "album", "track")
                    .defer(*history_deferred_item_fields("item"))
                }
                if music_ids
                else {}
            )

            track_duration_cache = {}
            if album_ids:
                tracks_qs = Track.objects.filter(
                    album_id__in=album_ids,
                    duration_ms__isnull=False,
                ).values("album_id", "title", "duration_ms", "musicbrainz_recording_id")
                for track_data in tracks_qs.iterator(chunk_size=500):
                    title_key = (track_data["album_id"], track_data["title"])
                    track_duration_cache[title_key] = track_data["duration_ms"]
                    if track_data["musicbrainz_recording_id"]:
                        recording_key = (
                            "recording",
                            track_data["musicbrainz_recording_id"],
                        )
                        track_duration_cache[recording_key] = track_data["duration_ms"]

            album_scores = {}
            if album_ids:
                album_trackers = AlbumTracker.objects.filter(
                    user=user,
                    album_id__in=album_ids,
                ).values("album_id", "score")
                for tracker in album_trackers.iterator(chunk_size=500):
                    if tracker["score"] is not None:
                        album_scores[tracker["album_id"]] = tracker["score"]


        album_groups = {}
        for record in music_history:
            played_at_local = _localize_datetime(record["end_date"])
            if not played_at_local:
                continue
            album_id = record["album_id"]
            track_id = record["track_id"]
            runtime_minutes = 0

            music_entry = music_map.get(record["id"])
            if music_entry:
                runtime_minutes = _get_music_runtime_minutes(
                    music_entry, track_duration_cache
                )
            if not runtime_minutes:
                track = track_map.get(track_id)
                if track and track.duration_ms:
                    runtime_minutes = track.duration_ms // 60000

            group = album_groups.setdefault(
                album_id,
                {
                    "play_times": [],
                    "play_count": 0,
                    "total_runtime_minutes": 0,
                    "latest_play_time": None,
                    "primary_music_id": None,
                },
            )
            group["play_times"].append(played_at_local)
            group["play_count"] += 1
            group["total_runtime_minutes"] += runtime_minutes
            latest_play_time = group["latest_play_time"]
            if latest_play_time is None or played_at_local > latest_play_time:
                group["latest_play_time"] = played_at_local
                group["primary_music_id"] = record["id"]

        for album_id, group in album_groups.items():
            play_times = group["play_times"]
            if not play_times:
                continue
            play_times.sort()
            earliest_time = play_times[0]
            latest_time = play_times[-1]
            if len(play_times) == 1:
                time_range_display = formats.time_format(earliest_time, "g:i A")
            else:
                time_range_display = f"{formats.time_format(earliest_time, 'g:i A')} - {formats.time_format(latest_time, 'g:i A')}"

            album = album_map.get(album_id)
            album_name = album.title if album else "Unknown Album"
            artist_name = (
                album.artist.name if album and album.artist else "Unknown Artist"
            )
            poster = album.image if album and album.image else settings.IMG_NONE
            entry_music = music_map.get(group["primary_music_id"])
            entry_item = entry_music.item if entry_music else None
            track = entry_music.track if entry_music else None
            genres = _resolve_music_genres(
                album=album, artist=album.artist if album else None, track=track
            )
            entry_key = f"{album_id or 'album'}-{day_key}"

            album_score = None
            if album_scores and album_id:
                album_score = album_scores.get(album_id)

            entry = {
                "media_type": MediaTypes.MUSIC.value,
                "item": _serialize_item(entry_item),
                "album": _serialize_album(album),
                "poster": poster,
                "title": album_name,
                "display_title": album_name,
                "artist_name": artist_name,
                "play_count": group["play_count"],
                "time_range_display": time_range_display,
                "episode_label": None,
                "episode_code": None,
                "played_at_local": latest_time,
                **_entry_dates(entry_music),
                "end_date": latest_time,
                "runtime_minutes": group["total_runtime_minutes"],
                "runtime_display": helpers.minutes_to_hhmm(
                    group["total_runtime_minutes"]
                )
                if group["total_runtime_minutes"]
                else None,
                "instance_id": group["primary_music_id"],
                "entry_key": entry_key,
                "score": album_score,
            }
            if genres:
                entry["genres"] = genres
            entries.append(entry)

    # Podcasts (HistoricalPodcast for the day)
    podcast_history_records = []
    if include_podcast and prefetch:
        podcast_history_records = prefetch.podcasts(day_date)
    elif include_podcast:
        HistoricalPodcast = apps.get_model("app", "HistoricalPodcast")
        podcast_history_records = list(
            HistoricalPodcast.objects.filter(
                models.Q(history_user=user) | models.Q(history_user__isnull=True),
                end_date__gte=day_start,
                end_date__lt=day_end,
            )
            .values_list("id", "start_date", "end_date", "history_id", named=True)
            .iterator(chunk_size=500)
        )
    if podcast_history_records:
        podcast_ids = list({record.id for record in podcast_history_records})
        if prefetch:
            podcasts_lookup = prefetch.podcast_lookup
            counts_by_id = {
                podcast_id: prefetch.podcast_counts[podcast_id]
                for podcast_id in podcast_ids
                if podcast_id in prefetch.podcast_counts
            }
        else:
            HistoricalPodcast = apps.get_model("app", "HistoricalPodcast")
            podcasts_lookup = {
                p.id: p
                for p in Podcast.objects.filter(
                    id__in=podcast_ids,
                    user=user,
                )
                .select_related("item", "episode", "episode__show", "show")
                .defer(*history_deferred_item_fields("item"))
            }
            counts_by_id = {
                row["id"]: row["play_count"]
                for row in HistoricalPodcast.objects.filter(
                    id__in=podcast_ids,
                    end_date__isnull=False,
                )
                .filter(
                    models.Q(history_user=user) | models.Q(history_user__isnull=True)
                )
                .values("id")
                .annotate(play_count=models.Count("id"))
            }

        podcast_play_counts = {}
        if podcast_ids:
            for podcast_id, play_count in counts_by_id.items():
                podcast = podcasts_lookup.get(podcast_id)
                if not podcast or not podcast.item:
                    continue
                key = (podcast.item.media_id, podcast.item.source)
                podcast_play_counts[key] = podcast_play_counts.get(key, 0) + play_count

        for history_record in podcast_history_records:
            podcast = podcasts_lookup.get(history_record.id)
            if not podcast or not podcast.item:
                continue

            played_at_local = _localize_datetime(
                getattr(history_record, "end_date", None)
            )
            if not played_at_local:
                continue

            show = (
                podcast.episode.show
                if podcast.episode and podcast.episode.show
                else podcast.show
            )
            show_podcast_uuid = show.podcast_uuid if show else None
            show_slug = (
                show.slug if show and show.slug else (show.title if show else "")
            )
            poster = settings.IMG_NONE
            if show and show.image:
                poster = show.image
            elif podcast.item.image:
                poster = podcast.item.image

            minutes_listened = podcast.progress or 0
            runtime_minutes = podcast.item.runtime_minutes or minutes_listened
            key = (podcast.item.media_id, podcast.item.source)
            play_count = podcast_play_counts.get(key, 1)

            entries.append(
                {
                    "media_type": MediaTypes.PODCAST.value,
                    "item": _serialize_item(podcast.item),
                    "show": _serialize_show(show),
                    "show_podcast_uuid": show_podcast_uuid,
                    "website_url": podcast.episode.website_url
                    if podcast.episode
                    else "",
                    "show_slug": show_slug,
                    "poster": poster,
                    "title": podcast.item.title,
                    "display_title": podcast.item.title,
                    "progress_display": f"{minutes_listened}m",
                    "date_range_display": None,
                    "episode_label": None,
                    "episode_code": None,
                    "played_at_local": played_at_local,
                    **_entry_dates(history_record, added_from=podcast),
                    "runtime_minutes": runtime_minutes,
                    "runtime_display": helpers.minutes_to_hhmm(runtime_minutes)
                    if runtime_minutes
                    else None,
                    "play_count": play_count,
                    "instance_id": podcast.id,
                    "entry_key": str(history_record.history_id),
                },
            )

    # Games / Boardgames
    if logging_style == "sessions":
        games = (
            (
                Game.objects.filter(user=user)
                .filter(
                    models.Q(end_date__gte=day_start, end_date__lt=day_end)
                    | (
                        models.Q(end_date__isnull=True)
                        & models.Q(start_date__gte=day_start, start_date__lt=day_end)
                    )
                    | (
                        models.Q(end_date__isnull=True)
                        & models.Q(start_date__isnull=True)
                        & models.Q(created_at__gte=day_start, created_at__lt=day_end)
                    )
                )
                .select_related("item")
                .defer(*history_deferred_item_fields("item"))
            )
            if include_game
            else Game.objects.none()
        )
        if prefetch:
            games = prefetch.games(day_date) if include_game else []
        else:
            games = games.iterator(chunk_size=500)
        for game in games:
            activity_dt = game.end_date or game.start_date or game.created_at
            played_at_local = _localize_datetime(activity_dt)
            if not played_at_local:
                continue
            runtime_minutes = game.progress or 0
            start_local = (
                _localize_datetime(game.start_date).date() if game.start_date else None
            )
            end_local = (
                _localize_datetime(game.end_date).date()
                if game.end_date
                else played_at_local.date()
            )
            if not start_local:
                start_local = end_local
            date_range_display = f"{formats.date_format(start_local, 'M j')} - {formats.date_format(end_local, 'M j')}"
            genres = _resolve_genres(game.item)
            entry = {
                "media_type": MediaTypes.GAME.value,
                "item": _serialize_item(game.item),
                "poster": game.item.image or settings.IMG_NONE,
                "title": game.item.title,
                "display_title": game.item.title,
                "progress_display": _format_game_hours(runtime_minutes),
                "date_range_display": date_range_display,
                "episode_label": None,
                "episode_code": None,
                "played_at_local": played_at_local,
                **_entry_dates(game),
                "runtime_minutes": runtime_minutes,
                "runtime_display": helpers.minutes_to_hhmm(runtime_minutes)
                if runtime_minutes
                else None,
                "instance_id": game.id,
                "entry_key": str(game.id),
            }
            _attach_entry_score(entry, game)
            if genres:
                entry["genres"] = genres
            entries.append(entry)

        boardgames = (
            (
                BoardGame.objects.filter(user=user)
                .filter(
                    models.Q(end_date__gte=day_start, end_date__lt=day_end)
                    | (
                        models.Q(end_date__isnull=True)
                        & models.Q(start_date__gte=day_start, start_date__lt=day_end)
                    )
                    | (
                        models.Q(end_date__isnull=True)
                        & models.Q(start_date__isnull=True)
                        & models.Q(created_at__gte=day_start, created_at__lt=day_end)
                    )
                )
                .select_related("item")
                .defer(*history_deferred_item_fields("item"))
            )
            if include_boardgame
            else BoardGame.objects.none()
        )
        if prefetch:
            boardgames = prefetch.boardgames(day_date) if include_boardgame else []
        else:
            boardgames = boardgames.iterator(chunk_size=500)
        for boardgame in boardgames:
            activity_dt = (
                boardgame.end_date or boardgame.start_date or boardgame.created_at
            )
            played_at_local = _localize_datetime(activity_dt)
            if not played_at_local:
                continue
            plays = boardgame.progress or 0
            start_local = (
                _localize_datetime(boardgame.start_date).date()
                if boardgame.start_date
                else None
            )
            end_local = (
                _localize_datetime(boardgame.end_date).date()
                if boardgame.end_date
                else played_at_local.date()
            )
            if not start_local:
                start_local = end_local
            date_range_display = f"{formats.date_format(start_local, 'M j')} - {formats.date_format(end_local, 'M j')}"
            progress_display = _format_boardgame_plays(plays)
            genres = _resolve_genres(boardgame.item)
            entry = {
                "media_type": MediaTypes.BOARDGAME.value,
                "item": _serialize_item(boardgame.item),
                "poster": boardgame.item.image or settings.IMG_NONE,
                "title": boardgame.item.title,
                "display_title": boardgame.item.title,
                "progress_display": progress_display,
                "date_range_display": date_range_display,
                "episode_label": None,
                "episode_code": None,
                "played_at_local": played_at_local,
                **_entry_dates(boardgame),
                "runtime_minutes": 0,
                "runtime_display": progress_display,
                "instance_id": boardgame.id,
                "entry_key": str(boardgame.id),
            }
            _attach_entry_score(entry, boardgame)
            if genres:
                entry["genres"] = genres
            entries.append(entry)
    else:
        games = (
            _span_may_touch_day(Game.objects.filter(user=user), day_start, day_end)
            .select_related("item")
            .defer(*history_deferred_item_fields("item"))
            if include_game
            else Game.objects.none()
        )
        if prefetch:
            games = prefetch.games(day_date) if include_game else []
        else:
            games = games.iterator(chunk_size=500)
        for game in games:
            total_minutes = game.progress or 0
            if total_minutes <= 0:
                continue
            start_dt = game.start_date or game.end_date or game.created_at
            end_dt = game.end_date or game.start_date or game.created_at
            if not start_dt or not end_dt:
                continue
            start_local = _localize_datetime(start_dt)
            end_local = _localize_datetime(end_dt)
            if not start_local or not end_local:
                continue
            start_date = start_local.date()
            end_date = end_local.date()
            if start_date > end_date:
                start_date, end_date = end_date, start_date
            if day_date < start_date or day_date > end_date:
                continue
            day_count = (end_date - start_date).days + 1
            base = total_minutes // day_count
            remainder = total_minutes % day_count
            offset = (day_date - start_date).days
            minutes_for_day = base + (1 if offset < remainder else 0)
            date_range_display = f"{formats.date_format(start_date, 'M j')} - {formats.date_format(end_date, 'M j')}"
            total_progress_display = _format_game_hours(total_minutes)
            genres = _resolve_genres(game.item)
            day_dt = timezone.make_aware(
                datetime.combine(day_date, datetime.min.time()),
                timezone.get_current_timezone(),
            )
            entry = {
                "media_type": MediaTypes.GAME.value,
                "item": _serialize_item(game.item),
                "poster": game.item.image or settings.IMG_NONE,
                "title": game.item.title,
                "display_title": game.item.title,
                "progress_display": total_progress_display,
                "date_range_display": date_range_display,
                "episode_label": None,
                "episode_code": None,
                "played_at_local": day_dt,
                **_entry_dates(game),
                "runtime_minutes": minutes_for_day,
                "runtime_display": helpers.minutes_to_hhmm(minutes_for_day)
                if minutes_for_day
                else None,
                "instance_id": game.id,
                "entry_key": f"{game.id}-{day_key}",
            }
            _attach_entry_score(entry, game)
            if genres:
                entry["genres"] = genres
            entries.append(entry)

        boardgames = (
            _span_may_touch_day(
                BoardGame.objects.filter(user=user), day_start, day_end
            )
            .select_related("item")
            .defer(*history_deferred_item_fields("item"))
            if include_boardgame
            else BoardGame.objects.none()
        )
        if prefetch:
            boardgames = prefetch.boardgames(day_date) if include_boardgame else []
        else:
            boardgames = boardgames.iterator(chunk_size=500)
        for boardgame in boardgames:
            total_plays = boardgame.progress or 0
            if total_plays <= 0:
                continue
            start_dt = (
                boardgame.start_date or boardgame.end_date or boardgame.created_at
            )
            end_dt = boardgame.end_date or boardgame.start_date or boardgame.created_at
            if not start_dt or not end_dt:
                continue
            start_local = _localize_datetime(start_dt)
            end_local = _localize_datetime(end_dt)
            if not start_local or not end_local:
                continue
            start_date = start_local.date()
            end_date = end_local.date()
            if start_date > end_date:
                start_date, end_date = end_date, start_date
            if day_date < start_date or day_date > end_date:
                continue
            day_count = (end_date - start_date).days + 1
            base = total_plays // day_count
            remainder = total_plays % day_count
            offset = (day_date - start_date).days
            plays_for_day = base + (1 if offset < remainder else 0)
            date_range_display = f"{formats.date_format(start_date, 'M j')} - {formats.date_format(end_date, 'M j')}"
            total_progress_display = _format_boardgame_plays(total_plays)
            genres = _resolve_genres(boardgame.item)
            day_dt = timezone.make_aware(
                datetime.combine(day_date, datetime.min.time()),
                timezone.get_current_timezone(),
            )
            entry = {
                "media_type": MediaTypes.BOARDGAME.value,
                "item": _serialize_item(boardgame.item),
                "poster": boardgame.item.image or settings.IMG_NONE,
                "title": boardgame.item.title,
                "display_title": boardgame.item.title,
                "progress_display": total_progress_display,
                "date_range_display": date_range_display,
                "episode_label": None,
                "episode_code": None,
                "played_at_local": day_dt,
                **_entry_dates(boardgame),
                "runtime_minutes": 0,
                "runtime_display": _format_boardgame_plays(plays_for_day)
                if plays_for_day
                else None,
                "instance_id": boardgame.id,
                "entry_key": f"{boardgame.id}-{day_key}",
            }
            _attach_entry_score(entry, boardgame)
            if genres:
                entry["genres"] = genres
            entries.append(entry)

    # Videos (one row per play ending on this day)
    if include_video:
        plays = (
            prefetch.videos(day_date)
            if prefetch
            else VideoPlay.objects.filter(
                video__user=user,
                end_date__gte=day_start,
                end_date__lt=day_end,
            )
            .select_related("video__item")
            .defer(*history_deferred_item_fields("video__item"))
        )
        for play in plays:
            entry = _build_video_play_entry(play)
            if entry:
                entries.append(entry)

    if not entries:
        return None

    entries.sort(key=history_entry_sort_key, reverse=True)
    total_minutes = sum(entry["runtime_minutes"] or 0 for entry in entries)
    first_entry_time = entries[0]["played_at_local"]

    return {
        "date": day_date,
        "weekday": formats.date_format(first_entry_time, "l"),
        "date_display": formats.date_format(first_entry_time, "F j, Y"),
        "entries": entries,
        "total_minutes": total_minutes,
        "total_runtime_display": helpers.minutes_to_hhmm(total_minutes)
        if total_minutes
        else "0min",
    }


def _empty_history_day(day_date):
    return {
        "date": day_date,
        "weekday": formats.date_format(day_date, "l"),
        "date_display": formats.date_format(day_date, "F j, Y"),
        "entries": [],
        "total_minutes": 0,
        "total_runtime_display": "0min",
    }


def _cache_history_day_payload(
    user_id: int, logging_style: str, day_key: str, day_payload
):
    cache.set(
        _day_cache_key(user_id, logging_style, day_key),
        _serialize_history_day(day_payload),
        timeout=HISTORY_DAY_CACHE_TIMEOUT,
    )
    return day_payload


def _build_and_cache_history_day(
    user, day_key, logging_style_override=None, media_types=None, prefetch=None
):
    logging_style = _normalize_logging_style(logging_style_override, user)
    normalized_day_key = _day_key_from_value(day_key)
    if not normalized_day_key:
        return None
    day_payload = build_history_day(
        user,
        normalized_day_key,
        logging_style_override=logging_style,
        media_types=media_types,
        prefetch=prefetch,
    )
    if day_payload is None:
        day_payload = _empty_history_day(_date_from_day_key(normalized_day_key))
    return _cache_history_day_payload(
        user.id,
        logging_style,
        normalized_day_key,
        day_payload,
    )
