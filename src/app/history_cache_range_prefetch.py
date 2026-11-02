"""Month-span row loading for repairing many missing History days at once.

``build_history_day`` runs a query bundle per media family per day. When a
month read finds most of its days missing, ``HistoryRangePrefetch`` runs one
bounded query per family over the missing span instead, buckets the rows by
local day in Python, and hands each day exactly the rows its own queries would
have returned. Lookups that do not depend on the day (titles, album maps, play
counts) are loaded once for the whole span.
"""

from collections import defaultdict
from datetime import datetime, timedelta

from django.apps import apps
from django.db import models
from django.utils import timezone

from app.history_cache_utils import (
    _date_from_day_key,
    _localize_datetime,
    _music_history_user_q,
    expand_history_media_types,
    history_deferred_item_fields,
)
from app.history_entry_builders import flat_anime_episode_watches
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

READING_MODELS = {
    MediaTypes.BOOK.value: Book,
    MediaTypes.COMIC.value: Comic,
    MediaTypes.MANGA.value: Manga,
}


def _local_day(value):
    return _localize_datetime(value).date()


def _on_window(win_start, win_end):
    """Rows dated in the window: by end date, else by start date."""
    return models.Q(end_date__gte=win_start, end_date__lt=win_end) | (
        models.Q(end_date__isnull=True)
        & models.Q(start_date__gte=win_start, start_date__lt=win_end)
    )


