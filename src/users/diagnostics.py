"""Build the diagnostic report any signed-in user can attach to a bug report.

The full log download is limited to superusers because the log is instance-wide
and can name other accounts' activity. A regular user still needs something
reliable to attach to a bug report, so this report holds only what describes the
server rather than a person:

* versions and the process manager's exit history;
* an activity timeline: line counts per level in 10-minute blocks, with no
  message text, so a silent (hung) process and a busy one look different;
* the recent warnings and errors with their tracebacks;
* the tagged progress lines from ``app.progress_log``.

Other INFO lines are left out, because they can say what an account watched.
Account names and email addresses are removed from every line that is kept.
"""

from __future__ import annotations

import platform
import re
import sys
from collections import Counter, deque
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from app.log_safety import redact_secrets
from app.progress_log import PROGRESS_TAG

# floppy.log lines look like "[2026-10-02 13:39:14 +0000] [41] [WARNING] message".
_RECORD_START = re.compile(
    r"^\[(?P<ts>[^\]]+)\] \[(?P<pid>\d+)\] \[(?P<level>[A-Z]+)\] ?(?P<msg>.*)",
)
_TIME_FORMAT = "%Y-%m-%d %H:%M:%S %z"
_KEPT_LEVELS = frozenset({"WARNING", "ERROR", "CRITICAL"})
_TIMELINE_LEVELS = ("INFO", "WARNING", "ERROR", "CRITICAL")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# The usernames shorter than this are not scrubbed: replacing a one or two
# letter name would mangle every word that contains it.
_MIN_USERNAME_LENGTH = 3
MAX_LOG_LINES = 400
MAX_PROGRESS_LINES = 200
MAX_LINE_LENGTH = 2000
MAX_PROCESS_LINES = 100
TIMELINE_HOURS = 6
BUCKET_MINUTES = 10
MAX_PIDS = 10
_PROCESS_LOGS = ("restart-history.log", "supervisord.log", "faulthandler.log")


def _username_pattern():
    """Return a pattern matching every account name on the instance, or None."""
    names = {
        name
        for name in get_user_model().objects.values_list("username", flat=True)
        if len(name) >= _MIN_USERNAME_LENGTH
    }
    if not names:
        return None
    # Longest first so "alexandra" is not cut short by an account named "alex".
    alternatives = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


def _scrub(line: str, usernames) -> str:
    """Remove secrets, email addresses, and account names from one log line."""
    line = redact_secrets(line[:MAX_LINE_LENGTH])
    line = _EMAIL.sub("[EMAIL]", line)
    if usernames is not None:
        line = usernames.sub("[USER]", line)
    return line


def _log_files(name: str) -> list[Path]:
    """Return a log file and its rotated backups, oldest first."""
    log_path = Path(settings.LOG_FILE).parent / name
    backups = sorted(
        (p for p in log_path.parent.glob(f"{name}.*") if p.suffix[1:].isdigit()),
        key=lambda p: int(p.suffix[1:]),
        reverse=True,
    )
    return [p for p in [*backups, log_path] if p.exists()]


def _parse_time(text: str) -> datetime | None:
    """Return the aware time in a log line's stamp, or None if it is not one."""
    try:
        return datetime.strptime(text, _TIME_FORMAT)  # noqa: DTZ007 - has %z
    except ValueError:
        return None


