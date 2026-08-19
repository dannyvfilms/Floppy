import datetime
from unittest.mock import patch
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import (
    TV,
    Anime,
    Book,
    Episode,
    Item,
    MediaTypes,
    Season,
    Sources,
    Status,
)

TEST_SEASON_EPISODES = [
    {
        "episode_number": 1,
        "name": "Episode 1",
        "still_path": None,
    },
    {
        "episode_number": 2,
        "name": "Episode 2",
        "still_path": None,
    },
]


def mock_get_media_metadata(
    media_type,
    _media_id,
    _source,
    _season_numbers=None,
    _episode_number=None,
):
    """Return deterministic metadata for season progress tests."""
    if media_type == MediaTypes.SEASON.value:
        return {
            "season_number": 1,
            "episodes": [episode.copy() for episode in TEST_SEASON_EPISODES],
            "max_progress": len(TEST_SEASON_EPISODES),
            "_tvdb_episode_image_map": {},
        }

    if media_type == MediaTypes.TV.value:
        return {
            "max_progress": len(TEST_SEASON_EPISODES),
            "related": {
                "seasons": [
                    {
                        "season_number": 1,
                    },
                ],
            },
        }

    if media_type == "tv_with_seasons":
        return {
            "season/1": {
                "episodes": [episode.copy() for episode in TEST_SEASON_EPISODES],
            },
        }

    raise AssertionError(f"Unexpected media type {media_type}")


def mock_find_next_episode(progress, episodes):
    """Return the next sequential episode number when available."""
    next_episode = progress + 1
    if next_episode > len(episodes):
        return None
    return next_episode


class ProgressEditSeason(TestCase):
    """Test for editing a season progress through views."""

    def setUp(self):
        """Prepare the database with a season and an episode."""
        self.get_media_metadata_patcher = patch(
            "app.models.providers.services.get_media_metadata",
            side_effect=mock_get_media_metadata,
        )
        self.find_next_episode_patcher = patch(
            "app.models.providers.tmdb.find_next_episode",
            side_effect=mock_find_next_episode,
        )
        self.get_media_metadata_patcher.start()
        self.find_next_episode_patcher.start()
        self.addCleanup(self.get_media_metadata_patcher.stop)
        self.addCleanup(self.find_next_episode_patcher.stop)

        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.item_season = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
        )
        self.season = Season.objects.create(
            item=self.item_season,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        item_ep = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=1,
        )
        Episode.objects.create(
            item=item_ep,
            related_season=self.season,
            end_date=datetime.datetime(2023, 6, 1, 0, 0, tzinfo=datetime.UTC),
        )

    def test_progress_increase(self):
        """Test the increase of progress for a season."""
        self.client.post(
            reverse(
                "progress_edit",
                kwargs={
                    "media_type": MediaTypes.SEASON.value,
                    "instance_id": self.season.id,
                },
            ),
            {
                "operation": "increase",
            },
        )

        self.assertEqual(
            Episode.objects.filter(item__media_id="1668").count(),
            2,
        )

        self.assertTrue(
            Episode.objects.filter(
                item__media_id="1668",
                item__episode_number=2,
            ).exists(),
        )

    def test_progress_decrease(self):
        """Test the decrease of progress for a season."""
        self.client.post(
            reverse(
                "progress_edit",
                kwargs={
                    "media_type": MediaTypes.SEASON.value,
                    "instance_id": self.season.id,
                },
            ),
            {
                "operation": "decrease",
            },
        )

        self.assertEqual(
            Episode.objects.filter(item__media_id="1668").count(),
            0,
        )


