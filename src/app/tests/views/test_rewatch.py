import json
from datetime import UTC, date, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Season,
    Sources,
    Status,
)

METADATA_PATH = "app.providers.services.get_media_metadata"

SEASON_METADATA = {
    "episodes": [{"episode_number": 1}, {"episode_number": 2}],
    "max_progress": 2,
    "image": "s.jpg",
    "season/1": {"episodes": [{"episode_number": 1}, {"episode_number": 2}]},
    # An ended show, so finishing its only season finishes the show.
    "details": {"status": "Ended"},
}


@patch(METADATA_PATH, return_value=SEASON_METADATA)
class RewatchViewTests(TestCase):
    """Starting and stopping a rewatch from the tracker."""

    def setUp(self):
        """Log in with a show whose only season has been fully watched."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        tv_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Show",
        )
        self.tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        season_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show",
            season_number=1,
        )
        self.season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.IN_PROGRESS.value,
        )
        for episode_number in (1, 2):
            item = Item.objects.create(
                media_id="123",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title="Show",
                season_number=1,
                episode_number=episode_number,
            )
            with patch(METADATA_PATH, return_value=SEASON_METADATA):
                Episode.objects.create(
                    item=item,
                    related_season=self.season,
                    end_date=datetime(2023, 6, episode_number, tzinfo=UTC),
                )

        # The last play completes the season, which is the state a rewatch
        # starts from.
        self.season.refresh_from_db()
        self.assertEqual(self.season.status, Status.COMPLETED.value)

    def _replay(self, episode_number, end_date):
        """Log another play of an episode that is already watched."""
        item = Item.objects.get(
            media_id="123",
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=episode_number,
        )
        with patch(METADATA_PATH, return_value=SEASON_METADATA):
            return Episode.objects.create(
                item=item,
                related_season=self.season,
                end_date=end_date,
            )

    def test_start_rewatch_reopens_the_season(self, _mock_metadata):
        """Starting a rewatch opens a pass and reopens the season."""
        self.client.post(
            reverse("media_rewatch"),
            data={
                "instance_id": self.season.id,
                "media_type": MediaTypes.SEASON.value,
                "action": "start",
            },
        )

        self.season.refresh_from_db()
        self.assertIsNotNone(self.season.rewatch_started_at)
        self.assertEqual(self.season.status, Status.IN_PROGRESS.value)

    def test_stop_rewatch_closes_the_pass(self, _mock_metadata):
        """Stopping a rewatch clears the pass and restores Completed."""
        self.season.start_rewatch()

        self.client.post(
            reverse("media_rewatch"),
            data={
                "instance_id": self.season.id,
                "media_type": MediaTypes.SEASON.value,
                "action": "stop",
            },
        )

        self.season.refresh_from_db()
        self.assertIsNone(self.season.rewatch_started_at)
        self.assertEqual(self.season.status, Status.COMPLETED.value)

    def test_rewatch_can_start_from_an_earlier_date(self, _mock_metadata):
        """A rewatch already under way is recorded from the day it began."""
        self.client.post(
            reverse("media_rewatch"),
            data={
                "instance_id": self.season.id,
                "media_type": MediaTypes.SEASON.value,
                "action": "start",
                "rewatch_started_at": "2026-08-01",
            },
        )

        self.season.refresh_from_db()
        self.assertEqual(
            timezone.localtime(self.season.rewatch_started_at).date(),
            date(2026, 8, 1),
        )

    def test_backdated_rewatch_counts_the_plays_already_logged(self, _mock_metadata):
        """Episodes replayed before pressing the button belong to the pass."""
        self._replay(1, datetime(2026, 8, 5, 20, 0, tzinfo=UTC))

        self.client.post(
            reverse("media_rewatch"),
            data={
                "instance_id": self.season.id,
                "media_type": MediaTypes.SEASON.value,
                "action": "start",
                "rewatch_started_at": "2026-08-01",
            },
        )

        self.season.refresh_from_db()
        self.assertEqual(self.season.progress, 1)
        self.assertEqual(self.season.next_episode_number(), 2)

    def test_backdated_rewatch_already_fully_replayed_is_rejected(
        self,
        _mock_metadata,
    ):
        """A start date that leaves nothing to rewatch is refused, not silently closed."""
        self._replay(1, datetime(2026, 8, 5, 20, 0, tzinfo=UTC))
        self._replay(2, datetime(2026, 8, 6, 20, 0, tzinfo=UTC))

        response = self.client.post(
            reverse("media_rewatch"),
            data={
                "instance_id": self.season.id,
                "media_type": MediaTypes.SEASON.value,
                "action": "start",
                "rewatch_started_at": "2026-08-01",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.season.refresh_from_db()
        self.assertIsNone(self.season.rewatch_started_at)
        self.assertEqual(self.season.status, Status.COMPLETED.value)

        # A 400 with no HX-Trigger just fails silently in the UI — htmx
        # won't swap an error response, so nothing tells the user why the
        # click did nothing unless the response also triggers a toast.
        trigger = json.loads(response["HX-Trigger"])
        self.assertEqual(trigger["showToast"]["type"], "error")
        self.assertIn("already", trigger["showToast"]["message"].lower())

    def test_show_rewatch_already_fully_replayed_is_rejected(
        self,
        _mock_metadata,
    ):
        """A show whose only season is already fully replayed refuses the pass too."""
        self._replay(1, datetime(2026, 8, 5, 20, 0, tzinfo=UTC))
        self._replay(2, datetime(2026, 8, 6, 20, 0, tzinfo=UTC))

        response = self.client.post(
            reverse("media_rewatch"),
            data={
                "instance_id": self.tv.id,
                "media_type": MediaTypes.TV.value,
                "action": "start",
                "rewatch_started_at": "2026-08-01",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.season.refresh_from_db()
        self.assertIsNone(self.season.rewatch_started_at)
        self.assertEqual(self.season.status, Status.COMPLETED.value)
        self.assertEqual(
            TV.objects.get(pk=self.tv.pk).status,
            Status.COMPLETED.value,
        )

    def test_show_rewatch_warns_about_a_season_it_skipped(self, _mock_metadata):
        """Partially skipping a show-level rewatch still tells the user.

        `start_rewatch` only raises when *every* season is a no-op; here
        season 2 genuinely reopens, so the request succeeds — but without
        this warning, season 1 being left alone would happen with no
        signal to the user at all.
        """
        season_2_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show",
            season_number=2,
        )
        season_2 = Season.objects.create(
            item=season_2_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.IN_PROGRESS.value,
        )
        season_2_episode_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Show",
            season_number=2,
            episode_number=1,
        )
        with patch(METADATA_PATH, return_value=SEASON_METADATA):
            Episode.objects.create(
                item=season_2_episode_item,
                related_season=season_2,
                end_date=datetime(2000, 1, 1, tzinfo=UTC),
            )
        # Season 1 (from setUp) is already fully replayed on the pass date.
        self._replay(1, datetime(2026, 8, 5, 20, 0, tzinfo=UTC))
        self._replay(2, datetime(2026, 8, 6, 20, 0, tzinfo=UTC))

        response = self.client.post(
            reverse("media_rewatch"),
            data={
                "instance_id": self.tv.id,
                "media_type": MediaTypes.TV.value,
                "action": "start",
                "rewatch_started_at": "2026-08-01",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(
            any("Season 1" in m and "left as is" in m for m in messages),
            messages,
        )
        season_2.refresh_from_db()
        self.assertIsNotNone(season_2.rewatch_started_at)

    def test_a_future_start_date_is_rejected(self, _mock_metadata):
        """A pass starting in the future would hide every play, so refuse it."""
        response = self.client.post(
            reverse("media_rewatch"),
            data={
                "instance_id": self.season.id,
                "media_type": MediaTypes.SEASON.value,
                "action": "start",
                "rewatch_started_at": "2099-01-01",
            },
        )

        self.season.refresh_from_db()
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self.season.rewatch_started_at)

    def test_an_unparseable_start_date_is_rejected(self, _mock_metadata):
        """Garbage in the date field must not silently become "now"."""
        response = self.client.post(
            reverse("media_rewatch"),
            data={
                "instance_id": self.season.id,
                "media_type": MediaTypes.SEASON.value,
                "action": "start",
                "rewatch_started_at": "last tuesday",
            },
        )

        self.season.refresh_from_db()
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self.season.rewatch_started_at)

    def test_stop_rewatch_accepts_the_action_from_the_query_string(
        self,
        _mock_metadata,
    ):
        """The modal button carries the action in the URL, like the other actions."""
        self.season.start_rewatch()

        self.client.post(
            f"{reverse('media_rewatch')}?action=stop",
            data={
                "instance_id": self.season.id,
                "media_type": MediaTypes.SEASON.value,
            },
        )

        self.season.refresh_from_db()
        self.assertIsNone(self.season.rewatch_started_at)

    def test_start_rewatch_for_a_show_covers_its_seasons(self, _mock_metadata):
        """Rewatching a show opens a pass on each season."""
        self.client.post(
            reverse("media_rewatch"),
            data={
                "instance_id": self.tv.id,
                "media_type": MediaTypes.TV.value,
                "action": "start",
            },
        )

        self.season.refresh_from_db()
        self.assertIsNotNone(self.season.rewatch_started_at)
        self.assertEqual(
            TV.objects.get(pk=self.tv.pk).status,
            Status.IN_PROGRESS.value,
        )

    def test_another_users_entry_is_not_touched(self, _mock_metadata):
        """A rewatch may only be started on the requester's own entry."""
        other = get_user_model().objects.create_user(username="other", password="x")
        self.client.force_login(other)

        response = self.client.post(
            reverse("media_rewatch"),
            data={
                "instance_id": self.season.id,
                "media_type": MediaTypes.SEASON.value,
                "action": "start",
            },
        )

        self.season.refresh_from_db()
        self.assertIsNone(self.season.rewatch_started_at)
        self.assertEqual(response.status_code, 404)

    def _track_modal(self):
        """Open the season's track modal."""
        return self.client.get(
            reverse(
                "track_modal",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.SEASON.value,
                    "media_id": "123",
                },
            ),
            {"season_number": 1, "instance_id": self.season.id},
        )

    def test_track_modal_offers_a_start_date_for_a_rewatch(self, _mock_metadata):
        """A rewatch already under way can be dated when it is recorded."""
        response = self._track_modal()

        self.assertContains(response, 'name="rewatch_started_at"')

    def test_track_modal_shows_when_an_open_rewatch_began(self, _mock_metadata):
        """An open pass says which day it started from."""
        self.season.start_rewatch(
            started_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        )

        response = self._track_modal()

        self.assertContains(response, "Rewatching since")

    def _show_track_modal(self):
        """Open the show's own track modal."""
        return self.client.get(
            reverse(
                "track_modal",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.TV.value,
                    "media_id": "123",
                },
            ),
            {"instance_id": self.tv.id},
        )

    def test_show_track_modal_shows_when_an_open_rewatch_began(self, _mock_metadata):
        """A show-level pass also says which day it started from.

        TV has no rewatch_started_at field of its own — the date comes
        from its seasons — so this is worth checking on its own rather
        than assuming the season-level test above covers it.
        """
        self.tv.start_rewatch(started_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC))

        response = self._show_track_modal()

        # "Rewatching since" is a static label rendered whenever a pass is
        # open at all — asserting on it alone would pass even with the date
        # itself missing, which is exactly the bug being checked for here.
        self.assertContains(response, "Rewatching since")
        self.assertContains(response, "Aug")
        self.assertContains(response, "2026")

    def test_track_modal_offers_a_rewatch_for_a_completed_season(self, _mock_metadata):
        """A finished season can be rewatched from its track modal."""
        response = self._track_modal()

        self.assertContains(response, reverse("media_rewatch"))
        self.assertContains(response, "Rewatch")

    def test_track_modal_offers_to_end_an_open_rewatch(self, _mock_metadata):
        """An open pass can be ended from the same place it was started."""
        self.season.start_rewatch()

        response = self._track_modal()

        self.assertContains(response, "End rewatch")

    def test_track_modal_hides_rewatch_for_an_unfinished_season(self, _mock_metadata):
        """A season still being watched for the first time is not a rewatch."""
        Season.objects.filter(pk=self.season.pk).update(
            status=Status.IN_PROGRESS.value,
        )

        response = self._track_modal()

        self.assertNotContains(response, reverse("media_rewatch"))


