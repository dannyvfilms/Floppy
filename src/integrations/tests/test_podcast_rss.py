from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from integrations import podcast_rss

ITUNES_IMAGE_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" version="2.0">
  <channel>
    <title>Example Show</title>
    <itunes:image href="https://example.com/itunes-art.jpg"/>
  </channel>
</rss>
"""

CHANNEL_IMAGE_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Show</title>
    <image>
      <url>https://example.com/rss-art.jpg</url>
    </image>
  </channel>
</rss>
"""

NO_IMAGE_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Show</title>
  </channel>
</rss>
"""

RSS_LINK_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Show</title>
    <link>https://example.com/show</link>
    <item>
      <title>Episode One</title>
      <link>https://example.com/show/episode-one</link>
    </item>
  </channel>
</rss>
"""

ATOM_LINK_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example Show</title>
  <link rel="self" href="https://example.com/feed.xml"/>
  <link rel="alternate" href="https://example.com/show"/>
  <entry>
    <title>Episode One</title>
    <id>episode-one</id>
    <link rel="enclosure" type="audio/mpeg" href="https://example.com/audio.mp3"/>
    <link rel="alternate" href="https://example.com/show/episode-one"/>
  </entry>
</feed>
"""

NO_LINK_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Show</title>
    <item>
      <title>Episode One</title>
    </item>
  </channel>
</rss>
"""


class FetchShowMetadataArtworkTests(SimpleTestCase):
    """Tests for artwork extraction in fetch_show_metadata_from_rss."""

    @patch("integrations.podcast_rss.safe_fetch")
    def test_prefers_itunes_image(self, mock_get):
        mock_get.return_value = (Mock(), ITUNES_IMAGE_FEED)

        metadata = podcast_rss.fetch_show_metadata_from_rss(
            "https://example.com/feed.xml"
        )

        self.assertEqual(metadata["image"], "https://example.com/itunes-art.jpg")

    @patch("integrations.podcast_rss.safe_fetch")
    def test_falls_back_to_channel_image_url(self, mock_get):
        mock_get.return_value = (Mock(), CHANNEL_IMAGE_FEED)

        metadata = podcast_rss.fetch_show_metadata_from_rss(
            "https://example.com/feed.xml"
        )

        self.assertEqual(metadata["image"], "https://example.com/rss-art.jpg")

    @patch("integrations.podcast_rss.safe_fetch")
    def test_no_image_omits_key(self, mock_get):
        mock_get.return_value = (Mock(), NO_IMAGE_FEED)

        metadata = podcast_rss.fetch_show_metadata_from_rss(
            "https://example.com/feed.xml"
        )

        self.assertNotIn("image", metadata)


class FetchShowMetadataWebsiteTests(SimpleTestCase):
    """Tests for website_url extraction in fetch_show_metadata_from_rss."""

    @patch("integrations.podcast_rss.safe_fetch")
    def test_reads_rss_link(self, mock_get):
        mock_get.return_value = (Mock(), RSS_LINK_FEED)

        metadata = podcast_rss.fetch_show_metadata_from_rss(
            "https://example.com/feed.xml"
        )

        self.assertEqual(metadata["website_url"], "https://example.com/show")

    @patch("integrations.podcast_rss.safe_fetch")
    def test_reads_atom_alternate_link(self, mock_get):
        mock_get.return_value = (Mock(), ATOM_LINK_FEED)

        metadata = podcast_rss.fetch_show_metadata_from_rss(
            "https://example.com/feed.xml"
        )

        self.assertEqual(metadata["website_url"], "https://example.com/show")

    @patch("integrations.podcast_rss.safe_fetch")
    def test_no_link_omits_key(self, mock_get):
        mock_get.return_value = (Mock(), NO_LINK_FEED)

        metadata = podcast_rss.fetch_show_metadata_from_rss(
            "https://example.com/feed.xml"
        )

        self.assertNotIn("website_url", metadata)


class FetchEpisodesWebsiteTests(SimpleTestCase):
    """Tests for website_url extraction in fetch_episodes_from_rss."""

    @patch("integrations.podcast_rss.safe_fetch")
    def test_reads_rss_item_link(self, mock_get):
        mock_get.return_value = (Mock(), RSS_LINK_FEED)

        episodes = podcast_rss.fetch_episodes_from_rss("https://example.com/feed.xml")

        self.assertEqual(
            episodes[0]["website_url"], "https://example.com/show/episode-one"
        )

    @patch("integrations.podcast_rss.safe_fetch")
    def test_reads_atom_entry_alternate_link_not_enclosure(self, mock_get):
        mock_get.return_value = (Mock(), ATOM_LINK_FEED)

        episodes = podcast_rss.fetch_episodes_from_rss("https://example.com/feed.xml")

        self.assertEqual(
            episodes[0]["website_url"], "https://example.com/show/episode-one"
        )

    @patch("integrations.podcast_rss.safe_fetch")
    def test_no_link_omits_key(self, mock_get):
        mock_get.return_value = (Mock(), NO_LINK_FEED)

        episodes = podcast_rss.fetch_episodes_from_rss("https://example.com/feed.xml")

        self.assertNotIn("website_url", episodes[0])