class ProgressEditTV(TestCase):
    """Test quick progress edits for a TV show through views."""

    def setUp(self):
        """Prepare the database with a TV show, season, and watched episode."""
        self.get_media_metadata_patcher = patch(
            "app.models.providers.services.get_media_metadata",
            side_effect=mock_get_media_metadata,
        )
        self.find_next_episode_patcher = patch(
            "app.models.providers.tmdb.find_next_episode",
            side_effect=mock_find_next_episode,
        )
        self.get_media_metadata_patcher.start()
        self.find_next_episode_patcher.start()
        self.addCleanup(self.get_media_metadata_patcher.stop)
        self.addCleanup(self.find_next_episode_patcher.stop)

        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.item_tv = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Friends",
            image="http://example.com/image.jpg",
        )
        self.tv = TV.objects.create(
            item=self.item_tv,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        self.item_season = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
        )
        self.season = Season.objects.create(
            item=self.item_season,
            user=self.user,
            related_tv=self.tv,
            status=Status.IN_PROGRESS.value,
        )

        item_ep = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=1,
        )
        Episode.objects.create(
            item=item_ep,
            related_season=self.season,
            end_date=datetime.datetime(2023, 6, 1, 0, 0, tzinfo=datetime.UTC),
        )

    def test_progress_increase(self):
        """Test the increase of progress for a TV show."""
        self.client.post(
            reverse(
                "progress_edit",
                kwargs={
                    "media_type": MediaTypes.TV.value,
                    "instance_id": self.tv.id,
                },
            ),
            {
                "operation": "increase",
            },
        )

        self.assertEqual(
            Episode.objects.filter(related_season=self.season).count(),
            2,
        )
        self.assertTrue(
            Episode.objects.filter(
                related_season=self.season,
                item__episode_number=2,
            ).exists(),
        )

    def test_progress_increase_retry_does_not_advance(self):
        """Retrying one rendered quick-progress request returns its original watch."""
        watch_operation_id = uuid4()
        url = reverse(
            "progress_edit",
            kwargs={
                "media_type": MediaTypes.TV.value,
                "instance_id": self.tv.id,
            },
        )

        first_response = self.client.post(
            url,
            {"operation": "increase", "watch_operation_id": watch_operation_id},
        )
        retry_response = self.client.post(
            url,
            {"operation": "increase", "watch_operation_id": watch_operation_id},
        )

        watched = Episode.objects.filter(related_season=self.season)
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(retry_response.status_code, 200)
        self.assertEqual(watched.count(), 2)
        self.assertTrue(watched.filter(item__episode_number=2).exists())
        returned_token = retry_response.content.decode().split(
            '"watch_operation_id": "',
            1,
        )[1].split('"', 1)[0]
        self.assertEqual(str(UUID(returned_token)), returned_token)
        self.assertNotEqual(returned_token, str(watch_operation_id))

    def test_progress_increase_rejects_malformed_operation_id_without_echo(self):
        malformed = "not-a-private-token"

        response = self.client.post(
            reverse(
                "progress_edit",
                kwargs={
                    "media_type": MediaTypes.TV.value,
                    "instance_id": self.tv.id,
                },
            ),
            {"operation": "increase", "watch_operation_id": malformed},
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotContains(response, malformed, status_code=400)

    def test_progress_increase_uses_same_next_episode_target_as_next_ep(self):
        """Quick update follows the later tracked season selected by Next ep."""
        from app.templatetags import app_tags
        from events.models import Event

        later_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=2,
        )
        later_season = Season.objects.create(
            item=later_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.PLANNING.value,
        )
        for episode_number in (1, 2):
            Event.objects.create(
                item=later_item,
                content_number=episode_number,
                datetime=datetime.datetime.now(datetime.UTC),
            )

        watched_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=2,
            episode_number=1,
        )
        Episode.objects.create(
            item=watched_item,
            related_season=later_season,
            end_date=datetime.datetime(2023, 6, 1, 0, 0, tzinfo=datetime.UTC),
        )

        next_ep_url = app_tags.next_episode_url(self.item_tv, self.tv)
        self.assertIn("/season/2/episode/2", next_ep_url)

        self.client.post(
            reverse(
                "progress_edit",
                kwargs={
                    "media_type": MediaTypes.TV.value,
                    "instance_id": self.tv.id,
                },
            ),
            {"operation": "increase"},
        )

        self.assertTrue(
            Episode.objects.filter(
                related_season=later_season,
                item__episode_number=2,
            ).exists(),
        )
        self.assertFalse(
            Episode.objects.filter(
                related_season=self.season,
                item__episode_number=2,
            ).exists(),
        )

    def test_progress_decrease(self):
        """Test the decrease of progress for a TV show."""
        self.client.post(
            reverse(
                "progress_edit",
                kwargs={
                    "media_type": MediaTypes.TV.value,
                    "instance_id": self.tv.id,
                },
            ),
            {
                "operation": "decrease",
            },
        )

        self.assertEqual(
            Episode.objects.filter(related_season=self.season).count(),
            0,
        )


