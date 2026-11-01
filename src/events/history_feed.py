"""Finished plays for the watch history calendar link."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.apps import apps
from django.utils import timezone

from app.models import (
    Anime,
    BoardGame,
    Book,
    Comic,
    ComicIssue,
    Episode,
    Game,
    Manga,
    MediaTypes,
    Movie,
    MoviePlay,
    Music,
    Podcast,
    Status,
    Video,
    VideoPlay,
)

# How far back the link reaches. A calendar app polls the link, and a decade of
# plays would make every poll build and ship thousands of events.
HISTORY_FEED_DAYS = 365

# A play carries one verb, so a calendar entry reads "Watched: Dune".
HISTORY_VERBS = {
    MediaTypes.TV.value: "Watched",
    MediaTypes.MOVIE.value: "Watched",
    MediaTypes.ANIME.value: "Watched",
    MediaTypes.MANGA.value: "Read",
    MediaTypes.GAME.value: "Played",
    MediaTypes.BOOK.value: "Read",
    MediaTypes.COMIC.value: "Read",
    MediaTypes.COMIC_ISSUE.value: "Read",
    MediaTypes.BOARDGAME.value: "Played",
    MediaTypes.MUSIC.value: "Listened to",
    MediaTypes.PODCAST.value: "Listened to",
    MediaTypes.VIDEO.value: "Watched",
}

# Types whose plays are one entry per finished record, dated by its end date.
# Music and podcasts keep every listen in their history table, and videos keep
# a row per viewing, so those are read separately below.
_ENTRY_MODELS = {
    MediaTypes.ANIME.value: Anime,
    MediaTypes.MANGA.value: Manga,
    MediaTypes.GAME.value: Game,
    MediaTypes.BOOK.value: Book,
    MediaTypes.COMIC.value: Comic,
    MediaTypes.COMIC_ISSUE.value: ComicIssue,
    MediaTypes.BOARDGAME.value: BoardGame,
}

_LISTEN_MODELS = {
    MediaTypes.MUSIC.value: Music,
    MediaTypes.PODCAST.value: Podcast,
}

# Plays that come in bulk (every song, every podcast episode) start switched
# off, so the link does not bury a calendar until the user asks for them.
DEFAULT_OFF_MEDIA_TYPES = frozenset(
    {
        MediaTypes.MUSIC.value,
        MediaTypes.PODCAST.value,
        MediaTypes.VIDEO.value,
        MediaTypes.COMIC_ISSUE.value,
    },
)

NO_MEDIA_TYPES = "none"
HISTORY_MEDIA_TYPES = tuple(HISTORY_VERBS)
DEFAULT_MEDIA_TYPES = tuple(
    media_type
    for media_type in HISTORY_MEDIA_TYPES
    if media_type not in DEFAULT_OFF_MEDIA_TYPES
)


@dataclass(frozen=True)
class HistoryPlay:
    """One finished play, ready to become a calendar entry."""

    uid: str
    summary: str
    played_at: datetime

    @property
    def is_date_only(self):
        """Whether the play has a day but no time.

        Date-only plays are stored at local midnight, so that moment is read
        as "no time known" and becomes an all-day entry.
        """
        local = timezone.localtime(self.played_at)
        return not (
            local.hour or local.minute or local.second or local.microsecond
        )

    @property
    def local_date(self):
        """The day the play is filed under."""
        return timezone.localtime(self.played_at).date()


def selected_history_media_types(requested):
    """Return the media types the link includes.

    No selection means the defaults, and "none" (what the page sends when every
    switch is off) means an empty calendar. Unknown values are ignored, and a
    selection that holds only unknown values falls back to the defaults.
    """
    valid = [value for value in requested if value in HISTORY_VERBS]
    if valid:
        return tuple(valid)
    if NO_MEDIA_TYPES in requested:
        return ()
    return DEFAULT_MEDIA_TYPES


def _item_fields(prefix):
    """Item columns a summary reads (its name includes season and episode)."""
    return [
        f"{prefix}__{field}"
        for field in ("title", "season_number", "episode_number")
    ]


def _summary(media_type, item):
    return f"{HISTORY_VERBS[media_type]}: {item}"


def _episode_plays(user, since):
    episodes = (
        Episode.all_objects.filter(
            related_season__user=user,
            end_date__isnull=False,
            end_date__gte=since,
            status=Status.COMPLETED.value,
        )
        .select_related("item", "related_season__item")
        .only(
            "id",
            "end_date",
            *_item_fields("item"),
            *_item_fields("related_season__item"),
        )
    )
    for episode in episodes:
        item = episode.item or episode.related_season.item
        yield HistoryPlay(
            uid=f"episode-{episode.id}",
            summary=_summary(MediaTypes.TV.value, item),
            played_at=episode.end_date,
        )


def _movie_plays(user, since):
    # A movie watched twice has two plays. Its own end date is the latest of
    # them, so it only stands in for a movie that has no play rows.
    plays = (
        MoviePlay.objects.filter(
            movie__user=user,
            end_date__isnull=False,
            end_date__gte=since,
        )
        .select_related("movie__item")
        .only("id", "end_date", *_item_fields("movie__item"))
    )
    for play in plays:
        yield HistoryPlay(
            uid=f"movieplay-{play.id}",
            summary=_summary(MediaTypes.MOVIE.value, play.movie.item),
            played_at=play.end_date,
        )

    movies = (
        Movie.objects.filter(
            user=user,
            end_date__isnull=False,
            end_date__gte=since,
            status=Status.COMPLETED.value,
            plays__isnull=True,
        )
        .select_related("item")
        .only("id", "end_date", *_item_fields("item"))
    )
    for movie in movies:
        yield HistoryPlay(
            uid=f"movie-{movie.id}",
            summary=_summary(MediaTypes.MOVIE.value, movie.item),
            played_at=movie.end_date,
        )


def _entry_plays(user, media_type, since):
    entries = (
        _ENTRY_MODELS[media_type]
        .objects.filter(
            user=user,
            end_date__isnull=False,
            end_date__gte=since,
            status=Status.COMPLETED.value,
        )
        .select_related("item")
        .only("id", "end_date", *_item_fields("item"))
    )
    for entry in entries:
        yield HistoryPlay(
            uid=f"{media_type}-{entry.id}",
            summary=_summary(media_type, entry.item),
            played_at=entry.end_date,
        )


def _listen_plays(user, media_type, since):
    """Every listen of a song or podcast, not just the latest one.

    Playing a track again moves the entry's own end date and keeps the earlier
    listens as rows in its history table, so those rows are the plays. Saving
    an entry for another reason (a new score) repeats a row with the same end
    date, which is one listen, not two.
    """
    model = _LISTEN_MODELS[media_type]
    historical = apps.get_model("app", f"Historical{model.__name__}")
    titles = {
        entry.id: entry.item
        for entry in model.objects.filter(user=user)
        .select_related("item")
        .only("id", *_item_fields("item"))
    }
    rows = (
        historical.objects.filter(
            id__in=list(titles),
            end_date__isnull=False,
            end_date__gte=since,
        )
        .order_by("history_id")
        .values_list("history_id", "id", "end_date")
    )
    seen = set()
    for history_id, entry_id, end_date in rows:
        if (entry_id, end_date) in seen:
            continue
        seen.add((entry_id, end_date))
        yield HistoryPlay(
            uid=f"{media_type}-{history_id}",
            summary=_summary(media_type, titles[entry_id]),
            played_at=end_date,
        )


def _video_plays(user, since):
    plays = (
        VideoPlay.objects.filter(
            video__user=user,
            end_date__gte=since,
        )
        .select_related("video__item")
        .only("id", "end_date", *_item_fields("video__item"))
    )
    for play in plays:
        yield HistoryPlay(
            uid=f"videoplay-{play.id}",
            summary=_summary(MediaTypes.VIDEO.value, play.video.item),
            played_at=play.end_date,
        )

    # A video from before viewings were recorded only has its own end date.
    videos = (
        Video.objects.filter(
            user=user,
            end_date__isnull=False,
            end_date__gte=since,
            status=Status.COMPLETED.value,
            plays__isnull=True,
        )
        .select_related("item")
        .only("id", "end_date", *_item_fields("item"))
    )
    for video in videos:
        yield HistoryPlay(
            uid=f"video-{video.id}",
            summary=_summary(MediaTypes.VIDEO.value, video.item),
            played_at=video.end_date,
        )


def get_history_plays(user, media_types, now=None):
    """Return the user's finished plays for the link, newest first."""
    since = (now or timezone.now()) - timedelta(days=HISTORY_FEED_DAYS)
    plays = []
    for media_type in media_types:
        if media_type == MediaTypes.TV.value:
            plays.extend(_episode_plays(user, since))
        elif media_type == MediaTypes.MOVIE.value:
            plays.extend(_movie_plays(user, since))
        elif media_type == MediaTypes.VIDEO.value:
            plays.extend(_video_plays(user, since))
        elif media_type in _LISTEN_MODELS:
            plays.extend(_listen_plays(user, media_type, since))
        elif media_type in _ENTRY_MODELS:
            plays.extend(_entry_plays(user, media_type, since))
    plays.sort(key=lambda play: (play.played_at, play.uid), reverse=True)
    return plays
