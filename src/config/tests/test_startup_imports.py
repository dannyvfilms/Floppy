import json
import os
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase

# Starting Django in a subprocess takes a second or two; this is a wedge
# detector, not a performance bound.
_SUBPROCESS_TIMEOUT_SECONDS = 120


class WebStartupImportTests(SimpleTestCase):
    def test_background_workers_register_game_group_tasks(self):
        script = """
import json
import sys

sys.argv = ["celery", "-A", "config", "worker"]
import django

django.setup()
from config.celery import app

app.loader.import_default_modules()
names = (
    "app.tasks.reconcile_game_groups_backfill",
    "app.tasks.populate_game_group_data_for_items",
    "app.tasks.populate_game_group_backfill_queue",
)
print(json.dumps({name: name in app.tasks for name in names}, sort_keys=True))
"""
        for role in ("background", "combined"):
            with self.subTest(role=role):
                environment = os.environ.copy()
                environment["DJANGO_SETTINGS_MODULE"] = "config.test_settings"
                environment["FLOPPY_PROCESS_ROLE"] = role
                environment["PYTHONPATH"] = str(settings.BASE_DIR)
                result = subprocess.run(  # noqa: S603
                    [sys.executable, "-c", script],
                    check=True,
                    timeout=_SUBPROCESS_TIMEOUT_SECONDS,
                    capture_output=True,
                    text=True,
                    env=environment,
                )
                registered = json.loads(result.stdout.splitlines()[-1])
                self.assertTrue(all(registered.values()), registered)

    def test_url_loading_does_not_import_task_aggregators(self):
        script = """
import json
import sys

import django

django.setup()
from django.urls import get_resolver

get_resolver().url_patterns
loaded = sorted(
    name
    for name in sys.modules
    if name == "app.tasks" or name.startswith("integrations.tasks._")
)
print(json.dumps(loaded))
"""
        environment = os.environ.copy()
        environment["DJANGO_SETTINGS_MODULE"] = "config.test_settings"
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

        self.assertEqual(json.loads(result.stdout.splitlines()[-1]), [])

    def test_interactive_worker_loads_only_interactive_task_modules(self):
        script = """
import json

import django

django.setup()
from config.celery import app

app.loader.import_default_modules()
names = (
    "Resolve live playback image",
    "app.tasks.refresh_statistics_cache_task",
    "app.tasks.statistics_sync_task",
    "Reconcile statistics sync",
    "Process media server webhook",
    "Process Stremio playback webhook",
    "Process Stremio tracker event",
    "Verify Stremio playback completion",
    "Refresh Plex library sections",
    "Import from CLZ",
    "app.tasks.reconcile_game_groups_backfill",
)
print(json.dumps({name: name in app.tasks for name in names}, sort_keys=True))
"""
        environment = os.environ.copy()
        environment["DJANGO_SETTINGS_MODULE"] = "config.test_settings"
        environment["FLOPPY_PROCESS_ROLE"] = "interactive"
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

        registered = json.loads(result.stdout.splitlines()[-1])
        self.assertFalse(registered.pop("Import from CLZ"))
        self.assertFalse(registered.pop("app.tasks.reconcile_game_groups_backfill"))
        self.assertTrue(all(registered.values()))


class ImportResidencyTests(SimpleTestCase):
    """Keep heavy third-party imports out of the long-lived processes.

    Every resident process pays for whatever is imported at module scope, and
    these libraries are each tens of megabytes that only a few code paths ever
    need. Deferring one is easy to undo by accident -- re-adding a top-level
    import restores the cost silently -- so each is asserted absent per role.
    """

    # Measured in isolation: aiohttp ~22 MiB, apprise ~17 MiB, bs4 ~12 MiB,
    # qrcode ~7 MiB (it pulls Pillow), Pillow ~5 MiB.
    DEFERRED = ("apprise", "PIL", "qrcode", "aiohttp", "bs4", "debug_toolbar")

    def _loaded(self, role):
        """Return which deferred modules a role has resident once started.

        A Celery role is measured after ``import_default_modules``, because
        that is what a worker does at boot and it is where autodiscovery pulls
        the task modules in. A web process is measured after URL resolution.
        """
        script = f"""
import json
import os
import sys

import django

django.setup()
if os.environ.get("FLOPPY_PROCESS_ROLE") in ("background", "combined", "interactive"):
    from config.celery import app

    app.loader.import_default_modules()
else:
    from django.urls import get_resolver

    get_resolver().url_patterns
watched = {self.DEFERRED!r}
print(json.dumps(sorted(name for name in watched if name in sys.modules)))
"""
        environment = os.environ.copy()
        environment["DJANGO_SETTINGS_MODULE"] = "config.test_settings"
        environment["PYTHONPATH"] = str(settings.BASE_DIR)
        # A developer .env with DEBUG=True turns on the debug toolbar, which
        # production never loads.
        environment["DEBUG"] = "False"
        if role:
            environment["FLOPPY_PROCESS_ROLE"] = role
        else:
            environment.pop("FLOPPY_PROCESS_ROLE", None)
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
        return json.loads(result.stdout.splitlines()[-1])

    def test_web_process_defers_them(self):
        """Serving a request must not require a notifier or an image decoder."""
        self.assertEqual(self._loaded(""), [])

    def test_background_worker_defers_them(self):
        """The background worker imports every task module, and still must not.

        This is the role that regressed most easily: autodiscovery imports
        events.tasks, which reached apprise through events.notifications.
        """
        self.assertEqual(self._loaded("background"), [])

    def test_interactive_worker_defers_them(self):
        """The interactive worker is the smallest role and must stay so."""
        self.assertEqual(self._loaded("interactive"), [])
