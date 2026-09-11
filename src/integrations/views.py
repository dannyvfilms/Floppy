"""Contains views for importing and exporting media data from various sources."""

import base64
import binascii
import hmac
import json
import logging
import re
import secrets
import zoneinfo
from datetime import datetime, timedelta
from http import HTTPStatus
from urllib.parse import unquote

import croniter
import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required, login_required
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import (
    HttpResponse,
    HttpResponseNotFound,
    JsonResponse,
    StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

import users
from app import helpers as app_helpers
from app import image_cache
from app.db_retry import run_retryable_db_operation
from app.log_safety import exception_summary
from app.models import TV, Item, MediaTypes, Movie, Sources
from app.providers import credentials, services
from integrations import (
    audiobookshelf_cover as abs_cover_proxy,
)
from integrations import (
    exports,
    gpodder_api,
    koito_api,
    lastfm_api,
    pocketcasts_api,
    psn_api,
    stremio_catalog,
    stremio_queue,
    tasks,
    xbox_api,
)
from integrations import plex as plex_api
from integrations import plex_cover as plex_cover_proxy
from integrations.gpodder_api import GPodderAuthError, GPodderClientError
from integrations.imports import anilist, helpers, mdblist, simkl, stremio, trakt
from integrations.imports.audiobookshelf import (
    AudiobookshelfAuthError,
    AudiobookshelfClient,
)
from integrations.imports.koreader import (
    KoreaderAuthError,
    KoreaderClient,
    KoreaderClientError,
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
from integrations.match_corrections import (
    InvalidMatchCorrectionError,
    MissingEpisodeMappingError,
    StaleCorrectionPreviewError,
    apply_match_correction,
    preview_match_correction,
)
from integrations.models import (
    AudiobookshelfAccount,
    CollectionSourceState,
    ExternalReference,
    ExternalReferenceReviewStatus,
    GPodderAccount,
    JellyfinAccount,
    KoitoAccount,
    KoreaderAccount,
    KoreaderDocumentLink,
    LastFMAccount,
    MDBListAccount,
    PlexAccount,
    PlexWebhookShare,
    PocketCastsAccount,
    PSNAccount,
    RadarrInstance,
    SonarrInstance,
    StateConflict,
    StateConflictStatus,
    StorytellerAccount,
    StremioAccount,
    SyncBinding,
    XboxAccount,
)
from integrations.plex_watchlist import (
    WATCHLIST_SYNC_INTERVAL_MINUTES,
    WATCHLIST_TASK_NAME,
)
from integrations.pocketcasts_api import PocketCastsAuthError
from integrations.state import outbound
from integrations.upload_staging import (
    build_staged_zip,
    discard_staged_upload,
    enqueue_staged_task,
    stage_uploaded_file,
    staged_payload_is_zip,
)
from integrations.webhooks.plex import extract_plex_webhook_usernames

logger = logging.getLogger(__name__)
ARR_SYNC_INTERVAL_HOURS = 2
RADARR_RECURRING_TASK_NAME = "Import from Radarr (Recurring)"
JELLYFIN_PLAYBACK_REPORTING_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
SONARR_RECURRING_TASK_NAME = "Import from Sonarr (Recurring)"
GPODDER_RECURRING_TASK_NAME = "Import from GPodder (Recurring)"
TRAKT_DEVICE_SESSION_KEY = "trakt_device_auth"


def _stage_upload_or_message(request, upload, label="upload"):
    """Stage an upload and report storage failures without returning a 500."""
    try:
        return str(stage_uploaded_file(upload))
    except OSError:
        logger.exception("Could not stage %s for background import", label)
        messages.error(
            request,
            "The upload could not be queued. Check available disk space and try again.",
        )
        return None


def _stage_uploads_or_message(request, uploads, label="upload"):
    """Stage multiple uploads and roll back earlier files on failure."""
    staged = []
    for upload in uploads:
        path = _stage_upload_or_message(request, upload, label)
        if path is None:
            for staged_path in staged:
                discard_staged_upload(staged_path)
            return None
        staged.append(path)
    return staged


def _queue_staged_task_or_message(
    request,
    task,
    *args,
    staged_paths=(),
    **kwargs,
):
    """Queue a staged task and turn broker failures into a user message."""
    try:
        return enqueue_staged_task(
            task,
            *args,
            staged_paths=staged_paths,
            **kwargs,
        )
    except Exception:
        logger.exception("Could not queue background import task")
        messages.error(
            request,
            "The import could not be queued. Check the worker and try again.",
        )
        return False


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


def _consume_oauth_state(request, provider):
    """Consume a provider OAuth state value and reject missing or replayed state."""
    state_token = request.GET.get("state")
    if not state_token:
        logger.warning("%s OAuth callback missing state parameter", provider)
        messages.error(
            request,
            f"Invalid or expired {provider} authorization request.",
        )
        return None

    state_data = request.session.pop(state_token, None)
    if not isinstance(state_data, dict):
        logger.warning("%s OAuth callback state not found in session", provider)
        messages.error(
            request,
            f"Invalid or expired {provider} authorization request.",
        )
        return None

    return state_data


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


def _periodic_task_filter_for_instance(instance_id):
    """Match a Radarr/Sonarr instance's periodic task regardless of JSON spacing/quotes."""
    return (
        Q(kwargs__contains=f"'instance_id': {instance_id},")
        | Q(kwargs__contains=f"'instance_id': {instance_id}" + "}")
        | Q(kwargs__contains=f'"instance_id": {instance_id},')
        | Q(kwargs__contains=f'"instance_id": {instance_id}' + "}")
    )


def _run_with_lock_retry(operation_name, fn):
    """Run an integration connect/disconnect DB write with retry on SQLite locks.

    Connect/disconnect views create or delete `django_celery_beat`
    `PeriodicTask` rows, which fire a signal that writes to a shared
    singleton row (`PeriodicTasks.changed()`) — a serialization hotspot on
    SQLite. Wrapping the write in a retried transaction turns a transient
    lock into a short delay instead of a 503 (see issue #1112).

    `max_retries=1` (2 attempts total) rather than the helper's default of
    5: each attempt can block for up to `SQLITE_BUSY_TIMEOUT_SECONDS`
    (30s by default) before raising, and nginx.conf sets no explicit
    `proxy_read_timeout` (nginx's own default is 60s) — more attempts would
    risk the proxy returning a gateway timeout to the user while this view
    keeps retrying underneath it, so the write could still commit after the
    client has already seen a failure.
    """

    def _atomic_fn():
        with transaction.atomic():
            return fn()

    return run_retryable_db_operation(
        _atomic_fn, operation_name=operation_name, max_retries=1
    ).value


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


def _ensure_jellyfin_pull_schedule(user, jellyfin_account):
    """Create or enable the per-user Jellyfin history pull schedule."""
    from django_celery_beat.models import IntervalSchedule, PeriodicTask

    pull_task_name = tasks.JELLYFIN_PULL_TASK_NAME
    pull_interval_minutes = tasks.JELLYFIN_PULL_INTERVAL_MINUTES

    next_interval_start = timezone.now() + timedelta(minutes=pull_interval_minutes)
    interval, _ = IntervalSchedule.objects.get_or_create(
        every=pull_interval_minutes,
        period=IntervalSchedule.MINUTES,
    )
    task_filter = PeriodicTask.objects.filter(
        _plex_watchlist_task_filter(user.id),
        task=pull_task_name,
    )
    existing_task = task_filter.first()
    if existing_task:
        was_enabled = existing_task.enabled
        updated_fields = []
        desired_name = (
            f"{pull_task_name} for "
            f"{jellyfin_account.jellyfin_username or user.username} "
            f"(every {pull_interval_minutes} minutes)"
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
            f"{pull_task_name} for "
            f"{jellyfin_account.jellyfin_username or user.username} "
            f"(every {pull_interval_minutes} minutes)"
        ),
        task=pull_task_name,
        interval=interval,
        kwargs=json.dumps({"user_id": user.id}),
        start_time=next_interval_start,
        enabled=True,
    )


def _disable_jellyfin_pull_schedule(user):
    """Delete any per-user Jellyfin pull periodic tasks."""
    from django_celery_beat.models import PeriodicTask

    return PeriodicTask.objects.filter(
        _plex_watchlist_task_filter(user.id),
        task=tasks.JELLYFIN_PULL_TASK_NAME,
    ).delete()


def _ensure_arr_schedule(instance, task_name, source_label):
    """Create or enable the per-instance Radarr/Sonarr recurring schedule."""
    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    user = instance.user
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
        _periodic_task_filter_for_instance(instance.id),
        task=task_name,
    )
    existing_task = task_filter.first()
    if existing_task:
        was_enabled = existing_task.enabled
        updated_fields = []
        desired_name = (
            f"Import from {source_label} ({instance.display_name} #{instance.id}) for "
            f"{user.username} (every {ARR_SYNC_INTERVAL_HOURS} hours)"
        )
        desired_kwargs = json.dumps({"instance_id": instance.id})
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
            f"Import from {source_label} ({instance.display_name} #{instance.id}) for "
            f"{user.username} (every {ARR_SYNC_INTERVAL_HOURS} hours)"
        ),
        task=task_name,
        crontab=crontab,
        kwargs=json.dumps({"instance_id": instance.id}),
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
    if not app_helpers.supports_oauth_redirect(redirect_uri):
        # Trakt refuses non-HTTPS callbacks, so this instance can only connect
        # through the device code flow (#681).
        return _start_trakt_device_flow(request)

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
    client_id = credentials.get("trakt", "client_id")
    return redirect(
        f"{url}?client_id={client_id}&redirect_uri={redirect_uri}&response_type=code&state={state_token}",
    )


