"""Worker registry is validated in a fresh process without web imports."""

import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase


class BackgroundTaskRegistryTests(SimpleTestCase):
    def test_background_loader_registers_game_group_chain_without_web_imports(self):
        code = """
import django
from django.conf import settings
settings.TESTING = True
django.setup()
from config.celery import app
app.loader.import_default_modules()
required = {"app.tasks.reconcile_game_groups_backfill", "app.tasks.populate_game_group_backfill_queue", "app.tasks.populate_game_group_data_for_items"}
assert required <= set(app.tasks), required - set(app.tasks)
"""
        env = dict(
            os.environ,
            DJANGO_SETTINGS_MODULE="config.test_settings",
            FLOPPY_PROCESS_ROLE="background",
            PYTHONPATH=str(Path(__file__).resolve().parents[2]),
        )
        result = subprocess.run(  # noqa: S603 - fixed interpreter and literal child program
            [sys.executable, "-c", code],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-2000:])
