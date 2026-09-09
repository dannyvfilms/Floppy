"""Regression tests for TV completion identity and sparse-history status (#812).

Two defects are covered:

* Completing a show looked up its season ``Item`` in the ``season`` bucket
  alone. Imported seasons inherit the show's ``tv`` bucket, so the lookup
  missed and forked a second season + episode set, orphaning real watch dates.
* Season status was derived from the highest watched episode number, which is
  a position rather than a count, so a single late episode could complete a
  season.
"""

from datetime import UTC, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import TV, Episode, Item, MediaTypes, Season, Sources, Status
from events.models import Event

METADATA_PATH = "app.providers.services.get_media_metadata"

WATCHED_AT = datetime(2025, 4, 7, 5, 0, tzinfo=UTC)

SPARSE_METADATA = {
    "max_progress": 10,
    "related": {"seasons": [{"season_number": 1, "image": "s1.jpg"}]},
    "season/1": {
        "season_number": 1,
        "image": "s1.jpg",
        "episodes": [{"episode_number": n} for n in range(1, 11)],
    },
}

SHOW_METADATA = {
    "max_progress": 3,
    "related": {"seasons": [{"season_number": 1, "image": "s1.jpg"}]},
    "season/1": {
        "season_number": 1,
        "image": "s1.jpg",
        "episodes": [
            {"episode_number": 1},
            {"episode_number": 2},
            {"episode_number": 3},
        ],
    },
}


def season_identity_items(media_id="1396"):
    """Every Item row for one season identity, across all buckets."""
    return Item.objects.filter(
        media_id=media_id,
        source=Sources.TMDB.value,
        media_type=MediaTypes.SEASON.value,
        season_number=1,
    )


class ImportedSeasonReuseTests(TestCase):
    """Completing a show must reuse an imported season, not fork a new one."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="u", password="x")
        # The CSV/Trakt importers give season and episode items the show's
        # bucket rather than the canonical 'season'/'episode' ones.
        self.tv_item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.TV.value,
            title="Breaking Bad",
        )
        self.tv = TV.objects.create(
            item=self.tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        self.season_item = Item.objects.create(
            media_id="1396",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            library_media_type=MediaTypes.TV.value,
            title="Breaking Bad",
            season_number=1,
        )
        self.season = Season.objects.create(
            item=self.season_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.IN_PROGRESS.value,
        )
        for number in (1, 2, 3):
            episode_item = Item.objects.create(
                media_id="1396",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                library_media_type=MediaTypes.TV.value,
                title=f"Episode {number}",
                season_number=1,
                episode_number=number,
            )
            Episode.objects.create(
                item=episode_item,
                related_season=self.season,
                end_date=WATCHED_AT,
            )

    @patch(METADATA_PATH)
    def test_reuses_imported_season_item(self, mock_meta):
        """No second season Item is created in the canonical bucket."""
        mock_meta.return_value = SHOW_METADATA
        self.tv.status = Status.COMPLETED.value
        self.tv.save()

        self.assertEqual(season_identity_items().count(), 1)
        self.assertEqual(
            season_identity_items().first().library_media_type,
            MediaTypes.TV.value,
        )

    @patch(METADATA_PATH)
    def test_creates_no_second_season_row(self, mock_meta):
        """The existing Season row is reused rather than duplicated."""
        mock_meta.return_value = SHOW_METADATA
        self.tv.status = Status.COMPLETED.value
        self.tv.save()

        seasons = Season.objects.filter(user=self.user, related_tv=self.tv)
        self.assertEqual(seasons.count(), 1)
        self.assertEqual(seasons.first().pk, self.season.pk)

    @patch(METADATA_PATH)
    def test_preserves_existing_watch_dates(self, mock_meta):
        """Imported episode dates survive completion of the parent show."""
        mock_meta.return_value = SHOW_METADATA
        self.tv.status = Status.COMPLETED.value
        self.tv.save()

        episodes = Episode.objects.filter(related_season=self.season)
        self.assertEqual(episodes.count(), 3)
        for episode in episodes:
            self.assertEqual(episode.end_date, WATCHED_AT)

    @patch(METADATA_PATH)
    def test_creates_no_duplicate_episode_rows(self, mock_meta):
        """Episodes already present are not recreated with today's date."""
        mock_meta.return_value = SHOW_METADATA
        self.tv.status = Status.COMPLETED.value
        self.tv.save()

        numbers = list(
            Episode.objects.filter(
                related_season__related_tv=self.tv,
            ).values_list("item__episode_number", flat=True),
        )
        self.assertEqual(sorted(numbers), [1, 2, 3])

    @patch(METADATA_PATH)
    def test_concurrent_create_converges(self, mock_meta):
        """A row inserted between lookup and create must not raise.

        ``title_fields_from_metadata`` is evaluated while building the
        ``defaults`` argument, so creating the conflicting row there lands it
        between the bucket lookup and the create - the race the review flagged.
        """
        mock_meta.return_value = SHOW_METADATA
        self.season.delete()
        self.season_item.delete()

        original = Item.title_fields_from_metadata

        def insert_then_delegate(metadata, fallback_title=None):
            Item.objects.get_or_create(
                media_id="1396",
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                library_media_type=MediaTypes.SEASON.value,
                season_number=1,
                defaults={"title": "Breaking Bad"},
            )
            return original(metadata, fallback_title=fallback_title)

        with patch.object(
            Item,
            "title_fields_from_metadata",
            side_effect=insert_then_delegate,
        ):
            self.tv.status = Status.COMPLETED.value
            self.tv.save()  # must not raise IntegrityError

        self.assertEqual(season_identity_items().count(), 1)


