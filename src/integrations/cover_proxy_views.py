"""Cover proxies for self-hosted Audiobookshelf and Plex servers.

The browser never talks to a user's server directly: these views fetch a cover
with the stored credentials, accept only plain raster types, and keep a copy.
When the server is down they serve the stored copy, then a placeholder
(Audiobookshelf) or a 404 (Plex). The signed tokens that name a cover live in
integrations/audiobookshelf_cover.py and integrations/plex_cover.py.
"""

import base64
import binascii
import logging
from http import HTTPStatus

import requests
from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseNotFound
from django.views.decorators.http import require_GET

from app import image_cache
from app.log_safety import exception_summary
from integrations import audiobookshelf_cover as abs_cover_proxy
from integrations import plex as plex_api
from integrations import plex_cover as plex_cover_proxy
from integrations.imports import helpers
from integrations.models import AudiobookshelfAccount, PlexAccount
from integrations.safe_fetch import send_to_self_hosted

logger = logging.getLogger(__name__)


AUDIOBOOKSHELF_COVER_TIMEOUT = 15


# After one failed cover fetch, the account's remaining covers skip ABS for this
# long. Otherwise every poster on a page holds a web worker for the full
# timeout while the server is down (#1307).
AUDIOBOOKSHELF_COVER_BACKOFF_SECONDS = 60


# Plain raster types only - an upstream ABS server (attacker-controlled, or
# just compromised) returning e.g. text/html or image/svg+xml would have it
# served as active content from Floppy's own origin to anyone holding the
# signed proxy URL, since the account owner can share that URL freely.
# The non-standard spellings are here because real ABS deployments behind a
# reverse proxy do emit them, and rejecting one lost the poster (#861).
AUDIOBOOKSHELF_COVER_CONTENT_TYPES = frozenset(
    {
        "image/jpeg",
        "image/jpg",
        "image/pjpeg",
        "image/png",
        "image/x-png",
        "image/webp",
        "image/gif",
        "image/avif",
        "image/bmp",
        "image/tiff",
        "image/heic",
        "image/heif",
    },
)


# Content types that mean "I don't know", where sniffing the body is the only
# way to tell a real cover from something we must not serve.
AUDIOBOOKSHELF_COVER_UNTYPED = frozenset({"", "application/octet-stream"})


# Leading magic bytes for the raster formats above. WebP is RIFF....WEBP, so it
# is matched on two separate offsets rather than a single prefix.
COVER_MAGIC_PREFIXES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)


COVER_SNIFF_BYTES = 16


def _sniff_cover_content_type(body: bytes) -> str:
    """Return the image type of `body` from its magic bytes, or "" if unknown.

    Deliberately recognises raster formats only: an SVG or HTML body has no
    magic number here and so stays rejected, exactly as an explicit
    image/svg+xml content type would be.
    """
    for prefix, content_type in COVER_MAGIC_PREFIXES:
        if body.startswith(prefix):
            return content_type
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    if body[4:8] == b"ftyp":
        brand = body[8:12]
        if brand in {b"avif", b"avis"}:
            return "image/avif"
        if brand in {b"heic", b"heix", b"heim", b"heis", b"mif1", b"msf1"}:
            return "image/heic"
    return ""


def _placeholder_image_bytes():
    """Decode settings.IMG_NONE into (body, content_type), or None.

    IMG_NONE is a base64 data URI by default but is overridable to a plain URL,
    which there is nothing to decode from. Decoded per call rather than cached
    so an overridden setting is always honoured; this only runs on the failure
    path, where one small base64 decode is not worth a staleness hazard.
    """
    prefix = "data:"
    value = settings.IMG_NONE or ""
    if not value.startswith(prefix):
        return None
    header, _, payload = value[len(prefix) :].partition(",")
    if not payload:
        return None
    content_type, _, encoding = header.partition(";")
    if encoding.strip().lower() != "base64":
        return None
    try:
        return base64.b64decode(payload), content_type.strip() or "image/svg+xml"
    except (binascii.Error, ValueError):
        return None


def _placeholder_image_response():
    """Return Floppy's own "no artwork" placeholder as a real image response.

    A 404 here renders as the browser's broken-image glyph, because nothing in
    the templates has an onerror fallback and the stored URL is a perfectly
    valid proxy URL (#861). Serving the placeholder instead keeps the grid
    looking the way it does for any other artless item. The bytes are Floppy's
    own fixed SVG, never anything the upstream server influenced, and the TTL
    is short so the real cover reappears once ABS recovers.
    """
    decoded = _placeholder_image_bytes()
    if decoded is None:
        return HttpResponseNotFound()
    body, content_type = decoded
    response = HttpResponse(body, content_type=content_type)
    response["Cache-Control"] = "private, max-age=300"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_not_required
