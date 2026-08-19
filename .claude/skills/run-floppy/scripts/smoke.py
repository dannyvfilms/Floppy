#!/usr/bin/env python3
# A developer CLI, not app code: printing a report is the whole point (T201),
# /tmp is the right place for throwaway screenshots (S108), and glob.glob reads
# more clearly than Path.glob for a single absolute pattern (PTH207).
# ruff: noqa: T201, S108, PTH207, PLR2004
"""Log into a local Floppy and sweep pages in headless Chromium.

Reports HTTP status, whether a server-error page rendered, and console errors
per page, and writes a screenshot of each. A 200 only proves the view didn't
raise - read the screenshots before believing a page is fine.

    python smoke.py --base http://localhost:8299
    python smoke.py --only statistics --shots /tmp/shots
    python smoke.py --pages custom=/medialist/manga

Sends X-Real-IP because settings.py sets ALLAUTH_TRUSTED_CLIENT_IP_HEADER when
IS_PROD, and allauth 403s requests without it. nginx supplies it in production.
Harmless when running with IS_PROD=False.
"""

from __future__ import annotations

import argparse
import glob
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

# Cache-heavy views first - they're the ones that break when cache or task
# scheduling changes.
DEFAULT_PAGES = [
    ("home", "/"),
    ("movies", "/medialist/movie"),
    ("tv", "/medialist/tv"),
    ("anime", "/medialist/anime"),
    ("games", "/medialist/game"),
    ("books", "/medialist/book"),
    ("history", "/history"),
    ("statistics", "/statistics"),
    ("calendar", "/calendar"),
    ("discover", "/discover"),
    ("settings-account", "/settings/account"),
    ("settings-prefs", "/settings/preferences"),
    ("settings-home", "/settings/home-screen"),
    ("settings-integrations", "/settings/integrations"),
    ("settings-advanced", "/settings/advanced"),
]

ERROR_MARKERS = ("Server Error", "Internal Server Error", "Traceback")


def find_chromium() -> str:
    """Return the preinstalled Chromium path (the version dir is not stable)."""
    matches = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))
    if not matches:
        sys.exit(
            "No Chromium under /opt/pw-browsers. Do not run `playwright install`; "
            "set PLAYWRIGHT_BROWSERS_PATH or pass --chromium."
        )
    return matches[-1]


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default="http://localhost:8299")
    p.add_argument("--user", default="smoke")
    p.add_argument("--password", default="smoketest12345")
    p.add_argument("--shots", default="/tmp/floppy-local/shots")
    p.add_argument("--chromium", default=None)
    p.add_argument("--only", default=None, help="run just this page name")
    p.add_argument(
        "--pages",
        default=None,
        help="extra pages as name=/path, comma separated",
    )
    return p.parse_args()


def main() -> int:
    """Log in, sweep the pages, print a table, return non-zero on failure."""
    args = parse_args()
    out = Path(args.shots)
    out.mkdir(parents=True, exist_ok=True)

    pages = list(DEFAULT_PAGES)
    if args.pages:
        for entry in args.pages.split(","):
            name, _, path = entry.partition("=")
            if path:
                pages.append((name.strip(), path.strip()))
    if args.only:
        pages = [p for p in pages if p[0] == args.only]
        if not pages:
            sys.exit(f"no page named {args.only!r}")

    results = []
    failures = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=args.chromium or find_chromium(),
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = browser.new_page(
            viewport={"width": 1280, "height": 900},
            extra_http_headers={"X-Real-IP": "127.0.0.1"},
        )

        console: list[str] = []
        # Static 404s are nginx's job in production; not worth reporting here.
        page.on(
            "console",
            lambda m: console.append(m.text)
            if m.type == "error" and "/static/" not in m.text
            else None,
        )
        page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))

        resp = page.goto(f"{args.base}/accounts/login/", wait_until="domcontentloaded")
        print(f"login page: HTTP {resp.status if resp else '?'}")
        page.fill("#id_login", args.user)
        page.fill("#id_password", args.password)
        with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
            page.locator("button[type='submit']").first.click()

        if "/accounts/login" in page.url:
            page.screenshot(path=str(out / "login-failed.png"))
            body = re.sub(r"\s+", " ", page.inner_text("body"))[:300]
            print(f"LOGIN FAILED - still at {page.url}\n  {body}")
            print(
                "\nA 403 here usually means the X-Real-IP/allauth issue or a bad "
                "password, not CSRF - see the skill's 'Login returns 403' section."
            )
            browser.close()
            return 1
        print(f"logged in -> {page.url}")

        for name, path in pages:
            console.clear()
            try:
                resp = page.goto(
                    f"{args.base}{path}", wait_until="domcontentloaded", timeout=45000
                )
                status = resp.status if resp else 0
                body = page.content()
                errored = any(marker in body for marker in ERROR_MARKERS)
                page.screenshot(path=str(out / f"{name}.png"))
                ok = status < 400 and not errored
            except Exception as error:  # report and keep sweeping the other pages
                status, errored, ok = "EXC", str(error)[:60], False
            results.append((name, path, status, errored, list(console), ok))
            if not ok:
                failures.append(name)

        browser.close()

    print(f"\n{'PAGE':<22} {'PATH':<28} {'HTTP':>5}  {'':<6} NOTES")
    for name, path, status, errored, errors, ok in results:
        notes = []
        if errored:
            notes.append("server error page" if errored is True else str(errored))
        if errors:
            notes.append(f"console:{len(errors)}")
        print(
            f"{name:<22} {path:<28} {status!s:>5}  "
            f"{'ok' if ok else 'FAIL':<6} {' '.join(notes)}"
        )

    distinct = {e for _, _, _, _, errs, _ in results for e in errs}
    if distinct:
        print("\ndistinct console messages:")
        for message in sorted(distinct):
            print(f"  {message[:110]}")

    print(f"\nscreenshots: {out}  <- look at these, a 200 is not proof of rendering")
    print(f"failed pages: {failures or 'none'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
