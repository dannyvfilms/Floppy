"""Contains views for importing and exporting media data from various sources."""

import hmac
import json
import logging
import re
import secrets
import zipfile
import zoneinfo
from datetime import datetime, timedelta
from http import HTTPStatus
from io import BytesIO
from urllib.parse import unquote

import croniter
import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError
from django.db.models import Q
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

import users
from app import helpers as app_helpers
from app.log_safety import exception_summary
from integrations import (
    exports,
    gpodder_api,
    koito_api,
    lastfm_api,
    pocketcasts_api,
    tasks,
    xbox_api,
)
from integrations import plex as plex_api
from integrations.gpodder_api import GPodderAuthError, GPodderClientError
from integrations.imports import anilist, helpers, mdblist, simkl, stremio, trakt
from integrations.imports.audiobookshelf import (
    AudiobookshelfAuthError,
    AudiobookshelfClient,
)
from integrations.imports.radarr import RadarrClient
from integrations.imports.sonarr import SonarrClient
from integrations.imports.storyteller import (
    StorytellerClient,
    StorytellerClientError,
)
from integrations.jellyfin_client import (
    JellyfinAuthError,
    JellyfinClient,
    JellyfinClientError,
)
from integrations.jellyfin_sync import (
    JELLYFIN_PUSH_INTERVAL_MINUTES,
    JELLYFIN_PUSH_TASK_NAME,
)
from integrations.lastfm_api import (
    LastFMAPIError,
    LastFMClientError,
    LastFMRateLimitError,
)
from integrations.models import (
    AudiobookshelfAccount,
    GPodderAccount,
    JellyfinAccount,
    KoitoAccount,
    LastFMAccount,
    MDBListAccount,
    PlexAccount,
    PocketCastsAccount,
    RadarrAccount,
    SonarrAccount,
    StorytellerAccount,
    StremioAccount,
    XboxAccount,
)
from integrations.plex_watchlist import (
    WATCHLIST_SYNC_INTERVAL_MINUTES,
    WATCHLIST_TASK_NAME,
)
from integrations.pocketcasts_api import PocketCastsAuthError

logger = logging.getLogger(__name__)
ARR_SYNC_INTERVAL_HOURS = 2
RADARR_RECURRING_TASK_NAME = "Import from Radarr (Recurring)"
SONARR_RECURRING_TASK_NAME = "Import from Sonarr (Recurring)"
GPODDER_RECURRING_TASK_NAME = "Import from GPodder (Recurring)"
# The upload rides in the Celery message, so bound what a single import can send.
TRAKT_EXPORT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _read_uploaded_file(file):
    """Read uploaded file bytes for safe Celery serialization."""
    file.seek(0)
    return file.read()


def _integration_redirect(request, *, connected_slug=None, next_url=None):
    """Redirect back to `next` (e.g. the onboarding wizard) if present.

    Falls back to `import_data`, the normal Settings destination. When
    `connected_slug` is given, records it on the user's onboarding progress
    so the setup wizard's queue drops that source on the next request.
    """
    if connected_slug:
        user = request.user
        if connected_slug not in user.onboarding_connected_sources:
            user.onboarding_connected_sources = [*user.onboarding_connected_sources, connected_slug]
            user.save(update_fields=["onboarding_connected_sources"])
    destination = next_url or request.POST.get("next") or request.GET.get("next")
    return redirect(destination or "import_data")


def _save_plex_usernames(user, raw_usernames):
    """Persist de-duplicated Plex usernames for webhook filtering."""
    if raw_usernames is None:
        return

    username_list = [u.strip() for u in raw_usernames.split(",") if u.strip()]
    seen = set()
    deduplicated = [
        u for u in username_list if not (u.lower() in seen or seen.add(u.lower()))
    ]
    cleaned_usernames = ", ".join(deduplicated)
    if cleaned_usernames != user.plex_usernames:
        user.plex_usernames = cleaned_usernames
        user.save(update_fields=["plex_usernames"])


def _plex_watchlist_task_filter(user_id):
    """Match a user's watchlist task regardless of JSON spacing/quotes."""
    return (
        Q(kwargs__contains=f"'user_id': {user_id},")
        | Q(
            kwargs__contains=f"'user_id': {user_id}" + "}",
        )
        | Q(
            kwargs__contains=f'"user_id": {user_id},',
        )
        | Q(
            kwargs__contains=f'"user_id": {user_id}' + "}",
        )
    )


def _periodic_task_filter_for_user(user_id):
    """Match a user's periodic task regardless of JSON spacing/quotes."""
    return _plex_watchlist_task_filter(user_id)


def _next_arr_sync_start(now=None):
    """Return the next future ARR sync boundary."""
    current = (now or timezone.now()).astimezone(timezone.get_default_timezone())
    boundary = current.replace(minute=0, second=0, microsecond=0)
    hours_until_next = ARR_SYNC_INTERVAL_HOURS - (
        boundary.hour % ARR_SYNC_INTERVAL_HOURS
    )
    return boundary + timedelta(hours=hours_until_next)


def _ensure_plex_watchlist_schedule(user, plex_account):
    """Create or enable the per-user Plex watchlist interval schedule."""
    from django_celery_beat.models import IntervalSchedule, PeriodicTask

    next_interval_start = timezone.now() + timedelta(
        minutes=WATCHLIST_SYNC_INTERVAL_MINUTES
    )
    interval, _ = IntervalSchedule.objects.get_or_create(
        every=WATCHLIST_SYNC_INTERVAL_MINUTES,
        period=IntervalSchedule.MINUTES,
    )
    task_filter = PeriodicTask.objects.filter(
        _plex_watchlist_task_filter(user.id),
        task=WATCHLIST_TASK_NAME,
    )
    existing_task = task_filter.first()
    if existing_task:
        was_enabled = existing_task.enabled
        updated_fields = []
        desired_name = (
            f"{WATCHLIST_TASK_NAME} for "
            f"{plex_account.plex_username or user.username} "
            f"(every {WATCHLIST_SYNC_INTERVAL_MINUTES} minutes)"
        )
        desired_kwargs = json.dumps({"user_id": user.id, "mode": "watchlist"})
        if existing_task.name != desired_name:
            existing_task.name = desired_name
            updated_fields.append("name")
        if existing_task.interval_id != interval.id:
            existing_task.interval = interval
            updated_fields.append("interval")
        if existing_task.crontab_id is not None:
            existing_task.crontab = None
            updated_fields.append("crontab")
        if existing_task.clocked_id is not None:
            existing_task.clocked = None
            updated_fields.append("clocked")
        if existing_task.solar_id is not None:
            existing_task.solar = None
            updated_fields.append("solar")
        if existing_task.one_off:
            existing_task.one_off = False
            updated_fields.append("one_off")
        if existing_task.kwargs != desired_kwargs:
            existing_task.kwargs = desired_kwargs
            updated_fields.append("kwargs")
        if not existing_task.enabled:
            existing_task.enabled = True
            updated_fields.append("enabled")
        if existing_task.start_time is None or not was_enabled:
            existing_task.start_time = next_interval_start
            updated_fields.append("start_time")
        if updated_fields:
            existing_task.save(update_fields=updated_fields)
        return existing_task

    return PeriodicTask.objects.create(
        name=(
            f"{WATCHLIST_TASK_NAME} for "
            f"{plex_account.plex_username or user.username} "
            f"(every {WATCHLIST_SYNC_INTERVAL_MINUTES} minutes)"
        ),
        task=WATCHLIST_TASK_NAME,
        interval=interval,
        kwargs=json.dumps({"user_id": user.id, "mode": "watchlist"}),
        start_time=next_interval_start,
        enabled=True,
    )


def _disable_plex_watchlist_schedule(user):
    """Delete any per-user Plex watchlist periodic tasks."""
    from django_celery_beat.models import PeriodicTask

    return PeriodicTask.objects.filter(
        _plex_watchlist_task_filter(user.id),
        task=WATCHLIST_TASK_NAME,
    ).delete()


def _ensure_jellyfin_push_schedule(user, jellyfin_account):
    """Create or enable the per-user Jellyfin watched-state push schedule."""
    from django_celery_beat.models import IntervalSchedule, PeriodicTask

    next_interval_start = timezone.now() + timedelta(
        minutes=JELLYFIN_PUSH_INTERVAL_MINUTES
    )
    interval, _ = IntervalSchedule.objects.get_or_create(
        every=JELLYFIN_PUSH_INTERVAL_MINUTES,
        period=IntervalSchedule.MINUTES,
    )
    task_filter = PeriodicTask.objects.filter(
        _plex_watchlist_task_filter(user.id),
        task=JELLYFIN_PUSH_TASK_NAME,
    )
    existing_task = task_filter.first()
    if existing_task:
        was_enabled = existing_task.enabled
        updated_fields = []
        desired_name = (
            f"{JELLYFIN_PUSH_TASK_NAME} for "
            f"{jellyfin_account.jellyfin_username or user.username} "
            f"(every {JELLYFIN_PUSH_INTERVAL_MINUTES} minutes)"
        )
        desired_kwargs = json.dumps({"user_id": user.id})
        if existing_task.name != desired_name:
            existing_task.name = desired_name
            updated_fields.append("name")
        if existing_task.interval_id != interval.id:
            existing_task.interval = interval
            updated_fields.append("interval")
        if existing_task.crontab_id is not None:
            existing_task.crontab = None
            updated_fields.append("crontab")
        if existing_task.kwargs != desired_kwargs:
            existing_task.kwargs = desired_kwargs
            updated_fields.append("kwargs")
        if not existing_task.enabled:
            existing_task.enabled = True
            updated_fields.append("enabled")
        if existing_task.start_time is None or not was_enabled:
            existing_task.start_time = next_interval_start
            updated_fields.append("start_time")
        if updated_fields:
            existing_task.save(update_fields=updated_fields)
        return existing_task

    return PeriodicTask.objects.create(
        name=(
            f"{JELLYFIN_PUSH_TASK_NAME} for "
            f"{jellyfin_account.jellyfin_username or user.username} "
            f"(every {JELLYFIN_PUSH_INTERVAL_MINUTES} minutes)"
        ),
        task=JELLYFIN_PUSH_TASK_NAME,
        interval=interval,
        kwargs=json.dumps({"user_id": user.id}),
        start_time=next_interval_start,
        enabled=True,
    )


def _disable_jellyfin_push_schedule(user):
    """Delete any per-user Jellyfin push periodic tasks."""
    from django_celery_beat.models import PeriodicTask

    return PeriodicTask.objects.filter(
        _plex_watchlist_task_filter(user.id),
        task=JELLYFIN_PUSH_TASK_NAME,
    ).delete()


