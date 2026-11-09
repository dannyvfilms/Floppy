# A developer CLI, not app code: printing a report is the point.
# ruff: noqa: T201, S603, S607, S310, DTZ005, PLW1510, S108
"""Repeatable review screenshots for the web app and the Expo app.

    uv run --no-sync python scripts/review_screenshots.py            # full run
    uv run --no-sync python scripts/review_screenshots.py --no-export  # reuse the last Expo export
    uv run --no-sync python scripts/review_screenshots.py --ios      # also grab a booted iOS Simulator

It starts a local Floppy (the run-floppy recipe), seeds a user plus one saved
book with a Barcode field, then drives headless Chromium through the search
scopes at desktop and phone widths:

* ``web``   - the Django-rendered app with its React islands.
* ``expo``  - the Expo web export (react-native-web) served same-origin through
              a tiny proxy, because the export authenticates with the Floppy
              session cookie.
* ``ios``   - optional ``simctl`` screenshot of whatever the booted Simulator
              shows. Launching Expo Go and tapping stays manual; this only
              records the frame. Expo web is NOT iOS or Android runtime evidence.

Output: ``.floppy/review-shots/<timestamp>/`` with PNGs, ``manifest.json`` (every
check and its result) and a self-contained ``report.html`` to publish or open.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
EXPO_DIR = ROOT / "native-proof"
EXPO_EXPORT = ROOT / ".floppy" / "expo-search-preview"  # no-auth search preview route
ISBN = "9780306406157"
USER, PASSWORD = "review", "review-pass-12345"
DESKTOP = {"width": 1280, "height": 800}
PHONE = {"width": 390, "height": 844}
UV = ["uv", "run", "--project", "..", "--no-sync"]

SEED = f"""
import events.tasks  # noqa: F401
from django.contrib.auth import get_user_model
from app.models import (CollectionEntry, CollectionField, CollectionFieldGroup,
    CollectionFieldType, Item, MediaTypes, Sources)
user, _ = get_user_model().objects.get_or_create(username={USER!r})
user.set_password({PASSWORD!r}); user.save()
group, _ = CollectionFieldGroup.objects.get_or_create(user=user, name="Shelf")
field, _ = CollectionField.objects.get_or_create(group=group, label="Barcode",
    defaults={{"field_type": CollectionFieldType.TEXT, "media_types": [MediaTypes.BOOK.value]}})
item, _ = Item.objects.get_or_create(media_id="review-owned-book", source=Sources.MANUAL.value,
    media_type=MediaTypes.BOOK.value, defaults={{"title": "Owned Book (saved barcode)", "image": ""}})
CollectionEntry.objects.get_or_create(user=user, item=item,
    defaults={{"custom_field_values": {{str(field.id): {ISBN!r}}}}})
"""


# macOS: a forked gunicorn worker that makes its first outbound request can die
# with "+[Swift.__SharedStringStorage initialize] ... fork()". These two switches
# are the standard workaround and are harmless elsewhere.
ENV = {
    **os.environ,
    "DJANGO_SETTINGS_MODULE": "local_serve",
    "OBJC_DISABLE_INITIALIZE_FORK_SAFETY": "YES",
    "NO_PROXY": "*",
}


def free_port():
    """Return an unused local port, so another session's server is never reused."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run(cmd, **kwargs):
    """Run a command in src/ and return its output, failing loudly."""
    return subprocess.run(
        cmd, cwd=SRC, check=True, capture_output=True, text=True, env=ENV, **kwargs,
    ).stdout


def start_floppy(port):
    """Migrate, seed, collect static and start the local server.

    Uses its own port and log directory so it never collides with another
    session's server on the run-floppy default (8299).
    """
    ENV["FLOPPY_LOCAL_PORT"] = str(port)
    ENV["FLOPPY_LOCAL_LOGDIR"] = f"/tmp/floppy-review-{port}"
    if subprocess.run(["redis-cli", "ping"], capture_output=True).returncode:
        subprocess.run(["redis-server", "--port", "6379", "--daemonize", "yes",
                        "--save", "", "--dir", "/tmp"], check=True)
    run([*UV, "python", "manage.py", "migrate", "--noinput"])
    run([*UV, "python", "manage.py", "shell", "-c", SEED])
    run([*UV, "python", "manage.py", "collectstatic", "--noinput"])
    run(["bash", "../.claude/skills/run-floppy/scripts/serve.sh", "start"])
    return f"http://localhost:{port}"


