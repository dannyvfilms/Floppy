#!/usr/bin/env python3
# ruff: noqa: T201
"""Prove the island reveal contract on every page in the parity matrix.

React owns the final layout of each ``[data-props-id]`` island. The server
fallback must not paint first, and a working island must always replace it.

For every page this check loads two states:

* chunk-blocked: JavaScript is enabled but every ``/static/ui/*.js`` request is
  aborted, so CSS and Alpine load while React cannot mount. Every top-level
  island root must be hidden during the first moments, then revealed by the
  four-second fail-safe so the no-JS fallback stays usable.
* mounted: a normal load. Every top-level island root must set
  ``data-react-mounted`` and must not remain visually hidden.

Roots excluded from the gate are the deliberate no-op adapters
(``data-media-table-root`` and ``data-media-column-menu-root``). They keep
server markup, must stay visible in both states, and must not change size
between them. The sidebar root is the other exception: it mounts like any
island but stays visible while it does, so a body swap never blanks it.

Usage:
    python scripts/check_island_reveals.py
    python scripts/check_island_reveals.py --base http://localhost:8000 --only calendar
    python scripts/check_island_reveals.py --json /tmp/island-reveals.json

Exit status is non-zero when a root violates the contract. Set
``FLOPPY_USER`` / ``FLOPPY_PASSWORD`` to override the local smoke account.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

# The parity matrix's page set. Keep this list in step with /tmp/parity_matrix.py
# while a parity sweep is in progress.
PAGES = [
    ("home", "/"),
    ("movies", "/medialist/movie"),
    ("tv", "/medialist/tv"),
    ("anime", "/medialist/anime"),
    ("manga", "/medialist/manga"),
    ("games", "/medialist/game"),
    ("books", "/medialist/book"),
    ("comics", "/medialist/comic"),
    ("boardgames", "/medialist/boardgame"),
    ("music", "/medialist/music"),
    ("podcasts", "/medialist/podcast"),
    ("seasons", "/medialist/season"),
    ("videos", "/medialist/video"),
    ("history", "/history"),
    ("statistics", "/statistics"),
    ("calendar", "/calendar"),
    ("discover", "/discover"),
    ("settings-account", "/settings/account"),
    ("settings-preferences", "/settings/preferences"),
    ("settings-notifications", "/settings/notifications"),
    ("settings-appearance", "/settings/appearance"),
    ("settings-cards", "/settings/cards"),
    ("settings-sidebar", "/settings/sidebar"),
    ("settings-home", "/settings/home-screen"),
    ("providers", "/settings/providers"),
    ("settings-activity", "/settings/activity"),
    ("settings-data", "/settings/data"),
    ("settings-access", "/settings/access"),
    ("settings-advanced", "/settings/advanced"),
    ("settings-about", "/settings/about"),
    ("settings-import", "/settings/import"),
    ("settings-export", "/settings/export"),
    ("settings-rss", "/settings/rss"),
    ("settings-integrations", "/settings/integrations"),
    ("settings-users", "/settings/users"),
    ("detail-movie", "/details/tmdb/movie/603/The-Matrix"),
    ("detail-tv", "/details/tmdb/tv/1399/Game-of-Thrones"),
    ("detail-music", "/details/manual/music/fix974-track/Fix974-Track"),
    ("detail-book", "/details/hardcover/book/386401/Wuthering-Heights"),
    ("provider-anilist", "/settings/providers/anilist"),
    ("provider-anilist-connection", "/settings/providers/anilist?tab=connection"),
    ("provider-anilist-import", "/settings/providers/anilist?tab=import"),
    ("provider-anilist-activity", "/settings/providers/anilist?tab=activity"),
    ("provider-tmdb-meta", "/settings/providers/tmdb?tab=metadata"),
]

# Deliberate no-op web adapters: they retain the server markup and never set
# data-react-mounted. They are excluded from the reveal gate by
# frontend/settings/island-reveal.css.
NOOP_ROOTS = {"data-media-table-root", "data-media-column-menu-root"}
# Shell roots whose server fallback matches the mounted island. They mount like
# any island but stay visible meanwhile, because hx-boost swaps the body on every
# navigation and a hidden fallback would blank them each time.
VISIBLE_FALLBACK_ROOTS = {"data-sidebar-root"}
# A no-op adapter keeps server markup, so it may not resize between states.
NOOP_WIDTH_TOLERANCE = 2
NOOP_HEIGHT_TOLERANCE = 8
# Smaller fallback-to-mounted deltas are rounding or dynamic content, not a swap.
LAYOUT_REPORT_TOLERANCE = 4

ROOT_STATE = """
() => [...document.querySelectorAll('[data-props-id]')].map((el) => {
  const style = getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  const root = [...el.attributes]
    .map((attribute) => attribute.name)
    .filter((name) => name.endsWith('-root'))
    .join(',');
  let ancestorHidden = '';
  for (let parent = el.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
    const parentStyle = getComputedStyle(parent);
    if (parentStyle.display === 'none') { ancestorHidden = 'display'; break; }
    if (parentStyle.visibility === 'hidden') { ancestorHidden = 'visibility'; break; }
  }
  return {
    root,
    id: el.getAttribute('data-props-id'),
    nested: Boolean(el.parentElement && el.parentElement.closest('[data-props-id]')),
    mounted: el.hasAttribute('data-react-mounted'),
    visibility: style.visibility,
    display: style.display,
    opacity: Number(style.opacity),
    width: rect.width,
    height: rect.height,
    x: rect.x,
    y: rect.y,
    ancestorHidden,
    text: el.textContent.trim().replace(/\\s+/g, ' ').slice(0, 60),
  };
})
"""


def root_label(root: dict) -> str:
    """Readable name for violation messages."""
    return root["root"] or "(no -root attribute)"


def is_painted(root: dict) -> bool:
    """Whether the root (or an ancestor) makes its subtree visible."""
    return (
        root["display"] != "none"
        and root["visibility"] == "visible"
        and root["opacity"] > 0
        and not root["ancestorHidden"]
    )


def index_roots(roots: list[dict]) -> dict[tuple[str, int], dict]:
    """Stable keys across two page loads: root attribute plus occurrence order.

    Props ids include per-render hashes, so they cannot be compared across
    contexts. Top-level island order is stable.
    """
    counts: dict[str, int] = {}
    indexed = {}
    for root in roots:
        if root["nested"]:
            continue
        key = root_label(root)
        occurrence = counts.get(key, 0)
        counts[key] = occurrence + 1
        indexed[(key, occurrence)] = root
    return indexed


def login(context, base: str) -> None:
    """Sign in once and reuse the session cookies for every page state."""
    page = context.new_page()
    page.goto(base + "/accounts/login/", wait_until="domcontentloaded")
    page.fill("#id_login", os.environ.get("FLOPPY_USER", "smoke"))
    page.fill("#id_password", os.environ.get("FLOPPY_PASSWORD", "smoketest12345"))
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle", timeout=30000)
    page.close()


def local_origin(page, base: str) -> str:
    """Allow only the target origin; external artwork and fonts stay offline."""
    origin = urlsplit(base).netloc

    def route(route):
        if urlsplit(route.request.url).netloc == origin:
            route.continue_()
        else:
            route.abort()

    page.route("**/*", route)
    return origin


def chunk_blocked_route(route, origin: str) -> None:
    """Serve CSS and HTML, but fail every React chunk."""
    url = urlsplit(route.request.url)
    if url.netloc != origin:
        route.abort()
        return
    if url.path.startswith("/static/ui/") and url.path.endswith(".js"):
        route.abort()
        return
    route.continue_()


def check_page(browser, base: str, origin: str, cookies, path: str, settle_ms: int):
    """Compare the chunk-blocked and mounted states for one page."""
    violations: list[str] = []
    observations: dict[str, list[dict]] = {}

    fallback = browser.new_context(
        viewport={"width": 1440, "height": 1000},
        extra_http_headers={"X-Real-IP": "127.0.0.1"},
    )
    fallback.add_cookies(cookies)
    fallback_page = fallback.new_page()
    fallback_page.route("**/*", lambda route: chunk_blocked_route(route, origin))
    fallback_page.goto(base + path, wait_until="domcontentloaded", timeout=45000)
    with contextlib.suppress(PlaywrightTimeoutError):
        fallback_page.wait_for_load_state("networkidle", timeout=30000)
    fallback_page.wait_for_timeout(700)
    early = fallback_page.evaluate(ROOT_STATE)
    fallback_page.wait_for_timeout(4300)
    late = fallback_page.evaluate(ROOT_STATE)
    fallback.close()
    observations["chunk_blocked_early"] = early
    observations["chunk_blocked_late"] = late

    mounted = browser.new_context(
        viewport={"width": 1440, "height": 1000},
        extra_http_headers={"X-Real-IP": "127.0.0.1"},
    )
    mounted.add_cookies(cookies)
    mounted_page = mounted.new_page()
    local_origin(mounted_page, base)
    mounted_page.goto(base + path, wait_until="domcontentloaded", timeout=45000)
    with contextlib.suppress(PlaywrightTimeoutError):
        mounted_page.wait_for_load_state("networkidle", timeout=30000)
    with contextlib.suppress(PlaywrightTimeoutError):
        mounted_page.wait_for_function(
            """() => [...document.querySelectorAll('[data-props-id]')]
                .filter((el) => !el.parentElement.closest('[data-props-id]'))
                .every((el) => el.hasAttribute('data-react-mounted')
                  || el.matches('[data-media-table-root], [data-media-column-menu-root]'))""",
            timeout=max(settle_ms, 10000),
        )
    mounted_page.wait_for_timeout(min(settle_ms, 1500))
    live = mounted_page.evaluate(ROOT_STATE)
    mounted.close()
    observations["mounted"] = live

    early_top = [root for root in early if not root["nested"]]
    late_top = [root for root in late if not root["nested"]]
    live_top = [root for root in live if not root["nested"]]

    for root in early_top:
        if root_label(root) in VISIBLE_FALLBACK_ROOTS:
            if root["visibility"] == "hidden":
                violations.append(
                    f"{root_label(root)} is hidden in the fallback; it must stay visible"
                )
            continue
        if root_label(root) in NOOP_ROOTS:
            if not is_painted(root):
                violations.append(
                    f"{root_label(root)} no-op adapter is not visible in the fallback"
                )
            continue
        if is_painted(root):
            violations.append(
                f"{root_label(root)} ({root['id']}) paints in the chunk-blocked fallback"
            )

    for root in late_top:
        if root_label(root) in NOOP_ROOTS:
            continue
        if (
            root["display"] != "none"
            and root["visibility"] == "hidden"
            and not root["ancestorHidden"]
        ):
            violations.append(
                f"{root_label(root)} ({root['id']}) never reveals from the four-second fail-safe"
            )

    for root in live_top:
        if root_label(root) in NOOP_ROOTS:
            continue
        if not root["mounted"]:
            violations.append(
                f"{root_label(root)} ({root['id']}) never sets data-react-mounted"
            )
        elif (
            root["display"] != "none"
            and root["visibility"] == "hidden"
            and not root["ancestorHidden"]
        ):
            violations.append(
                f"{root_label(root)} ({root['id']}) stays hidden after mounting"
            )

    early_index = index_roots(early)
    live_index = index_roots(live)
    layout_deltas = []
    for key, before in early_index.items():
        after = live_index.get(key)
        if not after:
            continue
        if (
            root_label(before) in NOOP_ROOTS
            and is_painted(before)
            and is_painted(after)
            and (
                abs(after["width"] - before["width"]) > NOOP_WIDTH_TOLERANCE
                or abs(after["height"] - before["height"]) > NOOP_HEIGHT_TOLERANCE
            )
        ):
            violations.append(
                f"{root_label(before)} no-op adapter changed layout "
                f"{before['width']:.0f}x{before['height']:.0f} -> "
                f"{after['width']:.0f}x{after['height']:.0f}"
            )
        if before["height"] and after["height"]:
            delta = abs(after["height"] - before["height"])
            if delta > LAYOUT_REPORT_TOLERANCE:
                layout_deltas.append(
                    {
                        "root": root_label(before),
                        "id": before["id"],
                        "fallback": f"{before['width']:.0f}x{before['height']:.0f}",
                        "mounted": f"{after['width']:.0f}x{after['height']:.0f}",
                        "heightDelta": round(delta, 1),
                    }
                )

    return {
        "violations": violations,
        "layoutDeltas": sorted(layout_deltas, key=lambda item: -item["heightDelta"]),
        "counts": {
            "roots": len(early),
            "topLevel": len(early_top),
            "noop": sum(1 for root in early_top if root_label(root) in NOOP_ROOTS),
        },
        "states": observations,
    }


def main() -> int:
    """Run the matrix and report every contract violation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8299")
    parser.add_argument(
        "--only", default=None, help="Run pages whose name contains this text"
    )
    parser.add_argument(
        "--json", default=None, help="Write the full report to this path"
    )
    parser.add_argument("--settle-ms", type=int, default=1500)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    pages = [(name, path) for name, path in PAGES if not args.only or args.only in name]
    if not pages:
        print(f"No pages match --only {args.only!r}", file=sys.stderr)
        return 2

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            extra_http_headers={"X-Real-IP": "127.0.0.1"},
        )
        login(context, args.base)
        cookies = context.cookies()
        origin = urlsplit(args.base).netloc
        report = {}
        failed = False
        for name, path in pages:
            try:
                result = check_page(
                    browser, args.base, origin, cookies, path, args.settle_ms
                )
            except Exception as error:
                failed = True
                print(f"FAIL {name}: {error}")
                report[name] = {"violations": [str(error)]}
                continue
            report[name] = result
            counts = result["counts"]
            status = "FAIL" if result["violations"] else "ok"
            print(
                f"{status:4} {name:28} roots={counts['roots']:2} "
                f"top-level={counts['topLevel']:2} no-op={counts['noop']} "
                f"layout-deltas={len(result['layoutDeltas'])}"
            )
            for violation in result["violations"]:
                print(f"      - {violation}")
            for delta in result["layoutDeltas"][:3]:
                print(
                    f"      layout {delta['root']}: {delta['fallback']} -> "
                    f"{delta['mounted']} ({delta['heightDelta']}px)"
                )
            if result["violations"]:
                failed = True
        context.close()
        browser.close()

    if args.json:
        with Path(args.json).open("w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=1)
        print(f"Report written to {args.json}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
