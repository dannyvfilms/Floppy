"""Stremio: connecting an account, and the Floppy add-on Stremio installs.

The add-on routes are public (Stremio calls them without a session) and
authenticate by the token in the URL. They serve the manifest, catalogs, meta
and subtitles, and turn player and library events into queued tracking work.
"""

import json
import logging
import os
import re
from urllib.parse import unquote

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.utils import timezone
from django.utils.translation import gettext
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

import users
from integrations import stremio_catalog, stremio_events, stremio_queue, tasks
from integrations.imports import helpers, stremio
from integrations.models import StremioAccount
from integrations.view_helpers import (
    _integration_redirect,
    _queue_task_or_message,
    _run_with_lock_retry,
)

logger = logging.getLogger(__name__)


STREMIO_RECURRING_TASK_NAME = "Import from Stremio (Recurring)"


def _ensure_stremio_schedule(user):
    """Create the recurring Stremio import schedule if missing."""
    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    existing_task = PeriodicTask.objects.filter(
        task=STREMIO_RECURRING_TASK_NAME,
        **helpers.periodic_task_user_kwargs(user.id),
        enabled=True,
    ).first()
    if existing_task:
        return

    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute=0,
        hour="*/2",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        timezone=timezone.get_default_timezone(),
    )
    PeriodicTask.objects.create(
        name=f"Import from Stremio for {user.username} (every 2 hours)",
        task=STREMIO_RECURRING_TASK_NAME,
        crontab=crontab,
        kwargs=json.dumps({"user_id": user.id}),
        start_time=timezone.now(),
        enabled=True,
    )


@require_POST
def stremio_connect(request):
    """Connect a Stremio account using email/password or a pasted auth key."""
    email = request.POST.get("email", "").strip()
    password = request.POST.get("password", "").strip()
    auth_key = request.POST.get("auth_key", "").strip()

    if not auth_key and not (email and password):
        messages.error(
            request, "Enter your Stremio email and password, or an auth key."
        )
        return _integration_redirect(request)

    try:
        if not auth_key:
            auth_key = stremio.login(email, password)
        else:
            # Validate a pasted auth key before storing it.
            stremio.get_user(auth_key)
    except helpers.MediaImportError as error:
        logger.exception("Stremio login failed")
        messages.error(
            request,
            "Could not connect to Stremio. Check your credentials; for accounts created "
            "via Facebook login, paste an auth key instead or set a password first. "
            f"({error})",
        )
        return _integration_redirect(request)
    except Exception as error:
        logger.exception("Failed to connect to Stremio")
        messages.error(request, f"Failed to connect to Stremio: {error}")
        return _integration_redirect(request)

    def _connect():
        StremioAccount.objects.update_or_create(
            user=request.user,
            defaults={
                "auth_key": helpers.encrypt(auth_key),
                "email": helpers.encrypt(email) if email else "",
                "connection_broken": False,
                "last_error_message": "",
            },
        )
        _ensure_stremio_schedule(request.user)

    _run_with_lock_retry("connect Stremio", _connect)
    if _queue_task_or_message(request,
        tasks.import_stremio, user_id=request.user.id, mode="new"
    ) is not False:
        messages.success(
            request,
            "Connected to Stremio. Initial import queued; your library will sync every 2 hours.",
        )
    return _integration_redirect(request, connected_slug="stremio")


@require_POST
def stremio_disconnect(request):
    """Disconnect the Stremio integration."""
    from django_celery_beat.models import PeriodicTask

    def _disconnect():
        PeriodicTask.objects.filter(
            task=STREMIO_RECURRING_TASK_NAME,
            **helpers.periodic_task_user_kwargs(request.user.id),
        ).delete()
        StremioAccount.objects.filter(user=request.user).delete()

    _run_with_lock_retry("disconnect Stremio", _disconnect)
    messages.info(request, "Disconnected Stremio.")
    return redirect("import_data")


@require_POST
def import_stremio(request):
    """Queue a Stremio import and ensure the recurring schedule exists."""
    account = getattr(request.user, "stremio_account", None)
    if not account:
        messages.error(request, "Connect Stremio before importing.")
        return redirect("import_data")

    queued = _queue_task_or_message(request, tasks.import_stremio, user_id=request.user.id, mode="new")
    _ensure_stremio_schedule(request.user)
    if queued is not False:
        messages.info(request, "Stremio import queued.")
    return redirect("import_data")