def stop_floppy():
    """Stop the local server."""
    subprocess.run(["bash", "../.claude/skills/run-floppy/scripts/serve.sh", "stop"],
                   cwd=SRC, capture_output=True, env=ENV)


def export_expo():
    """Build the Expo search-preview web export (see native-proof/app/routes/search-preview.jsx)."""
    subprocess.run(["npm", "run", "-s", "export:search-preview"], cwd=EXPO_DIR, check=True)


def serve_proxy(floppy, port):
    """Serve the Expo export at /static/native-proof/ and proxy the rest to Floppy."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_any(self):
            if self.path.startswith("/static/native-proof/"):
                rel = self.path.split("?")[0].removeprefix("/static/native-proof/") or "index.html"
                file = EXPO_EXPORT / rel
                if file.is_file():
                    kind = {"html": "text/html", "js": "application/javascript",
                            "css": "text/css", "json": "application/json",
                            "svg": "image/svg+xml", "png": "image/png",
                            "ttf": "font/ttf"}.get(file.suffix[1:], "application/octet-stream")
                    body = file.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", kind)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
            length = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(length) if length else None
            # Keep the proxy's Host so absolute URLs in API bodies stay same-origin.
            headers = dict(self.headers.items())
            headers["X-Real-IP"] = "127.0.0.1"
            request = urllib.request.Request(floppy + self.path, data=data,
                                             headers=headers, method=self.command)
            opener = urllib.request.build_opener(NoRedirect)
            try:
                response = opener.open(request)
            except urllib.error.HTTPError as error:
                response = error
            body = response.read()
            self.send_response(response.status)
            proxy = f"http://{self.headers.get('Host')}"
            for key, value in response.headers.items():
                if key.lower() not in {"transfer-encoding", "connection", "content-length"}:
                    # Keep redirects on the proxy origin: the Expo client refuses
                    # a redirect to another origin.
                    # CR/LF are removed so a header value cannot split the response.
                    clean = value.replace(floppy, proxy).replace("\r", "").replace("\n", "")
                    self.send_header(key, clean)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = handle_any  # noqa: N815

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def login(page, base):
    """Log in through the Floppy login form."""
    page.goto(f"{base}/accounts/login/")
    page.fill("#id_login", USER)
    page.fill("#id_password", PASSWORD)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")


def goto(page, url):
    """Navigate, retrying once: a live provider can drop the first request."""
    try:
        page.goto(url)
    except Exception:
        page.wait_for_timeout(1500)
        page.goto(url)


def search_state(page):
    """Return what the search control shows right now."""
    return page.evaluate("""() => {
      const root = document.querySelector('[data-global-search-root]') || document;
      const scan = [...root.querySelectorAll('[aria-label="Scan barcode"]')];
      const visible = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
      return {
        camera: scan.filter(visible).length,
        spinner: [...root.querySelectorAll('[role=progressbar], svg.animate-spin')].filter(visible).length,
        mounted: document.querySelector('[data-global-search-root]')?.dataset.reactMounted ?? null,
      };
    }""")


def web_cases(browser, base, out, results):
    """Screenshot the Django-rendered search at each scope and width."""
    cases = [
        ("all-empty", "all", "", 1, 0),
        ("manga-empty", "manga", "", 1, 0),
        ("movie-empty", "movie", "", 0, 0),
        ("all-isbn-results", "all", ISBN, 1, 0),
    ]
    for width_name, viewport in (("desktop", DESKTOP), ("phone", PHONE)):
        context = browser.new_context(viewport=viewport, color_scheme="dark",
                                      extra_http_headers={"X-Real-IP": "127.0.0.1"})
        page = context.new_page()
        login(page, base)
        for name, scope, query, want_camera, want_spinner in cases:
            goto(page, f"{base}/search?media_type={scope}&q={query}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(800)
            state = search_state(page)
            shot = out / f"web-{name}-{width_name}.png"
            page.screenshot(path=shot)
            results.append({
                "surface": "web", "case": f"{name} ({width_name})", "file": shot.name,
                "state": state, "expected": {"camera": want_camera, "spinner": want_spinner},
                "pass": state["camera"] == want_camera and state["spinner"] == want_spinner,
            })
        context.close()


def expo_cases(browser, proxy_base, out, results):
    """Screenshot the Expo search preview at phone width, per starting scope.

    The Expo web build cannot sign in (it only accepts a same-origin session and
    shows the connect screen otherwise), so it renders the real SearchSlot
    through the no-auth preview route instead. Scopes mirror the web cases.
    """
    context = browser.new_context(viewport=PHONE, color_scheme="dark")
    page = context.new_page()
    for scope, want_camera in (("all", 1), ("book", 1), ("manga", 1), ("comic", 1),
                               ("comicissue", 1), ("movie", 0), ("game", 0)):
        page.goto(f"{proxy_base}/static/native-proof/?type={scope}")
        page.wait_for_timeout(3500)
        state = search_state(page)
        shot = out / f"expo-web-{scope}-phone.png"
        page.screenshot(path=shot)
        results.append({
            "surface": "expo-web", "case": f"{scope} scope (phone)", "file": shot.name,
            "state": state, "expected": {"camera": want_camera, "spinner": 0},
            "pass": state["camera"] == want_camera and state["spinner"] == 0,
        })
    page.goto(f"{proxy_base}/static/native-proof/?type=all")
    page.wait_for_timeout(3000)
    page.get_by_label("Scan barcode").first.click()
    page.wait_for_timeout(1500)
    shot = out / "expo-web-scanner-open-phone.png"
    page.screenshot(path=shot)
    results.append({"surface": "expo-web", "case": "scanner opened from All (phone)",
                    "file": shot.name, "state": "opened", "expected": None, "pass": None})
    context.close()


def ios_shot(out, results):
    """Record the booted iOS Simulator's current screen, if there is one."""
    booted = subprocess.run(["xcrun", "simctl", "list", "devices", "booted"],
                            capture_output=True, text=True).stdout
    if "Booted" not in booted:
        results.append({"surface": "ios", "case": "simulator", "file": None,
                        "state": "no booted simulator", "expected": None, "pass": None})
        return
    shot = out / "ios-simulator.png"
    subprocess.run(["xcrun", "simctl", "io", "booted", "screenshot", str(shot)], check=True)
    results.append({"surface": "ios", "case": "simulator frame", "file": shot.name,
                    "state": "captured, not driven", "expected": None, "pass": None})


