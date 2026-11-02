"""What a client reads to offer Floppy as a library source.

NuvioTV's Sources, Library Source list shows providers that can read a user's
saved titles. Floppy's saved titles are the entries with status Planning, and
a client reads them from the tracked-media list. These tests pin that read as
the contract (see "Library source" in `docs/integrations/nuvio-client-guide.md`):
a default tracking token can page through it, filter it by type and status,
identify each title by provider id, and tell the titles it cannot place apart.
"""

from http import HTTPStatus as HTTP  # noqa: N814

from app.models import Game, Item, Movie, Status
from app.models.choices import MediaTypes, Sources
from integrations.models import IntegrationToken

from .base import FloppyApiTestCase

MEDIA = "/api/v1/media/"


class NuvioLibrarySourceTests(FloppyApiTestCase):
    """Reading saved titles with the credential a client is given."""

    def setUp(self):
        """Mint a tracking token and save a few titles."""
        super().setUp()
        _, secret = IntegrationToken.generate(
            user=self.user1,
            name="Nuvio library source",
        )
        self.headers = {"HTTP_X_API_KEY": secret}
        self.saved = [self._movie(f"{9100 + n}", f"Saved {n}") for n in range(5)]

    def _movie(self, media_id, title, status=Status.PLANNING.value, user=None):
        item = Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title=title,
            provider_external_ids={"imdb_id": f"tt{media_id.zfill(7)}"},
        )
        return Movie.objects.create(item=item, user=user or self.user1, status=status)

    def _saved(self, path=MEDIA, **params):
        response = self.client.get(
            path,
            {"status": "planning", **params},
            **self.headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        return response.json()

    def test_a_default_token_can_read_saved_titles(self):
        """The default tracking preset needs no extra scope for a library read."""
        body = self._saved()

        self.assertEqual(body["pagination"]["total"], 5)

    def test_each_saved_title_carries_the_ids_a_client_maps_on(self):
        """A title is identified by source and media_id, with ids when stored."""
        body = self._saved(MEDIA + "movie/", limit=1)

        entry = body["results"][0]["item"]
        self.assertEqual(entry["source"], "tmdb")
        self.assertEqual(entry["media_type"], "movie")
        self.assertTrue(entry["media_id"])
        self.assertTrue(entry["ids"]["imdb"].startswith("tt"))

    def test_only_saved_titles_are_returned(self):
        """Watched and in-progress titles are not part of the library source."""
        self._movie("9001", "Watched", Status.COMPLETED.value)
        self._movie("9002", "Watching", Status.IN_PROGRESS.value)

        titles = {row["item"]["title"] for row in self._saved()["results"]}

        self.assertEqual(titles, {f"Saved {n}" for n in range(5)})

    def test_paging_walks_every_saved_title_once(self):
        """Following offsets returns each title exactly once, then stops."""
        seen = []
        offset = 0
        while True:
            body = self._saved(limit=2, offset=offset)
            seen += [row["item"]["media_id"] for row in body["results"]]
            if not body["pagination"]["next"]:
                break
            offset += 2

        self.assertEqual(
            sorted(seen),
            sorted(item.item.media_id for item in self.saved),
        )

    def test_a_title_the_client_cannot_place_is_named_by_its_source(self):
        """A game has no TMDB id; its source lets a client skip it instead of guessing."""
        item = Item.objects.create(
            media_id="1942",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="A Game",
        )
        Game.objects.create(item=item, user=self.user1, status=Status.PLANNING.value)

        rows = self._saved()["results"]

        sources = {row["item"]["source"] for row in rows}
        self.assertEqual(sources, {"tmdb", "igdb"})
        movies = self._saved(MEDIA + "movie/")["results"]
        self.assertEqual({row["item"]["source"] for row in movies}, {"tmdb"})

    def test_one_account_never_reads_anothers_saved_titles(self):
        """The library source is scoped to the token's owner."""
        self._movie("9003", "Someone else's", user=self.user2)

        titles = {row["item"]["title"] for row in self._saved()["results"]}

        self.assertNotIn("Someone else's", titles)
        self.assertEqual(len(titles), 5)

    def test_an_unreadable_filter_is_a_client_error_not_an_empty_library(self):
        """A bad status must not look like an empty library."""
        response = self.client.get(MEDIA, {"status": "nonsense"}, **self.headers)

        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
