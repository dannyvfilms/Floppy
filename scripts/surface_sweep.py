#!/usr/bin/env python3
"""Time every user-facing GET surface cold and warm, with Server-Timing figures.

Standard library only. Point it at a server that either auto-logs-in a user
(FLOPPY_AUTO_LOGIN_USERNAME, as scripts/bench.sh does) or at one you can sign in
to with FLOPPY_SWEEP_USER / FLOPPY_SWEEP_PASSWORD (read from the environment,
never from arguments).

  scripts/surface_sweep.py --base http://localhost:8001 \
      --flush-cmd "redis-cli -n 3 flushdb" --label before

Per route: first request after the flush (cold), then --runs warm requests.
Reports status, wall seconds, and the server's own total/db/queries from the
Server-Timing header (queries needs a build that emits it). Dynamic routes
(details, list, person, ...) are discovered from links on the listing pages, so
the sweep follows whatever data the target has. Writes a TSV beside the repo's
bench output ($BENCH_DIR, default ${TMPDIR:-/tmp}/yamtrack-bench).

  --only SUBSTR   run only routes whose name or path contains SUBSTR (repeatable)
  --fragments     include HTMX fragment endpoints discovered from the pages
"""

import argparse
import http.cookiejar
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

STATIC_ROUTES = [
    ("home", "/"),
    ("home_rest", "/home/rest/"),
    ("discover", "/discover"),
    ("statistics", "/statistics"),
    ("history", "/history"),
    ("history_prev_month", "/history?year=2026&m=9"),
    ("history_old_month", "/history?year=2023&m=6"),
    ("history_movies", "/history?media_type=movie"),
    ("history_tv", "/history?media_type=tv"),
    ("history_range", "/history?start-date=2026-01-01&end-date=2026-03-31"),
    ("history_anniversary", "/history?month=10&day=26"),
    ("calendar", "/calendar"),
    ("lists", "/lists"),
    ("tags", "/tags"),
    ("collection", "/collection/"),
    ("search_tv", "/search?media_type=tv&q=the"),
    ("search_suggest", "/search/suggestions?q=the"),
    ("settings_account", "/settings/account"),
    ("settings_notifications", "/settings/notifications"),
    ("settings_ui", "/settings/ui"),
    ("settings_appearance", "/settings/appearance"),
    ("settings_cards", "/settings/cards"),
    ("settings_sidebar", "/settings/sidebar"),
    ("settings_home_screen", "/settings/home-screen"),
    ("settings_preferences", "/settings/preferences"),
    ("settings_integrations", "/settings/integrations"),
    ("settings_rss", "/settings/rss"),
    ("settings_metadata", "/settings/metadata"),
    ("settings_import", "/settings/import"),
    ("settings_import_activity", "/settings/import/activity"),
    ("settings_export", "/settings/export"),
    ("settings_advanced", "/settings/advanced"),
    ("settings_about", "/settings/about"),
    ("settings_whats_new", "/settings/about/whats-new"),
    ("health", "/health/"),
    ("ping", "/ping/"),
    ("api_health", "/api/v1/health"),
    ("api_info", "/api/v1/info"),
]
MEDIA_TYPES = ["tv", "movie", "anime", "season", "game", "book", "manga", "music", "podcast"]
# (route name, regex over the HTML of a listing page, page to scrape)
DISCOVER = [
    ("details_tv", r'href="(/details/[^"/]+/tv/[^"/]+/[^"/]+)"', "/medialist/tv"),
    ("details_movie", r'href="(/details/[^"/]+/movie/[^"/]+/[^"/]+)"', "/medialist/movie"),
    ("details_game", r'href="(/details/[^"/]+/game/[^"/]+/[^"/]+)"', "/medialist/game"),
    ("season", r'href="(/details/[^"/]+/tv/[^"/]+/[^"/]+/season/\d+)"', None),
    ("list_detail", r'href="(/list/[^"/?]+)"', "/lists"),
    ("person", r'href="(/person/[^"]+)"', None),
    ("music_artist", r'href="(/music/artist/\d+/)"', "/medialist/music"),
    ("podcast_show", r'href="(/podcast/show/\d+/)"', "/medialist/podcast"),
]
HX_RE = re.compile(r'hx-get="(/[^"]+)"')
TIMING_RE = re.compile(r'(\w+);(?:dur=([\d.]+)|desc="?(\d+)"?)')


args_timeout = 120