def _ensure_arr_schedule(user, task_name, source_label):
    """Create or enable the per-user Radarr/Sonarr recurring schedule."""
    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    next_sync_start = _next_arr_sync_start()
    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute=0,
        hour=f"*/{ARR_SYNC_INTERVAL_HOURS}",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        timezone=timezone.get_default_timezone(),
    )
    task_filter = PeriodicTask.objects.filter(
        _periodic_task_filter_for_user(user.id),
        task=task_name,
    )
    existing_task = task_filter.first()
    if existing_task:
        was_enabled = existing_task.enabled
        updated_fields = []
        desired_name = (
            f"Import from {source_label} for {user.username} "
            f"(every {ARR_SYNC_INTERVAL_HOURS} hours)"
        )
        desired_kwargs = json.dumps({"user_id": user.id})
        if existing_task.name != desired_name:
            existing_task.name = desired_name
            updated_fields.append("name")
        if existing_task.crontab_id != crontab.id:
            existing_task.crontab = crontab
            updated_fields.append("crontab")
        if existing_task.interval_id is not None:
            existing_task.interval = None
            updated_fields.append("interval")
        if existing_task.clocked_id is not None:
            existing_task.clocked = None
            updated_fields.append("clocked")
        if existing_task.solar_id is not None:
            existing_task.solar = None
            updated_fields.append("solar")
        if existing_task.one_off:
            existing_task.one_off = False
            updated_fields.append("one_off")
        if existing_task.kwargs != desired_kwargs:
            existing_task.kwargs = desired_kwargs
            updated_fields.append("kwargs")
        if not existing_task.enabled:
            existing_task.enabled = True
            updated_fields.append("enabled")
        if existing_task.start_time is None or not was_enabled:
            existing_task.start_time = next_sync_start
            updated_fields.append("start_time")
        if updated_fields:
            existing_task.save(update_fields=updated_fields)
        return existing_task

    return PeriodicTask.objects.create(
        name=(
            f"Import from {source_label} for {user.username} "
            f"(every {ARR_SYNC_INTERVAL_HOURS} hours)"
        ),
        task=task_name,
        crontab=crontab,
        kwargs=json.dumps({"user_id": user.id}),
        start_time=next_sync_start,
        enabled=True,
    )


def _ensure_lastfm_poll_schedule():
    """Create or update the shared Last.fm polling schedule."""
    from django_celery_beat.models import IntervalSchedule, PeriodicTask

    poll_interval_minutes = getattr(settings, "LASTFM_POLL_INTERVAL_MINUTES", 15)
    interval, _ = IntervalSchedule.objects.get_or_create(
        every=poll_interval_minutes,
        period=IntervalSchedule.MINUTES,
    )
    task_name = f"Poll Last.fm for all users (every {poll_interval_minutes} minutes)"
    existing_task = PeriodicTask.objects.filter(
        task="Poll Last.fm for all users"
    ).first()

    if existing_task:
        updated_fields = []
        if existing_task.name != task_name:
            existing_task.name = task_name
            updated_fields.append("name")
        if existing_task.interval_id != interval.id:
            existing_task.interval = interval
            updated_fields.append("interval")
        if not existing_task.enabled:
            existing_task.enabled = True
            updated_fields.append("enabled")
        if existing_task.start_time is None:
            existing_task.start_time = timezone.now()
            updated_fields.append("start_time")
        if updated_fields:
            existing_task.save(update_fields=updated_fields)
        return existing_task, poll_interval_minutes

    return PeriodicTask.objects.create(
        name=task_name,
        task="Poll Last.fm for all users",
        interval=interval,
        start_time=timezone.now(),
        enabled=True,
    ), poll_interval_minutes


def _save_lastfm_history_reset(account, cutoff_uts: int):
    """Persist a fresh Last.fm history import state."""
    account.reset_history_import(cutoff_uts)
    account.save(
        update_fields=[
            "history_import_status",
            "history_import_cutoff_uts",
            "history_import_next_page",
            "history_import_total_pages",
            "history_import_started_at",
            "history_import_completed_at",
            "history_import_last_error_message",
        ],
    )


@require_POST
def trakt_oauth(request):
    """View for initiating Trakt OAuth2 authorization flow."""
    redirect_uri = app_helpers.build_absolute_app_url(
        request,
        reverse("import_trakt_private"),
    )
    url = "https://trakt.tv/oauth/authorize"
    state = {
        "mode": request.POST["mode"],
        "frequency": request.POST["frequency"],
        "time": request.POST["time"],
        "redirect_uri": redirect_uri,
        "return_to": request.POST.get("next"),
    }
    state_token = secrets.token_urlsafe(32)
    request.session[state_token] = state
    return redirect(
        f"{url}?client_id={settings.TRAKT_API}&redirect_uri={redirect_uri}&response_type=code&state={state_token}",
    )


@require_GET
def import_trakt_private(request):
    """View for handling Trakt OAuth2 callback and scheduling private import."""
    state_token = request.GET["state"]
    redirect_uri = request.session[state_token].get("redirect_uri")
    oauth_callback = trakt.handle_oauth_callback(request, redirect_uri=redirect_uri)
    enc_token = helpers.encrypt(oauth_callback["refresh_token"])

    frequency = request.session[state_token]["frequency"]
    mode = request.session[state_token]["mode"]
    import_time = request.session[state_token]["time"]
    return_to = request.session[state_token].get("return_to")

    if frequency == "once":
        tasks.import_trakt.delay(
            token=enc_token,
            user_id=request.user.id,
            mode=mode,
            username=oauth_callback["username"],
        )
        messages.info(request, "The task to import media from Trakt has been queued.")
    else:
        helpers.create_import_schedule(
            oauth_callback["username"],
            request,
            mode,
            frequency,
            import_time,
            "Trakt",
            token=enc_token,
        )
    return _integration_redirect(request, connected_slug="trakt", next_url=return_to)


@require_POST
def import_trakt_public(request):
    """View for importing Trakt data using public username."""
    username = request.POST.get("user")
    if not username:
        messages.error(request, "Trakt username is required.")
        return _integration_redirect(request)

    mode = request.POST["mode"]
    frequency = request.POST["frequency"]
    import_time = request.POST["time"]

    if frequency == "once":
        tasks.import_trakt.delay(
            user_id=request.user.id,
            mode=mode,
            username=username,
        )
        messages.info(request, "The task to import media from Trakt has been queued.")
    else:
        helpers.create_import_schedule(
            username=username,
            request=request,
            mode=mode,
            frequency=frequency,
            import_time=import_time,
            source="Trakt",
        )
    return _integration_redirect(request, connected_slug="trakt")


@require_POST
def import_mdblist(request):
    """View for importing MDBList tracking data (watched, ratings, etc.)."""
    mode = request.POST["mode"]
    frequency = request.POST["frequency"]
    import_time = request.POST["time"]
    api_key = request.POST.get("api_key", "").strip()

    account = MDBListAccount.objects.filter(user=request.user).first()
    if api_key:
        try:
            mdblist.validate_api_key(api_key)
        except helpers.MediaImportError:
            messages.error(
                request,
                "Could not validate the MDBList API key. Check it and try again.",
            )
            return _integration_redirect(request)
        account, _ = MDBListAccount.objects.update_or_create(
            user=request.user,
            defaults={
                "api_key": helpers.encrypt(api_key),
                "connection_broken": False,
                "last_error_message": "",
            },
        )
    elif account is None:
        messages.error(request, "An MDBList API key is required.")
        return _integration_redirect(request)

    if frequency == "once":
        tasks.import_mdblist.delay(user_id=request.user.id, mode=mode)
        messages.info(request, "The task to import media from MDBList has been queued.")
    else:
        helpers.create_import_schedule(
            username=request.user.username,
            request=request,
            mode=mode,
            frequency=frequency,
            import_time=import_time,
            source="MDBList",
        )
    return _integration_redirect(request, connected_slug="mdblist")


@require_POST
def plex_connect(request):
    """Initiate Plex authentication via the pin-based flow."""
    redirect_uri = app_helpers.build_absolute_app_url(request, reverse("plex_callback"))
    state_token = secrets.token_urlsafe(16)

    try:
        pin = plex_api.create_pin()
    except plex_api.PlexClientError as exc:
        messages.error(request, f"Could not start Plex connection: {exc}")
        return _integration_redirect(request)
    except Exception as exc:  # pragma: no cover - defensive
        messages.error(request, f"Unexpected Plex error: {exc}")
        return _integration_redirect(request)

    request.session[state_token] = {
        "plex_pin_id": pin["id"],
        "plex_pin_code": pin["code"],
        "return_to": request.POST.get("next"),
    }

    auth_url = plex_api.build_auth_url(
        pin["code"], f"{redirect_uri}?state={state_token}"
    )
    return redirect(auth_url)


@require_GET
def plex_callback(request):
    """Handle Plex auth callback and persist the token."""
    state_token = request.GET.get("state")
    state_data = request.session.pop(state_token, None)

    if not state_data:
        messages.error(request, "Invalid or expired Plex authorization request.")
        return _integration_redirect(request)

    return_to = state_data.get("return_to")

    pin_id = state_data.get("plex_pin_id")
    try:
        plex_token = plex_api.poll_pin(pin_id)
    except plex_api.PlexAuthError as exc:
        messages.error(request, f"Plex authorization failed: {exc}")
        return _integration_redirect(request, next_url=return_to)
    except plex_api.PlexClientError as exc:  # pragma: no cover - defensive
        messages.error(request, f"Could not complete Plex authorization: {exc}")
        return _integration_redirect(request, next_url=return_to)
    except Exception as exc:  # pragma: no cover - defensive
        messages.error(request, f"Unexpected Plex response: {exc}")
        return _integration_redirect(request, next_url=return_to)

    try:
        account = plex_api.fetch_account(plex_token)
    except plex_api.PlexAuthError as exc:
        messages.error(request, f"Plex rejected the token: {exc}")
        return _integration_redirect(request, next_url=return_to)
    except plex_api.PlexClientError as exc:  # pragma: no cover - defensive
        messages.error(request, f"Could not read Plex account details: {exc}")
        return _integration_redirect(request, next_url=return_to)
    except Exception as exc:  # pragma: no cover - defensive
        messages.error(request, f"Unexpected Plex account response: {exc}")
        return _integration_redirect(request, next_url=return_to)

    sections: list[dict] = []
    try:
        sections = plex_api.list_sections(plex_token)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "Connected to Plex but could not fetch libraries: %s",
            exception_summary(exc),
        )
        messages.warning(
            request,
            "Connected to Plex, but could not load libraries yet. You can refresh from the import page.",
        )

    # Keep webhook allow list in sync
    username = (account.get("username") or "").strip()
    if username:
        existing = [
            u.strip()
            for u in (request.user.plex_usernames or "").split(",")
            if u.strip()
        ]
        if username.lower() not in [u.lower() for u in existing]:
            request.user.plex_usernames = ", ".join([*existing, username])
            request.user.save(update_fields=["plex_usernames"])

    defaults = {
        "plex_token": plex_token,
        "plex_username": account.get("username") or "",
        "plex_account_id": account.get("id") or "",
        "sections": sections,
        "sections_refreshed_at": timezone.now(),
    }

    if sections:
        defaults["server_name"] = sections[0].get("server_name")
        defaults["machine_identifier"] = sections[0].get("machine_identifier")

    PlexAccount.objects.update_or_create(
        user=request.user,
        defaults=defaults,
    )

    account_username = account.get("username") or "your Plex account"
    messages.success(request, f"Connected to Plex as {account_username}.")

    if return_to:
        # Arrived from the setup wizard: queue a sensible default import
        # rather than requiring a second visit to pick a library/mode.
        tasks.import_plex.delay(user_id=request.user.id, mode="new", library="all")

    return _integration_redirect(request, connected_slug="plex", next_url=return_to)


@require_POST
def plex_disconnect(request):
    """Remove stored Plex credentials."""
    _disable_plex_watchlist_schedule(request.user)
    PlexAccount.objects.filter(user=request.user).delete()
    messages.info(request, "Disconnected Plex.")
    return redirect("import_data")


