from http import HTTPStatus as HTTP  # noqa: N814

from django.utils import timezone

from app.models import TV, CollectionEntry, Item, ItemTag, Season, Status, Tag
from events.models import Event

from .base import FloppyApiTestCase


class MediaListFilterParityTests(FloppyApiTestCase):
    """The API media lists share the web filter and next-episode semantics."""

    def setUp(self):
        """Create released, future, and dropped TV episode cases."""
        super().setUp()
        now = timezone.now()
        tv1 = self.tv_medias[0]
        tv2 = self.tv_medias[1]
        tv3 = self.tv_medias[2]
        TV.objects.filter(pk=tv1.pk).update(status=Status.IN_PROGRESS.value)
        TV.objects.filter(pk=tv2.pk).update(status=Status.COMPLETED.value)
        TV.objects.filter(pk=tv3.pk).update(status=Status.IN_PROGRESS.value)

        season1 = self.season_medias[0]
        season2 = self.season_medias[1]
        Season.objects.filter(pk=season1.pk).update(status=Status.IN_PROGRESS.value)
        Season.objects.filter(pk=season2.pk).update(status=Status.DROPPED.value)
        self.episode_medias[0].__class__.objects.filter(
            related_season=season1,
        ).update(status=Status.PLANNING.value, end_date=None)
        Event.objects.create(
            item=season1.item,
            content_number=1,
            datetime=now - timezone.timedelta(days=3),
        )
        Event.objects.create(
            item=season1.item,
            content_number=2,
            datetime=now - timezone.timedelta(days=1),
        )
        Event.objects.create(
            item=season1.item,
            content_number=3,
            datetime=now + timezone.timedelta(days=3),
        )
        Event.objects.create(
            item=season2.item,
            content_number=1,
            datetime=now - timezone.timedelta(days=1),
        )
        self.episode_medias[0].__class__.objects.filter(
            pk=self.episode_medias[0].pk,
        ).update(
            status=Status.COMPLETED.value,
            end_date=now - timezone.timedelta(hours=1),
        )

        future_item = Item.objects.create(
            media_id=tv3.item.media_id,
            source=tv3.item.source,
            media_type="season",
            title=tv3.item.title,
            image=tv3.item.image,
            season_number=1,
        )
        Season.objects.create(
            item=future_item,
            user=self.user1,
            related_tv=tv3,
            status=Status.IN_PROGRESS.value,
        )
        Event.objects.create(
            item=future_item,
            content_number=1,
            datetime=now + timezone.timedelta(days=10),
        )

    def _get_tv(self, **params):
        """Return a typed media-list response."""
        return self.client.get(
            "/api/v1/media/tv/",
            params,
            **self.auth_headers,
        )

    def test_not_caught_up_serializes_first_released_unwatched_episode(self):
        """Released episodes are returned while future-only episodes are not metadata."""
        response = self._get_tv(
            status="1",
            progress="not_caught_up",
            sort="next_episode_air_date",
            direction="asc",
        )
        self.assertEqual(response.status_code, HTTP.OK)
        results = {entry["item"]["media_id"]: entry for entry in response.json()["results"]}
        self.assertIn("1001", results, response.json())
        self.assertEqual(results["1001"]["next_episode"]["season_number"], 1)
        self.assertEqual(results["1001"]["next_episode"]["episode_number"], 2)
        self.assertIsNotNone(results["1001"]["next_episode"]["air_date"])
        self.assertIsNone(results["1003"]["next_episode"])

    def test_repeated_statuses_and_pagination_are_backward_compatible(self):
        """Repeated status values and limit/offset pagination preserve the contract."""
        response = self._get_tv(
            status=["1", "3"],
            sort="title_desc",
            limit=1,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertGreaterEqual(response.json()["pagination"]["total"], 2)
        next_url = response.json()["pagination"]["next"]
        self.assertIn("status=1", next_url)
        self.assertIn("status=3", next_url)

    def test_statusless_collection_and_tag_filters(self):
        """Collection-backed statusless items participate in the shared filters."""
        movie_item = Item.objects.create(
            media_id="704",
            source="tmdb",
            media_type="movie",
            title="Collected only movie",
            image="https://example.com/movie-4.jpg",
        )
        CollectionEntry.objects.create(
            user=self.user1,
            item=movie_item,
            media_type="digital",
            resolution="1080p",
        )
        tag = Tag.objects.create(user=self.user1, name="favorite")
        ItemTag.objects.create(tag=tag, item=movie_item)
        response = self.client.get(
            "/api/v1/media/movie/",
            {
                "status": "no_status",
                "collection": "collected",
                "tag": "favorite",
            },
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["pagination"]["total"], 1, response.json())
        result = response.json()["results"][0]
        self.assertFalse(result["tracked"])
        self.assertIsNone(result["next_episode"])

    def test_metadata_and_type_specific_filters(self):
        """Metadata filters compose and platform modes remain type-specific."""
        movie_item = self.items_by_type["movie"][0]
        release_datetime = timezone.now() - timezone.timedelta(days=2)
        Item.objects.filter(pk=movie_item.pk).update(
            genres=["Drama"],
            release_datetime=release_datetime,
            country="US",
            languages=["en"],
            authors=[{"name": "A. Author"}],
            format="digital",
            status="released",
        )
        filter_params = {
            "search": "Movie 1",
            "genre": "Drama",
            "year": str(release_datetime.year),
            "release": "released",
            "source": "tmdb",
            "media_status": "released",
            "language": "en",
            "country": "US",
            "origin": "US",
            "format": "digital",
            "author": "A. Author",
            "rating": "rated",
        }
        for name, value in filter_params.items():
            single_response = self.client.get(
                "/api/v1/media/movie/",
                {name: value},
                **self.auth_headers,
            )
            self.assertEqual(
                single_response.status_code,
                HTTP.OK,
                {
                    name: single_response.json(),
                    "exc_info": getattr(single_response, "exc_info", None),
                },
            )
        response = self.client.get(
            "/api/v1/media/movie/",
            filter_params,
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK, response.json())
        self.assertEqual(response.json()["pagination"]["total"], 1)

        game_item = self.items_by_type["game"][0]
        Item.objects.filter(pk=game_item.pk).update(platforms=["PC", "Switch"])
        response = self.client.get(
            "/api/v1/media/game/",
            {
                "platform": ["PC", "Switch"],
                "platform_mode": "and",
            },
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        self.assertEqual(response.json()["pagination"]["total"], 1)

    def test_invalid_filter_values_return_bad_request(self):
        """Invalid filter choices are explicit API errors instead of ignored filters."""
        for params in (
            {"status": "watched"},
            {"platform_mode": "xor"},
            {"tag_mode": "xor"},
            {"direction": "sideways"},
            {"year": "20"},
        ):
            response = self._get_tv(**params)
            self.assertEqual(response.status_code, HTTP.BAD_REQUEST, params)