STREMIO_ADDON_MANIFEST = {
    # Keep the existing addon id so installed clients remain compatible.
    "id": "org.yamtrack.scrobbler",
    "version": "1.3.0",
    "name": "Floppy",
    "description": (
        "Floppy Watchlist catalogs and playback scrobbling for Stremio."
    ),
    # `player` and `library` are additive: a client that predates them parses
    # the manifest, never matches the resource, and never calls the route.
    "resources": ["catalog", "meta", "subtitles", "player", "library"],
    "types": ["movie", "series"],
    "idPrefixes": ["tt"],
    "catalogs": [],
    "behaviorHints": {"configurable": True, "configurationRequired": False},
}


# The player and library resources sit behind a kill switch so the manifest can
# withdraw them without a code change. Only an explicit falsy value disables
# them; declaring them is inert on clients that predate the resources.
STREMIO_PLAYER_RESOURCES = ("player", "library")


STREMIO_DISABLED_ENV_VALUES = {"0", "false", "no"}


def _stremio_manifest_resources():
    """Return the manifest resources, honoring the player/library kill switch."""
    resources = list(STREMIO_ADDON_MANIFEST["resources"])
    setting = os.environ.get("STREMIO_ENABLE_PLAYER_RESOURCE", "").strip().lower()
    if setting in STREMIO_DISABLED_ENV_VALUES:
        return [name for name in resources if name not in STREMIO_PLAYER_RESOURCES]
    return resources


STREMIO_SCROBBLE_THROTTLE_SECONDS = 1800


STREMIO_MAX_MEDIA_ID_LENGTH = 128


STREMIO_MEDIA_ID_PATTERN = re.compile(
    # Season 0 is Stremio's specials bucket; episodes start at 1. Both bounds
    # mirror MAX_EPISODE_COORDINATE so the route and the tracker agree on what
    # is malformed.
    r"^tt[0-9]+(?::[0-9]{1,4}:[1-9][0-9]{0,3})?$",
)


def _stremio_addon_response(payload, status=200):
    """Build a JSON response with the CORS headers Stremio requires."""
    response = JsonResponse(payload, status=status)
    response["Access-Control-Allow-Origin"] = "*"
    return response


def _stremio_validated_media_id(
    token,
    media_type,
    media_id,
    *,
    rejected,
    forbidden=None,
    allow_episode_id=False,
):
    """Authenticate an addon request and validate the media id it names.

    Returns `(user, grant, media_id)` when the request may proceed, and the
    response to send in its place otherwise. Every event route gates on this
    same pair, so it lives here rather than four times over.

    Each resource answers a refusal with its own protocol shape — Stremio
    renders none of them, so `meta` sends an empty object, `subtitles` an empty
    list (with a 200, since a subtitles request has no error to report), and
    the write routes a `success` flag — so the caller passes its own
    `(payload, status)`: `rejected` for a media id the pattern does not accept,
    and `forbidden` for a grant minted without playback permission. A `None`
    `forbidden` means the resource performs no write and needs no such gate.

    The id is client-supplied and is bound into the tracker's queries, so it is
    validated here rather than handed to a handler. `allow_episode_id` relaxes
    the movie rule for `meta`, which answers for whatever id it is asked about
    rather than writing playback for it.
    """
    user, grant = stremio_catalog.resolve_addon_credential(token)
    if user is None:
        logger.warning("Invalid token on Stremio addon request")
        return _stremio_addon_response({"error": "Invalid token"}, status=401)

    if forbidden is not None and grant is not None and not grant.allow_playback_start:
        # These resources record playback, which is a write. A grant minted
        # without that permission serves catalogs and nothing else.
        logger.info(
            "stremio_addon rejected reason=grant_excludes_playback_start "
            "user_id=%s media_type=%s",
            user.id,
            media_type,
        )
        return _stremio_addon_response(*forbidden)

    media_id = unquote(media_id)
    malformed = (
        media_type not in {"movie", "series"}
        or len(media_id) > STREMIO_MAX_MEDIA_ID_LENGTH
        or not STREMIO_MEDIA_ID_PATTERN.fullmatch(media_id)
        or (not allow_episode_id and media_type == "movie" and ":" in media_id)
    )
    if malformed:
        # The id is logged only up to the bound the pattern itself enforces.
        logger.info(
            "stremio_addon rejected reason=invalid_media_id user_id=%s "
            "media_type=%s media_id=%s",
            user.id,
            media_type,
            media_id[:STREMIO_MAX_MEDIA_ID_LENGTH],
        )
        return _stremio_addon_response(*rejected)

    return user, grant, media_id


