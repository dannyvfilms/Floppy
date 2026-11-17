"""TV and season reads build each watched episode once (assignment 49 C/D).

The season and show API read every watch of a show several times over (the
census in BENCH-12 counted about five), and the show page's second request
read every season's episodes twice. These pin one build per watch, and that
the answers did not change.
"""

from __future__ import annotations

import logging
from collections import Counter
from contextlib import contextmanager
from unittest.mock import patch

import requests
from django.db.models.signals import post_init
from django.test import RequestFactory, TestCase

from app import helpers
from app.models import TV, Episode, Item, MediaTypes, Season, Sources, Status
from app.tests import catalogue_fixtures as fx
from users.models import User


@contextmanager
def _built():
    counts = Counter()

    def receiver(sender, **_kwargs):
        counts[sender.__name__] += 1

    post_init.connect(receiver, weak=False, dispatch_uid="tv-builds-once")
    try:
        yield counts
    finally:
        post_init.disconnect(dispatch_uid="tv-builds-once")


class TvSeasonBuildsOnceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        from app.providers import services

        cls.fake = fx.FakeTmdb(passthrough=services.api_request)

        def offline(*_args, **_kwargs):
            raise requests.ConnectionError("offline in this test")

        for patcher in (
            patch("app.providers.services.api_request", side_effect=cls.fake),
            patch("requests.sessions.Session.request", offline),
            patch("celery.app.task.Task.apply_async"),
        ):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        logging.disable(logging.WARNING)
        cls.addClassCleanup(logging.disable, logging.NOTSET)
        super().setUpClass()

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="builds-once", password="x")
        cls.user.tv_enabled = True
        cls.user.save()
        cls.show = fx.build_tv_show(
            cls.fake, cls.user, seasons=3, episodes=12, prefix="builds-once"
        )
        cls.api = f"/api/v1/media/tv/tmdb/{cls.show.media_id}"

    def setUp(self):
        self.client.force_login(self.user)

    def _watches(self, season_number=None):
        rows = Episode.objects.filter(
            related_season__user=self.user,
            item__media_id=self.show.media_id,
        )
        if season_number is not None:
            rows = rows.filter(item__season_number=season_number)
        return rows.count()

    def _get(self, path):
        self.client.get(path)  # warm the provider cache
        with _built() as counts:
            response = self.client.get(path)
        self.assertEqual(response.status_code, 200, path)
        return response, counts

    def test_season_reads_each_watch_once(self):
        response, counts = self._get(f"{self.api}/1/")

        self.assertEqual(counts["Episode"], self._watches(season_number=1))
        episodes = response.json()["related"]["episodes"]
        self.assertEqual(len(episodes), 12)
        tracked = {row["item"]["episode_number"]: row for row in episodes}
        self.assertTrue(all(row["tracked"] for row in episodes))
        stored = dict(
            Episode.objects.filter(
                related_season__user=self.user,
                item__media_id=self.show.media_id,
                item__season_number=1,
            )
            .order_by("item__episode_number", "pk")
            .values_list("item__episode_number", "item_id"),
        )
        self.assertEqual(
            {number: row["id"] for number, row in tracked.items()},
            stored,
        )

    def test_season_episode_page_reads_only_its_page(self):
        response, counts = self._get(f"{self.api}/1/episodes/?limit=5")

        page = response.json()["results"]
        self.assertEqual(
            [row["item"]["episode_number"] for row in page], [1, 2, 3, 4, 5]
        )
        # The watches of these five episodes, not every watch of the season.
        page_watches = Episode.objects.filter(
            related_season__user=self.user,
            item__media_id=self.show.media_id,
            item__season_number=1,
            item__episode_number__lte=5,
        ).count()
        self.assertLess(page_watches, self._watches(season_number=1))
        self.assertEqual(counts["Episode"], page_watches)
        self.assertTrue(all(row["tracked"] for row in page))

    def test_untracked_episodes_still_reuse_stored_items(self):
        Episode.objects.filter(
            related_season__user=self.user,
            item__media_id=self.show.media_id,
            item__season_number=1,
            item__episode_number__gt=6,
        ).delete()
        # The fixture's show has two catalogue rows per episode (an older
        # blank-library one and the provider's); either is a stored row.
        episode_eight = Item.objects.filter(
            media_id=self.show.media_id,
            media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=8,
        )
        episode_eight.update(imdb_rating=8.4)

        response, counts = self._get(f"{self.api}/1/")

        rows = {
            row["item"]["episode_number"]: row
            for row in response.json()["related"]["episodes"]
        }
        self.assertEqual(counts["Episode"], self._watches(season_number=1))
        self.assertTrue(rows[6]["tracked"])
        self.assertFalse(rows[8]["tracked"])
        self.assertIn(rows[8]["id"], set(episode_eight.values_list("pk", flat=True)))
        self.assertEqual(rows[8]["item"]["imdb_rating"], 8.4)

    def test_show_reads_each_watch_once(self):
        response, counts = self._get(f"{self.api}/")

        self.assertEqual(counts["Episode"], self._watches())
        seasons = response.json()["related"]["seasons"]
        self.assertEqual([row["item"]["season_number"] for row in seasons], [1, 2, 3])
        self.assertTrue(all(row["consumption_id"] for row in seasons))

    def test_show_page_cards_reuse_the_show_seasons(self):
        path = f"/details/tmdb/tv/{self.show.media_id}/census?fragment=secondary"
        response, counts = self._get(path)

        self.assertEqual(counts["Episode"], self._watches())
        self.assertContains(response, "Season 3")

    def _queries(self, path):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as queries:
            self.client.get(path)
        return len(queries)

    def test_app_show_detail_reads_each_watch_once(self):
        path = f"{self.api}/detail/"
        response, counts = self._get(path)

        self.assertEqual(counts["Episode"], self._watches())
        payload = response.json()
        self.assertTrue(payload["tracking_entries"])
        # Not one catalogue query per watched episode (watch time used to
        # fetch each one); a fixed number whatever the show's length.
        self.assertLess(self._queries(path), 40)

    def test_app_season_detail_reads_each_watch_once(self):
        path = f"{self.api}/detail/?detail_type=season&season_number=1"
        response, counts = self._get(path)

        self.assertIn("Progress:", response.json()["activity_subtitle"]["primary_text"])
        # The page shows one season row (the first stored season Item's);
        # each of its watches is built once.
        season_item = (
            Item.objects.filter(
                media_id=self.show.media_id,
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                season_number=1,
            )
            .exclude(library_media_type=MediaTypes.ANIME.value)
            .first()
        )
        shown = Episode.objects.filter(
            related_season__item=season_item, related_season__user=self.user
        ).count()
        self.assertGreater(shown, 0)
        self.assertEqual(counts["Episode"], shown)
        self.assertLess(self._queries(path), 30)


