from django.contrib.auth import get_user_model
from django.test import TestCase

from app import helpers
from app.collection_views import _completeness_matching_keys
from app.models import CollectionEntry, Item, MediaTypes, Sources


class CompletenessMatchingKeysTest(TestCase):
    """The SQL-aggregated filter agrees with the per-episode completeness map."""

    def _item(self, media_id, media_type, season=None, episode=None):
        return Item.objects.create(
            media_id=media_id,
            source=Sources.TMDB.value,
            media_type=media_type,
            season_number=season,
            episode_number=episode,
            title=media_id,
            image="x",
        )

    def test_matches_reference_for_every_ownership_shape(self):
        user = get_user_model().objects.create_user(username="c", password="x")
        other = get_user_model().objects.create_user(username="o", password="x")
        shows = {}
        # shape: (owned show, owned season numbers, owned episode (season, ep))
        shapes = {
            "none": (False, [], []),
            "show_only": (True, [], []),
            "season_1": (False, [1], []),
            "season_1_show": (True, [1], []),
            "all_seasons": (False, [1, 2], []),
            "episodes_some": (False, [], [(1, 1), (2, 2)]),
            "episodes_all": (False, [], [(s, e) for s in (1, 2) for e in (1, 2)]),
            "empty_show": (True, [], []),
        }
        for name, (show_owned, seasons, episodes) in shapes.items():
            show = self._item(name, MediaTypes.TV.value)
            shows[name] = show
            if name != "empty_show":
                for season in (1, 2):
                    self._item(name, MediaTypes.SEASON.value, season)
                    for ep in (1, 2):
                        self._item(name, MediaTypes.EPISODE.value, season, ep)
            if show_owned:
                CollectionEntry.objects.create(user=user, item=show)
            for season in seasons:
                CollectionEntry.objects.create(
                    user=user,
                    item=Item.objects.get(
                        media_id=name,
                        media_type=MediaTypes.SEASON.value,
                        season_number=season,
                    ),
                )
            for season, ep in episodes:
                CollectionEntry.objects.create(
                    user=user,
                    item=Item.objects.get(
                        media_id=name,
                        media_type=MediaTypes.EPISODE.value,
                        season_number=season,
                        episode_number=ep,
                    ),
                )
        # Another user's ownership must not leak in.
        CollectionEntry.objects.create(user=other, item=shows["none"])

        keys = {(show.media_id, show.source) for show in shows.values()}
        stats = helpers.get_collection_completeness_map(user, shows.values())
        for mode in ("partial", "full"):
            expected = {
                (show.media_id, show.source)
                for show in shows.values()
                if stats[show.id]["total"]
                and (
                    stats[show.id]["is_partial"]
                    if mode == "partial"
                    else stats[show.id]["collected"] == stats[show.id]["total"]
                )
            }
            self.assertEqual(_completeness_matching_keys(user, keys, mode), expected)
            self.assertTrue(expected, mode)
