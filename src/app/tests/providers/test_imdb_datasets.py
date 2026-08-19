import gzip
import io
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from app.providers import imdb_datasets


def _gzip_tsv(header: list[str], rows: list[list[str]]) -> io.BytesIO:
    lines = ["\t".join(header)] + ["\t".join(row) for row in rows]
    raw = ("\n".join(lines) + "\n").encode("utf-8")
    return io.BytesIO(gzip.compress(raw))


def _mock_urlopen(payload: io.BytesIO):
    cm = MagicMock()
    cm.__enter__.return_value = payload
    cm.__exit__.return_value = False
    return cm


class DownloadVideogameTitleIndexTests(SimpleTestCase):
    def test_filters_to_video_game_titles_and_parses_year(self):
        payload = _gzip_tsv(
            ["tconst", "titleType", "primaryTitle", "startYear"],
            [
                ["tt0000001", "videoGame", "Dispatch", "2025"],
                ["tt0000002", "movie", "Not A Game", "2020"],
                ["tt0000003", "videoGame", "No Year Game", "\\N"],
            ],
        )
        with patch(
            "app.providers.imdb_datasets.urllib.request.urlopen",
            return_value=_mock_urlopen(payload),
        ):
            index = imdb_datasets.download_videogame_title_index()

        self.assertEqual(
            index,
            {
                "tt0000001": ("Dispatch", 2025),
                "tt0000003": ("No Year Game", None),
            },
        )


class DownloadPrincipalsTests(SimpleTestCase):
    def test_filters_to_requested_tconsts(self):
        payload = _gzip_tsv(
            ["tconst", "ordering", "nconst", "category", "job", "characters"],
            [
                ["tt0000001", "1", "nm0000001", "actor", "\\N", '["Sam"]'],
                ["tt0000001", "2", "nm0000002", "director", "Director", "\\N"],
                ["tt0000099", "1", "nm0000099", "actor", "\\N", "\\N"],
            ],
        )
        with patch(
            "app.providers.imdb_datasets.urllib.request.urlopen",
            return_value=_mock_urlopen(payload),
        ):
            result = imdb_datasets.download_principals({"tt0000001"})

        self.assertEqual(set(result.keys()), {"tt0000001"})
        rows = {row["nconst"]: row for row in result["tt0000001"]}
        self.assertEqual(rows["nm0000001"]["category"], "actor")
        self.assertEqual(rows["nm0000001"]["characters"], '["Sam"]')
        self.assertEqual(rows["nm0000002"]["job"], "Director")

    def test_empty_tconsts_short_circuits(self):
        with patch(
            "app.providers.imdb_datasets.urllib.request.urlopen"
        ) as mock_urlopen:
            result = imdb_datasets.download_principals(set())
        self.assertEqual(result, {})
        mock_urlopen.assert_not_called()


class DownloadNamesTests(SimpleTestCase):
    def test_filters_to_requested_nconsts(self):
        payload = _gzip_tsv(
            ["nconst", "primaryName"],
            [
                ["nm0000001", "Alice Actor"],
                ["nm0000002", "Bob Director"],
            ],
        )
        with patch(
            "app.providers.imdb_datasets.urllib.request.urlopen",
            return_value=_mock_urlopen(payload),
        ):
            names = imdb_datasets.download_names({"nm0000001"})

        self.assertEqual(names, {"nm0000001": "Alice Actor"})
