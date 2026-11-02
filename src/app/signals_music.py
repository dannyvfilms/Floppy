"""Lifecycle signals for music scrobbles.

Receivers must not block. A receiver's job is to enqueue work and return.
"""

import importlib.util
import logging
import sys
from pathlib import Path

from django.conf import settings
from django.dispatch import Signal

logger = logging.getLogger(__name__)

# Fired once per completed listen, after record_music_playback stored it.
# kwargs: music (Music), event (MusicPlaybackEvent).
music_listen_recorded = Signal()


def load_music_listen_hooks():
    """Import every ``*.py`` file in ``MUSIC_HOOKS_DIR``.

    Import is the registration step: a hook connects itself with
    ``@receiver(music_listen_recorded)``. An empty or missing directory
    loads nothing.
    """
    raw = getattr(settings, "MUSIC_HOOKS_DIR", "") or ""
    hooks_dir = Path(raw)
    if not raw or not hooks_dir.is_dir():
        return
    for path in sorted(hooks_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        module_name = f"music_listen_hook_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            logger.warning("Skipping music listen hook %s: no loader", path)
            continue
        module = importlib.util.module_from_spec(spec)
        # @receiver holds its function weakly; without a reference to the
        # module, garbage collection silently unhooks it.
        sys.modules[module_name] = module
        connected = list(music_listen_recorded.receivers)
        try:
            spec.loader.exec_module(module)
        except Exception:
            logger.exception("Music listen hook %s failed to load", path.name)
            # Drop the half-loaded module and any receiver it connected first.
            del sys.modules[module_name]
            with music_listen_recorded.lock:
                music_listen_recorded.receivers = connected
                music_listen_recorded.sender_receivers_cache.clear()
            continue
        logger.info("Loaded music listen hook %s", path.name)
