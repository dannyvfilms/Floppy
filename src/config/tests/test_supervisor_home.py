"""Programs run as ``abc`` must not inherit root's HOME (#2051).

supervisord keeps ``HOME=/root`` when it drops to ``abc``. libpq then tries to
read ``/root/.postgresql/postgresql.crt``, fails with permission denied, drops
every TLS handshake and falls back to plaintext, so a TLS Postgres server logs
one "could not accept SSL connection" error per connection.
"""

import configparser
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[3]
SUPERVISOR_FILES = (
    "supervisord.conf",
    "scripts/install/templates/supervisord.install.conf.tmpl",
)


class SupervisorHomeTests(SimpleTestCase):
    def test_home_is_not_roots(self):
        for name in SUPERVISOR_FILES:
            with self.subTest(file=name):
                parser = configparser.RawConfigParser(strict=False)
                parser.read_string((ROOT / name).read_text())
                environment = parser.get("supervisord", "environment")
                self.assertIn('HOME="/nonexistent"', environment)