def write_report(out, results):
    """Write manifest.json and a self-contained report.html."""
    (out / "manifest.json").write_text(json.dumps(results, indent=2))
    rows = []
    for item in results:
        image = ""
        if item["file"]:
            data = base64.b64encode((out / item["file"]).read_bytes()).decode()
            image = f'<img src="data:image/png;base64,{data}" alt="{item["case"]}">'
        verdict = {True: "pass", False: "FAIL", None: "recorded"}[item["pass"]]
        rows.append(f'<section><h3>{item["surface"]}: {item["case"]} <b class="{verdict}">'
                    f'{verdict}</b></h3><code>{json.dumps(item["state"])} expected '
                    f'{json.dumps(item["expected"])}</code>{image}</section>')
    (out / "report.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Review screenshots</title>"
        "<style>body{font:14px system-ui;background:#181a1b;color:#eee;margin:16px}"
        "section{margin:0 0 24px}img{max-width:100%;border:1px solid #444}"
        ".pass{color:#4ade80}.FAIL{color:#f87171}.recorded{color:#aaa}</style>"
        + "".join(rows))


def main():
    """Run the capture."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--port", type=int, default=0, help="0 picks a free port")
    parser.add_argument("--proxy-port", type=int, default=0)
    parser.add_argument("--no-export", action="store_true", help="reuse the last Expo export")
    parser.add_argument("--no-expo", action="store_true")
    parser.add_argument("--ios", action="store_true")
    args = parser.parse_args()

    args.port = args.port or free_port()
    args.proxy_port = args.proxy_port or free_port()
    out = ROOT / ".floppy" / "review-shots" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    results: list[dict] = []
    if not args.no_expo and not args.no_export:
        export_expo()
    base = start_floppy(args.port)
    try:
        time.sleep(1)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            web_cases(browser, base, out, results)
            if not args.no_expo:
                serve_proxy(base, args.proxy_port)
                expo_cases(browser, f"http://127.0.0.1:{args.proxy_port}", out, results)
            browser.close()
        if args.ios:
            ios_shot(out, results)
    finally:
        stop_floppy()
    write_report(out, results)
    failed = [r for r in results if r["pass"] is False]
    print(f"{len(results)} captures, {len(failed)} failed -> {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
