"""Origin URL storage and the post-listen signal, through record_music_playback."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import Music
from app.services.music_scrobble import MusicPlaybackEvent, record_music_playback
from app.signals_music import music_listen_recorded

URL = "https://soundcloud.com/duskymusic/dusky-careless"


class MusicOriginUrlSignalTests(TestCase):
    """The play stores the origin URL and fires the signal once."""

    def setUp(self):
        """Create a music user and stub MusicBrainz lookups."""
        self.user = get_user_model().objects.create_user(username="origin-user")
        self.user.music_enabled = True
        self.user.save()
        for name in ("search", "search_artists"):
            patcher = patch(
                f"app.services.music_scrobble.musicbrainz.{name}",
                return_value={"results": [], "total_results": 0},
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        self.calls = []
        self.addCleanup(music_listen_recorded.disconnect, self._receiver)
        music_listen_recorded.connect(self._receiver, weak=False)

    def _receiver(self, sender, music, event, **kwargs):
        self.calls.append((music.pk, event.origin_url))

    def _event(self, origin_url="", **kwargs):
        return MusicPlaybackEvent(
            user=self.user,
            artist_name="Dusky",
            album_title="Careless",
            track_title="Careless",
            external_ids={},
            completed=True,
            played_at=timezone.now(),
            origin_url=origin_url,
            **kwargs,
        )

    def test_origin_url_is_stored_on_the_music_row(self):
        """A scrobble that sent a URL leaves it on the Music row."""
        music = record_music_playback(self._event(URL))
        self.assertEqual(Music.objects.get(pk=music.pk).origin_url, URL)

    def test_missing_url_stays_blank(self):
        """A scrobble without a URL leaves the column empty."""
        music = record_music_playback(self._event(""))
        self.assertEqual(Music.objects.get(pk=music.pk).origin_url, "")

    def test_later_scrobble_without_url_keeps_the_stored_one(self):
        """An empty URL never erases a stored one."""
        record_music_playback(self._event(URL))
        music = record_music_playback(self._event(""))
        self.assertEqual(Music.objects.get(pk=music.pk).origin_url, URL)

    def test_signal_fires_once_per_play_with_the_url(self):
        """One recorded play, one signal, carrying the event URL."""
        music = record_music_playback(self._event(URL))
        self.assertEqual(self.calls, [(music.pk, URL)])

    def test_failing_receiver_does_not_lose_the_play(self):
        """The play is stored even when a receiver raises."""

        def boom(sender, **kwargs):
            raise RuntimeError("hook bug")

        music_listen_recorded.connect(boom, weak=False)
        self.addCleanup(music_listen_recorded.disconnect, boom)
        with self.assertLogs("app.services.music_scrobble", "ERROR"):
            music = record_music_playback(self._event(URL))
        self.assertEqual(Music.objects.filter(user=self.user).count(), 1)
        self.assertEqual(self.calls, [(music.pk, URL)])

    def test_url_longer_than_the_column_is_skipped(self):
        """An over-long URL is not stored, so Postgres cannot reject the save."""
        music = record_music_playback(self._event("https://x.test/" + "a" * 600))
        self.assertEqual(Music.objects.get(pk=music.pk).origin_url, "")
