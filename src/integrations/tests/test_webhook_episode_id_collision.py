"""An episode's TVDB id can equal an unrelated series' TVDB id (#1312).

Jellyfin and Emby send the episode's own TVDB id. TMDB's find answers with a
bare show when no episode carries that id but some series does, so the mark
was filed under the wrong show and dropped (or saved on it). These tests use
the payload and TMDB answers from the #1312 log.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from app import live_playback
from app.models import Episode
from app.providers import tmdb
from integrations.webhooks.base import BaseWebhookProcessor
from integrations.webhooks.emby import EmbyWebhookProcessor
from integrations.webhooks.jellyfin import JellyfinWebhookProcessor

NEWSRADIO_ID = "3968"
OTHER_ID = "3786"
COLLIDING_TVDB_ID = "83349"


def _season(season_number, episode_count):
    return {
        "season_number": season_number,
        "image": "https://example.com/season.jpg",
        "episodes": [
            {
                "episode_number": number,
                "runtime": 22,
                "air_date": None,
                "still_path": None,
                "name": f"Episode {number}",
                "overview": "",
            }
            for number in range(1, episode_count + 1)
        ],
    }


def _show(media_id, title, tvdb_id, episode_count):
    return {
        "media_id": media_id,
        "title": title,
        "image": "https://example.com/show.jpg",
        "tvdb_id": tvdb_id,
        "provider_external_ids": {"tmdb_id": media_id, "tvdb_id": tvdb_id},
        "season/3": _season(3, episode_count),
    }


def _find(external_id, external_type):
    """TMDB knows 83349 only as an unrelated show's series id."""
    if (str(external_id), external_type) == (COLLIDING_TVDB_ID, "tvdb_id"):
        return {
            "tv_episode_results": [],
            "tv_results": [{"id": int(OTHER_ID), "name": "Some Unrelated Show"}],
        }
    return {"tv_episode_results": [], "tv_results": []}


class EpisodeIdCollisionTests(TestCase):
    """Marks and unmarks land on the show named in the payload."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="collision-user",
            token="collision-token",
        )
        self.user.anime_enabled = False
        self.user.jellyfin_mark_played_enabled = True
        self.user.jellyfin_mark_unplayed_enabled = True
        self.user.save()
        self.other_episodes = 15
        patchers = [
            patch("app.live_playback._attach_resolved_image"),
            patch("app.providers.tmdb.get_tvdb_episode_image_map", return_value={}),
            patch("app.providers.tmdb.find", side_effect=_find),
            patch("app.providers.tmdb.tv_with_seasons", side_effect=self._tv),
            patch(
                "app.providers.tmdb.search",
                return_value={
                    "results": [
                        {
                            "media_id": NEWSRADIO_ID,
                            "title": "NewsRadio",
                            "media_type": "tv",
                        },
                    ],
                },
            ),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(live_playback.clear_user_playback_state, self.user.id)

    def _tv(self, media_id, _seasons, *_args, **_kwargs):
        if str(media_id) == NEWSRADIO_ID:
            return _show(NEWSRADIO_ID, "NewsRadio", "79151", 22)
        return _show(
            OTHER_ID, "Some Unrelated Show", COLLIDING_TVDB_ID, self.other_episodes
        )

    def _toggle(self, episode_number, tvdb_id, *, played=True):
        return {
            "Event": "UserDataSaved",
            "SaveReason": "TogglePlayed",
            "PlaybackPositionTicks": "0",
            "Item": {
                "Type": "Episode",
                "Name": "Kids",
                "SeriesName": "NewsRadio",
                "ParentIndexNumber": 3,
                "IndexNumber": episode_number,
                "ProviderIds": {"Tmdb": "", "Imdb": "", "Tvdb": tvdb_id},
                "UserData": {
                    "Played": played,
                    "LastPlayedDate": "2026-09-25T17:26:19.101Z" if played else "",
                },
            },
        }

    def _plays(self, media_id, episode_number):
        return Episode.objects.filter(
            item__media_id=media_id,
            item__season_number=3,
            item__episode_number=episode_number,
            related_season__user=self.user,
        )

    def test_mark_is_recorded_on_the_real_show_not_dropped(self):
        """The unrelated show has no S03E16, which used to drop the mark."""
        JellyfinWebhookProcessor().process_payload(
            self._toggle(16, COLLIDING_TVDB_ID),
            self.user,
        )

        self.assertEqual(self._plays(NEWSRADIO_ID, 16).count(), 1)
        self.assertFalse(Episode.objects.filter(item__media_id=OTHER_ID).exists())

    def test_mark_and_unmark_never_touch_an_unrelated_show_with_that_episode(self):
        """Here the unrelated show does have an S03E16 to write to or retract."""
        self.other_episodes = 16
        processor = JellyfinWebhookProcessor()

        processor.process_payload(self._toggle(16, COLLIDING_TVDB_ID), self.user)
        self.assertEqual(self._plays(NEWSRADIO_ID, 16).count(), 1)
        self.assertEqual(self._plays(OTHER_ID, 16).count(), 0)

        processor.process_payload(
            self._toggle(16, COLLIDING_TVDB_ID, played=False),
            self.user,
        )
        self.assertEqual(self._plays(NEWSRADIO_ID, 16).count(), 0)
        self.assertEqual(self._plays(OTHER_ID, 16).count(), 0)

    def test_episode_without_a_collision_still_resolves_by_title(self):
        JellyfinWebhookProcessor().process_payload(self._toggle(17, "83350"), self.user)

        self.assertEqual(self._plays(NEWSRADIO_ID, 17).count(), 1)

    def test_episode_tvdb_id_is_not_saved_as_the_shows_tvdb_id(self):
        """That override swaps the show's TVDB link and hides its Specials."""
        JellyfinWebhookProcessor().process_payload(self._toggle(17, "83350"), self.user)

        self.assertIsNone(tmdb.get_tvdb_id_override(NEWSRADIO_ID))

    def test_overrides_saved_before_the_fix_are_ignored(self):
        cache.set(f"tmdb_tvdb_override_{NEWSRADIO_ID}", "83350")

        self.assertIsNone(tmdb.get_tvdb_id_override(NEWSRADIO_ID))

    def test_emby_stop_is_recorded_on_the_real_show(self):
        payload = {
            "Event": "playback.stop",
            "PlaybackInfo": {"PlayedToCompletion": True},
            "Item": {
                "Type": "Episode",
                "Name": "Kids",
                "SeriesName": "NewsRadio",
                "ParentIndexNumber": 3,
                "IndexNumber": 16,
                "ProviderIds": {"Tvdb": COLLIDING_TVDB_ID},
                "UserData": {"Played": True},
            },
        }

        EmbyWebhookProcessor().process_payload(payload, self.user)

        self.assertEqual(self._plays(NEWSRADIO_ID, 16).count(), 1)
        self.assertFalse(Episode.objects.filter(item__media_id=OTHER_ID).exists())


