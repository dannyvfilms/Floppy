"""Drop-in music listen hooks."""

import gc
import sys
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from app.signals_music import load_music_listen_hooks, music_listen_recorded

# Hook files live in the repo, not a temp dir, so coverage can find their source.
FIXTURES = Path(__file__).parent / "music_hook_fixtures"


class MusicListenHookTests(SimpleTestCase):
    """Hook directory loading and signal delivery."""

    def test_unset_dir_loads_nothing(self):
        """An empty MUSIC_HOOKS_DIR is a no-op."""
        with override_settings(MUSIC_HOOKS_DIR=""):
            load_music_listen_hooks()

    def test_hook_file_receives_the_signal(self):
        """A dropped-in module connects and sees music plus event."""
        self.addCleanup(music_listen_recorded.disconnect, dispatch_uid="test-capture")
        with override_settings(MUSIC_HOOKS_DIR=str(FIXTURES / "capture")):
            load_music_listen_hooks()
            gc.collect()  # a hook must survive garbage collection
            music_listen_recorded.send(sender=object, music="row", event="evt")
        seen = sys.modules["music_listen_hook_capture"].SEEN
        self.assertEqual(seen, [("row", "evt")])

    def test_broken_hook_file_does_not_stop_startup(self):
        """A hook that raises on import is logged and skipped."""
        with override_settings(MUSIC_HOOKS_DIR=str(FIXTURES / "broken")):
            with self.assertLogs("app.signals_music", "ERROR"):
                load_music_listen_hooks()

    def test_hook_that_fails_after_connecting_is_unhooked(self):
        """A half-loaded hook neither stays in sys.modules nor keeps receiving."""
        with override_settings(MUSIC_HOOKS_DIR=str(FIXTURES / "partial")):
            with self.assertLogs("app.signals_music", "ERROR"):
                load_music_listen_hooks()
        gc.collect()
        music_listen_recorded.send(sender=object, music="row", event="evt")
        self.assertNotIn("music_listen_hook_partial", sys.modules)
        self.assertFalse(
            any(
                getattr(ref(), "__name__", "") == "_capture"
                for _, ref, *_ in music_listen_recorded.receivers
            )
        )
