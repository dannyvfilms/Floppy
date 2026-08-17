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
import sys
import threading
from contextlib import suppress
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from config.server_port import DEFAULT_SERVER_PORT, resolve_server_port, validate_port
from config.sqlite_integrity import (
    _RECOVERY_PAGE_NAME,
    _decision_path,
    _log,
    _publish_report,
    _read_incident_report,
)

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
# The approval code proves that the person has read the report file. The page
# must never show it, or the code proves only that they opened the page.
_SECRET_REPORT_KEYS = frozenset({"actions", "incident_token"})

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
    mark = (
        f"<img src='{icon}' alt='' width='36' height='36'>" if icon else ""
    )
    return f"<header class='masthead'>{mark}<span>Floppy</span></header>"


def _download_enabled() -> bool:
    """Report whether the operator opened the database download."""
    value = os.environ.get(_DOWNLOAD_ENV, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _backup_card() -> str:
    """Offer the copy Floppy already made, or the download if it is open."""
    if _download_enabled():
        action = (
            "<p><a class='button secondary' href='/backup'>"
            "Download database copy</a></p>"
        )
    else:
        action = (
            "<p class='note'>Floppy writes a copy of the database to the "
            "<code>sqlite-recovery</code> folder beside <code>db.sqlite3</code> "
            "before it removes any entry. Copy the file from there.</p>"
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
    return "<div class='card'><h2>What is affected</h2><ul>" + "".join(rows) + "</ul></div>"


def render_page(
    report: dict | None,
    *,
    interactive: bool,
    port: int = DEFAULT_SERVER_PORT,
) -> str:
    """Build the page. The written file is the same page without the buttons."""
    port = validate_port(port, source="recovery page port")
    if not report:
        body = (
            "<h1>Your data is safe. Nothing was deleted.</h1>"
            "<p>Floppy paused before it started. It cannot read the report that "
            "explains why. Look at the container log for the reason.</p>"
            + _help_card()
        )
        return _document(body)

    if report.get("status") == "corrupt":
        corruption_reasons = "".join(
            f"<li><span>{html.escape(r)}</span></li>"
            for r in report.get("unsafe_reasons", [])
        )
        parts = [
            "<h1>Floppy cannot read the database file.</h1>",
            "<p>The file is damaged. Floppy changed nothing, because a write "
            "can damage it more. Replace the file with a backup.</p>",
            "<div class='card'><h2>What Floppy found</h2>"
            f"<ul>{corruption_reasons}</ul></div>",
            "<div class='card'><h2>Keep a copy of the damaged file</h2>"
            "<p>Keep the damaged file before you replace it. A repair tool can "
            "still read data from it.</p>" + _backup_card() + "</div>",
            "<div class='card'><h2>How to restore</h2><ol>"
            "<li>Stop Floppy.</li>"
            "<li>Replace <code>db.sqlite3</code> with your known-good backup.</li>"
            "<li>Start Floppy.</li></ol></div>",
            _help_card(),
        ]
        return _document("".join(parts))

    total = _count(report.get("total_conflicts"))
    can_quarantine = bool(report.get("can_quarantine"))
    parts = [
        "<h1>Your data is safe. Nothing was deleted.</h1>",
        f"<p>Floppy found {total} entries that point to a record that is no "
        "longer in the database. Floppy paused so that you can choose what to "
        "do. No entry was changed.</p>",
        _affected_list(report),
    ]

    if interactive:
        parts.append(
            "<div class='card'><h2>Keep the entries, then start</h2>"
            "<p>Floppy starts and changes no data. The affected entries stay "
            "hidden until you repair them.</p>"
            "<form method='POST' action='/accept'>"
            "<button>Keep everything and start Floppy</button></form></div>",
        )
        if can_quarantine:
            parts.append(
                "<div class='card'><h2>Remove the entries, then start</h2>"
                "<p>Floppy saves a backup of the database first. Then it "
                f"removes the {total} entries above and starts. You cannot "
                "undo this, but the backup keeps the entries.</p>"
                "<form method='POST' action='/quarantine'>"
                f"<button>Remove {total} entries and start Floppy</button>"
                "</form></div>",
            )
        else:
            parts.append(
                "<div class='card'><h2>Repair these entries yourself</h2>"
                "<p>Floppy cannot remove these entries safely. The container "
                "log gives the reason.</p></div>",
            )
    else:
        parts.append(
            "<div class='card'><h2>How to choose</h2>"
            "<p>This is a copy on disk. To choose an action, open Floppy at "
            f"port {port} while the container runs.</p></div>",
        )

    parts.append(
        "<div class='card'><h2>Use a backup instead</h2><ol>"
        "<li>Stop Floppy.</li>"
        "<li>Replace <code>db.sqlite3</code> with your backup.</li>"
        "<li>Start Floppy.</li></ol>" + _backup_card() + "</div>",
    )
    parts.append(_help_card())
    public = {
        key: value
        for key, value in report.items()
        if key not in _SECRET_REPORT_KEYS
    }
    parts.append(
        "<details><summary>Technical details for a bug report</summary>"
        "<p><button data-copy='details'>Copy details</button></p>"
        "<pre id='details'>"
        + html.escape(json.dumps(public, indent=2, sort_keys=True))
        + "</pre></details>",
    )
    return _document("".join(parts))


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
        "stays on this message, look at the container log.</p>"
        "<p><a class='button' href='/'>Open Floppy</a></p>"
        "</div>"
    )
    return _document(body, script=_POLL_SCRIPT)


def _help_card() -> str:
    """Offer the places where a person can get help."""
    links = " · ".join(
        f"<a href='{url}' target='_blank' rel='noopener noreferrer'>"
        f"{html.escape(label)}</a>"
        for label, url in _HELP_LINKS
    )
    return (
        "<div class='card'><h2>Get help</h2>"
        "<p>Copy the details below and send them with your question.</p>"
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
) -> Path:
    """Write the page beside the database so it is always available."""
    page_path = Path(db_path).resolve().with_name(_RECOVERY_PAGE_NAME)
    _publish_report(
        page_path,
        render_page(report, interactive=False, port=port),
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
            self._send_backup()
            return
        report = _read_incident_report(self.db_path)
        self._send(
            200,
            render_page(report, interactive=True, port=self.server_port),
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
        db_file = Path(self.db_path).resolve()
        try:
            size = db_file.stat().st_size
            handle = db_file.open("rb")
        except OSError as error:
            self._send(404, f"could not read database: {error}", "text/plain; charset=utf-8")
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

    def do_POST(self) -> None:
        action = {"/accept": "accept", "/quarantine": "quarantine"}.get(self.path)
        report = _read_incident_report(self.db_path)
        if action is None or not report:
            self._send(404, "not found", "text/plain; charset=utf-8")
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
            if supplied and expected and not secrets.compare_digest(supplied, expected):
                self._send(
                    403,
                    _document(
                        "<h1>That code is not correct.</h1><p>The code belongs "
                        "to an earlier problem. Open this page again to get the "
                        "current one. No entry was changed.</p>",
                    ),
                    "text/html; charset=utf-8",
                )
                return
            if not report.get("can_quarantine"):
                self._send(
                    403,
                    _document(
                        "<h1>Cannot automatically repair</h1><p>These entries "
                        "cannot be removed automatically.</p>",
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
    try:
        page_path = write_page(db_path, report, port=server_port)
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
    cli_port = (
        sys.argv[_PORT_ARG_INDEX]
        if len(sys.argv) > _PORT_ARG_INDEX
        else None
    )
    serve(sys.argv[_DB_PATH_ARG_INDEX], cli_port)