class FindTvMediaIdEpisodeIdsTests(TestCase):
    """`_find_tv_media_id` only trusts a bare show hit for show-level ids."""

    def _lookup(self, **kwargs):
        with patch("app.providers.tmdb.find", side_effect=_find):
            return BaseWebhookProcessor()._find_tv_media_id(
                {"tmdb_id": None, "imdb_id": None, "tvdb_id": COLLIDING_TVDB_ID},
                **kwargs,
            )

    def test_show_level_id_keeps_the_show_hit(self):
        self.assertEqual(self._lookup(), (int(OTHER_ID), None, None))

    def test_episode_level_id_ignores_the_show_hit(self):
        self.assertEqual(self._lookup(episode_ids=True), (None, None, None))

    def test_episode_level_id_still_trusts_an_episode_hit(self):
        response = {
            "tv_episode_results": [
                {"show_id": 3968, "season_number": 3, "episode_number": 16},
            ],
            "tv_results": [{"id": int(OTHER_ID)}],
        }
        with patch("app.providers.tmdb.find", return_value=response):
            result = BaseWebhookProcessor()._find_tv_media_id(
                {"tmdb_id": None, "imdb_id": None, "tvdb_id": COLLIDING_TVDB_ID},
                episode_ids=True,
            )

        self.assertEqual(result, (3968, 3, 16))


class JellyfinRatingIdLevelTests(TestCase):
    """A Series item's ids name the show; an Episode item's name the episode."""

    def _episode_ids_flag(self, item_type):
        payload = {"Item": {"Type": item_type, "SeriesName": "NewsRadio"}}
        processor = JellyfinWebhookProcessor()
        with (
            patch.object(processor, "_find_local_collection_item", return_value=None),
            patch.object(
                processor,
                "_find_tv_media_id",
                return_value=(None, None, None),
            ) as find,
        ):
            processor._resolve_rating_tv_item(payload, {"tvdb_id": "79151"})
        return find.call_args.kwargs["episode_ids"]

    def test_series_rating_keeps_show_level_lookup(self):
        self.assertFalse(self._episode_ids_flag("Series"))

    def test_episode_rating_uses_episode_level_lookup(self):
        self.assertTrue(self._episode_ids_flag("Episode"))