@login_not_required
@csrf_exempt
@require_GET
def stremio_addon_catalog(
    request,
    token,
    media_type,
    catalog_id,
    extra=None,
    config=None,
):
    """Serve a Floppy Watchlist catalog to Stremio."""
    user, grant = stremio_catalog.resolve_addon_credential(token)
    if user is None:
        logger.warning("Invalid token on Stremio addon catalog request")
        return _stremio_addon_response(
            {"error": "Invalid token"},
            status=401,
        )

    spec = stremio_catalog.get_catalog_spec(media_type, catalog_id)
    if spec is None:
        return _stremio_addon_response({"metas": []})

    if grant is not None:
        if not grant.allows_catalog(catalog_id):
            # Not 403: the add-on protocol has no way to show one, and an empty
            # catalog is the honest answer for something this install may not see.
            logger.info(
                "stremio_catalog grant_scope_excluded catalog_id=%s",
                catalog_id,
            )
            return _stremio_addon_response({"metas": []})
        stremio_catalog.touch_grant(grant)

    try:
        skip = stremio_catalog.parse_skip(extra)
    except stremio_catalog.CatalogSkipError as error:
        return _stremio_addon_response({"error": error.message}, status=400)

    metas, unresolved_count = stremio_catalog.project_catalog(user, spec, skip)
    logger.info(
        "Stremio catalog projection catalog_id=%s skip=%s returned=%s unresolved=%s",
        catalog_id,
        skip,
        len(metas),
        unresolved_count,
    )
    return _stremio_addon_response({"metas": metas})


@login_not_required
@require_GET
def stremio_addon_configure(request, token, config=None):
    """Serve the addon configuration page for a user's install URL."""
    try:
        user = users.models.User.objects.get(token=token, is_active=True)
    except ObjectDoesNotExist:
        logger.warning("Invalid token on Stremio addon configure request")
        return HttpResponse("Invalid token", status=401)

    catalog_options = stremio_catalog.catalog_options(user)
    selected_ids = list(stremio_catalog.parse_catalog_config(config))
    props = {
        "options": catalog_options,
        "selectedIds": selected_ids,
        "labels": {
            "catalogs": gettext("Catalogs"),
            "hint": gettext(
                "Use the URL below, not the address of this page. It works "
                "in Stremio directly, or in an addon manager such as "
                "AIOStreams or AIOMetadata."
            ),
            "copy": gettext("Copy URL"),
            "copied": gettext("Copied."),
            "install": gettext("Install in Stremio"),
            "noneSelected": gettext(
                "Nothing selected. The default catalogs will be used."
            ),
        },
    }
    return render(
        request,
        "integrations/stremio_configure.html",
        {
            "catalog_options": catalog_options,
            "selected_ids": selected_ids,
            "stremio_config_props": props,
        },
    )


@login_not_required
@csrf_exempt
@require_GET
def stremio_addon_manifest(request, token, config=None):
    """Serve the Stremio addon manifest for a user's install URL."""
    user, grant = stremio_catalog.resolve_addon_credential(token)
    if user is None:
        logger.warning("Invalid token on Stremio addon manifest request")
        return _stremio_addon_response({"error": "Invalid token"}, status=401)

    if grant is not None:
        stremio_catalog.touch_grant(grant)

    selected = stremio_catalog.parse_catalog_config(config)
    manifest = STREMIO_ADDON_MANIFEST | {
        "logo": request.build_absolute_uri(
            static("favicon/apple-touch-icon.png"),
        ),
        # The kill switch withdraws the player/library resources from what
        # clients see; the routes themselves are unconditional.
        "resources": _stremio_manifest_resources(),
        # Both gates: the install URL picks the catalogs, the grant bounds them.
        "catalogs": stremio_catalog.manifest_catalogs_for_grant(
            user,
            grant,
            selected,
        ),
    }
    return _stremio_addon_response(manifest)


@login_not_required
@csrf_exempt
@require_GET
def stremio_addon_meta(request, token, media_type, media_id):
    """Serve metadata for one item the user tracks."""
    validated = _stremio_validated_media_id(
        token,
        media_type,
        media_id,
        rejected=({"meta": {}}, 400),
        allow_episode_id=True,
    )
    if isinstance(validated, HttpResponse):
        return validated
    user, grant, media_id = validated

    if grant is not None:
        stremio_catalog.touch_grant(grant)

    meta = stremio_catalog.project_meta(user, media_type, media_id, grant=grant)
    if meta is None:
        # Empty rather than 404: the item is simply not in this library, and
        # Stremio treats a 404 as the add-on being broken.
        return _stremio_addon_response({"meta": {}})

    return _stremio_addon_response({"meta": meta})


