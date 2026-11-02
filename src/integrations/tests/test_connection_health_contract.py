"""Guard the connection-health contract (docs/architecture/connection-health.md).

``connection_broken`` may only be set for rejected or unusable credentials, and
the shared recorder is where that decision lives. A new direct write is how a
timeout starts latching an account disconnected again (#1267), so any file
that sets the flag by hand must be reviewed and listed here.
"""

import re
from pathlib import Path

from django.test import SimpleTestCase

SRC = Path(__file__).resolve().parents[2]
SCANNED = ("integrations", "lists")
DIRECT_WRITE = re.compile(r"connection_broken\s*=\s*True\b")

# Each entry sets the flag only for a failure that already proves the
# credentials are bad; keep the reason current when touching the file.
REVIEWED_DIRECT_WRITERS = {
    "integrations/connection_health.py": "the shared recorder itself",
    "integrations/tasks/_koito.py": "history import, only on KoitoAuthError",
    "integrations/tasks/_lastfm.py": "Last.fm error 6: the user no longer exists",
    "integrations/imports/pocketcasts.py": "rejected login or refresh only",
}


class ConnectionHealthContractTests(SimpleTestCase):
    """Direct ``connection_broken = True`` writes stay reviewed."""

    def test_direct_writes_are_reviewed(self):
        writers = set()
        for package in SCANNED:
            for path in (SRC / package).rglob("*.py"):
                relative = path.relative_to(SRC).as_posix()
                if "/tests/" in relative or "/migrations/" in relative:
                    continue
                if DIRECT_WRITE.search(path.read_text(encoding="utf-8")):
                    writers.add(relative)

        unreviewed = writers - REVIEWED_DIRECT_WRITERS.keys()
        self.assertFalse(
            unreviewed,
            "Use integrations.connection_health.record_failure(auth=...) instead "
            f"of setting connection_broken directly in: {sorted(unreviewed)}",
        )
        stale = REVIEWED_DIRECT_WRITERS.keys() - writers
        self.assertFalse(stale, f"Remove stale allowlist entries: {sorted(stale)}")
