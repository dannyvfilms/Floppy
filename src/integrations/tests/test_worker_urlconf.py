import json
import os
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase

from integrations import plex_cover

# Starting Django in a subprocess takes a second or two; this is a wedge
# detector, not a performance bound.
_SUBPROCESS_TIMEOUT_SECONDS = 120


class WorkerUrlBuildingTests(SimpleTestCase):
    """URLs built inside a Celery worker must resolve in a real worker process.

    A worker has an empty ROOT_URLCONF (``config.celery_urls``) and no allauth
    in INSTALLED_APPS. ``@override_settings(ROOT_URLCONF=...)`` only imitates
    the first half, so a test using it passes even when ``reverse()`` is
    pointed at ``config.urls``, which crashes in production (#1314). This runs
    the real worker settings in a subprocess instead.
    """

    def test_worker_can_build_trakt_refresh_and_plex_cover_urls(self):
        script = """
import json

import django

django.setup()
from django.conf import settings

from integrations import plex_cover
from integrations.imports import trakt

print(json.dumps({
    "urlconf": settings.ROOT_URLCONF,
    "allauth_installed": "allauth" in settings.INSTALLED_APPS,
    "trakt_redirect_uri": trakt._refresh_redirect_uri(),
    "plex_cover_url": plex_cover.build_cover_proxy_url(1, "machine", "/thumb/1"),
}))
"""
        environment = os.environ.copy()
        environment["DJANGO_SETTINGS_MODULE"] = "config.test_settings"
        environment["FLOPPY_PROCESS_ROLE"] = "background"
        environment["URLS"] = "https://floppy.example.com"
        environment["PYTHONPATH"] = str(settings.BASE_DIR)
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-c", script],
            check=True,
            # Bounded on purpose: a wedged interpreter must fail this test,
            # not hang the whole run until the CI job's limit expires.
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            capture_output=True,
            text=True,
            env=environment,
        )

        built = json.loads(result.stdout.splitlines()[-1])
        # Guard against the subprocess silently not being a worker.
        self.assertEqual(built["urlconf"], "config.celery_urls")
        self.assertFalse(built["allauth_installed"])
        self.assertEqual(
            built["trakt_redirect_uri"],
            "https://floppy.example.com/import/trakt/private",
        )
        self.assertTrue(
            built["plex_cover_url"].startswith(plex_cover.PROXY_PATH_PREFIX),
        )
