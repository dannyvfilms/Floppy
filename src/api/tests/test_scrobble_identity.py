"""Regressions for canonical TV episode identities in generic scrobbles."""

from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from api.fork_views_playback import resolve_show_tmdb_id
from api.fork_views_scrobble import _resolve_live_playback_media_id
from app.models import Episode
from integrations.webhooks.generic_scrobble import GenericScrobbleProcessor

from .base import FloppyApiTestCase


class GenericScrobbleIdentityTests(SimpleTestCase):
    """Normalised episode identities are authoritative on the stop path."""

    def setUp(self):
        self.user = Mock()

    @patch.object(GenericScrobbleProcessor, "_should_record", return_value=True)
    @patch.object(GenericScrobbleProcessor, "_process_tv")
    def test_explicit_episode_coordinates_reach_tv_processing(
        self, process_tv, _policy
    ):
        payload = {
            "media_type": "episode",
            "ids": {"tmdb": "1421", "tvdb": "999999"},
            "series_title": "Modern Family",
            "season_number": 2,
            "episode_number": 3,
            "completed": True,
        }
        GenericScrobbleProcessor().process_payload(payload, self.user)
        process_tv.assert_called_once()
        args, kwargs = process_tv.call_args
        self.assertIs(args[0], payload)
        self.assertIs(args[1], self.user)
        self.assertEqual(args[2]["tmdb_id"], "1421")
        self.assertEqual(kwargs, {"season_number": 2, "episode_number": 3})

    @patch("integrations.webhooks.base.app.providers.tmdb.find")
    def test_normalised_tmdb_show_id_prevents_conflicting_external_lookup(self, find):
        ids = {"tmdb_id": "1421", "tvdb_id": "999999", "imdb_id": None}
        result = GenericScrobbleProcessor()._find_tv_media_id(
            ids, series_title="Modern Family", allow_title_fallback=True
        )
        self.assertEqual(result, ("1421", None, None))
        find.assert_not_called()

    @patch.object(GenericScrobbleProcessor, "_should_record", return_value=False)
    @patch.object(GenericScrobbleProcessor, "_process_tv")
    def test_write_policy_still_blocks_tv_processing(self, process_tv, policy):
        payload = {
            "media_type": "episode",
            "ids": {"tmdb": "1421"},
            "season_number": 2,
            "episode_number": 3,
            "completed": True,
        }
        self.assertIsNone(
            GenericScrobbleProcessor().process_payload(payload, self.user)
        )
        policy.assert_called_once()
        process_tv.assert_not_called()

    @patch("integrations.webhooks.base.BaseWebhookProcessor._find_tv_media_id")
    def test_fallback_retains_user_and_transient_error_policy(self, base_resolve):
        ids = {"tmdb_id": None, "tvdb_id": "999999", "imdb_id": None}
        base_resolve.return_value = ("1622", 7, 15)
        result = GenericScrobbleProcessor()._find_tv_media_id(
            ids,
            series_title="Modern Family",
            allow_title_fallback=True,
            season_number=2,
            episode_ids=True,
            user=self.user,
            raise_transient=True,
        )
        self.assertEqual(result, ("1622", 7, 15))
        base_resolve.assert_called_once_with(
            ids,
            series_title="Modern Family",
            allow_title_fallback=True,
            year=None,
            season_number=2,
            episode_ids=True,
            user=self.user,
            raise_transient=True,
            show_ids_only=False,
        )

    @patch.object(GenericScrobbleProcessor, "_should_record", return_value=True)
    @patch.object(GenericScrobbleProcessor, "_process_media")
    def test_movie_keeps_existing_dispatch(self, process_media, _policy):
        payload = {"media_type": "movie", "ids": {"tmdb": "603"}, "completed": True}
        GenericScrobbleProcessor().process_payload(payload, self.user)
        process_media.assert_called_once()
        self.assertEqual(process_media.call_args.args[2]["tmdb_id"], "603")

    @patch.object(GenericScrobbleProcessor, "_process_tv")
    @patch.object(GenericScrobbleProcessor, "_process_media")
    def test_missing_ids_never_dispatches(self, process_media, process_tv):
        payload = {
            "media_type": "episode",
            "ids": {},
            "season_number": 2,
            "episode_number": 3,
            "completed": True,
        }
        self.assertIsNone(
            GenericScrobbleProcessor().process_payload(payload, self.user)
        )
        process_tv.assert_not_called()
        process_media.assert_not_called()