def _finish_trakt_connection(request, oauth_result, state_data):
    """Encrypt the refresh token, then queue or schedule the Trakt import."""
    enc_token = helpers.encrypt(oauth_result["refresh_token"])

    frequency = state_data["frequency"]
    mode = state_data["mode"]
    import_time = state_data["time"]

    if frequency == "once":
        tasks.import_trakt.delay(
            token=enc_token,
            user_id=request.user.id,
            mode=mode,
            username=oauth_result["username"],
        )
        messages.info(request, "The task to import media from Trakt has been queued.")
    else:
        helpers.create_import_schedule(
            oauth_result["username"],
            request,
            mode,
            frequency,
            import_time,
            "Trakt",
            token=enc_token,
        )


def _start_trakt_device_flow(request):
    """Mint a Trakt device code and send the user to the code screen."""
    try:
        device = trakt.request_device_code()
    except helpers.MediaImportError as error:
        messages.error(request, str(error))
        return _integration_redirect(request)

    request.session[TRAKT_DEVICE_SESSION_KEY] = {
        "device_code": device["device_code"],
        "user_code": device["user_code"],
        "verification_url": device["verification_url"],
        "interval": device["interval"],
        "expires_at": (
            timezone.now() + timedelta(seconds=int(device["expires_in"]))
        ).isoformat(),
        "mode": request.POST["mode"],
        "frequency": request.POST["frequency"],
        "time": request.POST["time"],
        "return_to": request.POST.get("next"),
    }
    return redirect("trakt_device_verify")


def _trakt_device_state(request):
    """Return the pending device authorization, or None if gone or expired."""
    state = request.session.get(TRAKT_DEVICE_SESSION_KEY)
    if not isinstance(state, dict):
        return None
    expires_at = parse_datetime(state.get("expires_at") or "")
    if expires_at is None or timezone.now() >= expires_at:
        return None
    return state


@require_GET
def trakt_device_verify(request):
    """Show the Trakt device code the user must enter at trakt.tv/activate."""
    state = _trakt_device_state(request)
    if state is None:
        request.session.pop(TRAKT_DEVICE_SESSION_KEY, None)
        messages.error(request, "The Trakt authorization code expired. Start again.")
        return _integration_redirect(request)

    return render(
        request,
        "integrations/trakt_device_code.html",
        {
            "user_code": state["user_code"],
            "verification_url": state["verification_url"],
            "interval": state["interval"],
            "poll_url": reverse("trakt_device_poll"),
            "cancel_url": reverse("import_data"),
        },
    )


def _htmx_redirect(location):
    """Tell HTMX to navigate away without swapping anything in."""
    return HttpResponse(status=HTTPStatus.NO_CONTENT, headers={"HX-Redirect": location})


@require_GET
def trakt_device_poll(request):
    """Poll Trakt once for the pending device authorization."""
    state = _trakt_device_state(request)
    if state is None:
        request.session.pop(TRAKT_DEVICE_SESSION_KEY, None)
        messages.error(request, "The Trakt authorization code expired. Start again.")
        return _htmx_redirect(reverse("import_data"))

    try:
        result = trakt.poll_device_token(state["device_code"])
    except helpers.MediaImportError as error:
        request.session.pop(TRAKT_DEVICE_SESSION_KEY, None)
        messages.error(request, str(error))
        return _htmx_redirect(reverse("import_data"))

    if result is None:
        return HttpResponse(status=HTTPStatus.NO_CONTENT)

    request.session.pop(TRAKT_DEVICE_SESSION_KEY, None)
    _finish_trakt_connection(request, result, state)
    redirect_response = _integration_redirect(
        request,
        connected_slug="trakt",
        next_url=state.get("return_to"),
    )
    return _htmx_redirect(redirect_response["Location"])


@require_GET
def import_trakt_private(request):
    """View for handling Trakt OAuth2 callback and scheduling private import."""
    state_data = _consume_oauth_state(request, "Trakt")
    if state_data is None:
        return _integration_redirect(request)

    redirect_uri = state_data.get("redirect_uri")
    oauth_callback = trakt.handle_oauth_callback(request, redirect_uri=redirect_uri)
    _finish_trakt_connection(request, oauth_callback, state_data)
    return _integration_redirect(
        request,
        connected_slug="trakt",
        next_url=state_data.get("return_to"),
    )


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

    _run_with_lock_retry(
        "connect Plex",
        lambda: PlexAccount.objects.update_or_create(
            user=request.user,
            defaults=defaults,
        ),
    )

    account_username = account.get("username") or "your Plex account"
    messages.success(request, f"Connected to Plex as {account_username}.")

    if return_to:
        # Arrived from the setup wizard: queue a sensible default import
        # rather than requiring a second visit to pick a library/mode.
        tasks.import_plex.delay(user_id=request.user.id, mode="new", library=["all"])

    return _integration_redirect(request, connected_slug="plex", next_url=return_to)


@require_POST
def plex_disconnect(request):
    """Remove stored Plex credentials."""

    def _disconnect():
        _disable_plex_watchlist_schedule(request.user)
        PlexWebhookShare.objects.filter(owner=request.user).delete()
        PlexAccount.objects.filter(user=request.user).delete()

    _run_with_lock_retry("disconnect Plex", _disconnect)
    messages.info(request, "Disconnected Plex.")
    return redirect("import_data")


def _save_plex_content_kind(plex_account, library_content_kinds):
    """Persist per-library content-kind choices (auto/music/audiobook).

    Stored on the account rather than passed per-run so scheduled imports and
    the live webhook honor the same choice. Each entry is a
    "machine_identifier::section_id::content_kind" string.
    """
    changed = False
    for entry in library_content_kinds:
        try:
            machine_identifier, section_id, content_kind = entry.split("::", 2)
        except ValueError:
            continue
        changed = (
            plex_account.set_content_kind(machine_identifier, section_id, content_kind)
            or changed
        )
    if changed:
        plex_account.save(update_fields=["section_settings"])


@require_POST
def import_plex(request):
    """Queue a Plex history import for the current user."""
    plex_account = getattr(request.user, "plex_account", None)
    if not plex_account:
        messages.error(request, "Connect Plex before importing.")
        return redirect("import_data")

    library = request.POST.getlist("library") or ["all"]
    mode = request.POST.get("mode", "new")
    frequency = request.POST.get("frequency", "once")
    import_time = request.POST.get("time", "00:00")
    raw_usernames = request.POST.get("plex_usernames", "")
    library_content_kinds = request.POST.getlist("library_content_kind")

    _save_plex_usernames(request.user, raw_usernames)
    _save_plex_content_kind(plex_account, library_content_kinds)

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
        "redirect_uri": redirect_uri,
        "return_to": request.POST.get("next"),
    }
    state_token = secrets.token_urlsafe(32)
    request.session[state_token] = state

    return redirect(
        f"{url}?client_id={credentials.get("simkl", "client_id")}&redirect_uri={redirect_uri}&response_type=code&state={state_token}",
    )


@require_GET
def import_simkl_private(request):
    """View for getting the SIMKL OAuth2 token."""
    state_data = _consume_oauth_state(request, "SIMKL")
    if state_data is None:
        return _integration_redirect(request)

    redirect_uri = state_data.get("redirect_uri")
    oauth_callback = simkl.get_token(request, redirect_uri=redirect_uri)
    enc_token = helpers.encrypt(oauth_callback["access_token"])

    frequency = state_data["frequency"]
    mode = state_data["mode"]
    import_time = state_data["time"]
    return_to = state_data.get("return_to")

    if frequency == "once":
        tasks.import_simkl.delay(
            token=enc_token,
            user_id=request.user.id,
            mode=mode,
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
        f"{url}?client_id={credentials.get("anilist", "client_id")}&redirect_uri={redirect_uri}&response_type=code&state={state_token}",
    )


@require_GET
def import_anilist_private(request):
    """View for getting the AniList OAuth2 token."""
    state_data = _consume_oauth_state(request, "AniList")
    if state_data is None:
        return _integration_redirect(request)

    redirect_uri = state_data.get("redirect_uri")
    oauth_callback = anilist.get_token(request, redirect_uri=redirect_uri)
    enc_token = helpers.encrypt(oauth_callback["access_token"])
    username = oauth_callback["username"]
    return_to = state_data.get("return_to")

    if not username:
        messages.error(request, "AniList username is required.")
        return _integration_redirect(request, next_url=return_to)

    frequency = state_data["frequency"]
    mode = state_data["mode"]
    import_time = state_data["time"]

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

    staged_file = _stage_upload_or_message(request, file, "Floppy CSV")
    if staged_file is None:
        return _integration_redirect(request)

    mode = request.POST["mode"]
    if _queue_staged_task_or_message(
        request,
        tasks.import_yamtrack,
        user_id=request.user.id,
        file=staged_file,
        mode=mode,
        staged_paths=(staged_file,),
    ) is False:
        return _integration_redirect(request, connected_slug="yamtrack")
    messages.info(
        request,
        "The task to import media from the CSV file has been queued.",
    )
    return _integration_redirect(request, connected_slug="yamtrack")


