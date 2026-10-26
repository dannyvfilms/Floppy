"""Show the SQLite recovery page while startup is paused.

Django cannot serve this page. The database is the thing that is paused, and
migrations have not run, so this uses only the standard library.

The same page is written to disk beside the database. If the port is in use, or
the container is stopped, the person who runs Floppy can still open the file and
read what happened.
"""

from __future__ import annotations

import base64
import html
import json
import os
import secrets
import shutil
import socket
import sqlite3
import sys
import threading
from contextlib import suppress
from datetime import UTC, datetime
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from config.server_port import DEFAULT_SERVER_PORT, resolve_server_port, validate_port
from config.sqlite_integrity import (
    _RECOVERY_PAGE_NAME,
    _decision_path,
    _incident_report_path,
    _log,
    _publish_report,
    _read_incident_report,
    read_startup_status,
    startup_progress_diagnostics,
)

_DEFAULT_BACKUP_DIR = "/floppy/backups"
_DAMAGED_FOLDER = "sqlite-recovery"
_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
_COPY_CHUNK_BYTES = 8 * 1024 * 1024
_HEALTH_PATHS = frozenset({"/health", "/health/"})
_MAX_BODY_BYTES = 4096
_SOCKET_TIMEOUT_SECONDS = 15
_DOWNLOAD_CHUNK_BYTES = 1024 * 1024
_DB_PATH_ARG_INDEX = 1
_PORT_ARG_INDEX = 2
# This page has no sign-in. It runs before Django, on the port the app is
# published on, so every request it answers is anonymous. A report with the
# names redacted is safe to answer that way; the database file is not, because
# it carries every account, session and integration secret. The download is
# therefore off unless the operator turns it on for the length of the incident.
_DOWNLOAD_ENV = "FLOPPY_SQLITE_ALLOW_BACKUP_DOWNLOAD"
_DOWNLOAD_TOKEN_ENV = "FLOPPY_SQLITE_BACKUP_TOKEN"  # noqa: S105 - environment name
_MIN_DOWNLOAD_TOKEN_LENGTH = 32
# The approval code proves that the person has read the report file. The page
# must never show it, or the code proves only that they opened the page.
_SECRET_REPORT_KEYS = frozenset({"actions", "incident_token"})
# "the container log" alone is ambiguous: Floppy also writes its own app log
# files (LOG_DIR), and users have reported checking those instead (#960). Name
# the actual command and disclaim the app logs explicitly wherever this comes up.
_CONTAINER_LOG_HINT = (
    "the container's own log output, not Floppy's log files. Run "
    "<code>docker compose logs floppy</code> (or <code>docker logs "
    "&lt;container&gt;</code>) and search for &quot;approval code&quot;"
)

_HELP_LINKS = (
    ("Report a problem", "https://github.com/dannyvfilms/Floppy/issues"),
    ("Read the wiki", "https://github.com/dannyvfilms/Floppy/wiki"),
    ("Ask on Discord", "https://discord.gg/uFgha7Kb6n"),
)

# navigator.clipboard exists only in a secure context. Floppy is usually opened
# over plain HTTP on a local address, where it is undefined. The button falls
# back to the older command, and the text stays on the page to select by hand.
_COPY_SCRIPT = """
document.addEventListener('click',function(e){
 var b=e.target.closest('[data-copy]');if(!b)return;
 var t=document.getElementById(b.getAttribute('data-copy'));if(!t)return;
 var s=t.innerText,done=function(){b.textContent='Copied';
  setTimeout(function(){b.textContent='Copy details'},2000)};
 if(navigator.clipboard&&window.isSecureContext){
  navigator.clipboard.writeText(s).then(done,function(){b.textContent='Press Ctrl+C'})}
 else{var r=document.createRange();r.selectNodeContents(t);
  var sel=window.getSelection();sel.removeAllRanges();sel.addRange(r);
  try{document.execCommand('copy');done()}catch(err){b.textContent='Press Ctrl+C'}}
});
"""

# The recovery server stops as soon as a choice is made, so every request here
# fails until Floppy itself answers on this port. That is the signal to reload.
_POLL_SCRIPT = """
setInterval(function(){
 fetch('/',{method:'HEAD',cache:'no-store'}).then(function(r){
  if(r.ok){location.reload()}}).catch(function(){})
},5000);
"""

# Copied from src/static/css/input.css. The page must not request an external
# stylesheet, because it also opens as a file from the database folder.
_STYLE = """
/* Values taken from the app's --color-* tokens, so the page reads as the same
   product. The app picks its theme from the signed-in user; nobody is signed
   in here, so this follows the operating system instead. */
:root{--page:#212529;--panel:#2a2f35;--text:#f3f4f6;--muted:#adb5bd;
--accent:#4a9eff;--accent-strong:#1c5fb0;--border:#2c3136}
@media (prefers-color-scheme: light){:root{--page:#f8f9fa;--panel:#fff;
--text:#1f2937;--muted:#4b5563;--accent:#2f80ed;--accent-strong:#1a5fbf;
--border:#dee2e6}}
*{box-sizing:border-box}
body{margin:0;padding:2.5rem 1.25rem;background:var(--page);color:var(--text);
font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:44rem;margin:0 auto}
.masthead{display:flex;align-items:center;gap:.6rem;margin:0 0 1.5rem;
font-size:1.15rem;font-weight:600;color:var(--text);letter-spacing:-.01em}
.masthead img{border-radius:8px;flex:none}
h1{font-size:1.5rem;margin:0 0 .5rem}
p{margin:0 0 1rem;color:var(--muted)}
.card{background:var(--panel);border:1px solid var(--border);border-radius:10px;
padding:1.25rem;margin:1rem 0}
.card h2{font-size:1.05rem;margin:0 0 .35rem;color:var(--text)}
ul{list-style:none;padding:0;margin:.5rem 0}
/* The two lists read differently: one is a table of counts, the other is an
   ordered set of steps. Scope the row rule, or the steps inherit it. */
ul li{display:flex;justify-content:space-between;gap:1rem;padding:.3rem 0;
border-bottom:1px solid var(--border);color:var(--text)}
ul li:last-child{border-bottom:0}
ul li span:last-child{color:var(--muted);white-space:nowrap}
ol{margin:.5rem 0;padding-left:1.3rem;color:var(--text)}
ol li{padding:.2rem 0}
/* #fff on --accent measures 2.75:1, below the 4.5:1 that body text needs.
   The darker accent below carries white text at 5.3:1 in both schemes. */
button,.button{background:var(--accent-strong);color:#fff;border:1px solid
var(--accent-strong);border-radius:7px;padding:.6rem 1.1rem;font-size:1rem;
cursor:pointer;display:inline-block;text-decoration:none;line-height:1.2}
.button.secondary{background:transparent;color:var(--text);
border-color:var(--muted)}
button:focus-visible,.button:focus-visible,a:focus-visible{outline:3px solid
var(--accent);outline-offset:2px}
input{background:var(--page);color:var(--text);border:1px solid var(--border);
border-radius:7px;padding:.55rem .7rem;font-size:1rem;margin-right:.5rem}
code{background:var(--page);padding:.1rem .35rem;border-radius:4px;
border:1px solid var(--border);font-size:.9em}
details{margin-top:1.5rem;color:var(--muted)}
pre{overflow-x:auto;background:var(--panel);border:1px solid var(--border);
border-radius:8px;padding:1rem;font-size:.85rem}
.note{font-size:.9rem}
a{color:var(--accent)}
"""