class RewatchRatingVisibility(TestCase):
    """The episode rating stays reachable while a rewatch is under way."""

    def setUp(self):
        """Build the episode payload a season page renders mid-pass."""
        with patch(METADATA_PATH, return_value=SEASON_METADATA):
            self.user = get_user_model().objects.create_user(username="t", password="x")
            tv_item = Item.objects.create(
                media_id="123",
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                title="Show",
            )
            tv = TV.objects.create(item=tv_item, user=self.user)
            season_item = Item.objects.create(
                media_id="123",
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                title="Show",
                season_number=1,
            )
            self.season = Season.objects.create(
                item=season_item,
                user=self.user,
                related_tv=tv,
                status=Status.IN_PROGRESS.value,
            )
            self.episode_item = Item.objects.create(
                media_id="123",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title="Show",
                season_number=1,
                episode_number=1,
            )
            self.play = Episode.objects.create(
                item=self.episode_item,
                related_season=self.season,
                end_date=datetime(2023, 6, 1, tzinfo=UTC),
                score=8,
            )

    def _payload(self, history, all_history):
        """Mimic one entry of what process_episodes() hands the template."""
        return {
            "media_id": "123",
            "media_type": MediaTypes.EPISODE.value,
            "source": Sources.TMDB.value,
            "season_number": 1,
            "episode_number": 1,
            "item": self.episode_item,
            "history": history,
            "all_history": all_history,
            "unwatched_score": None,
        }

    def _render(self, episode_payload):
        return render_to_string(
            "app/components/detail_row_actions.html",
            {
                "episode": episode_payload,
                "action_media_type": MediaTypes.EPISODE.value,
                "track_button_variant": "row",
                "current_instance": self.season,
                "history_item": self.episode_item,
                "user": self.user,
                "MediaTypes": MediaTypes,
                "media_type": MediaTypes.SEASON.value,
            },
        )

    def _render_card_rating(self, episode_payload):
        """Render the season episode card, where its rating control now lives."""
        return render_to_string(
            "app/components/episode_card_rating.html",
            {
                "episode": episode_payload,
                "current_instance": self.season,
                "user": self.user,
                "MediaTypes": MediaTypes,
                "public_view": False,
            },
        )

    def test_rating_is_offered_for_an_episode_not_yet_replayed(self):
        """A past score remains available when the current pass has no play."""
        html = self._render_card_rating(self._payload([], [self.play]))

        self.assertIn('aria-label="Rate"', html)
        self.assertIn("initialRating: 8", html)

    def test_row_renders_no_leaked_template_comment(self):
        """A `{# #}` comment only spans one line; a longer one renders as text."""
        html = self._render(self._payload([], [self.play]))

        self.assertNotIn("{#", html)

    def test_unwatched_episode_offers_an_empty_card_rating(self):
        """An untouched episode offers a blank rating, never an invented score."""
        html = self._render_card_rating(self._payload([], []))

        self.assertIn('aria-label="Rate"', html)
        self.assertIn("initialRating: null", html)

    def _render_chip(self, episode_payload):
        return render_to_string(
            "app/components/detail_episode_rating_chip.html",
            {
                "episode": episode_payload,
                "current_instance": self.season,
                "user": self.user,
                "source": Sources.TMDB.value,
                "media_id": "123",
                "season_number": 1,
                "episode_number": 1,
                "public_view": False,
            },
        )

    def test_episode_page_chip_is_offered_for_an_episode_not_yet_replayed(self):
        """The standalone episode page's chip also survives a mid-pass gap."""
        html = self._render_chip(self._payload([], [self.play]))

        self.assertIn("Edit rating", html)

    def test_episode_page_chip_is_hidden_for_an_episode_never_watched(self):
        """An untouched episode still offers no chip to add a rating from."""
        html = self._render_chip(self._payload([], []))

        self.assertNotIn("Edit rating", html)
        self.assertNotIn("Add rating", html)


