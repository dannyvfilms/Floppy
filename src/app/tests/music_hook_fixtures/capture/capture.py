"""Fixture hook for test_music_listen_hooks: records every signal it receives."""

from django.dispatch import receiver

from app.signals_music import music_listen_recorded

SEEN = []


@receiver(music_listen_recorded, dispatch_uid="test-capture")
def _capture(sender, music, event, **kwargs):
    SEEN.append((music, event))