@require_GET
def audiobookshelf_cover(request, token):
    """Stream an Audiobookshelf item's cover art using the account's own token.

    The ABS `/api/items/:id/cover` endpoint requires a bearer token, so it
    can't be embedded directly in an `<img src>`. This resolves the signed
    token to the owning account, fetches the cover server-side with that
    account's stored credentials, and streams it back (see #861). The
    endpoint is deliberately anonymous, so the response is streamed with a
    hard size cap and its content type is restricted to known-safe image
    types - matching the bounded, allow-listed fetch app.image_cache already
    does for provider artwork.

    Every failure below is logged and answered with Floppy's own placeholder
    rather than a bare 404: the 404s were both invisible in Settings > Advanced
    and rendered as broken-image glyphs, which is what made #861 impossible to
    diagnose from a bug report.
    """
    resolved = abs_cover_proxy.resolve_cover_proxy_token(token)
    if resolved is None:
        # A tampered or malformed token is not something a Floppy page can
        # produce, so this one stays a plain 404. It is logged at debug
        # rather than warning because the view is anonymous: anyone could
        # otherwise flood the log with junk tokens and bury the real
        # Audiobookshelf failures below, which are the point of #861. Every
        # other branch here needs a valid signature to reach.
        logger.debug("Audiobookshelf cover proxy rejected an unsignable token")
        return HttpResponseNotFound()
    account_id, library_item_id = resolved

    account = AudiobookshelfAccount.objects.filter(pk=account_id).first()
    if account is None:
        logger.warning(
            "Audiobookshelf cover unavailable: no account account=%s item=%s",
            account_id,
            library_item_id,
        )
        return _placeholder_image_response()

    # The last good copy is served while fresh, and whenever ABS cannot answer
    # (#1307), so a slow server no longer blanks every poster.
    stored_key = f"abs-cover:{account_id}:{library_item_id}"
    stored = image_cache.load_stored_cover(stored_key)
    if stored is not None and stored[2]:
        return image_cache.stored_cover_response(stored)

    def fallback():
        if stored is not None:
            return image_cache.stored_cover_response(stored)
        return _placeholder_image_response()

    try:
        api_token = helpers.decrypt(account.api_token)
    except Exception as error:
        logger.warning(
            "Audiobookshelf cover unavailable: token decrypt failed "
            "account=%s item=%s error=%s",
            account_id,
            library_item_id,
            exception_summary(error),
        )
        return fallback()

    backoff_key = f"abs_cover_backoff:{account_id}"
    if cache.get(backoff_key):
        logger.debug(
            "Audiobookshelf cover skipped: server recently unreachable "
            "account=%s item=%s",
            account_id,
            library_item_id,
        )
        return fallback()

    cover_url = f"{account.base_url.rstrip('/')}/api/items/{library_item_id}/cover"
    try:
        upstream = send_to_self_hosted(
            requests.get,
            cover_url,
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=AUDIOBOOKSHELF_COVER_TIMEOUT,
            stream=True,
        )
    except requests.RequestException as error:
        cache.set(backoff_key, 1, AUDIOBOOKSHELF_COVER_BACKOFF_SECONDS)
        logger.warning(
            "Audiobookshelf cover unavailable: request failed "
            "account=%s item=%s error=%s",
            account_id,
            library_item_id,
            exception_summary(error),
        )
        return fallback()

    try:
        if upstream.status_code != HTTPStatus.OK:
            logger.warning(
                "Audiobookshelf cover unavailable: upstream status=%s "
                "account=%s item=%s",
                upstream.status_code,
                account_id,
                library_item_id,
            )
            return fallback()

        content_type = (
            upstream.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        )
        if (
            content_type not in AUDIOBOOKSHELF_COVER_CONTENT_TYPES
            and content_type not in AUDIOBOOKSHELF_COVER_UNTYPED
        ):
            logger.warning(
                "Audiobookshelf cover unavailable: refused content_type=%s "
                "account=%s item=%s",
                content_type,
                account_id,
                library_item_id,
            )
            return fallback()

        try:
            content_length = int(upstream.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length > image_cache.MAX_IMAGE_BYTES:
            logger.warning(
                "Audiobookshelf cover unavailable: declared content_length=%s "
                "over cap account=%s item=%s",
                content_length,
                account_id,
                library_item_id,
            )
            return fallback()

        body = bytearray()
        oversized = False
        try:
            for chunk in upstream.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                body.extend(chunk)
                if len(body) > image_cache.MAX_IMAGE_BYTES:
                    oversized = True
                    break
        except requests.RequestException as error:
            # With stream=True a server that stalls after the headers fails
            # here rather than at send time, so it gets the same backoff.
            cache.set(backoff_key, 1, AUDIOBOOKSHELF_COVER_BACKOFF_SECONDS)
            logger.warning(
                "Audiobookshelf cover unavailable: body read failed "
                "account=%s item=%s error=%s",
                account_id,
                library_item_id,
                exception_summary(error),
            )
            return fallback()
    finally:
        upstream.close()

    if oversized:
        logger.warning(
            "Audiobookshelf cover unavailable: body exceeded %s bytes "
            "account=%s item=%s",
            image_cache.MAX_IMAGE_BYTES,
            account_id,
            library_item_id,
        )
        return fallback()

    body = bytes(body)
    # An upstream that declares nothing useful still has to prove it sent a
    # raster image; sniffing keeps SVG and HTML out just as the allow-list does.
    if content_type in AUDIOBOOKSHELF_COVER_UNTYPED:
        sniffed = _sniff_cover_content_type(body[:COVER_SNIFF_BYTES])
        if not sniffed:
            logger.warning(
                "Audiobookshelf cover unavailable: untyped body was not an image "
                "content_type=%s account=%s item=%s",
                content_type,
                account_id,
                library_item_id,
            )
            return fallback()
        content_type = sniffed

    image_cache.store_cover(stored_key, body, content_type)
    response = HttpResponse(body, content_type=content_type)
    response["Cache-Control"] = "private, max-age=3600"
    response["X-Content-Type-Options"] = "nosniff"
    return response


PLEX_COVER_TIMEOUT = 15


# Same allow-list as the Audiobookshelf proxy: a Plex server is an arbitrary
# user-configured host, so anything but a plain raster type would be served as
# active content from Floppy's own origin to whoever holds the signed URL.
PLEX_COVER_CONTENT_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/gif", "image/avif"},
)


