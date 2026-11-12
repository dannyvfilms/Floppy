"""Offline regressions for Kodi episode GUIDs colliding with show IDs."""

from unittest.mock import patch

from django.test import SimpleTestCase

from integrations.webhooks.base import BaseWebhookProcessor
from integrations.webhooks.kodi import KodiWebhookProcessor


class KodiVerifiedShowIdentityTests(SimpleTestCase):
    def setUp(self):
        self.processor = KodiWebhookProcessor()
        self.payload = {
            "mediaType": "episode",
            "tvShowTitle": "Friends",
            "season": 1,
            "episode": 1,
            "uniqueIds": {"tmdb": "39354", "tvdb": "303821"},
            "tvShowUniqueIds": {"tmdb": "1668"},
        }

    def test_show_id_does_not_mix_with_episode_ids(self):
        ids = self.processor._extract_external_ids(self.payload)
        self.assertEqual(
            ids,
            {"tmdb_id": "1668", "tvdb_id": None, "imdb_id": None, "tvmaze_id": None},
        )

    def test_verified_show_is_passed_to_tracking(self):
        ids = self.processor._extract_external_ids(self.payload)
        user = object()
        with (
            patch(
                "integrations.webhooks.kodi.tmdb.tv",
                return_value={"title": "Friends"},
            ),
            patch.object(
                BaseWebhookProcessor, "_process_tv", return_value="persisted"
            ) as save,
        ):
            result = self.processor._process_tv(self.payload, user, ids)
        self.assertEqual(result, "persisted")
        save.assert_called_once_with(
            self.payload,
            user,
            {"tmdb_id": "1668", "tvdb_id": None, "imdb_id": None, "tvmaze_id": None},
            season_number=None,
            episode_number=None,
        )

    def test_contradictory_show_title_fails_closed(self):
        ids = self.processor._extract_external_ids(self.payload)
        with (
            patch(
                "integrations.webhooks.kodi.tmdb.tv",
                return_value={"title": "Up All Night"},
            ),
            patch.object(BaseWebhookProcessor, "_process_tv") as save,
        ):
            result = self.processor._process_tv(self.payload, object(), ids)
        self.assertIsNone(result)
        save.assert_not_called()

    def test_legacy_episode_id_uses_unique_title_instead(self):
        payload = {**self.payload, "tvShowUniqueIds": {}}
        ids = self.processor._extract_external_ids(payload)
        self.assertEqual(ids["tmdb_id"], "39354")
        with (
            patch.object(
                self.processor, "_resolve_tv_by_title", return_value="1668"
            ) as resolve,
            patch(
                "integrations.webhooks.kodi.tmdb.tv",
                return_value={"title": "Friends"},
            ),
            patch.object(
                BaseWebhookProcessor, "_process_tv", return_value="persisted"
            ) as save,
        ):
            result = self.processor._process_tv(payload, object(), ids)
        self.assertEqual(result, "persisted")
        resolve.assert_called_once_with("Friends", season_number=1)
        self.assertEqual(save.call_args.args[2]["tmdb_id"], "1668")

    def test_unresolved_legacy_title_does_not_write(self):
        payload = {**self.payload, "tvShowUniqueIds": {}}
        ids = self.processor._extract_external_ids(payload)
        with (
            patch.object(
                self.processor, "_resolve_tv_by_title", return_value=None
            ),
            patch.object(BaseWebhookProcessor, "_process_tv") as save,
        ):
            result = self.processor._process_tv(payload, object(), ids)
        self.assertIsNone(result)
        save.assert_not_called()