class PreloadedSeasonCardsTests(TestCase):
    """The season cards use the page's rows only when they are the same rows."""

    def setUp(self):
        self.user = User.objects.create_user(username="cards", password="x")
        self.request = RequestFactory().get("/")
        self.request.user = self.user
        show = Item.objects.create(
            media_id="9900001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Cards",
        )
        self.tv = TV.objects.create(
            item=show, user=self.user, status=Status.IN_PROGRESS.value
        )
        self.season_items = {
            number: Item.objects.create(
                media_id="9900001",
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                title="Cards",
                season_number=number,
            )
            for number in (1, 2)
        }
        self.seasons = {
            number: Season.objects.get_or_create(
                item=item,
                user=self.user,
                defaults={"related_tv": self.tv, "status": Status.IN_PROGRESS.value},
            )[0]
            for number, item in self.season_items.items()
        }
        self.cards = [
            {
                "media_id": "9900001",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.SEASON.value,
                "season_number": number,
                "title": "Cards",
            }
            for number in (1, 2)
        ]

    def _enrich(self, preloaded):
        with patch(
            "app.models.manager.MediaManager.annotate_max_progress", return_value=None
        ):
            return helpers.enrich_items_with_user_data(
                self.request, self.cards, preloaded_seasons=preloaded
            )

    def test_uses_preloaded_rows_when_they_are_the_whole_answer(self):
        preloaded = list(Season.objects.filter(user=self.user).select_related("item"))
        enriched = self._enrich(preloaded)

        self.assertEqual(
            [entry["media"] for entry in enriched],
            [self.seasons[1], self.seasons[2]],
        )
        self.assertIs(
            enriched[0]["media"],
            next(s for s in preloaded if s.pk == self.seasons[1].pk),
        )

    def test_falls_back_when_a_row_is_missing(self):
        # Only season 1 came from the page; season 2 must still be found.
        preloaded = list(
            Season.objects.filter(pk=self.seasons[1].pk).select_related("item")
        )
        enriched = self._enrich(preloaded)

        self.assertEqual(
            [entry["media"].pk for entry in enriched],
            [self.seasons[1].pk, self.seasons[2].pk],
        )
        self.assertIsNot(enriched[0]["media"], preloaded[0])
