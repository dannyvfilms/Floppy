from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from app.models import CollectionEntry, Item, MediaTypes, Season, Sources, Status

GROUP_TYPES = [
    MediaTypes.MOVIE.value,
    MediaTypes.TV.value,
    MediaTypes.ANIME.value,
    MediaTypes.BOOK.value,
    MediaTypes.GAME.value,
    MediaTypes.MANGA.value,
]


class CollectionGroupByTypeQueriesTest(TestCase):
    """Grouped collection decoration runs once, not once per media type."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="grp", password="12345"
        )
        self.client.login(username="grp", password="12345")
        for media_type in GROUP_TYPES:
            for n in range(5):
                item = Item.objects.create(
                    media_id=f"{media_type}{n}",
                    source=Sources.MANUAL.value
                    if media_type in (MediaTypes.BOOK.value, MediaTypes.GAME.value)
                    else Sources.TMDB.value
                    if media_type in (MediaTypes.MOVIE.value, MediaTypes.TV.value)
                    else Sources.MAL.value,
                    media_type=media_type,
                    title=f"{media_type} {n}",
                    image="http://example.com/x.jpg",
                )
                CollectionEntry.objects.create(user=self.user, item=item)
                if media_type == MediaTypes.TV.value:
                    season = Item.objects.create(
                        media_id=item.media_id,
                        source=item.source,
                        media_type=MediaTypes.SEASON.value,
                        season_number=1,
                        title=item.title,
                        image=item.image,
                    )
                    CollectionEntry.objects.create(user=self.user, item=season)

    def test_grouped_query_count_does_not_scale_per_type(self):
        """Six media types render in 29 queries (44 before decorating once)."""
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse("collection_list"), {"group": "type"})
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(ctx), 30)
