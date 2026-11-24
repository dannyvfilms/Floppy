"""Tests for the Netflix viewing-history CSV importer and review page."""

from datetime import date
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from app.models import TV, Episode, Item, MediaTypes, Movie, Season, Sources, Status
from integrations import import_progress
from integrations.imports import netflix
from integrations.imports.helpers import MediaImportError
from integrations.models import ImportRun, NetflixPendingRow


def _csv(*lines):
    return ("\n".join(lines) + "\n").encode("utf-8")


def _run(csv_bytes, user):
    return netflix.NetflixImporter(BytesIO(csv_bytes), user, "new").import_data()


def _named_show_meta(seasons):
    """TV metadata whose seasons carry names, for the named-season chain."""
    return {
        "title": "Show",
        "image": "t.jpg",
        "related": {
            "seasons": [
                {
                    "season_number": number,
                    "episode_count": count,
                    "name": name,
                }
                for number, count, name in seasons
            ],
        },
    }


class TitleSplitTests(TestCase):
    """Title -> (query, media type, season, episode) heuristics."""

    def test_episode_row_with_season_and_episode(self):
        result = netflix._split_title(
            "Weeds - Kleine Deals unter Nachbarn: Staffel 8: Folge 5"
        )
        self.assertEqual(
            result,
            ("Weeds - Kleine Deals unter Nachbarn", "tv", 8, 5),
        )

    def test_miniserie_row_starts_at_season_one(self):
        self.assertEqual(
            netflix._split_title("Some Show: Miniserie: Folge 3"),
            ("Some Show", "tv", 1, 3),
        )

    def test_english_season_and_episode_markers(self):
        self.assertEqual(
            netflix._split_title("Weeds: Season 8: Episode 5"),
            ("Weeds", "tv", 8, 5),
        )

    def test_limited_series_row_starts_at_season_one(self):
        self.assertEqual(
            netflix._split_title("Some Show: Limited Series: Episode 3"),
            ("Some Show", "tv", 1, 3),
        )
        self.assertEqual(
            netflix._split_title("Some Show: Limited Series"),
            ("Some Show", "tv", 1, None),
        )

    def test_part_segment_after_series_name_is_a_season(self):
        self.assertEqual(
            netflix._split_title("Disenchantment: Part 5: Goodbye Bean"),
            ("Disenchantment", "tv", 5, None),
        )

    def test_part_after_a_known_season_is_ignored(self):
        self.assertEqual(
            netflix._split_title("Weeds: Season 8: It's Time: Part 2"),
            ("Weeds", "tv", 8, None),
        )

    def test_dash_teil_movie_stays_a_movie(self):
        self.assertEqual(
            netflix._split_title("Die Tribute von Panam - Teil 3: Vögel"),
            ("Die Tribute von Panam - Teil 3: Vögel", "movie", None, None),
        )

    def test_episode_title_strips_labels_and_part(self):
        self.assertEqual(
            netflix._episode_title("Weeds: Season 8: It's Time: Part 2", "Weeds"),
            "It's Time",
        )
        self.assertEqual(
            netflix._episode_title("Weeds: Season 8: It's Time", "Weeds"),
            "It's Time",
        )
        self.assertIsNone(netflix._episode_title("Arrival", "Arrival"))

    def test_plain_title_is_a_movie(self):
        self.assertEqual(
            netflix._split_title("Arrival"),
            ("Arrival", "movie", None, None),
        )

    def test_teil_alone_is_not_a_tv_marker(self):
        self.assertEqual(
            netflix._split_title("The Thing - Teil 1"),
            ("The Thing - Teil 1", "movie", None, None),
        )

    def test_show_name_with_colon_keeps_its_second_segment(self):
        self.assertEqual(
            netflix._split_title("Tour de France: Unchained: Season 3: Episode 1"),
            ("Tour de France: Unchained", "tv", 3, 1),
        )

    def test_volume_segment_is_a_season(self):
        self.assertEqual(
            netflix._split_title("Love, Death & Robots: Volume 3: Jibaro"),
            ("Love, Death & Robots", "tv", 3, None),
        )
        self.assertEqual(
            netflix._episode_title(
                "Love, Death & Robots: Volume 3: Jibaro", "Love, Death & Robots",
            ),
            "Jibaro",
        )

    def test_volume_without_trailing_segment_keeps_movie_status(self):
        self.assertEqual(
            netflix._split_title("Some Film: Volume 2"),
            ("Some Film: Volume 2", "movie", None, None),
        )

    def test_limited_series_part_segment_is_the_episode(self):
        self.assertEqual(
            netflix._split_title("Wild Wild Country: Limited Series: Part 6"),
            ("Wild Wild Country", "tv", 1, 6),
        )