@require_POST
def import_plex(request):
    """Queue a Plex history import for the current user."""
    plex_account = getattr(request.user, "plex_account", None)
    if not plex_account:
        messages.error(request, "Connect Plex before importing.")
        return redirect("import_data")

    library = request.POST.get("library") or "all"
    mode = request.POST.get("mode", "new")
    frequency = request.POST.get("frequency", "once")
    import_time = request.POST.get("time", "00:00")
    raw_usernames = request.POST.get("plex_usernames", "")

    _save_plex_usernames(request.user, raw_usernames)

    if mode == "watchlist":
        _ensure_plex_watchlist_schedule(request.user, plex_account)
        plex_account.watchlist_sync_enabled = True
        plex_account.save(update_fields=["watchlist_sync_enabled"])
        tasks.sync_plex_watchlist.delay(
            user_id=request.user.id,
            mode="watchlist",
        )
        messages.info(
            request,
            (
                "Plex watchlist sync queued. "
                f"Recurring syncs will run every {WATCHLIST_SYNC_INTERVAL_MINUTES} minutes."
            ),
        )
        return redirect("import_data")

    # Handle "update_collection" mode separately
    if mode == "update_collection":
        if frequency != "once":
            messages.error(
                request, "Collection update mode only supports one-time execution."
            )
            return redirect("import_data")

        tasks.update_collection_metadata_from_plex.delay(
            library=library,
            user_id=request.user.id,
        )
        messages.info(
            request, "The task to update collection metadata from Plex has been queued."
        )
        return redirect("import_data")

    if frequency != "once":
        helpers.create_import_schedule(
            username=plex_account.plex_username or request.user.username,
            request=request,
            mode=mode,
            frequency=frequency,
            import_time=import_time,
            source="Plex",
            extra_kwargs={"library": library},
        )
        return redirect("import_data")

    tasks.import_plex.delay(
        library=library,
        user_id=request.user.id,
        mode=mode,
    )
    messages.info(request, "The task to import media from Plex has been queued.")
    return redirect("import_data")


@require_POST
def plex_disable_watchlist(request):
    """Disable recurring Plex watchlist sync for the current user."""
    plex_account = getattr(request.user, "plex_account", None)
    if not plex_account:
        messages.error(request, "Connect Plex before changing watchlist sync.")
        return redirect("import_data")

    _disable_plex_watchlist_schedule(request.user)
    if plex_account.watchlist_sync_enabled:
        plex_account.watchlist_sync_enabled = False
        plex_account.save(update_fields=["watchlist_sync_enabled"])

    messages.info(request, "Disabled Plex watchlist sync.")
    return redirect("import_data")


@require_POST
def simkl_oauth(request):
    """View for initiating the SIMKL OAuth2 authorization flow."""
    redirect_uri = app_helpers.build_absolute_app_url(
        request,
        reverse("import_simkl_private"),
    )
    url = "https://simkl.com/oauth/authorize"

    state = {
        "mode": request.POST["mode"],
        "frequency": request.POST["frequency"],
        "time": request.POST["time"],
        "anime_destination": request.POST.get("anime_destination", "anime"),
        "redirect_uri": redirect_uri,
        "return_to": request.POST.get("next"),
    }
    state_token = secrets.token_urlsafe(32)
    request.session[state_token] = state

    return redirect(
        f"{url}?client_id={settings.SIMKL_ID}&redirect_uri={redirect_uri}&response_type=code&state={state_token}",
    )


@require_GET
def import_simkl_private(request):
    """View for getting the SIMKL OAuth2 token."""
    state_token = request.GET["state"]
    redirect_uri = request.session[state_token].get("redirect_uri")
    oauth_callback = simkl.get_token(request, redirect_uri=redirect_uri)
    enc_token = helpers.encrypt(oauth_callback["access_token"])

    frequency = request.session[state_token]["frequency"]
    mode = request.session[state_token]["mode"]
    import_time = request.session[state_token]["time"]
    anime_destination = request.session[state_token].get("anime_destination", "anime")
    return_to = request.session[state_token].get("return_to")

    if frequency == "once":
        tasks.import_simkl.delay(
            token=enc_token,
            user_id=request.user.id,
            mode=mode,
            anime_destination=anime_destination,
        )
        messages.info(request, "The task to import media from Simkl has been queued.")
    else:
        helpers.create_import_schedule(
            oauth_callback["username"],
            request,
            mode,
            frequency,
            import_time,
            "SIMKL",
            token=enc_token,
            extra_kwargs={"anime_destination": anime_destination},
        )

    return _integration_redirect(request, connected_slug="simkl", next_url=return_to)


@require_POST
def import_mal(request):
    """View for importing anime and manga data from MyAnimeList."""
    username = request.POST.get("user")
    if not username:
        messages.error(request, "MyAnimeList username is required.")
        return _integration_redirect(request)

    mode = request.POST["mode"]
    frequency = request.POST["frequency"]

    if frequency == "once":
        tasks.import_mal.delay(username=username, user_id=request.user.id, mode=mode)
        messages.info(
            request,
            "The task to import media from MyAnimeList has been queued.",
        )
    else:
        import_time = request.POST["time"]
        helpers.create_import_schedule(
            username,
            request,
            mode,
            frequency,
            import_time,
            "MyAnimeList",
        )
    return _integration_redirect(request, connected_slug="myanimelist")


@require_POST
def anilist_oauth(request):
    """Initiate AniList OAuth flow."""
    redirect_uri = app_helpers.build_absolute_app_url(
        request,
        reverse("import_anilist_private"),
    )
    url = "https://anilist.co/api/v2/oauth/authorize"
    state = {
        "mode": request.POST["mode"],
        "frequency": request.POST["frequency"],
        "time": request.POST["time"],
        "redirect_uri": redirect_uri,
        "return_to": request.POST.get("next"),
    }

    state_token = secrets.token_urlsafe(32)
    request.session[state_token] = state

    return redirect(
        f"{url}?client_id={settings.ANILIST_ID}&redirect_uri={redirect_uri}&response_type=code&state={state_token}",
    )


@require_GET
def import_anilist_private(request):
    """View for getting the AniList OAuth2 token."""
    state_token = request.GET["state"]
    redirect_uri = request.session[state_token].get("redirect_uri")
    oauth_callback = anilist.get_token(request, redirect_uri=redirect_uri)
    enc_token = helpers.encrypt(oauth_callback["access_token"])
    username = oauth_callback["username"]
    return_to = request.session[state_token].get("return_to")

    if not username:
        messages.error(request, "AniList username is required.")
        return _integration_redirect(request, next_url=return_to)

    frequency = request.session[state_token]["frequency"]
    mode = request.session[state_token]["mode"]
    import_time = request.session[state_token]["time"]

    if frequency == "once":
        tasks.import_anilist.delay(
            user_id=request.user.id,
            mode=mode,
            username=username,
            token=enc_token,
        )
        messages.info(request, "AniList import queued.")
    else:
        helpers.create_import_schedule(
            username=username,
            request=request,
            mode=mode,
            frequency=frequency,
            import_time=import_time,
            source="AniList",
            token=enc_token,
        )
    return _integration_redirect(request, connected_slug="anilist", next_url=return_to)


@require_POST
def import_anilist_public(request):
    """View for importing anime and manga data from AniList."""
    username = request.POST.get("user")
    if not username:
        messages.error(request, "AniList username is required.")
        return redirect("import_data")

    mode = request.POST["mode"]
    frequency = request.POST["frequency"]
    import_time = request.POST["time"]

    if frequency == "once":
        tasks.import_anilist.delay(
            user_id=request.user.id,
            mode=mode,
            username=username,
        )
        messages.info(request, "AniList import queued.")
    else:
        helpers.create_import_schedule(
            username=username,
            request=request,
            mode=mode,
            frequency=frequency,
            import_time=import_time,
            source="AniList",
        )
    return redirect("import_data")


@require_POST
def import_kitsu(request):
    """View for importing anime and manga data from Kitsu by user ID."""
    kitsu_id = request.POST.get("user")
    if not kitsu_id:
        messages.error(request, "Kitsu user ID is required.")
        return _integration_redirect(request)

    mode = request.POST["mode"]
    frequency = request.POST["frequency"]

    if frequency == "once":
        tasks.import_kitsu.delay(username=kitsu_id, user_id=request.user.id, mode=mode)
        messages.info(request, "The task to import media from Kitsu has been queued.")
    else:
        import_time = request.POST["time"]
        helpers.create_import_schedule(
            kitsu_id,
            request,
            mode,
            frequency,
            import_time,
            "Kitsu",
        )
    return _integration_redirect(request, connected_slug="kitsu")


@require_POST
def import_yamtrack(request):
    """View for importing a Floppy backup or an upstream Yamtrack CSV."""
    file = request.FILES.get("yamtrack_csv")

    if not file:
        messages.error(request, "A CSV file is required.")
        return _integration_redirect(request)

    mode = request.POST["mode"]
    tasks.import_yamtrack.delay(
        user_id=request.user.id,
        file=_read_uploaded_file(file),
        mode=mode,
    )
    messages.info(
        request,
        "The task to import media from the CSV file has been queued.",
    )
    return _integration_redirect(request, connected_slug="yamtrack")


@require_POST
def import_trakt_export_file(request):
    """View for importing a Trakt data export: a .zip, loose .json files, or a .csv.

    Trakt now exports a .zip of flat .json files, but the older community CSV
    format is still accepted. Loose .json uploads are repackaged into an
    in-memory zip so the Celery task always receives a single blob of bytes.
    """
    uploads = request.FILES.getlist("trakt_export") or request.FILES.getlist(
        "trakt_collection_csv",
    )

    if not uploads:
        messages.error(request, "A Trakt export file is required.")
        return _integration_redirect(request)

    total_size = sum(upload.size for upload in uploads)
    if total_size > TRAKT_EXPORT_MAX_UPLOAD_BYTES:
        messages.error(
            request,
            "That Trakt export is too large to import "
            f"(limit {TRAKT_EXPORT_MAX_UPLOAD_BYTES // (1024 * 1024)} MB).",
        )
        return _integration_redirect(request)

    mode = request.POST["mode"]
    payloads = [(upload.name, _read_uploaded_file(upload)) for upload in uploads]

    if len(payloads) == 1 and not _is_trakt_export_payload(*payloads[0]):
        tasks.import_trakt_collection_csv.delay(
            user_id=request.user.id,
            file=payloads[0][1],
            mode=mode,
        )
        messages.info(
            request,
            "The task to import collection data from the Trakt CSV file has been "
            "queued.",
        )
        return _integration_redirect(request, connected_slug="trakt")

    tasks.import_trakt_export.delay(
        user_id=request.user.id,
        file=_build_trakt_export_archive(payloads),
        mode=mode,
    )
    messages.info(
        request,
        "The task to import your Trakt data export has been queued.",
    )
    return _integration_redirect(request, connected_slug="trakt")


def _is_trakt_export_payload(name, content):
    """Whether an upload is part of the JSON/zip export rather than the legacy CSV."""
    return name.lower().endswith((".zip", ".json")) or content[:4] == b"PK\x03\x04"


def _build_trakt_export_archive(payloads):
    """Return export bytes: the zip as uploaded, or loose .json files zipped up."""
    if len(payloads) == 1 and payloads[0][1][:4] == b"PK\x03\x04":
        return payloads[0][1]

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in payloads:
            archive.writestr(name.rsplit("/", 1)[-1], content)
    return buffer.getvalue()


@require_POST
def import_hltb(request):
    """View for importing game date from HowLongToBeat."""
    file = request.FILES.get("hltb_csv")

    if not file:
        messages.error(request, "HowLongToBeat CSV file is required.")
        return _integration_redirect(request)

    mode = request.POST["mode"]
    tasks.import_hltb.delay(
        user_id=request.user.id,
        file=_read_uploaded_file(file),
        mode=mode,
    )
    messages.info(
        request,
        "The task to import media from HowLongToBeat CSV file has been queued.",
    )
    return _integration_redirect(request, connected_slug="hltb")


