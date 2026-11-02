import json
import time
from datetime import timedelta
from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from app.models import Game, Item, MediaTypes, Sources
from app.providers import credentials, opencritic
from app.services import opencritic_scores
from app.tasks_opencritic import refresh_item_opencritic_score

REQUEST = "app.providers.services.resilient_request"

GAME_PAYLOAD = {
    "id": 7015,
    "name": "Hades",
    "topCriticScore": 93.2,
    "percentRecommended": 98.4,
    "numTopCriticReviews": 120,
    "tier": "Mighty",
    "url": "https://opencritic.com/game/7015/hades",
}


def _response(payload, status=200, headers=None):
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(payload).encode()
    response.headers.update(headers or {})
    response.url = "https://opencritic-api.p.rapidapi.com/"
    return response


def _fake_api(search_results=None, game=None, headers=None):
    """Answer searches and game lookups like RapidAPI would."""

    def respond(method, url, **kwargs):
        if url.endswith("/game/search"):
            return _response(search_results or [], headers=headers)
        return _response(game or GAME_PAYLOAD, headers=headers)

    return respond


def _game_item(title="Hades", **fields):
    return Item.objects.create(
        media_id=str(Item.objects.count() + 1),
        source=Sources.IGDB.value,
        media_type=MediaTypes.GAME.value,
        title=title,
        image="http://example.com/image.jpg",
        **fields,
    )


def _called_paths(mock_request):
    return [
        call.kwargs["url"].rsplit(".com", 1)[1] for call in mock_request.call_args_list
    ]


@override_settings(OPENCRITIC_API_KEY="test-key")
class OpenCriticRefreshTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_first_refresh_matches_and_stores_scores(self):
        item = _game_item()
        with patch(
            REQUEST, side_effect=_fake_api([{"id": 7015, "name": "Hades"}])
        ) as api:
            result = opencritic_scores.refresh_item(item)

        self.assertEqual(result, "updated")
        self.assertEqual(_called_paths(api), ["/game/search", "/game/7015"])
        self.assertEqual(api.call_args.kwargs["headers"]["X-RapidAPI-Key"], "test-key")
        item.refresh_from_db()
        self.assertEqual(item.opencritic_id, 7015)
        self.assertEqual(item.opencritic_score, 93.2)
        self.assertEqual(item.opencritic_percent_recommended, 98.4)
        self.assertEqual(item.opencritic_tier, "Mighty")
        self.assertEqual(item.opencritic_review_count, 120)
        self.assertEqual(item.opencritic_url, "https://opencritic.com/game/7015/hades")
        self.assertIsNotNone(item.opencritic_checked_at)

    def test_matched_game_is_never_searched_again(self):
        item = _game_item(
            opencritic_id=7015,
            opencritic_checked_at=timezone.now() - timedelta(days=8),
        )
        with patch(REQUEST, side_effect=_fake_api()) as api:
            opencritic_scores.refresh_item(item)

        self.assertEqual(_called_paths(api), ["/game/7015"])

    def test_fresh_scores_are_not_fetched_again(self):
        item = _game_item(opencritic_id=7015, opencritic_checked_at=timezone.now())
        with patch(REQUEST) as api:
            self.assertEqual(opencritic_scores.refresh_item(item), "skipped")
        api.assert_not_called()

    def test_ambiguous_titles_are_left_unmatched(self):
        item = _game_item(title="Doom")
        results = [{"id": 1, "name": "DOOM"}, {"id": 2, "name": "Doom"}]
        with patch(REQUEST, side_effect=_fake_api(results)) as api:
            self.assertEqual(opencritic_scores.refresh_item(item), "unmatched")

        self.assertEqual(_called_paths(api), ["/game/search"])
        item.refresh_from_db()
        self.assertIsNone(item.opencritic_id)
        self.assertIsNotNone(item.opencritic_checked_at)
        self.assertFalse(opencritic_scores.needs_refresh(item))

    @override_settings(OPENCRITIC_API_KEY="")
    def test_no_key_makes_no_requests(self):
        item = _game_item()
        with patch(REQUEST) as api:
            self.assertEqual(opencritic_scores.refresh_item(item), "skipped")
            self.assertFalse(opencritic_scores.queue_refresh(item))
            self.assertEqual(opencritic_scores.backfill(), 0)
        api.assert_not_called()

    def test_missing_scores_reported_as_minus_one_are_stored_empty(self):
        item = _game_item(opencritic_id=9)
        unscored = {**GAME_PAYLOAD, "topCriticScore": -1, "percentRecommended": -1}
        with patch(REQUEST, side_effect=_fake_api(game=unscored)):
            opencritic_scores.refresh_item(item)
        item.refresh_from_db()
        self.assertIsNone(item.opencritic_score)
        self.assertIsNone(item.opencritic_percent_recommended)