@require_POST
def import_clz(request):
    """View for importing a CLZ (Collectorz) CSV or XML export."""
    file = request.FILES.get("clz_export")

    if not file:
        messages.error(request, "A CLZ CSV or XML export is required.")
        return _integration_redirect(request)

    staged_file = _stage_upload_or_message(request, file, "CLZ export")
    if staged_file is None:
        return _integration_redirect(request)

    media_type = (request.POST.get("clz_media_type") or "").strip() or None
    if media_type and media_type not in MediaTypes.values:
        discard_staged_upload(staged_file)
        messages.error(request, "Unknown media type for the CLZ import.")
        return _integration_redirect(request)

    if _queue_staged_task_or_message(
        request,
        tasks.import_clz,
        user_id=request.user.id,
        file=staged_file,
        mode=request.POST.get("mode", "new"),
        media_type=media_type,
        staged_paths=(staged_file,),
    ) is False:
        return _integration_redirect(request, connected_slug="clz")
    messages.info(
        request,
        "The task to import your CLZ export has been queued.",
    )
    return _integration_redirect(request, connected_slug="clz")


@require_POST
def import_trakt_export_file(request):
    """View for importing a Trakt data export: a .zip, loose .json files, or a .csv.

    Trakt now exports a .zip of flat .json files, but the older community CSV
    format is still accepted. Loose .json uploads are repackaged into a
    staged zip so the Celery task always receives a single path.
    """
    uploads = request.FILES.getlist("trakt_export") or request.FILES.getlist(
        "trakt_collection_csv",
    )

    if not uploads:
        messages.error(request, "A Trakt export file is required.")
        return _integration_redirect(request)

    staged_files = _stage_uploads_or_message(request, uploads, "Trakt export")
    if staged_files is None:
        return _integration_redirect(request)

    mode = request.POST["mode"]
    payloads = [
        (upload.name, path)
        for upload, path in zip(uploads, staged_files, strict=True)
    ]

    if len(payloads) == 1 and not _is_trakt_export_payload(*payloads[0]):
        if _queue_staged_task_or_message(
            request,
            tasks.import_trakt_collection_csv,
            user_id=request.user.id,
            file=payloads[0][1],
            mode=mode,
            staged_paths=tuple(staged_files),
        ) is False:
            return _integration_redirect(request, connected_slug="trakt")
        messages.info(
            request,
            "The task to import collection data from the Trakt CSV file has been "
            "queued.",
        )
        return _integration_redirect(request, connected_slug="trakt")

    if len(payloads) == 1 and staged_payload_is_zip(payloads[0][1]):
        archive_path = payloads[0][1]
    else:
        try:
            archive_path = str(build_staged_zip(payloads))
        except OSError:
            for path in staged_files:
                discard_staged_upload(path)
            logger.exception("Could not build staged Trakt export archive")
            messages.error(
                request,
                "The Trakt export could not be prepared. Check available disk space and try again.",
            )
            return _integration_redirect(request)
        for path in staged_files:
            discard_staged_upload(path)

    if _queue_staged_task_or_message(
        request,
        tasks.import_trakt_export,
        user_id=request.user.id,
        file=archive_path,
        mode=mode,
        staged_paths=(archive_path,),
    ) is False:
        return _integration_redirect(request, connected_slug="trakt")
    messages.info(
        request,
        "The task to import your Trakt data export has been queued.",
    )
    return _integration_redirect(request, connected_slug="trakt")


def _is_trakt_export_payload(name, path):
    """Whether an upload is part of the JSON/zip export rather than the legacy CSV."""
    return name.lower().endswith((".zip", ".json")) or staged_payload_is_zip(path)


@require_POST
def import_hltb(request):
    """View for importing game date from HowLongToBeat."""
    file = request.FILES.get("hltb_csv")

    if not file:
        messages.error(request, "HowLongToBeat CSV file is required.")
        return _integration_redirect(request)

    staged_file = _stage_upload_or_message(request, file, "HowLongToBeat CSV")
    if staged_file is None:
        return _integration_redirect(request)

    mode = request.POST["mode"]
    if _queue_staged_task_or_message(
        request,
        tasks.import_hltb,
        user_id=request.user.id,
        file=staged_file,
        mode=mode,
        staged_paths=(staged_file,),
    ) is False:
        return _integration_redirect(request, connected_slug="hltb")
    messages.info(
        request,
        "The task to import media from HowLongToBeat CSV file has been queued.",
    )
    return _integration_redirect(request, connected_slug="hltb")


