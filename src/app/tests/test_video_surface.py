"""Checks for the YouTube video surface that history and stats share."""

from django.test import SimpleTestCase

from app.models import MediaTypes
from app.stats_youtube import youtube_thumbnail_url


class YoutubeThumbnailTests(SimpleTestCase):
    """Poster URL used when a video item has no stored image."""

    def test_builds_mqdefault_url(self):
        """A video id maps to the YouTube thumbnail host."""
        self.assertEqual(
            youtube_thumbnail_url("dQw4w9WgXcQ"),
            "https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg",
        )

    def test_blank_id_is_empty(self):
        """Missing ids do not invent a URL."""
        self.assertEqual(youtube_thumbnail_url(""), "")
        self.assertEqual(youtube_thumbnail_url(None), "")

    def test_video_has_icon_config(self):
        """Settings and calendar icons look up video in MEDIA_TYPE_CONFIG."""
        from app import config

        entry = config.MEDIA_TYPE_CONFIG[MediaTypes.VIDEO.value]
        self.assertIn("svg_icon", entry)
        self.assertEqual(
            config.get_collection_field_config(MediaTypes.VIDEO.value)["fields"],
            [],
        )

    def test_video_is_a_sidebar_type(self):
        """Videos sit in the media-type grid beside Music."""
        from users.models import User
        from users.views import SIDEBAR_MEDIA_TYPES

        self.assertIn(MediaTypes.VIDEO.value, SIDEBAR_MEDIA_TYPES)
        self.assertTrue(User._meta.get_field("video_enabled"))
