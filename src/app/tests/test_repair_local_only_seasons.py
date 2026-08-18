"""Tests for the repair_local_only_seasons management command."""

from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    ProviderMetadataStatus,
    Season,
    Sources,
    Status,
)


def _season_payload(episode_count, image=""):
    """Return provider season metadata with the given number of episodes."""
    return {
        "image": image,
        "episodes": [
            {"episode_number": number, "runtime": 24}
            for number in range(1, episode_count + 1)
        ],
    }


class RepairLocalOnlySeasonsTests(TestCase):
    """Verify the local-only season repair command."""

    def setUp(self):
        """Create a user and a local-only season with episode history."""
        self.user = get_user_model().objects.create_user(
            username="repair-user",
            password="12345",
        )
        self.show_item = Item.objects.create(
            media_id="96316",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.TV.value,
            title="Rent-a-Girlfriend",
            image="http://example.com/show.jpg",
        )
        self.tv = TV.objects.create(
            item=self.show_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        self.season_item = Item.objects.create(
            media_id="96316",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            library_media_type=MediaTypes.SEASON.value,
            season_number=5,
            title="Rent-a-Girlfriend",
            image="http://example.com/season.jpg",
            provider_metadata_status=(
                ProviderMetadataStatus.LOCAL_ONLY_MISSING_SEASON.value
            ),
        )
        self.season = Season.objects.create(
            item=self.season_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.IN_PROGRESS.value,
        )

    def _add_episode(self, episode_number):
        """Attach one watched episode to the local-only season."""
        episode_item = Item.objects.create(
            media_id="96316",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            library_media_type=MediaTypes.EPISODE.value,
            season_number=5,
            episode_number=episode_number,
            title="Rent-a-Girlfriend",
            image="http://example.com/episode.jpg",
        )
        return Episode.objects.create(
            item=episode_item,
            related_season=self.season,
            end_date="2026-07-26",
        )

    def _run(self, *args):
        """Run the command and return its captured stdout."""
        out = StringIO()
        call_command("repair_local_only_seasons", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_reports_without_writing(self):
        """The default run reports the planned move but changes nothing."""
        self._add_episode(1)

        def fake_tv_with_seasons(_media_id, season_numbers, _language=None):
            metadata = {
                "title": "Rent-a-Girlfriend",
                "image": "",
                "related": {
                    "seasons": [
                        {"season_number": 4, "episode_count": 12},
                        {"season_number": 5, "episode_count": 12},
                    ],
                },
            }
            if 5 in season_numbers:
                metadata["related"]["seasons"] = [
                    {"season_number": 5, "episode_count": 0},
                ]
            return metadata

        with patch(
            "app.providers.tmdb.tv_with_seasons",
            side_effect=fake_tv_with_seasons,
        ):
            output = self._run("--media-id", "96316")

        self.assertIn("DRY RUN", output)
        self.season_item.refresh_from_db()
        self.assertEqual(
            self.season_item.provider_metadata_status,
            ProviderMetadataStatus.LOCAL_ONLY_MISSING_SEASON.value,
        )

    def test_restores_season_when_provider_has_it_again(self):
        """A season the provider now knows about loses its local-only flag."""
        self._add_episode(1)
        self._add_episode(2)

        with patch(
            "app.providers.tmdb.tv_with_seasons",
            return_value={
                "title": "Rent-a-Girlfriend",
                "image": "",
                "related": {"seasons": [{"season_number": 5, "episode_count": 2}]},
                "season/5": _season_payload(2),
            },
        ):
            output = self._run("--media-id", "96316", "--apply")

        self.assertIn("clearing local-only flag", output)
        self.season_item.refresh_from_db()
        self.season.refresh_from_db()
        self.assertEqual(self.season_item.provider_metadata_status, "")
        self.assertEqual(self.season.status, Status.COMPLETED.value)

    def test_remaps_episodes_onto_provider_numbering(self):
        """Episodes spill into the season the provider actually has."""
        self._add_episode(1)

        def fake_tv_with_seasons(_media_id, season_numbers, _language=None):
            metadata = {
                "title": "Rent-a-Girlfriend",
                "image": "",
                "related": {
                    "seasons": [
                        {"season_number": 5, "episode_count": 0},
                        {"season_number": 6, "episode_count": 12},
                    ],
                },
            }
            if 6 in season_numbers:
                metadata["season/6"] = _season_payload(12)
            return metadata

        with patch(
            "app.providers.tmdb.tv_with_seasons",
            side_effect=fake_tv_with_seasons,
        ):
            output = self._run("--media-id", "96316", "--apply")

        self.assertIn("re-filing", output)
        self.assertTrue(
            Episode.objects.filter(
                item__media_id="96316",
                item__season_number=6,
                item__episode_number=1,
            ).exists(),
        )
        self.assertFalse(
            Episode.objects.filter(item__season_number=5).exists(),
        )

    def test_unresolvable_season_is_left_alone(self):
        """Without a provider season to move to, nothing is touched."""
        self._add_episode(1)

        with patch(
            "app.providers.tmdb.tv_with_seasons",
            return_value={
                "title": "Rent-a-Girlfriend",
                "image": "",
                "related": {"seasons": [{"season_number": 1, "episode_count": 12}]},
            },
        ):
            output = self._run("--media-id", "96316", "--apply")

        self.assertIn("no provider season found", output)
        self.season_item.refresh_from_db()
        self.assertEqual(
            self.season_item.provider_metadata_status,
            ProviderMetadataStatus.LOCAL_ONLY_MISSING_SEASON.value,
        )
        self.assertTrue(Episode.objects.filter(item__season_number=5).exists())
