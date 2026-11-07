#!/usr/bin/env python3
# ruff: noqa: T201
r"""Measure a web surface and a native screenshot with the same vocabulary.

Web is the ground truth, so a styling fix should start by reading what the
browser computes and end by measuring the same control in a simulator
screenshot. This tool prints those numbers in points instead of asking anyone
to eyeball them.

Examples:
    python scripts/surface_metrics.py web --url http://localhost:8000/accounts/login \
        --theme dark --viewport 390x844 --selector input='input[name="login"]' \
        --selector button='button[type="submit"]' \
        --selector card='.max-w-md > div:last-child'

    python scripts/surface_metrics.py image --file /tmp/duo.png --scale 3 \
        --crop 0:1146 --color input=#39404b --color button=#4f46e5

``web`` prints the rectangle, font, padding, margin, radius, border, background
and colour for each selector. ``image`` prints the connected rectangles of each
exact colour in points, which is enough to compare control heights, widths,
radii and gaps between surfaces.
"""

import argparse
import json
import sys

HEX_LENGTH = 6

DEFAULT_SELECTORS = {
    "card": ".max-w-md > div:last-child",
    "title": ".text-center p",
    "input": 'input[name="login"]',
    "button": 'button[type="submit"]',
    "label": "label",
}


def web_metrics(args):
    """Print computed geometry and type for selectors on a web page."""
    from playwright.sync_api import sync_playwright

    width, _, height = args.viewport.partition("x")
    selectors = dict(DEFAULT_SELECTORS)
    selectors.update(parse_pairs(args.selector))
    script = """
    (selectors) => {
      const pick = el => {
        if (!el) return null;
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return {
          rect: { x: +r.x.toFixed(2), y: +r.y.toFixed(2), w: +r.width.toFixed(2), h: +r.height.toFixed(2) },
          fontSize: s.fontSize, fontWeight: s.fontWeight, lineHeight: s.lineHeight,
          padding: [s.paddingTop, s.paddingRight, s.paddingBottom, s.paddingLeft].join(' '),
          margin: [s.marginTop, s.marginRight, s.marginBottom, s.marginLeft].join(' '),
          radius: s.borderRadius, borderWidth: s.borderWidth, borderColor: s.borderColor,
          background: s.backgroundColor, color: s.color, gap: s.gap,
        };
      };
      return Object.fromEntries(Object.entries(selectors).map(([name, sel]) => [name, pick(document.querySelector(sel))]));
    }
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": int(width), "height": int(height)},
            device_scale_factor=args.scale,
            extra_http_headers={"X-Real-IP": "127.0.0.1"},
        )
        page = context.new_page()
        page.goto(args.url)
        page.wait_for_load_state("networkidle")
        if args.theme:
            page.evaluate("theme => { document.documentElement.className = theme; }", args.theme)
            page.wait_for_timeout(200)
        result = page.evaluate(script, selectors)
        if args.screenshot:
            page.screenshot(path=args.screenshot)
        browser.close()
    print(json.dumps(result, indent=2))


def image_metrics(args):
    """Print connected rectangles of exact colours in a screenshot, in points."""
    import numpy as np
    from PIL import Image
    from scipy import ndimage

    image = Image.open(args.file).convert("RGB")
    pixels = np.array(image)
    if args.crop:
        start, _, end = args.crop.partition(":")
        pixels = pixels[:, int(start):int(end) or None]
    result = {"file": args.file, "size": list(image.size), "scale": args.scale, "colors": {}}
    for name, value in parse_pairs(args.color).items():
        rgb = hex_to_rgb(value)
        mask = np.abs(pixels.astype(int) - np.array(rgb)).sum(axis=2) <= args.tolerance
        labels, count = ndimage.label(mask)
        regions = []
        for index in range(1, count + 1):
            ys, xs = np.where(labels == index)
            if len(xs) < args.min_pixels:
                continue
            regions.append({
                "x": round(xs.min() / args.scale, 2),
                "y": round(ys.min() / args.scale, 2),
                "w": round((xs.max() - xs.min() + 1) / args.scale, 2),
                "h": round((ys.max() - ys.min() + 1) / args.scale, 2),
                "pixels": len(xs),
            })
        regions.sort(key=lambda region: (region["y"], region["x"]))
        result["colors"][name] = regions
    print(json.dumps(result, indent=2))


def parse_pairs(values):
    """Turn repeated ``name=value`` arguments into a dictionary."""
    pairs = {}
    for value in values or []:
        name, _, rest = value.partition("=")
        if not name or not rest:
            message = f"expected name=value, got {value!r}"
            raise SystemExit(message)
        pairs[name] = rest
    return pairs


def hex_to_rgb(value):
    """Return an RGB tuple for a six-digit hex colour."""
    text = value.lstrip("#")
    if len(text) != HEX_LENGTH:
        message = f"expected a 6-digit hex colour, got {value!r}"
        raise SystemExit(message)
    return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))


def main():
    """Parse arguments and run the requested mode."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    web = subparsers.add_parser("web", help="print computed styles for a web URL")
    web.add_argument("--url", required=True)
    web.add_argument("--viewport", default="390x844")
    web.add_argument("--scale", type=int, default=3)
    web.add_argument("--theme", help="override the html class, e.g. dark")
    web.add_argument("--selector", action="append", help="name=CSS selector; repeatable")
    web.add_argument("--screenshot")
    web.set_defaults(func=web_metrics)

    image = subparsers.add_parser("image", help="measure colour rectangles in a screenshot")
    image.add_argument("--file", required=True)
    image.add_argument("--scale", type=int, default=3)
    image.add_argument("--crop", help="pixel range x0:x1, for example 0:1146")
    image.add_argument("--tolerance", type=int, default=6)
    image.add_argument("--min-pixels", type=int, default=500)
    image.add_argument("--color", action="append", help="name=#rrggbb; repeatable")
    image.set_defaults(func=image_metrics)

    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