@lru_cache(maxsize=4)
def _asset_data_uri(name: str) -> str:
    """Inline an app icon so the page carries its own copy.

    Django is not running, so there is no static file server. The page is also
    written beside the database and opened from there, where no server exists
    at all. An inlined image is the only kind that survives both.
    """
    candidate = Path(__file__).resolve().parent.parent / "static" / "favicon" / name
    try:
        raw = candidate.read_bytes()
    except OSError:
        return ""
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def _masthead() -> str:
    """Show the Floppy mark, so the page reads as part of the app."""
    icon = _asset_data_uri("android-chrome-192x192.png")
    mark = f"<img src='{icon}' alt='' width='36' height='36'>" if icon else ""
    return f"<header class='masthead'>{mark}<span>Floppy</span></header>"


def _download_enabled() -> bool:
    """Report whether the operator opened the database download."""
    value = os.environ.get(_DOWNLOAD_ENV, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


class RestoreError(Exception):
    """A snapshot could not be restored; the damaged database was left in place.

    ``report`` is the technical text shown to the person if the restore fails,
    so a bug report can name the step, the error and the state of the files.
    """

    report = ""
    attempt: dict | None = None

    def __init__(self, message: str, step: str = "restore") -> None:
        """Keep the plain message and the name of the step that failed."""
        super().__init__(message)
        self.step = step


def _snapshot_dir() -> Path:
    """Return the folder the scheduled snapshot task writes to."""
    return Path(os.environ.get("BACKUP_DIR") or _DEFAULT_BACKUP_DIR) / "database"


def list_snapshots(snapshot_dir: Path | None = None) -> list[dict]:
    """List restorable snapshots, newest first.

    Dot-files are the writer's staging files and symlinks could point anywhere,
    so neither is offered.
    """
    directory = snapshot_dir or _snapshot_dir()
    found = []
    try:
        entries = list(directory.glob("*.sqlite3"))
    except OSError:
        return []
    for path in entries:
        try:
            if path.name.startswith(".") or path.is_symlink() or not path.is_file():
                continue
            info = path.stat()
        except OSError:
            continue
        found.append(
            {"name": path.name, "size": info.st_size, "mtime": info.st_mtime, "path": path}
        )
    return sorted(found, key=lambda item: (item["mtime"], item["name"]), reverse=True)


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":  # noqa: PLR2004
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"  # pragma: no cover


def _restore_card(snapshots: list[dict]) -> str:
    """Offer a one-click repair, and list the copies it will try."""
    if not snapshots:
        return ""

    def when(item: dict) -> str:
        return f"{datetime.fromtimestamp(item['mtime'], UTC):%B %d, %Y at %H:%M} UTC"

    rows = "".join(
        f"<li><span>{when(item)}</span>"
        f"<span>{_format_size(item['size'])}"
        f"{' &middot; newest' if index == 0 else ''}</span></li>"
        for index, item in enumerate(snapshots)
    )
    return (
        "<div class='card'><h2>Saved copies</h2>"
        "<p>Floppy keeps these checked copies of your database. Anything you "
        "added after the newest one is not in it.</p>"
        f"<ul>{rows}</ul></div>"
        "<div class='card'><h2>Repair it</h2>"
        "<p>Floppy starts with the newest copy. If a copy fails its check, it "
        "tries the next one. Your damaged file is moved to the "
        f"<code>{_DAMAGED_FOLDER}</code> folder next to your database, "
        "not deleted.</p>"
        "<form method='POST' action='/restore'>"
        "<button>Restore and start Floppy</button></form>"
        "<p class='note'>This can take a few minutes for a large library. "
        "Leave this page open.</p></div>"
    )


def _verify_snapshot_file(path: Path) -> None:
    """Refuse a snapshot that is not itself a healthy database."""
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    except sqlite3.Error as error:
        msg = "Floppy could not open the saved copy."
        raise RestoreError(msg, "open the saved copy") from error
    try:
        result = connection.execute("PRAGMA quick_check").fetchall()
    except sqlite3.Error as error:
        msg = "The saved copy failed its own check, so it was not used."
        raise RestoreError(msg, "check the saved copy") from error
    finally:
        connection.close()
    if result != [("ok",)]:
        msg = "The saved copy failed its own check, so it was not used."
        raise RestoreError(msg, "check the saved copy")


def _copy_durably(source: Path, destination: Path) -> None:
    with source.open("rb") as reader, destination.open("wb") as writer:
        shutil.copyfileobj(reader, writer, _COPY_CHUNK_BYTES)
        writer.flush()
        os.fsync(writer.fileno())


def _describe_files(folder: Path, *, limit: int = 60) -> list[str]:
    lines = []
    try:
        entries = sorted(folder.iterdir())
    except OSError as error:
        return [f"  (cannot list: {error})"]
    for entry in entries[:limit]:
        try:
            info = entry.lstat()
            modified = datetime.fromtimestamp(info.st_mtime, UTC).strftime("%Y-%m-%d %H:%M")
            lines.append(
                f"  {entry.name}  {info.st_size} bytes  {modified} UTC  "
                f"mode={info.st_mode & 0o7777:o} uid={info.st_uid} gid={info.st_gid}"
            )
        except OSError as error:
            lines.append(f"  {entry.name}  (cannot stat: {error})")
    if len(entries) > limit:
        lines.append(f"  ... {len(entries) - limit} more")
    return lines


def _filesystem_of(path: Path) -> str:
    """Name the filesystem under a path. Network shares are a prime suspect."""
    try:
        target = str(path.resolve())
        best = ("", "unknown")
        for line in Path("/proc/mounts").read_text().splitlines():
            fields = line.split()
            mount, kind = fields[1].replace("\\040", " "), fields[2]
            if (target == mount or target.startswith(mount.rstrip("/") + "/")) and len(
                mount
            ) >= len(best[0]):
                best = (mount, f"{kind} mounted at {mount} ({fields[3].split(',')[0]})")
        return best[1]
    except (OSError, IndexError):
        return "unknown (no /proc/mounts)"


def _damaged_file_lines(database: Path) -> list[str]:
    """Describe the damaged file itself, without ever writing to it."""
    lines = []
    try:
        with database.open("rb") as handle:
            header = handle.read(100)
        lines.append(f"damaged file header (first 16 bytes): {header[:16]!r}")
        if len(header) >= 100:  # noqa: PLR2004
            page_size = int.from_bytes(header[16:18], "big")
            lines.append(
                f"damaged file page_size={page_size} "
                f"journal_version(w/r)={header[18]}/{header[19]} "
                f"file_change_counter={int.from_bytes(header[24:28], 'big')}"
            )
    except OSError as error:
        lines.append(f"damaged file cannot be read: {error}")
    try:
        connection = sqlite3.connect(f"{database.as_uri()}?mode=ro&immutable=1", uri=True, timeout=1)
        try:
            lines.append(
                f"damaged file quick_check(10): "
                f"{connection.execute('PRAGMA quick_check(10)').fetchall()}"
            )
        finally:
            connection.close()
    except sqlite3.Error as error:
        lines.append(f"damaged file quick_check failed: {error}")
    return lines


_REPORT_ENV = (
    "VERSION", "COMMIT_SHA", "TZ", "BACKUP_DIR", "FLOPPY_DB_PATH", "DB_SNAPSHOT_ENABLED",
    "DB_SNAPSHOT_HOUR", "DB_SNAPSHOT_MINUTE", "DB_SNAPSHOT_RETENTION_COUNT",
    "SQLITE_JOURNAL_MODE", "SQLITE_SYNCHRONOUS", "FLOPPY_SQLITE_AUTO_SNAPSHOT",
    "FLOPPY_SQLITE_AUTO_REPAIR", "LOG_DIR",
)  # fmt: skip


def _failure_report(attempts: list[dict], db_path: str, folder: Path) -> str:
    """Collect everything needed to trace a failed restore from one pasted block."""
    database = Path(db_path).resolve()
    try:
        free = shutil.disk_usage(database.parent).free
    except OSError:
        free = "unknown"
    incident = _read_incident_report(db_path) or {}
    lines = [
        "Floppy restore failure report",
        f"time: {datetime.now(UTC).isoformat()}",
        f"floppy: {os.environ.get('VERSION', 'unknown')} "
        f"({os.environ.get('COMMIT_SHA', 'unknown')})",
        f"sqlite: {sqlite3.sqlite_version}  python: {sys.version.split()[0]}  "
        f"platform: {sys.platform}",
        f"process: uid={os.getuid()} gid={os.getgid()}" if hasattr(os, "getuid") else "",
        "",
        f"restore attempts ({len(attempts)}), newest first:",
    ]
    for number, attempt in enumerate(attempts, start=1):
        lines.append(f"  {number}. {attempt['snapshot']}")
        lines.append(f"     failed step: {attempt['step']}")
        lines.append(f"     error: {attempt['error']}")
        if attempt.get("errno") is not None:
            lines.append(f"     errno: {attempt['errno']} ({os.strerror(attempt['errno'])})")
        lines.append(f"     message shown: {attempt['message']}")
    lines += [
        "",
        f"incident reasons: {incident.get('unsafe_reasons', 'none recorded')}",
        f"startup status: {read_startup_status(db_path)}",
        "",
        f"database: {database}",
        f"database filesystem: {_filesystem_of(database.parent)}",
        f"backup filesystem: {_filesystem_of(folder)}",
        f"free space beside database: {free} bytes",
        *_damaged_file_lines(database),
        "",
        "settings:",
        *(f"  {key}={os.environ[key]}" for key in _REPORT_ENV if key in os.environ),
        "",
        f"database folder ({database.parent}):",
        *_describe_files(database.parent),
        f"{_DAMAGED_FOLDER} folder:",
        *_describe_files(database.parent / _DAMAGED_FOLDER),
        f"snapshot folder ({folder}):",
        *_describe_files(folder),
        "",
        "Also attach the container log (docker logs) and <data>/logs/floppy.log.",
    ]
    return "\n".join(line for line in lines if line is not None)


def _find_snapshot(directory: Path, name: str) -> Path:
    chosen = next((i for i in list_snapshots(directory) if i["name"] == name), None)
    if chosen is None:
        msg = "That saved copy is not available."
        raise RestoreError(msg, "choose saved copy")
    return chosen["path"]


def restore_snapshot(db_path: str, name: str, snapshot_dir: Path | None = None) -> Path:
    """Replace the damaged database with one verified snapshot.

    The snapshot is verified and copied beside the database first, so a failure
    at any step leaves the damaged file exactly where it was. Only then is the
    damaged file moved aside together with its -wal/-shm/-journal companions: a
    stale WAL left next to a restored file would be replayed into it and damage
    it again. Returns the folder the damaged files were moved to. Any failure
    raises RestoreError carrying an ``attempt`` record and a technical report.
    """
    directory = snapshot_dir or _snapshot_dir()
    step = "choose snapshot"
    try:
        # The path comes from the folder listing, never from the submitted
        # name, so a name that is not in the listing cannot reach the filesystem.
        source = _find_snapshot(directory, name)
        step = "check the saved copy"
        return _restore_verified(db_path, source)
    except RestoreError as error:
        cause = error.__cause__ or error
        error.attempt = {
            "snapshot": name,
            "step": error.step,
            "error": f"{type(cause).__name__}: {cause}",
            "errno": getattr(cause, "errno", None),
            "message": str(error),
        }
        error.report = _failure_report([error.attempt], db_path, directory)
        raise
    except (OSError, sqlite3.Error) as error:
        msg = "Floppy could not restore the saved copy."
        failure = RestoreError(msg, step)
        failure.attempt = {
            "snapshot": name,
            "step": step,
            "error": f"{type(error).__name__}: {error}",
            "errno": getattr(error, "errno", None),
            "message": msg,
        }
        failure.report = _failure_report([failure.attempt], db_path, directory)
        raise failure from error


def restore_latest(db_path: str, snapshot_dir: Path | None = None) -> tuple[str, Path]:
    """Restore the newest saved copy that works, trying each one in turn.

    Returns the name of the copy that was restored and the folder the damaged
    files were moved to. If every copy fails, raises RestoreError whose report
    lists every attempt.
    """
    directory = snapshot_dir or _snapshot_dir()
    attempts: list[dict] = []
    for item in list_snapshots(directory):
        try:
            return item["name"], restore_snapshot(db_path, item["name"], directory)
        except RestoreError as error:
            attempts.append(error.attempt)
            _log(
                f"[entrypoint] Saved copy {item['name']} could not be restored "
                f"({error.step}): {error.attempt['error']}"
            )
    if attempts:
        msg = (
            f"None of the {len(attempts)} saved copies could be restored. "
            "Floppy changed nothing."
        )
    else:
        msg = "Floppy found no saved copies to restore."
    failure = RestoreError(msg, "restore latest")
    failure.report = _failure_report(attempts, db_path, directory)
    raise failure


def _restore_verified(db_path: str, source: Path) -> Path:
    database = Path(db_path).resolve()
    _verify_snapshot_file(source)
    try:
        free = shutil.disk_usage(database.parent).free
    except OSError:
        free = None
    if free is not None and free < source.stat().st_size:
        msg = "There is not enough free disk space beside the database."
        raise RestoreError(msg, "check disk space")

    staged = database.with_name(f".{database.name}.restore-{secrets.token_hex(4)}")
    aside = (
        database.parent
        / _DAMAGED_FOLDER
        / f"damaged-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(2)}"
    )
    moved: list[tuple[Path, Path]] = []
    try:
        _copy_durably(source, staged)
        aside.mkdir(parents=True, exist_ok=True)
        for original in [database, *(Path(f"{database}{s}") for s in _SIDECAR_SUFFIXES)]:
            if original.exists():
                target = aside / original.name
                original.replace(target)
                moved.append((original, target))
        staged.replace(database)
    except OSError as error:
        for original, target in reversed(moved):
            with suppress(OSError):
                target.replace(original)
        with suppress(OSError):
            staged.unlink()
        msg = "Floppy could not swap in the saved copy. Nothing was changed."
        raise RestoreError(msg, "swap in the saved copy") from error
    # The incident belongs to the file that was moved. Clearing it lets the
    # normal startup check judge the restored file from scratch.
    with suppress(OSError):
        _incident_report_path(db_path).unlink()
    with suppress(OSError):
        database.with_name(_RECOVERY_PAGE_NAME).unlink()
    return aside


def _backup_card(*, for_corruption: bool = False) -> str:
    """Offer the copy Floppy already made, or the download if it is open."""
    if _download_enabled():
        action = (
            "<form method='post' action='/backup'>"
            "<label>Database download token "
            "<input type='password' name='token' required autocomplete='off'></label>"
            "<button class='button secondary'>Download database copy</button>"
            f"<p class='note'>Set {_DOWNLOAD_TOKEN_ENV} to a random token of at least "
            "32 characters in the server environment. Enter it here; use HTTPS "
            "or a trusted local connection.</p></form>"
        )
    elif for_corruption:
        action = (
            "<div class='card'><h2>Keep the damaged file</h2>"
            "<p class='note'>Repairing moves the damaged file to the "
            "<code>sqlite-recovery</code> folder beside <code>db.sqlite3</code>. "
            "A repair tool can still read data from it. Floppy keeps nightly "
            "database snapshots in the <code>database</code> folder of "
            "<code>BACKUP_DIR</code>; a CSV export is not a database snapshot "
            "and cannot replace this file.</p>"
            f"<p class='note'>To download the damaged file from this page, set "
            f"<code>{_DOWNLOAD_ENV}=true</code> and start Floppy again. Keep it "
            "off at other times, because this page has no sign-in.</p></div>"
        )
    else:
        action = (
            "<p class='note'>Floppy writes a verified copy of the database to the "
            "<code>sqlite-recovery</code> folder beside <code>db.sqlite3</code> "
            "before it changes a broken relationship or removes a row. Copy the "
            "file from there.</p>"
            f"<p class='note'>To download the file from this page instead, set "
            f"<code>{_DOWNLOAD_ENV}=true</code> and start Floppy again. Keep it "
            "off at other times, because this page has no sign-in.</p>"
        )
    return action


def _count(value: object) -> int:
    """Read a number from a damaged database without failing.

    The page exists because the database is damaged, so a value in it can be
    the wrong type. A wrong number must never stop the page from opening.
    """
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _affected_list(report: dict) -> str:
    rows = []
    for entry in report.get("affected", []):
        title = html.escape(str(entry.get("title") or "Unknown"))
        season = entry.get("season")
        label = title
        if season is not None:
            label = f"{title}, Season {html.escape(str(season))}"
        rows.append(
            f"<li><span>{label}</span>"
            f"<span>{_count(entry.get('count'))} entries</span></li>",
        )
    other = _count(report.get("affected_other_titles"))
    if other:
        count = _count(report.get("affected_other_titles_count"))
        rows.append(
            f"<li><span>and {other} other titles</span>"
            f"<span>{count} entries</span></li>",
        )
    unknown = _count(report.get("affected_unidentified"))
    if unknown:
        rows.append(
            f"<li><span>Entries we cannot identify</span>"
            f"<span>{unknown} entries</span></li>",
        )
    if not rows:
        return ""
    return (
        "<div class='card'><h2>What is affected</h2><ul>"
        + "".join(rows)
        + "</ul></div>"
    )


def _repair_plan_card(report: dict) -> str:
    """Explain safe work already done and any destructive work still required."""
    plan = report.get("repair_plan") or {}
    safe_repair = report.get("safe_repair") or {}
    parts = []
    cleared = _count(safe_repair.get("references_cleared"))
    derived = _count(safe_repair.get("relationship_rows_removed"))
    if cleared or derived:
        parts.append(
            "<p>Floppy already preserved the affected tracking rows where it could: "
            f"it cleared {cleared} broken optional reference(s) and removed "
            f"{derived} derived relationship row(s). A verified backup was created "
            "before those changes.</p>"
        )

    required = _count(plan.get("required_relationships"))
    if required:
        parts.append(
            f"<p>{required} broken required relationship(s) remain. Those child "
            "rows cannot exist validly without their missing parent. Repairing the "
            "database removes only those remaining rows from the live database; "
            "the verified backup keeps their original data.</p>"
        )

    safe_pending = _count(plan.get("safe_relationships"))
    if safe_pending:
        parts.append(
            f"<p>{safe_pending} relationship(s) can be repaired without deleting "
            "their user-owned child rows.</p>"
        )

    if not parts:
        return ""
    return "<div class='card'><h2>Repair plan</h2>" + "".join(parts) + "</div>"


def _timeout_body() -> str:
    return (
        "<h1>The SQLite startup check stopped making progress.</h1>"
        "<p>Floppy paused before migrations and services. The check read "
        "nothing and used no CPU for several minutes, so it was stopped; a "
        "check that is merely slow is left to finish. This usually means the "
        "storage under the database stopped responding (a network share or "
        "disk that went away), not that the database is damaged. No migration "
        "or recovery action completed; the database result is unknown until "
        "preflight or an offline check finishes.</p>"
    )


def _timeout_details(status: dict) -> str:
    phase = html.escape(str(status.get("phase", "unknown")))
    elapsed = status.get("elapsed_seconds")
    elapsed_text = f"{elapsed:.0f}s" if isinstance(elapsed, int | float) else "unknown"
    diagnostics = startup_progress_diagnostics(status)
    phase_elapsed = diagnostics["phase_elapsed_seconds"]
    phase_elapsed_text = (
        f"{phase_elapsed:.0f}s" if isinstance(phase_elapsed, int | float) else "unknown"
    )
    read_bytes = status.get("read_bytes")
    items = [
        f"<li>Phase when stopped: <code>{phase}</code></li>",
        "<li>Why it was stopped: "
        f"{html.escape(str(status.get('error_message') or 'unknown'))}</li>",
        f"<li>Elapsed: {elapsed_text}</li>",
        f"<li>Phase elapsed: {phase_elapsed_text}</li>",
    ]
    if isinstance(read_bytes, int | float) and read_bytes:
        items.append(f"<li>Read so far: ~{read_bytes / 1_048_576:.0f}MB</li>")
    progress_callbacks = status.get("progress_callbacks")
    if isinstance(progress_callbacks, int | float):
        items.append(
            f"<li>SQLite progress callbacks in phase: {progress_callbacks:.0f}</li>"
        )
    progress_rate = diagnostics["progress_rate_per_minute"]
    if isinstance(progress_rate, int | float):
        items.append(f"<li>Progress rate: {progress_rate:.1f} callbacks/min</li>")
    progress_age = diagnostics["last_progress_age_seconds"]
    if isinstance(progress_age, int | float):
        items.append(f"<li>Last progress observed: {progress_age:.0f}s ago</li>")
    else:
        items.append("<li>Last progress observed: unknown</li>")
    progress_state = diagnostics["progress_state"]
    if progress_state == "quiet":
        items.append(
            "<li><strong>No recent SQLite progress observed.</strong> "
            "This can indicate slow storage or a blocked operation; it does not "
            "by itself prove corruption.</li>"
        )
    else:
        items.append(f"<li>Progress state: <code>{progress_state}</code></li>")
    items.append(f"<li>Database: <code>{html.escape(str(status.get('database', 'unknown')))}</code></li>")
    version = html.escape(str(status.get("version") or "unknown"))
    commit_sha = html.escape(str(status.get("commit_sha") or "unknown"))
    items.append(f"<li>Build: version={version} commit={commit_sha}</li>")
    return f"<div class='card'><h2>What was happening</h2><ul>{''.join(items)}</ul></div>"


def _timeout_diagnosis_card() -> str:
    container_name = html.escape(os.environ.get("HOST_CONTAINERNAME", "floppy"))
    return (
        "<div class='card'><h2>Run a full diagnosis</h2>"
        f"<p><code>docker exec {container_name} python manage.py floppy_preflight"
        "</code></p>"
        "<p>If the container is restarting instead of running, use "
        "<code>docker compose run --rm floppy python manage.py "
        "floppy_preflight</code> instead.</p></div>"
    )


def _timeout_retry_card(*, interactive: bool) -> str:
    if interactive:
        return (
            "<div class='card'><h2>Retry the startup check</h2>"
            "<p>After checking the database, retry the startup integrity gate. "
            "Floppy will not bypass the gate; if it finds relationship damage, "
            "the normal recovery policy still applies.</p>"
            "<form method='POST' action='/retry'>"
            "<button>Retry startup check</button></form></div>"
        )
    return (
        "<div class='card'><h2>Retry the startup check</h2>"
        "<p>Open the recovery page on the published port to retry the scan after "
        "checking the database.</p></div>"
    )


def render_page(
    report: dict | None,
    *,
    interactive: bool,
    port: int = DEFAULT_SERVER_PORT,
    status: dict | None = None,
) -> str:
    """Build the page. The written file is the same page without the buttons."""
    port = validate_port(port, source="recovery page port")
    if status and status.get("error_class") == "startup_admission" and (
        not report or report.get("status") == "resolved"
    ):
        return _document(
            "<h1>SQLite startup needs maintenance</h1>"
            f"<p>{html.escape(str(status.get('error_message', 'Inspect the container logs.')))}</p>"
            "<p>Stop all application containers and database writers before preparing "
            "migrations or recovery. Run maintenance with the same image and database "
            "mounts, then restart Floppy. No database rows were changed by admission.</p>"
            + _help_card()
        )
    if status and status.get("status") == "timeout":
        body = (
            _timeout_body()
            + _timeout_details(status)
            + _timeout_retry_card(interactive=interactive)
            + _timeout_diagnosis_card()
            + _help_card()
        )
        return _document(body)
    if not report:
        body = (
            "<h1>Your data is safe. Nothing was deleted.</h1>"
            "<p>Floppy paused before it started. It cannot read the report that "
            f"explains why. Look at {_CONTAINER_LOG_HINT}.</p>"
            + _help_card()
        )
        return _document(body)

    if report.get("status") == "corrupt":
        corruption_reasons = "".join(
            f"<li><span>{html.escape(r)}</span></li>"
            for r in report.get("unsafe_reasons", [])
        )
        snapshots = list_snapshots()
        parts = [
            "<h1>Floppy's database file is damaged.</h1>",
            "<p>Your data is probably fine. Floppy stopped on purpose, because "
            "writing to a damaged file can make it worse. Nothing was changed.</p>",
            "<p>Floppy saves a checked copy of your database every night, so "
            "it can usually put things back.</p>",
        ]
        if snapshots:
            parts.append(_restore_card(snapshots))
        else:
            parts.append(
                "<div class='card'><h2>No saved copies were found</h2>"
                "<p>Floppy looks for nightly copies in the <code>database</code> "
                "folder inside your backups folder (<code>BACKUP_DIR</code>) and "
                "found none. If you have your own copy of <code>db.sqlite3</code>, "
                "stop Floppy, replace the file with it, and start Floppy again.</p>"
                "<p class='note'>A CSV export cannot replace this file. It only "
                "recreates media, ratings and lists, not accounts or "
                "integration settings.</p></div>"
            )
        parts.append(
            "<details><summary>Technical details and more options</summary>"
            "<div class='card'><h2>What Floppy found</h2>"
            f"<ul>{corruption_reasons}</ul></div>"
            + _backup_card(for_corruption=True)
            + "</details>"
        )
        return _document("".join(parts))

    total = _count(report.get("total_conflicts"))
    actions = report.get("actions") or {}
    can_accept = "accept" in actions
    can_repair = bool("quarantine" in actions and report.get("can_quarantine"))
    parts = [
        "<h1>Your data is safe. Floppy paused before migrations.</h1>",
        f"<p>Floppy found {total} broken relationship(s). One row can have more "
        "than one broken relationship, so this number is not a count of rows to "
        "remove. Floppy paused before migrations so recovery cannot silently "
        "discard user data.</p>",
        _repair_plan_card(report),
        _affected_list(report),
    ]

    if interactive:
        if can_accept:
            parts.append(
                "<div class='card'><h2>Keep the entries, then start</h2>"
                "<p>This legacy choice keeps every invalid relationship. Use it "
                "only when the current recovery policy explicitly allows it.</p>"
                "<form method='POST' action='/accept'>"
                "<button>Keep everything and start Floppy</button></form></div>",
            )
        if can_repair:
            required = _count((report.get("repair_plan") or {}).get("required_relationships"))
            if required:
                explanation = (
                    "Floppy creates and verifies a backup first. It preserves "
                    "nullable tracking rows by clearing only their broken references. "
                    "Rows whose required parent is still missing must be removed from "
                    "the live database so SQLite can validate migrations; their original "
                    "data remains in the backup."
                )
            else:
                explanation = (
                    "Floppy creates and verifies a backup first, then repairs the "
                    "broken relationships without removing user-owned rows when the "
                    "schema permits that."
                )
            parts.append(
                "<div class='card'><h2>Repair the relationships, then start</h2>"
                f"<p>{explanation}</p>"
                f"<p class='note'>Enter the current approval code, found in "
                f"{_CONTAINER_LOG_HINT}. The code is tied to this exact database "
                "state and changes if Floppy safely repairs part of the incident "
                "first.</p>"
                "<form method='POST' action='/quarantine'>"
                "<p><label for='recovery-token'>Approval code</label><br>"
                "<input id='recovery-token' name='token' required autocomplete='off' "
                "spellcheck='false' inputmode='text'></p>"
                "<button>Repair relationships and start Floppy</button>"
                "</form></div>",
            )
        elif not can_accept:
            parts.append(
                "<div class='card'><h2>Repair these entries yourself</h2>"
                "<p>Floppy cannot prove that an automatic write is safe for this "
                "schema. Restore a backup or inspect the technical details before "
                "you change the database.</p></div>",
            )
    else:
        parts.append(
            "<div class='card'><h2>How to choose</h2>"
            "<p>This is a copy on disk. To choose an available action, open Floppy "
            f"at port {port} while the container runs.</p></div>",
        )

    parts.append(
        "<div class='card'><h2>Use a backup instead</h2><ol>"
        "<li>Stop Floppy.</li>"
        "<li>Replace <code>db.sqlite3</code> with your backup.</li>"
        "<li>Start Floppy.</li></ol>"
        + _backup_card()
        + "</div>",
    )
    parts.append(_help_card())
    public = {
        key: value for key, value in report.items() if key not in _SECRET_REPORT_KEYS
    }
    parts.append(
        "<details><summary>Technical details for a bug report</summary>"
        "<p><button data-copy='details'>Copy details</button></p>"
        "<pre id='details'>"
        + html.escape(json.dumps(public, indent=2, sort_keys=True))
        + "</pre></details>",
    )
    return _document("".join(parts))


def _restore_failure_page(error: RestoreError) -> str:
    """Say what failed in plain words, then give a report that can be traced."""
    return _document(
        "<h1>The repair did not work.</h1>"
        f"<p>{html.escape(str(error))} Your damaged database is exactly where it "
        "was, so nothing is lost.</p>"
        "<p>Copy the report below into a new issue so it can be traced. It "
        "lists every saved copy Floppy tried and why each one failed.</p>"
        "<div class='card'><h2>Report</h2>"
        "<p><button data-copy='details'>Copy details</button></p>"
        f"<pre id='details'>{html.escape(error.report)}</pre></div>"
        + _help_card()
    )


def _waiting_page() -> str:
    """Confirm the choice and wait for Floppy, without promising a time.

    Floppy applies the choice, then runs migrations. On a large database that
    takes minutes, so this page must not reload on a timer: it would land on a
    connection error and read as a failed repair. It asks the server instead,
    and reloads only once the server answers.
    """
    body = (
        "<div class='card'>"
        "<h1>Floppy has your choice.</h1>"
        "<p role='status'>Floppy is applying it, then starting. This can take "
        "several minutes on a large database. You can leave this page open.</p>"
        "<p class='note'>This page opens Floppy when Floppy is ready. If it "
        f"stays on this message, look at {_CONTAINER_LOG_HINT}.</p>"
        "<p><a class='button' href='/'>Open Floppy</a></p>"
        "</div>"
    )
    return _document(body, script=_POLL_SCRIPT)


def _retry_waiting_page() -> str:
    body = (
        "<div class='card'>"
        "<h1>Floppy is retrying the startup check.</h1>"
        "<p role='status'>The database was not changed. Floppy will start the "
        "application if the check completes successfully.</p>"
        "<p class='note'>If the check times out again, this page will be available "
        "after the recovery server starts again.</p>"
        "</div>"
    )
    return _document(body)


def _help_card() -> str:
    """Offer the places where a person can get help."""
    links = " · ".join(
        f"<a href='{url}' target='_blank' rel='noopener noreferrer'>"
        f"{html.escape(label)}</a>"
        for label, url in _HELP_LINKS
    )
    return (
        "<div class='card'><h2>Get help</h2>"
        "<p>Include the technical details or report with your question.</p>"
        f"<p>{links}</p></div>"
    )


def _document(body: str, script: str = _COPY_SCRIPT) -> str:
    icon = _asset_data_uri("favicon-32x32.png")
    link = f"<link rel='icon' type='image/png' href='{icon}'>" if icon else ""
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Floppy needs a decision</title>"
        f"{link}<style>{_STYLE}</style></head><body>"
        f"<main>{_masthead()}{body}</main>"
        f"<script>{script}</script></body></html>"
    )


