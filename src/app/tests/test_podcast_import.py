from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from app.models import PodcastShow, Sources
from app.services import podcast_import


class ResolveShowMetadataTests(SimpleTestCase):
    """Tests for resolve_show_metadata's RSS-fallback guard."""

    @patch("integrations.podcast_rss.fetch_show_metadata_from_rss")
    def test_fetches_rss_for_website_url_even_with_a_description(self, mock_rss):
        """A description from iTunes alone must not skip the RSS fetch.

        website_url never comes from iTunes, so the RSS feed still needs to
        be read even when iTunes already supplied a description.
        """
        mock_rss.return_value = {"website_url": "https://example.com/show"}

        resolved = podcast_import.resolve_show_metadata(
            {"description": "From iTunes."},
            "https://example.com/feed.xml",
        )

        mock_rss.assert_called_once_with("https://example.com/feed.xml")
        self.assertEqual(resolved["description"], "From iTunes.")
        self.assertEqual(resolved["website_url"], "https://example.com/show")

    @patch("integrations.podcast_rss.fetch_show_metadata_from_rss")
    def test_skips_rss_fetch_once_description_and_website_url_are_present(
        self, mock_rss
    ):
        resolved = podcast_import.resolve_show_metadata(
            {
                "description": "From iTunes.",
                "website_url": "https://example.com/show",
            },
            "https://example.com/feed.xml",
        )

        mock_rss.assert_not_called()
        self.assertEqual(resolved["website_url"], "https://example.com/show")


class ImportShowFromFeedUrlTests(TestCase):
    """Tests for importing a GPodder search result by its RSS feed."""

    @patch("app.fork_services_podcast.refresh_show_episodes_from_rss")
    @patch("integrations.podcast_rss.fetch_feed_from_rss")
    def test_imports_show_and_episodes_from_feed(self, mock_feed, mock_refresh):
        mock_feed.return_value = (
            {
                "title": "Linux Outlaws",
                "author": "Sixgun Productions",
                "description": "New media, new rules",
                "language": "en",
                "image": "https://example.com/linux.jpg",
                "website_url": "https://linuxoutlaws.com",
            },
            [{"title": "Episode 1"}],
        )

        show = podcast_import.import_show_from_feed_url(
            "https://example.com/linux.xml"
        )

        self.assertEqual(show.source, Sources.GPODDER.value)
        self.assertEqual(show.title, "Linux Outlaws")
        self.assertEqual(show.rss_feed_url, "https://example.com/linux.xml")
        self.assertTrue(show.podcast_uuid.startswith("gp_"))
        mock_feed.assert_called_once_with("https://example.com/linux.xml")
        mock_refresh.assert_called_once_with(show, [{"title": "Episode 1"}])

    @patch("integrations.podcast_rss.fetch_feed_from_rss")
    def test_reuses_existing_show_with_the_same_feed(self, mock_feed):
        existing = PodcastShow.objects.create(
            podcast_uuid="itunes:123",
            source=Sources.POCKETCASTS.value,
            title="Already Tracked",
            rss_feed_url="https://example.com/linux.xml",
        )

        show = podcast_import.import_show_from_feed_url(
            "https://example.com/linux.xml"
        )

        self.assertEqual(show, existing)
        mock_feed.assert_not_called()

    @patch("integrations.podcast_rss.fetch_feed_from_rss")
    def test_unreadable_feed_raises_import_error(self, mock_feed):
        mock_feed.return_value = ({}, [])

        with self.assertRaises(podcast_import.PodcastImportError):
            podcast_import.import_show_from_feed_url(
                "https://example.com/missing.xml"
            )

        self.assertFalse(
            PodcastShow.objects.filter(
                rss_feed_url="https://example.com/missing.xml"
            ).exists()
        )
