"""Draw a list's tier board as a PNG, for the Tiers view's Export image button.

This runs on the server, not in the browser: covers come from provider hosts
that do not allow a page to read their pixels, so a canvas could not save them.
"""

import io
import textwrap
import time

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app import image_cache
from lists.tiers import ink_for, resolve_tiers

EXPORT_LIMIT = 300
FETCH_SECONDS = 20  # after this, covers not already cached become title tiles

WIDTH = 1200
PAD = 12
GAP = 6
LABEL_W = 120
TILE_W = 100
TILE_H = 150
MIN_ROW_H = 76
HEADER_H = 64
RADIUS = 6
LABEL_FONT = 30
MIN_LABEL_FONT = 12

BACKGROUND = (24, 26, 30)
ROW = (43, 46, 51)
TILE = (70, 74, 82)
TEXT = (243, 244, 246)


def _tile_mask():
    mask = Image.new("L", (TILE_W, TILE_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, TILE_W - 1, TILE_H - 1), RADIUS, fill=255
    )
    return mask


def _font(size):
    return ImageFont.load_default(size=size)


def _hex(color):
    return tuple(int(color[i : i + 2], 16) for i in (1, 3, 5))


def _cover(url, deadline):
    """Return the cover as a tile-sized image, or None when it is not available."""
    data = image_cache.cover_bytes(url, fetch=time.monotonic() < deadline)
    if data is None:
        return None
    try:
        with Image.open(io.BytesIO(data)) as source:
            return ImageOps.fit(source.convert("RGB"), (TILE_W, TILE_H))
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def _title_tile(title):
    tile = Image.new("RGB", (TILE_W, TILE_H), TILE)
    lines = textwrap.wrap(title or "", 11)[:6]
    ImageDraw.Draw(tile).multiline_text(
        (TILE_W / 2, TILE_H / 2),
        "\n".join(lines),
        font=_font(13),
        fill=TEXT,
        anchor="mm",
        align="center",
    )
    return tile


def _label(draw, box, text, color):
    """Centre a tier name in its coloured cell, shrinking it to fit."""
    left, top, right, bottom = box
    draw.rounded_rectangle(box, RADIUS, fill=_hex(color))
    size = LABEL_FONT
    font = _font(size)
    while (
        size > MIN_LABEL_FONT and draw.textlength(text, font=font) > right - left - 16
    ):
        size -= 2
        font = _font(size)
    draw.text(
        ((left + right) / 2, (top + bottom) / 2),
        text,
        font=font,
        fill=_hex(ink_for(color)),
        anchor="mm",
    )


def render_board(custom_list):
    """Return the board as PNG bytes: each tier, then the unranked items."""
    from app.models import Item
    from lists.models import CustomListItem

    groups = [
        (tier["name"], tier["color"], tier["id"]) for tier in resolve_tiers(custom_list)
    ]
    rank = {tier_id: index for index, (_, _, tier_id) in enumerate(groups)}
    # The same cut as the board: tier order, then place in the list, before the
    # limit, so a long list shows the same items on screen and in the picture.
    memberships = sorted(
        CustomListItem.objects.filter(custom_list=custom_list)
        .order_by("date_added", "id")
        .values_list("item_id", "tier"),
        key=lambda membership: rank.get(membership[1], len(rank)),
    )[:EXPORT_LIMIT]
    items = Item.objects.in_bulk([item_id for item_id, _ in memberships])
    by_tier = {tier_id: [] for _, _, tier_id in groups}
    unranked = []
    for item_id, tier in memberships:
        (by_tier[tier] if tier in rank else unranked).append(items[item_id])
    layout = [(name, color, by_tier[tier_id]) for name, color, tier_id in groups]
    if unranked:
        layout.append(("Unranked", "#aab2bd", unranked))

    per_line = max((WIDTH - 2 * PAD - LABEL_W - GAP) // (TILE_W + GAP), 1)
    heights = [
        max(MIN_ROW_H, -(-len(items) // per_line) * (TILE_H + GAP) + GAP)
        for _, _, items in layout
    ]
    height = HEADER_H + sum(heights) + GAP * len(layout) + PAD
    board = Image.new("RGB", (WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(board)
    draw.text(
        (PAD, HEADER_H / 2), custom_list.name, font=_font(30), fill=TEXT, anchor="lm"
    )

    mask = _tile_mask()
    deadline = time.monotonic() + FETCH_SECONDS
    top = HEADER_H
    for (name, color, items), row_h in zip(layout, heights, strict=True):
        draw.rounded_rectangle((PAD, top, WIDTH - PAD, top + row_h), RADIUS, fill=ROW)
        _label(draw, (PAD, top, PAD + LABEL_W, top + row_h), name, color)
        for index, item in enumerate(items):
            line, column = divmod(index, per_line)
            tile = _cover(item.image, deadline) or _title_tile(item.title)
            x = PAD + LABEL_W + GAP + column * (TILE_W + GAP)
            y = top + GAP + line * (TILE_H + GAP)
            board.paste(tile, (x, y), mask)
        top += row_h + GAP

    out = io.BytesIO()
    board.save(out, "PNG", optimize=True)
    return out.getvalue()
