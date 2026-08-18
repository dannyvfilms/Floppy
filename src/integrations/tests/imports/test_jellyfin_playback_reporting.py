from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import Item, MediaTypes, Movie, Status
from integrations.imports.jellyfin_playback_reporting import (
    JellyfinPlaybackReportingImporter,
    parse_tsv,
)
from integrations.models import JellyfinAccount


def playback_row(
    *,
    timestamp="2024-01-02 03:04:05.1234567",
    user_id="jf-user",
    item_id="jf-item",
    item_type="Movie",
    item_name="Example",
    duration="120",
):
    """Build one Playback Reporting export row."""
    return "\t".join(
        [
            timestamp,
            user_id,
            item_id,
            item_type,
            item_name,
            "DirectPlay",
            "Web",
            "Laptop",
            duration,
        ],
    )


class PlaybackReportingParserTests(TestCase):
    """Cover the unescaped nine-column Playback Reporting format."""

    def test_parser_handles_dotnet_fraction_and_tabs_in_title(self):
        result = parse_tsv(playback_row(item_name="A\tTabbed Title").encode())

        self.assertEqual(len(result.rows), 1)
        row = result.rows[0]
        self.assertEqual(row.item_name, "A\tTabbed Title")
        self.assertEqual(row.date_created.microsecond, 123456)
        self.assertEqual(row.play_duration, 120)

    def test_parser_rejects_invalid_durations_and_malformed_rows(self):
        result = parse_tsv(
            "\n".join(
                [
                    playback_row(duration="0"),
                    playback_row(duration="-10"),
                    "not\ta\tcomplete\trow",
                ],
            ),
        )

        self.assertEqual(result.rows, [])
        self.assertEqual(result.rejected_count, 3)
        self.assertTrue(any("PlayDuration" in warning for warning in result.warnings))
        self.assertTrue(any("9 tab-separated" in warning for warning in result.warnings))


class PlaybackReportingImporterTests(TestCase):
    """Cover Jellyfin hydration, user scoping, provider resolution, and dedupe."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="playback-user")
        self.account = JellyfinAccount.objects.create(
            user=self.user,
            base_url="https://jellyfin.example",
            api_key="encrypted",
            jellyfin_user_id="jf-user",
        )

    @patch(
        "integrations.imports.jellyfin_playback_reporting.decrypt_or_raise",
        return_value="api-key",
    )
    @patch("integrations.jellyfin_client.JellyfinClient.iter_library_items")
    def test_filters_other_users_and_reports_missing_items(
        self,
        mock_library,
        mock_decrypt,
    ):
        mock_library.return_value = []
        payload = "\n".join(
            [
                playback_row(user_id="other-user"),
                playback_row(item_id="missing-item"),
            ],
        )

        counts, warnings = JellyfinPlaybackReportingImporter(
            self.user,
            self.account,
        ).import_data(payload)

        self.assertEqual(counts[MediaTypes.MOVIE.value], 0)
        self.assertIn("another Jellyfin user", warnings)
        self.assertIn("was not found", warnings)
        mock_decrypt.assert_called_once_with("encrypted")

    @patch(
        "integrations.imports.jellyfin_playback_reporting.decrypt_or_raise",
        return_value="api-key",
    )
    @patch("integrations.jellyfin_client.JellyfinClient.iter_library_items")
    def test_resolves_movie_by_provider_id_and_preserves_timestamp(
        self,
        mock_library,
        mock_decrypt,
    ):
        item = Item.objects.create(
            media_id="123",
            source="tmdb",
            media_type=MediaTypes.MOVIE.value,
            title="Movie",
            image="",
        )
        Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
            score=None,
            notes="",
        )
        mock_library.return_value = [
            {
                "Id": "jf-item",
                "Type": "Movie",
                "ProviderIds": {"Tmdb": "123"},
            },
        ]
        payload = playback_row(timestamp="2024-01-02 03:04:05.1234567")

        counts, warnings = JellyfinPlaybackReportingImporter(
            self.user,
            self.account,
        ).import_data(payload)

        self.assertEqual(counts[MediaTypes.MOVIE.value], 1)
        self.assertEqual(warnings, "")
        movie = Movie.objects.get(pk=item.movie_set.get(user=self.user).pk)
        play = movie.plays.get()
        self.assertEqual(play.end_date.microsecond, 123456)
        self.assertEqual(play.external_id.count("hash:"), 1)

        # Re-uploading the same export does not create a second play.
        counts, warnings = JellyfinPlaybackReportingImporter(
            self.user,
            self.account,
        ).import_data(payload)
        self.assertEqual(counts[MediaTypes.MOVIE.value], 0)
        self.assertIn("already imported", warnings)
        self.assertEqual(movie.plays.count(), 1)
        mock_decrypt.assert_called()

    @patch(
        "integrations.imports.jellyfin_playback_reporting.decrypt_or_raise",
        return_value="api-key",
    )
    @patch(
        "integrations.imports.jellyfin_playback_reporting.fork_services_episode.resolve_or_create_season"
    )
    @patch("integrations.jellyfin_client.JellyfinClient.iter_library_items")
    def test_resolves_episode_by_series_provider_id_and_numbers(
        self,
        mock_library,
        mock_resolve_season,
        mock_decrypt,
    ):
        season = SimpleNamespace(
            watch=lambda episode_number, end_date, watch_operation_id: SimpleNamespace(
                created=True,
            ),
        )
        mock_resolve_season.return_value = season
        mock_library.return_value = [
            {
                "Id": "jf-series",
                "Type": "Series",
                "ProviderIds": {"Tvdb": "series-42"},
            },
            {
                "Id": "jf-episode",
                "Type": "Episode",
                "SeriesId": "jf-series",
                "ParentIndexNumber": 2,
                "IndexNumber": 7,
            },
        ]

        counts, warnings = JellyfinPlaybackReportingImporter(
            self.user,
            self.account,
        ).import_data(
            playback_row(
                item_id="jf-episode",
                item_type="Episode",
            ),
        )

        self.assertEqual(counts[MediaTypes.EPISODE.value], 1)
        self.assertEqual(warnings, "")
        mock_resolve_season.assert_called_once_with(
            self.user,
            "series-42",
            "tvdb",
            2,
        )
