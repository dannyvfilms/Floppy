from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone
from requests import RequestException

from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Season,
    Sources,
    Status,
)
from app.models import tv as tv_models

User = get_user_model()

class ShowCompletionStatusTests(TestCase):
    """A completed season may only finish a show the provider calls finished."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )
        self.tv_item = Item.objects.create(
            media_id="1001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Alien: Earth",
        )
        self.season_item = Item.objects.create(
            media_id="1001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Alien: Earth Season 1",
            season_number=1,
        )
        self.tv = TV.objects.create(
            item=self.tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        self.season = Season.objects.create(
            item=self.season_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.IN_PROGRESS.value,
        )
        # Create 3 episodes for Season 1
        for i in range(1, 4):
            ep_item = Item.objects.create(
                media_id="1001",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title=f"Episode {i}",
                season_number=1,
                episode_number=i,
            )
            Episode.objects.create(
                item=ep_item,
                related_season=self.season,
                end_date=timezone.now(),
                status=Status.COMPLETED.value,
            )
    @patch("app.models.providers.services.get_media_metadata")
    def test_handle_completed_season_overwrites_in_progress_tv_when_no_future_seasons(
        self, mock_metadata
    ):
        """_handle_completed_season preserves TV.status IN_PROGRESS when TMDB has no unstarted seasons."""
        mock_metadata.return_value = {
            "title": "Alien: Earth",
            "details": {"status": "Returning Series"},
            "related": {"seasons": [{"season_number": 1}]},
        }
        self.tv.status = Status.IN_PROGRESS.value
        self.tv.save()
        self.season.status = Status.COMPLETED.value
        self.season.save()

        self.tv._handle_completed_season(completed_season_number=1)
        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.IN_PROGRESS.value)
    @patch("app.models.providers.services.get_media_metadata")
    def test_handle_completed_season_flips_tv_status_for_ended_show(
        self, mock_metadata
    ):
        """_handle_completed_season sets TV.status to COMPLETED when show is ended."""
        mock_metadata.return_value = {
            "title": "Alien: Earth",
            "details": {"status": "Ended"},
        }
        self.tv.status = Status.IN_PROGRESS.value
        self.tv.save()
        self.season.status = Status.COMPLETED.value
        self.season.save()

        self.tv._handle_completed_season(completed_season_number=1)
        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.COMPLETED.value)
    @patch("app.models.providers.services.get_media_metadata")
    def test_handle_completed_season_with_none_nested_metadata(self, mock_metadata):
        """_handle_completed_season handles None details and related dicts without crashing."""
        mock_metadata.return_value = {
            "details": None,
            "related": None,
            "status": None,
        }
        self.tv.status = Status.IN_PROGRESS.value
        self.tv.save()
        self.season.status = Status.COMPLETED.value
        self.season.save()

        # Should not raise AttributeError
        self.tv._handle_completed_season(completed_season_number=1)
        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.COMPLETED.value)
    @patch("app.models.providers.services.get_media_metadata")
    def test_handle_completed_season_leaves_status_alone_when_provider_fails(
        self, mock_metadata
    ):
        """A provider outage must not be read as "the show ended"."""
        mock_metadata.side_effect = RequestException("TMDB is down")
        self.tv.status = Status.IN_PROGRESS.value
        self.tv.save()
        self.season.status = Status.COMPLETED.value
        self.season.save()

        self.tv._handle_completed_season(completed_season_number=1)
        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.IN_PROGRESS.value)
    @patch("app.models.providers.services.get_media_metadata")
    def test_handle_completed_season_leaves_status_alone_for_unknown_status(
        self, mock_metadata
    ):
        """An unrecognized provider status is indeterminate, not "ended"."""
        mock_metadata.return_value = {
            "title": "Alien: Earth",
            "details": {"status": "Returning Series (renewed)"},
            "related": {"seasons": [{"season_number": 1}]},
        }
        self.tv.status = Status.IN_PROGRESS.value
        self.tv.save()
        self.season.status = Status.COMPLETED.value
        self.season.save()

        self.tv._handle_completed_season(completed_season_number=1)
        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.IN_PROGRESS.value)
    @patch("app.models.providers.services.get_media_metadata")
    def test_handle_completed_season_preserves_user_paused_ongoing_show(
        self, mock_metadata
    ):
        """An ongoing show is left alone whatever status the user chose."""
        mock_metadata.return_value = {
            "title": "Alien: Earth",
            "details": {"status": "Returning Series"},
            "related": {"seasons": [{"season_number": 1}]},
        }
        for user_status in (Status.PAUSED.value, Status.DROPPED.value):
            with self.subTest(status=user_status):
                self.tv.status = user_status
                self.tv.save()
                self.season.status = Status.COMPLETED.value
                self.season.save()

                self.tv._handle_completed_season(completed_season_number=1)
                self.tv.refresh_from_db()
                self.assertEqual(self.tv.status, user_status)
    @patch("app.models.providers.services.get_media_metadata")
    def test_handle_completed_season_preserves_ongoing_tvdb_series(self, mock_metadata):
        """TVDB spells an airing series "Continuing", which must count as ongoing."""
        mock_metadata.return_value = {
            "title": "Alien: Earth",
            "details": {"status": "Continuing"},
            "related": {"seasons": [{"season_number": 1}]},
        }
        self.tv.status = Status.IN_PROGRESS.value
        self.tv.save()
        self.season.status = Status.COMPLETED.value
        self.season.save()

        self.tv._handle_completed_season(completed_season_number=1)
        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.IN_PROGRESS.value)
    def test_production_status_classification(self):
        """Only a known terminal status may finalize a show."""
        self.assertEqual(
            tv_models.classify_production_status("Ended"),
            tv_models.PRODUCTION_STATUS_ENDED,
        )
        self.assertEqual(
            tv_models.classify_production_status("FINISHED_AIRING"),
            tv_models.PRODUCTION_STATUS_ENDED,
        )
        self.assertEqual(
            tv_models.classify_production_status("Continuing"),
            tv_models.PRODUCTION_STATUS_ONGOING,
        )
        self.assertEqual(
            tv_models.classify_production_status("Terminada"),
            tv_models.PRODUCTION_STATUS_UNKNOWN,
        )
        # "Released" is movie/anime vocabulary and is used for airing titles;
        # it must not finalize a TV show.
        self.assertEqual(
            tv_models.classify_production_status("Released"),
            tv_models.PRODUCTION_STATUS_UNKNOWN,
        )
        self.assertEqual(
            tv_models.classify_production_status(""),
            tv_models.PRODUCTION_STATUS_ABSENT,
        )
        self.assertEqual(
            tv_models.classify_production_status(None),
            tv_models.PRODUCTION_STATUS_ABSENT,
        )
