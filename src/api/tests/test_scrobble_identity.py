"""Regressions for canonical TV episode identities in generic scrobbles."""

from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from integrations.webhooks.generic_scrobble import GenericScrobbleProcessor


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
            "media_type": "episode", "ids": {"tmdb": "1421"},
            "season_number": 2, "episode_number": 3, "completed": True,
        }
        self.assertIsNone(GenericScrobbleProcessor().process_payload(payload, self.user))
        policy.assert_called_once()
        process_tv.assert_not_called()