@login_not_required
@require_GET
def plex_cover(request, token):
    """Stream a Plex item's cover art using the account's own Plex token.

    Plex art endpoints require an X-Plex-Token, which must never end up in an
    `<img src>` or in a stored Item.image. This resolves the signed token to the
    owning account and server, fetches the art server-side, and streams it back
    under the same size cap and content-type allow-list as the Audiobookshelf
    cover proxy.
    """
    resolved = plex_cover_proxy.resolve_cover_proxy_token(token)
    if resolved is None:
        return HttpResponseNotFound()
    account_id, machine_identifier, thumb_path = resolved

    account = PlexAccount.objects.filter(pk=account_id).first()
    if account is None:
        return HttpResponseNotFound()

    # Same last-good-copy rule as the Audiobookshelf proxy (#1307).
    stored_key = f"plex-cover:{account_id}:{machine_identifier}:{thumb_path}"
    stored = image_cache.load_stored_cover(stored_key)
    if stored is not None and stored[2]:
        return image_cache.stored_cover_response(stored)

    def fallback():
        if stored is not None:
            return image_cache.stored_cover_response(stored)
        return HttpResponseNotFound()

    uri, plex_token = plex_api.connection_for_machine(
        account.sections,
        machine_identifier,
        account.plex_token,
    )
    if not uri or not plex_token:
        return fallback()

    try:
        upstream = send_to_self_hosted(
            requests.get,
            f"{uri}{thumb_path}",
            params={"X-Plex-Token": plex_token},
            timeout=PLEX_COVER_TIMEOUT,
            stream=True,
            verify=settings.PLEX_SSL_VERIFY,
        )
    except requests.RequestException:
        return fallback()

    try:
        if upstream.status_code != HTTPStatus.OK:
            return fallback()

        content_type = (
            upstream.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        )
        if content_type not in PLEX_COVER_CONTENT_TYPES:
            return fallback()

        try:
            content_length = int(upstream.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length > image_cache.MAX_IMAGE_BYTES:
            return fallback()

        body = bytearray()
        for chunk in upstream.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            body.extend(chunk)
            if len(body) > image_cache.MAX_IMAGE_BYTES:
                return fallback()
    finally:
        upstream.close()

    body = bytes(body)
    image_cache.store_cover(stored_key, body, content_type)
    response = HttpResponse(body, content_type=content_type)
    response["Cache-Control"] = "private, max-age=3600"
    return response