class ResolveRowTests(TestCase):
    """The safe shortcuts resolve_row adds on top of the exact match."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="test", password="12345"
        )
        self.resolver = netflix.NetflixResolver(self.user)

    @staticmethod
    def _show_meta(seasons):
        return {
            "title": "Show",
            "related": {
                "seasons": [
                    {"season_number": number, "episode_count": count}
                    for number, count in seasons
                ],
            },
        }

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_ambiguous_tv_narrowed_by_known_season(self, mock_meta, mock_search):
        mock_search.return_value = {
            "results": [
                {"media_id": 79744, "name": "The Rookie"},
                {"media_id": 7583, "name": "The Rookie"},
            ],
        }
        mock_meta.side_effect = [
            self._show_meta([(season, 10) for season in range(1, 10)]),
            self._show_meta([(1, 10)]),
        ]

        self.assertEqual(
            self.resolver.resolve_row(
                "The Rookie: Season 7: Episode 5", "The Rookie", "tv", 7, 5,
            ),
            ("79744", "tv", 7, 5),
        )

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_ambiguous_tv_stays_ambiguous_when_season_shares(self, mock_meta,
                                                             mock_search):
        mock_search.return_value = {
            "results": [
                {"media_id": 79744, "name": "The Rookie"},
                {"media_id": 7583, "name": "The Rookie"},
            ],
        }
        mock_meta.side_effect = [
            self._show_meta([(7, 10)]),
            self._show_meta([(7, 10)]),
        ]

        self.assertIsNone(
            self.resolver.resolve_row(
                "The Rookie: Season 7: Episode 5", "The Rookie", "tv", 7, 5,
            ),
        )

    @patch("integrations.imports.trakt.services.search")
    def test_ambiguous_movie_stays_ambiguous(self, mock_search):
        mock_search.return_value = {
            "results": [
                {"media_id": 1, "title": "Sinners"},
                {"media_id": 2, "title": "Sinners"},
            ],
        }

        self.assertIsNone(
            self.resolver.resolve_row("Sinners", "Sinners", "movie", None, None),
        )

    @patch("integrations.imports.trakt.services.search")
    def test_movie_part_continuation(self, mock_search):
        mock_search.return_value = {
            "results": [
                {
                    "media_id": 93618,
                    "title": "Mission: Impossible - Dead Reckoning Part One",
                },
            ],
        }

        self.assertEqual(
            self.resolver.resolve_row(
                "Mission: Impossible - Dead Reckoning",
                "Mission: Impossible - Dead Reckoning",
                "movie",
                None,
                None,
            ),
            ("93618", "movie", None, None),
        )

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_episode_without_season_finds_unique_season(self, mock_meta,
                                                        mock_search):
        mock_search.return_value = {
            "results": [{"media_id": 135114, "name": "Delicious in Dungeon"}],
        }
        mock_meta.return_value = self._show_meta([(1, 24), (2, 8)])

        self.assertEqual(
            self.resolver.resolve_row(
                "Delicious in Dungeon: Episode 12",
                "Delicious in Dungeon",
                "tv",
                None,
                12,
            ),
            ("135114", "tv", 1, 12),
        )

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_episode_without_season_stays_ambiguous(self, mock_meta,
                                                     mock_search):
        mock_search.return_value = {
            "results": [{"media_id": 135114, "name": "Delicious in Dungeon"}],
        }
        mock_meta.return_value = self._show_meta([(1, 24), (2, 24)])

        self.assertIsNone(
            self.resolver.resolve_row(
                "Delicious in Dungeon: Episode 12",
                "Delicious in Dungeon",
                "tv",
                None,
                12,
            ),
        )

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_unlabelled_colon_row_matches_unique_episode(self, mock_meta,
                                                         mock_search):
        mock_search.side_effect = [
            {"results": []},
            {"results": [{"media_id": 64635, "name": "Chef's Table"}]},
        ]
        mock_meta.side_effect = [
            self._show_meta([(1, 1), (2, 2)]),
            {"episodes": [{"episode_number": 1, "name": "Other"}]},
            {"episodes": [
                {"episode_number": 1, "name": "X"},
                {"episode_number": 2, "name": "China"},
            ]},
        ]

        self.assertEqual(
            self.resolver.resolve_row(
                "Chef's Table: China", "Chef's Table: China", "movie",
                None, None,
            ),
            ("64635", "tv", 2, 2),
        )

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_unlabelled_colon_row_stays_pending_when_episode_shared(
        self, mock_meta, mock_search
    ):
        mock_search.side_effect = [
            {"results": []},
            {"results": [{"media_id": 64635, "name": "Chef's Table"}]},
        ]
        mock_meta.side_effect = [
            self._show_meta([(1, 4), (2, 4)]),
            {"episodes": [{"episode_number": 2, "name": "China"}]},
            {"episodes": [{"episode_number": 1, "name": "China"}]},
        ]

        self.assertIsNone(
            self.resolver.resolve_row(
                "Chef's Table: China", "Chef's Table: China", "movie",
                None, None,
            ),
        )

    @patch("integrations.imports.trakt.services.search")
    def test_tv_row_without_coordinates_never_searches(self, mock_search):
        mock_search.return_value = {"results": [{"media_id": 1, "name": "Show"}]}

        self.assertIsNone(
            self.resolver.resolve_row(
                "Show: Limited Series", "Show", "tv", None, None,
            ),
        )
        mock_search.assert_not_called()


    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_named_season_chain_resolves_exact_episode(self, mock_meta,
                                                       mock_search):
        mock_search.side_effect = [
            {"results": []},
            {"results": []},
            {
                "results": [
                    {
                        "media_id": 62273,
                        "name": "Food Wars! Shokugeki no Soma",
                    }
                ]
            },
        ]
        mock_meta.side_effect = [
            _named_show_meta([(1, 24, "Season 1"), (2, 13, "The Second Plate")]),
            {
                "episodes": [
                    {"episode_number": 12, "name": "The Magician Returns"},
                    {"episode_number": 13, "name": "Pomp & Circumstance"},
                ]
            },
        ]

        self.assertEqual(
            self.resolver.resolve_row(
                "Food Wars!: Shokugeki no Soma: The Second Plate: "
                "Pomp & Circumstance",
                "Food Wars!: Shokugeki no Soma: The Second Plate: "
                "Pomp & Circumstance",
                "movie",
                None,
                None,
            ),
            ("62273", "tv", 2, 13),
        )

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_named_season_chain_fuzzy_episode(self, mock_meta, mock_search):
        mock_search.side_effect = [
            {"results": []},
            {"results": []},
            {
                "results": [
                    {
                        "media_id": 62273,
                        "name": "Food Wars! Shokugeki no Soma",
                    }
                ]
            },
        ]
        mock_meta.side_effect = [
            _named_show_meta([(2, 13, "The Second Plate")]),
            {
                "episodes": [
                    {"episode_number": 12, "name": "The Magician Returns"},
                    {"episode_number": 13, "name": "Pomp & Circumstance"},
                ]
            },
        ]

        self.assertEqual(
            self.resolver.resolve_row(
                "Food Wars!: Shokugeki no Soma: The Second Plate: "
                "Pomp and Circumstance",
                "Food Wars!: Shokugeki no Soma: The Second Plate: "
                "Pomp and Circumstance",
                "movie",
                None,
                None,
            ),
            ("62273", "tv", 2, 13),
        )

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_named_season_chain_ambiguous_show_stays_pending(
        self, mock_meta, mock_search
    ):
        mock_search.side_effect = [
            {"results": []},
            {"results": []},
            {
                "results": [
                    {"media_id": 62273, "name": "Food Wars! Shokugeki no Soma"},
                    {"media_id": 99999, "name": "Food Wars! Shokugeki no Soma"},
                ]
            },
            {"results": []},
        ]

        self.assertIsNone(
            self.resolver.resolve_row(
                "Food Wars!: Shokugeki no Soma: The Second Plate: "
                "Pomp & Circumstance",
                "Food Wars!: Shokugeki no Soma: The Second Plate: "
                "Pomp & Circumstance",
                "movie",
                None,
                None,
            ),
        )
        mock_meta.assert_not_called()

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_named_season_chain_ambiguous_season_name_stays_pending(
        self, mock_meta, mock_search
    ):
        mock_search.side_effect = [
            {"results": []},
            {"results": []},
            {"results": [{"media_id": 62273, "name": "Food Wars! Shokugeki no Soma"}]},
            {"results": []},
        ]
        mock_meta.return_value = _named_show_meta(
            [(2, 13, "The Second Plate"), (5, 13, "The Second Plate")],
        )

        self.assertIsNone(
            self.resolver.resolve_row(
                "Food Wars!: Shokugeki no Soma: The Second Plate: "
                "Pomp & Circumstance",
                "Food Wars!: Shokugeki no Soma: The Second Plate: "
                "Pomp & Circumstance",
                "movie",
                None,
                None,
            ),
        )

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_named_season_chain_keeps_season_when_episode_unmatched(
        self, mock_meta, mock_search
    ):
        mock_search.side_effect = [
            {"results": []},
            {"results": []},
            {"results": [{"media_id": 62273, "name": "Food Wars! Shokugeki no Soma"}]},
        ]
        mock_meta.side_effect = [
            _named_show_meta([(2, 13, "The Second Plate")]),
            {
                "episodes": [
                    {"episode_number": 1, "name": "Completely Different"},
                    {"episode_number": 2, "name": "Another Unrelated Name"},
                ]
            },
        ]

        self.assertEqual(
            self.resolver.resolve_row(
                "Food Wars!: Shokugeki no Soma: The Second Plate: "
                "Pomp & Circumstance",
                "Food Wars!: Shokugeki no Soma: The Second Plate: "
                "Pomp & Circumstance",
                "movie",
                None,
                None,
            ),
            ("62273", "tv", 2, None),
        )

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_two_segment_row_does_not_use_named_chain(self, mock_meta,
                                                       mock_search):
        mock_search.side_effect = [
            {"results": []},
            {"results": [{"media_id": 9, "name": "Some Show"}]},
        ]
        mock_meta.side_effect = [
            _named_show_meta([(1, 1, "The Part")]),
            {"episodes": [{"episode_number": 1, "name": "Something"}]},
        ]

        self.assertIsNone(
            self.resolver.resolve_row(
                "Some Show: The Part", "Some Show: The Part", "movie", None, None,
            ),
        )


class DateTests(TestCase):
    """Date parsing and per-file layout detection."""

    def test_layout_from_day_only_component(self):
        self.assertEqual(netflix._detect_date_layout(["11/20/26"]), "mdy")
        self.assertEqual(netflix._detect_date_layout(["31/12/24"]), "dmy")
        self.assertEqual(netflix._detect_date_layout(["10/7/18"]), "mdy")

    def test_parse_us_style(self):
        parsed = netflix._parse_netflix_date("11/20/26", "mdy")
        self.assertEqual(parsed.date(), date(2026, 11, 20))

    def test_parse_german_style(self):
        parsed = netflix._parse_netflix_date("31/12/24", "dmy")
        self.assertEqual(parsed.date(), date(2024, 12, 31))

    def test_unparseable_returns_none(self):
        self.assertIsNone(netflix._parse_netflix_date("garbage", "mdy"))
        self.assertIsNone(netflix._parse_netflix_date("13/45/26", "mdy"))


class NetflixImporterTests(TestCase):
    """CSV rows -> plays, or parked pending rows."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="test", password="12345"
        )

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_movie_row_creates_completed_movie(self, mock_meta, mock_search):
        mock_search.return_value = {
            "results": [{"media_id": 555, "title": "Arrival", "year": 2016}],
        }
        mock_meta.return_value = {"title": "Arrival", "image": "m.jpg"}

        counts, warnings = _run(_csv("Title,Date", "Arrival,11/20/26"), self.user)

        self.assertEqual(counts.get(MediaTypes.MOVIE.value), 1)
        movie = Movie.objects.get(user=self.user, item__media_id="555")
        self.assertEqual(movie.status, Status.COMPLETED.value)
        self.assertEqual(movie.end_date.date(), date(2026, 11, 20))
        self.assertEqual(NetflixPendingRow.objects.count(), 0)

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_episode_row_records_episode_play(self, mock_meta, mock_search):
        mock_search.return_value = {
            "results": [
                {
                    "media_id": 111,
                    "title": "Weeds - Kleine Deals unter Nachbarn",
                    "year": 2019,
                }
            ],
        }
        mock_meta.side_effect = [
            {"title": "Weeds - Kleine Deals unter Nachbarn", "image": "t.jpg"},
            {
                "title": "Season 8",
                "image": "s.jpg",
                "max_progress": 6,
                "episodes": [{"episode_number": 5, "title": "E5"}],
            },
        ]

        counts, _ = _run(
            _csv(
                "Title,Date",
                "Weeds - Kleine Deals unter Nachbarn: Staffel 8: Folge 5,10/7/18",
            ),
            self.user,
        )

        self.assertEqual(counts.get(MediaTypes.TV.value), 1)
        item = Item.objects.get(
            media_id="111",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=8,
            episode_number=5,
        )
        episode = Episode.objects.get(item=item)
        self.assertEqual(episode.end_date.date(), date(2018, 10, 7))
        self.assertEqual(
            TV.objects.filter(user=self.user, item__media_id="111").count(),
            1,
        )
        self.assertEqual(
            Season.objects.filter(user=self.user, item__media_id="111").count(),
            1,
        )

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_english_episode_title_match_records_play(
        self, mock_meta, mock_search
    ):
        mock_search.return_value = {
            "results": [{"media_id": 111, "title": "Weeds", "year": 2019}],
        }
        season_meta = {
            "title": "Season 8",
            "image": "s.jpg",
            "max_progress": 6,
            "episodes": [
                {"episode_number": 4, "name": "Some Other Episode"},
                {"episode_number": 5, "name": "It's Time"},
            ],
        }
        # The title match reads the season first; record_play then repeats
        # the TV and season lookups (the mock bypasses the real memo).
        mock_meta.side_effect = [
            season_meta,
            {"title": "Weeds", "image": "t.jpg"},
            season_meta,
        ]

        counts, _ = _run(
            _csv("Title,Date", "Weeds: Season 8: It's Time,10/7/18"),
            self.user,
        )

        self.assertEqual(counts.get(MediaTypes.TV.value), 1)
        item = Item.objects.get(
            media_id="111",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=8,
            episode_number=5,
        )
        self.assertEqual(Episode.objects.filter(item=item).count(), 1)

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_named_season_row_records_episode_play(self, mock_meta,
                                                   mock_search):
        mock_search.side_effect = [
            {"results": []},
            {"results": []},
            {
                "results": [
                    {
                        "media_id": 62273,
                        "name": "Food Wars! Shokugeki no Soma",
                    }
                ]
            },
        ]
        show_meta = _named_show_meta(
            [(1, 24, "Season 1"), (2, 13, "The Second Plate")],
        )
        season_meta = {
            "title": "Season 2",
            "image": "s.jpg",
            "max_progress": 13,
            "episodes": [{"episode_number": 13, "title": "Pomp & Circumstance"}],
        }
        # The chain reads the show and the season; record_play repeats both
        # lookups (the mock bypasses the real memo).
        mock_meta.side_effect = [show_meta, season_meta, show_meta, season_meta]

        counts, _ = _run(
            _csv(
                "Title,Date",
                "Food Wars!: Shokugeki no Soma: The Second Plate: "
                "Pomp & Circumstance,7/28/19",
            ),
            self.user,
        )

        self.assertEqual(counts.get(MediaTypes.TV.value), 1)
        item = Item.objects.get(
            media_id="62273",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number=2,
            episode_number=13,
        )
        self.assertEqual(Episode.objects.filter(item=item).count(), 1)
        self.assertEqual(NetflixPendingRow.objects.count(), 0)

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_part_as_season_row_records_play(self, mock_meta, mock_search):
        mock_search.return_value = {
            "results": [
                {"media_id": 333, "title": "Disenchantment", "year": 2018}
            ],
        }
        season_meta = {
            "title": "Part 5",
            "image": "s.jpg",
            "episodes": [{"episode_number": 8, "title": "Goodbye Bean"}],
        }
        mock_meta.side_effect = [
            season_meta,
            {"title": "Disenchantment", "image": "t.jpg"},
            season_meta,
        ]

        counts, _ = _run(
            _csv("Title,Date", "Disenchantment: Part 5: Goodbye Bean,11/20/26"),
            self.user,
        )

        self.assertEqual(counts.get(MediaTypes.TV.value), 1)
        self.assertEqual(
            Item.objects.filter(
                media_id="333",
                media_type=MediaTypes.EPISODE.value,
                season_number=5,
                episode_number=8,
            ).count(),
            1,
        )

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_unmatched_episode_title_becomes_pending_with_season(
        self, mock_meta, mock_search
    ):
        mock_search.return_value = {
            "results": [{"media_id": 111, "title": "Weeds", "year": 2019}],
        }
        mock_meta.return_value = {
            "title": "Season 8",
            "image": "s.jpg",
            "episodes": [{"episode_number": 1, "name": "Pilot"}],
        }

        counts, _ = _run(
            _csv("Title,Date", "Weeds: Season 8: Some Unknown Title,10/7/18"),
            self.user,
        )

        self.assertEqual(counts.get(MediaTypes.TV.value), 0)
        row = NetflixPendingRow.objects.get()
        self.assertEqual(row.season_number, 8)
        self.assertIsNone(row.episode_number)

    @patch("integrations.imports.trakt.services.search")
    def test_unmatched_title_becomes_pending(self, mock_search):
        mock_search.return_value = {"results": []}

        counts, warnings = _run(
            _csv("Title,Date", "Unbekannter Film,11/20/26"), self.user
        )

        self.assertEqual(counts.get(MediaTypes.MOVIE.value), 0)
        row = NetflixPendingRow.objects.get()
        self.assertEqual(row.title, "Unbekannter Film")
        self.assertEqual(row.status, NetflixPendingRow.Status.PENDING.value)
        self.assertEqual(row.watched_at, date(2026, 11, 20))
        self.assertIn("review", warnings)

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_ambiguous_tv_row_resolved_by_known_season(self, mock_meta,
                                                        mock_search):
        mock_search.return_value = {
            "results": [
                {"media_id": 79744, "name": "The Rookie"},
                {"media_id": 7583, "name": "The Rookie"},
            ],
        }
        seasons = [
            {"season_number": season, "episode_count": 10}
            for season in range(1, 10)
        ]

        def meta(media_type, tmdb_id, title, season_number=None):
            if media_type == MediaTypes.TV.value:
                if tmdb_id == "79744":
                    return {"title": "The Rookie", "image": "t.jpg",
                            "related": {"seasons": seasons}}
                return {"title": "The Rookie", "image": "t.jpg",
                        "related": {"seasons": [
                            {"season_number": 1, "episode_count": 10},
                        ]}}
            return {"image": "s.jpg",
                    "episodes": [{"episode_number": 5, "name": "The Call"}]}

        mock_meta.side_effect = meta

        counts, _ = _run(
            _csv("Title,Date", "The Rookie: Season 7: Episode 5,11/20/26"),
            self.user,
        )

        self.assertEqual(counts.get(MediaTypes.TV.value), 1)
        self.assertEqual(
            Item.objects.filter(
                media_id="79744",
                media_type=MediaTypes.EPISODE.value,
                season_number=7,
                episode_number=5,
            ).count(),
            1,
        )

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_episode_without_season_records_unique_season(self, mock_meta,
                                                          mock_search):
        mock_search.return_value = {
            "results": [{"media_id": 135114, "name": "Delicious in Dungeon"}],
        }
        show_meta = {
            "title": "Delicious in Dungeon",
            "image": "t.jpg",
            "related": {"seasons": [
                {"season_number": 1, "episode_count": 24},
                {"season_number": 2, "episode_count": 8},
            ]},
        }

        def meta(media_type, tmdb_id, title, season_number=None):
            if media_type == MediaTypes.TV.value:
                return show_meta
            return {"image": "s.jpg",
                    "episodes": [{"episode_number": 12, "name": "Dinner"}]}

        mock_meta.side_effect = meta

        counts, _ = _run(
            _csv("Title,Date", "Delicious in Dungeon: Episode 12,11/20/26"),
            self.user,
        )

        self.assertEqual(counts.get(MediaTypes.TV.value), 1)
        self.assertEqual(
            Item.objects.filter(
                media_id="135114",
                media_type=MediaTypes.EPISODE.value,
                season_number=1,
                episode_number=12,
            ).count(),
            1,
        )

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_unlabelled_colon_row_records_unique_tv_episode(self, mock_meta,
                                                            mock_search):
        mock_search.side_effect = [
            {"results": []},
            {"results": [{"media_id": 64635, "name": "Chef's Table"}]},
        ]
        show_meta = {
            "title": "Chef's Table",
            "image": "t.jpg",
            "related": {"seasons": [
                {"season_number": 1, "episode_count": 1},
                {"season_number": 2, "episode_count": 2},
            ]},
        }

        def meta(media_type, tmdb_id, title, season_number=None):
            if media_type == MediaTypes.TV.value:
                return show_meta
            if season_number == 1:
                return {"image": "s.jpg",
                        "episodes": [{"episode_number": 1, "name": "Other"}]}
            return {"image": "s.jpg",
                    "episodes": [
                        {"episode_number": 1, "name": "X"},
                        {"episode_number": 2, "name": "China"},
                    ]}

        mock_meta.side_effect = meta

        counts, _ = _run(
            _csv("Title,Date", "Chef's Table: China,11/20/26"), self.user,
        )

        self.assertEqual(counts.get(MediaTypes.TV.value), 1)
        self.assertEqual(
            Item.objects.filter(
                media_id="64635",
                media_type=MediaTypes.EPISODE.value,
                season_number=2,
                episode_number=2,
            ).count(),
            1,
        )

    def test_empty_title_row_is_skipped(self):
        counts, warnings = _run(
            _csv("Title,Date", " ,10/7/18"), self.user
        )
        self.assertEqual(counts.get(MediaTypes.MOVIE.value), 0)
        self.assertEqual(NetflixPendingRow.objects.count(), 0)
        self.assertIn("skipped", warnings)

    def test_unparseable_date_becomes_pending(self):
        counts, _ = _run(
            _csv("Title,Date", "Good Movie,not-a-date"), self.user
        )
        self.assertEqual(counts.get(MediaTypes.MOVIE.value), 0)
        row = NetflixPendingRow.objects.get()
        self.assertIsNone(row.watched_at)
        self.assertEqual(row.raw_date, "not-a-date")

    @patch.object(
        netflix.NetflixResolver,
        "_get_metadata",
        return_value={"title": "Arrival", "image": "m.jpg"},
    )
    @patch(
        "integrations.imports.trakt.services.search",
        return_value={"results": [{"media_id": 555, "title": "Arrival"}], "count": 1},
    )
    def test_reimport_does_not_duplicate_plays_or_pending(
        self, mock_search, mock_meta
    ):
        _run(_csv("Title,Date", "Arrival,11/20/26"), self.user)
        _run(_csv("Title,Date", "Arrival,11/20/26"), self.user)

        self.assertEqual(Movie.objects.filter(user=self.user).count(), 1)


