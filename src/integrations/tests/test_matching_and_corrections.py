from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Movie,
    MoviePlay,
    PlaybackProgress,
    ProgressChange,
    Season,
    Sources,
    Status,
)
from integrations.external_references import (
    ExternalReferenceReviewStatus,
    lookup_reference,
)
from integrations.match_corrections import (
    StaleCorrectionPreviewError,
    apply_match_correction,
    preview_match_correction,
)
from integrations.matching import unique_title_match
from integrations.models import ExternalReference


class MatchingSafetyTests(TestCase):
    """Title fallback only accepts one exact, year-compatible result."""

    def test_rejects_wrong_title_same_year_and_ambiguous_titles(self):
        results = [
            {"id": 1, "title": "The Other Film", "year": 2020},
            {"id": 2, "title": "The Film", "year": 2020},
        ]
        self.assertEqual(
            unique_title_match(results, "The Film", year=2020)["id"],
            2,
        )
        self.assertIsNone(
            unique_title_match(
                [
                    {"id": 1, "title": "The Film", "year": 2020},
                    {"id": 2, "title": "The Film", "year": 2020},
                ],
                "The Film",
                year=2020,
            )
        )

    def test_accepts_normalized_title_and_date_year(self):
        result = unique_title_match(
            [{"id": 8, "name": "A & B", "first_air_date": "2022-04-01"}],
            "A and B (2022)",
            year=2022,
        )
        self.assertEqual(result["id"], 8)


