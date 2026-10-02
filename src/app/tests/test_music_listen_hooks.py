"""Drop-in music listen hooks."""

import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from app.signals_music import load_music_listen_hooks, music_listen_recorded


class MusicListenHookTests(SimpleTestCase):
    """Hook directory loading and signal delivery."""

    def test_unset_dir_loads_nothing(self):
        """An empty MUSIC_HOOKS_DIR is a no-op."""
        with override_settings(MUSIC_HOOKS_DIR=""):
            load_music_listen_hooks()

    def test_hook_file_receives_the_signal(self):
        """A dropped-in module connects and sees music plus event."""
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "seen.txt"
            Path(tmp, "capture.py").write_text(
                "from django.dispatch import receiver\n"
                "from app.signals_music import music_listen_recorded\n"
                f"MARKER = {str(marker)!r}\n"
                "@receiver(music_listen_recorded, dispatch_uid='test-capture')\n"
                "def _capture(sender, music, event, **kwargs):\n"
                "    open(MARKER, 'w').write(f'{music}|{event}')\n"
            )
            with override_settings(MUSIC_HOOKS_DIR=tmp):
                load_music_listen_hooks()
                music_listen_recorded.send(sender=object, music="row", event="evt")
            self.assertEqual(marker.read_text(), "row|evt")
        music_listen_recorded.disconnect(dispatch_uid="test-capture")
