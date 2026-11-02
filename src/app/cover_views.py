"""Views for covers a person adds to their own items. See ``local_covers``."""

import logging
import re

from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required, login_required
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext
from django.views.decorators.http import require_GET, require_POST

from app import helpers, local_covers
from app.log_safety import exception_summary
from app.models import CollectionEntry, CollectionField, Item, MediaTypes
from app.providers import services
from app.services import metadata_resolution

logger = logging.getLogger(__name__)

CANDIDATE_LIMIT = 8
ONE_YEAR_SECONDS = 365 * 24 * 60 * 60
OPEN_LIBRARY_ISBN_COVER = "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"
_ISBN_RE = re.compile(r"\d{9}[\dX]|\d{13}")


def user_has_item(user, item):
    """Return whether ``user`` tracks or has collected ``item``."""
    if item.media_type == MediaTypes.EPISODE.value:
        return False
    media_model = apps.get_model("app", item.media_type)
    return (
        media_model.objects.filter(user=user, item=item).exists()
        or CollectionEntry.objects.filter(user=user, item=item).exists()
    )


@login_not_required
@require_GET
def serve_local_cover(request, name):
    """Serve a local cover. The name is the image's own hash, so it never changes.

    Public like ``/image-cache/``: public lists and API clients show covers
    without a session, and the name cannot be guessed.
    """
    path = local_covers.path_for(name)
    if path is None:
        raise Http404
    etag = f'"{name.split(".", 1)[0]}"'
    if request.headers.get("If-None-Match") == etag:
        response = HttpResponse(status=304)
    else:
        response = FileResponse(
            path.open("rb"), content_type=local_covers.content_type_for(name)
        )
    response["ETag"] = etag
    response["Cache-Control"] = f"public, max-age={ONE_YEAR_SECONDS}, immutable"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _set_cover(item, value):
    """Point ``item`` at a new cover and tidy up the one it replaces."""
    previous = item.image
    item.image = value
    update_fields = ["image"]
    # A manual item's Metadata form reads its image from here first, so a stale
    # link would bring the old cover back the next time that form is saved.
    if isinstance(item.manual_metadata, dict) and item.manual_metadata.get("image"):
        item.manual_metadata = {**item.manual_metadata, "image": value}
        update_fields.append("manual_metadata")
    item.save(update_fields=update_fields)
    if previous != value:
        local_covers.discard_if_unused(previous)


def _cover_from_request(request):
    """Store the uploaded file or linked image and return its local path."""
    upload = request.FILES.get("cover_file")
    link = (request.POST.get("cover_url") or "").strip()
    if upload is not None:
        if upload.size > local_covers.MAX_COVER_BYTES:
            raise local_covers.CoverError(gettext("That image is larger than 10 MB."))
        return local_covers.store_bytes(upload.read())
    if link:
        return local_covers.fetch_cover(link)
    raise local_covers.CoverError(gettext("Choose an image or enter a link to one."))


@login_required
@require_POST
def update_item_cover(request, item_id):
    """Set an item's cover from an uploaded file or from a link."""
    item = get_object_or_404(Item, id=item_id)
    if not user_has_item(request.user, item):
        messages.error(
            request, gettext("You can only change covers for items in your library.")
        )
        return helpers.redirect_back(request)

    try:
        value = _cover_from_request(request)
    except local_covers.CoverError as error:
        messages.error(request, str(error))
        return helpers.redirect_back(request)

    if item.image == value:
        messages.success(request, gettext("That cover is already in use."))
    else:
        _set_cover(item, value)
        messages.success(request, gettext("Cover updated."))
    return helpers.redirect_back(request)


def _owned_barcodes(user, item):
    """Return the ISBN-shaped values in the user's Barcode field for ``item``."""
    field_ids = [
        str(pk)
        for pk in CollectionField.objects.filter(
            group__user=user, label__iexact="Barcode"
        ).values_list("id", flat=True)
    ]
    found = []
    entries = CollectionEntry.objects.filter(user=user, item=item).values_list(
        "custom_field_values", flat=True
    )
    for values in entries:
        for field_id in field_ids:
            code = re.sub(r"[\s-]", "", str((values or {}).get(field_id) or "")).upper()
            if _ISBN_RE.fullmatch(code) and code not in found:
                found.append(code)
    return found


def _candidates(user, item):
    """Return covers worth offering: by barcode first, then a provider search."""
    candidates = [
        {
            "title": gettext("Open Library, barcode %(code)s") % {"code": code},
            "image": OPEN_LIBRARY_ISBN_COVER.format(isbn=code),
        }
        for code in _owned_barcodes(user, item)[:2]
    ]
    source = metadata_resolution.metadata_default_source(user, item.media_type)
    try:
        with services.interactive_request_scope():
            results = services.search(
                item.media_type,
                item.title,
                1,
                source,
                user=user,
                language=metadata_resolution.metadata_language_default(user),
            ).get("results", [])
    except Exception as error:  # a provider outage just means fewer suggestions
        logger.warning("Cover search failed for item %s: %s", item.id, exception_summary(error))
        results = []
    for result in results:
        image = result.get("image")
        if image and image != settings.IMG_NONE and len(candidates) < CANDIDATE_LIMIT:
            candidates.append({"title": result.get("title") or "", "image": image})
    return candidates


@login_required
@require_GET
def item_cover_candidates(request, item_id):
    """Return the picker tiles for covers other sources have for an item."""
    item = get_object_or_404(Item, id=item_id)
    if not user_has_item(request.user, item):
        raise Http404
    return render(
        request,
        "app/components/image_picker_tiles.html",
        {"candidates": _candidates(request.user, item)},
    )