@login_not_required
@csrf_exempt
@require_GET
def stremio_addon_subtitles(request, token, media_type, media_id, extra=None, config=None):
    """Record a playback-start scrobble from a Stremio subtitles request."""
    from django.core.cache import cache

    validated = _stremio_validated_media_id(
        token,
        media_type,
        media_id,
        rejected=({"subtitles": []}, 200),
        forbidden=({"subtitles": []}, 200),
    )
    if isinstance(validated, HttpResponse):
        return validated
    user, _grant, media_id = validated

    # Stremio re-requests subtitles on seeks and quality changes; only the
    # first request per item in the window records a scrobble.
    throttle_key = f"stremio_scrobble_{user.id}_{media_type}_{media_id}"
    throttle_added = cache.add(
        throttle_key,
        "1",
        timeout=STREMIO_SCROBBLE_THROTTLE_SECONDS,
    )
    if throttle_added is None:
        logger.info(
            "stremio_queue status=unavailable reason=throttle_cache user_id=%s",
            user.id,
        )
    elif throttle_added:
        # Reported, not used: Stremio appends the selected release's
        # `videoHash`/`videoSize`/`filename` here, and Floppy has always
        # discarded them. One line per item per throttle window is enough to
        # decide whether they are worth reading.
        extras = stremio_events.parse_subtitles_video_extras(extra)
        logger.info(
            "stremio_subtitles_extras user_id=%s media_type=%s videoHash=%s "
            "videoSize=%s filename=%s",
            user.id,
            media_type,
            extras["videoHash"],
            extras["videoSize"],
            extras["filename"],
        )
        queue_member = stremio_queue.member(media_type, media_id)
        queue_status = stremio_queue.reserve_pending(user.id, queue_member)
        if queue_status == "accepted":
            try:
                tasks.process_stremio_webhook.delay(
                    {"id": media_id, "type": media_type},
                    user.id,
                    queue_member,
                )
                logger.info(
                    "stremio_queue status=queued user_id=%s media_type=%s media_id=%s",
                    user.id,
                    media_type,
                    media_id,
                )
            except Exception:
                stremio_queue.release_pending(user.id, queue_member)
                logger.exception(
                    "stremio_queue status=dispatch_failed user_id=%s media_type=%s "
                    "media_id=%s",
                    user.id,
                    media_type,
                    media_id,
                )
        else:
            logger.info(
                "stremio_queue status=%s user_id=%s media_type=%s media_id=%s",
                queue_status,
                user.id,
                media_type,
                media_id,
            )

    return _stremio_addon_response({"subtitles": []})


def _dispatch_stremio_tracker_event(kind, user, media_type, media_id, extra):
    """Queue one player or library event so the web worker never does its writes.

    A first-viewed episode can ask the provider for season metadata and a batched
    library event writes up to a hundred rows, so both run on the Celery worker.
    Stremio ignores the body and a 500 only makes the client retry, so a dispatch
    failure is logged and accepted.
    """
    try:
        tasks.process_stremio_tracker_event.delay(
            kind,
            user.id,
            media_type,
            media_id,
            extra,
            timezone.now().isoformat(),
        )
    except Exception:
        logger.exception("stremio_%s status=dispatch_failed user_id=%s", kind, user.id)


@login_not_required
@csrf_exempt
@require_GET
def stremio_addon_player(
    request,
    token,
    media_type,
    media_id,
    extra=None,
    config=None,
):
    """Record one Stremio player event (start/pause/stop with position)."""
    validated = _stremio_validated_media_id(
        token,
        media_type,
        media_id,
        rejected=({"success": False}, 400),
        forbidden=({"success": True}, 200),
    )
    if isinstance(validated, HttpResponse):
        return validated
    user, _grant, media_id = validated

    _dispatch_stremio_tracker_event("player", user, media_type, media_id, extra)

    return _stremio_addon_response({"success": True})


@login_not_required
@csrf_exempt
@require_GET
def stremio_addon_library(
    request,
    token,
    media_type,
    media_id,
    extra=None,
    config=None,
):
    """Record one Stremio library event (watched/unwatched/add/remove)."""
    validated = _stremio_validated_media_id(
        token,
        media_type,
        media_id,
        rejected=({"success": False}, 400),
        forbidden=({"success": True}, 200),
    )
    if isinstance(validated, HttpResponse):
        return validated
    user, _grant, media_id = validated

    _dispatch_stremio_tracker_event("library", user, media_type, media_id, extra)

    return _stremio_addon_response({"success": True})