class ProgressEditAnime(TestCase):
    """Test for editing an anime progress through views."""

    def setUp(self):
        """Prepare the database with an anime."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.item = Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Cowboy Bebop",
            image="http://example.com/image.jpg",
        )
        self.anime = Anime.objects.create(
            item=self.item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
            progress=2,
        )

    def test_progress_increase(self):
        """Test the increase of progress for an anime."""
        self.client.post(
            reverse(
                "progress_edit",
                kwargs={
                    "media_type": MediaTypes.ANIME.value,
                    "instance_id": self.anime.id,
                },
            ),
            {
                "operation": "increase",
            },
        )

        self.assertEqual(Anime.objects.get(item__media_id="1").progress, 3)

    def test_progress_decrease(self):
        """Test the decrease of progress for an anime."""
        self.client.post(
            reverse(
                "progress_edit",
                kwargs={
                    "media_type": MediaTypes.ANIME.value,
                    "instance_id": self.anime.id,
                },
            ),
            {
                "operation": "decrease",
            },
        )

        self.assertEqual(Anime.objects.get(item__media_id="1").progress, 1)


class ProgressEditBook(TestCase):
    """Test quick progress edits for a book through views."""

    def setUp(self):
        """Prepare the database with a 200-page book in progress."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        self.item = Item.objects.create(
            media_id="1",
            source=Sources.OPENLIBRARY.value,
            media_type=MediaTypes.BOOK.value,
            title="Dune",
            image="http://example.com/image.jpg",
            number_of_pages=200,
        )
        self.book = Book.objects.create(
            item=self.item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
            progress=50,
        )

    def _post(self, operation):
        return self.client.post(
            reverse(
                "progress_edit",
                kwargs={
                    "media_type": MediaTypes.BOOK.value,
                    "instance_id": self.book.id,
                },
            ),
            {"operation": operation},
        )

    def test_progress_increase_by_page(self):
        """Without the percentage preference, increase steps by 1 page."""
        self._post("increase")
        self.assertEqual(Book.objects.get(id=self.book.id).progress, 51)

    def test_progress_decrease_by_page(self):
        """Without the percentage preference, decrease steps by 1 page."""
        self._post("decrease")
        self.assertEqual(Book.objects.get(id=self.book.id).progress, 49)

    def test_progress_increase_by_percentage(self):
        """With the percentage preference, increase steps by 1% of the page count."""
        self.user.book_comic_manga_progress_percentage = True
        self.user.save(update_fields=["book_comic_manga_progress_percentage"])

        response = self._post("increase")

        updated_book = Book.objects.get(id=self.book.id)
        self.assertEqual(updated_book.progress, 52)
        self.assertIn("26%", response.content.decode())

    def test_progress_decrease_by_percentage(self):
        """With the percentage preference, decrease steps by 1% of the page count."""
        self.user.book_comic_manga_progress_percentage = True
        self.user.save(update_fields=["book_comic_manga_progress_percentage"])

        response = self._post("decrease")

        updated_book = Book.objects.get(id=self.book.id)
        self.assertEqual(updated_book.progress, 48)
        self.assertIn("24%", response.content.decode())
