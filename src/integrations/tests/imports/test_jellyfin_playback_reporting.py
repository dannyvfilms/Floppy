from datetime import UTC, datetime
from datetime import timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Movie,
    MoviePlay,
    Season,
    Sources,
    Status,
)
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
                "RunTimeTicks": 1_200_000_000,
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
            watch=lambda episode_number, end_date, watch_operation_id, entry_source=None: SimpleNamespace(
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
                "RunTimeTicks": 1_200_000_000,
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

    @patch(
        "integrations.imports.jellyfin_playback_reporting.decrypt_or_raise",
        return_value="api-key",
    )
    @patch(
        "integrations.imports.jellyfin_playback_reporting.fork_services_episode.resolve_or_create_season"
    )
    @patch("integrations.jellyfin_client.JellyfinClient.iter_library_items")
    def test_skips_episode_already_recorded_by_webhook(
        self,
        mock_library,
        mock_resolve_season,
        mock_decrypt,
    ):
        """Issue #1162: the webhook logs stop time, the import logs start
        time, so a play recorded by one must still be recognized by the
        other even though their timestamps differ.
        """
        tv_item = Item.objects.create(
            media_id="series-42",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Show",
        )
        tv = TV.objects.create(
            user=self.user,
            item=tv_item,
            status=Status.IN_PROGRESS.value,
        )
        season_item = Item.objects.create(
            media_id="series-42",
            source=Sources.TVDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Season 2",
            season_number=2,
        )
        season = Season.objects.create(
            user=self.user,
            item=season_item,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )
        episode_item = Item.objects.create(
            media_id="series-42",
            source=Sources.TVDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Episode",
            season_number=2,
            episode_number=7,
        )
        # The webhook already recorded this play at playback-stop time.
        Episode.objects.create(
            item=episode_item,
            related_season=season,
            end_date=datetime(2024, 1, 2, 3, 34, 5, tzinfo=UTC),
        )

        mock_library.return_value = [
            {
                "Id": "jf-series",
                "Type": "Series",
                "ProviderIds": {"Tvdb": "series-42"},
            },
            {
                "Id": "jf-episode",
                "Type": "Episode",
                "RunTimeTicks": 1_200_000_000,
                "SeriesId": "jf-series",
                "ParentIndexNumber": 2,
                "IndexNumber": 7,
            },
        ]

        # The import runs later and describes the same play at
        # playback-start time, half an hour earlier.
        counts, warnings = JellyfinPlaybackReportingImporter(
            self.user,
            self.account,
        ).import_data(
            playback_row(
                timestamp="2024-01-02 03:04:05.1234567",
                item_id="jf-episode",
                item_type="Episode",
            ),
        )

        self.assertEqual(counts[MediaTypes.EPISODE.value], 0)
        self.assertIn("duplicate of an existing play", warnings)
        self.assertEqual(Episode.objects.count(), 1)
        mock_resolve_season.assert_not_called()

    @patch(
        "integrations.imports.jellyfin_playback_reporting.decrypt_or_raise",
        return_value="api-key",
    )
    @patch("integrations.jellyfin_client.JellyfinClient.iter_library_items")
    def test_skips_movie_already_recorded_by_webhook(
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
        movie = Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
            score=None,
            notes="",
            end_date=datetime(2024, 1, 2, 3, 34, 5, tzinfo=UTC),
        )
        mock_library.return_value = [
            {
                "Id": "jf-item",
                "Type": "Movie",
                "RunTimeTicks": 1_200_000_000,
                "ProviderIds": {"Tmdb": "123"},
            },
        ]

        counts, warnings = JellyfinPlaybackReportingImporter(
            self.user,
            self.account,
        ).import_data(playback_row(timestamp="2024-01-02 03:04:05.1234567"))

        self.assertEqual(counts[MediaTypes.MOVIE.value], 0)
        self.assertIn("duplicate of an existing play", warnings)
        self.assertEqual(MoviePlay.objects.filter(movie=movie).count(), 0)

    @patch(
        "integrations.imports.jellyfin_playback_reporting.decrypt_or_raise",
        return_value="api-key",
    )
    @patch("integrations.jellyfin_client.JellyfinClient.iter_library_items")
    def test_completion_threshold_for_api_and_tsv(self, mock_library, mock_decrypt):
        for path in ("api", "tsv"):
            for item_type in ("Movie", "Episode"):
                for runtime, duration, accepted in (
                    (14_400_000_000, 540, False),  # 9 of 24 minutes
                    (14_400_000_000, 1151, False),
                    (14_400_000_000, 1152, True),  # exactly 80%
                    (14_400_000_000, 1440, True),
                    (14_400_000_000, 1600, True),
                    (None, 1440, False),
                    (0, 1440, False),
                    (-1, 1440, False),
                    ("invalid", 1440, False),
                ):
                    with self.subTest(
                        path=path,
                        item_type=item_type,
                        runtime=runtime,
                        duration=duration,
                    ):
                        item = {
                            "Id": "jf-item",
                            "Type": item_type,
                            "ProviderIds": {"Tmdb": "123"},
                            "SeriesId": "jf-series",
                            "ParentIndexNumber": 1,
                            "IndexNumber": 1,
                            # A previous completed watch must not turn this
                            # historical partial session into another watch.
                            "UserData": {"Played": True},
                        }
                        if runtime is not None:
                            item["RunTimeTicks"] = runtime
                        mock_library.return_value = [
                            item,
                            {
                                "Id": "jf-series",
                                "Type": "Series",
                                "ProviderIds": {"Tmdb": "456"},
                            },
                        ]
                        importer = JellyfinPlaybackReportingImporter(
                            self.user, self.account
                        )
                        with (
                            patch.object(importer, "_import_movie") as movie,
                            patch.object(importer, "_import_episode") as episode,
                        ):
                            if path == "api":
                                _, warnings, cursor = importer.import_activity_rows(
                                    [
                                        {
                                            "rowid": 17,
                                            "date_created": "2024-01-02 03:04:05",
                                            "user_id": "jf-user",
                                            "item_id": "jf-item",
                                            "item_type": item_type,
                                            "play_duration": duration,
                                        }
                                    ]
                                )
                                self.assertEqual(cursor, 17)
                            else:
                                _, warnings = importer.import_data(
                                    playback_row(
                                        item_type=item_type,
                                        duration=str(duration),
                                    )
                                )
                        self.assertEqual(
                            movie.call_count, int(accepted and item_type == "Movie")
                        )
                        self.assertEqual(
                            episode.call_count, int(accepted and item_type == "Episode")
                        )
                        self.assertEqual(importer.skipped_count, int(not accepted))
                        if accepted:
                            self.assertEqual(warnings, "")
                        else:
                            self.assertIn("runtime", warnings)

class PlaybackActivityAPIImportTests(TestCase):
    """Cover the Playback Reporting REST API import path (no manual TSV)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pull-user")
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
    def test_imports_rows_with_rowid_identity_and_tracks_max_rowid(
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
                "RunTimeTicks": 1_200_000_000,
                "ProviderIds": {"Tmdb": "123"},
            },
        ]

        entries = [
            {
                "rowid": 5,
                "date_created": "2024-01-02 03:04:05",
                "user_id": "jf-user",
                "item_id": "jf-item",
                "item_type": "Movie",
                "item_name": "Example",
                "playback_method": "DirectPlay",
                "client_name": "Web",
                "device_name": "Laptop",
                "play_duration": "120",
            },
            {
                "rowid": 2,
                "date_created": "2024-01-01 00:00:00",
                "user_id": "other-user",
                "item_id": "jf-item",
                "item_type": "Movie",
                "item_name": "Example",
                "playback_method": "DirectPlay",
                "client_name": "Web",
                "device_name": "Laptop",
                "play_duration": "60",
            },
        ]

        counts, warnings, max_rowid = JellyfinPlaybackReportingImporter(
            self.user,
            self.account,
        ).import_activity_rows(entries)

        self.assertEqual(counts[MediaTypes.MOVIE.value], 1)
        self.assertEqual(warnings, "")
        self.assertEqual(max_rowid, 5)
        movie = item.movie_set.get(user=self.user)
        play = movie.plays.get()
        self.assertEqual(play.external_id, "jellyfin-playback-reporting:rowid:5")

        # Re-running with the same rows does not create a second play.
        counts, warnings, _ = JellyfinPlaybackReportingImporter(
            self.user,
            self.account,
        ).import_activity_rows(entries)
        self.assertEqual(counts[MediaTypes.MOVIE.value], 0)
        self.assertEqual(movie.plays.count(), 1)


class LibraryBackfillImportTests(TestCase):
    """Cover the plugin-free backfill from Jellyfin's UserData.Played state."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="backfill-user")
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
    def test_backfills_only_played_items_once(self, mock_library, mock_decrypt):
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
                "UserData": {"Played": True, "LastPlayedDate": "2024-01-02T03:04:05Z"},
            },
            {
                "Id": "jf-unwatched",
                "Type": "Movie",
                "ProviderIds": {"Tmdb": "999"},
                "UserData": {"Played": False},
            },
        ]

        counts, warnings = JellyfinPlaybackReportingImporter(
            self.user,
            self.account,
        ).import_library_backfill()

        self.assertEqual(counts[MediaTypes.MOVIE.value], 1)
        self.assertEqual(warnings, "")
        movie = item.movie_set.get(user=self.user)
        play = movie.plays.get()
        self.assertEqual(play.external_id, "jellyfin-library-backfill:jf-item")

        # Running again does not duplicate the single backfilled play.
        counts, warnings = JellyfinPlaybackReportingImporter(
            self.user,
            self.account,
        ).import_library_backfill()
        self.assertEqual(counts[MediaTypes.MOVIE.value], 0)
        self.assertEqual(movie.plays.count(), 1)
