"""Fixture hook for test_music_listen_hooks: connects a receiver, then fails."""

from django.dispatch import receiver

from app.signals_music import music_listen_recorded

SEEN = []


@receiver(music_listen_recorded, dispatch_uid="test-partial")
def _capture(sender, music, event, **kwargs):
    SEEN.append(music)


msg = "failed after connecting"
raise RuntimeError(msg)
