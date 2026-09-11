import calendar
from datetime import UTC, date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app import models as app_models
from app.models import TV, Anime, Item, MediaTypes, Movie, Season, Sources, Status
from events.models import Event, SentinelDatetime


class CalendarViewTests(TestCase):
    """Tests for the calendar views."""

    def setUp(self):
        """Set up test data."""
        self.credentials = {"username": "testuser", "password": "testpassword"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    @patch("events.models.Event.objects.get_user_events")
    @patch.object(get_user_model(), "update_preference")
    def test_calendar_default_view(
        self,
        mock_update_preference,
        mock_get_user_events,
    ):
        """Test the calendar view with default parameters."""
        # Set up mocks
        mock_update_preference.return_value = "month"
        mock_get_user_events.return_value = []

        # Make the request
        response = self.client.get(reverse("calendar"))

        # Check response
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "events/calendar.html")

        # Check that the view called the mocked methods
        mock_update_preference.assert_called_once_with("calendar_layout", None)

        # Get today's date for verification
        today = timezone.localdate()
        first_day = date(today.year, today.month, 1)

        # Calculate last day of the month
        december = 12
        if today.month == december:
            last_day = date(today.year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(today.year, today.month + 1, 1) - timedelta(days=1)

        mock_get_user_events.assert_called_once_with(self.user, first_day, last_day)

        # Check context data
        self.assertEqual(response.context["month"], today.month)
        self.assertEqual(response.context["year"], today.year)
        self.assertEqual(
            response.context["month_name"],
            calendar.month_name[today.month],
        )

        self.assertEqual(response.context["view_type"], "month")
        self.assertEqual(response.context["selected_day"], today.day)
        self.assertEqual(response.context["days_in_month"].start, 1)
        self.assertEqual(response.context["days_in_month"].stop, last_day.day + 1)
        self.assertEqual(response.context["today"], today)

    @patch("events.models.Event.objects.get_user_events")
    @patch.object(get_user_model(), "update_preference")
    def test_calendar_with_month_year_params(
        self,
        mock_update_preference,
        mock_get_user_events,
    ):
        """Test the calendar view with month and year parameters."""
        # Set up mocks
        mock_update_preference.return_value = "month"
        mock_get_user_events.return_value = []

        # Make the request with specific month and year
        response = self.client.get(reverse("calendar") + "?month=6&year=2024")

        # Check response
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "events/calendar.html")

        # Check that the view called the mocked methods
        mock_update_preference.assert_called_once_with("calendar_layout", None)

        # Verify date range for June 2024
        first_day = date(2024, 6, 1)
        last_day = date(2024, 7, 1) - timedelta(days=1)
        mock_get_user_events.assert_called_once_with(self.user, first_day, last_day)

        # Check context data
        self.assertEqual(response.context["month"], 6)
        self.assertEqual(response.context["year"], 2024)
        self.assertEqual(response.context["month_name"], "June")
        self.assertEqual(response.context["prev_month"], 5)
        self.assertEqual(response.context["prev_year"], 2024)
        self.assertEqual(response.context["next_month"], 7)
        self.assertEqual(response.context["next_year"], 2024)
        self.assertEqual(response.context["selected_day"], 1)

    @patch("events.models.Event.objects.get_user_events")
    @patch.object(get_user_model(), "update_preference")
    def test_calendar_with_view_param(
        self,
        mock_update_preference,
        mock_get_user_events,
    ):
        """Test the calendar view with view parameter."""
        # Set up mocks
        mock_update_preference.return_value = "list"
        mock_get_user_events.return_value = []

        # Make the request with view parameter
        response = self.client.get(reverse("calendar") + "?view=list")

        # Check response
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "events/calendar.html")

        # Check that the view called the mocked methods
        mock_update_preference.assert_called_once_with("calendar_layout", "list")

        # Check context data
        self.assertEqual(response.context["view_type"], "list")

    @patch("events.models.Event.objects.get_user_events")
    @patch.object(get_user_model(), "update_preference")
    def test_calendar_with_invalid_month_year(
        self,
        mock_update_preference,
        mock_get_user_events,
    ):
        """Test the calendar view with invalid month and year parameters."""
        # Set up mocks
        mock_update_preference.return_value = "month"
        mock_get_user_events.return_value = []

        # Make the request with invalid month and year
        response = self.client.get(
            reverse("calendar") + "?month=invalid&year=invalid",
        )

        # Check response
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "events/calendar.html")

        # Get today's date for verification
        today = timezone.localdate()

        # Check context data - should default to current month/year
        self.assertEqual(response.context["month"], today.month)
        self.assertEqual(response.context["year"], today.year)

    @patch("events.models.Event.objects.get_user_events")
    @patch.object(get_user_model(), "update_preference")
    def test_calendar_december_navigation(
        self,
        mock_update_preference,
        mock_get_user_events,
    ):
        """Test the calendar navigation for December."""
        # Set up mocks
        mock_update_preference.return_value = "month"
        mock_get_user_events.return_value = []

        # Make the request for December
        response = self.client.get(reverse("calendar") + "?month=12&year=2024")

        # Check context data for navigation
        self.assertEqual(response.context["prev_month"], 11)
        self.assertEqual(response.context["prev_year"], 2024)
        self.assertEqual(response.context["next_month"], 1)
        self.assertEqual(response.context["next_year"], 2025)

    @patch("events.models.Event.objects.get_user_events")
    @patch.object(get_user_model(), "update_preference")
    def test_calendar_january_navigation(
        self,
        mock_update_preference,
        mock_get_user_events,
    ):
        """Test the calendar navigation for January."""
        # Set up mocks
        mock_update_preference.return_value = "month"
        mock_get_user_events.return_value = []

        # Make the request for January
        response = self.client.get(reverse("calendar") + "?month=1&year=2024")

        # Check context data for navigation
        self.assertEqual(response.context["prev_month"], 12)
        self.assertEqual(response.context["prev_year"], 2023)
        self.assertEqual(response.context["next_month"], 2)
        self.assertEqual(response.context["next_year"], 2024)

    @patch("events.models.Event.objects.get_user_events")
    @patch.object(get_user_model(), "update_preference")
    def test_calendar_with_events(
        self,
        mock_update_preference,
        mock_get_user_events,
    ):
        """Test the calendar with events."""
        # Set up mocks
        mock_update_preference.return_value = "month"

        item1 = Item(
            id=1,
            media_id="123",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Test Show 1",
            image="https://example.com/image1.jpg",
        )

        item2 = Item(
            id=2,
            media_id="456",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
            image="https://example.com/image2.jpg",
        )

        # Create some mock events
        today = timezone.localdate()
        event1 = Event(
            item=item1,
            datetime=timezone.make_aware(
                timezone.datetime(today.year, today.month, 15, 12, 0),
            ),
        )
        event2 = Event(
            item=item1,
            content_number=2,
            datetime=timezone.make_aware(
                timezone.datetime(today.year, today.month, 15, 18, 0),
            ),
        )
        event3 = Event(
            item=item2,
            datetime=timezone.make_aware(
                timezone.datetime(today.year, today.month, 20, 9, 0),
            ),
        )

        mock_get_user_events.return_value = [event1, event2, event3]

        # Make the request
        response = self.client.get(reverse("calendar"))

        # Check response
        self.assertEqual(response.status_code, 200)

        # Check release_dict in context
        release_dict = response.context["release_dict"]
        self.assertEqual(len(release_dict), 2)  # Two days with events
        self.assertEqual(len(release_dict[15]), 2)  # Two events on the 15th
        self.assertEqual(len(release_dict[20]), 1)  # One event on the 20th
        self.assertEqual(response.context["selected_day"], today.day)

    @patch("events.models.Event.objects.get_user_events")
    @patch.object(get_user_model(), "update_preference")
    def test_calendar_list_uses_podcast_show_image_when_item_image_missing(
        self,
        mock_update_preference,
        mock_get_user_events,
    ):
        """List view should use show artwork when item image is empty."""
        mock_update_preference.return_value = "list"

        show = app_models.PodcastShow.objects.create(
            podcast_uuid="show-uuid-1",
            title="Podcast Show",
            image="https://example.com/show-art.jpg",
        )
        episode = app_models.PodcastEpisode.objects.create(
            show=show,
            episode_uuid="episode-uuid-1",
            title="Episode 1",
        )

        podcast_item = Item.objects.create(
            media_id=episode.episode_uuid,
            source=Sources.POCKETCASTS.value,
            media_type=MediaTypes.PODCAST.value,
            title=episode.title,
            image="",
        )

        today = timezone.localdate()
        event = Event(
            item=podcast_item,
            datetime=timezone.make_aware(
                timezone.datetime(today.year, today.month, 15, 12, 0),
            ),
        )
        mock_get_user_events.return_value = [event]

        response = self.client.get(reverse("calendar") + "?view=list")

        self.assertEqual(response.status_code, 200)
        rendered = response.content.decode()
        self.assertIn("https://example.com/show-art.jpg", rendered)

    @patch("events.models.Event.objects.get_user_events")
    @patch.object(get_user_model(), "update_preference")
    def test_calendar_shows_available_statuses_and_status_data_attribute(
        self,
        mock_update_preference,
        mock_get_user_events,
    ):
        """Calendar context and markup should expose each release's tracked status."""
        mock_update_preference.return_value = "grid"

        movie_item = Item.objects.create(
            media_id="movie-1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MOVIE.value,
            title="Planned Movie",
            image="https://example.com/movie.jpg",
        )
        Movie.objects.create(
            item=movie_item,
            user=self.user,
            status=Status.PLANNING.value,
        )

        today = timezone.localdate()
        event = Event(
            item=movie_item,
            datetime=timezone.make_aware(
                timezone.datetime(today.year, today.month, 15, 12, 0),
            ),
        )
        mock_get_user_events.return_value = [event]

        response = self.client.get(reverse("calendar"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["available_statuses_by_type"],
            {MediaTypes.MOVIE.value: [Status.PLANNING.value]},
        )
        self.assertIn(
            f'data-release-status="{Status.PLANNING.value}"',
            response.content.decode(),
        )

    @patch("events.models.Event.objects.get_user_events")
    @patch.object(get_user_model(), "update_preference")
    def test_calendar_scopes_available_statuses_per_media_type(
        self,
        mock_update_preference,
        mock_get_user_events,
    ):
        """Statuses for one media type should not appear under another type."""
        mock_update_preference.return_value = "grid"

        movie_item = Item.objects.create(
            media_id="movie-1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MOVIE.value,
            title="Planned Movie",
        )
        Movie.objects.create(
            item=movie_item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        anime_item = Item.objects.create(
            media_id="anime-1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Completed Anime",
        )
        Anime.objects.create(
            item=anime_item,
            user=self.user,
            status=Status.COMPLETED.value,
        )

        today = timezone.localdate()
        mock_get_user_events.return_value = [
            Event(
                item=movie_item,
                datetime=timezone.make_aware(
                    timezone.datetime(today.year, today.month, 15, 12, 0),
                ),
            ),
            Event(
                item=anime_item,
                datetime=timezone.make_aware(
                    timezone.datetime(today.year, today.month, 16, 12, 0),
                ),
            ),
        ]

        response = self.client.get(reverse("calendar"))

        self.assertEqual(
            response.context["available_statuses_by_type"],
            {
                MediaTypes.MOVIE.value: [Status.PLANNING.value],
                MediaTypes.ANIME.value: [Status.COMPLETED.value],
            },
        )
        self.assertIn(MediaTypes.MOVIE.value, response.context["filter_media_types"])
        self.assertIn(MediaTypes.ANIME.value, response.context["filter_media_types"])
        self.assertIn(
            Status.PLANNING.value,
            response.context["filter_statuses_by_type"][MediaTypes.ANIME.value],
        )

    @patch("events.models.Event.objects.get_user_events")
    @patch.object(get_user_model(), "update_preference")
    def test_calendar_omits_media_type_without_resolvable_status(
        self,
        mock_update_preference,
        mock_get_user_events,
    ):
        """Types with no tracked release status should still expose filter options."""
        mock_update_preference.return_value = "grid"

        movie_item = Item.objects.create(
            media_id="untracked-movie-1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MOVIE.value,
            title="Untracked Movie",
        )
        today = timezone.localdate()
        mock_get_user_events.return_value = [
            Event(
                item=movie_item,
                datetime=timezone.make_aware(
                    timezone.datetime(today.year, today.month, 15, 12, 0),
                ),
            ),
        ]

        response = self.client.get(reverse("calendar"))

        self.assertNotIn(
            MediaTypes.MOVIE.value,
            response.context["available_statuses_by_type"],
        )
        self.assertIn(
            MediaTypes.MOVIE.value,
            response.context["filter_statuses_by_type"],
        )

    @patch("events.models.Event.objects.get_user_events")
    @patch.object(get_user_model(), "update_preference")
    def test_calendar_filter_media_types_include_enabled_types_without_releases(
        self,
        mock_update_preference,
        mock_get_user_events,
    ):
        """Enabled media types should remain in the filter even without month releases."""
        mock_update_preference.return_value = "grid"
        mock_get_user_events.return_value = []

        self.user.game_enabled = False
        self.user.save(update_fields=["game_enabled"])

        response = self.client.get(reverse("calendar"))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(MediaTypes.GAME.value, response.context["filter_media_types"])
        self.assertNotIn(
            MediaTypes.GAME.value,
            response.context["available_media_types"],
        )
        self.assertIn(MediaTypes.MOVIE.value, response.context["filter_media_types"])
        self.assertNotIn(
            MediaTypes.MOVIE.value,
            response.context["available_media_types"],
        )

    @patch("events.tasks.reload_calendar.delay")
    def test_reload_calendar(self, mock_reload_task):
        """Test the reload_calendar view."""
        # Make the request
        response = self.client.post(reverse("reload_calendar"))

        # Check response
        self.assertRedirects(response, reverse("calendar"))

        # Check that the task was called
        mock_reload_task.assert_called_once_with(user_id=self.user.id)

        # Check for message
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("refresh upcoming releases", str(messages[0]))

    def test_reload_calendar_get_method_not_allowed(self):
        """Test that GET requests to reload_calendar are not allowed."""
        # Make a GET request
        response = self.client.get(reverse("reload_calendar"))

        # Check response - should be 405 Method Not Allowed
        self.assertEqual(response.status_code, 405)


class DownloadCalendarViewTests(TestCase):
    """Tests for the calendar export endpoint."""

    def setUp(self):
        """Set up test data."""
        self.credentials = {"username": "caluser", "password": "testpassword"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        self.movie_item = Item.objects.create(
            media_id="movie-1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MOVIE.value,
            title="Export Movie",
            image="https://example.com/movie.jpg",
        )
        self.season_item = Item.objects.create(
            media_id="tv-1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.SEASON.value,
            title="Export Season",
            image="https://example.com/season.jpg",
            season_number=1,
        )
        self.tv_item = Item.objects.create(
            media_id="tv-1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.TV.value,
            title="Export Show",
            image="https://example.com/show.jpg",
        )

        self.movie = Movie.objects.create(
            item=self.movie_item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        self.tv = TV.objects.create(
            item=self.tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        self.season = Season.objects.create(
            item=self.season_item,
            related_tv=self.tv,
            user=self.user,
            status=Status.PLANNING.value,
        )

        now = timezone.now()
        self.movie_event = Event.objects.create(item=self.movie_item, datetime=now)
        self.season_event = Event.objects.create(item=self.season_item, datetime=now)

    def test_download_calendar_filters_selected_media_types(self):
        """Only selected media types should be exported."""
        export_events = Event.objects.filter(
            id__in=[self.movie_event.id, self.season_event.id],
        )
        with patch(
            "events.views.Event.objects.get_user_events",
            return_value=export_events,
        ):
            response = self.client.get(
                reverse("download_calendar", kwargs={"token": self.user.token}),
                {"media_types": [MediaTypes.MOVIE.value]},
            )

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Export Movie", body)
        self.assertNotIn("Export Season", body)

    def test_download_calendar_tv_filter_includes_seasons(self):
        """Selecting tv should include season events in export."""
        export_events = Event.objects.filter(
            id__in=[self.movie_event.id, self.season_event.id],
        )
        with patch(
            "events.views.Event.objects.get_user_events",
            return_value=export_events,
        ):
            response = self.client.get(
                reverse("download_calendar", kwargs={"token": self.user.token}),
                {"media_types": [MediaTypes.TV.value]},
            )

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Export Season", body)
        self.assertNotIn("Export Movie", body)

    def test_download_calendar_filters_selected_status(self):
        """Only events whose own tracked status matches should be exported."""
        export_events = Event.objects.filter(
            id__in=[self.movie_event.id, self.season_event.id],
        )
        with patch(
            "events.views.Event.objects.get_user_events",
            return_value=export_events,
        ):
            planning_response = self.client.get(
                reverse("download_calendar", kwargs={"token": self.user.token}),
                {"status": [Status.PLANNING.value]},
            )
            in_progress_response = self.client.get(
                reverse("download_calendar", kwargs={"token": self.user.token}),
                {"status": [Status.IN_PROGRESS.value]},
            )

        self.assertEqual(planning_response.status_code, 200)
        planning_body = planning_response.content.decode()
        self.assertIn("Export Movie", planning_body)
        self.assertIn("Export Season", planning_body)

        # Neither item's own status is In Progress, even though the related
        # TV show's status is - confirms per-item, not per-show, filtering.
        self.assertEqual(in_progress_response.status_code, 200)
        in_progress_body = in_progress_response.content.decode()
        self.assertNotIn("Export Movie", in_progress_body)
        self.assertNotIn("Export Season", in_progress_body)

    def test_download_calendar_invalid_token_returns_401(self):
        """Unknown export tokens should be rejected."""
        response = self.client.get(
            reverse("download_calendar", kwargs={"token": "missing-token"}),
        )

        self.assertEqual(response.status_code, 401)

    @patch(
        "events.views.Event.objects.get_user_events",
        return_value=Event.objects.none(),
    )
    def test_download_calendar_returns_empty_calendar(self, _mock_get_user_events):
        """An empty export should still return a valid iCalendar payload."""
        response = self.client.get(
            reverse("download_calendar", kwargs={"token": self.user.token}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/calendar")
        body = response.content.decode()
        self.assertIn("BEGIN:VCALENDAR", body)
        self.assertIn("END:VCALENDAR", body)
        self.assertNotIn("Export Movie", body)

    def test_download_calendar_returns_events(self):
        """Exports should include tracked release summaries."""
        response = self.client.get(
            reverse("download_calendar", kwargs={"token": self.user.token}),
        )

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("BEGIN:VCALENDAR", body)
        self.assertIn("Export Movie", body)
        self.assertIn("Export Season", body)

    def test_download_calendar_uses_all_day_event_for_sentinel_time(self):
        """Events with an unknown release time should export as all-day."""
        # download_calendar only returns events within a rolling
        # [now-30d, now+90d] window, so the target date must be relative to
        # "now" rather than a hardcoded date -- a fixed date eventually
        # drifts outside that window and the event silently disappears from
        # the query instead of failing the assertion it was meant to check.
        target_date = (timezone.now() + timedelta(days=1)).date()
        sentinel_dt = timezone.datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            SentinelDatetime.HOUR,
            SentinelDatetime.MINUTE,
            SentinelDatetime.SECOND,
            SentinelDatetime.MICROSECOND,
            tzinfo=UTC,
        )
        self.movie_event.datetime = sentinel_dt
        self.movie_event.save()

        response = self.client.get(
            reverse("download_calendar", kwargs={"token": self.user.token}),
        )

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        start_str = target_date.strftime("%Y%m%d")
        end_str = (target_date + timedelta(days=1)).strftime("%Y%m%d")
        self.assertIn(f"DTSTART;VALUE=DATE:{start_str}", body)
        self.assertIn(f"DTEND;VALUE=DATE:{end_str}", body)
        self.assertNotIn(f"DTSTART:{start_str}T115959Z", body)

    def test_download_calendar_keeps_timed_event_for_known_time(self):
        """Events with a known release time should keep a timed DTSTART/DTEND."""
        target_date = (timezone.now() + timedelta(days=1)).date()
        known_dt = timezone.datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            7,
            0,
            0,
            tzinfo=UTC,
        )
        self.movie_event.datetime = known_dt
        self.movie_event.save()

        response = self.client.get(
            reverse("download_calendar", kwargs={"token": self.user.token}),
        )

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        expected = known_dt.strftime("%Y%m%dT%H%M%SZ")
        self.assertIn(f"DTSTART:{expected}", body)
        self.assertIn(f"DTEND:{expected}", body)

    def test_download_calendar_allows_head_requests(self):
        """HEAD requests should be accepted for calendar clients."""
        response = self.client.head(
            reverse("download_calendar", kwargs={"token": self.user.token}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/calendar")

    def test_download_calendar_does_not_require_authentication(self):
        """The tokenized export should remain available without a session."""
        self.client.logout()

        response = self.client.get(
            reverse("download_calendar", kwargs={"token": self.user.token}),
        )

        self.assertEqual(response.status_code, 200)

    def test_download_calendar_post_not_allowed(self):
        """Only GET-like methods should be allowed on the export endpoint."""
        response = self.client.post(
            reverse("download_calendar", kwargs={"token": self.user.token}),
        )

        self.assertEqual(response.status_code, 405)