class MatchCorrectionTests(TestCase):
    """Corrections move this user's state and retain future source mappings."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="correction-user",
            password="password",
        )
        self.other_user = get_user_model().objects.create_user(
            username="other-correction-user",
            password="password",
        )

    def _item(self, media_id, media_type, title, **extra):
        return Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=media_type,
            title=title,
            **extra,
        )

    def test_movie_move_preserves_reliable_and_unidentified_plays(self):
        source = self._item("101", MediaTypes.MOVIE.value, "Wrong Movie")
        destination = self._item("202", MediaTypes.MOVIE.value, "Right Movie")
        source_movie = Movie.objects.create(
            user=self.user,
            item=source,
            status=Status.COMPLETED.value,
            progress=1,
        )
        Movie.objects.create(
            user=self.other_user,
            item=source,
            status=Status.COMPLETED.value,
            progress=1,
        )
        destination_movie = Movie.objects.create(
            user=self.user,
            item=destination,
            status=Status.COMPLETED.value,
            progress=1,
        )
        MoviePlay.objects.create(
            movie=source_movie,
            end_date="2024-01-01T00:00:00Z",
            external_id="plex:one",
        )
        MoviePlay.objects.create(
            movie=destination_movie,
            end_date="2024-01-01T00:00:00Z",
            external_id="plex:one",
        )
        MoviePlay.objects.create(
            movie=source_movie,
            end_date="2024-02-01T00:00:00Z",
        )
        PlaybackProgress.objects.create(
            user=self.user,
            item=source,
            position_seconds=50,
            duration_seconds=100,
        )
        ProgressChange.objects.create(
            user=self.user,
            item=source,
            sequence=1,
        )
        reference = ExternalReference.objects.create(
            user=self.user,
            integration="plex",
            source_account="server::account",
            external_namespace="plex_rating_key",
            external_identity="101",
            media_type=MediaTypes.MOVIE.value,
            matched_item=source,
        )
        preview = preview_match_correction(self.user, source, destination)

        with patch("app.models.Item.fetch_releases"):
            apply_match_correction(
                self.user,
                source.pk,
                destination.pk,
                preview["token"],
                reference_ids=[reference.pk],
            )

        self.assertFalse(Movie.objects.filter(user=self.user, item=source).exists())
        self.assertTrue(Movie.objects.filter(user=self.other_user, item=source).exists())
        self.assertEqual(
            destination_movie.plays.count(),
            2,
        )
        self.assertTrue(
            PlaybackProgress.objects.filter(user=self.user, item=destination).exists()
        )
        self.assertTrue(
            ProgressChange.objects.filter(user=self.user, item=destination).exists()
        )
        reference.refresh_from_db()
        self.assertEqual(reference.corrected_item_id, destination.pk)
        self.assertEqual(
            reference.review_status,
            ExternalReferenceReviewStatus.CORRECTED.value,
        )

    def test_stale_preview_is_rejected(self):
        source = self._item("301", MediaTypes.MOVIE.value, "Wrong")
        destination = self._item("302", MediaTypes.MOVIE.value, "Right")
        movie = Movie.objects.create(
            user=self.user,
            item=source,
            status=Status.COMPLETED.value,
            progress=1,
        )
        preview = preview_match_correction(self.user, source, destination)
        movie.notes = "changed after preview"
        movie.save(update_fields=["notes"])

        with self.assertRaises(StaleCorrectionPreviewError):
            apply_match_correction(
                self.user,
                source.pk,
                destination.pk,
                preview["token"],
            )

    def test_tv_move_applies_editable_episode_mapping(self):
        source = self._item("401", MediaTypes.TV.value, "Wrong Show")
        destination = self._item("402", MediaTypes.TV.value, "Right Show")
        source_tv = TV.objects.create(
            user=self.user,
            item=source,
            status=Status.IN_PROGRESS.value,
        )
        destination_tv = TV.objects.create(
            user=self.user,
            item=destination,
            status=Status.IN_PROGRESS.value,
        )
        source_season_item = self._item(
            "401",
            MediaTypes.SEASON.value,
            "Season 1",
            season_number=1,
        )
        source_season = Season.objects.create(
            user=self.user,
            item=source_season_item,
            related_tv=source_tv,
            status=Status.IN_PROGRESS.value,
        )
        episode_item = self._item(
            "401",
            MediaTypes.EPISODE.value,
            "Pilot",
            season_number=1,
            episode_number=1,
        )
        episode = Episode.objects.create(
            item=episode_item,
            related_season=source_season,
            end_date="2024-01-01T00:00:00Z",
        )
        preview = preview_match_correction(
            self.user,
            source,
            destination,
            episode_mapping={"1:1": {"season": 2, "episode": 3}},
        )
        with patch("app.models.Item.fetch_releases"):
            apply_match_correction(
                self.user,
                source.pk,
                destination.pk,
                preview["token"],
                episode_mapping={"1:1": {"season": 2, "episode": 3}},
            )

        episode.refresh_from_db()
        self.assertEqual(episode.related_season.related_tv_id, destination_tv.pk)
        self.assertEqual(episode.item.season_number, 2)
        self.assertEqual(episode.item.episode_number, 3)
        self.assertTrue(Season.objects.filter(related_tv=destination_tv).exists())

    def test_tv_move_to_untracked_destination_repoints_season_items(self):
        """Seasons must follow the show when the destination is not tracked yet.

        With no destination TV row the correction repoints the source row
        itself, so source and destination became the same row; the
        already-seen season map was then pre-filled with the source's own
        seasons and every season matched itself, leaving app_season.item on
        the old provider's season Item while the show and its episodes moved.
        Season lookups key off that Item, so the user's watches went
        invisible under the corrected identity.
        """
        source = Item.objects.create(
            media_id="501",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Wrong Show",
        )
        destination = self._item("502", MediaTypes.TV.value, "Right Show")
        source_tv = TV.objects.create(
            user=self.user,
            item=source,
            status=Status.IN_PROGRESS.value,
        )
        source_season_item = Item.objects.create(
            media_id="501",
            source=Sources.TVDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Season 1",
            season_number=1,
        )
        source_season = Season.objects.create(
            user=self.user,
            item=source_season_item,
            related_tv=source_tv,
            status=Status.IN_PROGRESS.value,
        )
        episode_item = Item.objects.create(
            media_id="501",
            source=Sources.TVDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Pilot",
            season_number=1,
            episode_number=1,
        )
        episode = Episode.objects.create(
            item=episode_item,
            related_season=source_season,
            end_date="2024-01-01T00:00:00Z",
        )

        preview = preview_match_correction(self.user, source, destination)
        with patch("app.models.Item.fetch_releases"):
            apply_match_correction(
                self.user,
                source.pk,
                destination.pk,
                preview["token"],
            )

        source_tv.refresh_from_db()
        source_season.refresh_from_db()
        episode.refresh_from_db()
        self.assertEqual(source_tv.item_id, destination.pk)
        self.assertEqual(source_season.item.media_id, "502")
        self.assertEqual(source_season.item.source, Sources.TMDB.value)
        self.assertEqual(source_season.item.season_number, 1)
        self.assertEqual(episode.item.media_id, "502")
        self.assertEqual(episode.item.source, Sources.TMDB.value)
        self.assertEqual(episode.related_season_id, source_season.pk)

    @patch("integrations.views.services.search")
    def test_match_fix_search_does_not_persist_candidate_items(self, mock_search):
        """Listing search results must not write an Item per candidate.

        The destination radio used to carry an Item pk, so rendering the
        result list materialized one Item per hit. A single search wrote
        rows for every unrelated show it returned, and the metadata
        backfill then fanned each one out into season, episode, person and
        calendar rows.
        """
        source = Item.objects.create(
            media_id="601",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Tracked Show",
        )
        TV.objects.create(
            user=self.user,
            item=source,
            status=Status.IN_PROGRESS.value,
        )
        mock_search.return_value = {
            "results": [
                {"media_id": "900", "title": "Right Show", "year": 2020},
                {"media_id": "901", "title": "Unrelated Show", "year": 2011},
            ],
        }
        self.client.force_login(self.user)

        before = set(Item.objects.values_list("pk", flat=True))
        response = self.client.get(
            reverse("match_fix", args=[source.pk]),
            {"q": "show"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Right Show")
        self.assertContains(response, "Unrelated Show")
        self.assertEqual(set(Item.objects.values_list("pk", flat=True)), before)
        self.assertFalse(
            Item.objects.filter(
                media_id__in=("900", "901"),
                source=Sources.TMDB.value,
            ).exists(),
        )

    @patch("integrations.views.services.search")
    def test_match_fix_preview_materializes_only_the_chosen_destination(
        self,
        mock_search,
    ):
        """Previewing one candidate creates that destination Item and no other."""
        source = Item.objects.create(
            media_id="602",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Tracked Show",
        )
        TV.objects.create(
            user=self.user,
            item=source,
            status=Status.IN_PROGRESS.value,
        )
        mock_search.return_value = {
            "results": [
                {"media_id": "910", "title": "Right Show", "year": 2020},
                {"media_id": "911", "title": "Unrelated Show", "year": 2011},
            ],
        }
        self.client.force_login(self.user)

        with patch("app.models.Item.fetch_releases"):
            response = self.client.post(
                reverse("match_fix", args=[source.pk]) + "?q=show",
                {"action": "preview", "destination_media_id": "910"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            Item.objects.filter(
                media_id="910",
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
            ).exists(),
        )
        self.assertFalse(
            Item.objects.filter(media_id="911", source=Sources.TMDB.value).exists(),
        )

    def test_reference_lookup_is_user_scoped(self):
        ExternalReference.objects.create(
            user=self.user,
            integration="trakt",
            source_account="account",
            external_namespace="trakt",
            external_identity="55",
            media_type=MediaTypes.MOVIE.value,
        )
        self.assertIsNone(
            lookup_reference(
                self.other_user,
                "trakt",
                "account",
                "trakt",
                "55",
                MediaTypes.MOVIE.value,
            )
        )
