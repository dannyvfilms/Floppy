"""The web detail sidebar's projection matches what the shared React cards read."""

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from app.detail_secondary_props import (
    genre_library_counts,
    platform_collection_counts,
    web_sidebar_payload,
)
from app.models import CollectionEntry, Game, Item, MediaTypes, Sources, Status


class WebSidebarPayloadTests(SimpleTestCase):
    """Cover the pieces the Details, Genres, Studios and Collection cards need."""

    def context(self, **extra):
        """Return a minimal media-details template context."""
        return {
            "media": {
                "details": {"runtime": "1h 58min", "status": "Released"},
                "genres": ["Drama", "Sci-Fi"],
            },
            "media_type": "movie",
            "user": None,
            **extra,
        }

    def test_details_are_projected_with_labels(self):
        """Facts arrive display-formatted with the translated labels."""
        data = web_sidebar_payload(self.context(), "details")
        secondary = data["payload"]["secondary"]
        self.assertEqual(data["kind"], "details")
        self.assertEqual(secondary["display_details"]["runtime"], "1h 58min")
        self.assertEqual(secondary["labels"]["details"], "Details")
        self.assertEqual(secondary["watch_provider_region"], "UNSET")

    def test_genres_link_to_the_filtered_list(self):
        """Each genre links to the media list filtered by it."""
        entries = web_sidebar_payload(self.context(), "genres")["payload"]["tag_sections"][0]["entries"]
        self.assertEqual([entry["label"] for entry in entries], ["Drama", "Sci-Fi"])
        self.assertTrue(entries[1]["url"].endswith("?genre=Sci-Fi"))

    def test_collection_rows_skip_seasons_for_a_season(self):
        """A season only reports episodes; a show reports both."""
        stats = {"collected_seasons": 1, "total_seasons": 2, "collected_episodes": 3, "total_episodes": 4}
        show = web_sidebar_payload(self.context(media_type="tv", collection_stats=stats), "collection")
        season = web_sidebar_payload(self.context(media_type="season", collection_stats=stats), "collection")
        self.assertEqual([row["key"] for row in show["payload"]["collection_rows"]], ["seasons", "episodes"])
        self.assertEqual(show["payload"]["collection_rows"][0]["value"], "1/2 • 50%")
        self.assertEqual([row["key"] for row in season["payload"]["collection_rows"]], ["episodes"])

    def test_heading_needs_no_data(self):
        """A heading carries only its title."""
        self.assertEqual(
            web_sidebar_payload({}, "heading", "Collection"),
            {"kind": "heading", "title": "Collection", "payload": {}},
        )


class PlatformCountsTests(TestCase):
    """Platform rows report how many other games are collected on each platform."""

    def test_counts_games_per_listed_platform(self):
        """Each listed platform counts the viewer's collected games, this one included."""
        user = get_user_model().objects.create_user(username="counts", password="x")
        games = [
            Item.objects.create(
                media_id=str(number), source=Sources.MANUAL.value,
                media_type=MediaTypes.GAME.value, title=f"Game {number}",
            )
            for number in range(3)
        ]
        for game, platform in zip(games, ["PC (Windows)", "PC (Windows)", "Mac"], strict=True):
            CollectionEntry.objects.create(item=game, user=user, resolution=platform)
        counts = platform_collection_counts(user, games[0], {"platforms": ["PC (Windows)", "Mac", "Linux"]})
        self.assertEqual(counts, {"PC (Windows)": 2, "Mac": 1, "Linux": 0})
        self.assertEqual(platform_collection_counts(None, games[0], {"platforms": ["Mac"]}), {})

    def test_counts_other_tracked_items_per_genre(self):
        """A genre counts the viewer's tracked items of the same type, this one included."""
        user = get_user_model().objects.create_user(username="genres", password="x")
        items = [
            Item.objects.create(
                media_id=f"g{number}", source=Sources.MANUAL.value,
                media_type=MediaTypes.GAME.value, title=f"Game {number}", genres=genres,
            )
            for number, genres in enumerate([["Racing", "Action"], ["Racing"], ["Puzzle"]])
        ]
        for item in items:
            Game.objects.create(item=item, user=user, status=Status.COMPLETED.value)
        counts = genre_library_counts(user, items[0], "game", ["Racing", "Action", "Puzzle"])
        self.assertEqual(counts, {"Racing": 2, "Action": 1, "Puzzle": 1})