class ImportRunProvenanceTests(TestCase):
    """Rows an import run writes are tagged with it, so an undo can remove
    exactly them (and only them).
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="test", password="12345"
        )
        self.run = ImportRun.objects.create(
            user=self.user,
            source="netflix",
            status=ImportRun.Status.COMPLETED,
        )

    def _run_with(self, csv_bytes):
        with import_progress.tracking(None, self.run.id):
            return netflix.NetflixImporter(
                BytesIO(csv_bytes), self.user, "new"
            ).import_data()

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_created_movie_is_tagged_with_the_run(self, mock_meta, mock_search):
        mock_search.return_value = {
            "results": [{"media_id": 555, "title": "Arrival", "year": 2016}]
        }
        mock_meta.return_value = {"title": "Arrival", "image": "m.jpg"}

        self._run_with(_csv("Title,Date", "Arrival,11/20/26"))

        movie = Movie.objects.get(user=self.user)
        self.assertEqual(movie.import_run_id, self.run.id)

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_created_show_rows_are_tagged_with_the_run(
        self, mock_meta, mock_search
    ):
        mock_search.return_value = {
            "results": [{"media_id": 111, "title": "Weeds", "year": 2019}]
        }
        mock_meta.side_effect = [
            {"title": "Weeds", "image": "t.jpg"},
            {
                "title": "Season 8",
                "image": "s.jpg",
                "max_progress": 6,
                "episodes": [{"episode_number": 5, "title": "E5"}],
            },
        ]

        self._run_with(_csv("Title,Date", "Weeds: Season 8: Episode 5,10/7/18"))

        self.assertEqual(
            TV.objects.get(user=self.user).import_run_id, self.run.id
        )
        self.assertEqual(
            Season.objects.get(user=self.user).import_run_id, self.run.id
        )
        self.assertEqual(Episode.objects.get().import_run_id, self.run.id)

    def test_parked_row_is_tagged_with_the_run(self):
        self._run_with(_csv("Title,Date", "Unknown Show,not-a-date"))

        row = NetflixPendingRow.objects.get()
        self.assertEqual(row.import_run_id, self.run.id)

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_reimport_does_not_retag_existing_rows(self, mock_meta, mock_search):
        """Rows written before this run keep their own provenance."""
        mock_search.return_value = {
            "results": [{"media_id": 555, "title": "Arrival", "year": 2016}]
        }
        mock_meta.return_value = {"title": "Arrival", "image": "m.jpg"}
        _run(_csv("Title,Date", "Arrival,11/20/26"), self.user)
        _run(_csv("Title,Date", "No Such Show,not-a-date"), self.user)
        self._run_with(_csv("Title,Date", "Arrival,11/20/26"))
        self._run_with(_csv("Title,Date", "No Such Show,not-a-date"))

        self.assertIsNone(Movie.objects.get(user=self.user).import_run_id)
        self.assertIsNone(NetflixPendingRow.objects.get().import_run_id)

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_import_outside_a_run_leaves_rows_untagged(
        self, mock_meta, mock_search
    ):
        mock_search.return_value = {
            "results": [{"media_id": 555, "title": "Arrival", "year": 2016}]
        }
        mock_meta.return_value = {"title": "Arrival", "image": "m.jpg"}

        _run(_csv("Title,Date", "Arrival,11/20/26"), self.user)

        self.assertIsNone(Movie.objects.get(user=self.user).import_run_id)


class NetflixPendingViewTests(TestCase):
    """The interactive review page."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="test", password="12345"
        )
        self.client.force_login(self.user)

    def _row(self, **kwargs):
        defaults = {
            "user": self.user,
            "title": "Weeds - Kleine Deals unter Nachbarn: Staffel 8: Folge 5",
            "watched_at": date(2018, 10, 7),
            "media_type": MediaTypes.TV.value,
            "season_number": 8,
            "episode_number": 5,
        }
        defaults.update(kwargs)
        return NetflixPendingRow.objects.create(**defaults)

    def test_pending_list_shows_only_pending_rows(self):
        self._row()
        done = self._row(status=NetflixPendingRow.Status.RESOLVED.value)
        response = self.client.get(reverse("netflix_pending"))
        self.assertContains(response, "Weeds - Kleine Deals unter Nachbarn")
        response = self.client.get(reverse("netflix_pending") + "?show=all")
        self.assertContains(response, "Recorded.")

    def test_search_shows_provider_results(self):
        row = self._row()
        results = [
            {"media_id": 100 + i, "title": f"Weeds {i}", "year": 2019}
            for i in range(10)
        ]
        with patch(
            "integrations.imports.trakt.services.search",
            return_value={"results": results},
        ) as mock_search:
            response = self.client.get(
                reverse("netflix_pending"),
                {"search_row": row.id, "q": "Weeds", "type": "tv"},
            )
        # The review page must show page 1 of the provider results, capped at
        # SEARCH_RESULT_LIMIT (the third positional argument is the page).
        mock_search.assert_called_once_with(
            "tv", "Weeds", 1, source="tmdb",
        )
        for i in range(netflix.SEARCH_RESULT_LIMIT):
            self.assertContains(response, f'value="{100 + i}"')
        self.assertNotContains(response, f'value="{100 + netflix.SEARCH_RESULT_LIMIT}"')

    def test_search_json_for_the_react_island(self):
        self._row()
        with patch(
            "integrations.imports.trakt.services.search",
            return_value={
                "results": [{"media_id": 111, "title": "Weeds", "year": 2019}]
            },
        ):
            response = self.client.get(
                reverse("netflix_pending"),
                {"format": "json", "q": "Weeds", "type": "tv"},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["results"],
            [{"media_id": 111, "title": "Weeds", "year": 2019}],
        )
        self.assertEqual(payload["mediaType"], "tv")

    def test_review_props_render_for_the_react_island(self):
        self._row()
        response = self.client.get(reverse("netflix_pending"))
        self.assertContains(response, "data-netflix-review-root")
        self.assertContains(
            response, 'data-props-id="netflix-review-props"'
        )

    def test_review_page_paginates_hundred_per_page(self):
        for i in range(150):
            self._row(title=f"Show {i:03d}: Episode {i}")

        response = self.client.get(reverse("netflix_pending"))
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 2)
        self.assertEqual(len(response.context["rows"]), 100)
        # The island only ever receives the current page.
        self.assertEqual(
            len(response.context["review_props"]["model"]["rows"]), 100
        )

        response = self.client.get(reverse("netflix_pending") + "?page=2")
        self.assertEqual(len(response.context["rows"]), 50)

    def test_review_page_filter_narrows_and_tabs_keep_it(self):
        self._row(title="Alpha Show")
        self._row(title="Beta Show")

        response = self.client.get(
            reverse("netflix_pending"), {"filter": "alpha"}
        )
        self.assertEqual(len(response.context["rows"]), 1)
        # The Pending/All tabs and the pagination links carry the filter.
        self.assertContains(response, "filter=alpha")

        response = self.client.get(
            reverse("netflix_pending") + "?show=all&filter=alpha"
        )
        self.assertEqual(len(response.context["rows"]), 1)

    def test_page_beyond_the_end_falls_back_to_the_last_page(self):
        self._row()

        response = self.client.get(reverse("netflix_pending") + "?page=99")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["rows"]), 1)

    def test_empty_filter_result_offers_a_reset(self):
        self._row(title="Alpha Show")

        response = self.client.get(
            reverse("netflix_pending"), {"filter": "no-such-title"}
        )

        self.assertEqual(len(response.context["rows"]), 0)
        self.assertContains(response, "No rows match")
        self.assertContains(response, "Clear filter")

    @patch.object(
        netflix.NetflixResolver,
        "_get_metadata",
        side_effect=[
            {"title": "Weeds", "image": "t.jpg"},
            {
                "title": "Season 8",
                "image": "s.jpg",
                "max_progress": 6,
                "episodes": [{"episode_number": 5, "title": "E5"}],
            },
        ],
    )
    def test_resolve_records_play_and_marks_row(self, mock_meta):
        row = self._row()
        response = self.client.post(
            reverse("netflix_pending_resolve", args=[row.id]),
            {
                "media_type": "tv",
                "tmdb_id": "111",
                "season_number": "8",
                "episode_number": "5",
            },
        )
        row.refresh_from_db()
        self.assertRedirects(response, reverse("netflix_pending"))
        self.assertEqual(row.status, NetflixPendingRow.Status.RESOLVED.value)
        self.assertIsNotNone(row.resolved_item)
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(), 1
        )

    @patch.object(
        netflix.NetflixResolver, "_get_metadata",
        return_value={"title": "Arrival", "image": "m.jpg"},
    )
    def test_resolve_movie(self, mock_meta):
        row = self._row(
            title="Arrival",
            media_type=MediaTypes.MOVIE.value,
            season_number=None,
            episode_number=None,
        )
        self.client.post(
            reverse("netflix_pending_resolve", args=[row.id]),
            {"media_type": "movie", "tmdb_id": "555"},
        )
        row.refresh_from_db()
        self.assertEqual(row.status, NetflixPendingRow.Status.RESOLVED.value)
        self.assertEqual(
            Movie.objects.filter(user=self.user).count(), 1
        )

    def test_dismiss(self):
        row = self._row()
        self.client.post(reverse("netflix_pending_dismiss", args=[row.id]))
        row.refresh_from_db()
        self.assertEqual(row.status, NetflixPendingRow.Status.DISMISSED.value)

    @patch.object(
        netflix.NetflixResolver,
        "_get_metadata",
        return_value={"title": "Arrival", "image": "m.jpg"},
    )
    def test_resolve_keeps_filter_and_page(self, mock_meta):
        row = self._row(title="Alpha Show")
        response = self.client.post(
            reverse("netflix_pending_resolve", args=[row.id])
            + "?show=all&filter=alpha&page=2",
            {
                "media_type": "movie",
                "tmdb_id": "555",
            },
        )
        self.assertEqual(response.status_code, 302)
        location = response.headers["Location"]
        self.assertIn("filter=alpha", location)
        self.assertIn("page=2", location)
        self.assertIn("show=all", location)
        self.assertNotIn("q=", location)

    def test_dismiss_keeps_filter_and_page(self):
        row = self._row(title="Alpha Show")
        response = self.client.post(
            reverse("netflix_pending_dismiss", args=[row.id])
            + "?filter=alpha&page=2",
        )
        self.assertEqual(response.status_code, 302)
        location = response.headers["Location"]
        self.assertIn("filter=alpha", location)
        self.assertIn("page=2", location)

    @patch.object(
        netflix.NetflixResolver,
        "_get_metadata",
        side_effect=[
            {"title": "Weeds", "image": "t.jpg"},
            {
                "title": "Season 8",
                "image": "s.jpg",
                "max_progress": 6,
                "episodes": [{"episode_number": 5, "title": "E5"}],
            },
        ],
    )
    def test_resolve_stamps_the_play_with_the_rows_run(self, mock_meta):
        """A play recorded on the review page belongs to the import that
        parked the row, so rolling that run back removes it.
        """
        run = ImportRun.objects.create(
            user=self.user, source="netflix", status=ImportRun.Status.COMPLETED
        )
        row = self._row(import_run=run)
        self.client.post(
            reverse("netflix_pending_resolve", args=[row.id]),
            {
                "media_type": "tv",
                "tmdb_id": "111",
                "season_number": "8",
                "episode_number": "5",
            },
        )
        episode = Episode.objects.get(related_season__user=self.user)
        self.assertEqual(episode.import_run_id, run.id)

    def test_row_is_scoped_to_its_user(self):
        other = get_user_model().objects.create_user(
            username="other", password="12345"
        )
        row = self._row()
        other_client = self.client
        other_client.force_login(other)
        response = other_client.post(
            reverse("netflix_pending_dismiss", args=[row.id])
        )
        self.assertEqual(response.status_code, 404)
        row.refresh_from_db()
        self.assertEqual(row.status, NetflixPendingRow.Status.PENDING.value)


