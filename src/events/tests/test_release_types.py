from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escapejs

from app.models import Item, MediaTypes, Movie, Sources, Status
from app.providers import tmdb
from app.track_modal_views import (
    _track_modal_date_suggestion,
    _track_modal_other_release_dates,
)
from events.calendar.helpers import date_parser
from events.calendar.main import cleanup_invalid_events, save_events
from events.calendar.other import process_other
from events.calendar.selectors import get_movie_items_to_include
from events.models import Event, ReleaseTypes
from events.notifications import get_user_releases

TMDB_RELEASE_DATES = {
    "results": [
        {
            "iso_3166_1": "US",
            "release_dates": [
                {"type": 3, "release_date": "2026-12-12T00:00:00.000Z"},
                {"type": 4, "release_date": "2027-02-01T00:00:00.000Z"},
                {"type": 4, "release_date": "2027-01-20T00:00:00.000Z"},
                {"type": 5, "release_date": "2027-02-14T00:00:00.000Z"},
            ],
        },
        {
            "iso_3166_1": "FR",
            "release_dates": [
                {"type": 4, "release_date": "2027-03-01T00:00:00.000Z"},
                {"type": 6, "release_date": "2027-06-01T00:00:00.000Z"},
            ],
        },
        {
            "iso_3166_1": "DE",
            "release_dates": [{"type": 3, "release_date": "2026-12-11T00:00:00.000Z"}],
        },
    ],
}

RELEASE_TYPES = {
    "US": {"digital": "2027-01-20", "physical": "2027-02-14"},
    "FR": {"digital": "2027-03-01"},
}


class ReleaseTypeParsingTests(TestCase):
    """TMDB release dates are reduced to digital and physical dates per region."""

    def test_keeps_earliest_digital_and_physical_date_per_region(self):
        """Other types and regions without either type are left out."""
        self.assertEqual(
            tmdb.get_movie_release_types(TMDB_RELEASE_DATES),
            RELEASE_TYPES,
        )

    def test_tolerates_missing_or_malformed_payloads(self):
        """A movie without release dates yields no release types."""
        self.assertEqual(tmdb.get_movie_release_types({}), {})
        self.assertEqual(tmdb.get_movie_release_types(None), {})
        self.assertEqual(
            tmdb.get_movie_release_types({"results": ["x", {"iso_3166_1": ""}]}),
            {},
        )


class ReleaseTypeEventsMixin:
    """A TMDB movie tracked by one user in a chosen region."""

    region = "US"

    def setUp(self):
        """Create a user, a tracked movie and its metadata."""
        super().setUp()
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="regionuser",
            password="pw",
            watch_provider_region=self.region,
        )
        self.item = Item.objects.create(
            media_id="9001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Dune Part Three",
            image="http://example.com/dune.jpg",
        )
        Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        self.metadata = {
            "max_progress": 1,
            "details": {"release_date": "2026-12-12"},
            "release_types": RELEASE_TYPES,
        }

    def process(self):
        """Run the movie through the calendar and save its events."""
        events_bulk = []
        with patch(
            "events.calendar.other.services.get_media_metadata",
            return_value=self.metadata,
        ):
            process_other(self.item, events_bulk)
        save_events(events_bulk)
        cleanup_invalid_events(events_bulk)
        return events_bulk