class CanonicalEpisodeWritePathTests(FloppyApiTestCase):
    """Exercise real TV dispatch without making external provider requests."""

    @patch.object(GenericScrobbleProcessor, "_should_record", return_value=True)
    @patch(
        "app.providers.tmdb.tv_with_seasons",
        return_value={"title": "Modern Family", "tvdb_id": "999999"},
    )
    @patch.object(GenericScrobbleProcessor, "_handle_tv_episode")
    @patch(
        "integrations.webhooks.base.app.providers.tmdb.find",
        return_value={
            "tv_results": [{"id": 1421}],
            "tv_episode_results": [
                {"show_id": 1622, "season_number": 7, "episode_number": 15}
            ],
        },
    )
    def test_show_lookup_ignores_colliding_episode_and_preserves_coordinates(
        self, find, handle_episode, seasons, _policy
    ):
        payload = {
            "media_type": "episode",
            "ids": {"tvdb": "999999"},
            "series_title": "Modern Family",
            "season_number": 2,
            "episode_number": 3,
            "completed": True,
        }

        GenericScrobbleProcessor().process_payload(payload, self.user1)

        find.assert_called()
        seasons.assert_called()
        handle_episode.assert_called_once()
        media_id, season, episode = handle_episode.call_args.args[:3]
        self.assertEqual(str(media_id), "1421")
        self.assertEqual((season, episode), (2, 3))

    @patch("integrations.webhooks.base.app.providers.tvdb.episode_by_id")
    @patch("integrations.webhooks.base.app.providers.tmdb.find")
    def test_show_ids_skip_episode_results_and_try_next_id(self, find, episode_by_id):
        find.side_effect = [
            {"tv_episode_results": [{"show_id": 1622}]},
            {"tv_results": [{"id": 1421}]},
        ]
        result = GenericScrobbleProcessor()._find_tv_media_id(
            {"tmdb_id": None, "tvdb_id": "403245", "imdb_id": "tt123"}
        )
        self.assertEqual(result, (1421, None, None))
        self.assertEqual(find.call_count, 2)
        episode_by_id.assert_not_called()

    @patch("integrations.webhooks.base.app.providers.tvdb.episode_by_id")
    @patch("integrations.webhooks.base.app.providers.tmdb.find")
    def test_unresolved_show_id_does_not_resolve_as_episode(self, find, episode_by_id):
        find.return_value = {"tv_episode_results": [{"show_id": 1622}]}
        result = GenericScrobbleProcessor()._find_tv_media_id(
            {"tmdb_id": None, "tvdb_id": "403245", "imdb_id": None}
        )
        self.assertEqual(result, (None, None, None))
        episode_by_id.assert_not_called()

    @patch.object(GenericScrobbleProcessor, "_resolve_tv_by_title", return_value="1421")
    @patch(
        "app.providers.tmdb.find",
        return_value={"tv_episode_results": [{"show_id": 1622}]},
    )
    def test_show_id_miss_uses_existing_title_fallback(self, _find, title):
        result = GenericScrobbleProcessor()._find_tv_media_id(
            {"tmdb_id": None, "tvdb_id": "403245", "imdb_id": None},
            series_title="Silo",
            allow_title_fallback=True,
        )
        self.assertEqual(result, ("1421", None, None))
        title.assert_called_once()

    @patch("app.providers.tmdb.tv_with_seasons")
    @patch("app.providers.tmdb.find")
    def test_completed_scrobble_records_requested_episode(self, find, seasons):
        find.return_value = {
            "tv_results": [{"id": 1001}],
            "tv_episode_results": [
                {"show_id": 1622, "season_number": 7, "episode_number": 15}
            ],
        }
        seasons.return_value = {
            "media_id": "1001",
            "title": "TV Show 1",
            "genres": [],
            "tvdb_id": "403245",
            "season/1": {"episodes": [{"episode_number": 1}]},
        }
        plays = Episode.objects.filter(
            related_season__user=self.user1,
            item__media_id="1001",
            item__season_number=1,
            item__episode_number=1,
        )
        before = plays.count()
        response = self.call_api(
            "post",
            "api_scrobble",
            headers=self.auth_headers,
            payload={
                "action": "stop",
                "media_type": "episode",
                "ids": {"tvdb": "403245"},
                "season_number": 1,
                "episode_number": 1,
                "completed": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(plays.count(), before + 1)
        self.assertFalse(Episode.objects.filter(item__media_id="1622").exists())

    @patch("app.providers.tmdb.find")
    def test_playback_resolvers_use_show_results_and_try_next_id(self, find):
        ids = {"imdb": "tt123", "tvdb": "403245"}
        for resolver in (resolve_show_tmdb_id, _resolve_live_playback_media_id):
            with self.subTest(resolver=resolver.__name__):
                find.side_effect = [
                    {"tv_episode_results": [{"show_id": 1622}]},
                    {
                        "tv_results": [{"id": 1421}],
                        "tv_episode_results": [{"show_id": 1622}],
                    },
                ]
                self.assertEqual(resolver("episode", ids), "1421")
                self.assertEqual(resolver("episode", {"tmdb": "1421"}), "1421")

    @patch(
        "app.providers.tmdb.find",
        return_value={"tv_episode_results": [{"show_id": 1622}]},
    )
    def test_playback_resolvers_reject_episode_only_results(self, _find):
        for resolver in (resolve_show_tmdb_id, _resolve_live_playback_media_id):
            with self.subTest(resolver=resolver.__name__):
                self.assertIsNone(resolver("episode", {"tvdb": "403245"}))
