"""``migrate`` that names each step on its own line, with elapsed time and I/O.

Django writes ``Applying <name>...`` without a newline and only completes the
line when the step ends. Container logs are line-buffered, so a slow migration
never appears until it finishes: operators saw ``Running migrations:`` and
nothing else for the whole run. Every start is a complete line here.
"""

import sys
import time

from django.core.management.commands import migrate

_IO_PATH = "/proc/self/io"


def _read_bytes():
    """Return the bytes this process has read from storage, or None off Linux."""
    try:
        with open(_IO_PATH, encoding="ascii") as handle:  # noqa: PTH123
            for line in handle:
                if line.startswith("read_bytes:"):
                    return int(line.split(":", 1)[1])
    except (OSError, ValueError):
        return None
    return None


class Command(migrate.Command):
    """Run ``migrate`` with newline-terminated per-migration progress lines."""

    def migration_progress_callback(self, action, migration=None, fake=False):
        """Report each step as it starts and again with its elapsed time."""
        if self.verbosity < 1 or action not in (
            "apply_start",
            "apply_success",
            "unapply_start",
            "unapply_success",
        ):
            super().migration_progress_callback(action, migration, fake)
            return
        verb = "Applying" if action.startswith("apply") else "Unapplying"
        if action.endswith("_start"):
            self._step_started = time.monotonic()
            self._step_read = _read_bytes()
            self.stdout.write(f"  {verb} {migration} ...")
        else:
            elapsed = time.monotonic() - self._step_started
            detail = f"{elapsed:.1f}s"
            read = _read_bytes()
            if read is not None and self._step_read is not None:
                detail += f", read {(read - self._step_read) / 1_048_576:.0f}MB"
            outcome = "FAKED" if fake else "OK"
            self.stdout.write(self.style.SUCCESS(f"  {verb} {migration}: {outcome} ({detail})"))
        self.stdout.flush()
        sys.stderr.flush()