@require_POST
def import_grouvee(request):
    """View for importing game data from a Grouvee JSON export."""
    file = request.FILES.get("grouvee_json")

    if not file:
        messages.error(request, "Grouvee JSON file is required.")
        return _integration_redirect(request)

    mode = request.POST["mode"]
    tasks.import_grouvee.delay(
        user_id=request.user.id,
        file=_read_uploaded_file(file),
        mode=mode,
    )
    messages.info(
        request,
        "The task to import media from Grouvee JSON file has been queued.",
    )
    return _integration_redirect(request, connected_slug="grouvee")


@require_POST
def import_steam(request):
    """View for importing game data from Steam."""
    steam_id = request.POST.get("user")
    if not steam_id:
        messages.error(request, "Steam ID is required.")
        return _integration_redirect(request)

    mode = request.POST["mode"]
    frequency = request.POST["frequency"]

    if frequency == "once":
        tasks.import_steam.delay(username=steam_id, user_id=request.user.id, mode=mode)
        messages.info(request, "The task to import media from Steam has been queued.")
    else:
        import_time = request.POST["time"]
        helpers.create_import_schedule(
            steam_id,
            request,
            mode,
            frequency,
            import_time,
            "Steam",
        )
    return _integration_redirect(request, connected_slug="steam")


@require_POST
def radarr_connect(request):
    """Connect Radarr account using base URL + API key."""
    base_url = request.POST.get("base_url", "").strip()
    api_key = request.POST.get("api_key", "").strip()
    if not base_url or not api_key:
        messages.error(request, "Radarr base URL and API key are required.")
        return _integration_redirect(request)

    try:
        RadarrClient(base_url, api_key).healthcheck()
    except (helpers.MediaImportError, requests.RequestException) as exc:
        messages.error(request, f"Failed to connect to Radarr: {exc}")
        return _integration_redirect(request)

    RadarrAccount.objects.update_or_create(
        user=request.user,
        defaults={
            "base_url": base_url,
            "api_key": helpers.encrypt(api_key),
            "connection_broken": False,
            "last_error_message": "",
        },
    )
    _ensure_arr_schedule(request.user, RADARR_RECURRING_TASK_NAME, "Radarr")
    tasks.import_radarr.delay(user_id=request.user.id, mode="new")
    messages.success(
        request,
        "Connected Radarr. Initial import queued and recurring sync enabled.",
    )
    return _integration_redirect(request, connected_slug="radarr")


@require_POST
def radarr_disconnect(request):
    """Disconnect Radarr integration."""
    from django_celery_beat.models import PeriodicTask

    PeriodicTask.objects.filter(
        _periodic_task_filter_for_user(request.user.id),
        task=RADARR_RECURRING_TASK_NAME,
    ).delete()
    RadarrAccount.objects.filter(user=request.user).delete()
    messages.info(request, "Disconnected Radarr.")
    return redirect("import_data")


@require_POST
def import_radarr(request):
    """Queue Radarr import and ensure recurring schedule exists."""
    account = getattr(request.user, "radarr_account", None)
    if not account:
        messages.error(request, "Connect Radarr before importing.")
        return redirect("import_data")

    tasks.import_radarr.delay(user_id=request.user.id, mode="new")
    _ensure_arr_schedule(request.user, RADARR_RECURRING_TASK_NAME, "Radarr")
    messages.info(request, "Radarr import queued.")
    return redirect("import_data")


@require_POST
def sonarr_connect(request):
    """Connect Sonarr account using base URL + API key."""
    base_url = request.POST.get("base_url", "").strip()
    api_key = request.POST.get("api_key", "").strip()
    if not base_url or not api_key:
        messages.error(request, "Sonarr base URL and API key are required.")
        return _integration_redirect(request)

    try:
        SonarrClient(base_url, api_key).healthcheck()
    except (helpers.MediaImportError, requests.RequestException) as exc:
        messages.error(request, f"Failed to connect to Sonarr: {exc}")
        return _integration_redirect(request)

    SonarrAccount.objects.update_or_create(
        user=request.user,
        defaults={
            "base_url": base_url,
            "api_key": helpers.encrypt(api_key),
            "connection_broken": False,
            "last_error_message": "",
        },
    )
    _ensure_arr_schedule(request.user, SONARR_RECURRING_TASK_NAME, "Sonarr")
    tasks.import_sonarr.delay(user_id=request.user.id, mode="new")
    messages.success(
        request,
        "Connected Sonarr. Initial import queued and recurring sync enabled.",
    )
    return _integration_redirect(request, connected_slug="sonarr")


@require_POST
def sonarr_disconnect(request):
    """Disconnect Sonarr integration."""
    from django_celery_beat.models import PeriodicTask

    PeriodicTask.objects.filter(
        _periodic_task_filter_for_user(request.user.id),
        task=SONARR_RECURRING_TASK_NAME,
    ).delete()
    SonarrAccount.objects.filter(user=request.user).delete()
    messages.info(request, "Disconnected Sonarr.")
    return redirect("import_data")


@require_POST
def import_sonarr(request):
    """Queue Sonarr import and ensure recurring schedule exists."""
    account = getattr(request.user, "sonarr_account", None)
    if not account:
        messages.error(request, "Connect Sonarr before importing.")
        return redirect("import_data")

    tasks.import_sonarr.delay(user_id=request.user.id, mode="new")
    _ensure_arr_schedule(request.user, SONARR_RECURRING_TASK_NAME, "Sonarr")
    messages.info(request, "Sonarr import queued.")
    return redirect("import_data")


@require_POST
def jellyfin_connect(request):
    """Connect a Jellyfin server using base URL + API key."""
    base_url = request.POST.get("base_url", "").strip()
    api_key = request.POST.get("api_key", "").strip()
    username = request.POST.get("username", "").strip()
    if not base_url or not api_key:
        messages.error(request, "Jellyfin base URL and API key are required.")
        return redirect("integrations")

    client = JellyfinClient(base_url, api_key)
    try:
        client.healthcheck()
        current_user = client.get_current_user()
        if not current_user and username:
            current_user = client.find_user_by_name(username)
    except (JellyfinAuthError, JellyfinClientError) as exc:
        messages.error(request, f"Failed to connect to Jellyfin: {exc}")
        return redirect("integrations")

    if not current_user or not current_user.get("Id"):
        messages.error(
            request,
            "Could not resolve a Jellyfin user for this API key. "
            "Dashboard API keys are not tied to a user, so enter the exact "
            "Jellyfin username in the username field and try again.",
        )
        return redirect("integrations")

    JellyfinAccount.objects.update_or_create(
        user=request.user,
        defaults={
            "base_url": base_url,
            "api_key": helpers.encrypt(api_key),
            "jellyfin_user_id": current_user["Id"],
            "jellyfin_username": current_user.get("Name", ""),
            "connection_broken": False,
            "last_error_message": "",
        },
    )
    messages.success(request, "Connected Jellyfin.")
    return redirect("integrations")


@require_POST
def jellyfin_disconnect(request):
    """Disconnect the Jellyfin integration."""
    _disable_jellyfin_push_schedule(request.user)
    JellyfinAccount.objects.filter(user=request.user).delete()
    messages.info(request, "Disconnected Jellyfin.")
    return redirect("integrations")


@require_POST
def jellyfin_settings(request):
    """Update Jellyfin push-sync toggles."""
    account = getattr(request.user, "jellyfin_account", None)
    if not account:
        messages.error(request, "Connect Jellyfin before changing sync settings.")
        return redirect("integrations")

    account.push_watched_enabled = "push_watched_enabled" in request.POST
    account.push_unwatched_enabled = "push_unwatched_enabled" in request.POST
    account.scheduled_push_enabled = "scheduled_push_enabled" in request.POST
    account.instant_push_enabled = "instant_push_enabled" in request.POST
    account.save(
        update_fields=[
            "push_watched_enabled",
            "push_unwatched_enabled",
            "scheduled_push_enabled",
            "instant_push_enabled",
        ],
    )

    if account.scheduled_push_enabled:
        _ensure_jellyfin_push_schedule(request.user, account)
    else:
        _disable_jellyfin_push_schedule(request.user)

    messages.success(request, "Jellyfin sync settings updated.")
    return redirect("integrations")


@require_POST
def jellyfin_push_now(request):
    """Queue an immediate Jellyfin watched-state push."""
    account = getattr(request.user, "jellyfin_account", None)
    if not account:
        messages.error(request, "Connect Jellyfin before syncing.")
        return redirect("integrations")

    tasks.push_jellyfin_watched.delay(user_id=request.user.id)
    messages.info(request, "Jellyfin sync queued.")
    return redirect("integrations")


def _ensure_audiobookshelf_schedule(user):
    """Create or update the recurring Audiobookshelf import schedule for a user."""
    from django_celery_beat.models import IntervalSchedule, PeriodicTask

    poll_interval_minutes = getattr(
        settings, "AUDIOBOOKSHELF_POLL_INTERVAL_MINUTES", 15
    )
    interval, _ = IntervalSchedule.objects.get_or_create(
        every=poll_interval_minutes,
        period=IntervalSchedule.MINUTES,
    )
    task_name = (
        f"Import from Audiobookshelf for {user.username} "
        f"(every {poll_interval_minutes} minutes)"
    )
    existing_task = PeriodicTask.objects.filter(
        task="Import from Audiobookshelf (Recurring)",
        kwargs__contains=f'"user_id": {user.id}',
    ).first()

    if existing_task:
        updated_fields = []
        if existing_task.name != task_name:
            existing_task.name = task_name
            updated_fields.append("name")
        if existing_task.interval_id != interval.id:
            existing_task.interval = interval
            updated_fields.append("interval")
        if existing_task.crontab_id is not None:
            existing_task.crontab = None
            updated_fields.append("crontab")
        if not existing_task.enabled:
            existing_task.enabled = True
            updated_fields.append("enabled")
        if updated_fields:
            existing_task.save(update_fields=updated_fields)
        return existing_task

    return PeriodicTask.objects.create(
        name=task_name,
        task="Import from Audiobookshelf (Recurring)",
        interval=interval,
        kwargs=json.dumps({"user_id": user.id}),
        start_time=timezone.now(),
        enabled=True,
    )


@require_POST
def audiobookshelf_connect(request):
    """Connect Audiobookshelf account using base URL + API token."""
    base_url = request.POST.get("base_url", "").strip()
    api_token = request.POST.get("api_token", "").strip()

    if not base_url or not api_token:
        messages.error(request, "Audiobookshelf base URL and API token are required.")
        return _integration_redirect(request)

    try:
        client = AudiobookshelfClient(base_url, api_token)
        client.get_me()
    except AudiobookshelfAuthError as exc:
        messages.error(request, str(exc))
        return _integration_redirect(request)
    except Exception as exc:
        messages.error(request, f"Failed to connect to Audiobookshelf: {exc}")
        return _integration_redirect(request)

    AudiobookshelfAccount.objects.update_or_create(
        user=request.user,
        defaults={
            "base_url": base_url,
            "api_token": helpers.encrypt(api_token),
            "connection_broken": False,
            "last_error_message": "",
        },
    )

    _ensure_audiobookshelf_schedule(request.user)
    tasks.import_audiobookshelf.delay(user_id=request.user.id, mode="new")
    messages.success(request, "Connected Audiobookshelf. Initial import queued.")
    return _integration_redirect(request, connected_slug="audiobookshelf")


