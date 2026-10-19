"""The container's stop timeout must cover supervisord's stop windows.

supervisord stops programs one after another and SIGKILLs any that outlast its
``stopwaitsecs`` (10 s by default). Docker kills the whole container when its
own stop timeout (10 s by default) runs out. The compose files' grace period
has to be at least the longest sequence supervisord can take.
"""

import configparser
from pathlib import Path

import yaml
from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.postgres.yml",
    "scripts/install/templates/docker-compose.install.yml.tmpl",
)
SUPERVISOR_FILES = (
    "supervisord.conf",
    "scripts/install/templates/supervisord.install.conf.tmpl",
)
# The default and constrained tiers run up to two celery workers plus the web
# server; the third (discover) worker is never started alongside them.
SEQUENTIAL_PROGRAMS = ("gunicorn", "celery", "celery-interactive")


def _stop_windows(name):
    parser = configparser.RawConfigParser(strict=False)
    parser.read(ROOT / name, encoding="utf-8")
    return {
        program: int(parser[f"program:{program}"].get("stopwaitsecs", 10))
        for program in SEQUENTIAL_PROGRAMS
    }


def _grace_seconds(name):
    # Template placeholders are quoted strings or unquoted scalars; swap them
    # for plain text so the file parses as YAML.
    text = (ROOT / name).read_text(encoding="utf-8").replace("@@", "x")
    value = yaml.safe_load(text)["services"]["floppy"]["stop_grace_period"]
    return int(value.removesuffix("s"))


class ShutdownBudgetTests(SimpleTestCase):
    """Docker must not kill a container supervisord is still stopping."""

    def test_gunicorn_gets_its_graceful_timeout(self):
        for name in SUPERVISOR_FILES:
            with self.subTest(name):
                self.assertGreaterEqual(_stop_windows(name)["gunicorn"], 30)

    def test_compose_grace_period_covers_every_stop_window(self):
        for supervisor in SUPERVISOR_FILES:
            budget = sum(_stop_windows(supervisor).values())
            for compose in COMPOSE_FILES:
                with self.subTest(supervisor=supervisor, compose=compose):
                    self.assertGreaterEqual(_grace_seconds(compose), budget)
