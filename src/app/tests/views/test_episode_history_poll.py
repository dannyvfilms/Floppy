from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import Episode, Item, MediaTypes, Season, Sources, Status


class EpisodeHistoryPollTests(TestCase):
    """Test the season-page poller that catches up on webhook/scrobble writes."""

    def setUp(self):
        """Create a user and log in, plus a tracked season with one episode."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.season = Season.objects.create(
            item=Item.objects.create(
                media_id="1668",
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                season_number=1,
            ),
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        self.episode_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=1,
        )

    def test_recently_created_episode_history_is_oob_swapped(self):
        """A history row written outside episode_save (e.g. by a webhook) shows up."""
        Episode.objects.create(item=self.episode_item, related_season=self.season)

        response = self.client.get(
            reverse("episode_history_poll", args=[self.season.id]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'id="episode-history-{self.episode_item.id}"',
            html=False,
        )
        self.assertContains(
            response,
            f'id="episode-track-button-{self.episode_item.id}"',
            html=False,
        )
        self.assertContains(response, 'hx-swap-oob="true"', html=False)
        self.assertContains(response, "season-progress-mobile-", html=False)
        self.assertContains(response, "season-progress-desktop-", html=False)

    def test_stale_history_is_not_included(self):
        """History outside the lookback window shouldn't be re-sent every poll."""
        old_entry = Episode.objects.create(
            item=self.episode_item,
            related_season=self.season,
        )
        old_entry.created_at = timezone.now() - timezone.timedelta(minutes=5)
        old_entry.save(update_fields=["created_at"])

        response = self.client.get(
            reverse("episode_history_poll", args=[self.season.id]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            f'id="episode-history-{self.episode_item.id}"',
            html=False,
        )
        self.assertContains(response, "season-progress-mobile-", html=False)

    def test_other_users_season_is_not_accessible(self):
        """The poll endpoint is scoped to the requesting user's own season."""
        other_credentials = {"username": "other", "password": "12345"}
        other_user = get_user_model().objects.create_user(**other_credentials)
        other_season = Season.objects.create(
            item=Item.objects.create(
                media_id="9999",
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                season_number=1,
            ),
            user=other_user,
            status=Status.IN_PROGRESS.value,
        )

        response = self.client.get(
            reverse("episode_history_poll", args=[other_season.id]),
        )

        self.assertEqual(response.status_code, 404)