@require_POST
def import_grouvee(request):
    """View for importing game data from a Grouvee export (JSON or zip)."""
    file = request.FILES.get("grouvee_json")

    if not file:
        messages.error(request, "A Grouvee export file is required.")
        return _integration_redirect(request)

    staged_file = _stage_upload_or_message(request, file, "Grouvee export")
    if staged_file is None:
        return _integration_redirect(request)

    mode = request.POST["mode"]
    if _queue_staged_task_or_message(
        request,
        tasks.import_grouvee,
        user_id=request.user.id,
        file=staged_file,
        mode=mode,
        staged_paths=(staged_file,),
    ) is False:
        return _integration_redirect(request, connected_slug="grouvee")
    messages.info(
        request,
        "The task to import media from the Grouvee export has been queued.",
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
    """Connect a new Radarr instance using base URL + API key."""
    base_url = request.POST.get("base_url", "").strip()
    api_key = request.POST.get("api_key", "").strip()
    name = request.POST.get("name", "").strip()
    if not base_url or not api_key:
        messages.error(request, "Radarr base URL and API key are required.")
        return _integration_redirect(request)

    try:
        RadarrClient(base_url, api_key).healthcheck()
    except (helpers.MediaImportError, requests.RequestException) as exc:
        messages.error(request, f"Failed to connect to Radarr: {exc}")
        return _integration_redirect(request)

    try:
        instance = _run_with_lock_retry(
            "create Radarr instance",
            lambda: RadarrInstance.objects.create(
                user=request.user,
                name=name,
                base_url=base_url,
                api_key=helpers.encrypt(api_key),
            ),
        )
    except IntegrityError:
        messages.error(
            request, "You already have a Radarr instance connected at this URL."
        )
        return _integration_redirect(request)

    _ensure_arr_schedule(instance, RADARR_RECURRING_TASK_NAME, "Radarr")
    tasks.import_radarr.delay(user_id=request.user.id, mode="new", instance_id=instance.id)
    messages.success(
        request,
        "Connected Radarr. Initial import queued and recurring sync enabled.",
    )
    return _integration_redirect(request, connected_slug="radarr")


@require_POST
def radarr_disconnect(request):
    """Disconnect one Radarr instance."""
    from django_celery_beat.models import PeriodicTask

    instance = get_object_or_404(
        RadarrInstance, pk=request.POST.get("instance_id"), user=request.user
    )

    def _disconnect():
        PeriodicTask.objects.filter(
            _periodic_task_filter_for_instance(instance.id),
            task=RADARR_RECURRING_TASK_NAME,
        ).delete()
        CollectionSourceState.objects.filter(
            user=request.user, source="radarr", source_instance_id=instance.id
        ).delete()
        instance.delete()

    _run_with_lock_retry("disconnect Radarr", _disconnect)
    messages.info(request, "Disconnected Radarr.")
    return redirect("import_data")


@require_POST
def import_radarr(request):
    """Queue Radarr import and ensure recurring schedule exists."""
    instance = get_object_or_404(
        RadarrInstance, pk=request.POST.get("instance_id"), user=request.user
    )

    tasks.import_radarr.delay(user_id=request.user.id, mode="new", instance_id=instance.id)
    _ensure_arr_schedule(instance, RADARR_RECURRING_TASK_NAME, "Radarr")
    messages.info(request, "Radarr import queued.")
    return redirect("import_data")


@require_POST
def sonarr_connect(request):
    """Connect a new Sonarr instance using base URL + API key."""
    base_url = request.POST.get("base_url", "").strip()
    api_key = request.POST.get("api_key", "").strip()
    name = request.POST.get("name", "").strip()
    if not base_url or not api_key:
        messages.error(request, "Sonarr base URL and API key are required.")
        return _integration_redirect(request)

    try:
        SonarrClient(base_url, api_key).healthcheck()
    except (helpers.MediaImportError, requests.RequestException) as exc:
        messages.error(request, f"Failed to connect to Sonarr: {exc}")
        return _integration_redirect(request)

    try:
        instance = _run_with_lock_retry(
            "create Sonarr instance",
            lambda: SonarrInstance.objects.create(
                user=request.user,
                name=name,
                base_url=base_url,
                api_key=helpers.encrypt(api_key),
            ),
        )
    except IntegrityError:
        messages.error(
            request, "You already have a Sonarr instance connected at this URL."
        )
        return _integration_redirect(request)

    _ensure_arr_schedule(instance, SONARR_RECURRING_TASK_NAME, "Sonarr")
    tasks.import_sonarr.delay(user_id=request.user.id, mode="new", instance_id=instance.id)
    messages.success(
        request,
        "Connected Sonarr. Initial import queued and recurring sync enabled.",
    )
    return _integration_redirect(request, connected_slug="sonarr")


@require_POST
def sonarr_disconnect(request):
    """Disconnect one Sonarr instance."""
    from django_celery_beat.models import PeriodicTask

    instance = get_object_or_404(
        SonarrInstance, pk=request.POST.get("instance_id"), user=request.user
    )

    def _disconnect():
        PeriodicTask.objects.filter(
            _periodic_task_filter_for_instance(instance.id),
            task=SONARR_RECURRING_TASK_NAME,
        ).delete()
        CollectionSourceState.objects.filter(
            user=request.user, source="sonarr", source_instance_id=instance.id
        ).delete()
        instance.delete()

    _run_with_lock_retry("disconnect Sonarr", _disconnect)
    messages.info(request, "Disconnected Sonarr.")
    return redirect("import_data")


@require_POST
def import_sonarr(request):
    """Queue Sonarr import and ensure recurring schedule exists."""
    instance = get_object_or_404(
        SonarrInstance, pk=request.POST.get("instance_id"), user=request.user
    )

    tasks.import_sonarr.delay(user_id=request.user.id, mode="new", instance_id=instance.id)
    _ensure_arr_schedule(instance, SONARR_RECURRING_TASK_NAME, "Sonarr")
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

    existing_account = getattr(request.user, "jellyfin_account", None)
    identity_changed = existing_account is not None and (
        existing_account.base_url != base_url
        or existing_account.jellyfin_user_id != current_user["Id"]
    )

    defaults = {
        "base_url": base_url,
        "api_key": helpers.encrypt(api_key),
        "jellyfin_user_id": current_user["Id"],
        "jellyfin_username": current_user.get("Name", ""),
        "connection_broken": False,
        "last_error_message": "",
    }
    if existing_account is None or identity_changed:
        # A different server/user invalidates any cached pull state: a
        # Playback Reporting rowid or "unavailable" result from the old
        # identity would otherwise silently carry over to the new one.
        defaults.update(
            {
                "playback_reporting_available": None,
                "playback_reporting_last_rowid": None,
                "library_backfill_completed_at": None,
            },
        )

    def _connect():
        account, _ = JellyfinAccount.objects.update_or_create(
            user=request.user,
            defaults=defaults,
        )
        if account.pull_history_enabled:
            _ensure_jellyfin_pull_schedule(request.user, account)
        return account

    _run_with_lock_retry("connect Jellyfin", _connect)

    # Seamless by default: queue an automatic history pull right away so a
    # newly connected user sees their watch history without any manual
    # export/upload step, and keep it running on a schedule going forward.
    tasks.pull_jellyfin_history.delay(user_id=request.user.id)

    messages.success(
        request,
        "Connected Jellyfin. Importing your watch history now.",
    )
    return redirect("integrations")


@require_POST
def jellyfin_disconnect(request):
    """Disconnect the Jellyfin integration."""

    def _disconnect():
        _disable_jellyfin_push_schedule(request.user)
        _disable_jellyfin_pull_schedule(request.user)
        JellyfinAccount.objects.filter(user=request.user).delete()

    _run_with_lock_retry("disconnect Jellyfin", _disconnect)
    messages.info(request, "Disconnected Jellyfin.")
    return redirect("integrations")


@require_POST
def jellyfin_settings(request):
    """Update Jellyfin push-sync and history-pull toggles."""
    account = getattr(request.user, "jellyfin_account", None)
    if not account:
        messages.error(request, "Connect Jellyfin before changing sync settings.")
        return redirect("integrations")

    account.push_watched_enabled = "push_watched_enabled" in request.POST
    account.push_unwatched_enabled = "push_unwatched_enabled" in request.POST
    account.scheduled_push_enabled = "scheduled_push_enabled" in request.POST
    account.instant_push_enabled = "instant_push_enabled" in request.POST
    account.pull_history_enabled = "pull_history_enabled" in request.POST
    account.save(
        update_fields=[
            "push_watched_enabled",
            "push_unwatched_enabled",
            "scheduled_push_enabled",
            "instant_push_enabled",
            "pull_history_enabled",
        ],
    )

    if account.scheduled_push_enabled:
        _ensure_jellyfin_push_schedule(request.user, account)
    else:
        _disable_jellyfin_push_schedule(request.user)

    if account.pull_history_enabled:
        _ensure_jellyfin_pull_schedule(request.user, account)
    else:
        _disable_jellyfin_pull_schedule(request.user)

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


@require_POST
def jellyfin_pull_now(request):
    """Queue an immediate automatic Jellyfin history pull."""
    account = getattr(request.user, "jellyfin_account", None)
    if not account or not account.is_connected:
        messages.error(request, "Connect Jellyfin before importing history.")
        return redirect("integrations")

    tasks.pull_jellyfin_history.delay(user_id=request.user.id)
    messages.info(request, "Jellyfin history import queued.")
    return redirect("integrations")


@require_POST
def jellyfin_playback_reporting_import(request):
    """Queue a manual Playback Reporting TSV import for the connected user."""
    account = getattr(request.user, "jellyfin_account", None)
    if not account or not account.is_connected:
        messages.error(request, "Connect Jellyfin before importing Playback Reporting data.")
        return redirect("integrations")

    uploaded_file = request.FILES.get("playback_reporting_file")
    if not uploaded_file:
        messages.error(request, "Choose a Playback Reporting TSV export first.")
        return redirect("integrations")

    if uploaded_file.size > JELLYFIN_PLAYBACK_REPORTING_MAX_UPLOAD_BYTES:
        messages.error(request, "The Playback Reporting export is larger than 50 MB.")
        return redirect("integrations")

    if uploaded_file.size == 0:
        messages.error(request, "The Playback Reporting export is empty.")
        return redirect("integrations")

    staged_file = _stage_upload_or_message(
        request,
        uploaded_file,
        "Jellyfin Playback Reporting export",
    )
    if staged_file is None:
        return redirect("integrations")

    if _queue_staged_task_or_message(
        request,
        tasks.import_jellyfin_playback_reporting,
        staged_file,
        request.user.id,
        "new",
        staged_paths=(staged_file,),
    ) is False:
        return redirect("integrations")
    messages.info(request, "Jellyfin Playback Reporting import queued.")
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

    def _connect():
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

    _run_with_lock_retry("connect Audiobookshelf", _connect)
    tasks.import_audiobookshelf.delay(user_id=request.user.id, mode="new")
    messages.success(request, "Connected Audiobookshelf. Initial import queued.")
    return _integration_redirect(request, connected_slug="audiobookshelf")


@require_POST
def audiobookshelf_disconnect(request):
    """Disconnect Audiobookshelf integration."""
    from django_celery_beat.models import PeriodicTask

    def _disconnect():
        PeriodicTask.objects.filter(
            task="Import from Audiobookshelf (Recurring)",
            kwargs__contains=f'"user_id": {request.user.id}',
        ).delete()
        AudiobookshelfAccount.objects.filter(user=request.user).delete()

    _run_with_lock_retry("disconnect Audiobookshelf", _disconnect)
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


AUDIOBOOKSHELF_COVER_TIMEOUT = 15
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
        return _placeholder_image_response()

    cover_url = f"{account.base_url.rstrip('/')}/api/items/{library_item_id}/cover"
    try:
        upstream = requests.get(
            cover_url,
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=AUDIOBOOKSHELF_COVER_TIMEOUT,
            stream=True,
        )
    except requests.RequestException as error:
        logger.warning(
            "Audiobookshelf cover unavailable: request failed "
            "account=%s item=%s error=%s",
            account_id,
            library_item_id,
            exception_summary(error),
        )
        return _placeholder_image_response()

    try:
        if upstream.status_code != HTTPStatus.OK:
            logger.warning(
                "Audiobookshelf cover unavailable: upstream status=%s "
                "account=%s item=%s",
                upstream.status_code,
                account_id,
                library_item_id,
            )
            return _placeholder_image_response()

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
            return _placeholder_image_response()

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
            return _placeholder_image_response()

        body = bytearray()
        oversized = False
        for chunk in upstream.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            body.extend(chunk)
            if len(body) > image_cache.MAX_IMAGE_BYTES:
                oversized = True
                break
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
        return _placeholder_image_response()

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
            return _placeholder_image_response()
        content_type = sniffed

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

    uri, plex_token = plex_api.connection_for_machine(
        account.sections,
        machine_identifier,
        account.plex_token,
    )
    if not uri or not plex_token:
        return HttpResponseNotFound()

    try:
        upstream = requests.get(
            f"{uri}{thumb_path}",
            params={"X-Plex-Token": plex_token},
            timeout=PLEX_COVER_TIMEOUT,
            stream=True,
            verify=settings.PLEX_SSL_VERIFY,
        )
    except requests.RequestException:
        return HttpResponseNotFound()

    try:
        if upstream.status_code != HTTPStatus.OK:
            return HttpResponseNotFound()

        content_type = (
            upstream.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        )
        if content_type not in PLEX_COVER_CONTENT_TYPES:
            return HttpResponseNotFound()

        try:
            content_length = int(upstream.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length > image_cache.MAX_IMAGE_BYTES:
            return HttpResponseNotFound()

        body = bytearray()
        for chunk in upstream.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            body.extend(chunk)
            if len(body) > image_cache.MAX_IMAGE_BYTES:
                return HttpResponseNotFound()
    finally:
        upstream.close()

    response = HttpResponse(bytes(body), content_type=content_type)
    response["Cache-Control"] = "private, max-age=3600"
    return response


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

        def _connect():
            StorytellerAccount.objects.update_or_create(
                user=request.user,
                defaults={
                    "server_url": pending["server_url"],
                    "auth_token": helpers.encrypt(access_token),
                    "connection_broken": False,
                    "last_error_message": "",
                },
            )
            _ensure_storyteller_schedule(request.user)

        _run_with_lock_retry("connect Storyteller", _connect)
        request.session.pop(STORYTELLER_PENDING_SESSION_KEY, None)
        tasks.import_storyteller.delay(user_id=request.user.id, mode="new")
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

    def _disconnect():
        PeriodicTask.objects.filter(
            task=STORYTELLER_RECURRING_TASK_NAME,
            kwargs__contains=f'"user_id": {request.user.id}',
        ).delete()
        StorytellerAccount.objects.filter(user=request.user).delete()

    _run_with_lock_retry("disconnect Storyteller", _disconnect)
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


KOREADER_IMPORT_TASK_NAME = "Import from KOReader"
KOREADER_MAX_COMPLETION = 100


def _parse_finished_threshold_percent(post):
    """Return a 0-1 completion threshold from a percentage form field."""
    raw = (post.get("finished_threshold_percent") or "").strip()
    if not raw:
        return 1.0
    try:
        percent = float(raw)
    except ValueError as exc:
        msg = "Completion threshold must be a number between 1 and 100."
        raise ValueError(msg) from exc
    if not 1 <= percent <= KOREADER_MAX_COMPLETION:
        msg = "Completion threshold must be between 1 and 100 percent."
        raise ValueError(msg)
    return percent / 100.0


def _koreader_options_from_post(post):
    """Read KOReader account toggles from a form POST."""
    return {
        "verify_ssl": post.get("verify_ssl") == "on",
        "create_missing": post.get("create_missing") == "on",
        "skip_finished_books": post.get("skip_finished_books") == "on",
        "finished_threshold": _parse_finished_threshold_percent(post),
    }


def _validate_koreader_connection(server_url, username, auth_key, verify_ssl):
    """Verify credentials against the sync server or raise."""
    client = KoreaderClient(server_url, username, auth_key, verify_ssl=verify_ssl)
    client.auth()


@require_POST
def koreader_connect(request):
    """Connect a KOReader sync server account."""
    server_url = request.POST.get("server_url", "").strip().rstrip("/")
    username = request.POST.get("username", "").strip()
    password = request.POST.get("password", "")
    try:
        options = _koreader_options_from_post(request.POST)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("import_data")
    mode = request.POST.get("mode", "new")
    frequency = request.POST.get("frequency", "once")
    import_time = request.POST.get("time", "00:00")

    if not server_url or not username or not password:
        messages.error(request, "Server URL, username, and password are required.")
        return redirect("import_data")

    auth_key = KoreaderClient.password_to_auth_key(password)
    try:
        _validate_koreader_connection(
            server_url,
            username,
            auth_key,
            options["verify_ssl"],
        )
    except KoreaderAuthError as exc:
        messages.error(request, str(exc))
        return redirect("import_data")
    except KoreaderClientError as exc:
        messages.error(request, f"Could not reach KOReader sync server: {exc}")
        return redirect("import_data")
    except requests.RequestException as exc:
        messages.error(request, f"Could not reach KOReader sync server: {exc}")
        return redirect("import_data")

    _run_with_lock_retry(
        "connect KOReader",
        lambda: KoreaderAccount.objects.update_or_create(
            user=request.user,
            defaults={
                "server_url": server_url,
                "username": username,
                "auth_key": helpers.encrypt(auth_key),
                **options,
                "connection_broken": False,
                "last_error_message": "",
            },
        ),
    )

    if frequency == "once":
        tasks.import_koreader.delay(user_id=request.user.id, mode=mode)
        messages.success(request, "Connected to KOReader. Import queued.")
    else:
        helpers.create_import_schedule(
            username=username,
            request=request,
            mode=mode,
            frequency=frequency,
            import_time=import_time,
            source="KOReader",
            extra_kwargs={"user_id": request.user.id},
        )
        tasks.import_koreader.delay(user_id=request.user.id, mode=mode)
        messages.success(request, "Connected to KOReader. Import scheduled.")
    return redirect("import_data")


@require_POST
def koreader_settings(request):
    """Update KOReader connection and sync options."""
    account = getattr(request.user, "koreader_account", None)
    if not account:
        messages.error(request, "Connect KOReader before changing settings.")
        return redirect("import_data")

    server_url = request.POST.get("server_url", "").strip().rstrip("/")
    username = request.POST.get("username", "").strip()
    password = request.POST.get("password", "")
    try:
        options = _koreader_options_from_post(request.POST)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("import_data")

    if not server_url or not username:
        messages.error(request, "Server URL and username are required.")
        return redirect("import_data")

    if password:
        auth_key = KoreaderClient.password_to_auth_key(password)
    else:
        try:
            auth_key = helpers.decrypt_or_raise(account.auth_key)
        except helpers.MediaImportError as exc:
            messages.error(request, str(exc))
            return redirect("import_data")

    try:
        _validate_koreader_connection(
            server_url,
            username,
            auth_key,
            options["verify_ssl"],
        )
    except KoreaderAuthError as exc:
        messages.error(request, str(exc))
        return redirect("import_data")
    except KoreaderClientError as exc:
        messages.error(request, f"Could not reach KOReader sync server: {exc}")
        return redirect("import_data")
    except requests.RequestException as exc:
        messages.error(request, f"Could not reach KOReader sync server: {exc}")
        return redirect("import_data")

    account.server_url = server_url
    account.username = username
    account.auth_key = helpers.encrypt(auth_key)
    account.verify_ssl = options["verify_ssl"]
    account.create_missing = options["create_missing"]
    account.skip_finished_books = options["skip_finished_books"]
    account.finished_threshold = options["finished_threshold"]
    account.connection_broken = False
    account.last_error_message = ""
    account.save(
        update_fields=[
            "server_url",
            "username",
            "auth_key",
            "verify_ssl",
            "create_missing",
            "skip_finished_books",
            "finished_threshold",
            "connection_broken",
            "last_error_message",
            "updated_at",
        ],
    )
    messages.success(request, "KOReader settings saved.")
    return redirect("import_data")


@require_POST
def koreader_disconnect(request):
    """Disconnect the KOReader integration."""
    from django_celery_beat.models import PeriodicTask

    def _disconnect():
        PeriodicTask.objects.filter(
            task=KOREADER_IMPORT_TASK_NAME,
            kwargs__contains=f'"user_id": {request.user.id}',
        ).delete()
        KoreaderDocumentLink.objects.filter(user=request.user).delete()
        KoreaderAccount.objects.filter(user=request.user).delete()

    _run_with_lock_retry("disconnect KOReader", _disconnect)
    messages.info(request, "Disconnected KOReader.")
    return redirect("import_data")


@require_POST
def import_koreader(request):
    """Queue a KOReader import or update its schedule."""
    account = getattr(request.user, "koreader_account", None)
    if not account:
        messages.error(request, "Connect KOReader before importing.")
        return redirect("import_data")

    mode = request.POST["mode"]
    frequency = request.POST["frequency"]
    import_time = request.POST["time"]

    if frequency == "once":
        tasks.import_koreader.delay(user_id=request.user.id, mode=mode)
        messages.info(request, "KOReader import queued.")
    else:
        helpers.create_import_schedule(
            username=account.username,
            request=request,
            mode=mode,
            frequency=frequency,
            import_time=import_time,
            source="KOReader",
            extra_kwargs={"user_id": request.user.id},
        )
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
    tasks.import_stremio.delay(user_id=request.user.id, mode="new")
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
            kwargs__contains=f'"user_id": {request.user.id}',
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

    tasks.import_stremio.delay(user_id=request.user.id, mode="new")
    _ensure_stremio_schedule(request.user)
    messages.info(request, "Stremio import queued.")
    return redirect("import_data")


XBOX_RECURRING_TASK_NAME = "Import from Xbox (Recurring)"
PSN_RECURRING_TASK_NAME = "Import from PSN (Recurring)"
CONSOLE_RECURRING_FREQUENCIES = {"daily": "*", "2days": "*/2"}
CONSOLE_DEFAULT_IMPORT_TIME = "04:00"


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


def _console_schedule_name(source, user, parsed_time, frequency):
    """Name a user's console schedule for the beat admin and the schedule list."""
    return f"Import from {source} for {user.username} at {parsed_time} {frequency}"


def _reclaim_console_schedule_name(source, task_name, parsed_time, frequency):
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

    current_name = _console_schedule_name(source, holder_user, parsed_time, frequency)
    if current_name == task_name:
        # The holder is entitled to the name; it just isn't ours.
        return False

    holder.name = current_name
    holder.save(update_fields=["name"])
    return True


def _create_console_schedule(
    request,
    source,
    recurring_task_name,
    mode,
    frequency,
    import_time,
):
    """Create a recurring console import schedule for the chosen time."""
    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    try:
        parsed_time = datetime.strptime(import_time, "%H:%M").time()  # noqa: DTZ007  # wall-clock value; the crontab carries the timezone
    except (TypeError, ValueError):
        messages.error(request, "Invalid import time.")
        return

    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute=parsed_time.minute,
        hour=parsed_time.hour,
        day_of_week=CONSOLE_RECURRING_FREQUENCIES[frequency],
        day_of_month="*",
        month_of_year="*",
        timezone=timezone.get_default_timezone(),
    )

    task_name = _console_schedule_name(source, request.user, parsed_time, frequency)
    desired_kwargs = json.dumps({"user_id": request.user.id, "mode": mode})
    existing_task = (
        PeriodicTask.objects.filter(
            _periodic_task_filter_for_user(request.user.id),
            task=recurring_task_name,
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
        messages.success(request, f"{source} import task re-enabled.")
        return

    if not _reclaim_console_schedule_name(source, task_name, parsed_time, frequency):
        messages.error(request, "The same import task is already scheduled.")
        return

    try:
        PeriodicTask.objects.create(
            name=task_name,
            task=recurring_task_name,
            crontab=crontab,
            kwargs=desired_kwargs,
            start_time=_next_crontab_run(crontab),
            enabled=True,
        )
    except IntegrityError:
        logger.exception("%s schedule %s could not be created", source, task_name)
        messages.error(request, "The same import task is already scheduled.")
        return

    messages.success(request, f"{source} import task scheduled.")


def _start_console_import(request, source, task, recurring_task_name):
    """Queue a one-off console import, or schedule a recurring one.

    A scheduled import only runs on its schedule; a one time import runs
    straight away and creates no periodic task.
    """
    mode = request.POST.get("mode") or "new"
    frequency = request.POST.get("frequency") or "once"
    import_time = request.POST.get("time") or CONSOLE_DEFAULT_IMPORT_TIME

    if frequency not in CONSOLE_RECURRING_FREQUENCIES:
        task.delay(user_id=request.user.id, mode=mode)
        messages.info(
            request,
            f"The task to import media from {source} has been queued.",
        )
        return

    _create_console_schedule(
        request,
        source,
        recurring_task_name,
        mode,
        frequency,
        import_time,
    )


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

    _run_with_lock_retry(
        "connect Xbox",
        lambda: XboxAccount.objects.update_or_create(
            user=request.user,
            defaults={
                "api_key": helpers.encrypt(api_key),
                "xuid": xuid,
                "gamertag": gamertag,
                "connection_broken": False,
                "last_error_message": "",
            },
        ),
    )
    messages.success(request, f"Connected to Xbox as {gamertag or xuid}.")
    _run_with_lock_retry(
        "schedule Xbox import",
        lambda: _start_console_import(
            request, "Xbox", tasks.import_xbox, XBOX_RECURRING_TASK_NAME
        ),
    )
    return redirect("import_data")


@require_POST
def xbox_disconnect(request):
    """Disconnect the Xbox integration."""
    from django_celery_beat.models import PeriodicTask

    def _disconnect():
        PeriodicTask.objects.filter(
            _periodic_task_filter_for_user(request.user.id),
            task=XBOX_RECURRING_TASK_NAME,
        ).delete()
        XboxAccount.objects.filter(user=request.user).delete()

    _run_with_lock_retry("disconnect Xbox", _disconnect)
    messages.info(request, "Disconnected Xbox.")
    return redirect("import_data")


@require_POST
def import_xbox(request):
    """Queue a one-off Xbox import or schedule a recurring one."""
    account = getattr(request.user, "xbox_account", None)
    if not account:
        messages.error(request, "Connect Xbox before importing.")
        return redirect("import_data")

    _start_console_import(request, "Xbox", tasks.import_xbox, XBOX_RECURRING_TASK_NAME)
    return redirect("import_data")


@require_POST
def psn_connect(request):
    """Connect a PlayStation Network account using an NPSSO token."""
    npsso = request.POST.get("npsso", "").strip()
    if not npsso:
        messages.error(request, "A PSN NPSSO token is required.")
        return redirect("import_data")

    try:
        account_id, online_id = psn_api.get_account(npsso)
    except helpers.MediaImportError as error:
        messages.error(
            request,
            f"Could not connect to PlayStation Network: {error}",
        )
        return redirect("import_data")
    except Exception as error:
        logger.exception("Failed to connect to PlayStation Network")
        messages.error(
            request,
            "Failed to connect to PlayStation Network "
            f"({exception_summary(error)}). Check the logs for details.",
        )
        return redirect("import_data")

    _run_with_lock_retry(
        "connect PSN",
        lambda: PSNAccount.objects.update_or_create(
            user=request.user,
            defaults={
                "npsso": helpers.encrypt(npsso),
                "account_id": account_id,
                "online_id": online_id,
                "connection_broken": False,
                "last_error_message": "",
            },
        ),
    )
    messages.success(
        request,
        f"Connected to PlayStation Network as {online_id or account_id}.",
    )
    _run_with_lock_retry(
        "schedule PSN import",
        lambda: _start_console_import(
            request, "PSN", tasks.import_psn, PSN_RECURRING_TASK_NAME
        ),
    )
    return redirect("import_data")


@require_POST
def psn_disconnect(request):
    """Disconnect the PlayStation Network integration."""
    from django_celery_beat.models import PeriodicTask

    def _disconnect():
        PeriodicTask.objects.filter(
            _periodic_task_filter_for_user(request.user.id),
            task=PSN_RECURRING_TASK_NAME,
        ).delete()
        PSNAccount.objects.filter(user=request.user).delete()

    _run_with_lock_retry("disconnect PSN", _disconnect)
    messages.info(request, "Disconnected PlayStation Network.")
    return redirect("import_data")


@require_POST
def import_psn(request):
    """Queue a one-off PSN import or schedule a recurring one."""
    account = getattr(request.user, "psn_account", None)
    if not account:
        messages.error(request, "Connect PlayStation Network before importing.")
        return redirect("import_data")

    _start_console_import(request, "PSN", tasks.import_psn, PSN_RECURRING_TASK_NAME)
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

        from django_celery_beat.models import CrontabSchedule, PeriodicTask

        def _connect():
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
            existing_task = PeriodicTask.objects.filter(
                task="Import from Pocket Casts (Recurring)",
                kwargs__contains=f'"user_id": {request.user.id}',
                enabled=True,
            ).first()

            if existing_task:
                return False

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
            return True

        newly_scheduled = _run_with_lock_retry("connect Pocket Casts", _connect)

        if newly_scheduled:
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

    def _disconnect():
        # Delete periodic import task if it exists
        PeriodicTask.objects.filter(
            task="Import from Pocket Casts (Recurring)",
            kwargs__contains=f'"user_id": {request.user.id}',
        ).delete()

        # Clear all credentials (full disconnect)
        PocketCastsAccount.objects.filter(user=request.user).delete()

    _run_with_lock_retry("disconnect Pocket Casts", _disconnect)
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
        from django_celery_beat.models import CrontabSchedule, PeriodicTask

        def _connect():
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

            existing_task = PeriodicTask.objects.filter(
                task=GPODDER_RECURRING_TASK_NAME,
                kwargs__contains=f'"user_id": {request.user.id}',
                enabled=True,
            ).first()
            if existing_task:
                return False

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
            return True

        newly_scheduled = _run_with_lock_retry("connect GPodder", _connect)

        if newly_scheduled:
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

    def _disconnect():
        PeriodicTask.objects.filter(
            task=GPODDER_RECURRING_TASK_NAME,
            kwargs__contains=f'"user_id": {request.user.id}',
        ).delete()
        GPodderAccount.objects.filter(user=request.user).delete()

    _run_with_lock_retry("disconnect GPodder", _disconnect)
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

        def _connect():
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

        _run_with_lock_retry("connect Last.fm", _connect)
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

    def _connect():
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

    _run_with_lock_retry("connect Koito", _connect)
    tasks.poll_koito_for_user.delay(user_id=request.user.id)
    tasks.import_koito_history.delay(user_id=request.user.id, reset=True)
    messages.success(request, "Connected Koito. Full history import queued.")
    return _integration_redirect(request, connected_slug="koito")


@require_POST
def koito_disconnect(request):
    """Disconnect the Koito integration."""
    from django_celery_beat.models import PeriodicTask

    def _disconnect():
        PeriodicTask.objects.filter(
            task=tasks.KOITO_POLL_TASK_NAME,
            kwargs__contains=f'"user_id": {request.user.id}',
        ).delete()
        KoitoAccount.objects.filter(user=request.user).delete()

    _run_with_lock_retry("disconnect Koito", _disconnect)
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

    staged_file = _stage_upload_or_message(request, file, "IMDB CSV")
    if staged_file is None:
        return _integration_redirect(request)

    mode = request.POST["mode"]
    if _queue_staged_task_or_message(
        request,
        tasks.import_imdb,
        user_id=request.user.id,
        file=staged_file,
        mode=mode,
        staged_paths=(staged_file,),
    ) is False:
        return _integration_redirect(request, connected_slug="imdb")
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

    staged_file = _stage_upload_or_message(request, file, "Goodreads CSV")
    if staged_file is None:
        return _integration_redirect(request)

    mode = request.POST["mode"]
    if _queue_staged_task_or_message(
        request,
        tasks.import_goodreads,
        user_id=request.user.id,
        file=staged_file,
        mode=mode,
        staged_paths=(staged_file,),
    ) is False:
        return _integration_redirect(request, connected_slug="goodreads")
    messages.info(
        request,
        "The task to import media from Goodreads CSV file has been queued.",
    )
    return _integration_redirect(request, connected_slug="goodreads")


@require_POST
def import_hardcover(request):
    """View for importing books data from Hardcover CSV and/or saving a personal API key."""
    file = request.FILES.get("hardcover_csv")
    api_key = request.POST.get("hardcover_api_key", "").strip()

    if not file and not api_key:
        messages.error(request, "Enter a Hardcover API key or select a CSV file.")
        return _integration_redirect(request)

    if api_key:
        credentials.set_user("hardcover", request.user, {"api_key": api_key})
        messages.success(request, "Hardcover API key saved.")

    if file:
        staged_file = _stage_upload_or_message(request, file, "Hardcover CSV")
        if staged_file is None:
            return _integration_redirect(request, connected_slug="hardcover")

        mode = request.POST["mode"]
        if _queue_staged_task_or_message(
            request,
            tasks.import_hardcover,
            user_id=request.user.id,
            file=staged_file,
            mode=mode,
            staged_paths=(staged_file,),
        ) is False:
            return _integration_redirect(request, connected_slug="hardcover")
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

    staged_file = _stage_upload_or_message(request, file, "StoryGraph CSV")
    if staged_file is None:
        return _integration_redirect(request)

    mode = request.POST["mode"]
    if _queue_staged_task_or_message(
        request,
        tasks.import_storygraph,
        user_id=request.user.id,
        file=staged_file,
        mode=mode,
        staged_paths=(staged_file,),
    ) is False:
        return _integration_redirect(request, connected_slug="storygraph")
    messages.info(
        request,
        "The task to import media from StoryGraph CSV file has been queued.",
    )
    return _integration_redirect(request, connected_slug="storygraph")


@require_POST
def import_tvtime(request):
    """View for importing watch history from TV Time's GDPR export CSVs."""
    shows_file = request.FILES.get("tvtime_shows_csv")
    movies_file = request.FILES.get("tvtime_movies_csv")

    if not shows_file and not movies_file:
        messages.error(
            request,
            "Select at least one TV Time CSV file (shows and/or movies).",
        )
        return _integration_redirect(request)

    uploads = [upload for upload in (shows_file, movies_file) if upload]
    staged_files = _stage_uploads_or_message(request, uploads, "TV Time CSV")
    if staged_files is None:
        return _integration_redirect(request)

    mode = request.POST["mode"]
    staged_index = 0
    if shows_file:
        staged_file = staged_files[staged_index]
        staged_index += 1
        if _queue_staged_task_or_message(
            request,
            tasks.import_tvtime_shows,
            user_id=request.user.id,
            file=staged_file,
            mode=mode,
            staged_paths=(staged_file,),
        ) is False:
            for path in staged_files[staged_index:]:
                discard_staged_upload(path)
            return _integration_redirect(request, connected_slug="tvtime")
    if movies_file:
        staged_file = staged_files[staged_index]
        if _queue_staged_task_or_message(
            request,
            tasks.import_tvtime_movies,
            user_id=request.user.id,
            file=staged_file,
            mode=mode,
            staged_paths=(staged_file,),
        ) is False:
            return _integration_redirect(request, connected_slug="tvtime")
    messages.info(
        request,
        "The task to import media from TV Time CSV file(s) has been queued.",
    )
    return _integration_redirect(request, connected_slug="tvtime")


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


@require_GET
def export_csv_letterboxd(request):
    """View for exporting the user's watched movies as a Letterboxd import CSV."""
    now = timezone.localtime()
    response = StreamingHttpResponse(
        streaming_content=exports.generate_letterboxd_rows(request.user),
        content_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="letterboxd_{now}.csv"',
        },
    )
    logger.info("User %s started Letterboxd CSV export", request.user.username)
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
    payload_usernames = extract_plex_webhook_usernames(payload)
    for share in PlexWebhookShare.objects.filter(
        owner=user,
        recipient_enabled=True,
        recipient__is_active=True,
    ).only("id", "recipient_id", "plex_username"):
        if share.plex_username.strip().casefold() in payload_usernames:
            tasks.process_webhook.delay(
                "plex",
                payload,
                share.recipient_id,
                share_id=share.id,
            )
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
    # Keep the existing addon id so installed clients remain compatible.
    "id": "org.yamtrack.scrobbler",
    "version": "1.2.0",
    "name": "Floppy",
    "description": (
        "Floppy Watchlist catalogs and playback scrobbling for Stremio."
    ),
    "resources": ["catalog", "meta", "subtitles"],
    "types": ["movie", "series"],
    "idPrefixes": ["tt"],
    "catalogs": [],
    "behaviorHints": {"configurable": True, "configurationRequired": False},
}
STREMIO_SCROBBLE_THROTTLE_SECONDS = 1800
STREMIO_MAX_MEDIA_ID_LENGTH = 128
STREMIO_MEDIA_ID_PATTERN = re.compile(
    r"^tt[0-9]+(?::[1-9][0-9]*:[1-9][0-9]*)?$",
)


def _stremio_addon_response(payload, status=200):
    """Build a JSON response with the CORS headers Stremio requires."""
    response = JsonResponse(payload, status=status)
    response["Access-Control-Allow-Origin"] = "*"
    return response


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
    except ValueError as error:
        return _stremio_addon_response({"error": str(error)}, status=400)

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
        user = users.models.User.objects.get(token=token)
    except ObjectDoesNotExist:
        logger.warning("Invalid token on Stremio addon configure request")
        return HttpResponse("Invalid token", status=401)

    return render(
        request,
        "integrations/stremio_configure.html",
        {
            "catalog_options": stremio_catalog.catalog_options(user),
            "selected_ids": list(stremio_catalog.parse_catalog_config(config)),
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
    user, grant = stremio_catalog.resolve_addon_credential(token)
    if user is None:
        logger.warning("Invalid token on Stremio addon meta request")
        return _stremio_addon_response({"error": "Invalid token"}, status=401)

    media_id = unquote(media_id)
    if (
        media_type not in {"movie", "series"}
        or len(media_id) > STREMIO_MAX_MEDIA_ID_LENGTH
        or not STREMIO_MEDIA_ID_PATTERN.fullmatch(media_id)
    ):
        return _stremio_addon_response({"meta": {}}, status=400)

    if grant is not None:
        stremio_catalog.touch_grant(grant)

    meta = stremio_catalog.project_meta(user, media_type, media_id)
    if meta is None:
        # Empty rather than 404: the item is simply not in this library, and
        # Stremio treats a 404 as the add-on being broken.
        return _stremio_addon_response({"meta": {}})

    return _stremio_addon_response({"meta": meta})


@login_not_required
@csrf_exempt
@require_GET
def stremio_addon_subtitles(request, token, media_type, media_id, config=None):
    """Record a playback-start scrobble from a Stremio subtitles request."""
    from django.core.cache import cache

    user, grant = stremio_catalog.resolve_addon_credential(token)
    if user is None:
        logger.warning("Invalid token on Stremio addon subtitles request")
        return _stremio_addon_response({"error": "Invalid token"}, status=401)
    if grant is not None and not grant.allow_playback_start:
        # This route records a playback start, which is a write. A grant minted
        # without that permission serves catalogs and nothing else.
        logger.info("stremio_subtitles rejected reason=grant_excludes_playback_start")
        return _stremio_addon_response({"subtitles": []})

    media_id = unquote(media_id)
    if (
        media_type not in {"movie", "series"}
        or len(media_id) > STREMIO_MAX_MEDIA_ID_LENGTH
        or not STREMIO_MEDIA_ID_PATTERN.fullmatch(media_id)
        or (media_type == "movie" and ":" in media_id)
    ):
        logger.info(
            "stremio_queue status=limited reason=invalid_media_id user_id=%s "
            "media_type=%s media_id=%s",
            user.id,
            media_type,
            media_id[:STREMIO_MAX_MEDIA_ID_LENGTH],
        )
        return _stremio_addon_response({"subtitles": []})

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


@require_POST
def sync_direction_settings(request):
    """Set which way watched state may travel for one connection.

    The chosen direction is intersected with what the provider's adapter can
    actually do, so picking "Both" on a read-only connection grants the reads
    and grants no writes — rather than recording an approval that would never
    be honoured and reporting it as if it had been.
    """
    from integrations.state import identity, settings_view

    binding = SyncBinding.objects.filter(
        pk=request.POST.get("binding_id"),
        user=request.user,
    ).first()
    if binding is None:
        messages.error(request, "That connection no longer exists.")
        return redirect("integrations")

    direction = request.POST.get("direction", settings_view.DIRECTION_OFF)
    if direction not in settings_view.DIRECTION_LABELS:
        messages.error(request, "Unknown synchronization direction.")
        return redirect("integrations")

    if direction == settings_view.DIRECTION_OFF:
        identity.deactivate_binding(binding)
        messages.success(
            request,
            f"Turned off watched-state sync for {binding.get_client_kind_display()}.",
        )
        return redirect("integrations")

    adapter = outbound.get_adapter(binding)
    supported = set(adapter.CAPABILITIES) if adapter is not None else set()
    capabilities = settings_view.capabilities_for_direction(direction, supported)

    if not capabilities:
        messages.error(
            request,
            (
                f"{binding.get_client_kind_display()} cannot do that yet. "
                "Its adapter reports no matching capability."
            ),
        )
        return redirect("integrations")

    identity.activate_binding(
        binding,
        capabilities=capabilities,
        directions=settings_view.directions_for_choice(direction, capabilities),
    )

    granted = settings_view.capabilities_for_direction(direction, supported)
    requested = settings_view.capabilities_for_direction(
        direction,
        set(settings_view.CAPABILITY_LABELS),
    )
    if len(granted) < len(requested):
        messages.warning(
            request,
            (
                f"Enabled what {binding.get_client_kind_display()} supports. "
                "The rest is listed as unavailable until its adapter is verified."
            ),
        )
    else:
        messages.success(
            request,
            f"Updated watched-state sync for {binding.get_client_kind_display()}.",
        )
    return redirect("integrations")


@require_POST
def sync_kill_switch(request):
    """Stop or resume one connection without discarding its approvals."""
    binding = SyncBinding.objects.filter(
        pk=request.POST.get("binding_id"),
        user=request.user,
    ).first()
    if binding is None:
        messages.error(request, "That connection no longer exists.")
        return redirect("integrations")

    binding.kill_switch = request.POST.get("kill_switch") == "on"
    binding.save(update_fields=["kill_switch", "updated_at"])

    if binding.kill_switch:
        messages.info(
            request,
            f"Paused {binding.get_client_kind_display()}. Your settings are kept.",
        )
    else:
        messages.success(request, f"Resumed {binding.get_client_kind_display()}.")
    return redirect("integrations")


@require_POST
def sync_resolve_conflict(request):
    """Settle one held disagreement with the state the user chose."""
    from integrations.state.apply import resolve_conflict

    conflict = StateConflict.objects.filter(
        pk=request.POST.get("conflict_id"),
        user=request.user,
        status=StateConflictStatus.OPEN.value,
    ).first()
    if conflict is None:
        messages.error(request, "That conflict is no longer open.")
        return redirect("integrations")

    watched = request.POST.get("watched") == "true"
    resolve_conflict(conflict, watched=watched)
    messages.success(
        request,
        f"Resolved. {conflict.item} is now marked "
        f"{'watched' if watched else 'unwatched'}.",
    )
    return redirect("integrations")


def _match_source_for_user(request, item_id):
    """Return a movie/TV source item that this user actually tracks."""
    item = get_object_or_404(
        Item,
        pk=item_id,
        media_type__in=(MediaTypes.MOVIE.value, MediaTypes.TV.value),
    )
    tracked = (
        Movie.objects.filter(user=request.user, item=item).exists()
        if item.media_type == MediaTypes.MOVIE.value
        else TV.objects.filter(user=request.user, item=item).exists()
    )
    if not tracked:
        from django.http import Http404

        raise Http404
    return item


def _match_destination_from_result(result, media_type):
    """Materialize a same-type TMDB search result for preview/apply."""
    media_id = result.get("media_id") or result.get("id")
    title = result.get("title") or result.get("name")
    if not media_id or not title:
        return None
    defaults = {
        "title": title,
        "original_title": result.get("original_title") or result.get("original_name"),
        "localized_title": result.get("localized_title"),
        "image": result.get("image") or result.get("poster_path") or "",
    }
    destination, _created = Item.objects.get_or_create(
        media_id=str(media_id),
        source=Sources.TMDB.value,
        media_type=media_type,
        defaults=defaults,
    )
    return destination


def _match_reference_ids(user, source_item):
    """Return only this user's source references affected by the correction."""
    item_ids = [source_item.pk]
    if source_item.media_type == MediaTypes.TV.value:
        item_ids.extend(
            Item.objects.filter(
                media_id=source_item.media_id,
                source=source_item.source,
                media_type=MediaTypes.EPISODE.value,
            ).values_list("pk", flat=True),
        )
    return list(
        ExternalReference.objects.filter(
            user=user,
        ).filter(
            Q(matched_item_id__in=item_ids) | Q(corrected_item_id__in=item_ids),
        ).values_list("id", flat=True),
    )


@login_required
def match_fix(request, item_id):
    """Search, preview, and apply a same-type match correction."""
    source_item = _match_source_for_user(request, item_id)
    query = request.GET.get("q", "").strip()
    candidates = []
    if query:
        try:
            candidates = services.search(
                source_item.media_type,
                query,
                1,
                source=Sources.TMDB.value,
                user=request.user,
            ).get("results", [])
        except services.ProviderAPIError as error:
            messages.error(request, f"Could not search TMDB: {error}")

    preview = None
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "preview":
            destination = Item.objects.filter(
                pk=request.POST.get("destination_item_id"),
                source=Sources.TMDB.value,
                media_type=source_item.media_type,
            ).first()
            if destination is None:
                messages.error(request, "Choose a valid same-type destination.")
            else:
                try:
                    mapping = json.loads(request.POST.get("mapping_json") or "{}")
                    preview = preview_match_correction(
                        request.user,
                        source_item,
                        destination,
                        episode_mapping=mapping or None,
                    )
                    request.session["match_correction_preview"] = {
                        "source_item_id": source_item.pk,
                        "destination_item_id": destination.pk,
                        "token": preview["token"],
                        "reference_ids": _match_reference_ids(
                            request.user,
                            source_item,
                        ),
                    }
                except (ValueError, json.JSONDecodeError) as error:
                    messages.error(request, str(error))
        elif action == "apply":
            stored = request.session.get("match_correction_preview") or {}
            if stored.get("source_item_id") != source_item.pk:
                messages.error(request, "Refresh the correction preview before applying.")
            else:
                try:
                    mapping = json.loads(request.POST.get("mapping_json") or "{}")
                    decisions = {
                        key.removeprefix("decision_"): value
                        for key, value in request.POST.items()
                        if key.startswith("decision_") and value
                    }
                    destination_item = apply_match_correction(
                        request.user,
                        stored["source_item_id"],
                        stored["destination_item_id"],
                        stored["token"],
                        episode_mapping=mapping or None,
                        decisions=decisions,
                        reference_ids=stored.get("reference_ids", []),
                        note=request.POST.get("note", ""),
                    )
                except (
                    InvalidMatchCorrectionError,
                    MissingEpisodeMappingError,
                    StaleCorrectionPreviewError,
                ) as error:
                    messages.error(request, str(error))
                else:
                    request.session.pop("match_correction_preview", None)
                    messages.success(
                        request,
                        "Match corrected and future imports mapped.",
                    )
                    return redirect(
                        "media_details",
                        source=Sources.TMDB.value,
                        media_type=source_item.media_type,
                        media_id=destination_item.media_id,
                        title=destination_item.title,
                    )

    context = {
        "source_item": source_item,
        "candidates": [
            {
                "result": result,
                "item": _match_destination_from_result(result, source_item.media_type),
            }
            for result in candidates
        ],
        "preview": preview,
        "preview_mapping_json": (
            json.dumps(preview["episode_mapping"], sort_keys=True)
            if preview
            else ""
        ),
        "reference_count": len(_match_reference_ids(request.user, source_item)),
    }
    return render(request, "integrations/match_fix.html", context)


@login_required
@require_POST
def match_reference_status(request, reference_id, status):
    """Ignore or restore one user-scoped external reference."""
    reference = get_object_or_404(
        ExternalReference,
        pk=reference_id,
        user=request.user,
    )
    if status == ExternalReferenceReviewStatus.IGNORED.value:
        reference.review_status = status
        reference.save(update_fields=["review_status", "updated_at"])
        messages.success(request, "Future imports will ignore this source identity.")
    elif status == "remove":
        reference.review_status = ExternalReferenceReviewStatus.RESOLVED.value
        reference.corrected_item = None
        reference.episode_mapping = {}
        reference.decision_note = ""
        reference.save(
            update_fields=[
                "review_status",
                "corrected_item",
                "episode_mapping",
                "decision_note",
                "updated_at",
            ],
        )
        messages.success(request, "The saved correction was removed.")
    else:
        messages.error(request, "Unknown match decision.")
    return redirect("integrations")