class IdentityBucketBoundaryTests(TestCase):
    """Normal-TV and anime parent identities must not cross-attach (#623)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="u2", password="x")

    def _make_show(self, bucket):
        item = Item.objects.create(
            media_id="99001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=bucket,
            title="Show",
        )
        return TV.objects.create(
            item=item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

    def _make_foreign_season(self, bucket):
        return Item.objects.create(
            media_id="99001",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            library_media_type=bucket,
            title="Show",
            season_number=1,
        )

    @patch(METADATA_PATH)
    def test_anime_parent_ignores_tv_bucket_season(self, mock_meta):
        """An anime show must not adopt a normal-TV season item."""
        mock_meta.return_value = SHOW_METADATA
        foreign = self._make_foreign_season(MediaTypes.TV.value)
        show = self._make_show(MediaTypes.ANIME.value)

        show.status = Status.COMPLETED.value
        show.save()

        season = Season.objects.get(user=self.user, related_tv=show)
        self.assertNotEqual(season.item_id, foreign.pk)
        self.assertEqual(season.item.library_media_type, MediaTypes.ANIME.value)

    @patch(METADATA_PATH)
    def test_tv_parent_ignores_anime_bucket_season(self, mock_meta):
        """A normal-TV show must not adopt an anime season item."""
        mock_meta.return_value = SHOW_METADATA
        foreign = self._make_foreign_season(MediaTypes.ANIME.value)
        show = self._make_show(MediaTypes.TV.value)

        show.status = Status.COMPLETED.value
        show.save()

        season = Season.objects.get(user=self.user, related_tv=show)
        self.assertNotEqual(season.item_id, foreign.pk)
        self.assertNotEqual(season.item.library_media_type, MediaTypes.ANIME.value)


class SparseHistoryStatusTests(TestCase):
    """Completion is derived from distinct completed episodes, not position."""

    def setUp(self):
        patcher = patch(METADATA_PATH, return_value=SPARSE_METADATA)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = get_user_model().objects.create_user(username="u3", password="x")
        self.tv_item = Item.objects.create(
            media_id="55501",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Show",
        )
        self.tv = TV.objects.create(
            item=self.tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        self.season_item = Item.objects.create(
            media_id="55501",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show",
            season_number=1,
            local_season_episode_count=10,
        )
        self.season = Season.objects.create(
            item=self.season_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.PLANNING.value,
        )

    def _watch(self, number):
        episode_item, _ = Item.objects.get_or_create(
            media_id="55501",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            library_media_type=MediaTypes.EPISODE.value,
            season_number=1,
            episode_number=number,
            defaults={"title": f"Episode {number}"},
        )
        return Episode.objects.create(
            item=episode_item,
            related_season=self.season,
            end_date=WATCHED_AT,
        )

    def _reset_status(self, status):
        """Set status without save() side-effects (episode fan-out, etc.)."""
        Season.objects.filter(pk=self.season.pk).update(status=status)
        self.season.refresh_from_db()

    def _sync(self):
        if hasattr(self.season, "_episode_stats_cache"):
            del self.season._episode_stats_cache
        self.season._sync_status_after_episode_change()
        self.season.refresh_from_db()

    def test_late_single_episode_with_local_count_stays_in_progress(self):
        """E10 of 10 is one completed episode, not ten."""
        self._watch(10)
        self._reset_status(Status.PLANNING.value)
        self._sync()
        self.assertEqual(self.season.status, Status.IN_PROGRESS.value)

    def test_late_single_episode_with_release_events_stays_in_progress(self):
        """The release-event branch uses the same distinct count."""
        self.season_item.local_season_episode_count = None
        self.season_item.save(update_fields=["local_season_episode_count"])
        for number in range(1, 11):
            Event.objects.create(
                item=self.season_item,
                content_number=number,
                datetime=WATCHED_AT,
            )
        self._watch(10)
        # Without the reset, Episode.save() leaves the season In progress and
        # the rewatch override would hide a wrong Completed result.
        self._reset_status(Status.PLANNING.value)
        self._sync()
        self.assertEqual(self.season.status, Status.IN_PROGRESS.value)

    def test_all_distinct_episodes_complete_the_season(self):
        """Ten distinct completed episodes satisfy a local count of ten."""
        for number in range(1, 11):
            self._watch(number)
        self._sync()
        self.assertEqual(self.season.status, Status.COMPLETED.value)

    def test_duplicate_plays_do_not_complete_the_season(self):
        """Repeat plays of one episode are still one distinct episode."""
        for _ in range(10):
            self._watch(1)
        self._reset_status(Status.PLANNING.value)
        self._sync()
        self.assertEqual(self.season.status, Status.IN_PROGRESS.value)

    def test_manual_rewatch_override_remains_in_progress(self):
        """A deliberate In progress rewatch is not forced back to Completed."""
        for number in range(1, 11):
            self._watch(number)
        self.season.status = Status.IN_PROGRESS.value
        self.season.save(update_fields=["status"])
        self._sync()
        self.assertEqual(self.season.status, Status.IN_PROGRESS.value)

    def test_no_logged_episodes_returns_to_planning(self):
        """Unwatching the last episode must not leave the season Completed."""
        self.season.status = Status.COMPLETED.value
        self.season.save(update_fields=["status"])
        self._sync()
        self.assertEqual(self.season.status, Status.PLANNING.value)