class NetflixTaskTests(TestCase):
    """Task wiring and the TMDB precondition."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="test", password="12345"
        )

    @patch("app.providers.tmdb.enabled", return_value=True)
    @patch("integrations.imports.trakt.services.search")
    def test_task_imports_csv(self, mock_search, mock_enabled):
        from integrations import tasks

        mock_search.return_value = {"results": []}
        message = tasks.import_netflix(
            BytesIO(_csv("Title,Date", "Unbekannt,11/20/26")),
            self.user.id,
            "new",
        )
        self.assertIn("Netflix", message)
        self.assertTrue(NetflixPendingRow.objects.exists())

    def test_importer_raises_without_tmdb(self):
        with patch(
            "integrations.imports.netflix.app.providers.tmdb.enabled",
            return_value=False,
        ):
            with self.assertRaises(MediaImportError):
                netflix.importer(
                    BytesIO(_csv("Title,Date", "Arrival,11/20/26")),
                    self.user,
                    "new",
                )


class NetflixRetryTests(TestCase):
    """Re-running parked rows through the improved matcher."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="test", password="12345"
        )
        self.client.force_login(self.user)
        self.run = ImportRun.objects.create(
            user=self.user,
            source="netflix",
            status=ImportRun.Status.COMPLETED.value,
        )
        self.resolvable = NetflixPendingRow.objects.create(
            user=self.user,
            title=(
                "Food Wars!: Shokugeki no Soma: The Second Plate: "
                "Pomp & Circumstance"
            ),
            watched_at=date(2019, 7, 28),
            raw_date="7/28/19",
            media_type=MediaTypes.MOVIE.value,
            import_run_id=self.run.id,
        )
        self.unresolvable = NetflixPendingRow.objects.create(
            user=self.user,
            title="Unmatched: Show: Title",
            watched_at=date(2019, 7, 28),
            raw_date="7/28/19",
            media_type=MediaTypes.MOVIE.value,
            import_run_id=self.run.id,
        )

    def _mocks(self, mock_search, mock_meta):
        mock_search.side_effect = [
            {"results": []},
            {"results": []},
            {
                "results": [
                    {
                        "media_id": 62273,
                        "name": "Food Wars! Shokugeki no Soma",
                    }
                ]
            },
            {"results": []},
            {"results": []},
            {"results": []},
        ]
        show_meta = _named_show_meta(
            [(1, 24, "Season 1"), (2, 13, "The Second Plate")],
        )
        season_meta = {
            "title": "Season 2",
            "image": "s.jpg",
            "max_progress": 13,
            "episodes": [{"episode_number": 13, "title": "Pomp & Circumstance"}],
        }
        mock_meta.side_effect = [show_meta, season_meta, show_meta, season_meta]

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_retry_records_and_removes_resolvable_row(self, mock_meta,
                                                      mock_search):
        from integrations import tasks

        self._mocks(mock_search, mock_meta)

        tasks.retry_netflix_pending(self.user.id)

        remaining = NetflixPendingRow.objects.all()
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(remaining.first().id, self.unresolvable.id)
        episode = Episode.objects.get(import_run_id=self.run.id)
        self.assertEqual(episode.item.season_number, 2)
        self.assertEqual(episode.item.episode_number, 13)

    @patch("integrations.imports.trakt.services.search")
    @patch.object(netflix.NetflixResolver, "_get_metadata")
    def test_retry_view_queues_task_and_removes_resolvable_row(
        self, mock_meta, mock_search
    ):
        self._mocks(mock_search, mock_meta)

        response = self.client.post(reverse("netflix_pending_retry"))

        self.assertRedirects(response, reverse("netflix_pending"))
        self.assertEqual(NetflixPendingRow.objects.count(), 1)
        messages = [m.message for m in get_messages(response.wsgi_request)]
        self.assertTrue(
            any("auto-matching" in m.lower() for m in messages),
            messages,
        )
