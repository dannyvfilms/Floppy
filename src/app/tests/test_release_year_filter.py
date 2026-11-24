import datetime

from django.test import TestCase

from app.models import Item, MediaTypes, Sources
from app.models.manager import release_year_q


def _at(year, month=1, day=15):
    return datetime.datetime(year, month, day, 12, tzinfo=datetime.UTC)


class SeasonReleaseYearFilterTest(TestCase):
    """A season with no date of its own filters by its earliest episode's year."""

    def _item(self, media_type, season=None, episode=None, released=None, media_id="1"):
        return Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=media_type,
            season_number=season,
            episode_number=episode,
            title=f"{media_type}{season}",
            image="x",
            release_datetime=released,
        )

    def _ids(self, year):
        return set(
            Item.objects.filter(release_year_q(year)).values_list("pk", flat=True),
        )

    def test_undated_season_matches_its_first_episode_year(self):
        self._item(MediaTypes.TV.value, released=_at(2024))
        s1 = self._item(MediaTypes.SEASON.value, 1, released=_at(2024))
        s2 = self._item(MediaTypes.SEASON.value, 2)
        self._item(MediaTypes.EPISODE.value, 2, 1, _at(2026))

        self.assertIn(s2.pk, self._ids(2026))
        self.assertNotIn(s2.pk, self._ids(2024))
        self.assertIn(s1.pk, self._ids(2024))
        self.assertNotIn(s1.pk, self._ids(2026))
        self.assertNotIn(s2.pk, self._ids("unknown"))

    def test_season_spanning_years_belongs_to_the_first(self):
        season = self._item(MediaTypes.SEASON.value, 1)
        self._item(MediaTypes.EPISODE.value, 1, 1, _at(2025, 12, 30))
        self._item(MediaTypes.EPISODE.value, 1, 2, _at(2026, 1, 6))

        self.assertIn(season.pk, self._ids(2025))
        self.assertNotIn(season.pk, self._ids(2026))

    def test_season_without_any_date_is_unknown(self):
        season = self._item(MediaTypes.SEASON.value, 1)
        self._item(MediaTypes.EPISODE.value, 1, 1)

        self.assertIn(season.pk, self._ids("unknown"))
        self.assertNotIn(season.pk, self._ids(2026))
