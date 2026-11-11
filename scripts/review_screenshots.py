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
import html
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
from http import HTTPStatus
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
                    self.send_header(key, value.replace(floppy, proxy))
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



def compare_existing(config_path):
    """Capture matched states from running previews without seeding or saving forms.

    The private Playwright storage-state file is supplied separately and never
    copied into the report. The configuration and manifest contain no cookies.
    """
    config = json.loads(Path(config_path).read_text())
    out = Path(config["output"])
    out.mkdir(parents=True, exist_ok=True)
    results = []
    previous = []
    if config.get("reuse_captures") and (out / "manifest.json").exists():
        previous = json.loads((out / "manifest.json").read_text())
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for size, viewport in config["viewports"].items():
                context = browser.new_context(storage_state=config["storage_state"], viewport=viewport)
                for case in config["cases"]:
                    for side, base in config["bases"].items():
                        prior = next((r for r in previous if r["case"] == case["name"]
                                      and r["viewport"] == size and r["side"] == side), None)
                        if (prior and prior.get("file") and (out / prior["file"]).is_file()
                                and prior.get("signed_in") and prior.get("status") == HTTPStatus.OK
                                and case["id"] not in config.get("recapture", [])):
                            results.append(prior)
                            continue
                        page = context.new_page()
                        errors = []
                        page.on("pageerror", lambda error, errors=errors: errors.append(str(error)[:350]))
                        result = {"case": case["name"], "viewport": size, "side": side,
                                  "path": case["path"], "file": None, "errors": errors}
                        try:
                            response = page.goto(base + case["path"], wait_until="domcontentloaded", timeout=45000)
                            result["status"] = response.status
                            result["signed_in"] = "/accounts/login" not in page.url
                            page.wait_for_timeout(config.get("settle_ms", 1800))
                            if case.get("hover"):
                                page.locator(case["hover"]).first.hover(timeout=12000)
                            clicks = case.get("click", [])
                            if isinstance(clicks, dict):
                                clicks = clicks.get(size, [])
                            if isinstance(clicks, str):
                                clicks = [clicks]
                            for selector in clicks:
                                page.locator(selector).first.click(timeout=12000)
                                page.wait_for_timeout(1800)
                            try:
                                page.wait_for_function("() => [...document.images].filter(i => { const r = i.getBoundingClientRect(); return r.top < innerHeight && r.bottom > 0; }).every(i => i.complete)", timeout=6000)
                            except Exception:
                                result["artwork_pending"] = True
                            result["state"] = page.evaluate("""() => ({
                              title: document.title,
                              horizontalOverflow: document.documentElement.scrollWidth > innerWidth + 1,
                              theme: document.documentElement.dataset.theme || null,
                              headings: [...document.querySelectorAll('h1,h2,h3')].filter(e => e.getBoundingClientRect().height).slice(0,15).map(e => e.textContent.trim()),
                              mountedIslands: document.querySelectorAll('[data-react-mounted="true"]').length
                            })""")
                            file = f'{case["id"]}-{size}-{side}.png'
                            masks = [page.locator("input[type=password], #token")]
                            masks.extend(page.locator(selector) for selector in case.get("mask", []))
                            page.screenshot(path=str(out / file), full_page=False,
                                            animations="disabled", mask=masks, mask_color="#465365")
                            result["file"] = file
                        except Exception as error:
                            result["capture_error"] = str(error)[:500]
                        finally:
                            page.close()
                        results.append(result)
                        print(f'{case["id"]} {size} {side}: {result.get("status", "error")} {"captured" if result["file"] else "FAILED"}', flush=True)
                context.close()
        finally:
            browser.close()
    (out / "manifest.json").write_text(json.dumps(results, indent=2))
    esc = html.escape
    sections = []
    for case in config["cases"]:
        rows = []
        for size in config["viewports"]:
            panels = []
            for side in config["bases"]:
                item = next(r for r in results if r["case"] == case["name"] and r["viewport"] == size and r["side"] == side)
                picture = "<p>Capture failed. See manifest.</p>"
                if item["file"]:
                    data = base64.b64encode((out / item["file"]).read_bytes()).decode()
                    picture = f'<a href="{esc(item["file"])}" target="_blank"><img loading="lazy" src="data:image/png;base64,{data}" alt="{esc(case["name"])}: {esc(side)} {size}"></a>'
                flags = []
                if item.get("status") != HTTPStatus.OK:
                    flags.append(f'HTTP {item.get("status")}')
                if item.get("state", {}).get("horizontalOverflow"):
                    flags.append("Horizontal overflow")
                if item.get("errors"):
                    flags.append(f'{len(item["errors"])} browser errors')
                panels.append(f'<figure><figcaption>{esc(config["labels"][side])} <small>{size}</small></figcaption>{picture}<p class="flags">{esc(" · ".join(flags))}</p></figure>')
            rows.append(f'<div class="pair" data-size="{size}">{"".join(panels)}</div>')
        choices = "".join(f'<option value="{v}" {"selected" if v == case.get("decision", "review") else ""}>{label}</option>' for v, label in [("review","Needs your decision"),("latest","Keep latest"),("branch","Keep branch"),("polish","Accept, polish later"),("neither","Neither / needs repair")])
        sections.append(f'<section id="{case["id"]}"><div class="section-head"><h2>{esc(case["name"])}</h2><select aria-label="Decision for {esc(case["name"])}" data-case="{case["id"]}">{choices}</select></div><p>{esc(case.get("note", ""))}</p><textarea aria-label="Notes for {esc(case["name"])}" data-notes="{case["id"]}" placeholder="Your notes"></textarea>{"".join(rows)}</section>')
    nav = "".join(f'<a href="#{case["id"]}">{esc(case["name"])}</a>' for case in config["cases"])
    summary = "".join(f"<li>{esc(line)}</li>" for line in config.get("summary", []))
    (out / "report.html").write_text("""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PWA branch review</title>
<style>:root{color-scheme:dark}*{box-sizing:border-box}body{font:15px/1.5 system-ui;background:#111418;color:#e6eaf0;margin:0}header,main{max-width:1700px;margin:auto;padding:24px}header{border-bottom:1px solid #36404d}h1{margin:0;font-size:30px}h2{font-size:23px}p,li{max-width:1100px;color:#bac6d5}.toolbar{position:sticky;top:0;background:#1a2029;padding:12px 24px;display:flex;gap:12px;z-index:2;align-items:center;flex-wrap:wrap}button,select,textarea{font:inherit;color:inherit;background:#242e3b;border:1px solid #52647c;border-radius:7px;padding:8px}button{cursor:pointer}nav{display:flex;flex-wrap:wrap;gap:8px 18px;margin-top:20px}a{color:#8ac4ff}section{padding:24px 0;border-bottom:1px solid #36404d;scroll-margin-top:80px}.section-head{display:flex;gap:20px;align-items:center;justify-content:space-between}textarea{width:100%;height:55px;margin:0 0 14px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px;align-items:start}.pair[data-size=phone]{max-width:850px;margin:0 auto}.pair[hidden]{display:none}figure{margin:0;min-width:0}figcaption{font-weight:600;margin:0 0 8px}small{color:#aab8c9;margin-left:12px}img{width:100%;height:auto;display:block;border:1px solid #465365}a:has(img){display:block}.flags{color:#ffbd80;font-size:13px}footer{padding:30px} @media(max-width:700px){header,main{padding:16px}.pair{grid-template-columns:1fr}.section-head{align-items:start;flex-direction:column;gap:0}}
</style><header><h1>PWA: working latest vs Expo parity branch</h1><p>Visual decision review. Same signed-in account and database, matched viewport and route. Screenshots show the first viewport, not complete page or interaction coverage.</p><ul>""" + summary + "</ul><nav>" + nav + '</nav></header><div class="toolbar"><label>Viewport <select id="viewport"><option value="desktop">Desktop</option><option value="phone">Phone</option></select></label><button id="export">Download decisions</button><small>Choices stay in this browser. Screenshot links open full size.</small></div><main>' + "".join(sections) + """</main><footer>Browser runtime evidence only. These images do not verify native iOS or Android appearance or performance. See manifest.json for capture errors and states.</footer><script>
const key='floppy-parity-review-v1:'+location.pathname;let state={};try{state=JSON.parse(localStorage.getItem(key)||'{}')}catch{};const controls=[...document.querySelectorAll('[data-case],[data-notes]')];for(const control of controls){const id=control.dataset.case||control.dataset.notes;const field=control.dataset.case?'decision':'notes';if(state[id]?.[field]!==undefined)control.value=state[id][field];control.addEventListener('input',()=>{state[id]??={};state[id][field]=control.value;try{localStorage.setItem(key,JSON.stringify(state))}catch{}})}function sizes(){document.querySelectorAll('.pair').forEach(e=>e.hidden=e.dataset.size!==document.getElementById('viewport').value)}document.getElementById('viewport').addEventListener('change',sizes);sizes();document.getElementById('export').onclick=()=>{const decisions={};for(const c of controls){const id=c.dataset.case||c.dataset.notes;decisions[id]??={};decisions[id][c.dataset.case?'decision':'notes']=c.value}const url=URL.createObjectURL(new Blob([JSON.stringify(decisions,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='pwa-review-decisions.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
</script></html>""")
    failed = [r for r in results if not r["file"] or r.get("status") != HTTPStatus.OK or not r.get("signed_in")]
    print(f'{len(results)} captures, {len(failed)} failed -> {out / "report.html"}')
    return bool(failed)


def main():
    """Run the capture."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--port", type=int, default=0, help="0 picks a free port")
    parser.add_argument("--proxy-port", type=int, default=0)
    parser.add_argument("--no-export", action="store_true", help="reuse the last Expo export")
    parser.add_argument("--no-expo", action="store_true")
    parser.add_argument("--ios", action="store_true")
    parser.add_argument("--comparison-config", help="capture running previews using a private session and matched cases")
    args = parser.parse_args()
    if args.comparison_config:
        return compare_existing(args.comparison_config)

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
