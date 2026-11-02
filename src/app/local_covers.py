"""Covers a person adds themselves, stored in Floppy's own data folder.

A provider cover is a link Floppy shows from the provider. A *local* cover is
a file the person chose, so it is copied into ``FLOPPY_DATA_DIR/covers`` and
the item keeps the path ``/covers/<sha256>.<ext>``. See
``docs/architecture/local-covers.md`` for the contract.
"""

import hashlib
import io
import logging
import os
import re
import tempfile
from contextlib import suppress
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.utils.translation import gettext

from integrations import safe_fetch

logger = logging.getLogger(__name__)

COVER_URL_PREFIX = "/covers/"
MAX_COVER_BYTES = 10 * 1024 * 1024
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_EDGE_PIXELS = 1600
FETCH_SECONDS = 15

# Pillow's name for the format -> (file extension, MIME type).
FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}
_NAME_RE = re.compile(r"^[0-9a-f]{64}\.(?:jpg|png|webp)$")
_META_KEYS = ("og:image", "og:image:url", "og:image:secure_url", "twitter:image")


class CoverError(Exception):
    """A cover could not be used. The message is safe to show to the person."""


def covers_root():
    """Return the folder holding local covers."""
    return Path(settings.FLOPPY_DATA_DIR) / "covers"


def is_local(value):
    """Return whether ``value`` is the stored path of a local cover."""
    return (
        isinstance(value, str)
        and value.startswith(COVER_URL_PREFIX)
        and _NAME_RE.fullmatch(value.removeprefix(COVER_URL_PREFIX)) is not None
    )


def path_for(name):
    """Return the file behind a cover name, or None for anything unexpected."""
    if not _NAME_RE.fullmatch(name or ""):
        return None
    root = os.path.normpath(covers_root())
    path = os.path.normpath(f"{root}{os.sep}{name}")
    # The name pattern already allows no separators; this keeps the folder
    # check explicit for anything that reads the result.
    if not path.startswith(root + os.sep):
        return None
    result = Path(path)
    return result if result.is_file() else None


def content_type_for(name):
    """Return the MIME type for a stored cover name."""
    extension = name.rsplit(".", 1)[-1]
    return next(mime for ext, mime in FORMATS.values() if ext == extension)


def store_bytes(data):
    """Validate, re-encode and save image bytes. Returns the local cover path.

    Re-encoding drops metadata such as the GPS position a phone photo carries,
    and the size cap keeps a 12-megapixel photo from filling the data folder.
    """
    # Imported here: Pillow is only needed on this path.
    from PIL import Image, ImageOps, UnidentifiedImageError

    if len(data) > MAX_COVER_BYTES:
        raise CoverError(gettext("That image is larger than 10 MB."))
    try:
        with Image.open(io.BytesIO(data)) as source:
            image_format = source.format
            if image_format not in FORMATS:
                raise CoverError(gettext("Use a JPEG, PNG or WebP image."))
            image = ImageOps.exif_transpose(source)
            image.thumbnail((MAX_EDGE_PIXELS, MAX_EDGE_PIXELS))
            if image_format == "JPEG":
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format=image_format, quality=90)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise CoverError(gettext("That file is not a usable image.")) from None

    body = output.getvalue()
    name = f"{hashlib.sha256(body).hexdigest()}.{FORMATS[image_format][0]}"
    root = covers_root()
    root.mkdir(parents=True, exist_ok=True)
    target = root / name
    if not target.exists():
        with tempfile.NamedTemporaryFile(
            dir=root, prefix=".cover-", suffix=".tmp", delete=False
        ) as handle:
            handle.write(body)
        Path(handle.name).replace(target)
    return f"{COVER_URL_PREFIX}{name}"


def _fetch(url, accept, max_bytes):
    """Fetch through the outbound boundary, turning failures into CoverError."""
    try:
        response, body = safe_fetch.safe_fetch(
            url,
            headers={"Accept": accept},
            max_bytes=max_bytes,
            total_timeout=FETCH_SECONDS,
        )
    except safe_fetch.UnsafeUrlError as error:
        if getattr(error, "reason_code", "") == safe_fetch.REASON_RESPONSE_TOO_LARGE:
            raise CoverError(gettext("That image is larger than 10 MB.")) from None
        raise CoverError(gettext("That link cannot be used.")) from None
    except requests.RequestException:
        raise CoverError(gettext("That link could not be reached.")) from None
    if not 200 <= response.status_code < 300:  # noqa: PLR2004
        raise CoverError(gettext("That link could not be reached."))
    return response, body


class _ImageLinkParser(HTMLParser):
    """Collect the cover a book or comic page advertises for sharing."""

    def __init__(self):
        super().__init__()
        self.found = {}

    def handle_starttag(self, tag, attrs):
        values = {key: value for key, value in attrs if value}
        if tag == "meta":
            key = values.get("property") or values.get("name")
            if key in _META_KEYS and values.get("content"):
                self.found.setdefault(key, values["content"])
        elif tag == "link" and values.get("rel") == "image_src" and values.get("href"):
            self.found.setdefault("image_src", values["href"])


def page_image_url(html, base_url):
    """Return the cover image a web page names, resolved against ``base_url``."""
    parser = _ImageLinkParser()
    with suppress(Exception):  # malformed markup still yields what came before
        parser.feed(html)
    for key in (*_META_KEYS, "image_src"):
        if key in parser.found:
            return urljoin(base_url, parser.found[key].strip())
    return None


def fetch_cover(url):
    """Save the cover at ``url``, which may be an image or a web page naming one."""
    url = (url or "").strip()
    response, body = _fetch(url, "image/*,text/html;q=0.8", MAX_COVER_BYTES)
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
    if content_type.startswith("image/"):
        return store_bytes(body)
    if "html" not in content_type:
        raise CoverError(gettext("That link is not an image or a web page."))

    encoding = response.encoding or "utf-8"
    image_url = page_image_url(
        body[:MAX_PAGE_BYTES].decode(encoding, errors="replace"),
        # A redirect can move the page, and relative links follow the page.
        getattr(response, "logical_url", url),
    )
    if not image_url:
        raise CoverError(gettext("That page does not name a cover image."))
    response, body = _fetch(image_url, "image/*", MAX_COVER_BYTES)
    if not response.headers.get("Content-Type", "").lower().startswith("image/"):
        raise CoverError(gettext("That page does not name a cover image."))
    return store_bytes(body)


def discard_if_unused(value):
    """Delete a local cover's file once no item points at it any more."""
    from app.models import Item

    if not is_local(value):
        return
    name = value.removeprefix(COVER_URL_PREFIX)
    if (
        Item.objects.filter(image=value).exists()
        or Item.objects.filter(manual_metadata__icontains=name).exists()
    ):
        return
    path = path_for(name)
    if path is not None:
        with suppress(OSError):
            path.unlink()