class ReleaseTypeEventTests(ReleaseTypeEventsMixin, TestCase):
    """Digital and physical dates become events for the user's region only."""

    def test_creates_events_for_the_tracking_users_region(self):
        """Only the region of the user tracking the movie gets events."""
        self.process()

        typed = Event.objects.filter(item=self.item).exclude(release_type="")
        self.assertEqual(
            {(event.release_type, event.region, event.datetime) for event in typed},
            {
                ("digital", "US", date_parser("2027-01-20")),
                ("physical", "US", date_parser("2027-02-14")),
            },
        )
        main = Event.objects.get(item=self.item, release_type="")
        self.assertEqual(main.datetime, date_parser("2026-12-12"))

    def test_user_without_region_gets_only_the_main_release(self):
        """No region set means nothing to look dates up for."""
        self.user.watch_provider_region = "UNSET"
        self.user.save()

        self.process()

        self.assertEqual(Event.objects.filter(item=self.item).count(), 1)

    def test_second_refresh_updates_events_in_place(self):
        """A moved date updates the existing event instead of adding another."""
        self.process()
        self.metadata["release_types"] = {"US": {"digital": "2027-01-27"}}

        self.process()

        digital = Event.objects.get(item=self.item, release_type="digital")
        self.assertEqual(digital.datetime, date_parser("2027-01-27"))
        self.assertEqual(Event.objects.filter(item=self.item).count(), 2)

    def test_dates_tmdb_no_longer_lists_are_removed(self):
        """A stale digital or physical event goes; the main release stays."""
        self.process()
        self.metadata["release_types"] = {}

        self.process()

        self.assertEqual(
            list(
                Event.objects.filter(item=self.item).values_list(
                    "release_type", flat=True
                )
            ),
            [""],
        )

    def test_skipped_movie_keeps_its_events(self):
        """A failed provider call leaves the stored dates alone."""
        self.process()
        events_before = Event.objects.filter(item=self.item).count()

        cleanup_invalid_events([])

        self.assertEqual(Event.objects.filter(item=self.item).count(), events_before)

    def test_event_title_names_the_release_type(self):
        """The calendar, notifications and feed all show the release type."""
        event = Event(item=self.item, release_type=ReleaseTypes.DIGITAL.value)

        self.assertEqual(str(event), "Dune Part Three (Digital release)")
        self.assertEqual(str(Event(item=self.item)), "Dune Part Three")


class ReleaseTypeVisibilityTests(ReleaseTypeEventsMixin, TestCase):
    """Users only see the digital and physical dates of their own region."""

    def setUp(self):
        """Add an event for the user's region and one for another region."""
        super().setUp()
        now = timezone.now()
        self.main = Event.objects.create(item=self.item, datetime=now)
        self.us_digital = Event.objects.create(
            item=self.item,
            datetime=now,
            release_type="digital",
            region="US",
        )
        self.fr_digital = Event.objects.create(
            item=self.item,
            datetime=now,
            release_type="digital",
            region="FR",
        )

    def events_for(self, user):
        """Return the ids the calendar shows the user this month."""
        start = (timezone.now() - timedelta(days=1)).date()
        end = (timezone.now() + timedelta(days=1)).date()
        return {event.id for event in Event.objects.get_user_events(user, start, end)}

    def test_calendar_shows_main_and_own_region_events(self):
        """The other region's date is hidden."""
        self.assertEqual(self.events_for(self.user), {self.main.id, self.us_digital.id})

    def test_user_in_other_region_sees_that_regions_dates(self):
        """Switching the watch provider region switches the dates."""
        self.user.watch_provider_region = "FR"

        self.assertEqual(self.events_for(self.user), {self.main.id, self.fr_digital.id})

    def test_user_without_region_sees_only_the_main_release(self):
        """Unset region has no digital or physical dates."""
        self.user.watch_provider_region = "UNSET"

        self.assertEqual(self.events_for(self.user), {self.main.id})

    def test_notifications_skip_other_regions(self):
        """Only the user's own region is announced."""
        self.user.release_notifications_enabled = True
        events = {
            event.id: event for event in Event.objects.select_related("item").all()
        }

        releases = get_user_releases([self.user], events)

        self.assertEqual(
            {event.id for event in releases[self.user.id]},
            {self.main.id, self.us_digital.id},
        )

    def test_calendar_page_marks_release_types(self):
        """Events carry their release type so the dropdown can filter them."""
        self.client.force_login(self.user)

        response = self.client.get(reverse("calendar"))

        self.assertContains(response, 'data-release-type="digital"')
        self.assertContains(response, "Digital release")
        self.assertEqual(response.context["available_release_types"], ["digital"])

    def test_calendar_page_without_region_points_to_preferences(self):
        """A user with no region is told where to set it."""
        self.user.watch_provider_region = "UNSET"
        self.user.save()
        self.client.force_login(self.user)

        response = self.client.get(reverse("calendar"))

        self.assertContains(response, "Set your watch provider region")

    def test_feed_filters_release_types(self):
        """The iCal feed includes every date unless release types are chosen."""
        url = reverse("download_calendar", kwargs={"token": self.user.token})

        everything = self.client.get(url).content.decode()
        main_only = self.client.get(url, {"release_types": "none"}).content.decode()
        physical_only = self.client.get(
            url,
            {"release_types": "physical"},
        ).content.decode()

        self.assertIn("Digital release", everything)
        self.assertNotIn("Digital release", main_only)
        self.assertIn("Dune Part Three", main_only)
        self.assertNotIn("Digital release", physical_only)


