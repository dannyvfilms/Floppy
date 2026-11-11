# FORK: calendar links, viewer statuses and the episode-event contract the
# native calendar depends on.
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from django.utils import timezone

from app.models import Item, MediaTypes, Season, Sources, Status
from events.models import Event

from .base import FloppyApiTestCase


class CalendarLinksTests(FloppyApiTestCase):
    """GET /calendar/links/."""

    def test_links_carry_the_account_token(self):
        """Release and history URLs are the real per-user ICS downloads."""
        self.client.force_login(self.user1)
        response = self.call_api("get", "api_calendar_links")
        self.assertEqual(response.status_code, HTTP.OK)
        payload = response.json()
        self.assertIn(self.user1.token, payload["release_base_url"])
        self.assertIn(self.user1.token, payload["history_base_url"])
        self.assertTrue(payload["release_base_url"].startswith("http"))
        self.assertNotEqual(payload["release_base_url"], payload["history_base_url"])
        values = {entry["value"] for entry in payload["release_media_types"]}
        self.assertIn("movie", values)
        self.assertNotIn("episode", values)
        self.assertTrue(payload["statuses"])
        self.assertTrue(payload["release_types"])
        self.assertNotIn("tv", payload["filter_statuses_by_type"])
        self.assertIn(payload["week_start_day"], ("monday", "sunday"))
        self.assertEqual(payload["user_id"], self.user1.id)

    def test_other_user_gets_own_token(self):
        """Links never leak another account's token."""
        self.client.force_login(self.user2)
        response = self.call_api("get", "api_calendar_links")
        payload = response.json()
        self.assertIn(self.user2.token, payload["release_base_url"])
        self.assertNotIn(self.user1.token, payload["release_base_url"])

    def test_requires_authentication(self):
        """Anonymous callers are rejected."""
        response = self.call_api("get", "api_calendar_links", headers=self.invalid_auth_headers)
        self.assertEqual(response.status_code, HTTP.FORBIDDEN)


class CalendarEpisodeContractTests(FloppyApiTestCase):
    """A TV episode release reaches the client as an episode of a season."""

    def setUp(self):
        """Create a season item with an episode release this month."""
        super().setUp()
        patcher = patch("app.models.Item.fetch_releases", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.season_item = Item.objects.create(
            media_id="9100",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show - Season 2",
            image="https://example.com/s2.jpg",
            season_number=2,
        )
        Season.objects.create(item=self.season_item, user=self.user1, status=Status.IN_PROGRESS.value)
        self.event = Event.objects.create(
            item=self.season_item,
            content_number=4,
            datetime=timezone.now(),
        )

    def test_episode_event_keeps_season_and_episode_numbers(self):
        """The API rewrites season to episode; the client must see both numbers."""
        response = self.call_api("get", "api_calendar", headers=self.auth_headers)
        results = response.json()["results"]
        match = next(entry for entry in results if entry["id"] == self.event.id)
        self.assertEqual(match["item"]["media_type"], "episode")
        self.assertEqual(match["item"]["season_number"], 2)
        self.assertEqual(match["item"]["episode_number"], 4)
        self.assertEqual(match["content_number"], 4)

    def test_statuses_for_viewer_events(self):
        """Statuses map event ids to the viewer's own tracking status."""
        response = self.call_api("get", "api_calendar_statuses", headers=self.auth_headers)
        self.assertEqual(response.status_code, HTTP.OK)
        statuses = response.json()["statuses"]
        self.assertEqual(statuses[str(self.event.id)], Status.IN_PROGRESS.value)

    def test_statuses_hide_other_users_tracking(self):
        """A user who does not track the item gets no status."""
        response = self.call_api("get", "api_calendar_statuses", headers=self.auth_headers2)
        self.assertNotIn(str(self.event.id), response.json()["statuses"])

    def test_statuses_rejects_bad_dates(self):
        """Malformed dates return 400."""
        response = self.call_api(
            "get",
            "api_calendar_statuses",
            params={"start_date": "nope", "end_date": "nope"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
