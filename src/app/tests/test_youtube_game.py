"""The game YouTube tags on a video, read from its watch page."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings, tag
from django.utils import timezone

from app.models import Item, MediaTypes, Sources, Status, VideoGameTag
from app.services import youtube_game


def _page(*games, icon="GAMING_LOGO", heading="Games"):
    """The slice of ytInitialData that carries the game section."""
    return {
        "engagementPanels": [
            {
                "items": [
                    {
                        "videoAttributesSectionViewModel": {
                            "headerTitle": heading,
                            "videoAttributeViewModels": [
                                {
                                    "videoAttributeViewModel": {
                                        "title": title,
                                        "subtitle": year,
                                        "onTap": {
                                            "innertubeCommand": {
                                                "browseEndpoint": {"browseId": game_id},
                                            },
                                        },
                                    },
                                }
                                for title, year, game_id in games
                            ],
                            "footerButton": {"buttonViewModel": {"iconName": icon}},
                        },
                    },
                ],
            },
        ],
    }


MINECRAFT = ("Minecraft", "2009", "UCQvWX73GQygcwXOTSf_VDVg")


class ExtractGamesTests(TestCase):
    def test_reads_title_year_and_game_id(self):
        self.assertEqual(
            youtube_game.extract_games(_page(MINECRAFT)),
            [{"title": "Minecraft", "game_id": MINECRAFT[2], "year": "2009"}],
        )

    def test_translated_heading_still_matches(self):
        self.assertEqual(
            len(youtube_game.extract_games(_page(MINECRAFT, heading="Spiele"))), 1
        )

    def test_a_section_without_the_gaming_icon_is_not_a_game(self):
        self.assertEqual(
            youtube_game.extract_games(_page(MINECRAFT, icon="MUSIC_LOGO")), []
        )

    def test_a_page_without_a_section_has_no_game(self):
        self.assertEqual(youtube_game.extract_games({"contents": []}), [])


class RefreshGameTagTests(TestCase):
    def setUp(self):
        self.item = Item.objects.create(
            media_id="HQp_b8VHtgI",
            source=Sources.YOUTUBE.value,
            media_type=MediaTypes.VIDEO.value,
            title="A video",
        )

    def _refresh(self, data=None, error=None):
        target = "app.services.youtube_game.fetch_watch_page"
        with patch(target, side_effect=error, return_value=(data, 600)):
            return youtube_game.refresh_game_tag(self.item.pk)

    def test_found(self):
        self.assertEqual(self._refresh(_page(MINECRAFT)), "found")
        tag_row = VideoGameTag.objects.get(item=self.item)
        self.assertEqual((tag_row.game_title, tag_row.game_id), ("Minecraft", MINECRAFT[2]))
        self.assertEqual(tag_row.runtime_seconds, 600)

    def test_runtime_is_read_from_the_requested_video(self):
        html = (
            'var ytInitialPlayerResponse = {"videoDetails":'
            '{"videoId":"HQp_b8VHtgI","lengthSeconds":"1394"}};'
        )
        self.assertEqual(youtube_game._runtime_seconds(html, self.item.media_id), 1394)
        self.assertEqual(youtube_game._runtime_seconds(html, "dQw4w9WgXcQ"), 0)

    def test_untagged_video_is_not_found_not_guessed(self):
        self.assertEqual(self._refresh({"contents": []}), "not_found")
        self.assertEqual(VideoGameTag.objects.get(item=self.item).game_title, "")

    def test_fetch_failure_is_unavailable_and_counts(self):
        err = youtube_game.WatchPageUnavailableError("boom")
        self._refresh(error=err)
        self._refresh(error=err)
        row = VideoGameTag.objects.get(item=self.item)
        self.assertEqual((row.status, row.failures), ("unavailable", 2))

    def test_recovery_after_failure_clears_the_count(self):
        self._refresh(error=youtube_game.WatchPageUnavailableError("boom"))
        self._refresh(_page(MINECRAFT))
        self.assertEqual(VideoGameTag.objects.get(item=self.item).failures, 0)

    def test_other_sources_are_ignored(self):
        self.item.source = Sources.MANUAL.value
        self.item.save()
        self.assertIsNone(self._refresh(_page(MINECRAFT)))
        self.assertFalse(VideoGameTag.objects.exists())

    def test_bad_video_id_never_reaches_the_network(self):
        with self.assertRaises(youtube_game.WatchPageUnavailableError):
            youtube_game.fetch_watch_page("../etc/passwd")


class LookupDueTests(TestCase):
    def setUp(self):
        self.item = Item.objects.create(
            media_id="HQp_b8VHtgI",
            source=Sources.YOUTUBE.value,
            media_type=MediaTypes.VIDEO.value,
            title="A video",
        )

    def _tag(self, status, age, failures=0, runtime_seconds=None):
        VideoGameTag.objects.create(
            item=self.item,
            status=status,
            checked_at=timezone.now() - age,
            failures=failures,
            runtime_seconds=runtime_seconds,
        )

    def test_new_item_is_due(self):
        self.assertTrue(youtube_game.lookup_due(self.item))

    def test_found_is_never_due_again(self):
        self._tag("found", timedelta(days=400), runtime_seconds=600)
        self.assertFalse(youtube_game.lookup_due(self.item))

    def test_backfill_adds_runtime_without_losing_known_game(self):
        self._tag("found", timedelta(days=8))
        VideoGameTag.objects.update(game_title=MINECRAFT[0], game_id=MINECRAFT[2])
        self.assertTrue(youtube_game.lookup_due(self.item))
        with patch.object(youtube_game, "fetch_watch_page", side_effect=youtube_game.WatchPageUnavailableError("offline")):
            self.assertEqual(youtube_game.backfill_due_items(), 1)
        row = VideoGameTag.objects.get(item=self.item)
        self.assertEqual(row.status, "found")
        self.assertIsNone(row.runtime_seconds)
        self.assertFalse(youtube_game.lookup_due(self.item))
        VideoGameTag.objects.update(checked_at=timezone.now() - timedelta(days=1))
        with patch.object(youtube_game, "fetch_watch_page", return_value=({}, 1394)):
            self.assertEqual(youtube_game.backfill_due_items(), 1)
        row.refresh_from_db()
        self.assertEqual((row.status, row.game_title, row.runtime_seconds), ("found", "Minecraft", 1394))
        self.assertFalse(youtube_game.lookup_due(self.item))

    def _play(self, ago):
        from django.contrib.auth import get_user_model

        from app.models import Video, VideoPlay

        user = get_user_model().objects.create_user("viewer", password="x")
        video = Video.objects.create(item=self.item, user=user)
        VideoPlay.objects.create(
            video=video, external_id="p1", end_date=timezone.now() - ago
        )

    def test_not_found_waits_a_week(self):
        self._play(timedelta(days=2))
        self._tag("not_found", timedelta(days=1))
        self.assertFalse(youtube_game.lookup_due(self.item))
        VideoGameTag.objects.update(checked_at=timezone.now() - timedelta(days=8))
        self.assertTrue(youtube_game.lookup_due(self.item))

    def test_not_found_is_not_rechecked_once_nobody_watches_it(self):
        """A tag added long after anyone watched is not worth a weekly fetch, forever."""
        self._play(timedelta(days=45))
        self._tag("not_found", timedelta(days=8))
        self.assertFalse(youtube_game.lookup_due(self.item))
        with patch("app.services.youtube_game.fetch_watch_page") as fetch:
            self.assertEqual(youtube_game.backfill_due_items(), 0)
        fetch.assert_not_called()

    def test_recently_watched_not_found_is_rechecked_by_the_backfill(self):
        self._play(timedelta(days=3))
        self._tag("not_found", timedelta(days=8))
        with patch(
            "app.services.youtube_game.fetch_watch_page", return_value=({}, 0)
        ) as fetch:
            self.assertEqual(youtube_game.backfill_due_items(), 1)
        fetch.assert_called_once_with(self.item.media_id)

    def test_unavailable_backs_off_then_gives_up(self):
        self._tag("unavailable", timedelta(minutes=5), failures=1)
        self.assertFalse(youtube_game.lookup_due(self.item))
        VideoGameTag.objects.update(checked_at=timezone.now() - timedelta(hours=7))
        self.assertTrue(youtube_game.lookup_due(self.item))
        VideoGameTag.objects.update(failures=youtube_game.MAX_FAILURES)
        self.assertFalse(youtube_game.lookup_due(self.item))


@tag("network")
class LiveWatchPageTests(TestCase):
    """Reads YouTube for real: run with `scripts/test.sh --network`."""

    def test_sample_video_is_tagged_minecraft(self):
        games = youtube_game.extract_games(
            youtube_game.fetch_watch_page("HQp_b8VHtgI")[0]
        )
        self.assertEqual(games[0]["title"], "Minecraft")
        self.assertEqual(games[0]["game_id"], MINECRAFT[2])

    def test_untagged_video_has_no_game(self):
        self.assertEqual(
            youtube_game.extract_games(youtube_game.fetch_watch_page("dQw4w9WgXcQ")[0]),
            [],
        )


class WatchedForGameTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user("watcher", password="x")
        self.other = get_user_model().objects.create_user("other", password="x")
        self.game = Item.objects.create(
            media_id="1",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="The Legend of Zelda: Tears of the Kingdom",
            release_datetime=timezone.now().replace(year=2023),
        )

    def _video(self, user, vid, title, year, progress, length, status="found"):
        from app.models import Status, Video

        item, _ = Item.objects.get_or_create(
            media_id=vid,
            source=Sources.YOUTUBE.value,
            media_type=MediaTypes.VIDEO.value,
            defaults={"title": vid},
        )
        VideoGameTag.objects.get_or_create(
            item=item,
            defaults={
                "status": status,
                "game_title": title,
                "release_year": year,
                "checked_at": timezone.now(),
            },
        )
        return Video.objects.create(
            item=item,
            user=user,
            progress=progress,
            length_seconds=length,
            status=Status.IN_PROGRESS.value,
        )

    def test_sums_matching_videos_for_one_user_and_caps_at_runtime(self):
        from app.services import youtube_game_watch as watch

        self._video(self.user, "v1", self.game.title, "2023", 600, 1000)
        self._video(self.user, "v2", self.game.title, "2023", 5000, 1000)
        self._video(self.user, "v3", "Minecraft", "2009", 900, 900)
        self._video(self.other, "v4", self.game.title, "2023", 900, 900)
        self.assertEqual(
            watch.watched_for_game(self.user, self.game),
            {
                "videos": 2, "videos_without_time": 0, "seconds": 1600,
                "hours_label": "26m", "channels": [], "estimated": True,
            },
        )

    def test_splits_watch_time_by_channel(self):
        from app.services import youtube_game_watch as watch

        first = self._video(self.user, "c1", self.game.title, "2023", 750, 1000)
        second = self._video(self.user, "c2", self.game.title, "2023", 250, 1000)
        first.channel = "Alpha"
        first.save()
        second.channel = "Beta"
        second.save()
        channels = watch.watched_for_game(self.user, self.game)["channels"]
        self.assertEqual(
            channels,
            [
                {"name": "Alpha", "seconds": 750, "percent": 75},
                {"name": "Beta", "seconds": 250, "percent": 25},
            ],
        )

    def test_missing_positions_on_incomplete_videos_do_not_add_time(self):
        from app.services import youtube_game_watch as watch

        history = self._video(self.user, "history", self.game.title, "2023", 0, 1800)
        history.channel = "History"
        history.save(update_fields=["channel"])
        summary = watch.watched_for_game(self.user, self.game)
        self.assertEqual(summary["seconds"], 0)
        self.assertEqual(summary["videos_without_time"], 1)
        self.assertEqual(
            summary["channels"],
            [{"name": "History", "seconds": 0, "percent": 0}],
        )

        tracked = self._video(self.user, "tracked", self.game.title, "2023", 30, 0)
        tracked.channel = "Tracked"
        tracked.save(update_fields=["channel"])
        summary = watch.watched_for_game(self.user, self.game)
        self.assertEqual(summary["seconds"], 30)
        self.assertEqual(summary["hours_label"], "30s")
        self.assertEqual(summary["videos_without_time"], 1)
        self.assertEqual(
            summary["channels"],
            [
                {"name": "Tracked", "seconds": 30, "percent": 100},
                {"name": "History", "seconds": 0, "percent": 0},
            ],
        )

    def test_completed_history_uses_published_runtime_when_position_is_missing(self):
        from app.services import youtube_game_watch as watch

        history = self._video(self.user, "imported", self.game.title, "2023", 0, 0)
        history.status = Status.COMPLETED.value
        history.save(update_fields=["status"])
        VideoGameTag.objects.filter(item=history.item).update(runtime_seconds=1394)

        summary = watch.watched_for_game(self.user, self.game)
        self.assertEqual(summary["seconds"], 1394)
        self.assertEqual(summary["videos_without_time"], 0)
        self.assertFalse(summary["estimated"])

    def test_minecraft_youtube_identity_maps_to_java_edition_once(self):
        from app.services import youtube_game_watch as watch

        java = Item.objects.create(
            media_id="121", source=Sources.IGDB.value, media_type=MediaTypes.GAME.value,
            title="Minecraft: Java Edition", release_datetime=timezone.now().replace(year=2011),
        )
        other_edition = Item.objects.create(
            media_id="135400", source=Sources.IGDB.value, media_type=MediaTypes.GAME.value,
            title="Minecraft", release_datetime=timezone.now().replace(year=2016),
        )
        video = self._video(self.user, "minecraft", "Minecraft", "2009", 600, 1000)
        VideoGameTag.objects.filter(item=video.item).update(game_id=MINECRAFT[2])
        self.assertEqual(watch.watched_for_game(self.user, java)["seconds"], 600)
        self.assertIsNone(watch.watched_for_game(self.user, other_edition))

        for vid, title, year, game_id in (
            ("bedrock", "Minecraft: Bedrock Edition", "", "UCqLDGOjU4oxhd9M5hFPjwfw"),
            ("mobile", "Minecraft: Dream it, Build it!", "2011", "UCQLJP2NLGXxEosSEW5vaohQ"),
        ):
            video = self._video(self.user, vid, title, year, 500, 1000)
            VideoGameTag.objects.filter(item=video.item).update(game_id=game_id)
        self.assertEqual(watch.watched_for_game(self.user, other_edition)["seconds"], 1000)

        self._video(self.user, "spinoff", "Minecraft Dungeons", "2020", 900, 1000)
        self.assertEqual(watch.watched_for_game(self.user, java)["videos"], 1)

    def test_wrong_year_and_missing_tags_do_not_match(self):
        from app.services import youtube_game_watch as watch

        self._video(self.user, "v1", self.game.title, "2017", 600, 1000)
        self._video(self.user, "v2", self.game.title, "", 600, 1000, "not_found")
        self.assertIsNone(watch.watched_for_game(self.user, self.game))

    def test_punctuation_and_accents_are_folded(self):
        from app.services import youtube_game_watch as watch

        self.assertEqual(
            watch.normalize_title("Pokémon: Legends Z-A"),
            watch.normalize_title("pokemon legends z a"),
        )


    @override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "game-watch-test"}})
    def test_cached_summary_keeps_channels_and_refreshes_after_writes(self):
        from app.models import VideoGameLink
        from app.services import youtube_game_watch as watch

        with self.captureOnCommitCallbacks(execute=True):
            video = self._video(self.user, "cached", self.game.title, "2023", 0, 0)
            video.channel = "Original"
            video.status = Status.COMPLETED.value
            video.save(update_fields=["channel", "status"])

        with patch.object(watch, "watched_for_game", wraps=watch.watched_for_game) as calculate:
            self.assertEqual(watch.cached_watched_for_game(self.user, self.game)["seconds"], 0)
            self.assertEqual(watch.cached_watched_for_game(self.user, self.game)["seconds"], 0)
            self.assertIsNone(watch.cached_watched_for_game(self.other, self.game))
            self.assertIsNone(watch.cached_watched_for_game(self.other, self.game))
            self.assertEqual(calculate.call_count, 2)

            with self.captureOnCommitCallbacks(execute=True):
                tag = VideoGameTag.objects.get(item=video.item)
                tag.runtime_seconds = 1800
                tag.save(update_fields=["runtime_seconds"])
            self.assertEqual(watch.cached_watched_for_game(self.user, self.game)["seconds"], 1800)

            with self.captureOnCommitCallbacks(execute=True):
                video.channel = "Updated"
                video.save(update_fields=["channel"])
            summary = watch.cached_watched_for_game(self.user, self.game)
            self.assertEqual(summary["channels"], [{"name": "Updated", "seconds": 1800, "percent": 100}])
            self.assertEqual(watch.cached_watched_for_game(self.user, self.game), summary)
            self.assertEqual(calculate.call_count, 4)

            with self.captureOnCommitCallbacks(execute=True):
                VideoGameLink.objects.create(video=video, game_item=None)
            self.assertIsNone(watch.cached_watched_for_game(self.user, self.game))
            self.assertEqual(calculate.call_count, 5)


class BackfillTests(TestCase):
    def test_looks_up_untagged_videos_within_the_limit(self):
        for n in range(3):
            Item.objects.create(
                media_id=f"vid{n:08d}",
                source=Sources.YOUTUBE.value,
                media_type=MediaTypes.VIDEO.value,
                title=f"v{n}",
            )
        target = "app.services.youtube_game.fetch_watch_page"
        with patch(target, return_value=(_page(MINECRAFT), 600)):
            self.assertEqual(youtube_game.backfill_due_items(limit=2), 2)
            self.assertEqual(youtube_game.backfill_due_items(limit=2), 1)
            self.assertEqual(youtube_game.backfill_due_items(limit=2), 0)


class ManualLinkWatchTests(TestCase):
    """A viewer's link overrides YouTube's tag in their own watch time only."""

    def setUp(self):
        """One tagged video watched by two users; one game."""
        from django.contrib.auth import get_user_model

        from app.models import Video, VideoGameLink
        from app.services.youtube_game_watch import watched_for_game

        self.watched = watched_for_game
        self.link_model = VideoGameLink
        users = get_user_model()
        self.me = users.objects.create_user(username="me", password="x")
        self.other = users.objects.create_user(username="other", password="x")
        self.game = Item.objects.create(
            media_id="1", source="igdb", media_type="game", title="Minecraft"
        )
        self.elsewhere = Item.objects.create(
            media_id="2", source="igdb", media_type="game", title="Pong"
        )
        item = Item.objects.create(
            media_id="aaaaaaaaaaa",
            source="youtube",
            media_type="video",
            library_media_type="video",
            title="Let's Play",
        )
        VideoGameTag.objects.create(
            item=item,
            status=VideoGameTag.Status.FOUND,
            game_title="Minecraft",
            checked_at=timezone.now(),
        )
        self.mine = Video.objects.create(
            item=item,
            user=self.me,
            status="In progress",
            progress=600,
            length_seconds=1000,
        )
        Video.objects.create(
            item=item,
            user=self.other,
            status="In progress",
            progress=100,
            length_seconds=1000,
        )

    def test_tag_counts_until_unlinked(self):
        """The tag matches by title; unlinking removes it for that user only."""
        self.assertEqual(self.watched(self.me, self.game)["seconds"], 600)
        self.link_model.objects.create(video=self.mine, game_item=None)
        self.assertIsNone(self.watched(self.me, self.game))
        self.assertEqual(self.watched(self.other, self.game)["seconds"], 100)

    def test_relink_moves_the_time_to_the_other_game(self):
        """A manual link counts for its game and the tag stops counting."""
        self.link_model.objects.create(video=self.mine, game_item=self.elsewhere)
        self.assertIsNone(self.watched(self.me, self.game))
        self.assertEqual(self.watched(self.me, self.elsewhere)["seconds"], 600)
