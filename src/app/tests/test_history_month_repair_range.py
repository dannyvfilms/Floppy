"""A dense month repair loads each media family once for the span, not per day."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from app import history_cache_day_builder as builder
from app.history_cache_range_prefetch import HistoryRangePrefetch
from app.models import (
    TV,
    Album,
    Anime,
    Artist,
    BoardGame,
    Book,
    Episode,
    Game,
    Item,
    MediaTypes,
    Movie,
    Music,
    Podcast,
    PodcastEpisode,
    PodcastShow,
    Season,
    Sources,
    Status,
    Track,
    Video,
)

DAYS = 24


def _item(media_type, media_id, **extra):
    return Item.objects.get_or_create(
        media_id=media_id,
        source=Sources.MANUAL.value,
        media_type=media_type,
        defaults={"title": f"{media_type} {media_id}", "image": "http://example.com/x.jpg"},
        **extra,
    )[0]


class MonthRepairRangeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user = cls.user = get_user_model().objects.create_user(
            username="range-repair", password="12345",
        )
        base = timezone.localtime().replace(
            hour=20, minute=0, second=0, microsecond=0,
        )
        cls.first = (base - timedelta(days=DAYS - 1)).date()
        done = Status.COMPLETED.value
        tv = TV.objects.create(
            item=Item.objects.create(
                media_id="tv", source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value, title="Show",
            ),
            user=user, status=Status.IN_PROGRESS.value,
        )
        season = Season.objects.create(
            item=Item.objects.create(
                media_id="tv", source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value, title="Show", season_number=1,
            ),
            user=user, related_tv=tv, status=Status.IN_PROGRESS.value,
        )
        artist = Artist.objects.create(name="Artist")
        album = Album.objects.create(title="Album", artist=artist)
        track = Track.objects.create(
            album=album, title="Track", track_number=1, duration_ms=180000,
        )
        show = PodcastShow.objects.create(
            podcast_uuid="s", source=Sources.POCKETCASTS.value, title="Pod",
        )
        video = Video.objects.create(
            item=_item(MediaTypes.VIDEO.value, "v1"), user=user, status=done,
        )
        for i in range(DAYS):
            when = base - timedelta(days=i)
            # Every day is dense; every fifth is sparse (movie only).
            Movie.objects.create(
                item=_item(MediaTypes.MOVIE.value, f"m{i % 6}"),
                user=user, status=done, progress=1, end_date=when,
            )
            if i % 5 == 0:
                continue
            Episode.objects.create(
                item=Item.objects.create(
                    media_id="tv", source=Sources.TMDB.value,
                    media_type=MediaTypes.EPISODE.value, title=f"Ep {i}",
                    season_number=1, episode_number=i + 1,
                ),
                related_season=season, end_date=when,
            )
            Book.objects.create(
                item=_item(MediaTypes.BOOK.value, f"b{i}"),
                user=user, status=done, progress=1, end_date=when,
            )
            Anime.objects.create(
                item=_item(MediaTypes.ANIME.value, f"a{i}"),
                user=user, status=done, progress=3, end_date=when,
            )
            Music.objects.create(
                item=_item(MediaTypes.MUSIC.value, f"mu{i}"),
                user=user, album=album, artist=artist, track=track,
                status=done, progress=1, start_date=when, end_date=when,
            )
            ep = PodcastEpisode.objects.create(
                show=show, episode_uuid=f"e{i}", title=f"E{i}",
                published=when, duration=1800,
            )
            Podcast.objects.create(
                item=_item(MediaTypes.PODCAST.value, f"e{i}"),
                user=user, show=show, episode=ep, status=done, progress=30,
                start_date=when, end_date=when,
            )
            video.upsert_play(f"yt:{i}", 60, end_date=when)
            if i % 3 == 0:
                Game.objects.create(
                    item=_item(MediaTypes.GAME.value, f"g{i}"),
                    user=user, status=done, progress=300,
                    start_date=when - timedelta(days=2), end_date=when,
                )
                BoardGame.objects.create(
                    item=_item(MediaTypes.BOARDGAME.value, f"bg{i}"),
                    user=user, status=done, progress=4,
                    start_date=when - timedelta(days=1), end_date=when,
                )
        cls.day_keys = [
            (cls.first + timedelta(days=i)).strftime("%Y%m%d")
            for i in range(DAYS)
        ][:22]

    def setUp(self):
        cache.clear()

    def test_prefetched_days_match_per_day_builds(self):
        for style in ("sessions", "repeats"):
            with self.subTest(style=style):
                by_day = builder.history_media_types_by_day(
                    self.user, self.day_keys, style,
                )
                with CaptureQueriesContext(connection) as per_day:
                    expected = {
                        key: builder.build_history_day(
                            self.user, key, style, media_types=by_day[key],
                        )
                        for key in self.day_keys
                    }
                with CaptureQueriesContext(connection) as ranged:
                    prefetch = HistoryRangePrefetch(
                        self.user, self.day_keys, style, by_day,
                    )
                    actual = {
                        key: builder.build_history_day(
                            self.user, key, style,
                            media_types=by_day[key], prefetch=prefetch,
                        )
                        for key in self.day_keys
                    }
                self.assertEqual(expected, actual)
                self.assertTrue(any(expected.values()))
                self.assertLess(len(ranged), 40)
                self.assertLess(len(ranged) * 3, len(per_day))
