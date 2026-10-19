import json
from datetime import timedelta
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
        return response.context["row"]

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

    def test_home_settings_save_up_next_columns_for_each_row(self):
        self._show("Column preview")
        for media_type in ("all", "tv"):
            for columns in (2, 3, 4):
                with self.subTest(media_type=media_type, columns=columns):
                    payload = [
                        {
                            "media_type": media_type,
                            "rows": [
                                {
                                    "row_type": "up_next",
                                    "columns": columns,
                                }
                            ],
                        }
                    ]
                    response = self.client.post(
                        reverse("home_screen"),
                        {
                            "home_screen_sections": json.dumps(payload),
                        },
                    )
                    self.assertEqual(response.status_code, 302)
                    self.row = HomeScreenRow.objects.get(
                        user=self.user, row_type="up_next"
                    )
                    self.assertEqual(self.row.columns, columns)
                    self.assertEqual(self.row.sort_by, "episode_feed")
                    self.assertEqual(self.row.direction, "asc")
                    self.assertContains(
                        self.client.get(reverse("home")),
                        f"repeat({columns}, minmax(0, 1fr))",
                    )
                    self.assertContains(
                        self.client.get(reverse("home_screen")),
                        'x-model.number="row.columns"',
                    )

    def test_home_rows_keep_independent_grid_columns(self):
        tv, _ = self._show("Shared library")
        second = HomeScreenRow.objects.create(
            user=self.user,
            media_type="all",
            row_type="up_next",
            sort_by="episode_feed",
            direction="asc",
            columns=4,
            position=1,
        )
        response = self.client.get(reverse("home"))
        soup = BeautifulSoup(response.content, "html.parser")
        for row, columns in ((self.row, 2), (second, 4)):
            grid = soup.select_one(f"#episode-feed-{row.pk} > .grid")
            self.assertIn(f"repeat({columns}, minmax(0, 1fr))", grid["style"])
        response = self.client.post(reverse("episode_save"), {
            "up_next_row_id": second.pk,
            "media_id": tv.item.media_id, "source": tv.item.source,
            "season_number": 1, "episode_number": 1,
            "end_date": timezone.localtime().strftime("%Y-%m-%dT%H:%M:%S"),
            "watch_operation_id": uuid4(),
        }, HTTP_HX_REQUEST="true")
        self.assertContains(response, "repeat(4, minmax(0, 1fr))")
        self.assertContains(response, f'id="episode-feed-{second.pk}"')
        self.assertNotContains(response, f'id="episode-feed-{self.row.pk}"')

    def test_invalid_up_next_settings_do_not_replace_existing_rows(self):
        for media_type, columns in (("movie", 2), ("all", 5), ("tv", "bad")):
            with self.subTest(media_type=media_type, columns=columns):
                with self.assertRaises(home_screen.HomeScreenValidationError):
                    home_screen.save_home_screen_configuration(
                        self.user,
                        json.dumps(
                            [
                                {
                                    "media_type": media_type,
                                    "rows": [
                                        {"row_type": "up_next", "columns": columns}
                                    ],
                                },
                            ]
                        ),
                    )
                self.assertTrue(HomeScreenRow.objects.filter(pk=self.row.pk).exists())

    def test_up_next_watch_cannot_target_another_users_row(self):
        tv, season = self._show("Owned show", watched=1)
        other = get_user_model().objects.create_user(username="other-row-owner")
        other_row = HomeScreenRow.objects.create(
            user=other, media_type="tv", row_type="up_next"
        )
        response = self.client.post(
            reverse("episode_save"),
            {
                "up_next_row_id": other_row.pk,
                "media_id": tv.item.media_id,
                "source": tv.item.source,
                "season_number": 1,
                "episode_number": 2,
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Episode.objects.filter(related_season=season).count(), 1)
        response = self.client.get(
            reverse("home"), {"load_row": other_row.pk}, HTTP_HX_REQUEST="true"
        )
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
        ):
            with self.subTest(language=language):
                self.user.ui_language = language
                self.user.save(update_fields=["ui_language"])
                response = self.client.get(reverse("home"))
                self.assertContains(response, title)
                self.assertContains(response, behind)
                self.assertContains(response, day)
                self.assertContains(response, upcoming)
                self.assertNotContains(response, "released episodes not watched")

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
        self.assertEqual(
            [entry.item.title for entry in self._feed()["items"]],
            ["A two left", "Z two left"],
        )
        response = self.client.post(
            reverse("episode_save"),
            {
                "media_id": tv.item.media_id,
                "source": tv.item.source,
                "season_number": 1,
                "episode_number": 2,
                "end_date": timezone.localtime().strftime("%Y-%m-%dT%H:%M:%S"),
                "up_next_row_id": self.row.pk,
                "watch_operation_id": uuid4(),
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        cards = BeautifulSoup(response.content, "html.parser").select("article")
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
        response = self.client.get(reverse("home"))
        self.assertEqual(self._response_row(response)["total"], 0)
        self.assertEqual(self._response_row(response)["items"], [])
        self.assertNotContains(response, f'id="episode-feed-{self.row.pk}"')

    def test_ended_show_disappears_immediately_after_last_episode_is_watched(self):
        tv, _ = self._show("Ended backlog", watched=2)
        Item.objects.filter(pk=tv.item_id).update(status="Ended")
        self.assertContains(self.client.get(reverse("home")), "Ended backlog")
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
        self.assertNotContains(response, "Ended backlog")
        self.assertEqual(self._response_row(response)["total"], 0)

    def test_standalone_feed_requires_login_and_only_shows_viewers_queue(self):
        self._show("My queued show")
        other = get_user_model().objects.create_user(username="other-feed")
        self._show("Other private show", user=other)
        response = self.client.get(reverse("home"))
        self.assertContains(response, "My queued show")
        self.assertNotContains(response, "Other private show")
        self.assertContains(response, "S01E01")
        self.assertContains(response, "My queued show episode 1")
        self.assertContains(response, "#all-episodes")
        self.assertNotContains(response, f"{reverse('discover')}?media_type=tv")
        self.assertContains(response, 'id="global-search"')
        self.assertTrue(
            HomeScreenRow.objects.filter(user=self.user, row_type="up_next").exists()
        )
        self.client.logout()
        response = self.client.get(reverse("home"))
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
        response = self.client.get(reverse("home"))
        card = BeautifulSoup(response.content, "html.parser").select_one(
            f"#episode-feed-{self.row.pk} article"
        )
        self.assertEqual(card.select_one("img")["alt"], "Poster show")
        self.assertIn("poster.jpg", card.select_one("img")["src"])
        self.assertIn("S01E02", card.get_text())
        self.assertIn("Poster show episode 2", card.get_text())
        badge = card.select_one('[title="Released episodes not watched"]')
        self.assertEqual(" ".join(badge.stripped_strings), "2 Behind")
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
                response = self.client.get(reverse("home"))
                cards = BeautifulSoup(response.content, "html.parser").select("article")
                self.assertEqual(
                    [card.img["alt"] for card in cards], ["Two behind", "New season"]
                )
                self.assertIn("S02E01", cards[1].get_text())
                self.assertIn("New season episode 1", cards[1].get_text())
                self.assertIn("4 Behind", " ".join(cards[1].stripped_strings))
                form = cards[1].select_one("form")
                self.assertEqual(
                    form.select_one('[name="season_number"]')["value"], "2"
                )
                self.assertEqual(
                    form.select_one('[name="episode_number"]')["value"], "1"
                )
        self.assertFalse(
            Season.objects.filter(related_tv=tv, item__season_number=2).exists()
        )
        payload = {
            field["name"]: field.get("value", "") for field in form.select("input")
        }
        response = self.client.post(
            reverse("episode_save"), payload, HTTP_HX_REQUEST="true"
        )
        self.assertContains(response, "S02E02")
        self.assertTrue(
            Season.objects.filter(related_tv=tv, item__season_number=2).exists()
        )

    def test_standalone_watch_refreshes_queue_and_waits_for_continuation(self):
        tv, season = self._show("Standalone queue", watched=1)
        payload = {
            "media_id": tv.item.media_id,
            "source": tv.item.source,
            "season_number": 1,
            "episode_number": 2,
            "end_date": timezone.localtime().strftime("%Y-%m-%dT%H:%M:%S"),
            "up_next_row_id": self.row.pk,
            "watch_operation_id": uuid4(),
        }
        response = self.client.post(
            reverse("episode_save"),
            payload,
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(response, "S01E03")
        badge = BeautifulSoup(response.content, "html.parser").select_one(
            '[title="Released episodes not watched"]'
        )
        self.assertEqual(" ".join(badge.stripped_strings), "1 Behind")
        self.assertContains(response, f'id="episode-feed-{self.row.pk}"')
        self.assertNotContains(response, "<!DOCTYPE", html=False)
        retry = self.client.post(
            reverse("episode_save"),
            payload,
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(retry, "S01E03")
        self.assertEqual(
            Episode.objects.filter(
                related_season=season, item__episode_number=2
            ).count(),
            1,
        )
        payload["episode_number"] = 3
        payload["watch_operation_id"] = uuid4()
        response = self.client.post(
            reverse("episode_save"),
            payload,
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(response, "Upcoming")
        self.assertContains(response, f'id="episode-feed-{self.row.pk}"')
        self.assertContains(response, tv.item.title)
        self.assertNotContains(response, "Mark watched")
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
        response = self.client.get(reverse("home"))
        card = BeautifulSoup(response.content, "html.parser").select_one("article")
        self.assertEqual(
            self._response_row(response)["items"][0].next_episode["days_until"], 7
        )
        self.assertIn("S02E01", card.get_text())
        self.assertEqual(
            " ".join(card.select_one('[title="Next episode"]').stripped_strings),
            "7 days",
        )
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
        response = self.client.get(reverse("home"))
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
        response = self.client.get(reverse("home"))
        target = self._response_row(response)["items"][0].next_episode
        self.assertEqual(target["days_until"], 2)
        self.assertEqual(target["title"], "Coming next")
        self.assertContains(response, "S01E04")
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
            response = self.client.get(reverse("home"))
        self.assertContains(response, "Today")
        self.assertNotContains(response, "Mark watched")

    def test_home_row_load_more_has_no_duplicates(self):
        for index in range(31):
            self._show(f"Queue {index:02}", days_ago=40 - index)
        first = self.client.get(reverse("home"))
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
        self.assertContains(second, "offset=28")
        self.assertNotContains(second, "<section")
        self.assertEqual(second["X-Home-Row-Loaded"], "28")
