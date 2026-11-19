"""The artist page and its API send a page of each release group (prompt 49-B).

Every album still counts towards the group sizes, the release count, the
plays and the listening dates; only the first ``ARTIST_ALBUM_PAGE_SIZE``
albums of a group are drawn, and the rest load a page at a time on the web
page ("Show more") and through ``/api/v1/music/artists/{id}/albums/``.
"""

from __future__ import annotations

from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from app.models import Album, AlbumArtist, Music
from app.music_artist_page import ARTIST_ALBUM_PAGE_SIZE
from app.tests import catalogue_fixtures as fx
from users.models import User

PAGE = ARTIST_ALBUM_PAGE_SIZE


def _cards(html):
    return html.count('data-media-type="music"')


@patch("app.music_page_repair.queue_artist_repair", return_value=False)
class ArtistDiscographyPagesTests(TestCase):
    """A long discography: 30 albums plus 2 singles, every track played twice."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="artist-pages")
        cls.artist = fx.build_artist(cls.user, albums=PAGE + 6, prefix="pages")
        # Two singles credited to the artist through artist_credits only.
        for number in range(2):
            single = Album.objects.create(
                title=f"Single {number}", release_type="Single"
            )
            AlbumArtist.objects.create(album=single, artist=cls.artist, position=0)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.user)

    # -- web ---------------------------------------------------------------

    def _page(self):
        response = self.client.get(
            reverse("artist_detail", args=[self.artist.id]),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        return response

    def test_page_draws_the_first_page_of_each_group_with_full_counts(self, _repair):
        response = self._page()
        html = response.content.decode()
        groups = response.context["discography_groups"]

        self.assertEqual([group["label"] for group in groups], ["Album", "Single"])
        self.assertEqual([group["count"] for group in groups], [PAGE + 6, 2])
        self.assertEqual([len(group["albums"]) for group in groups], [PAGE, 2])
        self.assertEqual(_cards(html), PAGE + 2)
        self.assertEqual(response.context["total_releases"], PAGE + 8)
        self.assertIn(f"{PAGE + 6} releases", html)
        self.assertIn("Show more (6 remaining)", html)
        self.assertIn(f'value="{PAGE}:Album"', html)
        self.assertIn('value="2:Single"', html)
        # Every track of every album was played twice.
        self.assertEqual(response.context["total_plays"], (PAGE + 6) * 10)
        self.assertEqual(groups[0]["albums"][0].play_count, 10)

    def test_show_more_redraws_the_group_as_one_grid(self, _repair):
        response = self.client.get(
            reverse("artist_discography_more", args=[self.artist.id]),
            {"group": "Album", "offset": PAGE},
        )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        # One grid from the group's first album, so rows stay aligned.
        self.assertEqual(_cards(html), PAGE + 6)
        self.assertEqual(html.count("data-music-albums-root"), 1)
        self.assertIn("data-discography-group", html)
        self.assertIn(f'value="{PAGE + 6}:Album"', html)
        self.assertNotIn("Show more", html)
        # The play count travels in the album props; React draws "10 plays" from it.
        self.assertIn('"plays": 10', html)

    def test_show_more_for_an_unknown_group_is_not_found(self, _repair):
        response = self.client.get(
            reverse("artist_discography_more", args=[self.artist.id]),
            {"group": "Bootleg", "offset": 0},
        )
        self.assertEqual(response.status_code, 404)

    def test_cover_refresh_keeps_an_expanded_group_expanded(self, _repair):
        url = reverse("prefetch_artist_covers", args=[self.artist.id])

        collapsed = self.client.get(url).content.decode()
        expanded = self.client.get(
            url,
            {"shown": [f"{PAGE + 6}:Album", "2:Single"]},
        ).content.decode()

        self.assertEqual(_cards(collapsed), PAGE + 2)
        self.assertEqual(_cards(expanded), PAGE + 8)
        self.assertNotIn("Show more", expanded)
        self.assertIn("hx-include", collapsed)

    # -- API ---------------------------------------------------------------

    def test_api_sends_the_same_groups_and_pages_the_rest(self, _repair):
        payload = self.client.get(f"/api/v1/music/artists/{self.artist.id}/").json()

        self.assertEqual(payload["total_releases"], PAGE + 8)
        self.assertEqual(payload["total_plays"], (PAGE + 6) * 10)
        self.assertEqual(
            [
                (g["label"], g["count"], len(g["albums"]), g["next_offset"])
                for g in payload["discography"]
            ],
            [("Album", PAGE + 6, PAGE, PAGE), ("Single", 2, 2, None)],
        )
        self.assertEqual(len(payload["albums"]), PAGE + 2)
        self.assertEqual(payload["albums"][0]["play_count"], 10)

        rest = self.client.get(
            f"/api/v1/music/artists/{self.artist.id}/albums/",
            {"group": "Album", "offset": PAGE},
        ).json()
        self.assertEqual(rest["count"], PAGE + 6)
        self.assertEqual(len(rest["albums"]), 6)
        self.assertIsNone(rest["next_offset"])
        shown = {album["id"] for album in payload["discography"][0]["albums"]}
        self.assertFalse(shown & {album["id"] for album in rest["albums"]})

        small = self.client.get(
            f"/api/v1/music/artists/{self.artist.id}/albums/",
            {"group": "Album", "offset": 0, "limit": 5},
        ).json()
        self.assertEqual((len(small["albums"]), small["next_offset"]), (5, 5))
        missing = self.client.get(
            f"/api/v1/music/artists/{self.artist.id}/albums/",
            {"group": "Bootleg"},
        )
        self.assertEqual(missing.status_code, 404)

    def test_web_and_api_agree_on_albums_and_activity(self, _repair):
        web = self._page().context
        api = self.client.get(f"/api/v1/music/artists/{self.artist.id}/").json()

        web_ids = [a.id for g in web["discography_groups"] for a in g["albums"]]
        self.assertEqual(web_ids, [album["id"] for album in api["albums"]])
        subtitle = web["music_artist_activity_subtitle"]
        self.assertEqual(
            subtitle["date_start"].isoformat().replace("+00:00", "Z"),
            api["first_listened"],
        )
        self.assertEqual(
            subtitle["date_end"].isoformat().replace("+00:00", "Z"),
            api["last_listened"],
        )


@patch("app.music_page_repair.queue_artist_repair", return_value=False)
class ArtistPageCostTests(TestCase):
    """The page and API cost the same at 6 and 60 albums played twice each."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="artist-cost")
        cls.small = fx.build_artist(cls.user, albums=6, prefix="cost-small")
        cls.large = fx.build_artist(cls.user, albums=60, prefix="cost-large")

    def setUp(self):
        self.client.force_login(self.user)

    def _queries(self, path, **kwargs):
        cache.clear()
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(path, **kwargs)
        self.assertEqual(response.status_code, 200)
        return len(queries.captured_queries), response

    def test_queries_do_not_grow_with_albums_or_plays(self, _repair):
        for name in ("artist_detail",):
            small, _ = self._queries(reverse(name, args=[self.small.id]), follow=True)
            large, response = self._queries(
                reverse(name, args=[self.large.id]), follow=True
            )
            self.assertEqual(small, large)
            self.assertEqual(_cards(response.content.decode()), PAGE)

        small, _ = self._queries(f"/api/v1/music/artists/{self.small.id}/")
        large, response = self._queries(f"/api/v1/music/artists/{self.large.id}/")
        self.assertEqual(small, large)
        self.assertEqual(len(response.json()["albums"]), PAGE)

    def test_totals_count_an_entry_once_when_its_album_credits_the_artist_twice(
        self,
        _repair,
    ):
        album = Album.objects.filter(artist=self.small).first()
        AlbumArtist.objects.create(album=album, artist=self.small, position=0)
        plays = Music.history.model.objects.filter(
            id__in=Music.objects.filter(
                user=self.user, album__artist=self.small
            ).values("id"),
        ).count()

        web = self.client.get(
            reverse("artist_detail", args=[self.small.id]),
            follow=True,
        ).context
        api = self.client.get(f"/api/v1/music/artists/{self.small.id}/").json()

        self.assertEqual(plays, 60)
        self.assertEqual(web["total_plays"], plays)
        self.assertEqual(api["total_plays"], plays)