@require_POST
def audiobookshelf_disconnect(request):
    """Disconnect Audiobookshelf integration."""
    from django_celery_beat.models import PeriodicTask

    PeriodicTask.objects.filter(
        task="Import from Audiobookshelf (Recurring)",
        kwargs__contains=f'"user_id": {request.user.id}',
    ).delete()
    AudiobookshelfAccount.objects.filter(user=request.user).delete()
    messages.info(request, "Disconnected Audiobookshelf.")
    return redirect("import_data")


@require_POST
def import_audiobookshelf(request):
    """Queue Audiobookshelf import and ensure recurring schedule exists."""
    account = getattr(request.user, "audiobookshelf_account", None)
    if not account:
        messages.error(request, "Connect Audiobookshelf before importing.")
        return redirect("import_data")

    tasks.import_audiobookshelf.delay(user_id=request.user.id, mode="new")
    _ensure_audiobookshelf_schedule(request.user)

    messages.info(request, "Audiobookshelf import queued.")
    return redirect("import_data")


STORYTELLER_RECURRING_TASK_NAME = "Import from Storyteller (Recurring)"
STORYTELLER_PENDING_SESSION_KEY = "storyteller_pending_auth"


def _fix_storyteller_uri(uri, base_url):
    """Rewrite a verification URI's host to the configured server URL.

    Storyteller may return verification URLs with an internal host/port
    (e.g. 0.0.0.0:80); keep only the path and re-root it on the server URL.
    """
    if not uri:
        return uri
    match = re.match(r"^https?://[^/]+(/.*)$", uri) or re.match(r"^(/.*)$", uri)
    if match:
        return base_url + match.group(1)
    return uri


def _ensure_storyteller_schedule(user):
    """Create the recurring Storyteller import schedule if missing."""
    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    existing_task = PeriodicTask.objects.filter(
        task=STORYTELLER_RECURRING_TASK_NAME,
        kwargs__contains=f'"user_id": {user.id}',
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
        name=f"Import from Storyteller for {user.username} (every 2 hours)",
        task=STORYTELLER_RECURRING_TASK_NAME,
        crontab=crontab,
        kwargs=json.dumps({"user_id": user.id}),
        start_time=timezone.now(),
        enabled=True,
    )


@require_POST
def storyteller_connect(request):
    """Begin the Storyteller device-code login flow."""
    server_url = request.POST.get("server_url", "").strip().rstrip("/")
    if not server_url:
        messages.error(request, "Storyteller server URL is required.")
        return _integration_redirect(request)

    try:
        data = StorytellerClient(server_url).start_device_auth()
    except StorytellerClientError as exc:
        messages.error(request, str(exc))
        return _integration_redirect(request)
    except Exception as exc:
        messages.error(request, f"Failed to reach Storyteller: {exc}")
        return _integration_redirect(request)

    device_code = data.get("device_code")
    if not device_code:
        messages.error(request, "Storyteller did not return a device code.")
        return _integration_redirect(request)

    expires_in = int(data.get("expires_in") or 600)
    request.session[STORYTELLER_PENDING_SESSION_KEY] = {
        "server_url": server_url,
        "device_code": device_code,
        "user_code": data.get("user_code") or "",
        "verification_uri": _fix_storyteller_uri(
            data.get("verification_uri"), server_url
        ),
        "verification_uri_complete": _fix_storyteller_uri(
            data.get("verification_uri_complete"),
            server_url,
        ),
        "interval": int(data.get("interval") or 5),
        "expires_at": (timezone.now() + timedelta(seconds=expires_in)).isoformat(),
    }
    request.session.modified = True
    messages.info(
        request, "Approve the login on your Storyteller server to finish connecting."
    )
    return redirect("import_data")


@require_GET
def storyteller_poll(request):
    """Poll Storyteller for the access token during device login."""
    pending = request.session.get(STORYTELLER_PENDING_SESSION_KEY)
    if not pending:
        return JsonResponse({"status": "idle"})

    expires_at = pending.get("expires_at")
    if expires_at and timezone.now() > datetime.fromisoformat(expires_at):
        request.session.pop(STORYTELLER_PENDING_SESSION_KEY, None)
        return JsonResponse({"status": "expired"})

    client = StorytellerClient(pending["server_url"])
    try:
        data, status_code = client.poll_device_token(pending["device_code"])
    except Exception as exc:
        return JsonResponse({"status": "pending", "detail": str(exc)})

    access_token = data.get("access_token") if isinstance(data, dict) else None
    if access_token:
        StorytellerAccount.objects.update_or_create(
            user=request.user,
            defaults={
                "server_url": pending["server_url"],
                "auth_token": helpers.encrypt(access_token),
                "connection_broken": False,
                "last_error_message": "",
            },
        )
        request.session.pop(STORYTELLER_PENDING_SESSION_KEY, None)
        tasks.import_storyteller.delay(user_id=request.user.id, mode="new")
        _ensure_storyteller_schedule(request.user)
        return JsonResponse({"status": "connected"})

    error = data.get("error") if isinstance(data, dict) else None
    if (
        error in ("authorization_pending", "slow_down")
        or status_code == HTTPStatus.BAD_REQUEST
    ):
        return JsonResponse({"status": "pending"})

    request.session.pop(STORYTELLER_PENDING_SESSION_KEY, None)
    return JsonResponse({"status": "error", "message": error or "Login failed."})


@require_POST
def storyteller_cancel(request):
    """Cancel an in-progress Storyteller device login."""
    request.session.pop(STORYTELLER_PENDING_SESSION_KEY, None)
    messages.info(request, "Storyteller login cancelled.")
    return redirect("import_data")


@require_POST
def storyteller_disconnect(request):
    """Disconnect the Storyteller integration."""
    from django_celery_beat.models import PeriodicTask

    PeriodicTask.objects.filter(
        task=STORYTELLER_RECURRING_TASK_NAME,
        kwargs__contains=f'"user_id": {request.user.id}',
    ).delete()
    StorytellerAccount.objects.filter(user=request.user).delete()
    messages.info(request, "Disconnected Storyteller.")
    return redirect("import_data")


@require_POST
def import_storyteller(request):
    """Queue a Storyteller import and ensure the recurring schedule exists."""
    account = getattr(request.user, "storyteller_account", None)
    if not account:
        messages.error(request, "Connect Storyteller before importing.")
        return redirect("import_data")

    tasks.import_storyteller.delay(user_id=request.user.id, mode="new")
    _ensure_storyteller_schedule(request.user)
    messages.info(request, "Storyteller import queued.")
    return redirect("import_data")


STREMIO_RECURRING_TASK_NAME = "Import from Stremio (Recurring)"


def _ensure_stremio_schedule(user):
    """Create the recurring Stremio import schedule if missing."""
    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    existing_task = PeriodicTask.objects.filter(
        task=STREMIO_RECURRING_TASK_NAME,
        kwargs__contains=f'"user_id": {user.id}',
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

    StremioAccount.objects.update_or_create(
        user=request.user,
        defaults={
            "auth_key": helpers.encrypt(auth_key),
            "email": helpers.encrypt(email) if email else "",
            "connection_broken": False,
            "last_error_message": "",
        },
    )
    tasks.import_stremio.delay(user_id=request.user.id, mode="new")
    _ensure_stremio_schedule(request.user)
    messages.success(
        request,
        "Connected to Stremio. Initial import queued; your library will sync every 2 hours.",
    )
    return _integration_redirect(request, connected_slug="stremio")


@require_POST
def stremio_disconnect(request):
    """Disconnect the Stremio integration."""
    from django_celery_beat.models import PeriodicTask

    PeriodicTask.objects.filter(
        task=STREMIO_RECURRING_TASK_NAME,
        kwargs__contains=f'"user_id": {request.user.id}',
    ).delete()
    StremioAccount.objects.filter(user=request.user).delete()
    messages.info(request, "Disconnected Stremio.")
    return redirect("import_data")


@require_POST
def import_stremio(request):
    """Queue a Stremio import and ensure the recurring schedule exists."""
    account = getattr(request.user, "stremio_account", None)
    if not account:
        messages.error(request, "Connect Stremio before importing.")
        return redirect("import_data")

    tasks.import_stremio.delay(user_id=request.user.id, mode="new")
    _ensure_stremio_schedule(request.user)
    messages.info(request, "Stremio import queued.")
    return redirect("import_data")


XBOX_RECURRING_TASK_NAME = "Import from Xbox (Recurring)"
XBOX_RECURRING_FREQUENCIES = {"daily": "*", "2days": "*/2"}
XBOX_DEFAULT_IMPORT_TIME = "04:00"


def _next_crontab_run(crontab):
    """Return the next fire time for a crontab schedule.

    New periodic tasks are created with this as their `start_time`; beat
    treats a task whose `start_time` has already passed as due immediately,
    which would run the import once on creation and again on schedule.
    """
    schedule_timezone = zoneinfo.ZoneInfo(str(crontab.timezone))
    cron_expression = (
        f"{crontab.minute} {crontab.hour} {crontab.day_of_month} "
        f"{crontab.month_of_year} {crontab.day_of_week}"
    )
    now = timezone.now().astimezone(schedule_timezone)
    return croniter.croniter(cron_expression, now).get_next(datetime)


def _xbox_schedule_name(user, parsed_time, frequency):
    """Name a user's Xbox schedule for the beat admin and the schedule list."""
    return f"Import from Xbox for {user.username} at {parsed_time} {frequency}"


def _reclaim_xbox_schedule_name(task_name, parsed_time, frequency):
    """Free a schedule name whose holder no longer answers to it.

    `PeriodicTask.name` is unique and these names are built from the
    username, which can be changed and freed for someone else to take — so
    a name outlives its owner's claim to it. The kwargs `user_id` is the
    real owner: rename the holder to match whoever that is now, or drop it
    if that user is gone. Returns whether the name is ours to take.
    """
    from django_celery_beat.models import PeriodicTask

    holder = PeriodicTask.objects.filter(name=task_name).first()
    if holder is None:
        return True

    try:
        holder_user_id = json.loads(holder.kwargs or "{}").get("user_id")
    except (TypeError, ValueError):
        holder_user_id = None

    holder_user = (
        users.models.User.objects.filter(id=holder_user_id).first()
        if holder_user_id
        else None
    )
    if holder_user is None:
        holder.delete()
        return True

    current_name = _xbox_schedule_name(holder_user, parsed_time, frequency)
    if current_name == task_name:
        # The holder is entitled to the name; it just isn't ours.
        return False

    holder.name = current_name
    holder.save(update_fields=["name"])
    return True


def _create_xbox_schedule(request, mode, frequency, import_time):
    """Create a recurring Xbox import schedule for the chosen time."""
    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    try:
        parsed_time = datetime.strptime(import_time, "%H:%M").time()  # noqa: DTZ007  # wall-clock value; the crontab carries the timezone
    except (TypeError, ValueError):
        messages.error(request, "Invalid import time.")
        return

    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute=parsed_time.minute,
        hour=parsed_time.hour,
        day_of_week=XBOX_RECURRING_FREQUENCIES[frequency],
        day_of_month="*",
        month_of_year="*",
        timezone=timezone.get_default_timezone(),
    )

    task_name = _xbox_schedule_name(request.user, parsed_time, frequency)
    desired_kwargs = json.dumps({"user_id": request.user.id, "mode": mode})
    existing_task = (
        PeriodicTask.objects.filter(
            _periodic_task_filter_for_user(request.user.id),
            task=XBOX_RECURRING_TASK_NAME,
            crontab=crontab,
        )
        .order_by("-enabled", "id")
        .first()
    )
    if existing_task:
        if existing_task.enabled:
            messages.error(request, "The same import task is already scheduled.")
            return

        # A disabled task still owns its unique name, so revive it instead of
        # creating a second one that would collide.
        existing_task.name = task_name
        existing_task.kwargs = desired_kwargs
        existing_task.start_time = _next_crontab_run(crontab)
        existing_task.enabled = True
        existing_task.save(
            update_fields=["name", "kwargs", "start_time", "enabled"],
        )
        messages.success(request, "Xbox import task re-enabled.")
        return

    if not _reclaim_xbox_schedule_name(task_name, parsed_time, frequency):
        messages.error(request, "The same import task is already scheduled.")
        return

    try:
        PeriodicTask.objects.create(
            name=task_name,
            task=XBOX_RECURRING_TASK_NAME,
            crontab=crontab,
            kwargs=desired_kwargs,
            start_time=_next_crontab_run(crontab),
            enabled=True,
        )
    except IntegrityError:
        logger.exception("Xbox schedule %s could not be created", task_name)
        messages.error(request, "The same import task is already scheduled.")
        return

    messages.success(request, "Xbox import task scheduled.")