@override_settings(OPENCRITIC_API_KEY="test-key")
class OpenCriticQuotaTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_free_tier_search_limit_is_assumed_until_headers_say_otherwise(self):
        with patch(REQUEST, side_effect=_fake_api()) as api:
            for _ in range(opencritic.FREE_TIER_LIMITS[opencritic.QUOTA_SEARCHES]):
                opencritic.search("Hades")
            with self.assertRaises(opencritic.QuotaExhaustedError):
                opencritic.search("Hades")

        self.assertEqual(api.call_count, 25)

    def test_quota_headers_override_the_local_count(self):
        headers = {
            "X-RateLimit-Searches-Remaining": "3999",
            "X-RateLimit-Searches-Reset": "3600",
        }
        with patch(REQUEST, side_effect=_fake_api(headers=headers)):
            opencritic.search("Hades")

        state = opencritic.quota_state(opencritic.QUOTA_SEARCHES)
        self.assertEqual(state["remaining"], 3999)
        self.assertAlmostEqual(state["reset_at"], time.time() + 3600, delta=5)

    def test_zero_remaining_stops_the_next_call(self):
        headers = {"X-RateLimit-Requests-Remaining": "0"}
        with patch(REQUEST, side_effect=_fake_api(headers=headers)) as api:
            opencritic.game(7015)
            with self.assertRaises(opencritic.QuotaExhaustedError):
                opencritic.game(7015)
        self.assertEqual(api.call_count, 1)

    def test_rate_limited_response_marks_quota_spent(self):
        with patch(REQUEST, return_value=_response({}, status=429)):
            with self.assertRaises(opencritic.QuotaExhaustedError):
                opencritic.game(7015)
        self.assertFalse(opencritic.has_quota(opencritic.QUOTA_REQUESTS))

    def test_match_survives_running_out_between_search_and_lookup(self):
        item = _game_item()
        responses = [
            _response(
                [{"id": 7015, "name": "Hades"}],
                headers={"X-RateLimit-Requests-Remaining": "0"},
            ),
        ]
        with patch(REQUEST, side_effect=responses):
            with self.assertRaises(opencritic.QuotaExhaustedError):
                opencritic_scores.refresh_item(item)

        item.refresh_from_db()
        self.assertEqual(item.opencritic_id, 7015)
        self.assertIsNone(item.opencritic_checked_at)


