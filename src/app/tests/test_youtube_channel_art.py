"""Channel artwork uses bounded YouTube metadata with a safe fallback."""

from unittest.mock import MagicMock, patch

import requests
from django.core.cache import cache
from django.test import SimpleTestCase

from app.youtube_channel_art import video_details


class YouTubeChannelArtworkTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @patch("app.youtube_channel_art.requests.get")
    def test_extracts_and_caches_the_video_owner_avatar(self, get):
        response = MagicMock(status_code=200)
        response.iter_content.return_value = [
            b'{"owner":{"videoOwnerRenderer":{"thumbnail":{"thumbnails":['
            b'{"url":"https://yt3.ggpht.com/avatar=s176"}]}}}}'
        ]
        get.return_value.__enter__.return_value = response
        self.assertEqual(
            video_details("vidAAAAAAAA")["avatar"], "https://yt3.ggpht.com/avatar=s176"
        )
        self.assertEqual(
            video_details("vidAAAAAAAA")["avatar"], "https://yt3.ggpht.com/avatar=s176"
        )
        get.assert_called_once()
        self.assertFalse(get.call_args.kwargs["allow_redirects"])

    @patch("app.youtube_channel_art.requests.get")
    def test_rejects_untrusted_image_and_invalid_video_id(self, get):
        response = MagicMock(status_code=200)
        response.iter_content.return_value = [
            b'{"owner":{"videoOwnerRenderer":{"thumbnail":{"thumbnails":['
            b'{"url":"https://evil.example/avatar"}]}}}}'
        ]
        get.return_value.__enter__.return_value = response
        self.assertEqual(video_details("vidAAAAAAAA")["avatar"], "")
        self.assertEqual(video_details("../../bad")["avatar"], "")
        get.assert_called_once()

    @patch("app.youtube_channel_art.requests.get")
    def test_network_failure_is_cached_briefly(self, get):
        get.side_effect = requests.Timeout()
        self.assertEqual(video_details("vidAAAAAAAA")["avatar"], "")
        self.assertEqual(video_details("vidAAAAAAAA")["avatar"], "")
        get.assert_called_once()

    @patch("app.youtube_channel_art.requests.get")
    def test_returns_description_for_matching_video(self, get):
        response = MagicMock(status_code=200)
        response.iter_content.return_value = [
            b'var ytInitialPlayerResponse = {"videoDetails":'
            b'{"videoId":"vidAAAAAAAA","shortDescription":"Line one\\nLine two"}};'
        ]
        get.return_value.__enter__.return_value = response
        self.assertEqual(
            video_details("vidAAAAAAAA")["description"], "Line one\nLine two"
        )