def _start_xbox_import(request):
    """Queue a one-off Xbox import, or schedule a recurring one.

    A scheduled import only runs on its schedule; a one time import runs
    straight away and creates no periodic task.
    """
    mode = request.POST.get("mode") or "new"
    frequency = request.POST.get("frequency") or "once"
    import_time = request.POST.get("time") or XBOX_DEFAULT_IMPORT_TIME

    if frequency not in XBOX_RECURRING_FREQUENCIES:
        tasks.import_xbox.delay(user_id=request.user.id, mode=mode)
        messages.info(request, "The task to import media from Xbox has been queued.")
        return

    _create_xbox_schedule(request, mode, frequency, import_time)


@require_POST
def xbox_connect(request):
    """Connect an Xbox account using an OpenXBL API key."""
    api_key = request.POST.get("api_key", "").strip()
    if not api_key:
        messages.error(request, "An OpenXBL API key is required.")
        return redirect("import_data")

    try:
        xuid, gamertag = xbox_api.get_account(api_key)
    except helpers.MediaImportError as error:
        messages.error(request, f"Could not connect to Xbox: {error}")
        return redirect("import_data")
    except Exception as error:
        logger.exception("Failed to connect to Xbox")
        messages.error(
            request,
            "Failed to connect to Xbox "
            f"({exception_summary(error)}). Check the logs for details.",
        )
        return redirect("import_data")

    XboxAccount.objects.update_or_create(
        user=request.user,
        defaults={
            "api_key": helpers.encrypt(api_key),
            "xuid": xuid,
            "gamertag": gamertag,
            "connection_broken": False,
            "last_error_message": "",
        },
    )
    messages.success(request, f"Connected to Xbox as {gamertag or xuid}.")
    _start_xbox_import(request)
    return redirect("import_data")


@require_POST
def xbox_disconnect(request):
    """Disconnect the Xbox integration."""
    from django_celery_beat.models import PeriodicTask

    PeriodicTask.objects.filter(
        _periodic_task_filter_for_user(request.user.id),
        task=XBOX_RECURRING_TASK_NAME,
    ).delete()
    XboxAccount.objects.filter(user=request.user).delete()
    messages.info(request, "Disconnected Xbox.")
    return redirect("import_data")


@require_POST
def import_xbox(request):
    """Queue a one-off Xbox import or schedule a recurring one."""
    account = getattr(request.user, "xbox_account", None)
    if not account:
        messages.error(request, "Connect Xbox before importing.")
        return redirect("import_data")

    _start_xbox_import(request)
    return redirect("import_data")


@require_POST
def pocketcasts_connect(request):
    """Connect Pocket Casts account using email and password."""
    email = request.POST.get("email", "").strip()
    password = request.POST.get("password", "").strip()

    if not email:
        messages.error(request, "Email is required.")
        return _integration_redirect(request)

    if not password:
        messages.error(request, "Password is required.")
        return _integration_redirect(request)

    # Attempt to login with credentials
    try:
        logger.debug("Attempting Pocket Casts login with configured credentials")
        login_response = pocketcasts_api.login(email, password)
        access_token = login_response["accessToken"]
        refresh_token = login_response.get("refreshToken", "")

        logger.info(
            "Successfully logged in to Pocket Casts for user %s", request.user.username
        )
    except PocketCastsAuthError:
        logger.exception("Pocket Casts login failed")
        messages.error(
            request,
            "Invalid email or password. For accounts created via 'Sign in with Apple' or 'Sign in with Google', "
            "please set a password first using Pocket Casts' 'Forgot Password' feature, then enter your email and new password here.",
        )
        return _integration_redirect(request)
    except Exception as e:
        logger.exception("Failed to login to Pocket Casts")
        messages.error(request, f"Failed to connect to Pocket Casts: {e}")
        return _integration_redirect(request)

    # Encrypt and store credentials and tokens
    try:
        encrypted_email = helpers.encrypt(email)
        encrypted_password = helpers.encrypt(password)
        encrypted_access = helpers.encrypt(access_token)
        encrypted_refresh = helpers.encrypt(refresh_token) if refresh_token else None

        # Parse expiration from JWT
        token_expires_at = pocketcasts_api.parse_token_expiration(access_token)

        PocketCastsAccount.objects.update_or_create(
            user=request.user,
            defaults={
                "email": encrypted_email,
                "password": encrypted_password,
                "access_token": encrypted_access,
                "refresh_token": encrypted_refresh,
                "token_expires_at": token_expires_at,
                "connection_broken": False,  # Clear broken flag on successful connection
            },
        )

        # Set up 2-hour recurring import if it doesn't exist
        from django_celery_beat.models import CrontabSchedule, PeriodicTask

        existing_task = PeriodicTask.objects.filter(
            task="Import from Pocket Casts (Recurring)",
            kwargs__contains=f'"user_id": {request.user.id}',
            enabled=True,
        ).first()

        if not existing_task:
            # Create crontab for every 2 hours (0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22)
            crontab, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour="*/2",
                day_of_week="*",
                day_of_month="*",
                month_of_year="*",
                timezone=timezone.get_default_timezone(),
            )

            task_name = (
                f"Import from Pocket Casts for {request.user.username} (every 2 hours)"
            )
            PeriodicTask.objects.create(
                name=task_name,
                task="Import from Pocket Casts (Recurring)",
                crontab=crontab,
                kwargs=json.dumps(
                    {
                        "user_id": request.user.id,
                    }
                ),
                start_time=timezone.now(),
                enabled=True,
            )

            # Run initial import
            tasks.import_pocketcasts.delay(
                user_id=request.user.id,
                mode="new",
            )
            messages.success(
                request,
                "Connected to Pocket Casts successfully. Initial import queued. Recurring imports will run every 2 hours.",
            )
        else:
            messages.success(request, "Connected to Pocket Casts successfully.")
    except Exception as e:
        logger.exception("Failed to store Pocket Casts credentials")
        messages.error(request, f"Failed to store credentials: {e}")
        return _integration_redirect(request)

    return _integration_redirect(request, connected_slug="pocketcasts")


@require_POST
def pocketcasts_disconnect(request):
    """Remove stored Pocket Casts credentials and delete periodic import task."""
    from django_celery_beat.models import PeriodicTask

    # Delete periodic import task if it exists
    PeriodicTask.objects.filter(
        task="Import from Pocket Casts (Recurring)",
        kwargs__contains=f'"user_id": {request.user.id}',
    ).delete()

    # Clear all credentials (full disconnect)
    PocketCastsAccount.objects.filter(user=request.user).delete()
    messages.info(request, "Disconnected Pocket Casts and removed scheduled imports.")
    return redirect("import_data")


@require_POST
def gpodder_connect(request):
    """Connect a GPodder-compatible account using Basic Auth credentials."""
    server_url = gpodder_api.normalize_server_url(request.POST.get("server_url", ""))
    username = request.POST.get("username", "").strip()
    password = request.POST.get("password", "").strip()
    device_filter = request.POST.get("device_filter", "").strip()

    if not username:
        messages.error(request, "Username is required.")
        return _integration_redirect(request)

    if not password:
        messages.error(request, "Password is required.")
        return _integration_redirect(request)

    credentials = gpodder_api.GPodderCredentials(
        server_url=server_url,
        username=username,
        password=password,
    )
    try:
        gpodder_api.verify_login(credentials)
    except GPodderAuthError:
        messages.error(request, "Invalid GPodder username or password.")
        return _integration_redirect(request)
    except GPodderClientError as exc:
        messages.error(request, f"Failed to connect to GPodder: {exc}")
        return _integration_redirect(request)

    # Device id stays "yamtrack-<id>": it is registered on the remote
    # GPodder server, and a new id would start a fresh sync from scratch.
    device_id = f"yamtrack-{request.user.id}"

    try:
        GPodderAccount.objects.update_or_create(
            user=request.user,
            defaults={
                "server_url": helpers.encrypt(server_url),
                "username": helpers.encrypt(username),
                "password": helpers.encrypt(password),
                "device_id": device_id,
                "device_filter": device_filter,
                "connection_broken": False,
                "last_error_message": "",
            },
        )

        from django_celery_beat.models import CrontabSchedule, PeriodicTask

        existing_task = PeriodicTask.objects.filter(
            task=GPODDER_RECURRING_TASK_NAME,
            kwargs__contains=f'"user_id": {request.user.id}',
            enabled=True,
        ).first()
        if not existing_task:
            crontab, _ = CrontabSchedule.objects.get_or_create(
                minute=0,
                hour="*/2",
                day_of_week="*",
                day_of_month="*",
                month_of_year="*",
                timezone=timezone.get_default_timezone(),
            )
            PeriodicTask.objects.create(
                name=f"Import from GPodder for {request.user.username} (every 2 hours)",
                task=GPODDER_RECURRING_TASK_NAME,
                crontab=crontab,
                kwargs=json.dumps({"user_id": request.user.id}),
                start_time=timezone.now(),
                enabled=True,
            )
            tasks.import_gpodder.delay(user_id=request.user.id, mode="new")
            messages.success(
                request,
                "Connected to GPodder successfully. Initial sync queued. Recurring syncs will run every 2 hours.",
            )
        else:
            messages.success(request, "Connected to GPodder successfully.")
    except Exception as exc:
        logger.exception("Failed to store GPodder credentials")
        messages.error(request, f"Failed to save GPodder connection: {exc}")
        return _integration_redirect(request)

    return _integration_redirect(request, connected_slug="gpodder")


@require_POST
def gpodder_disconnect(request):
    """Remove stored GPodder credentials and scheduled imports."""
    from django_celery_beat.models import PeriodicTask

    PeriodicTask.objects.filter(
        task=GPODDER_RECURRING_TASK_NAME,
        kwargs__contains=f'"user_id": {request.user.id}',
    ).delete()
    GPodderAccount.objects.filter(user=request.user).delete()
    messages.info(request, "Disconnected GPodder and removed scheduled imports.")
    return redirect("import_data")


