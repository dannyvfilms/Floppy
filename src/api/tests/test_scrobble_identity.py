"""Regressions for canonical TV episode identities in generic scrobbles."""

from unittest.mock import Mock, patch

from django.test import SimpleTestCase

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
            "tv_episode_results": [
                {"show_id": 1622, "season_number": 7, "episode_number": 15}
            ]
        },
    )
    def test_external_episode_lookup_cannot_override_explicit_coordinates(
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
        self.assertEqual(str(media_id), "1622")
        self.assertEqual((season, episode), (2, 3))