@override_settings(OPENCRITIC_API_KEY="test-key")
class OpenCriticBackfillTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="oc", password="x")

    def _tracked_game(self, title, **fields):
        item = _game_item(title=title, **fields)
        Game.objects.create(item=item, user=self.user, status="Planning")
        return item

    def _set_reset_in(self, seconds, requests_left=200, searches_left=25):
        reset_at = time.time() + seconds
        cache.set(
            opencritic.quota_cache_key(opencritic.QUOTA_REQUESTS),
            {"remaining": requests_left, "reset_at": reset_at},
        )
        cache.set(
            opencritic.quota_cache_key(opencritic.QUOTA_SEARCHES),
            {"remaining": searches_left, "reset_at": reset_at},
        )

    def test_backfill_waits_until_the_hour_before_reset(self):
        self._tracked_game("Hades")
        self._set_reset_in(3 * 60 * 60)
        with patch(REQUEST) as api:
            self.assertEqual(opencritic_scores.backfill(), 0)
        api.assert_not_called()

    def test_backfill_spends_leftover_quota_on_tracked_games_only(self):
        tracked = self._tracked_game("Hades")
        untracked = _game_item(title="Celeste")
        self._set_reset_in(10 * 60)
        with patch(REQUEST, side_effect=_fake_api([{"id": 7015, "name": "Hades"}])):
            self.assertEqual(opencritic_scores.backfill(), 1)

        tracked.refresh_from_db()
        untracked.refresh_from_db()
        self.assertEqual(tracked.opencritic_score, 93.2)
        self.assertIsNone(untracked.opencritic_checked_at)

    def test_backfill_refreshes_matched_games_when_searches_run_out(self):
        unmatched = self._tracked_game("Celeste")
        matched = self._tracked_game(
            "Hades",
            opencritic_id=7015,
            opencritic_checked_at=timezone.now() - timedelta(days=10),
        )
        self._set_reset_in(10 * 60, searches_left=0)
        with patch(REQUEST, side_effect=_fake_api()) as api:
            self.assertEqual(opencritic_scores.backfill(), 1)

        self.assertEqual(_called_paths(api), ["/game/7015"])
        unmatched.refresh_from_db()
        self.assertIsNone(unmatched.opencritic_checked_at)
        matched.refresh_from_db()
        self.assertEqual(matched.opencritic_score, 93.2)


@override_settings(OPENCRITIC_API_KEY="test-key")
class OpenCriticDetailPageTests(TestCase):
    def setUp(self):
        cache.clear()
        credentials = {"username": "oc-view", "password": "12345"}
        self.user = get_user_model().objects.create_user(**credentials)
        self.client.login(**credentials)

    def _get_detail(self, item):
        metadata = {
            "media_id": item.media_id,
            "title": item.title,
            "media_type": MediaTypes.GAME.value,
            "source": Sources.IGDB.value,
            "source_url": "https://www.igdb.com/games/hades",
            "image": "http://example.com/image.jpg",
            "details": {},
            "related": {},
        }
        with patch("app.providers.services.get_media_metadata", return_value=metadata):
            return self.client.get(
                reverse(
                    "media_details",
                    kwargs={
                        "source": Sources.IGDB.value,
                        "media_type": MediaTypes.GAME.value,
                        "media_id": item.media_id,
                        "title": "hades",
                    },
                ),
            )

    def test_stored_score_renders_chip_linking_to_opencritic(self):
        item = _game_item(
            opencritic_id=7015,
            opencritic_score=93.2,
            opencritic_percent_recommended=98.4,
            opencritic_tier="Mighty",
            opencritic_url="https://opencritic.com/game/7015/hades",
            opencritic_checked_at=timezone.now(),
        )
        with patch("app.tasks_opencritic.refresh_item_opencritic_score.delay") as delay:
            response = self._get_detail(item)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "opencritic-logo.svg")
        self.assertContains(response, "https://opencritic.com/game/7015/hades")
        self.assertContains(response, "Mighty")
        self.assertEqual(response.context["opencritic_score"]["score"], 93)
        delay.assert_not_called()

    def test_opening_an_unscored_game_queues_one_refresh(self):
        item = _game_item()
        with patch("app.tasks_opencritic.refresh_item_opencritic_score.delay") as delay:
            response = self._get_detail(item)
            self._get_detail(item)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "opencritic-logo.svg")
        delay.assert_called_once_with(item.id, user_id=self.user.id)


@override_settings(OPENCRITIC_API_KEY="instance-key")
class OpenCriticPersonalKeyTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="oc-own", password="x"
        )
        credentials.set_user("opencritic", self.user, {"api_key": "personal-key"})

    def test_page_refresh_spends_the_viewers_own_key_and_quota(self):
        item = _game_item(opencritic_id=7015)
        with patch(REQUEST, side_effect=_fake_api()) as api:
            refresh_item_opencritic_score(item.id, user_id=self.user.id)

        self.assertEqual(
            api.call_args.kwargs["headers"]["X-RapidAPI-Key"], "personal-key"
        )
        # The instance key's allowance is untouched.
        self.assertEqual(
            opencritic.quota_state(opencritic.QUOTA_REQUESTS)["remaining"],
            opencritic.FREE_TIER_LIMITS[opencritic.QUOTA_REQUESTS],
        )
