"""The web detail sidebar's projection matches what the shared React cards read."""

from django.test import SimpleTestCase

from app.detail_secondary_props import web_sidebar_payload


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