class ReleaseTypeSelectionTests(ReleaseTypeEventsMixin, TestCase):
    """Recent movies are re-fetched until their region has events."""

    def included(self):
        """Return whether the movie is picked for a calendar refresh."""
        with patch(
            "events.calendar.selectors.get_changed_tmdb_movie_ids", return_value=set()
        ):
            return self.item.id in get_movie_items_to_include(
                Item.objects.filter(id=self.item.id),
            )

    def test_recent_movie_without_region_events_is_refreshed(self):
        """A movie scheduled before this feature picks up its region's dates."""
        Event.objects.create(item=self.item, datetime=timezone.now())

        self.assertTrue(self.included())

    def test_movie_with_region_events_is_left_alone(self):
        """Nothing to fetch once the region has dates."""
        Event.objects.create(item=self.item, datetime=timezone.now())
        Event.objects.create(
            item=self.item,
            datetime=timezone.now(),
            release_type="digital",
            region="US",
        )

        self.assertFalse(self.included())

    def test_old_movie_waits_for_the_change_feed(self):
        """Years-old movies are not re-fetched every window."""
        Event.objects.create(
            item=self.item,
            datetime=timezone.now() - timedelta(days=800),
        )

        self.assertFalse(self.included())


class TrackModalReleaseDatesTests(ReleaseTypeEventsMixin, TestCase):
    """The track modal date picker offers the other dates stored for the region."""

    def setUp(self):
        """Store dates for the user's region and for another region."""
        super().setUp()
        for release_type, region, release_date in (
            ("physical", "US", "2027-02-14"),
            ("digital", "US", "2027-01-20"),
            ("digital", "FR", "2027-03-01"),
        ):
            Event.objects.create(
                item=self.item,
                datetime=date_parser(release_date),
                release_type=release_type,
                region=region,
            )

    def test_lists_digital_and_physical_dates_for_the_region(self):
        """Dates come back in digital, physical order, for the user's region."""
        rows = _track_modal_other_release_dates(
            MediaTypes.MOVIE.value,
            self.item,
            self.user,
        )

        self.assertEqual(
            [(row["label"], row["date"]) for row in rows],
            [("Digital release", "2027-01-20"), ("Physical release", "2027-02-14")],
        )

    def test_date_picker_offers_each_date_as_a_quick_button(self):
        """The picker dropdown gets a button per date, next to the theatrical one."""
        extras = _track_modal_other_release_dates(
            MediaTypes.MOVIE.value,
            self.item,
            self.user,
        )
        suggestion = _track_modal_date_suggestion(
            "Theatrical release",
            "2026-12-12",
            extras=extras,
        )

        html = render_to_string(
            "app/components/date_time_picker.html",
            {
                "field_name": "start_date",
                "field_id": "id_start_date",
                "suggestion_label": suggestion["label"],
                "suggestion_date": suggestion["date"],
                "suggestion_extras": suggestion["extras"],
            },
        )

        self.assertIn(f"applySuggestion('{escapejs('2027-01-20')}')", html)
        self.assertIn(f"applySuggestion('{escapejs('2027-02-14')}')", html)
        self.assertIn("Digital release", html)
        self.assertIn("Physical release", html)

    def test_other_media_and_unset_region_have_none(self):
        """Nothing to show outside movies or without a region."""
        self.assertEqual(
            _track_modal_other_release_dates(
                MediaTypes.TV.value,
                self.item,
                self.user,
            ),
            [],
        )
        self.assertEqual(
            _track_modal_other_release_dates(MediaTypes.MOVIE.value, None, self.user),
            [],
        )
        self.user.watch_provider_region = "UNSET"
        self.assertEqual(
            _track_modal_other_release_dates(
                MediaTypes.MOVIE.value,
                self.item,
                self.user,
            ),
            [],
        )
