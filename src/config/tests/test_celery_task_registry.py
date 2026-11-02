"""Every Celery task must be loaded by the worker that is meant to run it.

``app.autodiscover_tasks()`` only imports each app's ``tasks`` module. A task
defined anywhere else (``integrations/tasks/_*.py``, ``app/tasks_*.py``) is
unknown to the worker unless something it loads imports it, typically a
``CELERY_IMPORTS`` entry; the queued message is then discarded as "unregistered
task" (#1726, #1827). The worker's real module set is measured in a clean
subprocess, so a lazy re-export cannot hide a gap.
"""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

SRC = Path(settings.BASE_DIR)
DECORATORS = {"shared_task", "task"}


def _defines_task(path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            name = getattr(target, "attr", getattr(target, "id", ""))
            if name in DECORATORS:
                return True
    return False


def _module(path):
    parts = path.relative_to(SRC).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


class CeleryTaskRegistryTests(SimpleTestCase):
    def test_every_task_module_is_loaded_by_the_worker(self):
        probe = (
            "import json, sys, django; django.setup();"
            "from config.celery import app;"
            "app.loader.import_default_modules();"
            "print(json.dumps(sorted(sys.modules)))"
        )
        env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.test_settings"}
        env.pop("FLOPPY_PROCESS_ROLE", None)
        out = subprocess.run(  # noqa: S603
            [sys.executable, "-c", probe],
            cwd=SRC,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        loaded = set(json.loads(out.splitlines()[-1]))
        missing = []
        for path in sorted(SRC.glob("*/**/*.py")):
            parts = path.relative_to(SRC).parts
            if "tests" in parts or "migrations" in parts or parts[0] == "config":
                continue
            module = _module(path)
            if module not in loaded and _defines_task(path):
                missing.append(module)
        self.assertEqual(
            missing,
            [],
            "These modules define Celery tasks but the background worker never "
            "imports them, so it discards their messages as unregistered. Add "
            "them to CELERY_IMPORTS in src/config/settings.py.",
        )