class _Scan:
    """What one pass over the application log collects."""

    def __init__(self, usernames, now):
        self.usernames = usernames
        self.since = now - timedelta(hours=TIMELINE_HOURS)
        self.problems: deque[str] = deque(maxlen=MAX_LOG_LINES)
        self.progress: deque[str] = deque(maxlen=MAX_PROGRESS_LINES)
        self.buckets: dict[datetime, Counter] = {}
        self.last_by_level: dict[str, datetime] = {}
        self.last_by_pid: dict[str, datetime] = {}

    def read(self):
        """Read floppy.log and its backups, oldest first."""
        for path in _log_files(Path(settings.LOG_FILE).name):
            try:
                with path.open(encoding="utf-8", errors="replace") as log:
                    self._read_file(log)
            except OSError:
                continue

    def _read_file(self, log):
        keeping = False
        for line in log:
            match = _RECORD_START.match(line)
            if match:
                keeping = match.group("level") in _KEPT_LEVELS
                self._count(match)
                if match.group("level") == "INFO" and match.group("msg").startswith(
                    PROGRESS_TAG,
                ):
                    self.progress.append(_scrub(line.rstrip("\n"), self.usernames))
            if keeping:
                self.problems.append(_scrub(line.rstrip("\n"), self.usernames))

    def _count(self, match):
        """Add one record to the timeline; the message is never read here."""
        when = _parse_time(match.group("ts"))
        if when is None:
            return
        level, pid = match.group("level"), match.group("pid")
        self.last_by_level[level] = when
        self.last_by_pid[pid] = when
        if when >= self.since:
            block = when.replace(
                minute=when.minute - when.minute % BUCKET_MINUTES,
                second=0,
                microsecond=0,
            )
            self.buckets.setdefault(block, Counter())[level] += 1

    def timeline(self, now) -> list[str]:
        """Return the activity section: last lines, then counts per block."""
        out = []
        newest = max(self.last_by_level.values(), default=None)
        if newest is None:
            return ["(no timestamped log lines found)"]
        ago = int((now - newest).total_seconds() // 60)
        out.append(f"Newest log line: {newest:%Y-%m-%d %H:%M:%S %z} ({ago} min ago)")
        out.extend(
            f"Last {level}: {self.last_by_level[level]:%H:%M:%S}"
            for level in _TIMELINE_LEVELS
            if level in self.last_by_level
        )
        recent = sorted(self.last_by_pid.items(), key=lambda kv: kv[1])[-MAX_PIDS:]
        out.append(
            "Last line per process: "
            + ", ".join(f"pid {pid} at {when:%H:%M:%S}" for pid, when in recent),
        )
        out.append("")
        out.append(f"Lines per {BUCKET_MINUTES} minutes, last {TIMELINE_HOURS} hours:")
        for block in sorted(self.buckets):
            counts = self.buckets[block]
            cells = "  ".join(f"{lv[:4]} {counts[lv]}" for lv in _TIMELINE_LEVELS)
            out.append(f"  {block:%H:%M}  {cells}")
        if not self.buckets:
            out.append("  (no lines in this window: nothing was logged)")
        return out


def _process_log_tail(name: str, usernames) -> list[str]:
    """Return the end of a process-level log (restarts, exits, crash traces)."""
    tail: deque[str] = deque(maxlen=MAX_PROCESS_LINES)
    for path in _log_files(name):
        try:
            with path.open(encoding="utf-8", errors="replace") as log:
                tail.extend(_scrub(line.rstrip("\n"), usernames) for line in log)
        except OSError:
            continue
    return list(tail)


def build_report(*, logs_since: str = "", last_unclean_exit=None) -> str:
    """Return the diagnostic report as plain text."""
    usernames = _username_pattern()
    now = timezone.now()
    scan = _Scan(usernames, now)
    scan.read()
    engine = settings.DATABASES["default"]["ENGINE"].rsplit(".", 1)[-1]
    out = [
        "Floppy diagnostic report",
        f"Generated: {timezone.localtime():%Y-%m-%d %H:%M:%S %Z}",
        "",
        "This report holds server details, activity counts, recent warnings and",
        "errors, and progress lines only. Account names, email addresses, and",
        "secrets are removed. Look it over before you share it.",
        "",
        "== Server ==",
        f"Floppy version: {settings.VERSION}",
        f"Commit: {settings.COMMIT_SHA_SHORT}",
        f"Python: {sys.version.split()[0]} on {platform.system()} {platform.machine()}",
        f"Database: {engine}",
        f"Debug mode: {settings.DEBUG}",
        f"Log covers: {logs_since or 'unknown'} onward",
        f"Last unclean shutdown: {last_unclean_exit or 'none recorded'}",
        "",
        "== Activity ==",
        *scan.timeline(now),
        "",
        f"== Progress lines (newest {MAX_PROGRESS_LINES}) ==",
        *(scan.progress or ["(none logged)"]),
        "",
        f"== Recent warnings and errors (newest {MAX_LOG_LINES} lines) ==",
        *(scan.problems or ["(none in the retained logs)"]),
    ]
    for name in _PROCESS_LOGS:
        tail = _process_log_tail(name, usernames)
        if tail:
            out += ["", f"== {name} (last {MAX_PROCESS_LINES} lines) =="]
            out += tail
    return "\n".join(out) + "\n"
