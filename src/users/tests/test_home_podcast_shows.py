"""Home podcast shelves list shows by default and can list episodes (#1378, #752)."""

from datetime import UTC, datetime

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from app.models import (
    Item,
    MediaTypes,
    Podcast,
    PodcastEpisode,
    PodcastShow,
    PodcastShowTracker,
    Sources,
    Status,
)
from users import home_screen
from users.home_screen import build_home_page_groups
from users.models import (
    DirectionChoices,
    HomeScreenRow,
    HomeScreenRowTypeChoices,
    HomeSortChoices,
    MediaSortChoices,
)


class HomePodcastShowShelfTests(TestCase):
    """A podcast shelf is one card per tracked show."""

    def setUp(self):
        """Create a show with two played episodes and a second, paused show."""
        cache.clear()
        self.user = get_user_model().objects.create_user(username="pod", password="x")
        self.user.podcast_enabled = True
        self.user.save()

        self.show = PodcastShow.objects.create(
            podcast_uuid="11111111-1111-1111-1111-111111111111",
            title="The Show",
            author="Some Host",
            language="en",
            genres=["Comedy"],
        )
        PodcastShowTracker.objects.create(
            user=self.user, show=self.show, status=Status.IN_PROGRESS.value
        )
        for number in (1, 2):
            item = Item.objects.create(
                media_id=f"ep-{number}",
                source=Sources.POCKETCASTS.value,
                media_type=MediaTypes.PODCAST.value,
                title=f"Episode {number}",
            )
            Podcast.objects.create(
                item=item,
                user=self.user,
                show=self.show,
                status=Status.IN_PROGRESS.value,
            )

        paused = PodcastShow.objects.create(
            podcast_uuid="22222222-2222-2222-2222-222222222222",
            title="Paused Show",
            language="de",
            genres=["News"],
        )
        PodcastShowTracker.objects.create(
            user=self.user, show=paused, status=Status.PAUSED.value
        )

    def row(self, filters):
        """Create a podcast library shelf with the given filters."""
        return HomeScreenRow.objects.create(
            user=self.user,
            media_type=MediaTypes.PODCAST.value,
            position=0,
            enabled=True,
            row_type=HomeScreenRowTypeChoices.LIBRARY_QUERY,
            sort_by=HomeSortChoices.RECENT,
            direction=DirectionChoices.DESC,
            filters=filters,
        )

    def titles(self, row):
        """Return the card titles and total the shelf loads."""
        entries, total = home_screen._library_row_window(
            self.user, row, 0, 14, seed=0
        )
        return [entry.item.title for entry in entries], total

    def test_in_progress_shelf_shows_the_show_once(self):
        """Two in-progress episodes still make one show card."""
        titles, total = self.titles(self.row({"status": [Status.IN_PROGRESS.value]}))

        self.assertEqual(titles, ["The Show"])
        self.assertEqual(total, 1)

    def test_entry_carries_show_for_card_link_and_modal(self):
        """The card links to the show and edits the show's tracker."""
        row = self.row({"status": [Status.IN_PROGRESS.value]})
        entries, _ = home_screen._library_row_window(
            self.user, row, 0, 14, seed=0
        )

        self.assertTrue(entries[0].use_podcast_show)
        self.assertEqual(entries[0].podcast_show, self.show)
        self.assertEqual(entries[0].media.card_subtitle_text, "Some Host")

    def test_status_genre_and_language_filters_apply_to_shows(self):
        """Filters match the show's tracker and metadata."""
        self.assertEqual(
            self.titles(self.row({"status": [Status.PAUSED.value]}))[0],
            ["Paused Show"],
        )
        self.assertEqual(
            self.titles(self.row({"status": [], "genre": "news"}))[0],
            ["Paused Show"],
        )
        self.assertEqual(
            self.titles(self.row({"status": [], "language": "EN"}))[0],
            ["The Show"],
        )

    def test_episodes_subview_lists_each_episode(self):
        """Choosing Episodes keeps the per-episode shelf."""
        row = self.row({"status": [Status.IN_PROGRESS.value], "subview": "episodes"})

        titles, total = self.titles(row)

        self.assertCountEqual(titles, ["Episode 1", "Episode 2"])
        self.assertEqual(total, 2)

    def test_settings_offer_shows_and_episodes(self):
        """The Home settings filter menu has a Shows/Episodes choice for podcasts."""
        fields = home_screen.build_filter_field_data(self.user, MediaTypes.PODCAST.value)
        subview = next(field for field in fields if field["key"] == "subview")

        self.assertEqual(
            [option["value"] for option in subview["options"]],
            ["shows", "episodes"],
        )

    def test_subview_is_validated_per_media_type(self):
        """Podcast rows accept shows/episodes and reject music's values."""
        for value in ("shows", "episodes"):
            filters = home_screen.validate_library_row_filters(
                {"subview": value}, MediaTypes.PODCAST.value
            )
            self.assertEqual(filters["subview"], value)
        with self.assertRaises(home_screen.HomeScreenValidationError):
            home_screen.validate_library_row_filters(
                {"subview": "tracks"}, MediaTypes.PODCAST.value
            )

    def test_row_without_subview_defaults_to_shows(self):
        """Rows saved before the choice existed show shows, and say so."""
        row = self.row({"status": [Status.IN_PROGRESS.value]})

        self.assertEqual(
            home_screen.describe_library_query(
                row.filters, self.user, MediaTypes.PODCAST.value
            ),
            "In Progress • Shows",
        )

    def test_renamed_show_updates_its_card_title(self):
        """A show renamed after its card was first built shows the new title."""
        row = self.row({"status": [Status.IN_PROGRESS.value]})
        self.titles(row)
        self.show.title = "The Show, Renamed"
        self.show.save()

        titles, _total = self.titles(row)

        self.assertEqual(titles, ["The Show, Renamed"])

    def test_release_date_sort_uses_first_episode_publication(self):
        """Shows sort by when their first episode was published."""
        older = PodcastShow.objects.create(
            podcast_uuid="33333333-3333-3333-3333-333333333333", title="Zebra Older"
        )
        PodcastShowTracker.objects.create(
            user=self.user, show=older, status=Status.IN_PROGRESS.value
        )
        PodcastEpisode.objects.create(
            show=older,
            episode_uuid="old-1",
            title="Old",
            published=datetime(2019, 1, 1, tzinfo=UTC),
        )
        PodcastEpisode.objects.create(
            show=self.show,
            episode_uuid="new-1",
            title="New",
            published=datetime(2024, 1, 1, tzinfo=UTC),
        )
        row = self.row({"status": [Status.IN_PROGRESS.value]})
        row.sort_by = MediaSortChoices.RELEASE_DATE
        row.direction = DirectionChoices.ASC

        titles, _total = self.titles(row)

        self.assertEqual(titles, ["Zebra Older", "The Show"])

    def test_home_page_renders_one_card_per_show(self):
        """The Home page lists the show title once, not once per episode."""
        self.row({"status": [Status.IN_PROGRESS.value]})
        self.client.force_login(self.user)
        build_home_page_groups(self.user, 14)  # the shell only inlines warm shelves

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The Show", count=3)  # title, alt text, link
        self.assertNotContains(response, "Episode 1")
        self.assertNotContains(response, "Episode 2")