class HistoryRangePrefetch:
    """Rows for a set of History days, loaded once and bucketed by day."""

    def __init__(self, user, day_keys, logging_style, media_types_by_day):
        """Load every family any of ``day_keys`` may need, once for the span."""
        self.user = user
        self.logging_style = logging_style
        days = sorted(
            {d for d in (_date_from_day_key(key) for key in day_keys) if d},
        )
        self.days = set(days)
        tz = timezone.get_current_timezone()
        self.win_start = timezone.make_aware(
            datetime.combine(days[0], datetime.min.time()), tz,
        )
        self.win_end = timezone.make_aware(
            datetime.combine(days[-1], datetime.min.time()), tz,
        ) + timedelta(days=1)

        wanted = set()
        for media_types in media_types_by_day.values():
            expanded = expand_history_media_types(media_types)
            if expanded is None:
                wanted = None
                break
            wanted |= expanded
        self._wanted = wanted
        self._load()

    def _wants(self, media_type):
        return self._wanted is None or media_type in self._wanted

    def _bucket(self, rows, when):
        by_day = defaultdict(list)
        for row in rows:
            value = when(row)
            if value is not None:
                day = _local_day(value)
                if day in self.days:
                    by_day[day].append(row)
        return by_day

    def _load(self):
        user, win_start, win_end = self.user, self.win_start, self.win_end
        on_window = _on_window(win_start, win_end)
        self.episodes_by_day = {}
        self.episode_titles = {}
        self.movies_by_day = {}
        self.movie_play_map = {}
        self.reading_by_day = {}
        self.anime_by_day = {}
        self.anime_watches = {}
        self.music_by_day = {}
        self.podcasts_by_day = {}
        self.videos_by_day = {}
        self.games_by_day = {}
        self.boardgames_by_day = {}

        if self._wants(MediaTypes.EPISODE.value):
            self._load_episodes(on_window)
        if self._wants(MediaTypes.MOVIE.value):
            self._load_movies(on_window)
        for media_type, model in READING_MODELS.items():
            if self._wants(media_type):
                rows = (
                    model.objects.filter(user=user)
                    .filter(on_window)
                    .select_related("item")
                    .defer(*history_deferred_item_fields("item"))
                )
                self.reading_by_day[media_type] = self._bucket(
                    rows, lambda r: r.end_date or r.start_date,
                )
        if self._wants(MediaTypes.ANIME.value):
            self._load_anime(on_window)
        if self._wants(MediaTypes.MUSIC.value):
            self._load_music()
        if self._wants(MediaTypes.PODCAST.value):
            self._load_podcasts()
        if self._wants(MediaTypes.VIDEO.value):
            rows = (
                VideoPlay.objects.filter(
                    video__user=user, end_date__gte=win_start, end_date__lt=win_end,
                )
                .select_related("video__item")
                .defer(*history_deferred_item_fields("video__item"))
            )
            self.videos_by_day = self._bucket(rows, lambda r: r.end_date)
        self._load_games()

    def _load_episodes(self, on_window):
        rows = list(
            Episode.all_objects.filter(related_season__user=self.user)
            .filter(on_window)
            .select_related(
                "item", "related_season__item", "related_season__related_tv__item",
            )
            .defer(
                *history_deferred_item_fields(
                    "item", "related_season__item", "related_season__related_tv__item",
                ),
            )
            .order_by("-end_date", "-start_date")
        )
        self.episodes_by_day = self._bucket(rows, lambda r: r.end_date or r.start_date)
        keys = []
        for ep in rows:
            item = getattr(ep, "item", None)
            if (
                item
                and item.media_id
                and item.source
                and item.season_number is not None
                and item.episode_number is not None
            ):
                keys.append(
                    (
                        item.media_id,
                        item.source,
                        item.season_number,
                        item.episode_number,
                        item.library_media_type,
                    ),
                )
        if not keys:
            return
        titles = (
            Item.objects.filter(
                media_type=MediaTypes.EPISODE.value,
                media_id__in={k[0] for k in keys},
                source__in={k[1] for k in keys},
                season_number__in={k[2] for k in keys},
                episode_number__in={k[3] for k in keys},
                library_media_type__in={k[4] for k in keys},
            )
            .exclude(title__isnull=True)
            .exclude(title="")
        )
        for item in titles.iterator(chunk_size=500):
            key = (
                item.media_id,
                item.source,
                item.season_number,
                item.episode_number,
                item.library_media_type,
            )
            self.episode_titles.setdefault(key, item.title)

    def _load_movies(self, on_window):
        base = (
            Movie.objects.filter(user=self.user)
            .filter(
                models.Q(end_date__isnull=False) | models.Q(start_date__isnull=False),
            )
            .select_related("item")
            .defer(*history_deferred_item_fields("item"))
        )
        rows = list(base.filter(on_window).order_by("-end_date"))
        self.movies_by_day = self._bucket(rows, lambda r: r.end_date or r.start_date)
        if rows:
            counts = (
                base.filter(
                    item__media_id__in={m.item.media_id for m in rows},
                    item__source__in={m.item.source for m in rows},
                )
                .values("item__media_id", "item__source")
                .annotate(play_count=models.Count("id"))
                .order_by()
            )
            self.movie_play_map = {
                (r["item__media_id"], r["item__source"]): r["play_count"]
                for r in counts
            }

    def _load_anime(self, on_window):
        """Flat anime: records on the day, plus those with change-log activity."""
        HistoricalAnime = apps.get_model("app", "HistoricalAnime")
        history = HistoricalAnime.objects.filter(
            id__in=Anime.objects.filter(user=self.user).values("id"),
        ).filter(
            models.Q(history_date__gte=self.win_start, history_date__lt=self.win_end)
            | models.Q(end_date__gte=self.win_start, end_date__lt=self.win_end),
        )
        history_rows = list(history.values_list("id", "history_date", "end_date"))
        records = list(
            Anime.objects.filter(user=self.user)
            .filter(on_window | models.Q(id__in={row[0] for row in history_rows}))
            .select_related("item")
            .defer(*history_deferred_item_fields("item")),
        )
        by_id = {record.id: record for record in records}
        by_day = defaultdict(dict)
        for record in records:
            value = record.end_date or record.start_date
            if value and _local_day(value) in self.days:
                by_day[_local_day(value)][record.id] = record
        for row_id, history_date, end_date in history_rows:
            for value in (history_date, end_date):
                if value and self.win_start <= value < self.win_end:
                    day = _local_day(value)
                    if day in self.days and row_id in by_id:
                        by_day[day][row_id] = by_id[row_id]
        self.anime_by_day = {day: list(rows.values()) for day, rows in by_day.items()}
        self.anime_watches = flat_anime_episode_watches(records)

    def _load_music(self):
        HistoricalMusic = apps.get_model("app", "HistoricalMusic")
        records = list(
            HistoricalMusic.objects.filter(
                _music_history_user_q(self.user),
                end_date__gte=self.win_start,
                end_date__lt=self.win_end,
            ).values("id", "end_date", "album_id", "track_id"),
        )
        self.music_by_day = self._bucket(records, lambda r: r["end_date"])
        album_ids = {r["album_id"] for r in records if r["album_id"]}
        track_ids = {r["track_id"] for r in records if r["track_id"]}
        music_ids = {r["id"] for r in records if r["id"]}
        self.album_map = {
            a.id: a
            for a in Album.objects.filter(id__in=album_ids).select_related("artist")
        } if album_ids else {}
        self.track_map = {
            t.id: t for t in Track.objects.filter(id__in=track_ids)
        } if track_ids else {}
        self.music_map = {
            m.id: m
            for m in Music.objects.filter(id__in=music_ids, user=self.user)
            .select_related("item", "album", "track")
            .defer(*history_deferred_item_fields("item"))
        } if music_ids else {}
        self.track_durations = {}
        self.album_scores = {}
        if album_ids:
            tracks = Track.objects.filter(
                album_id__in=album_ids, duration_ms__isnull=False,
            ).values("album_id", "title", "duration_ms", "musicbrainz_recording_id")
            for t in tracks.iterator(chunk_size=500):
                self.track_durations[(t["album_id"], t["title"])] = t["duration_ms"]
                if t["musicbrainz_recording_id"]:
                    self.track_durations[("recording", t["musicbrainz_recording_id"])] = (
                        t["duration_ms"]
                    )
            trackers = AlbumTracker.objects.filter(
                user=self.user, album_id__in=album_ids,
            ).values("album_id", "score")
            for tracker in trackers.iterator(chunk_size=500):
                if tracker["score"] is not None:
                    self.album_scores[tracker["album_id"]] = tracker["score"]

    def _load_podcasts(self):
        HistoricalPodcast = apps.get_model("app", "HistoricalPodcast")
        owned = models.Q(history_user=self.user) | models.Q(history_user__isnull=True)
        records = list(
            HistoricalPodcast.objects.filter(
                owned, end_date__gte=self.win_start, end_date__lt=self.win_end,
            ).values_list("id", "start_date", "end_date", "history_id", named=True),
        )
        self.podcasts_by_day = self._bucket(records, lambda r: r.end_date)
        ids = list({r.id for r in records})
        self.podcast_lookup = {}
        self.podcast_counts = {}
        if ids:
            self.podcast_lookup = {
                p.id: p
                for p in Podcast.objects.filter(id__in=ids, user=self.user)
                .select_related("item", "episode", "episode__show", "show")
                .defer(*history_deferred_item_fields("item"))
            }
            self.podcast_counts = {
                row["id"]: row["play_count"]
                for row in HistoricalPodcast.objects.filter(
                    id__in=ids, end_date__isnull=False,
                )
                .filter(owned)
                .values("id")
                .annotate(play_count=models.Count("id"))
            }

    def _load_games(self):
        from app.history_cache_day_builder import _span_may_touch_day

        for media_type, model, attr in (
            (MediaTypes.GAME.value, Game, "games_by_day"),
            (MediaTypes.BOARDGAME.value, BoardGame, "boardgames_by_day"),
        ):
            if not self._wants(media_type):
                continue
            base = model.objects.filter(user=self.user)
            if self.logging_style == "sessions":
                window = (
                    models.Q(end_date__gte=self.win_start, end_date__lt=self.win_end)
                    | (
                        models.Q(end_date__isnull=True)
                        & models.Q(
                            start_date__gte=self.win_start,
                            start_date__lt=self.win_end,
                        )
                    )
                    | (
                        models.Q(end_date__isnull=True)
                        & models.Q(start_date__isnull=True)
                        & models.Q(
                            created_at__gte=self.win_start,
                            created_at__lt=self.win_end,
                        )
                    )
                )
                rows = base.filter(window)
            else:
                rows = _span_may_touch_day(base, self.win_start, self.win_end)
            rows = list(
                rows.select_related("item").defer(*history_deferred_item_fields("item")),
            )
            if self.logging_style == "sessions":
                rows = self._bucket(
                    rows, lambda r: r.end_date or r.start_date or r.created_at,
                )
            setattr(self, attr, rows)

    # Per-day accessors -----------------------------------------------------

    def episodes(self, day):
        """Rows for ``day``."""
        return self.episodes_by_day.get(day, [])

    def movies(self, day):
        """Rows for ``day``."""
        return self.movies_by_day.get(day, [])

    def reading(self, media_type, day):
        """Rows for ``day``."""
        return self.reading_by_day.get(media_type, {}).get(day, [])

    def anime(self, day):
        """Rows for ``day``."""
        return self.anime_by_day.get(day, [])

    def music(self, day):
        """Rows for ``day``."""
        return self.music_by_day.get(day, [])

    def podcasts(self, day):
        """Rows for ``day``."""
        return self.podcasts_by_day.get(day, [])

    def videos(self, day):
        """Rows for ``day``."""
        return self.videos_by_day.get(day, [])

    def games(self, day):
        """Sessions: that day's rows. Repeats: every span row (caller filters)."""
        if self.logging_style == "sessions":
            return self.games_by_day.get(day, [])
        return self.games_by_day

    def boardgames(self, day):
        """As ``games``, for board games."""
        if self.logging_style == "sessions":
            return self.boardgames_by_day.get(day, [])
        return self.boardgames_by_day
