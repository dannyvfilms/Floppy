import json
import re
from datetime import datetime, time, timedelta
from unittest.mock import patch
from uuid import uuid4

from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import TV, Episode, Item, MediaTypes, Season, Sources, Status
from events.models import Event
from users import home_screen
from users.models import HomeScreenRow


class EpisodeFeedTests(TestCase):
    """Exercise Up Next as a Home row and its existing watched action."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="episode-feed")
        self.client.force_login(self.user)
        self.row = HomeScreenRow.objects.create(
            user=self.user,
            media_type="all",
            row_type="up_next",
            sort_by="episode_feed",
            direction="asc",
        )
        self.metadata = patch(
            "app.models.providers.services.get_media_metadata",
            return_value={
                "max_progress": 3,
                "season_number": 1,
                "episodes": [
                    {
                        "episode_number": number,
                        "name": f"Episode {number}",
                        "still_path": None,
                    }
                    for number in range(1, 4)
                ],
                "related": {"seasons": [{"season_number": 1}]},
                "details": {"status": "Returning Series"},
            },
        )
        self.metadata.start()
        self.addCleanup(self.metadata.stop)
        self.addCleanup(cache.clear)

    @staticmethod
    def _queue(card):
        """Return the card's chip label and the season and episode it links to."""
        chip = card.select_one('[data-episode-queue="true"]')
        link = re.search(r"/season/(\d+)/episode/(\d+)", chip.get("href", ""))
        label = " ".join(chip.stripped_strings)
        if link is None:
            return (label, None, None)
        return (label, int(link.group(1)), int(link.group(2)))

    def _chips(self, response):
        soup = BeautifulSoup(response.content.decode(response.charset), "html.parser")
        return [
            self._queue(card)
            for card in soup.select(f"#media-grid-row-{self.row.pk} .home-row-card")
        ]

    def _feed(self, page=1):
        section = home_screen._build_row_section(
            self.user,
            self.row,
            self.row.media_type,
            30,
            batch_start=(page - 1) * 30,
        )
        return section or {"items": [], "total": 0}

    def _response_row(self, response):
        groups = response.context.get("home_groups")
        if groups is not None:
            return next(
                (
                    row
                    for group in groups
                    for row in group["rows"]
                    if row["row_id"] == self.row.pk
                ),
                {"items": [], "total": 0},
            )
        return response.context["media_list"]

    def _hydrated_home(self):
        """Follow Home's deferred row requests as the browser does."""
        response = self.client.get(reverse("home"))
        if response.context is None:
            return response
        soup = BeautifulSoup(response.content.decode(response.charset), "html.parser")
        for group in response.context.get("deferred_groups", []):
            rows = []
            for row_id in group["row_ids"]:
                url = reverse("home_row_fragment", args=[row_id])
                fragment = self.client.get(url)
                slot = soup.find(attrs={"data-home-row-slot": True, "hx-get": url})
                slot.replace_with(BeautifulSoup(fragment.content.decode(fragment.charset), "html.parser"))
                row = (fragment.context or {}).get("row")
                if row is not None:
                    rows.append(row)
            if rows:
                response.context["home_groups"].append({**group, "rows": rows})
        response.content = str(soup)
        return response

    def _show(
        self,
        title,
        *,
        days_ago=3,
        status=Status.IN_PROGRESS.value,
        watched=0,
        future=False,
        user=None,
    ):
        user = user or self.user
        item = Item.objects.create(
            title=title,
            media_id=title,
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            image="https://example.com/poster.jpg",
            status="Returning Series",
        )
        tv = TV.objects.create(item=item, user=user, status=status)
        season_item = Item.objects.create(
            title=title,
            media_id=title,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=1,
        )
        season = Season.objects.create(
            item=season_item,
            user=user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )
        for number in range(1, 4):
            released_at = (
                timezone.now() + timedelta(days=number)
                if future
                else (timezone.now() - timedelta(days=days_ago, hours=3 - number))
            )
            episode_item = Item.objects.create(
                title=f"{title} episode {number}",
                media_id=title,
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                season_number=1,
                episode_number=number,
                release_datetime=released_at,
            )
            Event.objects.create(
                item=season_item,
                content_number=number,
                datetime=released_at,
            )
            if number <= watched:
                Episode.objects.create(
                    item=episode_item,
                    related_season=season,
                    end_date=timezone.now(),
                )
        return tv, season

    def test_up_next_is_a_native_home_preset(self):
        self._show("Native card", watched=1)
        for media_type in ("all", "tv"):
            with self.subTest(media_type=media_type):
                response = self.client.post(
                    reverse("home_screen"),
                    {
                        "home_screen_sections": json.dumps(
                            [
                                {
                                    "media_type": media_type,
                                    "rows": [{"row_type": "up_next"}],
                                }
                            ]
                        ),
                    },
                )
                self.assertEqual(response.status_code, 302)
                self.row = HomeScreenRow.objects.get(user=self.user, row_type="up_next")
                self.assertEqual(self.row.sort_by, "episode_feed")
                self.assertEqual(self.row.direction, "asc")
                settings = self.client.get(reverse("home_screen"))
                response = self._hydrated_home()
                soup = BeautifulSoup(response.content, "html.parser")
                self.assertIsNotNone(
                    soup.select_one(
                        "[data-home-row-wrapper] .home-row-card .media-card"
                    )
                )
                self.assertEqual(self._chips(response), [("2 Behind", 1, 2)])
                self.assertNotContains(response, "episode-feed-")

    def test_up_next_chip_replaces_next_episode_link_and_respects_card_settings(self):
        self._show("Backlog show", watched=1)
        self._show("Future show", future=True)
        self._show("Upcoming show", watched=3)
        regular = HomeScreenRow.objects.create(
            user=self.user, media_type="all", row_type="library_query",
            sort_by="title", position=1,
            filters={"media_types": ["tv"], "status": [Status.IN_PROGRESS.value]},
        )
        self.user.card_metadata = {
            "version": 1,
            "types": {"tv": {"display": "hover", "fields": []}},
        }
        self.user.quick_season_update_mobile = "next_episode"
        self.user.save(update_fields=["card_metadata", "quick_season_update_mobile"])
        response = self._hydrated_home()
        soup = BeautifulSoup(response.content, "html.parser")
        queue = soup.select_one(f"#media-grid-row-{self.row.pk}")
        cards = queue.select(".home-row-card")
        self.assertEqual(len(cards), 3)
        for card in cards:
            # The user's subtitle setting decides; Up Next adds none of its own.
            self.assertIsNone(card.select_one(".media-card-subtitle-always"))
            # One chip in the next-episode slot, linking the same way.
            self.assertEqual(len(card.select('[data-episode-queue="true"]')), 1)
            self.assertNotIn("Next ep", card.get_text())
            # The status chip steps aside on phones so the two never overlap.
            status = card.select_one(".media-status-chip")
            self.assertEqual(status["data-mobile-hide-on-mobile"], "true")
        # Shows with a known next episode link to it; an undated show has none.
        self.assertEqual(len(queue.select('a[data-episode-queue="true"]')), 2)
        self.assertEqual(
            [label for label, *_ in self._chips(response)],
            ["2 Behind", "1 day", "Upcoming"],
        )
        ordinary = soup.select_one(f"#media-grid-row-{regular.pk}")
        self.assertIsNotNone(ordinary)
        self.assertIsNone(ordinary.select_one('[data-episode-queue="true"]'))

    def test_up_next_sort_direction_reverses_the_queue(self):
        self._show("One behind", watched=2)
        self._show("Three behind", watched=0)
        self._show("Future show", future=True)

        def titles():
            return [entry.item.title for entry in self._feed()["items"]]

        self.assertEqual(titles(), ["One behind", "Three behind", "Future show"])
        self.row.direction = "desc"
        self.row.save(update_fields=["direction"])
        cache.clear()
        self.assertEqual(titles(), ["Future show", "Three behind", "One behind"])

    def test_up_next_sort_and_direction_save_with_the_row(self):
        self._show("Show", watched=1)
        for sort_by, direction in (("episode_feed", "desc"), ("title", "asc")):
            with self.subTest(sort_by=sort_by):
                home_screen.save_home_screen_configuration(
                    self.user,
                    json.dumps(
                        [
                            {
                                "media_type": "tv",
                                "rows": [
                                    {
                                        "row_type": "up_next",
                                        "sort_by": sort_by,
                                        "direction": direction,
                                    }
                                ],
                            },
                        ]
                    ),
                )
                row = HomeScreenRow.objects.get(user=self.user, row_type="up_next")
                self.assertEqual((row.sort_by, row.direction), (sort_by, direction))

    def test_invalid_up_next_settings_do_not_replace_existing_rows(self):
        for media_type, sort_by in (("movie", "episode_feed"), ("tv", "bogus")):
            with self.subTest(media_type=media_type, sort_by=sort_by):
                with self.assertRaises(home_screen.HomeScreenValidationError):
                    home_screen.save_home_screen_configuration(
                        self.user,
                        json.dumps(
                            [
                                {
                                    "media_type": media_type,
                                    "rows": [
                                        {"row_type": "up_next", "sort_by": sort_by}
                                    ],
                                },
                            ]
                        ),
                    )
                self.assertTrue(HomeScreenRow.objects.filter(pk=self.row.pk).exists())

    def test_up_next_paging_cannot_load_another_users_row(self):
        self._show("Owned show", watched=1)
        other = get_user_model().objects.create_user(username="other-row-owner")
        other_row = HomeScreenRow.objects.create(
            user=other, media_type="tv", row_type="up_next"
        )
        response = self.client.get(
            reverse("home"), {"load_row": other_row.pk}, HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.content, b"")
        response = self.client.get(reverse("home_row_fragment", args=[other_row.pk]))
        self.assertEqual(response.content, b"")

    def test_standalone_up_next_route_is_removed(self):
        self.assertEqual(self.client.get("/up-next").status_code, 404)

    def test_saved_language_localizes_feed_and_sidebar_settings(self):
        self._show("Backlog", watched=1)
        self._show("Future", future=True)
        self._show("Undated", watched=3)
        for language, title, behind, day, upcoming in (
            ("de", "Als Nächstes", "Ungesehen", "Tag", "Demnächst"),
            ("es", "A continuación", "Sin ver", "día", "Próximos"),
            ("fr", "À suivre", "Non vus", "jour", "À venir"),
            ("it", "Da guardare", "Da vedere", "giorno", "In arrivo"),
        ):
            with self.subTest(language=language):
                self.user.ui_language = language
                self.user.save(update_fields=["ui_language"])
                response = self._hydrated_home()
                self.assertContains(response, title)
                self.assertContains(response, behind)
                self.assertContains(response, day)
                self.assertContains(response, upcoming)
                self.assertNotContains(response, "released episodes not watched")

    def test_date_only_release_today_counts_down_instead_of_behind(self):
        tv, season = self._show("Date only", watched=3)
        # A date-only release keeps its sentinel time. It is not out until the
        # local date has ended, whatever the clock says.
        today = timezone.make_aware(
            datetime.combine(timezone.localdate(), time(0, 59, 59, 999999)),
        )
        Item.objects.create(
            title="Date only episode 4",
            media_id=tv.item.media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=4,
            release_datetime=today,
        )
        Event.objects.create(item=season.item, content_number=4, datetime=today)
        response = self._hydrated_home()
        self.assertEqual(self._chips(response), [("Today", 1, 4)])

    def test_feed_uses_released_next_targets_and_backlog_order(self):
        self._show("Newer", days_ago=2, watched=1)
        ended_backlog, _ = self._show("Older", days_ago=10, watched=2)
        Item.objects.filter(pk=ended_backlog.item_id).update(status="Canceled")
        self._show("Future", future=True)
        ended, _ = self._show("Caught up", watched=3)
        Item.objects.filter(pk=ended.item_id).update(status="Ended")
        self._show("Planning", status=Status.PLANNING.value)
        row = self._feed()
        self.assertEqual(
            [entry.item.title for entry in row["items"]], ["Older", "Newer", "Future"]
        )
        self.assertEqual(
            [entry.next_episode["episode_number"] for entry in row["items"]],
            [3, 2, 1],
        )

    def test_feed_ranks_backlog_then_release_then_recent_undated_shows(self):
        self._show("Three behind", watched=0, days_ago=1)
        self._show("One behind", watched=2, days_ago=20)
        self._show("Two behind", watched=1, days_ago=10)
        later, _ = self._show("Later release", future=True)
        Item.objects.filter(media_id=later.item.media_id).exclude(
            release_datetime=None,
        ).update(release_datetime=timezone.now() + timedelta(days=10))
        Event.objects.filter(item__media_id=later.item.media_id).update(
            datetime=timezone.now() + timedelta(days=10),
        )
        self._show("Sooner release", future=True)
        self._show("Older undated", watched=3, days_ago=30)
        self._show("Recent undated", watched=3, days_ago=2)
        self._show("Alpha undated", watched=3, days_ago=40)
        self.assertEqual(
            [entry.item.title for entry in self._feed()["items"]],
            [
                "One behind",
                "Two behind",
                "Three behind",
                "Sooner release",
                "Later release",
                "Recent undated",
                "Older undated",
                "Alpha undated",
            ],
        )

    def test_backlog_ties_and_missing_last_air_dates_use_title(self):
        self._show("Zebra backlog", watched=2, days_ago=20)
        self._show("Alpha backlog", watched=2, days_ago=1)
        for title in ("Zebra unknown", "Alpha unknown"):
            tv, _ = self._show(title, watched=3)
            Event.objects.filter(item__media_id=tv.item.media_id).delete()
            Item.objects.filter(media_id=tv.item.media_id).update(release_datetime=None)
        self.assertEqual(
            [entry.item.title for entry in self._feed()["items"]],
            ["Alpha backlog", "Zebra backlog", "Alpha unknown", "Zebra unknown"],
        )

    def test_backlog_order_is_applied_before_pagination(self):
        for number in range(30):
            self._show(f"A backlog {number:02d}", watched=0)
        self._show("Z one episode left", watched=2)
        first = self._feed()
        second = self._feed(page=2)
        self.assertEqual(first["items"][0].item.title, "Z one episode left")
        self.assertEqual(len(first["items"]), 30)
        self.assertEqual(
            [entry.item.title for entry in second["items"]], ["A backlog 29"]
        )

    def test_watching_an_episode_invalidates_cached_feed_order(self):
        self._show("A two left", watched=1)
        tv, _ = self._show("Z two left", watched=1)
        self.assertContains(self._hydrated_home(), "A two left")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("episode_save"),
                {
                    "media_id": tv.item.media_id,
                    "source": tv.item.source,
                    "season_number": 1,
                    "episode_number": 2,
                    "end_date": timezone.localtime().strftime("%Y-%m-%dT%H:%M:%S"),
                    "watch_operation_id": uuid4(),
                },
            )
        self.assertEqual(response.status_code, 302)
        response = self._hydrated_home()
        cards = BeautifulSoup(response.content, "html.parser").select(
            f"#media-grid-row-{self.row.pk} .home-row-card"
        )
        self.assertEqual(
            [card.img["alt"] for card in cards], ["Z two left", "A two left"]
        )

    def test_undated_sort_uses_episode_dates_without_calendar_events(self):
        self._show("Alpha older", watched=3, days_ago=30)
        recent, _ = self._show("Zebra newer", watched=3, days_ago=1)
        Event.objects.filter(item__media_id=recent.item.media_id).delete()
        self.assertEqual(
            [entry.item.title for entry in self._feed()["items"]],
            ["Zebra newer", "Alpha older"],
        )

    def test_finished_production_is_hidden_when_no_released_episodes_remain(self):
        for number, production_status in enumerate(
            ("Ended", "Canceled", "Cancelled", " FINISHED_AIRING ")
        ):
            tv, season = self._show(f"Finished show {number}", watched=3)
            Item.objects.filter(pk=tv.item_id).update(status=production_status)
            Event.objects.create(
                item=season.item,
                content_number=4,
                datetime=timezone.now() + timedelta(days=7),
            )
        response = self._hydrated_home()
        self.assertEqual(self._response_row(response)["total"], 0)
        self.assertEqual(self._response_row(response)["items"], [])
        self.assertNotContains(response, f'id="episode-feed-{self.row.pk}"')

    def test_ended_show_disappears_immediately_after_last_episode_is_watched(self):
        tv, _ = self._show("Ended backlog", watched=2)
        Item.objects.filter(pk=tv.item_id).update(status="Ended")
        self.assertContains(self._hydrated_home(), "Ended backlog")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("episode_save"),
                {
                    "media_id": tv.item.media_id,
                    "source": tv.item.source,
                    "season_number": 1,
                    "episode_number": 3,
                    "end_date": timezone.localtime().strftime("%Y-%m-%dT%H:%M:%S"),
                    "up_next_row_id": self.row.pk,
                    "watch_operation_id": uuid4(),
                },
                HTTP_HX_REQUEST="true",
            )
        self.assertEqual(response.status_code, 200)
        response = self._hydrated_home()
        self.assertNotContains(response, f'id="media-grid-row-{self.row.pk}"')
        self.assertEqual(self._response_row(response)["total"], 0)

    def test_standalone_feed_requires_login_and_only_shows_viewers_queue(self):
        self._show("My queued show")
        other = get_user_model().objects.create_user(username="other-feed")
        self._show("Other private show", user=other)
        response = self._hydrated_home()
        self.assertContains(response, "My queued show")
        self.assertNotContains(response, "Other private show")
        self.assertEqual(self._chips(response), [("3 Behind", 1, 1)])
        self.assertNotContains(response, "#all-episodes")
        self.assertNotContains(response, f"{reverse('discover')}?media_type=tv")
        self.assertContains(response, 'id="global-search"')
        self.assertTrue(
            HomeScreenRow.objects.filter(user=self.user, row_type="up_next").exists()
        )
        self.client.logout()
        response = self._hydrated_home()
        self.assertEqual(response.status_code, 302)
        self.assertIn("next=", response.url)

    def test_poster_card_shows_next_episode_and_only_released_backlog(self):
        tv, season = self._show("Poster show", watched=1)
        Item.objects.create(
            title="Future episode",
            media_id=tv.item.media_id,
            source=tv.item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=4,
            release_datetime=timezone.now() + timedelta(days=30),
        )
        Event.objects.create(
            item=season.item,
            content_number=4,
            datetime=timezone.now() + timedelta(days=30),
        )
        response = self._hydrated_home()
        card = BeautifulSoup(response.content, "html.parser").select_one(
            ".home-row-card"
        )
        self.assertEqual(card.select_one("img")["alt"], "Poster show")
        self.assertIn("poster.jpg", card.select_one("img")["src"])
        self.assertEqual(self._queue(card), ("2 Behind", 1, 2))
        self.assertEqual(
            self._response_row(response)["items"][0].media.episodes_left, 2
        )

    def test_unstarted_new_season_shows_released_backlog_before_future_episode(self):
        tv, _ = self._show("New season", watched=3)
        season_item = Item.objects.create(
            title=tv.item.title,
            media_id=tv.item.media_id,
            source=tv.item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=2,
        )
        for number in range(1, 6):
            release = timezone.now() + timedelta(days=4 if number == 5 else -number)
            Item.objects.create(
                title=f"New season episode {number}",
                media_id=tv.item.media_id,
                source=tv.item.source,
                media_type=MediaTypes.EPISODE.value,
                season_number=2,
                episode_number=number,
                release_datetime=release,
            )
            Event.objects.create(
                item=season_item, content_number=number, datetime=release
            )
        self._show("Two behind", watched=1)
        for calendar_synced in (True, False):
            with self.subTest(calendar_synced=calendar_synced):
                if not calendar_synced:
                    Event.objects.filter(item=season_item).delete()
                    cache.clear()
                response = self._hydrated_home()
                cards = BeautifulSoup(response.content, "html.parser").select(
                    f"#media-grid-row-{self.row.pk} .home-row-card"
                )
                self.assertEqual(
                    [card.img["alt"] for card in cards], ["Two behind", "New season"]
                )
                self.assertEqual(self._queue(cards[1]), ("4 Behind", 2, 1))
                self.assertNotIn("#all-episodes", str(cards[1]))
        self.assertFalse(
            Season.objects.filter(related_tv=tv, item__season_number=2).exists()
        )
        payload = {
            "media_id": tv.item.media_id,
            "source": tv.item.source,
            "season_number": 2,
            "episode_number": 1,
            "end_date": timezone.localtime().strftime("%Y-%m-%dT%H:%M:%S"),
            "watch_operation_id": uuid4(),
        }
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("episode_save"), payload)
        self.assertEqual(response.status_code, 302)
        chips = self._chips(self._hydrated_home())
        self.assertIn((2, 2), [chip[1:] for chip in chips])
        self.assertTrue(
            Season.objects.filter(related_tv=tv, item__season_number=2).exists()
        )

    def test_standard_episode_save_refreshes_home_queue(self):
        tv, season = self._show("Native queue", watched=1)
        payload = {
            "media_id": tv.item.media_id,
            "source": tv.item.source,
            "season_number": 1,
            "episode_number": 2,
            "end_date": timezone.localtime().strftime("%Y-%m-%dT%H:%M:%S"),
            "watch_operation_id": uuid4(),
        }
        self._hydrated_home()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(
                self.client.post(reverse("episode_save"), payload).status_code, 302
            )
        response = self._hydrated_home()
        self.assertEqual(self._chips(response), [("1 Behind", 1, 3)])
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("episode_save"), payload)
        self.assertEqual(
            Episode.objects.filter(
                related_season=season, item__episode_number=2
            ).count(),
            1,
        )
        payload["episode_number"] = 3
        payload["watch_operation_id"] = uuid4()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("episode_save"), payload)
        response = self._hydrated_home()
        self.assertContains(response, "Upcoming")
        self.assertContains(response, tv.item.title)
        self.assertEqual(Episode.objects.filter(related_season=season).count(), 3)

    def test_caught_up_show_counts_down_to_untracked_next_season(self):
        tv, _ = self._show("Next season", watched=3)
        season_item = Item.objects.create(
            title="Next season",
            media_id=tv.item.media_id,
            source=tv.item.source,
            media_type=MediaTypes.SEASON.value,
            season_number=2,
        )
        Event.objects.create(
            item=season_item,
            content_number=1,
            datetime=timezone.now() + timedelta(days=7),
        )
        response = self._hydrated_home()
        card = BeautifulSoup(response.content, "html.parser").select_one(
            f"#media-grid-row-{self.row.pk} .home-row-card"
        )
        self.assertEqual(
            self._response_row(response)["items"][0].next_episode["days_until"], 7
        )
        self.assertEqual(self._queue(card), ("7 days", 2, 1))
        self.assertIsNone(card.select_one("form"))

    def test_upcoming_without_date_excludes_finished_shows_before_pagination(self):
        ongoing, _ = self._show("Waiting for renewal", watched=3)
        for index in range(31):
            ended, _ = self._show(f"Ended {index}", watched=3)
            Item.objects.filter(pk=ended.item_id).update(status="  Finished_Airing  ")
        row = self._feed()
        self.assertEqual(row["total"], 1)
        self.assertEqual([entry.item.pk for entry in row["items"]], [ongoing.item_id])
        self.assertFalse(row["items"][0].next_episode["released"])
        self.assertIsNone(row["items"][0].next_episode["days_until"])

    def test_missing_release_dates_do_not_turn_metadata_total_into_released_target(
        self,
    ):
        tv, _ = self._show("Unknown dates", watched=0)
        Event.objects.filter(item__media_id=tv.item.media_id).delete()
        Item.objects.filter(media_id=tv.item.media_id).update(release_datetime=None)
        response = self._hydrated_home()
        self.assertContains(response, "Upcoming")
        self.assertNotContains(response, "Mark watched")
        self.assertFalse(
            self._response_row(response)["items"][0].next_episode["released"]
        )

    def test_unknown_calendar_date_is_upcoming_not_a_countdown(self):
        _, season = self._show("Unknown release", watched=3)
        Event.objects.create(
            item=season.item,
            content_number=4,
            datetime=timezone.now().replace(year=9999, month=12, day=31),
        )
        row = self._feed()
        self.assertEqual(row["items"][0].next_episode["days_until"], None)

    def test_future_item_date_works_before_calendar_sync(self):
        tv, _ = self._show("Next episode dated", watched=3)
        Item.objects.create(
            title="Coming next",
            media_id=tv.item.media_id,
            source=tv.item.source,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=4,
            release_datetime=timezone.now() + timedelta(days=2),
        )
        response = self._hydrated_home()
        target = self._response_row(response)["items"][0].next_episode
        self.assertEqual(target["days_until"], 2)
        self.assertEqual(target["title"], "Coming next")
        self.assertEqual(self._chips(response), [("2 days", 1, 4)])
        self.assertNotContains(response, "Mark watched")

    def test_episode_releasing_later_today_has_today_badge(self):
        _, season = self._show("Today episode", watched=3)
        now = timezone.localtime().replace(hour=8, minute=0, second=0, microsecond=0)
        Event.objects.create(
            item=season.item,
            content_number=4,
            datetime=now + timedelta(hours=2),
        )
        with patch("users.home_screen.timezone.now", return_value=now):
            response = self._hydrated_home()
        self.assertContains(response, "Today")
        self.assertNotContains(response, "Mark watched")

    def test_home_row_load_more_has_no_duplicates(self):
        for index in range(31):
            self._show(f"Queue {index:02}", days_ago=40 - index)
        first = self._hydrated_home()
        second = self.client.get(
            reverse("home"),
            {"load_row": self.row.pk, "offset": 14},
            HTTP_HX_REQUEST="true",
        )
        first_row = self._response_row(first)
        second_row = self._response_row(second)
        self.assertEqual(len(first_row["items"]), 14)
        self.assertEqual(len(second_row["items"]), 14)
        self.assertFalse(
            {e.item.pk for e in first_row["items"]}
            & {e.item.pk for e in second_row["items"]}
        )
        self.assertNotContains(second, "episode-feed-")
        self.assertContains(first, "data-home-row-wrapper")
        self.assertNotContains(second, "<section")
        self.assertEqual(second["X-Home-Row-Loaded"], "28")
        scroll = BeautifulSoup(first.content, "html.parser").select_one(
            f"#media-grid-row-{self.row.pk}"
        )
        self.assertEqual(scroll["hx-get"], f"{reverse('home')}?load_row={self.row.pk}")
        self.assertEqual(scroll["data-total-count"], "31")
        third = self.client.get(
            reverse("home"),
            {"load_row": self.row.pk, "offset": 28},
            HTTP_HX_REQUEST="true",
        )
        last = self._response_row(third)
        self.assertEqual(len(last["items"]), 3)
        self.assertEqual(third["X-Home-Row-Loaded"], "31")
        ids = [
            entry.item.pk
            for row in (first_row, second_row, last)
            for entry in row["items"]
        ]
        self.assertEqual(len(set(ids)), 31)

    def test_deferred_up_next_uses_the_same_native_row(self):
        self._show("Deferred show", watched=2)
        response = self.client.get(reverse("home_row_fragment", args=[self.row.pk]))
        self.assertContains(response, f'id="media-grid-row-{self.row.pk}"')
        self.assertContains(response, "home-row-card")
        self.assertEqual(self._chips(response), [("1 Behind", 1, 3)])
        self.assertNotContains(response, "episode-feed-")