@require_POST
def lastfm_connect(request):
    """Connect Last.fm account using username."""
    username = request.POST.get("lastfm_username", "").strip()

    if not username:
        messages.error(request, "Last.fm username is required.")
        return _integration_redirect(request)

    # Validate username by making a test API call
    try:
        logger.debug("Validating Last.fm username: %s", username)
        # Make a minimal API call to verify user exists and has public scrobbles
        lastfm_api.get_recent_tracks(username=username, limit=1, page=1)
        logger.info("Successfully validated Last.fm username: %s", username)
    except LastFMClientError:
        logger.exception("Last.fm username validation failed")
        messages.error(
            request,
            "Invalid Last.fm username or user not found. Please check your username and ensure your scrobbles are public.",
        )
        return _integration_redirect(request)
    except LastFMRateLimitError:
        logger.exception("Last.fm rate limit during validation")
        messages.error(
            request,
            "Last.fm API rate limit exceeded. Please try again in a few moments.",
        )
        return _integration_redirect(request)
    except LastFMAPIError as e:
        logger.exception("Last.fm API error during validation")
        messages.error(request, f"Failed to connect to Last.fm: {e}")
        return _integration_redirect(request)
    except Exception as e:
        logger.exception("Unexpected error validating Last.fm username")
        messages.error(request, f"Failed to connect to Last.fm: {e}")
        return _integration_redirect(request)

    # Store username and initialize sync state
    try:
        import time

        current_timestamp = int(time.time())

        lastfm_account, _ = LastFMAccount.objects.update_or_create(
            user=request.user,
            defaults={
                "lastfm_username": username,
                "last_fetch_timestamp_uts": current_timestamp,
                "connection_broken": False,
                "failure_count": 0,
                "last_error_code": "",
                "last_error_message": "",
                "last_failed_at": None,
            },
        )
        _save_lastfm_history_reset(lastfm_account, current_timestamp - 1)

        _ensure_lastfm_poll_schedule()
        poll_interval_minutes = getattr(settings, "LASTFM_POLL_INTERVAL_MINUTES", 15)
        tasks.poll_lastfm_for_user.delay(user_id=request.user.id)
        tasks.import_lastfm_history.delay(user_id=request.user.id, reset=False)
        messages.success(
            request,
            (
                "Connected to Last.fm successfully. Recurring syncs will run every "
                f"{poll_interval_minutes} minutes. Initial sync and full history import queued."
            ),
        )
    except Exception as e:
        logger.exception("Failed to store Last.fm connection")
        messages.error(request, f"Failed to save Last.fm connection: {e}")
        return _integration_redirect(request)

    return _integration_redirect(request, connected_slug="lastfm")


@require_POST
def lastfm_disconnect(request):
    """Remove Last.fm connection."""
    from integrations.models import ImportRun

    LastFMAccount.objects.filter(user=request.user).delete()
    # Deleting the account already stops future self-requeued chunks (they
    # no-op when the account is gone), but flag any in-flight run too so
    # the cooperative cancel check picks it up before its next requeue.
    ImportRun.objects.filter(
        user=request.user,
        source="lastfm",
        status=ImportRun.Status.RUNNING,
    ).update(cancel_requested=True)

    # If no users left, we could disable the periodic task, but we'll leave it
    # running - it will just skip if no users are connected
    # This allows the task to stay configured for future users

    messages.info(request, "Disconnected Last.fm.")
    return redirect("import_data")


@require_POST
def poll_lastfm_manual(request):
    """Manually trigger Last.fm polling for the current user."""
    lastfm_account = getattr(request.user, "lastfm_account", None)
    if not lastfm_account:
        messages.error(request, "Connect Last.fm before syncing.")
        return redirect("import_data")

    lastfm_account.refresh_from_db()
    if not lastfm_account.is_connected:
        messages.error(request, "Last.fm connection is broken. Please reconnect.")
        return redirect("import_data")

    tasks.poll_lastfm_for_user.delay(user_id=request.user.id)
    messages.info(request, "Last.fm sync queued. Scrobbles will be imported shortly.")
    return redirect("import_data")


@require_POST
def import_lastfm_history_manual(request):
    """Queue or rerun a full Last.fm history import for the current user."""
    lastfm_account = getattr(request.user, "lastfm_account", None)
    if not lastfm_account:
        messages.error(request, "Connect Last.fm before importing history.")
        return redirect("import_data")

    lastfm_account.refresh_from_db()
    if not lastfm_account.is_connected:
        messages.error(request, "Last.fm connection is broken. Please reconnect.")
        return redirect("import_data")

    if lastfm_account.history_import_is_active:
        messages.info(request, "Full Last.fm history import already running.")
        return redirect("import_data")

    import time

    cutoff_uts = (lastfm_account.last_fetch_timestamp_uts or int(time.time())) - 1
    _save_lastfm_history_reset(lastfm_account, cutoff_uts)
    tasks.import_lastfm_history.delay(user_id=request.user.id, reset=False)
    messages.info(request, "Full Last.fm history import queued.")
    return redirect("import_data")


def _ensure_koito_poll_schedule(user):
    """Create the recurring Koito poll schedule for a user if missing."""
    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    existing_task = PeriodicTask.objects.filter(
        task=tasks.KOITO_POLL_TASK_NAME,
        kwargs__contains=f'"user_id": {user.id}',
        enabled=True,
    ).first()
    if existing_task:
        return

    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute="*/15",
        hour="*",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        timezone=timezone.get_default_timezone(),
    )
    PeriodicTask.objects.create(
        name=f"Poll Koito for {user.username} (every 15 minutes)",
        task=tasks.KOITO_POLL_TASK_NAME,
        crontab=crontab,
        kwargs=json.dumps({"user_id": user.id}),
        start_time=timezone.now(),
        enabled=True,
    )


@require_POST
def koito_connect(request):
    """Connect a Koito account using base URL + API key."""
    base_url = request.POST.get("base_url", "").strip().rstrip("/")
    api_key = request.POST.get("api_key", "").strip()

    if not base_url or not api_key:
        messages.error(request, "Koito server URL and API key are required.")
        return _integration_redirect(request)

    try:
        koito_api.validate_connection(base_url, api_key)
    except koito_api.KoitoAuthError as exc:
        messages.error(request, str(exc))
        return _integration_redirect(request)
    except Exception as exc:
        messages.error(request, f"Failed to connect to Koito: {exc}")
        return _integration_redirect(request)

    KoitoAccount.objects.update_or_create(
        user=request.user,
        defaults={
            "base_url": base_url,
            "api_key": helpers.encrypt(api_key),
            "last_fetch_timestamp_uts": int(timezone.now().timestamp()),
            "connection_broken": False,
            "failure_count": 0,
            "last_error_message": "",
            "last_failed_at": None,
        },
    )

    _ensure_koito_poll_schedule(request.user)
    tasks.poll_koito_for_user.delay(user_id=request.user.id)
    tasks.import_koito_history.delay(user_id=request.user.id, reset=True)
    messages.success(request, "Connected Koito. Full history import queued.")
    return _integration_redirect(request, connected_slug="koito")


@require_POST
def koito_disconnect(request):
    """Disconnect the Koito integration."""
    from django_celery_beat.models import PeriodicTask

    PeriodicTask.objects.filter(
        task=tasks.KOITO_POLL_TASK_NAME,
        kwargs__contains=f'"user_id": {request.user.id}',
    ).delete()
    KoitoAccount.objects.filter(user=request.user).delete()
    messages.info(request, "Disconnected Koito.")
    return redirect("import_data")


@require_POST
def poll_koito_manual(request):
    """Manually trigger a Koito sync for the current user."""
    koito_account = getattr(request.user, "koito_account", None)
    if not koito_account:
        messages.error(request, "Connect Koito before syncing.")
        return redirect("import_data")

    koito_account.refresh_from_db()
    if not koito_account.is_connected:
        messages.error(request, "Koito connection is broken. Please reconnect.")
        return redirect("import_data")

    tasks.poll_koito_for_user.delay(user_id=request.user.id)
    messages.info(request, "Koito sync queued. Listens will be imported shortly.")
    return redirect("import_data")


@require_POST
def import_koito_history_manual(request):
    """Queue or rerun a full Koito history import for the current user."""
    koito_account = getattr(request.user, "koito_account", None)
    if not koito_account:
        messages.error(request, "Connect Koito before importing history.")
        return redirect("import_data")

    koito_account.refresh_from_db()
    if not koito_account.is_connected:
        messages.error(request, "Koito connection is broken. Please reconnect.")
        return redirect("import_data")

    if koito_account.history_import_is_active:
        messages.info(request, "Full Koito history import already running.")
        return redirect("import_data")

    tasks.import_koito_history.delay(user_id=request.user.id, reset=True)
    messages.info(request, "Full Koito history import queued.")
    return redirect("import_data")


@require_POST
def import_pocketcasts(request):
    """Queue a Pocket Casts history import for the current user.

    Pocket Casts always uses mode="new" and runs every 2 hours automatically.
    First import is "new", subsequent recurring imports are also "new".
    """
    pocketcasts_account = getattr(request.user, "pocketcasts_account", None)
    if not pocketcasts_account:
        messages.error(request, "Connect Pocket Casts before importing.")
        return redirect("import_data")

    # Refresh from DB to get latest status
    pocketcasts_account.refresh_from_db()

    # Allow sync even if connection is broken - importer will attempt refresh

    # Check if this is the first import (no existing schedule)
    from django_celery_beat.models import PeriodicTask

    existing_task = PeriodicTask.objects.filter(
        task="Import from Pocket Casts (Recurring)",
        kwargs__contains=f'"user_id": {request.user.id}',
        enabled=True,
    ).first()

    # Always use mode="new" for Pocket Casts
    mode = "new"

    if not existing_task:
        # First import - run immediately, then set up 2-hour schedule
        tasks.import_pocketcasts.delay(
            user_id=request.user.id,
            mode=mode,
        )
        messages.info(
            request,
            "The task to import media from Pocket Casts has been queued. Recurring imports will run every 2 hours.",
        )

        # Set up 2-hour recurring schedule
        from django.utils import timezone as tz
        from django_celery_beat.models import CrontabSchedule

        # Create crontab for every 2 hours (0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22)
        crontab, _ = CrontabSchedule.objects.get_or_create(
            minute=0,
            hour="*/2",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
            timezone=tz.get_default_timezone(),
        )

        task_name = (
            f"Import from Pocket Casts for {request.user.username} (every 2 hours)"
        )
        PeriodicTask.objects.create(
            name=task_name,
            task="Import from Pocket Casts (Recurring)",
            crontab=crontab,
            kwargs=json.dumps(
                {
                    "user_id": request.user.id,
                }
            ),
            start_time=tz.now(),
            enabled=True,
        )
    else:
        # Just run a manual import
        tasks.import_pocketcasts.delay(
            user_id=request.user.id,
            mode=mode,
        )
        messages.info(
            request, "The task to import media from Pocket Casts has been queued."
        )

    return redirect("import_data")


@require_POST
def import_gpodder(request):
    """Queue a GPodder podcast history sync for the current user."""
    gpodder_account = getattr(request.user, "gpodder_account", None)
    if not gpodder_account:
        messages.error(request, "Connect GPodder before syncing.")
        return redirect("import_data")

    gpodder_account.refresh_from_db()

    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    existing_task = PeriodicTask.objects.filter(
        task=GPODDER_RECURRING_TASK_NAME,
        kwargs__contains=f'"user_id": {request.user.id}',
        enabled=True,
    ).first()

    if not existing_task:
        crontab, _ = CrontabSchedule.objects.get_or_create(
            minute=0,
            hour="*/2",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
            timezone=timezone.get_default_timezone(),
        )
        PeriodicTask.objects.create(
            name=f"Import from GPodder for {request.user.username} (every 2 hours)",
            task=GPODDER_RECURRING_TASK_NAME,
            crontab=crontab,
            kwargs=json.dumps({"user_id": request.user.id}),
            start_time=timezone.now(),
            enabled=True,
        )
        messages.info(
            request,
            "The task to import media from GPodder has been queued. Recurring syncs will run every 2 hours.",
        )
    else:
        messages.info(request, "The task to import media from GPodder has been queued.")

    tasks.import_gpodder.delay(user_id=request.user.id, mode="new")
    return redirect("import_data")


