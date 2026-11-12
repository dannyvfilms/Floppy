# A developer CLI, not app code: printing a report is the point.
# ruff: noqa: T201, S603, S607, S310, DTZ005, PLR0912, PLR0915, C901, E501
"""Compare the web app against a released baseline, page by page.

Runs two Floppy servers (a baseline checkout such as the v26.10.29 tag and the
current tree) against copies of the same database, then drives headless
Chromium through every discoverable page at desktop and phone width.

    # 1. find the pages (static routes plus links crawled from the app)
    python scripts/web_parity_audit.py discover --main http://localhost:8402 \
        --user NAME --password-env AUDIT_PASSWORD --out audit/routes.json

    # 2. capture + compare every page on both servers
    python scripts/web_parity_audit.py compare --base http://localhost:8401 \
        --main http://localhost:8402 --user NAME --password-env AUDIT_PASSWORD \
        --routes audit/routes.json --out audit

Per page and viewport it records: HTTP status, console errors, failed requests,
horizontal overflow, broken images, every visible text node with its computed
type style (size, weight, colour, family, line height, position), every control
with its box and colours, then diffs the two sides:

* ``pixel``    share of pixels that differ in the shared top of the page
* ``missing``  copy the baseline shows that the current page does not (and
               ``added`` for the reverse)
* ``style``    the same text drawn with a different size/weight/colour/font
* ``move``     the same text sitting somewhere else (box offset > 12px)
* ``height``   full page height change

Outputs ``summary.json`` and a self-contained ``report.html`` (side by side +
diff images) under ``--out``. Standard library, Playwright, Pillow and numpy.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

import numpy as np
from PIL import Image, ImageChops
from playwright.async_api import async_playwright

VIEWPORTS = {"desktop": {"width": 1440, "height": 900}, "phone": {"width": 390, "height": 844}}

# Routes that mutate state, leave the app, or are not pages.
SKIP = re.compile(
    r"(/logout|/accounts/(logout|password|email|social)|/admin|/static/|/media/|/api/|/delete|/remove|"
    r"/export|/download|/backup|/restore|/import/run|/sync|/refresh|/mark|/bulk|/health|/ping|\.(png|jpe?g|webp|svg|ico|xml|txt|json|css|js)$)",
)

SEEDS = [
    "/", "/discover", "/statistics", "/history", "/calendar", "/lists", "/tags", "/collection/",
    "/search?media_type=tv&q=the", "/search?media_type=movie&q=the", "/search?media_type=book&q=the",
    "/medialist/tv", "/medialist/movie", "/medialist/anime", "/medialist/game", "/medialist/book",
    "/medialist/manga", "/medialist/comic", "/medialist/music", "/medialist/podcast", "/medialist/boardgame",
    "/settings/account", "/settings/notifications", "/settings/ui", "/settings/appearance", "/settings/cards",
    "/settings/sidebar", "/settings/home-screen", "/settings/preferences", "/settings/integrations",
    "/settings/rss", "/settings/metadata", "/settings/import", "/settings/import/activity", "/settings/export",
    "/settings/advanced", "/settings/about", "/settings/about/whats-new", "/settings/providers",
    "/settings/users", "/settings/data", "/settings/access", "/settings/activity",
    "/notifications", "/create", "/accounts/login/",
]

# JS run inside each page: collects the facts the comparison needs.
CAPTURE_JS = r"""
() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const vis = (el, cs, r) => cs.display !== 'none' && cs.visibility !== 'hidden' && +cs.opacity > 0.02 && r.width > 0 && r.height > 0;
  const sx = window.scrollX, sy = window.scrollY;
  const box = (r) => [Math.round(r.left + sx), Math.round(r.top + sy), Math.round(r.width), Math.round(r.height)];
  const texts = [], controls = [];
  const all = document.body.querySelectorAll('*');
  for (const el of all) {
    if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'SVG', 'PATH'].includes(el.tagName.toUpperCase())) continue;
    const cs = getComputedStyle(el), r = el.getBoundingClientRect();
    if (!vis(el, cs, r)) continue;
    let own = '';
    for (const n of el.childNodes) if (n.nodeType === 3) own += n.nodeValue + ' ';
    own = norm(own);
    if (own.length > 0) {
      texts.push({
        t: own.slice(0, 90), tag: el.tagName.toLowerCase(), box: box(r),
        fs: cs.fontSize, fw: cs.fontWeight, color: cs.color, ff: cs.fontFamily.split(',')[0].replace(/["']/g, '').trim(),
        lh: cs.lineHeight, ls: cs.letterSpacing, tt: cs.textTransform,
      });
    }
    const isCtl = el.matches('a[href],button,input,select,textarea,summary,[role=button],[role=tab],[role=switch],[role=checkbox]');
    if (isCtl) {
      controls.push({
        k: el.tagName.toLowerCase() + (el.type ? ':' + el.type : ''),
        label: norm(el.innerText || el.value || el.getAttribute('aria-label') || el.title || el.placeholder || '').slice(0, 60),
        href: el.getAttribute('href') || '', box: box(r),
        bg: cs.backgroundColor, color: cs.color, radius: cs.borderTopLeftRadius,
        border: cs.borderTopWidth + ' ' + cs.borderTopStyle + ' ' + cs.borderTopColor,
        pad: cs.padding, fs: cs.fontSize, fw: cs.fontWeight, disabled: !!el.disabled,
      });
    }
  }
  const imgs = [...document.images].filter((i) => { const r = i.getBoundingClientRect(); return r.width > 0 && getComputedStyle(i).display !== 'none'; });
  const de = document.documentElement;
  return {
    title: document.title,
    h1: norm((document.querySelector('h1') || {}).innerText),
    texts, controls,
    brokenImages: imgs.filter((i) => i.complete && i.naturalWidth === 0).map((i) => i.currentSrc || i.src).slice(0, 10),
    imageCount: imgs.length,
    overflowX: Math.max(0, de.scrollWidth - de.clientWidth),
    docHeight: Math.max(de.scrollHeight, document.body.scrollHeight),
    islands: [...document.querySelectorAll('[data-props-id]')].map((e) => ({
      id: e.getAttribute('data-props-id'), mounted: e.hasAttribute('data-react-mounted'), hidden: getComputedStyle(e).visibility === 'hidden',
    })),
    bodyBg: getComputedStyle(document.body).backgroundColor,
    bodyFont: getComputedStyle(document.body).fontFamily.split(',')[0].replace(/["']/g, '').trim(),
  };
}
"""


def shape(path: str) -> str:
    """Collapse ids so '/details/tmdb/tv/123/x' and '/details/tmdb/tv/456/y' share a shape."""
    parts = urlparse(path).path.split("/")
    out = []
    for part in parts:
        if re.fullmatch(r"\d+", part) or re.fullmatch(r"[0-9a-f-]{8,}", part):
            out.append("N")
        elif part.startswith("tt") and part[2:].isdigit():
            out.append("N")
        else:
            out.append(part)
    # details pages carry a title slug as the last segment
    if len(out) > 2 and out[1] == "details" and out[-1] not in {"N"} and not out[-1].isdigit():
        out[-1] = "slug"
    return "/".join(out)


def _placeholder(url: str) -> bytes:
    """A deterministic poster-shaped PNG per URL, so off-origin artwork looks the same on both sides."""
    h = sum(ord(c) * (i + 7) for i, c in enumerate(url)) % 360
    img = Image.new("RGB", (300, 450))
    px = img.load()
    for y in range(450):
        for x in range(0, 300):
            v = 0.35 + 0.4 * (y / 450)
            px[x, y] = (int(40 + 120 * v * ((h % 3) == 0) + 50 * (x / 300)), int(40 + 120 * v * ((h % 3) == 1) + 40), int(60 + 120 * v * ((h % 3) == 2) + 30))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


async def stub_external(ctx, origin_host: str) -> None:
    """Off-origin requests cannot be reached from the audit box; answer images locally, drop the rest."""

    async def handler(route):
        req = route.request
        if urlparse(req.url).netloc == origin_host or req.url.startswith(("data:", "blob:")):
            await route.continue_()
        elif req.resource_type == "image":
            await route.fulfill(status=200, content_type="image/png", body=_placeholder(req.url))
        else:
            await route.abort()

    await ctx.route("**/*", handler)


async def login(ctx, base: str, user: str, password: str) -> None:
    page = await ctx.new_page()
    await page.goto(base + "/accounts/login/", wait_until="load")
    await page.fill("#id_login", user)
    await page.fill("#id_password", password)
    await page.click('button[type="submit"]')
    await page.wait_for_load_state("load")
    await page.close()


async def settle(page, extra_ms: int = 1200, idle_ms: int = 9000) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=idle_ms)
    except Exception:  # noqa: BLE001
        pass
    await page.wait_for_timeout(extra_ms)
    try:
        await page.wait_for_function(
            "() => ![...document.querySelectorAll('[data-props-id]')].some(e => !e.hasAttribute('data-react-mounted') && getComputedStyle(e).display !== 'none')",
            timeout=5000,
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        await page.wait_for_function(
            "() => [...document.images].filter(i => i.getBoundingClientRect().width>0).every(i => i.complete)", timeout=3500
        )
    except Exception:  # noqa: BLE001
        pass
    await page.wait_for_timeout(300)


async def discover(args) -> None:
    pw = await async_playwright().start()
    browser = await pw.chromium.launch()
    ctx = await browser.new_context(viewport=VIEWPORTS["desktop"])
    await stub_external(ctx, urlparse(args.main).netloc)
    await login(ctx, args.main, args.user, os.environ[args.password_env])
    seen_shapes: dict[str, list[str]] = {}
    queue = list(SEEDS)
    visited: set[str] = set()
    per_shape = args.per_shape
    host = urlparse(args.main).netloc
    page = await ctx.new_page()
    while queue and len(visited) < args.max_pages:
        path = queue.pop(0)
        if path in visited:
            continue
        visited.add(path)
        try:
            resp = await page.goto(args.main + path, wait_until="load")
            await settle(page, 400, 2500)
        except Exception as exc:  # noqa: BLE001
            print("discover fail", path, exc)
            continue
        status = resp.status if resp else 0
        final = urlparse(page.url).path + (("?" + urlparse(page.url).query) if urlparse(page.url).query else "")
        key = shape(path)
        bucket = seen_shapes.setdefault(key, [])
        if status < 400 and len(bucket) < per_shape and path not in bucket:
            bucket.append(path)
        hrefs = await page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
        for href in hrefs:
            if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
                continue
            url = urldefrag(urljoin(args.main + path, href))[0]
            p = urlparse(url)
            if p.netloc != host or SKIP.search(p.path):
                continue
            rel = p.path + (("?" + p.query) if p.query else "")
            k = shape(rel)
            # query-string variants of the same path are separate shapes only for known list filters
            if p.query and not re.search(r"(sort|status|layout|view|tab|year|media_type|filter)=", p.query):
                continue
            if len(seen_shapes.get(k, [])) + sum(1 for q in queue if shape(q) == k) < per_shape and rel not in visited:
                queue.append(rel)
        print(f"[{len(visited):3}] {status} {path}  (final {final})")
    routes = sorted({p for b in seen_shapes.values() for p in b})
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(routes, indent=1))
    print(f"{len(routes)} routes in {len(seen_shapes)} shapes -> {args.out}")
    await browser.close()
    await pw.stop()


async def capture_one(ctx, base: str, path: str, vp: str, outdir: Path, tag: str, idx: int) -> dict:
    page = await ctx.new_page()
    errors, failed, pageerrors = [], [], []
    host = urlparse(base).netloc
    page.on("console", lambda m: errors.append(m.text[:300]) if m.type == "error" else None)
    page.on("pageerror", lambda e: pageerrors.append(str(e)[:300]))
    page.on("requestfailed", lambda r: failed.append(f"{r.url[:120]} {r.failure}") if urlparse(r.url).netloc == host else None)
    page.on("response", lambda r: failed.append(f"{r.status} {r.url[:120]}") if r.status >= 400 and urlparse(r.url).netloc == host and "favicon" not in r.url else None)
    rec: dict = {"path": path, "vp": vp, "side": tag}
    t0 = time.time()
    try:
        resp = await page.goto(base + path, wait_until="load", timeout=60000)
        rec["status"] = resp.status if resp else 0
        rec["final"] = urlparse(page.url).path
        await settle(page)
        rec["load_s"] = round(time.time() - t0, 1)
        rec["data"] = await page.evaluate(CAPTURE_JS)
        shot = outdir / "shots" / f"{idx:03d}-{vp}-{tag}.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(shot), full_page=True, animations="disabled", timeout=45000)
        rec["shot"] = str(shot.relative_to(outdir))
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    rec["console"] = errors[:8]
    rec["pageerrors"] = pageerrors[:5]
    rec["failed"] = failed[:8]
    await page.close()
    return rec


def _num(v: str) -> float:
    m = re.search(r"-?\d+(\.\d+)?", v or "")
    return float(m.group()) if m else 0.0


def pixel_diff(a_path: Path, b_path: Path, out_path: Path) -> tuple[float, int, int]:
    a, b = Image.open(a_path).convert("RGB"), Image.open(b_path).convert("RGB")
    h = max(a.height, b.height)
    h_cmp = min(a.height, b.height)
    w = max(a.width, b.width)
    ca, cb = Image.new("RGB", (w, h), "white"), Image.new("RGB", (w, h), "white")
    ca.paste(a, (0, 0))
    cb.paste(b, (0, 0))
    diff = np.asarray(ImageChops.difference(ca, cb).convert("L"))
    region = diff[:h_cmp]
    pct = float((region > 24).mean() * 100) if region.size else 100.0
    # composite: baseline | current | diff (heat), downscaled and capped for the report
    heat = np.zeros((h, w, 3), dtype=np.uint8)
    heat[..., 0] = np.clip(diff.astype(int) * 4, 0, 255)
    heat[..., 1] = (np.asarray(ca.convert("L")) * 0.25).astype(np.uint8)
    heat[..., 2] = (np.asarray(ca.convert("L")) * 0.25).astype(np.uint8)
    comp = Image.new("RGB", (w * 3 + 40, h), "#888")
    comp.paste(ca, (0, 0))
    comp.paste(cb, (w + 20, 0))
    comp.paste(Image.fromarray(heat), (2 * w + 40, 0))
    max_h = 6000
    if comp.height > max_h:
        comp = comp.crop((0, 0, comp.width, max_h))
    scale = 1800 / comp.width if comp.width > 1800 else 1
    if scale < 1:
        comp = comp.resize((int(comp.width * scale), int(comp.height * scale)))
    comp.save(out_path, optimize=True)
    return pct, a.height, b.height


def compare_data(a: dict, b: dict) -> dict:
    """a = baseline, b = current."""
    res = {"missing": [], "added": [], "style": [], "move": [], "controls_missing": [], "controls_added": []}

    def index(items, key):
        d: dict[str, list] = {}
        for it in items:
            d.setdefault(key(it), []).append(it)
        return d

    ta, tb = index(a["texts"], lambda x: x["t"].lower()), index(b["texts"], lambda x: x["t"].lower())
    for k, items in ta.items():
        if k not in tb:
            res["missing"].append(items[0]["t"])
            continue
        other = tb[k]
        for i, it in enumerate(items[: len(other)]):
            o = other[i]
            diffs = []
            if abs(_num(it["fs"]) - _num(o["fs"])) >= 0.75:
                diffs.append(f"size {it['fs']}→{o['fs']}")
            if it["fw"] != o["fw"] and abs(_num(it["fw"]) - _num(o["fw"])) >= 100:
                diffs.append(f"weight {it['fw']}→{o['fw']}")
            if it["color"] != o["color"]:
                diffs.append(f"color {it['color']}→{o['color']}")
            if it["ff"].lower() != o["ff"].lower():
                diffs.append(f"font {it['ff']}→{o['ff']}")
            if it["tt"] != o["tt"]:
                diffs.append(f"transform {it['tt']}→{o['tt']}")
            if diffs:
                res["style"].append({"t": it["t"], "d": diffs})
            dx, dy = o["box"][0] - it["box"][0], o["box"][1] - it["box"][1]
            if abs(dx) > 12 or abs(dy) > 12:
                res["move"].append({"t": it["t"], "dx": dx, "dy": dy})
    for k, items in tb.items():
        if k not in ta:
            res["added"].append(items[0]["t"])

    def ckey(c):
        return (c["k"], c["label"].lower(), c["href"].split("?")[0])

    ca, cb = index(a["controls"], ckey), index(b["controls"], ckey)
    for k, items in ca.items():
        if k not in cb:
            res["controls_missing"].append(f"{k[0]} '{items[0]['label']}' {k[2]}")
    for k, items in cb.items():
        if k not in ca:
            res["controls_added"].append(f"{k[0]} '{items[0]['label']}' {k[2]}")
    return res


async def compare(args) -> None:
    routes = json.loads(Path(args.routes).read_text())
    if args.only:
        routes = [r for r in routes if any(s in r for s in args.only)]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    password = os.environ[args.password_env]
    pw = await async_playwright().start()
    browser = await pw.chromium.launch()
    sides = {"base": args.base, "main": args.main}
    ctxs: dict[tuple[str, str], object] = {}
    for tag, url in sides.items():
        for vp, size in VIEWPORTS.items():
            ctx = await browser.new_context(viewport=size, device_scale_factor=1, has_touch=vp == "phone", is_mobile=False)
            await stub_external(ctx, urlparse(url).netloc)
            await login(ctx, url, args.user, password)
            ctxs[(tag, vp)] = ctx
    sem = asyncio.Semaphore(args.parallel)
    results: list[dict] = []

    async def job(idx: int, path: str, vp: str) -> None:
        async with sem:
            a, b = await asyncio.gather(
                capture_one(ctxs[("base", vp)], args.base, path, vp, out, "base", idx),
                capture_one(ctxs[("main", vp)], args.main, path, vp, out, "main", idx),
            )
        row = {"idx": idx, "path": path, "vp": vp, "base": {k: v for k, v in a.items() if k != "data"}, "main": {k: v for k, v in b.items() if k != "data"}}
        if "data" in a and "data" in b:
            row["cmp"] = compare_data(a["data"], b["data"])
            row["facts"] = {
                "base": {k: a["data"][k] for k in ("title", "h1", "brokenImages", "overflowX", "docHeight", "imageCount", "islands", "bodyBg", "bodyFont")},
                "main": {k: b["data"][k] for k in ("title", "h1", "brokenImages", "overflowX", "docHeight", "imageCount", "islands", "bodyBg", "bodyFont")},
            }
            try:
                pct, ha, hb = pixel_diff(out / a["shot"], out / b["shot"], out / "shots" / f"{idx:03d}-{vp}-diff.png")
                row["pixel"] = round(pct, 2)
                row["height"] = [ha, hb]
                row["diff_shot"] = f"shots/{idx:03d}-{vp}-diff.png"
            except Exception as exc:  # noqa: BLE001
                row["pixel_error"] = str(exc)
        results.append(row)
        print(f"{idx:3} {vp:7} {path[:60]:60} base={a.get('status')} main={b.get('status')} px={row.get('pixel')}", flush=True)

    jobs = [job(i, p, vp) for i, p in enumerate(routes) for vp in VIEWPORTS]
    await asyncio.gather(*jobs)
    results.sort(key=lambda r: (r["idx"], r["vp"]))
    (out / "summary.json").write_text(json.dumps(results, indent=1))
    write_report(out, results)
    await browser.close()
    await pw.stop()


# ---------------------------------------------------------------- actions sweep
# Never click anything that could leave the scratch database or call a provider.
DENY = re.compile(
    r"(theme|appearance|delete|remove|clear|reset|sync|import|export|download|connect|disconnect|test|send|push|pull|refresh|rescan|"
    r"scan|revoke|generate|logout|log out|sign out|restart|shutdown|upgrade|update now|backup|restore|merge|"
    r"purge|wipe|danger|unlink|cancel subscription|run now|start|stop|kill|retry|fetch|reload metadata|trakt|plex|"
    r"jellyfin|emby|kodi|seerr|stremio|nuvio|mal |anilist|simkl|listenbrainz|lastfm|letterboxd)",
    re.I,
)

OVERLAYS_JS = r"""
() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const out = [];
  for (const e of document.body.querySelectorAll('*')) {
    const cs = getComputedStyle(e);
    const dialogish = e.matches('[role=dialog],[role=menu],[role=listbox],dialog[open],[aria-modal=true],[popover]:popover-open');
    if (!(cs.position === 'fixed' || cs.position === 'absolute' || dialogish)) continue;
    if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity < 0.05) continue;
    const r = e.getBoundingClientRect();
    if (r.width < 90 || r.height < 40) continue;
    const t = norm(e.innerText).slice(0, 140);
    if (!t) continue;
    out.push({ key: t, tag: e.tagName.toLowerCase(), role: e.getAttribute('role') || '', box: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)], bg: cs.backgroundColor, radius: cs.borderTopLeftRadius, z: cs.zIndex });
  }
  return out;
}
"""

TRIGGERS_JS = r"""
() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const res = [];
  const els = document.querySelectorAll('button, [role=button], summary, a[hx-get], a[href="#"], a[data-modal], [aria-haspopup], [aria-expanded]');
  let n = 0;
  for (const el of els) {
    const cs = getComputedStyle(el), r = el.getBoundingClientRect();
    if (cs.display === 'none' || cs.visibility === 'hidden' || r.width < 8 || r.height < 8) continue;
    if (el.disabled || el.closest('[aria-hidden=true]')) continue;
    if (el.tagName === 'BUTTON' && el.type === 'submit' && el.form && !el.form.matches('[hx-get],[method=get]')) continue;
    const label = norm(el.getAttribute('aria-label') || el.innerText || el.title || el.getAttribute('data-testid') || '').slice(0, 50);
    el.setAttribute('data-audit-trigger', String(n));
    res.push({ n: n++, label, tag: el.tagName.toLowerCase(), hx: el.getAttribute('hx-get') || el.getAttribute('hx-post') || '', href: el.getAttribute('href') || '', box: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)] });
  }
  return res;
}
"""


async def sweep_page(ctx, base: str, path: str, vp: str, outdir: Path, tag: str, idx: int, limit: int) -> list[dict]:
    """Open every safe trigger on the page once; record what appears. Returns one record per trigger."""
    page = await ctx.new_page()
    records: list[dict] = []
    try:
        await page.goto(base + path, wait_until="load", timeout=60000)
        await settle(page, 800, 3500)
        triggers = await page.evaluate(TRIGGERS_JS)
        seen: set[str] = set()
        todo = []
        for t in triggers:
            blob = f"{t['label']} {t['hx']} {t['href']}"
            key = f"{t['tag']}|{t['label'].lower()}"
            if DENY.search(blob) or key in seen or (not t["label"] and not t["hx"]):
                continue
            seen.add(key)
            todo.append(t)
        for t in todo[:limit]:
            rec = {"label": t["label"], "tag": t["tag"], "key": f"{t['tag']}|{t['label'].lower()}|{t['hx'].split('?')[0]}"}
            try:
                before = {o["key"] for o in await page.evaluate(OVERLAYS_JS)}
                loc = page.locator(f"[data-audit-trigger='{t['n']}']").first
                url0 = page.url
                await loc.scroll_into_view_if_needed(timeout=2000)
                await loc.click(timeout=2500, no_wait_after=True)
                await page.wait_for_timeout(700)
                if page.url != url0:
                    rec["navigated"] = urlparse(page.url).path
                    await page.goto(base + path, wait_until="load")
                    await settle(page, 500, 2500)
                    await page.evaluate(TRIGGERS_JS)
                else:
                    after = await page.evaluate(OVERLAYS_JS)
                    new = [o for o in after if o["key"] not in before]
                    rec["opened"] = new[:3]
                    if new:
                        shot = outdir / "action-shots" / f"{idx:03d}-{vp}-{tag}-{t['n']:02d}.png"
                        shot.parent.mkdir(parents=True, exist_ok=True)
                        await page.screenshot(path=str(shot), animations="disabled", timeout=15000)
                        rec["shot"] = str(shot.relative_to(outdir))
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(250)
                    # a click-outside-to-close pattern: click an empty corner too
                    await page.mouse.click(2, 2)
                    await page.wait_for_timeout(150)
            except Exception as exc:  # noqa: BLE001
                rec["error"] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:120]}"
            records.append(rec)
    except Exception as exc:  # noqa: BLE001
        records.append({"label": "(page)", "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
    await page.close()
    return records


async def actions(args) -> None:
    routes = json.loads(Path(args.routes).read_text())
    if args.only:
        routes = [r for r in routes if any(s in r for s in args.only)]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    password = os.environ[args.password_env]
    pw = await async_playwright().start()
    browser = await pw.chromium.launch()
    ctxs = {}
    for tag, url in {"base": args.base, "main": args.main}.items():
        for vp, size in VIEWPORTS.items():
            if vp not in args.viewports:
                continue
            ctx = await browser.new_context(viewport=size, device_scale_factor=1)
            await stub_external(ctx, urlparse(url).netloc)
            await login(ctx, url, args.user, password)
            ctxs[(tag, vp)] = ctx
    sem = asyncio.Semaphore(args.parallel)
    results = []

    async def job(idx: int, path: str, vp: str) -> None:
        async with sem:
            a, b = await asyncio.gather(
                sweep_page(ctxs[("base", vp)], args.base, path, vp, out, "base", idx, args.limit),
                sweep_page(ctxs[("main", vp)], args.main, path, vp, out, "main", idx, args.limit),
            )
        ak, bk = {r["key"]: r for r in a if "key" in r}, {r["key"]: r for r in b if "key" in r}
        findings = []
        for k, ra in ak.items():
            rb = bk.get(k)
            if rb is None:
                findings.append({"kind": "trigger-missing", "trigger": ra["label"] or k})
                continue
            oa, ob = bool(ra.get("opened")), bool(rb.get("opened"))
            if oa and not ob:
                findings.append({"kind": "opens-in-baseline-only", "trigger": ra["label"], "baseline": ra["opened"][0]["key"][:100], "err": rb.get("error")})
            elif ob and not oa:
                findings.append({"kind": "opens-in-current-only", "trigger": ra["label"], "current": rb["opened"][0]["key"][:100]})
            elif oa and ob:
                da, db = ra["opened"][0], rb["opened"][0]
                if da["key"][:60].lower() != db["key"][:60].lower():
                    findings.append({"kind": "different-content", "trigger": ra["label"], "baseline": da["key"][:100], "current": db["key"][:100]})
                dw, dh = abs(da["box"][2] - db["box"][2]), abs(da["box"][3] - db["box"][3])
                if dw > 24 or dh > 24 or da["radius"] != db["radius"] or da["bg"] != db["bg"]:
                    findings.append({"kind": "different-look", "trigger": ra["label"], "baseline": {k2: da[k2] for k2 in ("box", "bg", "radius")}, "current": {k2: db[k2] for k2 in ("box", "bg", "radius")}})
            if ra.get("navigated") != rb.get("navigated"):
                findings.append({"kind": "different-navigation", "trigger": ra["label"], "baseline": ra.get("navigated"), "current": rb.get("navigated")})
            if rb.get("error") and not ra.get("error"):
                findings.append({"kind": "click-error-current-only", "trigger": ra["label"], "err": rb["error"]})
            if ra.get("shot") and rb.get("shot"):
                pct, _, _ = pixel_diff(out / ra["shot"], out / rb["shot"], out / "action-shots" / f"{idx:03d}-{vp}-{abs(hash(k)) % 10**6}-diff.png")
                if pct > 3:
                    findings.append({"kind": "pixel", "trigger": ra["label"], "pct": round(pct, 1), "diff": f"action-shots/{idx:03d}-{vp}-{abs(hash(k)) % 10**6}-diff.png"})
        for k, rb in bk.items():
            if k not in ak and rb.get("opened"):
                findings.append({"kind": "trigger-added-opens", "trigger": rb["label"]})
        results.append({"idx": idx, "path": path, "vp": vp, "baseline_triggers": len(ak), "current_triggers": len(bk), "findings": findings})
        print(f"{idx:3} {vp:7} {path[:55]:55} triggers {len(ak)}/{len(bk)} findings {len(findings)}", flush=True)

    await asyncio.gather(*[job(i, p, vp) for i, p in enumerate(routes) for vp in VIEWPORTS if vp in args.viewports])
    results.sort(key=lambda r: (r["idx"], r["vp"]))
    (out / "actions.json").write_text(json.dumps(results, indent=1))
    await browser.close()
    await pw.stop()


def write_report(out: Path, results: list[dict]) -> None:
    def score(r):
        c = r.get("cmp", {})
        return (r.get("pixel") or 0) + 5 * len(c.get("missing", [])) + 2 * len(c.get("style", []))

    rows = sorted(results, key=score, reverse=True)
    html = ["<meta charset=utf-8><title>Web parity audit</title><style>body{font:14px system-ui;margin:24px;max-width:1500px}code{background:#eee;padding:1px 4px}details{border:1px solid #ddd;margin:6px 0;padding:6px 10px;border-radius:6px}summary{cursor:pointer}img{max-width:100%}.bad{color:#b00020}.ok{color:#1b7f3b}</style><h1>Web parity audit</h1>"]
    for r in rows:
        c = r.get("cmp", {})
        html.append(f"<details><summary><b>{r['path']}</b> [{r['vp']}] pixel {r.get('pixel')}% · missing {len(c.get('missing', []))} · style {len(c.get('style', []))} · status {r['base'].get('status')}/{r['main'].get('status')}</summary>")
        for k in ("missing", "added", "controls_missing", "controls_added", "style", "move"):
            if c.get(k):
                html.append(f"<p><b>{k}</b> ({len(c[k])})</p><ul>" + "".join(f"<li><code>{json.dumps(x)[:200]}</code></li>" for x in c[k][:15]) + "</ul>")
        if r.get("diff_shot"):
            data = base64.b64encode((out / r["diff_shot"]).read_bytes()).decode()
            html.append(f"<img src='data:image/png;base64,{data}'>")
        html.append("</details>")
    (out / "report.html").write_text("".join(html))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("discover", "compare", "actions"):
        s = sub.add_parser(name)
        s.add_argument("--main", required=True)
        s.add_argument("--user", required=True)
        s.add_argument("--password-env", default="AUDIT_PASSWORD")
        s.add_argument("--out", required=True)
        if name == "discover":
            s.add_argument("--per-shape", type=int, default=2)
            s.add_argument("--max-pages", type=int, default=160)
        else:
            s.add_argument("--base", required=True)
            s.add_argument("--routes", required=True)
            s.add_argument("--only", action="append")
            s.add_argument("--parallel", type=int, default=3)
            s.add_argument("--limit", type=int, default=30, help="actions: max triggers per page")
            s.add_argument("--viewports", nargs="+", default=["desktop", "phone"])
    args = p.parse_args()
    asyncio.run({"discover": discover, "compare": compare, "actions": actions}[args.cmd](args))


if __name__ == "__main__":
    sys.exit(main())
