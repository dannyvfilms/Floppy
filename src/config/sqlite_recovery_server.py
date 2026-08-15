"""Show the SQLite recovery page while startup is paused.

Django cannot serve this page. The database is the thing that is paused, and
migrations have not run, so this uses only the standard library.

The same page is written to disk beside the database. If the port is in use, or
the container is stopped, the person who runs Floppy can still open the file and
read what happened.
"""

from __future__ import annotations

import html
import json
import secrets
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from config.sqlite_integrity import (
    _RECOVERY_PAGE_NAME,
    _decision_path,
    _log,
    _publish_report,
    _read_incident_report,
)

_PORT = 8000
_HEALTH_PATHS = frozenset({"/health", "/health/"})
_MAX_BODY_BYTES = 4096
_SOCKET_TIMEOUT_SECONDS = 15
# The approval code proves that the person has read the report file. The page
# must never show it, or the code proves only that they opened the page.
_SECRET_REPORT_KEYS = frozenset({"actions", "incident_token"})

_HELP_LINKS = (
    ("Report a problem", "https://github.com/dannyvfilms/Floppy/issues"),
    ("Read the wiki", "https://github.com/dannyvfilms/Floppy/wiki"),
    ("Ask on Discord", "https://discord.gg/QfNA6zJ5Ws"),
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

# Copied from src/static/css/input.css. The page must not request an external
# stylesheet, because it also opens as a file from the database folder.
_STYLE = """
:root{--page:#212529;--panel:#272c31;--text:#f3f4f6;--muted:#9ca3af;
--accent:#4a9eff;--border:#2c3136}
@media (prefers-color-scheme: light){:root{--page:#f8f9fa;--panel:#fff;
--text:#1f2937;--muted:#4b5563;--accent:#2f80ed;--border:#dee2e6}}
*{box-sizing:border-box}
body{margin:0;padding:2.5rem 1.25rem;background:var(--page);color:var(--text);
font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:44rem;margin:0 auto}
h1{font-size:1.5rem;margin:0 0 .5rem}
p{margin:0 0 1rem;color:var(--muted)}
.card{background:var(--panel);border:1px solid var(--border);border-radius:10px;
padding:1.25rem;margin:1rem 0}
.card h2{font-size:1.05rem;margin:0 0 .35rem;color:var(--text)}
ul{list-style:none;padding:0;margin:.5rem 0}
li{display:flex;justify-content:space-between;gap:1rem;padding:.3rem 0;
border-bottom:1px solid var(--border);color:var(--text)}
li:last-child{border-bottom:0}
li span:last-child{color:var(--muted);white-space:nowrap}
button{background:var(--accent);color:#fff;border:0;border-radius:7px;
padding:.6rem 1.1rem;font-size:1rem;cursor:pointer}
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


def render_page(report: dict | None, *, interactive: bool) -> str:
    """Build the page. The written file is the same page without the buttons."""
    if not report:
        body = (
            "<h1>Your data is safe. Nothing was deleted.</h1>"
            "<p>Floppy paused before it started. It cannot read the report that "
            "explains why. Look at the container log for the reason.</p>"
            + _help_card()
        )
        return _document(body)

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
            "<div class='card'><h2>Start anyway, keep everything</h2>"
            "<p>Floppy starts and changes no data. The affected entries stay "
            "hidden until you repair them.</p>"
            "<form method='POST' action='/accept'><button>Start Floppy</button>"
            "</form></div>",
        )
        if can_quarantine:
            parts.append(
                "<div class='card'><h2>Remove the affected entries</h2>"
                "<p>Floppy saves a full backup first. Then it removes the "
                f"{total} entries above and starts.</p>"
                "<p class='note'>To confirm, copy the code from "
                "<code>db.sqlite3.integrity.json</code> in the same folder as "
                "your database.</p>"
                "<form method='POST' action='/quarantine'>"
                "<input name='token' placeholder='Paste the code' size='34'>"
                "<button>Remove entries</button></form></div>",
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
            "port 8000 while the container runs.</p></div>",
        )

    parts.append(
        "<div class='card'><h2>Use a backup instead</h2>"
        "<p>Stop Floppy. Replace <code>db.sqlite3</code> with your backup. "
        "Start Floppy again.</p></div>",
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


def _document(body: str) -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Floppy needs a decision</title>"
        f"<style>{_STYLE}</style></head><body><main>{body}</main>"
        f"<script>{_COPY_SCRIPT}</script></body></html>"
    )


def write_page(db_path: str, report: dict | None) -> Path:
    """Write the page beside the database so it is always available."""
    page_path = Path(db_path).resolve().with_name(_RECOVERY_PAGE_NAME)
    _publish_report(page_path, render_page(report, interactive=False), mode=0o644)
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
    timeout = _SOCKET_TIMEOUT_SECONDS

    def log_message(self, *_args) -> None:
        """Keep the container log free of one line per request."""

    def _send(self, status: int, body: str, content_type: str) -> None:
        payload = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        # Floppy is not able to serve requests, so the health check must fail.
        # A success here would report the container as healthy while it is not.
        if self.path.split("?")[0] in _HEALTH_PATHS:
            self._send(503, "paused", "text/plain; charset=utf-8")
            return
        report = _read_incident_report(self.db_path)
        self._send(
            200,
            render_page(report, interactive=True),
            "text/html; charset=utf-8",
        )

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
            if not report.get("can_quarantine") or not secrets.compare_digest(
                supplied,
                expected,
            ):
                self._send(
                    403,
                    _document(
                        "<h1>That code is not correct.</h1><p>Copy the code from "
                        "<code>db.sqlite3.integrity.json</code>. No entry was "
                        "changed.</p>",
                    ),
                    "text/html; charset=utf-8",
                )
                return
        _write_decision(self.db_path, report, action)
        self._send(
            200,
            _document(
                "<h1>Thank you. Restart Floppy now.</h1>"
                "<p>Floppy applies your choice when it starts again.</p>",
            ),
            "text/html; charset=utf-8",
        )


def serve(db_path: str) -> None:
    """Write the page, then serve it until the container stops."""
    report = _read_incident_report(db_path)
    try:
        page_path = write_page(db_path, report)
        _log(f"[entrypoint] Recovery page written to {page_path}")
    except OSError as error:
        _log(f"[entrypoint] Could not write the recovery page: {error}")

    _Handler.db_path = db_path
    socket.setdefaulttimeout(_SOCKET_TIMEOUT_SECONDS)
    try:
        server = ThreadingHTTPServer(("", _PORT), _Handler)
    except OSError as error:
        _log(
            f"[entrypoint] Could not use port {_PORT} for the recovery page: "
            f"{error}. Open the file above instead.",
        )
        return
    _log(
        f"[entrypoint] Open http://localhost:{_PORT}/ to choose what Floppy does "
        "next.",
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    serve(sys.argv[1])
