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
    suggest_mapping,
)
from integrations.matching import split_title_year, unique_title_match
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

    def test_split_title_year_reads_media_server_disambiguation(self):
        self.assertEqual(
            split_title_year("All Creatures Great & Small (2020)"),
            ("All Creatures Great & Small", "2020"),
        )
        self.assertEqual(split_title_year("Show [1978] "), ("Show", "1978"))
        self.assertEqual(split_title_year("Game Changer"), ("Game Changer", None))
        # A title that is only a year is a title, not a suffix.
        self.assertEqual(split_title_year("(1984)"), ("(1984)", None))
        self.assertEqual(split_title_year(None), ("", None))


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

    def test_mapping_edited_after_preview_still_applies(self):
        """The preview token covers tracked state, not the mapping chosen later.

        The review page previews with the default mapping and the user then
        changes it; the token used to include the mapping, so any edit made
        the apply fail as "out of date".
        """
        source = self._item("411", MediaTypes.TV.value, "Wrong Show")
        destination = self._item("412", MediaTypes.TV.value, "Right Show")
        source_tv = TV.objects.create(
            user=self.user,
            item=source,
            status=Status.IN_PROGRESS.value,
        )
        source_season = Season.objects.create(
            user=self.user,
            item=self._item(
                "411",
                MediaTypes.SEASON.value,
                "Season 1",
                season_number=1,
            ),
            related_tv=source_tv,
            status=Status.IN_PROGRESS.value,
        )
        episode = Episode.objects.create(
            item=self._item(
                "411",
                MediaTypes.EPISODE.value,
                "Pilot",
                season_number=1,
                episode_number=1,
            ),
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
                episode_mapping={"1:1": {"season": 1, "episode": 2}},
            )

        episode.refresh_from_db()
        self.assertEqual(episode.item.episode_number, 2)

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


def _catalogue_metadata(seasons):
    """Fake provider metadata: {season: [(episode, title), ...]}."""

    def side_effect(media_type, media_id, source, *args, **kwargs):
        if media_type == "tv_with_seasons":
            return {
                f"season/{number}": {
                    "season_number": number,
                    "episodes": [
                        {
                            "episode_number": episode,
                            "title": title,
                            "air_date": "2020-01-01",
                        }
                        for episode, title in episodes
                    ],
                }
                for number, episodes in seasons.items()
            }
        return {
            "related": {"seasons": [{"season_number": n} for n in seasons]},
        }

    return patch("integrations.match_corrections.services.get_media_metadata", side_effect=side_effect)


