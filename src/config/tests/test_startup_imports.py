import json
import os
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase


class WebStartupImportTests(SimpleTestCase):
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
    "Process media server webhook",
    "Process Stremio playback webhook",
    "Verify Stremio playback completion",
    "Refresh Plex library sections",
    "Import from CLZ",
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
            capture_output=True,
            text=True,
            env=environment,
        )

        registered = json.loads(result.stdout.splitlines()[-1])
        self.assertFalse(registered.pop("Import from CLZ"))
        self.assertTrue(all(registered.values()))