def import_imdb(request):
    """View for importing data from IMDB."""
    file = request.FILES.get("imdb_csv")

    if not file:
        messages.error(request, "IMDB CSV file is required.")
        return _integration_redirect(request)

    mode = request.POST["mode"]
    tasks.import_imdb.delay(
        user_id=request.user.id,
        file=_read_uploaded_file(file),
        mode=mode,
    )
    messages.info(
        request,
        "The task to import media from IMDB CSV file has been queued.",
    )
    return _integration_redirect(request, connected_slug="imdb")


@require_POST
def import_goodreads(request):
    """View for importing books data from Goodreads CSV."""
    file = request.FILES.get("goodreads_csv")

    if not file:
        messages.error(request, "Goodreads CSV file is required.")
        return _integration_redirect(request)

    mode = request.POST["mode"]
    tasks.import_goodreads.delay(
        user_id=request.user.id,
        file=_read_uploaded_file(file),
        mode=mode,
    )
    messages.info(
        request,
        "The task to import media from Goodreads CSV file has been queued.",
    )
    return _integration_redirect(request, connected_slug="goodreads")


@require_POST
def import_hardcover(request):
    """View for importing books data from Hardcover CSV."""
    file = request.FILES.get("hardcover_csv")

    if not file:
        messages.error(request, "Hardcover CSV file is required.")
        return _integration_redirect(request)

    mode = request.POST["mode"]
    tasks.import_hardcover.delay(
        user_id=request.user.id,
        file=_read_uploaded_file(file),
        mode=mode,
    )
    messages.info(
        request,
        "The task to import media from Hardcover CSV file has been queued.",
    )
    return _integration_redirect(request, connected_slug="hardcover")


@require_POST
def import_storygraph(request):
    """View for importing books data from StoryGraph CSV."""
    file = request.FILES.get("storygraph_csv")

    if not file:
        messages.error(request, "StoryGraph CSV file is required.")
        return _integration_redirect(request)

    mode = request.POST["mode"]
    tasks.import_storygraph.delay(
        user_id=request.user.id,
        file=_read_uploaded_file(file),
        mode=mode,
    )
    messages.info(
        request,
        "The task to import media from StoryGraph CSV file has been queued.",
    )
    return _integration_redirect(request, connected_slug="storygraph")


@require_GET
def import_template_csv(request):
    """View for downloading a sample CSV demonstrating the import format."""
    content = exports.generate_sample_template()
    response = HttpResponse(content, content_type="text/csv")
    response["Content-Disposition"] = (
        'attachment; filename="floppy_import_template.csv"'
    )
    return response


@require_GET
def export_csv(request):
    """View for exporting all media data to a CSV file."""
    selected_media_types = request.GET.getlist("media_types")
    include_lists = request.GET.get("include_lists", "on") == "on"
    include_collection = request.GET.get("include_collection", "on") == "on"

    if selected_media_types:
        media_types = selected_media_types
    elif request.GET:
        # explicit request with no media types checked -> lists/collection-only
        # when either is included
        media_types = [] if include_lists or include_collection else None
    else:
        media_types = None

    now = timezone.localtime()
    response = StreamingHttpResponse(
        streaming_content=exports.generate_rows(
            request.user,
            media_types=media_types,
            include_lists=include_lists,
            include_collection=include_collection,
        ),
        content_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="floppy_{now}.csv"'},
    )
    logger.info("User %s started CSV export", request.user.username)
    return response


@login_not_required
@csrf_exempt
@require_POST
def jellyfin_webhook(request, token):
    """Handle Jellyfin webhook notifications for media playback."""
    try:
        user = users.models.User.objects.get(token=token)
    except ObjectDoesNotExist:
        logger.warning(
            "Could not process Jellyfin webhook: Invalid token: %s",
            token,
        )
        return HttpResponse(status=401)

    data = request.body
    if not data:
        logger.warning("Missing payload in Jellyfin webhook request")
        return HttpResponse("Missing payload", status=400)

    payload = json.loads(data)
    tasks.process_webhook.delay("jellyfin", payload, user.id)
    return HttpResponse(status=200)


@login_not_required
@csrf_exempt
@require_POST
def plex_webhook(request, token):
    """Handle Plex webhook notifications for media playback."""
    try:
        user = users.models.User.objects.get(token=token)
    except ObjectDoesNotExist:
        logger.warning(
            "Could not process Plex webhook: Invalid token: %s",
            token,
        )
        return HttpResponse(status=401)

    # https://support.plex.tv/hc/en-us/articles/115002267687-Webhooks
    # As stated above, the payload is sent in JSON format inside a multipart
    # HTTP POST request. For the media.play and media.rate events, a second part of
    # the POST request contains a JPEG thumbnail for the media.

    data = request.POST.get("payload")
    if not data:
        logger.warning("Missing payload in Plex webhook request")
        user.mark_plex_webhook_error("Missing payload in Plex webhook request")
        return HttpResponse("Missing payload", status=400)

    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON payload in Plex webhook request")
        user.mark_plex_webhook_error("Invalid JSON payload in Plex webhook request")
        return HttpResponse("Invalid payload", status=400)

    event_type = payload.get("event")
    logger.info(
        "Received Plex webhook request - Event: %s, User: %s", event_type, user.username
    )

    tasks.process_webhook.delay("plex", payload, user.id)
    return HttpResponse(status=200)


@login_not_required
@csrf_exempt
@require_POST
def emby_webhook(request, token):
    """Handle Emby webhook notifications for media playback."""
    try:
        user = users.models.User.objects.get(token=token)
    except ObjectDoesNotExist:
        logger.warning(
            "Could not process Emby webhook: Invalid token: %s",
            token,
        )
        return HttpResponse(status=401)

    # The payload is sent in JSON format inside a multipart
    # HTTP POST request.

    data = request.POST.get("data")
    if not data:
        logger.warning("Missing payload in Emby webhook request")
        return HttpResponse("Missing payload", status=400)

    payload = json.loads(data)
    tasks.process_webhook.delay("emby", payload, user.id)
    return HttpResponse(status=200)


# kept: URL name — renaming breaks already-configured Seerr/Jellyseerr webhook URLs
@login_not_required
@csrf_exempt
@require_POST
def jellyseerr_webhook(request, token):
    """Handle Seerr webhook notifications for requested/approved media."""
    try:
        user = users.models.User.objects.get(token=token)
    except ObjectDoesNotExist:
        logger.warning(
            "Could not process Seerr webhook: Invalid token: %s",
            token,
        )
        return HttpResponse(status=401)

    data = request.body
    if not data:
        logger.warning("Missing payload in Seerr webhook request")
        return HttpResponse("Missing payload", status=400)

    try:
        payload = json.loads(data)
    except Exception:
        logger.warning("Invalid JSON payload in Seerr webhook request")
        return HttpResponse("Invalid JSON", status=400)

    tasks.process_webhook.delay("seerr", payload, user.id)
    return HttpResponse(status=200)


@login_not_required
@csrf_exempt
@require_POST
def seerr_global_webhook(request):
    """Handle a single shared Seerr webhook for multiple Floppy users.

    Unlike the per-user Seerr webhook, this endpoint has no per-user
    token in the URL, so it demultiplexes users by matching the payload's
    requester username against each opted-in user's allowed usernames.
    """
    if not settings.SEERR_GLOBAL_WEBHOOK_SECRET:
        return HttpResponse(status=404)

    data = request.body
    if not data:
        logger.warning("Missing payload in Seerr global webhook request")
        return HttpResponse("Missing payload", status=400)

    try:
        payload = json.loads(data)
    except Exception:
        logger.warning("Invalid JSON payload in Seerr global webhook request")
        return HttpResponse("Invalid JSON", status=400)

    if not hmac.compare_digest(
        str(payload.get("secret", "")),
        settings.SEERR_GLOBAL_WEBHOOK_SECRET,
    ):
        logger.warning("Seerr global webhook: invalid or missing secret")
        return HttpResponse(status=401)

    requester = (payload.get("requestedBy_username") or "").strip() or (
        payload.get("notifyuser_username") or ""
    ).strip()
    if not requester:
        logger.warning("Missing requester in Seerr global webhook request")
        return HttpResponse("Missing requester", status=400)

    matched = False
    for user in users.models.User.objects.filter(
        jellyseerr_enabled=True,
    ).exclude(jellyseerr_allowed_usernames=""):
        allowed = {
            username.strip().lower()
            for username in user.jellyseerr_allowed_usernames.split(",")
            if username.strip()
        }
        if requester.lower() in allowed:
            matched = True
            tasks.process_webhook.delay("seerr", payload, user.id)

    if not matched:
        logger.info(
            "Seerr global webhook: no user matched requester=%r",
            requester,
        )

    return HttpResponse(status=200)


@login_not_required
@csrf_exempt
@require_POST
def kodi_webhook(request, token):
    """Handle Kodi webhook notifications for media playback."""
    try:
        user = users.models.User.objects.get(token=token)
    except ObjectDoesNotExist:
        logger.warning(
            "Could not process Kodi webhook: Invalid token: %s",
            token,
        )
        return HttpResponse(status=401)

    data = request.body
    if not data:
        logger.warning("Missing payload in Kodi webhook request")
        return HttpResponse("Missing payload", status=400)

    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON payload in Kodi webhook request")
        return HttpResponse("Invalid JSON", status=400)

    tasks.process_webhook.delay("kodi", payload, user.id)
    return HttpResponse(status=200)


STREMIO_ADDON_MANIFEST = {
    # Id stays "org.yamtrack.scrobbler": Stremio clients key installed
    # addons by it, and changing it would force everyone to reinstall.
    "id": "org.yamtrack.scrobbler",
    "version": "1.0.0",
    "name": "Floppy Scrobbler",
    "description": (
        "Marks movies and episodes as in progress on Floppy when playback "
        "starts in Stremio."
    ),
    "resources": ["subtitles"],
    "types": ["movie", "series"],
    "idPrefixes": ["tt"],
    "catalogs": [],
}
STREMIO_SCROBBLE_THROTTLE_SECONDS = 1800


def _stremio_addon_response(payload, status=200):
    """Build a JSON response with the CORS headers Stremio requires."""
    response = JsonResponse(payload, status=status)
    response["Access-Control-Allow-Origin"] = "*"
    return response


@login_not_required
@csrf_exempt
@require_GET
def stremio_addon_manifest(request, token):
    """Serve the Stremio addon manifest for a user's install URL."""
    try:
        users.models.User.objects.get(token=token)
    except ObjectDoesNotExist:
        logger.warning("Invalid token on Stremio addon manifest request")
        return _stremio_addon_response({"error": "Invalid token"}, status=401)

    return _stremio_addon_response(STREMIO_ADDON_MANIFEST)


@login_not_required
@csrf_exempt
@require_GET
def stremio_addon_subtitles(request, token, media_type, media_id):
    """Record a playback-start scrobble from a Stremio subtitles request."""
    from django.core.cache import cache

    try:
        user = users.models.User.objects.get(token=token)
    except ObjectDoesNotExist:
        logger.warning("Invalid token on Stremio addon subtitles request")
        return _stremio_addon_response({"error": "Invalid token"}, status=401)

    media_id = unquote(media_id)

    # Stremio re-requests subtitles on seeks and quality changes; only the
    # first request per item in the window records a scrobble.
    throttle_key = f"stremio_scrobble_{user.id}_{media_id}"
    if cache.add(throttle_key, "1", timeout=STREMIO_SCROBBLE_THROTTLE_SECONDS):
        tasks.process_webhook.delay(
            "stremio",
            {"id": media_id, "type": media_type},
            user.id,
        )

    return _stremio_addon_response({"subtitles": []})
