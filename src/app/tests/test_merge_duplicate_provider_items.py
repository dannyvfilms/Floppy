"""Tests for the merge_duplicate_provider_items repair command (#620)."""

from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from app.models import TV, Item, MediaTypes, Sources, Status


class MergeDuplicateProviderItemsTests(TestCase):
    """A verified TMDB/TVDB duplicate pair is reported, then merged with --apply."""

    def setUp(self):
        """Create a user tracking the same show under both TMDB and TVDB."""
        self.user = get_user_model().objects.create_user(
            username="dup-tracker",
            password="12345",
        )
        self.tmdb_item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            image="",
            provider_external_ids={"tvdb_id": "81189"},
        )
        TV.objects.create(
            item=self.tmdb_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        self.tvdb_item = Item.objects.create(
            media_id="81189",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            image="",
        )
        self.tvdb_enabled_patcher = patch(
            "app.management.commands.merge_duplicate_provider_items.tvdb.enabled",
            return_value=True,
        )
        self.tvdb_enabled_patcher.start()
        self.addCleanup(self.tvdb_enabled_patcher.stop)

    def test_dry_run_reports_without_writing(self):
        """A dry run lists the proposed merge but changes nothing."""
        out = StringIO()
        call_command("merge_duplicate_provider_items", stdout=out)

        output = out.getvalue()
        self.assertIn("Would merge", output)
        self.assertIn("Breaking Bad", output)
        self.assertTrue(Item.objects.filter(pk=self.tmdb_item.pk).exists())
        self.assertTrue(Item.objects.filter(pk=self.tvdb_item.pk).exists())

    @patch("app.models.tv.TV._start_next_available_season")
    @patch("app.services.tv_provider_migration.tvdb.tv_with_seasons")
    def test_apply_merges_the_duplicate(
        self,
        mock_tv_with_seasons,
        _mock_start_next_season,
    ):
        """--apply merges the TMDB duplicate onto the existing TVDB item."""
        mock_tv_with_seasons.return_value = {
            "media_id": "81189",
            "title": "Breaking Bad",
            "image": "",
        }

        out = StringIO()
        call_command("merge_duplicate_provider_items", "--apply", stdout=out)

        output = out.getvalue()
        self.assertIn("Merged", output)
        self.assertFalse(Item.objects.filter(pk=self.tmdb_item.pk).exists())
        self.assertTrue(
            TV.objects.filter(item=self.tvdb_item, user=self.user).exists(),
        )

    def test_skips_when_no_verified_counterpart(self):
        """A show with no TVDB counterpart is left untouched and not counted."""
        self.tvdb_item.delete()

        out = StringIO()
        call_command("merge_duplicate_provider_items", stdout=out)

        self.assertIn("Would merge: 0", out.getvalue())
        self.assertTrue(Item.objects.filter(pk=self.tmdb_item.pk).exists())

    def test_username_filters_to_that_users_shows(self):
        """--username scopes the check to shows tracked by that user."""
        other_user = get_user_model().objects.create_user(
            username="other",
            password="12345",
        )

        out = StringIO()
        call_command(
            "merge_duplicate_provider_items",
            f"--username={other_user.username}",
            stdout=out,
        )

        self.assertIn("checking 0 TMDB TV item(s)", out.getvalue())

    def test_skips_entirely_when_tvdb_not_configured(self):
        """No candidates are examined when TVDB isn't configured."""
        with patch(
            "app.management.commands.merge_duplicate_provider_items.tvdb.enabled",
            return_value=False,
        ):
            out = StringIO()
            call_command("merge_duplicate_provider_items", stdout=out)

        self.assertIn("not configured", out.getvalue())