class MatchFixReviewTests(TestCase):
    """The Fix Match page asks for episode numbering instead of raw JSON."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="match-fix-review",
            password="password",
        )
        self.client.force_login(self.user)
        self.source = Item.objects.create(
            media_id="701",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Old Show",
        )
        tv = TV.objects.create(
            user=self.user,
            item=self.source,
            status=Status.IN_PROGRESS.value,
        )
        season = Season.objects.create(
            user=self.user,
            item=Item.objects.create(
                media_id="701",
                source=Sources.TMDB.value,
                media_type=MediaTypes.SEASON.value,
                title="Season 1",
                season_number=1,
            ),
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )
        self.episodes = {}
        for number, title in ((1, "Pilot"), (2, "Second Thing"), (3, "Gone")):
            self.episodes[number] = Episode.objects.create(
                item=Item.objects.create(
                    media_id="701",
                    source=Sources.TMDB.value,
                    media_type=MediaTypes.EPISODE.value,
                    title=title,
                    season_number=1,
                    episode_number=number,
                ),
                related_season=season,
                end_date="2024-01-01T00:00:00Z",
            )
        self.search = patch(
            "integrations.views.services.search",
            return_value={"results": [{"media_id": "800", "title": "New Show"}]},
        )
        self.search.start()
        self.addCleanup(self.search.stop)
        fetch = patch("app.models.Item.fetch_releases")
        fetch.start()
        self.addCleanup(fetch.stop)
        self.url = reverse("match_fix", args=[self.source.pk]) + "?q=show"
        # Destination: same number and title for E1, renumbered E2, no E3.
        self.catalogue = _catalogue_metadata(
            {1: [(1, "Pilot"), (5, "Second Thing")]},
        )

    def test_review_prefills_matches_and_leaves_missing_episodes_open(self):
        with self.catalogue:
            response = self.client.post(
                self.url,
                {"action": "preview", "destination_media_id": "800"},
            )

        self.assertEqual(response.status_code, 200)
        rows = response.context["review"]["rows"]
        self.assertEqual(rows["1_1"]["selected"], "1:1")
        self.assertEqual(rows["1_1"]["kind"], "matched")
        # Same title under a different number is a suggestion, not a match.
        self.assertEqual(rows["1_2"]["selected"], "1:5")
        self.assertEqual(rows["1_2"]["kind"], "suggested")
        self.assertEqual(rows["1_3"]["selected"], "")
        self.assertNotContains(response, "mapping_json")

    def test_apply_uses_the_chosen_numbering(self):
        with self.catalogue:
            self.client.post(
                self.url,
                {"action": "preview", "destination_media_id": "800"},
            )
            response = self.client.post(
                self.url,
                {
                    "action": "apply",
                    "map_1_1": "1:1",
                    "map_1_2": "1:5",
                    "map_1_3": "1:1",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.episodes[2].refresh_from_db()
        self.assertEqual(self.episodes[2].item.episode_number, 5)

    def test_apply_with_a_missing_choice_keeps_the_review_and_the_choices(self):
        with self.catalogue:
            self.client.post(
                self.url,
                {"action": "preview", "destination_media_id": "800"},
            )
            response = self.client.post(
                self.url,
                {
                    "action": "apply",
                    "map_1_1": "1:1",
                    "map_1_2": "1:1",
                    "map_1_3": "",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["review"]["rows"]["1_2"]["selected"], "1:1")
        self.episodes[2].refresh_from_db()
        self.assertEqual(self.episodes[2].item.episode_number, 2)

    def test_tvdb_is_offered_and_chosen_as_the_destination(self):
        with (
            patch(
                "integrations.views.metadata_resolution.provider_is_enabled",
                return_value=True,
            ),
            self.catalogue,
        ):
            page = self.client.get(self.url)
            self.assertEqual(
                [key for key, _label in page.context["providers"]],
                [Sources.TMDB.value, Sources.TVDB.value],
            )
            self.client.post(
                self.url,
                {
                    "action": "preview",
                    "provider": Sources.TVDB.value,
                    "destination_media_id": "800",
                },
            )

        self.assertTrue(
            Item.objects.filter(
                media_id="800",
                source=Sources.TVDB.value,
                media_type=MediaTypes.TV.value,
            ).exists(),
        )

    def test_movies_are_not_offered_tvdb(self):
        movie = Item.objects.create(
            media_id="702",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Old Movie",
        )
        Movie.objects.create(user=self.user, item=movie, status=Status.COMPLETED.value)
        with patch(
            "integrations.views.metadata_resolution.provider_is_enabled",
            return_value=True,
        ):
            page = self.client.get(reverse("match_fix", args=[movie.pk]))

        self.assertEqual(
            [key for key, _label in page.context["providers"]],
            [Sources.TMDB.value],
        )


class SuggestMappingTests(TestCase):
    """Proposals favour a unique title over a shared episode number."""

    def test_unique_title_outranks_the_number(self):
        catalogue = [
            {"id": "1:1", "title": "Pilot", "code": "S1E1", "air_date": ""},
            {"id": "1:2", "title": "Equinox, Part II", "code": "S1E2", "air_date": ""},
            {"id": "1:3", "title": "Survival", "code": "S1E3", "air_date": ""},
        ]
        source = [
            {"key": "1:1", "title": "Pilot"},
            {"key": "1:2", "title": "Survival"},
            {"key": "1:3", "title": "Unknown"},
            {"key": "1:9", "title": "Special"},
        ]

        self.assertEqual(
            suggest_mapping(source, catalogue),
            {
                "1:1": ("1:1", "matched"),
                "1:2": ("1:3", "suggested"),
                "1:3": ("1:3", "suggested"),
            },
        )