@patch(METADATA_PATH, return_value=SEASON_METADATA)
class EpisodePageDuringRewatch(TestCase):
    """The episode page and the season page agree on the current pass."""

    def setUp(self):
        """Watch one episode, then reopen the season for a rewatch."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        with patch(METADATA_PATH, return_value=SEASON_METADATA):
            tv_item = Item.objects.create(
                media_id="123",
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                title="Show",
            )
            tv = TV.objects.create(item=tv_item, user=self.user)
            season_item = Item.objects.create(
                media_id="123",
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                title="Show",
                season_number=1,
            )
            self.season = Season.objects.create(
                item=season_item,
                user=self.user,
                related_tv=tv,
                status=Status.IN_PROGRESS.value,
            )
            episode_item = Item.objects.create(
                media_id="123",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title="Show",
                season_number=1,
                episode_number=1,
            )
            Episode.objects.create(
                item=episode_item,
                related_season=self.season,
                end_date=datetime(2023, 6, 1, tzinfo=UTC),
            )

    @patch("app.providers.tmdb.process_episodes", return_value=[])
    def test_episode_page_scopes_plays_to_the_open_pass(
        self,
        mock_process_episodes,
        _mock_metadata,
    ):
        """Without the season, the page would contradict the season page."""
        self.season.start_rewatch()

        self.client.get(
            reverse(
                "episode_details",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_id": "123",
                    "title": "show",
                    "season_number": 1,
                    "episode_number": 1,
                },
            ),
        )

        seasons_passed = [
            call.kwargs.get("season") for call in mock_process_episodes.call_args_list
        ]
        self.assertIn(self.season, seasons_passed)


@patch(METADATA_PATH, return_value=SEASON_METADATA)
class HistoryModalEditing(TestCase):
    """Past plays stay editable while a rewatch hides them from the season page."""

    def setUp(self):
        """Track one episode, watched twice."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        with patch(METADATA_PATH, return_value=SEASON_METADATA):
            tv_item = Item.objects.create(
                media_id="123",
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                title="Show",
            )
            tv = TV.objects.create(item=tv_item, user=self.user)
            season_item = Item.objects.create(
                media_id="123",
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                title="Show",
                season_number=1,
            )
            self.season = Season.objects.create(
                item=season_item,
                user=self.user,
                related_tv=tv,
                status=Status.IN_PROGRESS.value,
            )
            self.episode_item = Item.objects.create(
                media_id="123",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title="Show",
                season_number=1,
                episode_number=1,
            )
            self.old_play = Episode.objects.create(
                item=self.episode_item,
                related_season=self.season,
                end_date=datetime(2023, 6, 1, tzinfo=UTC),
            )

    def _history_modal(self):
        return self.client.get(
            reverse(
                "history_modal",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.EPISODE.value,
                    "media_id": "123",
                    "season_number": 1,
                    "episode_number": 1,
                },
            ),
        )

    def test_each_entry_offers_to_edit_the_play_it_belongs_to(self, _mock_metadata):
        """A play is reachable for editing from its own timeline entry."""
        response = self._history_modal()

        self.assertContains(response, f"instance_id={self.old_play.id}")
        self.assertContains(response, "Edit")

    def test_entries_stay_editable_during_a_rewatch(self, _mock_metadata):
        """An open pass hides the play elsewhere, but not from its history."""
        self.season.start_rewatch()

        response = self._history_modal()

        self.assertContains(response, f"instance_id={self.old_play.id}")