class Client:
    def __init__(self, base):
        self.base = base.rstrip("/")
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self.jar = jar

    def get(self, path):
        url = self.base + path
        started = time.perf_counter()
        try:
            with self.opener.open(
                urllib.request.Request(url, headers={"HX-Request": "true"} if "fragment" in path else {}),
                timeout=args_timeout,
            ) as response:
                body = response.read()
                status = response.status
                timing = response.headers.get("Server-Timing", "")
                final = response.geturl()
        except urllib.error.HTTPError as error:
            body, status, timing, final = error.read(), error.code, "", url
        except (TimeoutError, OSError) as error:
            body, status, timing, final = b"", f"ERR:{type(error).__name__}", "", url
        wall = time.perf_counter() - started
        return status, wall, timing, body.decode("utf-8", "replace"), final

    def login(self, user, password):
        _, _, _, html, _ = self.get("/accounts/login/")
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
        data = urllib.parse.urlencode(
            {"login": user, "password": password, "csrfmiddlewaretoken": token.group(1) if token else ""}
        ).encode()
        request = urllib.request.Request(
            self.base + "/accounts/login/", data=data, headers={"Referer": self.base + "/accounts/login/"}
        )
        self.opener.open(request, timeout=60).read()


def parse_timing(header):
    values = {}
    for name, dur, desc in TIMING_RE.findall(header):
        values[name] = float(dur) if dur else int(desc)
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://localhost:8001")
    parser.add_argument("--runs", type=int, default=3, help="warm requests per route")
    parser.add_argument("--flush-cmd", help="shell command that empties the cache before each cold request")
    parser.add_argument("--label", default="sweep")
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--fragments", action="store_true")
    args = parser.parse_args()

    client = Client(args.base)
    user, password = os.environ.get("FLOPPY_SWEEP_USER"), os.environ.get("FLOPPY_SWEEP_PASSWORD")
    if user and password:
        client.login(user, password)

    routes = list(STATIC_ROUTES)
    routes += [(f"medialist_{kind}", f"/medialist/{kind}") for kind in MEDIA_TYPES]
    pages = {}
    for name, pattern, source in DISCOVER:
        sources = [source] if source else ["/medialist/tv", "/statistics", "/"]
        for src in sources:
            if src not in pages:
                pages[src] = client.get(src)[3]
            match = re.search(pattern, pages[src])
            if match:
                routes.append((name, match.group(1)))
                break
    tv = next((p for n, p in routes if n == "details_tv"), None)
    if tv:
        parts = tv.split("/")  # /details/<source>/tv/<media_id>/<title>
        routes.append(
            ("history_sessions", f"/history/sessions?media_type=tv&source={parts[2]}&media_id={parts[4]}&season_number=1")
        )
    if args.fragments:
        seen = {path for _, path in routes}
        families = {}  # one sample per URL shape
        for page in ("/", "/history", "/statistics", "/lists"):
            html = pages.get(page) or client.get(page)[3]
            for path in sorted(set(HX_RE.findall(html))):
                family = re.sub(r"/[^/]*\d[^/]*", "/N", path)
                if path not in seen and "{" not in path and family not in families:
                    families[family] = 1
                    seen.add(path)
                    routes.append((f"hx{path.rstrip('/').replace('/', '_')}", path))
    if args.only:
        routes = [r for r in routes if any(token in r[0] or token in r[1] for token in args.only)]

    out_dir = os.environ.get("BENCH_DIR") or os.path.join(os.environ.get("TMPDIR", "/tmp"), "yamtrack-bench")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"surface_{args.label}.tsv")
    header = "route\tpath\tstatus\tcold_s\tcold_db_ms\tcold_q\twarm_med_s\twarm_db_ms\twarm_q\tbytes"
    rows = [header]
    print(header)
    for name, path in routes:
        if args.flush_cmd:
            subprocess.run(args.flush_cmd, shell=True, check=False, stdout=subprocess.DEVNULL)
        status, cold, timing, body, final = client.get(path)
        cold_t = parse_timing(timing)
        warm, warm_t = [], {}
        for _ in range(args.runs):
            _, wall, timing, _, _ = client.get(path)
            warm.append(wall)
            warm_t = parse_timing(timing)
        row = "\t".join(
            str(v)
            for v in (
                name,
                path,
                status if "/accounts/login" not in final else "login",
                f"{cold:.3f}",
                f"{cold_t.get('db', 0):.0f}",
                cold_t.get("queries", ""),
                f"{statistics.median(warm):.3f}",
                f"{warm_t.get('db', 0):.0f}",
                warm_t.get("queries", ""),
                len(body),
            )
        )
        rows.append(row)
        print(row, flush=True)
    with open(out_path, "w") as handle:
        handle.write("\n".join(rows) + "\n")
    print(f"saved -> {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