def write_page(
    db_path: str,
    report: dict | None,
    *,
    port: int = DEFAULT_SERVER_PORT,
    status: dict | None = None,
) -> Path:
    """Write the page beside the database so it is always available."""
    page_path = Path(db_path).resolve().with_name(_RECOVERY_PAGE_NAME)
    _publish_report(
        page_path,
        render_page(report, interactive=False, port=port, status=status),
        mode=0o644,
    )
    return page_path


def _write_decision(db_path: str, report: dict, action: str) -> None:
    _publish_report(
        _decision_path(db_path),
        json.dumps(
            {
                "action": action,
                "fingerprint": report.get("fingerprint"),
                "token": report.get("incident_token"),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


def _write_retry_decision(db_path: str) -> None:
    _publish_report(
        _decision_path(db_path),
        json.dumps({"action": "retry"}, sort_keys=True) + "\n",
    )


class _Handler(BaseHTTPRequestHandler):
    db_path = ""
    server_port = DEFAULT_SERVER_PORT
    timeout = _SOCKET_TIMEOUT_SECONDS

    def log_message(self, *_args) -> None:
        """Keep the container log free of one line per request."""

    def _send(self, status: int, body: str, content_type: str) -> None:
        payload = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        # Floppy is not able to serve requests, so the health check must fail.
        # A success here would report the container as healthy while it is not.
        path = self.path.split("?")[0]
        if path in _HEALTH_PATHS:
            self._send(503, "paused", "text/plain; charset=utf-8")
            return
        if path == "/backup":
            self._send(404, "not found", "text/plain; charset=utf-8")
            return
        report = _read_incident_report(self.db_path)
        status = read_startup_status(self.db_path)
        self._send(
            200,
            render_page(report, interactive=True, port=self.server_port, status=status),
            "text/html; charset=utf-8",
        )

    def _send_backup(self) -> None:
        """Send the database file, if the operator opened the download.

        The file is sent in parts. Reading it into memory first would need as
        much memory as the database is large, and the container that serves
        this page is already the one that failed to start.
        """
        if not _download_enabled():
            self._send(404, "not found", "text/plain; charset=utf-8")
            return
        if not self._is_same_origin():
            self._send(403, "cross-site request", "text/plain; charset=utf-8")
            return
        fields = self._read_body()
        expected = os.environ.get(_DOWNLOAD_TOKEN_ENV, "")
        supplied = (fields.get("token") or [""])[0] if fields is not None else ""
        if len(expected) < _MIN_DOWNLOAD_TOKEN_LENGTH or not secrets.compare_digest(
            supplied.encode(), expected.encode(),
        ):
            self._send(403, "invalid download token", "text/plain; charset=utf-8")
            return
        db_file = Path(self.db_path).resolve()
        try:
            size = db_file.stat().st_size
            handle = db_file.open("rb")
        except OSError as error:
            self._send(
                404,
                f"could not read database: {error}",
                "text/plain; charset=utf-8",
            )
            return
        with handle:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-sqlite3")
            self.send_header("Content-Length", str(size))
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="floppy-backup-{db_file.name}"',
            )
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.end_headers()
            with suppress(OSError):
                shutil.copyfileobj(handle, self.wfile, _DOWNLOAD_CHUNK_BYTES)

    def _read_body(self) -> dict | None:
        """Read a small form body. Refuse a large or malformed one."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length < 0 or length > _MAX_BODY_BYTES:
            return None
        return parse_qs(self.rfile.read(length).decode(errors="replace"))

    def _is_same_origin(self) -> bool:
        """Refuse a form sent from another site.

        A page on another site must not be able to make this choice for the
        person who runs Floppy.
        """
        site = self.headers.get("Sec-Fetch-Site")
        if site is not None:
            return site in {"same-origin", "none"}
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("Host", "")
        # Compare the whole name. A name that merely ends with the host, such
        # as "notfloppy.local" against "floppy.local", is another site.
        return bool(host) and urlsplit(origin).netloc == host

    def _restore(self) -> None:
        """Restore a snapshot, but only while the page is showing damage."""
        report = _read_incident_report(self.db_path)
        if not report or report.get("status") != "corrupt":
            self._send(409, "the database is not marked as damaged", "text/plain")
            return
        if not self._is_same_origin():
            self._send(403, "cross-site request", "text/plain; charset=utf-8")
            return
        try:
            name, aside = restore_latest(self.db_path)
        except RestoreError as error:
            _log(f"[entrypoint] Restore failed:\n{error.report}")
            self._send(409, _restore_failure_page(error), "text/html; charset=utf-8")
            return
        _log(
            f"[entrypoint] Restored snapshot {name}; the damaged files were moved to {aside}"
        )
        _write_retry_decision(self.db_path)
        self._send(200, _waiting_page(), "text/html; charset=utf-8")
        with suppress(OSError):
            self.wfile.flush()
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def do_POST(self) -> None:
        if self.path == "/backup":
            self._send_backup()
            return
        if self.path == "/restore":
            self._restore()
            return
        if self.path == "/retry":
            status = read_startup_status(self.db_path)
            if not status or status.get("status") != "timeout":
                self._send(409, "startup is not waiting after a timeout", "text/plain")
                return
            if not self._is_same_origin():
                self._send(403, "cross-site request", "text/plain; charset=utf-8")
                return
            _write_retry_decision(self.db_path)
            self._send(200, _retry_waiting_page(), "text/html; charset=utf-8")
            with suppress(OSError):
                self.wfile.flush()
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return

        action = {"/accept": "accept", "/quarantine": "quarantine"}.get(self.path)
        report = _read_incident_report(self.db_path)
        if action is None or not report:
            self._send(404, "not found", "text/plain; charset=utf-8")
            return
        if action not in (report.get("actions") or {}):
            self._send(
                403,
                _document(
                    "<h1>That recovery choice is not available.</h1>"
                    "<p>Floppy changed nothing. Reload the recovery page and use "
                    "one of the choices shown for the current database state.</p>"
                ),
                "text/html; charset=utf-8",
            )
            return
        if not self._is_same_origin():
            self._send(403, "cross-site request", "text/plain; charset=utf-8")
            return
        if action == "quarantine":
            fields = self._read_body()
            if fields is None:
                self._send(400, "bad request", "text/plain; charset=utf-8")
                return
            supplied = (fields.get("token") or [""])[0].strip()
            expected = report.get("incident_token") or ""
            if not supplied or not expected or not secrets.compare_digest(
                supplied,
                expected,
            ):
                self._send(
                    403,
                    _document(
                        "<h1>That code is not correct.</h1><p>Use the current "
                        f"approval code, found in {_CONTAINER_LOG_HINT}. The code "
                        "changes when the database state changes. No entry was "
                        "changed.</p>",
                    ),
                    "text/html; charset=utf-8",
                )
                return
            if not report.get("can_quarantine"):
                self._send(
                    403,
                    _document(
                        "<h1>Cannot automatically repair</h1><p>These entries "
                        "cannot be changed automatically.</p>",
                    ),
                    "text/html; charset=utf-8",
                )
                return
        _write_decision(self.db_path, report, action)
        self._send(200, _waiting_page(), "text/html; charset=utf-8")
        # The response is written above, but the socket is closed when this
        # process ends. Flush first, or the page never reaches the browser.
        with suppress(OSError):
            self.wfile.flush()
        threading.Thread(target=self.server.shutdown, daemon=True).start()


def serve(db_path: str, port: object | None = None) -> None:
    """Write the page, then serve it until the container stops."""
    server_port = (
        resolve_server_port()
        if port is None
        else validate_port(port, source="recovery server port")
    )
    report = _read_incident_report(db_path)
    status = read_startup_status(db_path)
    try:
        page_path = write_page(db_path, report, port=server_port, status=status)
        _log(f"[entrypoint] Recovery page written to {page_path}")
    except OSError as error:
        _log(f"[entrypoint] Could not write the recovery page: {error}")

    _Handler.db_path = db_path
    _Handler.server_port = server_port
    socket.setdefaulttimeout(_SOCKET_TIMEOUT_SECONDS)
    try:
        server = ThreadingHTTPServer(("", server_port), _Handler)
    except OSError as error:
        _log(
            f"[entrypoint] Could not use port {server_port} for the recovery page: "
            f"{error}. Open the file above instead.",
        )
        return
    _log(
        f"[entrypoint] Open http://localhost:{server_port}/ to choose what Floppy does "
        "next.",
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    cli_port = sys.argv[_PORT_ARG_INDEX] if len(sys.argv) > _PORT_ARG_INDEX else None
    serve(sys.argv[_DB_PATH_ARG_INDEX], cli_port)
