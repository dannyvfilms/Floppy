"""Contains views for importing and exporting media data from various sources."""

import base64
import hashlib
import json
import logging
import re
import secrets
import zoneinfo
from datetime import datetime, timedelta
from http import HTTPStatus

import croniter
import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.db.models import Q
from django.http import (
    HttpResponse,
    HttpResponseNotFound,
    JsonResponse,
    StreamingHttpResponse,
)
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext
from django.views.decorators.http import (
    require_GET,
    require_http_methods,
    require_POST,
)

import users
from app import helpers as app_helpers
from app.log_safety import exception_summary
from app.models import TV, Item, MediaTypes, Movie, Sources, Status
from app.providers import credentials, services
from app.services import metadata_resolution
from integrations import (
    arr_library,
    exports,
    gpodder_api,
    koito_api,
    lastfm_api,
    pending_auth,
    pocketcasts_api,
    psn_api,
    seerr_api,
    tasks,
    xbox_api,
)
from integrations import plex as plex_api
from integrations.cover_proxy_views import (
    audiobookshelf_cover,  # noqa: F401
    plex_cover,  # noqa: F401
)
from integrations.gpodder_api import GPodderAuthError, GPodderClientError
from integrations.imports import anilist, helpers, mdblist, simkl, trakt
from integrations.imports import plex as plex_import
from integrations.imports import psn as psn_import
from integrations.imports.audiobookshelf import (
    AudiobookshelfAuthError,
    AudiobookshelfClient,
)
from integrations.imports.kapowarr import KapowarrClient
from integrations.imports.kavita import KavitaClient
from integrations.imports.komga import KomgaClient
from integrations.imports.koreader import (
    KoreaderAuthError,
    KoreaderClient,
    KoreaderClientError,
)
from integrations.imports.mylar import MylarClient
from integrations.imports.netflix import NetflixResolver
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
from integrations.mal_sync_views import (
    mal_callback,  # noqa: F401
    mal_disconnect,  # noqa: F401
    mal_episode_mapping_revert,  # noqa: F401
    mal_episode_mapping_save,  # noqa: F401
    mal_export_schedule_delete,  # noqa: F401
    mal_export_schedule_save,  # noqa: F401
    mal_full_sync,  # noqa: F401
    mal_full_sync_preview,  # noqa: F401
    mal_full_sync_retry_failed,  # noqa: F401
    mal_full_sync_status,  # noqa: F401
    mal_mapping_episodes,  # noqa: F401
    mal_mapping_ignore,  # noqa: F401
    mal_mapping_search,  # noqa: F401
    mal_oauth,  # noqa: F401
    mal_per_item_sync_toggle,  # noqa: F401
    mal_sync_filters_save,  # noqa: F401
    mal_toggle,  # noqa: F401
)
from integrations.match_corrections import (
    InvalidMatchCorrectionError,
    MissingEpisodeMappingError,
    StaleCorrectionPreviewError,
    apply_match_correction,
    destination_episodes,
    preview_match_correction,
    suggest_mapping,
)
from integrations.models import (
    AudiobookshelfAccount,
    CollectionSourceState,
    ExternalReference,
    ExternalReferenceReviewStatus,
    GPodderAccount,
    JellyfinAccount,
    KapowarrInstance,
    KavitaAccount,
    KoitoAccount,
    KomgaAccount,
    KoreaderAccount,
    KoreaderDocumentLink,
    LastFMAccount,
    MDBListAccount,
    MylarInstance,
    NetflixPendingRow,
    PlaytimeSnapshot,
    PlexAccount,
    PlexWebhookShare,
    PocketCastsAccount,
    PSNAccount,
    RadarrInstance,
    SonarrInstance,
    StateConflict,
    StateConflictStatus,
    StorytellerAccount,
    SyncBinding,
    XboxAccount,
)
from integrations.plex_watchlist import (
    WATCHLIST_SYNC_INTERVAL_MINUTES,
    WATCHLIST_TASK_NAME,
)
from integrations.pocketcasts_api import PocketCastsAuthError
from integrations.source_sync import remove_collection_source_state
from integrations.state import outbound
from integrations.stremio_views import (
    import_stremio,  # noqa: F401
    stremio_addon_catalog,  # noqa: F401
    stremio_addon_configure,  # noqa: F401
    stremio_addon_library,  # noqa: F401
    stremio_addon_manifest,  # noqa: F401
    stremio_addon_meta,  # noqa: F401
    stremio_addon_player,  # noqa: F401
    stremio_addon_subtitles,  # noqa: F401
    stremio_connect,  # noqa: F401
    stremio_disconnect,  # noqa: F401
)
from integrations.upload_staging import (
    build_staged_zip,
    discard_staged_upload,
    enqueue_staged_task,
    stage_uploaded_file,
    staged_payload_is_zip,
    staging_failure_message,
)
from integrations.view_helpers import (
    _consume_oauth_state,
    _import_queue_failure_message,
    _integration_redirect,
    _periodic_task_filter_for_user,
    _plex_watchlist_task_filter,
    _queue_task_or_message,
    _queue_task_quietly,
    _run_with_lock_retry,
)
from integrations.webhook_views import (
    emby_webhook,  # noqa: F401
    jellyfin_webhook,  # noqa: F401
    jellyseerr_webhook,  # noqa: F401
    kodi_webhook,  # noqa: F401
    plex_webhook,  # noqa: F401
    seerr_global_webhook,  # noqa: F401
)

logger = logging.getLogger(__name__)
ARR_SYNC_INTERVAL_HOURS = 2
RADARR_RECURRING_TASK_NAME = "Import from Radarr (Recurring)"
JELLYFIN_PLAYBACK_REPORTING_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
SONARR_RECURRING_TASK_NAME = "Import from Sonarr (Recurring)"
MYLAR_RECURRING_TASK_NAME = "Import from Mylar3 (Recurring)"
KAPOWARR_RECURRING_TASK_NAME = "Import from Kapowarr (Recurring)"
GPODDER_RECURRING_TASK_NAME = "Import from GPodder (Recurring)"
TRAKT_DEVICE_SESSION_KEY = "trakt_device_auth"


def _stage_upload_or_message(request, upload, label="upload"):
    """Stage an upload and report storage failures without returning a 500."""
    try:
        return str(stage_uploaded_file(upload))
    except OSError as error:
        logger.exception("Could not stage %s for background import", label)
        messages.error(request, staging_failure_message(error))
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
    except Exception as error:
        logger.exception("Could not queue background import task")
        messages.error(request, _import_queue_failure_message(error))
        return False


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


def _periodic_task_filter_for_instance(instance_id):
    """Match a Radarr/Sonarr instance's periodic task regardless of JSON spacing/quotes."""
    return (
        Q(kwargs__contains=f"'instance_id': {instance_id},")
        | Q(kwargs__contains=f"'instance_id': {instance_id}" + "}")
        | Q(kwargs__contains=f'"instance_id": {instance_id},')
        | Q(kwargs__contains=f'"instance_id": {instance_id}' + "}")
    )


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


def _jellyfin_account_task_filter(user_id, account_id):
    """Return a ``Q`` matching one Jellyfin connection's periodic task exactly."""
    return Q(**helpers.periodic_task_user_kwargs(user_id)) & Q(
        kwargs__regex=rf"[\"']account_id[\"']: {int(account_id)}[,}}]",
    )


def _ensure_jellyfin_schedule(user, account, task_name, interval_minutes):
    """Create or enable one connection's recurring Jellyfin task.

    Each connection owns its schedule, so connecting, editing or disconnecting
    one server never touches another's. A user-wide schedule left over from
    before multiple connections would fan out to every server, so it goes.
    """
    from django_celery_beat.models import IntervalSchedule, PeriodicTask

    PeriodicTask.objects.filter(
        Q(**helpers.periodic_task_user_kwargs(user.id)),
        task=task_name,
    ).exclude(kwargs__contains="account_id").delete()

    next_interval_start = timezone.now() + timedelta(minutes=interval_minutes)
    interval, _ = IntervalSchedule.objects.get_or_create(
        every=interval_minutes,
        period=IntervalSchedule.MINUTES,
    )
    desired_name = (
        f"{task_name} for {account.display_name} of {user.username} "
        f"#{account.id} (every {interval_minutes} minutes)"
    )
    desired_kwargs = json.dumps({"user_id": user.id, "account_id": account.id})
    existing_task = PeriodicTask.objects.filter(
        _jellyfin_account_task_filter(user.id, account.id),
        task=task_name,
    ).first()
    if existing_task:
        was_enabled = existing_task.enabled
        updated_fields = []
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
        name=desired_name,
        task=task_name,
        interval=interval,
        kwargs=desired_kwargs,
        start_time=next_interval_start,
        enabled=True,
    )


def _disable_jellyfin_schedule(user, account, task_name):
    """Delete one connection's recurring Jellyfin task."""
    from django_celery_beat.models import PeriodicTask

    return PeriodicTask.objects.filter(
        _jellyfin_account_task_filter(user.id, account.id),
        task=task_name,
    ).delete()


def _ensure_jellyfin_push_schedule(user, jellyfin_account):
    """Create or enable one connection's watched-state push schedule."""
    return _ensure_jellyfin_schedule(
        user,
        jellyfin_account,
        JELLYFIN_PUSH_TASK_NAME,
        JELLYFIN_PUSH_INTERVAL_MINUTES,
    )


def _disable_jellyfin_push_schedule(user, jellyfin_account):
    """Delete one connection's push periodic task."""
    return _disable_jellyfin_schedule(user, jellyfin_account, JELLYFIN_PUSH_TASK_NAME)


def _ensure_jellyfin_pull_schedule(user, jellyfin_account):
    """Create or enable one connection's history pull schedule."""
    return _ensure_jellyfin_schedule(
        user,
        jellyfin_account,
        tasks.JELLYFIN_PULL_TASK_NAME,
        tasks.JELLYFIN_PULL_INTERVAL_MINUTES,
    )


def _disable_jellyfin_pull_schedule(user, jellyfin_account):
    """Delete one connection's pull periodic task."""
    return _disable_jellyfin_schedule(
        user,
        jellyfin_account,
        tasks.JELLYFIN_PULL_TASK_NAME,
    )


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
    client_id = credentials.get("trakt", "client_id")
    query = (
        f"client_id={client_id}&redirect_uri={redirect_uri}"
        f"&response_type=code&state={state_token}"
    )
    if not trakt.default_client_secret():
        # An app without a client secret authorizes with PKCE instead.
        state["code_verifier"], code_challenge = trakt.new_pkce_pair()
        query += f"&code_challenge={code_challenge}&code_challenge_method=S256"
    pending_auth.stash_state(request, state_token, state)
    return redirect(f"{url}?{query}")


def _finish_trakt_connection(request, oauth_result, state_data):
    """Encrypt the refresh token, then queue or schedule the Trakt import."""
    enc_token = helpers.encrypt(oauth_result["refresh_token"])

    frequency = state_data["frequency"]
    mode = state_data["mode"]
    import_time = state_data["time"]

    if frequency == "once":
        if _queue_task_or_message(request,
            tasks.import_trakt,
            token=enc_token,
            user_id=request.user.id,
            mode=mode,
            username=oauth_result["username"],
            redirect_uri=oauth_result.get("redirect_uri"),
        ) is False:
            return
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
            extra_kwargs={"redirect_uri": oauth_result.get("redirect_uri")},
            replace_existing=True,
        )


def _start_trakt_device_flow(request):
    """Mint a Trakt device code and send the user to the code screen."""
    try:
        device = trakt.request_device_code()
    except helpers.MediaImportError as error:
        messages.error(request, str(error))
        return _integration_redirect(request)

    pending_auth.put(TRAKT_DEVICE_SESSION_KEY, request.user.pk, {
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
    })
    return redirect("trakt_device_verify")


def _trakt_device_state(request):
    """Return the pending device authorization, or None if gone or expired."""
    state = pending_auth.get(TRAKT_DEVICE_SESSION_KEY, request.user.pk)
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
        pending_auth.clear(TRAKT_DEVICE_SESSION_KEY, request.user.pk)
        messages.error(request, "The Trakt authorization code expired. Start again.")
        return _integration_redirect(request)

    poll_url = reverse("trakt_device_poll")
    cancel_url = reverse("import_data")
    verification_url = state["verification_url"]
    user_code = state["user_code"]
    props = {
        "code": user_code,
        "openUrl": f"{verification_url.rstrip('/')}/{user_code}",
        "pollUrl": poll_url,
        "cancelUrl": cancel_url,
        "interval": state["interval"],
        "expiresAt": state["expires_at"],
        "title": gettext("Connect Trakt"),
        "description": gettext(
            "This instance is not served over HTTPS, so Trakt will not accept "
            "a browser redirect. Enter this code on Trakt instead."
        ),
        "labels": {
            "copy": gettext("Copy code"),
            "copied": gettext("Copied!"),
            "open": gettext("Open %(url)s") % {"url": verification_url},
            "waiting": gettext("Waiting for you to authorize Floppy…"),
            "cancel": gettext("Cancel"),
            "expired": gettext(
                "The Trakt authorization code expired. Start again."
            ),
            "retry": gettext("Start again"),
        },
    }
    return render(
        request,
        "integrations/trakt_device_code.html",
        {
            "user_code": user_code,
            "verification_url": verification_url,
            "interval": state["interval"],
            "poll_url": poll_url,
            "cancel_url": cancel_url,
            "device_connect_props": props,
        },
    )


def _htmx_redirect(location):
    """Tell HTMX to navigate away without swapping anything in."""
    return HttpResponse(status=HTTPStatus.NO_CONTENT, headers={"HX-Redirect": location})


def poll_trakt_device(request):
    """Poll Trakt once; return (status, message, state) for web and native callers.

    Status is pending, connected, expired or error. A finished state is cleared.
    """
    state = _trakt_device_state(request)
    if state is None:
        pending_auth.clear(TRAKT_DEVICE_SESSION_KEY, request.user.pk)
        return "expired", "The Trakt authorization code expired. Start again.", None

    try:
        result = trakt.poll_device_token(state["device_code"])
    except helpers.MediaImportError as error:
        pending_auth.clear(TRAKT_DEVICE_SESSION_KEY, request.user.pk)
        return "error", error.message, state

    if result is None:
        return "pending", "", state

    pending_auth.clear(TRAKT_DEVICE_SESSION_KEY, request.user.pk)
    _finish_trakt_connection(request, result, state)
    return "connected", "", state


@require_GET
def trakt_device_poll(request):
    """Poll Trakt once for the pending device authorization."""
    status, message, state = poll_trakt_device(request)
    if status in ("expired", "error"):
        messages.error(request, message)
        return _htmx_redirect(reverse("import_data"))
    if status == "pending":
        return HttpResponse(status=HTTPStatus.NO_CONTENT)
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
    oauth_callback = trakt.handle_oauth_callback(
        request,
        redirect_uri=redirect_uri,
        code_verifier=state_data.get("code_verifier"),
    )
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
        if _queue_task_or_message(request,
            tasks.import_trakt,
            user_id=request.user.id,
            mode=mode,
            username=username,
        ) is False:
            return _integration_redirect(request, connected_slug="trakt")
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
        if _queue_task_or_message(request,
            tasks.import_mdblist, user_id=request.user.id, mode=mode
        ) is False:
            return _integration_redirect(request, connected_slug="mdblist")
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

    pending_auth.stash_state(request, state_token, {
        "plex_pin_id": pin["id"],
        "plex_pin_code": pin["code"],
        "return_to": request.POST.get("next"),
    })

    auth_url = plex_api.build_auth_url(
        pin["code"], f"{redirect_uri}?state={state_token}"
    )
    return redirect(auth_url)


@require_GET
def plex_callback(request):
    """Handle Plex auth callback and persist the token."""
    state_token = request.GET.get("state")
    state_data = pending_auth.pop_state(request, state_token)

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
        _queue_task_or_message(request,
            tasks.import_plex, user_id=request.user.id, mode="new", library=["all"]
        )

    return _integration_redirect(request, connected_slug="plex", next_url=return_to)


@require_POST
def plex_disconnect(request):
    """Remove stored Plex credentials."""

    def _disconnect():
        _disable_plex_watchlist_schedule(request.user)
        account = PlexAccount.objects.filter(user=request.user).first()
        if account:
            plex_import.set_mark_watched_sync(account, enabled=False)
        PlexWebhookShare.objects.filter(owner=request.user).delete()
        PlexAccount.objects.filter(user=request.user).delete()

    _run_with_lock_retry("disconnect Plex", _disconnect)
    messages.info(request, "Disconnected Plex.")
    return redirect(
        app_helpers.safe_return_url(
            request,
            request.POST.get("next"),
            reverse("provider_detail", args=["plex"]) + "?tab=connection",
        ),
    )


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
        if _queue_task_or_message(request,
            tasks.sync_plex_watchlist,
            user_id=request.user.id,
            mode="watchlist",
        ) is not False:
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

        if _queue_task_or_message(request,
            tasks.update_collection_metadata_from_plex,
            library=library,
            user_id=request.user.id,
        ) is not False:
            messages.info(
                request,
                "The task to update collection metadata from Plex has been queued.",
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

    if _queue_task_or_message(request,
        tasks.import_plex,
        library=library,
        user_id=request.user.id,
        mode=mode,
    ) is not False:
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
    if not credentials.is_configured("simkl", request.user):
        messages.error(
            request,
            "SIMKL needs your own Client ID and Client secret. "
            "Add them in Settings > Metadata, then connect again.",
        )
        return _integration_redirect(request)

    redirect_uri = app_helpers.build_absolute_app_url(
        request,
        reverse("import_simkl_private"),
    )
    state = {
        "mode": request.POST["mode"],
        "frequency": request.POST["frequency"],
        "time": request.POST["time"],
        "redirect_uri": redirect_uri,
        "return_to": request.POST.get("next"),
    }
    state_token = secrets.token_urlsafe(32)
    query = (
        f"client_id={credentials.get("simkl", "client_id")}&redirect_uri={redirect_uri}"
        f"&response_type=code&state={state_token}"
    )

    if request.POST.get("auth_version") == "v1":
        # SIMKL apps made before 2026-09-18; AUTH V1 retires around April 2027
        url = f"https://simkl.com/oauth/authorize?{query}"
    else:
        # AUTH V2 requires PKCE (S256)
        code_verifier = secrets.token_urlsafe(64)
        state["code_verifier"] = code_verifier
        code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        url = (
            f"https://simkl.com/oauth2/authorize?{query}"
            f"&code_challenge={code_challenge}&code_challenge_method=S256"
        )

    pending_auth.stash_state(request, state_token, state)
    return redirect(url)


@require_GET
def import_simkl_private(request):
    """View for getting the SIMKL OAuth2 token."""
    state_data = _consume_oauth_state(request, "SIMKL")
    if state_data is None:
        return _integration_redirect(request)

    redirect_uri = state_data.get("redirect_uri")
    return_to = state_data.get("return_to")

    if state_data.get("code_verifier") and request.GET.get("iss") != "https://simkl.com":
        # AUTH V2 callbacks must come from SIMKL itself, not another provider.
        logger.warning("SIMKL OAuth callback carried an unexpected issuer")
        messages.error(request, "Invalid or expired SIMKL authorization request.")
        return _integration_redirect(request, next_url=return_to)

    if request.GET.get("error"):
        # AUTH V2 reports a declined consent through the callback, unlike V1.
        messages.error(request, "SIMKL authorization was cancelled or denied.")
        return _integration_redirect(request, next_url=return_to)

    if not request.GET.get("code"):
        messages.error(request, "SIMKL authorization did not return a code.")
        return _integration_redirect(request, next_url=return_to)

    try:
        oauth_callback = simkl.get_token(
            request,
            redirect_uri=redirect_uri,
            code_verifier=state_data.get("code_verifier"),
        )
    except helpers.MediaImportError as error:
        messages.error(request, str(error))
        return _integration_redirect(request, next_url=return_to)
    enc_token = helpers.encrypt(oauth_callback["access_token"])

    frequency = state_data["frequency"]
    mode = state_data["mode"]
    import_time = state_data["time"]

    if frequency == "once":
        if _queue_task_or_message(request,
            tasks.import_simkl,
            token=enc_token,
            user_id=request.user.id,
            mode=mode,
        ) is False:
            return _integration_redirect(request, connected_slug="simkl", next_url=return_to)
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
            # AUTH V2 access tokens expire after 7 days; V1 has no refresh token
            extra_kwargs=(
                {"refresh_token": helpers.encrypt(oauth_callback["refresh_token"])}
                if oauth_callback["refresh_token"]
                else None
            ),
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
        if _queue_task_or_message(request,
            tasks.import_mal, username=username, user_id=request.user.id, mode=mode
        ) is False:
            return _integration_redirect(request, connected_slug="myanimelist")
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
def import_mangabaka(request):
    """View for importing a manga library from MangaBaka.

    MangaBaka exposes no public per-user API, so the Personal Access Token is
    the only credential. That also means there is no username to key a
    recurring schedule on, which is why this import runs once.
    """
    token = (request.POST.get("token") or "").strip()
    if not token:
        messages.error(request, "MangaBaka API token is required.")
        return _integration_redirect(request, connected_slug="mangabaka")

    if request.POST.get("frequency", "once") != "once":
        messages.error(request, "MangaBaka imports run once only.")
        return _integration_redirect(request, connected_slug="mangabaka")

    tasks.import_mangabaka.delay(
        token=helpers.encrypt(token),
        user_id=request.user.id,
        mode=request.POST["mode"],
    )
    messages.info(
        request,
        "The task to import media from MangaBaka has been queued.",
    )
    return _integration_redirect(request, connected_slug="mangabaka")


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
    pending_auth.stash_state(request, state_token, state)

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
        if _queue_task_or_message(request,
            tasks.import_anilist,
            user_id=request.user.id,
            mode=mode,
            username=username,
            token=enc_token,
        ) is False:
            return _integration_redirect(request, connected_slug="anilist", next_url=return_to)
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
        return redirect(app_helpers.safe_return_url(request, request.POST.get("next"), reverse("import_data")))

    mode = request.POST["mode"]
    frequency = request.POST["frequency"]
    import_time = request.POST["time"]

    if frequency == "once":
        if _queue_task_or_message(request,
            tasks.import_anilist,
            user_id=request.user.id,
            mode=mode,
            username=username,
        ) is False:
            return redirect(app_helpers.safe_return_url(request, request.POST.get("next"), reverse("import_data")))
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
    return redirect(app_helpers.safe_return_url(request, request.POST.get("next"), reverse("import_data")))


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
        if _queue_task_or_message(request,
            tasks.import_kitsu, username=kitsu_id, user_id=request.user.id, mode=mode
        ) is False:
            return _integration_redirect(request)
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

    wishlist_status = (request.POST.get("clz_wishlist_status") or "").strip() or None
    if wishlist_status and wishlist_status not in Status.values:
        discard_staged_upload(staged_file)
        messages.error(request, "Unknown status for the CLZ wishlist items.")
        return _integration_redirect(request)

    if _queue_staged_task_or_message(
        request,
        tasks.import_clz,
        user_id=request.user.id,
        file=staged_file,
        mode=request.POST.get("mode", "new"),
        media_type=media_type,
        wishlist_status=wishlist_status,
        wishlist_tag=(request.POST.get("clz_wishlist_tag") or "").strip() or None,
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

    if mode not in helpers.TRAKT_EXPORT_MODES:
        for path in staged_files:
            discard_staged_upload(path)
        messages.error(request, helpers.TRAKT_EXPORT_UNSUPPORTED_MODE_MESSAGE)
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


@require_POST
def import_wetrakr(request):
    """View for importing a WeTrakr data export: the .zip or its loose .csv files.

    Loose .csv uploads are repackaged into a staged zip so the Celery task
    always receives a single path.
    """
    uploads = request.FILES.getlist("wetrakr_export")
    if not uploads:
        messages.error(request, "A WeTrakr export file is required.")
        return _integration_redirect(request)

    staged_files = _stage_uploads_or_message(request, uploads, "WeTrakr export")
    if staged_files is None:
        return _integration_redirect(request)

    if len(staged_files) == 1 and staged_payload_is_zip(staged_files[0]):
        archive_path = staged_files[0]
    else:
        payloads = [
            (upload.name, path)
            for upload, path in zip(uploads, staged_files, strict=True)
        ]
        try:
            archive_path = str(build_staged_zip(payloads))
        except OSError:
            logger.exception("Could not build staged WeTrakr export archive")
            messages.error(
                request,
                "The WeTrakr export could not be prepared. Check available disk space and try again.",
            )
            return _integration_redirect(request)
        finally:
            for path in staged_files:
                discard_staged_upload(path)

    if _queue_staged_task_or_message(
        request,
        tasks.import_wetrakr_export,
        user_id=request.user.id,
        file=archive_path,
        mode=request.POST["mode"],
        staged_paths=(archive_path,),
    ) is False:
        return _integration_redirect(request, connected_slug="wetrakr")
    messages.info(
        request,
        "The task to import your WeTrakr data export has been queued.",
    )
    return _integration_redirect(request, connected_slug="wetrakr")


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
def import_netflix(request):
    """View for importing a Netflix viewing-history CSV."""
    file = request.FILES.get("netflix_csv")

    if not file:
        messages.error(request, "A Netflix viewing history CSV file is required.")
        return _integration_redirect(request)

    staged_file = _stage_upload_or_message(request, file, "Netflix CSV")
    if staged_file is None:
        return _integration_redirect(request)

    mode = request.POST["mode"]
    if _queue_staged_task_or_message(
        request,
        tasks.import_netflix,
        user_id=request.user.id,
        file=staged_file,
        mode=mode,
        staged_paths=(staged_file,),
    ) is False:
        return _integration_redirect(request, connected_slug="netflix")
    messages.info(
        request,
        "The task to import your Netflix viewing history has been queued.",
    )
    return _integration_redirect(request, connected_slug="netflix")


def netflix_pending(request):
    """List unresolved Netflix viewing-history rows, with an inline search.

    The page shell renders server-side for the no-JavaScript fallback; the
    interactive review is a React island fed by ``review_props``.  The
    fallback and the island share the same search: ``?q=<title>&type=<type>``
    re-renders that row's results server-side, and adding ``format=json``
    returns the same results as JSON for the island.
    """
    rows = (
        NetflixPendingRow.objects.filter(user=request.user)
        .select_related("resolved_item")
        .order_by("-created_at")
    )
    show_all = request.GET.get("show") == "all"
    if not show_all:
        rows = rows.filter(status=NetflixPendingRow.Status.PENDING.value)

    query = (request.GET.get("q") or "").strip()
    media_type = request.GET.get("type") or MediaTypes.MOVIE.value
    if media_type not in (MediaTypes.MOVIE.value, MediaTypes.TV.value):
        media_type = MediaTypes.MOVIE.value

    if request.GET.get("format") == "json":
        if not query:
            return JsonResponse({"results": []})
        resolver = NetflixResolver(request.user)
        try:
            results = resolver.search_results(query, media_type)
        except services.ProviderAPIError:
            results = []
        return JsonResponse(
            {
                "query": query,
                "mediaType": media_type,
                "results": [
                    {
                        "media_id": result["media_id"],
                        "title": result["title"],
                        "year": result.get("year"),
                    }
                    for result in results
                ],
            }
        )

    search = None
    search_row_id = request.GET.get("search_row")
    if search_row_id and query:
        row = get_object_or_404(
            NetflixPendingRow,
            pk=search_row_id,
            user=request.user,
            status=NetflixPendingRow.Status.PENDING.value,
        )
        if not request.GET.get("type"):
            media_type = row.media_type
        resolver = NetflixResolver(request.user)
        try:
            results = resolver.search_results(query, media_type)
        except services.ProviderAPIError:
            results = []
        search = {
            "row": row,
            "query": query,
            "media_type": media_type,
            "results": results,
        }

    review_props = None
    if rows:
        review_props = {
            "csrf": get_token(request),
            "model": {
                "showAll": show_all,
                "actions": {"searchUrl": reverse("netflix_pending")},
                "rows": [
                    {
                        "id": row.id,
                        "title": row.title,
                        "watchedAt": (
                            row.watched_at.isoformat() if row.watched_at else None
                        ),
                        "mediaType": row.media_type,
                        "seasonNumber": row.season_number,
                        "episodeNumber": row.episode_number,
                        "status": row.status,
                        "resolvedTitle": (
                            row.resolved_item.title if row.resolved_item_id else None
                        ),
                        "resolvedAt": (
                            row.resolved_at.date().isoformat()
                            if row.resolved_at
                            else None
                        ),
                        "resolveUrl": reverse(
                            "netflix_pending_resolve", args=[row.id]
                        ),
                        "dismissUrl": reverse(
                            "netflix_pending_dismiss", args=[row.id]
                        ),
                    }
                    for row in rows
                ],
            },
            "labels": {
                "search": gettext("Search"),
                "record": gettext("Record play"),
                "dismiss": gettext("Dismiss row"),
                "season": gettext("Season"),
                "episode": gettext("Episode"),
                "movie": gettext("Movie"),
                "tv": gettext("TV show"),
                "titleToSearch": gettext("Title to search"),
                "mediaType": gettext("Media type"),
                "searchHint": gettext("Search above, then choose the right title."),
                "noResults": gettext(
                    "No results for that title and type. Try the other type or a shorter title."
                ),
                "searching": gettext("Searching"),
                "searchFailed": gettext("Search failed. Try again."),
                "resolved": gettext("Recorded as “%(title)s”."),
                "resolvedShort": gettext("Recorded."),
                "dismissed": gettext("Dismissed, no play recorded."),
                "empty": gettext(
                    "Nothing to review: every imported row was matched automatically."
                ),
            },
        }

    return render(
        request,
        "integrations/netflix_pending.html",
        {"rows": rows, "show_all": show_all, "search": search,
         "review_props": review_props},
    )


@require_POST
def netflix_pending_resolve(request, row_id):
    """Record the play for one reviewed Netflix row."""
    row = get_object_or_404(
        NetflixPendingRow,
        pk=row_id,
        user=request.user,
        status=NetflixPendingRow.Status.PENDING.value,
    )
    if row.watched_at is None:
        messages.error(
            request,
            "This row has no readable date, so it can't be recorded.",
        )
        return redirect(reverse("netflix_pending"))
    watched_at = datetime(
        row.watched_at.year,
        row.watched_at.month,
        row.watched_at.day,
        tzinfo=timezone.get_current_timezone(),
    )
    media_type = request.POST.get("media_type") or row.media_type
    if media_type not in (MediaTypes.MOVIE.value, MediaTypes.TV.value):
        media_type = row.media_type
    tmdb_id = (request.POST.get("tmdb_id") or "").strip()
    if not tmdb_id:
        messages.error(request, "Choose a title to record.")
        return redirect(reverse("netflix_pending"))
    season_number = None
    episode_number = None
    if media_type == MediaTypes.TV.value:
        for field in ("season_number", "episode_number"):
            try:
                value = int(request.POST.get(field) or 0)
            except ValueError:
                value = 0
            if field == "season_number":
                season_number = value or None
            else:
                episode_number = value or None

    resolver = NetflixResolver(request.user)
    item, error = resolver.record_play(
        row.title,
        watched_at,
        media_type,
        tmdb_id,
        season_number=season_number,
        episode_number=episode_number,
    )
    if error:
        messages.error(request, error)
        return redirect(reverse("netflix_pending"))
    row.status = NetflixPendingRow.Status.RESOLVED.value
    row.media_type = media_type
    row.season_number = season_number
    row.episode_number = episode_number
    row.resolved_item = item
    row.resolved_at = timezone.now()
    row.save()
    messages.success(request, f"{item.title} recorded.")
    return redirect(reverse("netflix_pending"))


@require_POST
def netflix_pending_dismiss(request, row_id):
    """Dismiss one unresolved Netflix row."""
    row = get_object_or_404(
        NetflixPendingRow,
        pk=row_id,
        user=request.user,
        status=NetflixPendingRow.Status.PENDING.value,
    )
    row.status = NetflixPendingRow.Status.DISMISSED.value
    row.resolved_at = timezone.now()
    row.save()
    messages.success(request, "Row dismissed.")
    return redirect(reverse("netflix_pending"))


@require_POST
def import_playnite(request):
    """View for importing a Playnite library CSV backup."""
    file = request.FILES.get("playnite_csv")

    if not file:
        messages.error(request, "A Playnite CSV file is required.")
        return _integration_redirect(request)

    staged_file = _stage_upload_or_message(request, file, "Playnite CSV")
    if staged_file is None:
        return _integration_redirect(request)

    if _queue_staged_task_or_message(
        request,
        tasks.import_playnite,
        user_id=request.user.id,
        file=staged_file,
        mode=request.POST["mode"],
        staged_paths=(staged_file,),
    ) is False:
        return _integration_redirect(request, connected_slug="playnite")
    messages.info(request, "The Playnite library import has been queued.")
    return _integration_redirect(request, connected_slug="playnite")


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
        if _queue_task_or_message(request,
            tasks.import_steam, username=steam_id, user_id=request.user.id, mode=mode
        ) is False:
            return _integration_redirect(request, connected_slug="steam")
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
    if _queue_task_or_message(request,
        tasks.import_radarr, user_id=request.user.id, mode="new", instance_id=instance.id
    ) is not False:
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
        instance.delete()

    # Queue the row cleanup first: it is too slow for the request (#1911).
    if _queue_task_or_message(
        request,
        tasks.remove_collection_source_states,
        request.user.id,
        "radarr",
        instance.id,
    ) is False:
        return redirect("import_data")
    _run_with_lock_retry("disconnect Radarr", _disconnect)
    messages.info(request, "Disconnected Radarr.")
    return redirect("import_data")


@require_POST
def import_radarr(request):
    """Queue Radarr import and ensure recurring schedule exists."""
    instance = get_object_or_404(
        RadarrInstance, pk=request.POST.get("instance_id"), user=request.user
    )

    queued = _queue_task_or_message(request,
        tasks.import_radarr, user_id=request.user.id, mode="new", instance_id=instance.id
    )
    _ensure_arr_schedule(instance, RADARR_RECURRING_TASK_NAME, "Radarr")
    if queued is not False:
        messages.info(request, "Radarr import queued.")
    return redirect("import_data")


@require_POST
def mylar_connect(request):
    """Connect a new Mylar3 instance using base URL + API key."""
    base_url = request.POST.get("base_url", "").strip()
    api_key = request.POST.get("api_key", "").strip()
    name = request.POST.get("name", "").strip()
    if not base_url or not api_key:
        messages.error(request, "Mylar3 base URL and API key are required.")
        return _integration_redirect(request)

    try:
        MylarClient(base_url, api_key).healthcheck()
    except helpers.MediaImportError as exc:
        messages.error(request, f"Failed to connect to Mylar3: {exc}")
        return _integration_redirect(request)

    try:
        instance = _run_with_lock_retry(
            "create Mylar3 instance",
            lambda: MylarInstance.objects.create(
                user=request.user,
                name=name,
                base_url=base_url,
                api_key=helpers.encrypt(api_key),
            ),
        )
    except IntegrityError:
        messages.error(
            request, "You already have a Mylar3 instance connected at this URL."
        )
        return _integration_redirect(request)

    _ensure_arr_schedule(instance, MYLAR_RECURRING_TASK_NAME, "Mylar3")
    if _queue_task_or_message(request,
        tasks.import_mylar, user_id=request.user.id, mode="new", instance_id=instance.id
    ) is not False:
        messages.success(
            request,
            "Connected Mylar3. Initial import queued and recurring sync enabled.",
        )
    return _integration_redirect(request, connected_slug="mylar")


@require_POST
def mylar_disconnect(request):
    """Disconnect one Mylar3 instance."""
    from django_celery_beat.models import PeriodicTask

    instance = get_object_or_404(
        MylarInstance, pk=request.POST.get("instance_id"), user=request.user
    )

    def _disconnect():
        PeriodicTask.objects.filter(
            _periodic_task_filter_for_instance(instance.id),
            task=MYLAR_RECURRING_TASK_NAME,
        ).delete()
        # Through the reconciling helper, so copies only Mylar3 created go too.
        instance.delete()

    # Queue the row cleanup first: it is too slow for the request (#1911).
    if _queue_task_or_message(
        request,
        tasks.remove_collection_source_states,
        request.user.id,
        "mylar",
        instance.id,
    ) is False:
        return redirect("import_data")
    _run_with_lock_retry("disconnect Mylar3", _disconnect)
    messages.info(request, "Disconnected Mylar3.")
    return redirect("import_data")


@require_POST
def import_mylar(request):
    """Queue Mylar3 import and ensure recurring schedule exists."""
    instance = get_object_or_404(
        MylarInstance, pk=request.POST.get("instance_id"), user=request.user
    )

    queued = _queue_task_or_message(request,
        tasks.import_mylar, user_id=request.user.id, mode="new", instance_id=instance.id
    )
    _ensure_arr_schedule(instance, MYLAR_RECURRING_TASK_NAME, "Mylar3")
    if queued is not False:
        messages.info(request, "Mylar3 import queued.")
    return redirect("import_data")


@require_POST
def kapowarr_connect(request):
    """Connect a new Kapowarr instance using base URL + API key."""
    base_url = request.POST.get("base_url", "").strip()
    api_key = request.POST.get("api_key", "").strip()
    name = request.POST.get("name", "").strip()
    if not base_url or not api_key:
        messages.error(request, "Kapowarr base URL and API key are required.")
        return _integration_redirect(request)

    try:
        KapowarrClient(base_url, api_key).healthcheck()
    except helpers.MediaImportError as exc:
        messages.error(request, f"Failed to connect to Kapowarr: {exc}")
        return _integration_redirect(request)

    try:
        instance = _run_with_lock_retry(
            "create Kapowarr instance",
            lambda: KapowarrInstance.objects.create(
                user=request.user,
                name=name,
                base_url=base_url,
                api_key=helpers.encrypt(api_key),
            ),
        )
    except IntegrityError:
        messages.error(
            request, "You already have a Kapowarr instance connected at this URL."
        )
        return _integration_redirect(request)

    _ensure_arr_schedule(instance, KAPOWARR_RECURRING_TASK_NAME, "Kapowarr")
    if _queue_task_or_message(request,
        tasks.import_kapowarr, user_id=request.user.id, mode="new", instance_id=instance.id
    ) is not False:
        messages.success(
            request,
            "Connected Kapowarr. Initial import queued and recurring sync enabled.",
        )
    return _integration_redirect(request, connected_slug="kapowarr")


@require_POST
def kapowarr_disconnect(request):
    """Disconnect one Kapowarr instance."""
    from django_celery_beat.models import PeriodicTask

    instance = get_object_or_404(
        KapowarrInstance, pk=request.POST.get("instance_id"), user=request.user
    )

    def _disconnect():
        PeriodicTask.objects.filter(
            _periodic_task_filter_for_instance(instance.id),
            task=KAPOWARR_RECURRING_TASK_NAME,
        ).delete()
        # Through the reconciling helper, so copies only Kapowarr created go too.
        states = CollectionSourceState.objects.filter(
            user=request.user, source="kapowarr", source_instance_id=instance.id
        ).select_related("item")
        for state in states:
            remove_collection_source_state(
                user=request.user,
                item=state.item,
                source="kapowarr",
                source_instance_id=instance.id,
            )
        instance.delete()

    _run_with_lock_retry("disconnect Kapowarr", _disconnect)
    messages.info(request, "Disconnected Kapowarr.")
    return redirect("import_data")


@require_POST
def import_kapowarr(request):
    """Queue Kapowarr import and ensure recurring schedule exists."""
    instance = get_object_or_404(
        KapowarrInstance, pk=request.POST.get("instance_id"), user=request.user
    )

    queued = _queue_task_or_message(request,
        tasks.import_kapowarr, user_id=request.user.id, mode="new", instance_id=instance.id
    )
    _ensure_arr_schedule(instance, KAPOWARR_RECURRING_TASK_NAME, "Kapowarr")
    if queued is not False:
        messages.info(request, "Kapowarr import queued.")
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
    if _queue_task_or_message(request,
        tasks.import_sonarr, user_id=request.user.id, mode="new", instance_id=instance.id
    ) is not False:
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
        instance.delete()

    # Queue the row cleanup first: it is too slow for the request (#1911).
    if _queue_task_or_message(
        request,
        tasks.remove_collection_source_states,
        request.user.id,
        "sonarr",
        instance.id,
    ) is False:
        return redirect("import_data")
    _run_with_lock_retry("disconnect Sonarr", _disconnect)
    messages.info(request, "Disconnected Sonarr.")
    return redirect("import_data")


@require_POST
def import_sonarr(request):
    """Queue Sonarr import and ensure recurring schedule exists."""
    instance = get_object_or_404(
        SonarrInstance, pk=request.POST.get("instance_id"), user=request.user
    )

    queued = _queue_task_or_message(request,
        tasks.import_sonarr, user_id=request.user.id, mode="new", instance_id=instance.id
    )
    _ensure_arr_schedule(instance, SONARR_RECURRING_TASK_NAME, "Sonarr")
    if queued is not False:
        messages.info(request, "Sonarr import queued.")
    return redirect("import_data")


def _jellyfin_posted_account_id(request):
    """Return the posted connection id; ``instance_id`` is what the shared UI sends."""
    return (
        request.POST.get("account_id") or request.POST.get("instance_id") or ""
    ).strip()


def _jellyfin_account_from_post(request):
    """Return the connection a POST names with ``account_id``, or None.

    Always scoped to the requesting user, so a forged id reaches no one else's
    server. A user with exactly one connection may omit the id, which keeps
    forms and clients from before multiple connections working.
    """
    accounts = JellyfinAccount.objects.filter(user=request.user)
    account_id = _jellyfin_posted_account_id(request)
    if account_id:
        return accounts.filter(id=account_id).first() if account_id.isdigit() else None
    only = list(accounts[:2])
    return only[0] if len(only) == 1 else None


def _jellyfin_identity_scope(server_id, base_url):
    """Return the Playback Reporting identity prefix for a new connection."""
    return server_id or hashlib.sha256(base_url.encode()).hexdigest()[:16]


@require_POST
def jellyfin_connect(request):
    """Add a Jellyfin connection, or edit one when ``account_id`` is given."""
    redirect_target = app_helpers.safe_return_url(
        request,
        request.POST.get("next"),
        reverse("provider_detail", args=["jellyfin"]) + "?tab=connection",
    )
    editing = bool(_jellyfin_posted_account_id(request))
    existing_account = _jellyfin_account_from_post(request) if editing else None
    if editing and existing_account is None:
        messages.error(request, "That Jellyfin connection no longer exists.")
        return redirect(redirect_target)

    base_url = request.POST.get("base_url", "").strip()
    api_key = request.POST.get("api_key", "").strip()
    username = request.POST.get("username", "").strip()
    name = request.POST.get("name", "").strip()[:100]
    if existing_account is not None:
        # Editing keeps whatever the form leaves blank; the key is never shown,
        # so blank means "unchanged".
        base_url = base_url or existing_account.base_url
        if not api_key and existing_account.api_key:
            try:
                api_key = helpers.decrypt_or_raise(existing_account.api_key)
            except helpers.MediaImportError:
                api_key = ""
    if not base_url or not api_key:
        messages.error(request, "Jellyfin base URL and API key are required.")
        return redirect(redirect_target)

    client = JellyfinClient(base_url, api_key)
    try:
        server_info = client.healthcheck() or {}
        current_user = client.get_current_user()
        if not current_user and username:
            current_user = client.find_user_by_name(username)
    except (JellyfinAuthError, JellyfinClientError) as exc:
        messages.error(request, f"Failed to connect to Jellyfin: {exc}")
        return redirect(redirect_target)

    if not current_user or not current_user.get("Id"):
        messages.error(
            request,
            "Could not resolve a Jellyfin user for this API key. "
            "Dashboard API keys are not tied to a user, so enter the exact "
            "Jellyfin username in the username field and try again.",
        )
        return redirect(redirect_target)

    server_id = (
        str(server_info.get("Id") or "") if isinstance(server_info, dict) else ""
    )
    same_server = Q(base_url=base_url)
    if server_id:
        same_server |= Q(server_id=server_id)
    duplicates = JellyfinAccount.objects.filter(
        same_server,
        user=request.user,
        jellyfin_user_id=current_user["Id"],
    )
    if existing_account is not None:
        duplicates = duplicates.exclude(pk=existing_account.pk)
    if duplicates.exists():
        messages.error(request, "This Jellyfin server and user are already connected.")
        return redirect(redirect_target)

    identity_changed = existing_account is not None and (
        existing_account.base_url != base_url
        or existing_account.jellyfin_user_id != current_user["Id"]
    )

    values = {
        "base_url": base_url,
        "api_key": helpers.encrypt(api_key),
        "jellyfin_user_id": current_user["Id"],
        "jellyfin_username": current_user.get("Name", ""),
        "server_id": server_id,
        "connection_broken": False,
        "last_error_message": "",
        "last_pull_error_message": "",
    }
    if name or existing_account is None:
        values["name"] = name
    if existing_account is None or identity_changed:
        # A different server/user invalidates any cached pull state: a
        # Playback Reporting rowid or "unavailable" result from the old
        # identity would otherwise silently carry over to the new one.
        values.update(
            {
                "identity_scope": _jellyfin_identity_scope(server_id, base_url),
                "playback_reporting_available": None,
                "playback_reporting_last_rowid": None,
                "library_backfill_completed_at": None,
            },
        )

    def _connect():
        if existing_account is None:
            account = JellyfinAccount.objects.create(user=request.user, **values)
        else:
            account = existing_account
            for field, value in values.items():
                setattr(account, field, value)
            account.save(update_fields=[*values, "updated_at"])
        if account.pull_history_enabled:
            _ensure_jellyfin_pull_schedule(request.user, account)
        return account

    account = _run_with_lock_retry("connect Jellyfin", _connect)

    # Seamless by default: queue an automatic history pull right away so a
    # newly connected user sees their watch history without any manual
    # export/upload step, and keep it running on a schedule going forward.
    if _queue_task_or_message(
        request,
        tasks.pull_jellyfin_history,
        user_id=request.user.id,
        account_id=account.id,
    ) is not False:
        messages.success(
            request,
            "Connected Jellyfin. Importing your watch history now.",
        )
    return redirect(redirect_target)


@require_POST
def jellyfin_disconnect(request):
    """Disconnect one Jellyfin connection, leaving the others untouched."""
    redirect_target = app_helpers.safe_return_url(
        request,
        request.POST.get("next"),
        reverse("provider_detail", args=["jellyfin"]) + "?tab=connection",
    )
    account = _jellyfin_account_from_post(request)
    if account is None:
        messages.error(request, "That Jellyfin connection no longer exists.")
        return redirect(redirect_target)

    def _disconnect():
        from integrations.webhooks.jellyfin import release_connection_sources

        _disable_jellyfin_push_schedule(request.user, account)
        _disable_jellyfin_pull_schedule(request.user, account)
        release_connection_sources(request.user, account)
        account.delete()

    _run_with_lock_retry("disconnect Jellyfin", _disconnect)
    messages.info(request, "Disconnected Jellyfin.")
    return redirect(redirect_target)


@require_POST
def jellyfin_settings(request):
    """Update one connection's push-sync and history-pull toggles."""
    redirect_target = app_helpers.safe_return_url(
        request,
        request.POST.get("next"),
        reverse("provider_detail", args=["jellyfin"]) + "?tab=sync",
    )
    account = _jellyfin_account_from_post(request)
    if not account:
        messages.error(request, "Connect Jellyfin before changing sync settings.")
        return redirect(redirect_target)

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
        _disable_jellyfin_push_schedule(request.user, account)

    if account.pull_history_enabled:
        _ensure_jellyfin_pull_schedule(request.user, account)
    else:
        _disable_jellyfin_pull_schedule(request.user, account)

    messages.success(request, "Jellyfin sync settings updated.")
    return redirect(redirect_target)


@require_POST
def jellyfin_push_now(request):
    """Queue an immediate watched-state push to one Jellyfin connection."""
    redirect_target = app_helpers.safe_return_url(
        request,
        request.POST.get("next"),
        reverse("provider_detail", args=["jellyfin"]) + "?tab=sync",
    )
    account = _jellyfin_account_from_post(request)
    if not account:
        messages.error(request, "Connect Jellyfin before syncing.")
        return redirect(redirect_target)

    if _queue_task_or_message(
        request,
        tasks.push_jellyfin_watched,
        user_id=request.user.id,
        account_id=account.id,
    ) is not False:
        messages.info(request, "Jellyfin sync queued.")
    return redirect(redirect_target)


@require_POST
def jellyfin_pull_now(request):
    """Queue an immediate history pull for one Jellyfin connection."""
    redirect_target = app_helpers.safe_return_url(
        request,
        request.POST.get("next"),
        reverse("provider_detail", args=["jellyfin"]) + "?tab=import",
    )
    account = _jellyfin_account_from_post(request)
    # A broken account is still queued: the pull re-probes the key and clears
    # the flag when it works again.
    if not account or not account.base_url or not account.api_key:
        messages.error(request, "Connect Jellyfin before importing history.")
        return redirect(redirect_target)

    if _queue_task_or_message(
        request,
        tasks.pull_jellyfin_history,
        user_id=request.user.id,
        account_id=account.id,
    ) is not False:
        messages.info(request, "Jellyfin history import queued.")
    return redirect(redirect_target)


@require_POST
def jellyfin_playback_reporting_import(request):
    """Queue a manual Playback Reporting TSV import for one connection."""
    redirect_target = app_helpers.safe_return_url(
        request,
        request.POST.get("next"),
        reverse("provider_detail", args=["jellyfin"]) + "?tab=import",
    )
    account = _jellyfin_account_from_post(request)
    if not account or not account.is_connected:
        messages.error(
            request,
            "Connect Jellyfin before importing Playback Reporting data.",
        )
        return redirect(redirect_target)

    uploaded_file = request.FILES.get("playback_reporting_file")
    if not uploaded_file:
        messages.error(request, "Choose a Playback Reporting TSV export first.")
        return redirect(redirect_target)

    if uploaded_file.size > JELLYFIN_PLAYBACK_REPORTING_MAX_UPLOAD_BYTES:
        messages.error(request, "The Playback Reporting export is larger than 50 MB.")
        return redirect(redirect_target)

    if uploaded_file.size == 0:
        messages.error(request, "The Playback Reporting export is empty.")
        return redirect(redirect_target)

    staged_file = _stage_upload_or_message(
        request,
        uploaded_file,
        "Jellyfin Playback Reporting export",
    )
    if staged_file is None:
        return redirect(redirect_target)

    if _queue_staged_task_or_message(
        request,
        tasks.import_jellyfin_playback_reporting,
        staged_file,
        request.user.id,
        "new",
        account.id,
        staged_paths=(staged_file,),
    ) is False:
        return redirect(redirect_target)
    messages.info(request, "Jellyfin Playback Reporting import queued.")
    return redirect(redirect_target)


def _ensure_recurring_import_schedule(user, label, poll_interval_minutes):
    """Create or update a user's recurring "Import from <label>" schedule."""
    from django_celery_beat.models import IntervalSchedule, PeriodicTask

    interval, _ = IntervalSchedule.objects.get_or_create(
        every=poll_interval_minutes,
        period=IntervalSchedule.MINUTES,
    )
    task_name = (
        f"Import from {label} for {user.username} "
        f"(every {poll_interval_minutes} minutes)"
    )
    task = f"Import from {label} (Recurring)"
    existing_task = PeriodicTask.objects.filter(
        task=task,
        **helpers.periodic_task_user_kwargs(user.id),
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
        task=task,
        interval=interval,
        kwargs=json.dumps({"user_id": user.id}),
        start_time=timezone.now(),
        enabled=True,
    )


def _ensure_audiobookshelf_schedule(user):
    """Create or update the recurring Audiobookshelf import schedule for a user."""
    return _ensure_recurring_import_schedule(
        user,
        "Audiobookshelf",
        getattr(settings, "AUDIOBOOKSHELF_POLL_INTERVAL_MINUTES", 15),
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
    if _queue_task_or_message(request,
        tasks.import_audiobookshelf, user_id=request.user.id, mode="new"
    ) is not False:
        messages.success(request, "Connected Audiobookshelf. Initial import queued.")
    return _integration_redirect(request, connected_slug="audiobookshelf")


@require_POST
def audiobookshelf_disconnect(request):
    """Disconnect Audiobookshelf integration."""
    from django_celery_beat.models import PeriodicTask

    def _disconnect():
        PeriodicTask.objects.filter(
            task="Import from Audiobookshelf (Recurring)",
            **helpers.periodic_task_user_kwargs(request.user.id),
        ).delete()
        AudiobookshelfAccount.objects.filter(user=request.user).delete()

    _run_with_lock_retry("disconnect Audiobookshelf", _disconnect)
    messages.info(request, "Disconnected Audiobookshelf.")
    return _integration_redirect(request)


@require_POST
def import_audiobookshelf(request):
    """Queue Audiobookshelf import and ensure recurring schedule exists."""
    account = getattr(request.user, "audiobookshelf_account", None)
    if not account:
        messages.error(request, "Connect Audiobookshelf before importing.")
        return _integration_redirect(request)

    queued = _queue_task_or_message(request,
        tasks.import_audiobookshelf, user_id=request.user.id, mode="new"
    )
    _ensure_audiobookshelf_schedule(request.user)

    if queued is not False:
        messages.info(request, "Audiobookshelf import queued.")
    return _integration_redirect(request)


def _sync_interval(request, account_model, default=15):
    """Return the sync interval chosen in a reading server form, or ``default``."""
    try:
        minutes = int(request.POST.get("sync_interval_minutes", default))
    except ValueError:
        return default
    return minutes if minutes in account_model.SYNC_INTERVAL_CHOICES else default


def _reading_server_connect(
    request, service, account_model, client_class, import_task, related_name
):
    """Connect a reading server (Komga, Kavita) using its URL and an API key."""
    base_url = request.POST.get("base_url", "").strip()
    api_key = request.POST.get("api_key", "").strip()

    if not base_url or not api_key:
        messages.error(request, f"{service} server URL and API key are required.")
        return _integration_redirect(request)

    try:
        client_class(base_url, api_key).healthcheck()
    except Exception as exc:
        messages.error(request, f"Failed to connect to {service}: {exc}")
        return _integration_redirect(request)

    interval = _sync_interval(request, account_model)

    def _connect():
        account_model.objects.update_or_create(
            user=request.user,
            defaults={
                "base_url": base_url,
                "api_key": helpers.encrypt(api_key),
                "sync_interval_minutes": interval,
                "connection_broken": False,
                "last_error_message": "",
            },
        )
        _ensure_recurring_import_schedule(request.user, service, interval)

    _run_with_lock_retry(f"connect {service}", _connect)
    if _queue_task_or_message(
        request, import_task, user_id=request.user.id, mode="new"
    ) is not False:
        messages.success(request, f"Connected {service}. Initial import queued.")
    return _integration_redirect(request, connected_slug=related_name)


def _reading_server_disconnect(request, service, account_model):
    """Disconnect a reading server and remove its recurring schedule."""
    from django_celery_beat.models import PeriodicTask

    def _disconnect():
        PeriodicTask.objects.filter(
            task=f"Import from {service} (Recurring)",
            **helpers.periodic_task_user_kwargs(request.user.id),
        ).delete()
        account_model.objects.filter(user=request.user).delete()

    _run_with_lock_retry(f"disconnect {service}", _disconnect)
    messages.info(request, f"Disconnected {service}.")
    return redirect("import_data")


def _reading_server_sync_now(request, service, account_attr, import_task):
    """Queue a sync now and keep the recurring schedule in place."""
    account = getattr(request.user, account_attr, None)
    if not account:
        messages.error(request, f"Connect {service} before importing.")
        return redirect("import_data")

    queued = _queue_task_or_message(
        request, import_task, user_id=request.user.id, mode="new"
    )
    _ensure_recurring_import_schedule(
        request.user, service, account.sync_interval_minutes
    )

    if queued is not False:
        messages.info(request, f"{service} sync queued.")
    return redirect("import_data")


@require_POST
def komga_connect(request):
    """Connect Komga using its server URL and an API key."""
    return _reading_server_connect(
        request, "Komga", KomgaAccount, KomgaClient, tasks.import_komga, "komga"
    )


@require_POST
def komga_disconnect(request):
    """Disconnect Komga."""
    return _reading_server_disconnect(request, "Komga", KomgaAccount)


@require_POST
def import_komga(request):
    """Queue a Komga sync now."""
    return _reading_server_sync_now(
        request, "Komga", "komga_account", tasks.import_komga
    )


@require_POST
def kavita_connect(request):
    """Connect Kavita using its server URL and an API key."""
    return _reading_server_connect(
        request, "Kavita", KavitaAccount, KavitaClient, tasks.import_kavita, "kavita"
    )


@require_POST
def kavita_disconnect(request):
    """Disconnect Kavita."""
    return _reading_server_disconnect(request, "Kavita", KavitaAccount)


@require_POST
def import_kavita(request):
    """Queue a Kavita sync now."""
    return _reading_server_sync_now(
        request, "Kavita", "kavita_account", tasks.import_kavita
    )


@require_POST
def refresh_kavita(request):
    """Queue a full Kavita rescan with provider re-resolution."""
    account = getattr(request.user, "kavita_account", None)
    if not account:
        messages.error(request, "Connect Kavita before refreshing.")
        return redirect("import_data")
    queued = _queue_task_or_message(
        request,
        tasks.import_kavita,
        user_id=request.user.id,
        mode="overwrite",
    )
    if queued is not False:
        messages.info(request, "Kavita metadata refresh queued.")
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
    pending_auth.put(STORYTELLER_PENDING_SESSION_KEY, request.user.pk, {
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
    }, ttl=expires_in)
    messages.info(
        request, "Approve the login on your Storyteller server to finish connecting."
    )
    return redirect("import_data")


@require_GET
def storyteller_poll(request):
    """Poll Storyteller for the access token during device login."""
    pending = pending_auth.get(STORYTELLER_PENDING_SESSION_KEY, request.user.pk)
    if not pending:
        return JsonResponse({"status": "idle"})

    expires_at = pending.get("expires_at")
    if expires_at and timezone.now() > datetime.fromisoformat(expires_at):
        pending_auth.clear(STORYTELLER_PENDING_SESSION_KEY, request.user.pk)
        return JsonResponse({"status": "expired"})

    client = StorytellerClient(pending["server_url"])
    try:
        data, status_code = client.poll_device_token(pending["device_code"])
    except Exception as exc:
        # requests errors carry the server URL: log the class, answer plainly.
        logger.warning("Storyteller device poll failed: %s", exception_summary(exc))
        return JsonResponse({"status": "pending"})

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
        pending_auth.clear(STORYTELLER_PENDING_SESSION_KEY, request.user.pk)
        if not _queue_task_quietly(
            tasks.import_storyteller, user_id=request.user.id, mode="new"
        ):
            return JsonResponse({"status": "connected", "import_queued": False})
        return JsonResponse({"status": "connected"})

    error = data.get("error") if isinstance(data, dict) else None
    if (
        error in ("authorization_pending", "slow_down")
        or status_code == HTTPStatus.BAD_REQUEST
    ):
        return JsonResponse({"status": "pending"})

    pending_auth.clear(STORYTELLER_PENDING_SESSION_KEY, request.user.pk)
    return JsonResponse({"status": "error", "message": error or "Login failed."})


@require_POST
def storyteller_cancel(request):
    """Cancel an in-progress Storyteller device login."""
    pending_auth.clear(STORYTELLER_PENDING_SESSION_KEY, request.user.pk)
    messages.info(request, "Storyteller login cancelled.")
    return redirect("import_data")


@require_POST
def storyteller_disconnect(request):
    """Disconnect the Storyteller integration."""
    from django_celery_beat.models import PeriodicTask

    def _disconnect():
        PeriodicTask.objects.filter(
            task=STORYTELLER_RECURRING_TASK_NAME,
            **helpers.periodic_task_user_kwargs(request.user.id),
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

    queued = _queue_task_or_message(request, tasks.import_storyteller, user_id=request.user.id, mode="new")
    _ensure_storyteller_schedule(request.user)
    if queued is not False:
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
        if _queue_task_or_message(request,
            tasks.import_koreader, user_id=request.user.id, mode=mode
        ) is not False:
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
        if _queue_task_or_message(request,
            tasks.import_koreader, user_id=request.user.id, mode=mode
        ) is not False:
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
            **helpers.periodic_task_user_kwargs(request.user.id),
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
        if _queue_task_or_message(request,
            tasks.import_koreader, user_id=request.user.id, mode=mode
        ) is not False:
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
        if _queue_task_or_message(request, task, user_id=request.user.id, mode=mode) is False:
            return
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


def _psn_import_existing_playtime(request, default=True):
    """Read the setup choice posted with the PSN forms."""
    value = request.POST.get("existing_playtime")
    return default if value is None else value != "new_only"


def _ensure_psn_schedule(user):
    """Keep exactly one recurring PSN sync for the user, at the fixed cadence.

    PSN has no per-user frequency setting: a sync is cheap, and the sooner the
    next one runs the narrower the window its new entry is slotted into. A
    schedule left from the earlier daily/2-day choice is replaced.
    """
    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    crontab, _ = CrontabSchedule.objects.get_or_create(
        # Spread users across the hour instead of syncing them all at once.
        minute=str(user.id % 60),
        hour=f"*/{psn_import.SYNC_EVERY_HOURS}",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        timezone=timezone.get_default_timezone(),
    )
    own_tasks = PeriodicTask.objects.filter(
        _periodic_task_filter_for_user(user.id),
        task=PSN_RECURRING_TASK_NAME,
    )
    own_tasks.exclude(crontab=crontab).delete()

    kwargs = json.dumps({"user_id": user.id, "mode": "new"})
    task = own_tasks.first()
    if task:
        task.kwargs = kwargs
        task.enabled = True
        task.save(update_fields=["kwargs", "enabled"])
        return

    # The id keeps the name unique when a username is changed and reused.
    PeriodicTask.objects.create(
        name=(
            f"Import from PSN for {user.username} (#{user.id}) "
            f"every {psn_import.SYNC_EVERY_HOURS} hours"
        ),
        task=PSN_RECURRING_TASK_NAME,
        crontab=crontab,
        kwargs=kwargs,
        start_time=_next_crontab_run(crontab),
        enabled=True,
    )


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

    def _connect():
        # Remembered totals belong to one PSN account: another account's totals
        # would read as fabricated (or hidden) play against the old ones.
        previous = PSNAccount.objects.filter(user=request.user).first()
        new_account = previous is None or previous.account_id != account_id
        if new_account:
            PlaytimeSnapshot.objects.filter(user=request.user, source="psn").delete()
        PSNAccount.objects.update_or_create(
            user=request.user,
            defaults={
                **({"last_sync_at": None} if new_account else {}),
                "npsso": helpers.encrypt(npsso),
                "account_id": account_id,
                "online_id": online_id,
                "import_existing_playtime": _psn_import_existing_playtime(request),
                "connection_broken": False,
                "last_error_message": "",
            },
        )

    _run_with_lock_retry("connect PSN", _connect)
    messages.success(
        request,
        f"Connected to PlayStation Network as {online_id or account_id}.",
    )
    _run_with_lock_retry("schedule PSN import", lambda: _sync_psn_now(request))
    return redirect("import_data")


def _sync_psn_now(request):
    """Queue a sync now and make sure the recurring one is in place."""
    _ensure_psn_schedule(request.user)
    if (
        _queue_task_or_message(
            request,
            tasks.import_psn,
            user_id=request.user.id,
            mode="new",
        )
        is False
    ):
        return
    messages.info(
        request,
        "The PlayStation sync has been queued. It repeats every "
        f"{psn_import.SYNC_EVERY_HOURS} hours.",
    )


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
        PlaytimeSnapshot.objects.filter(user=request.user, source="psn").delete()

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

    wants_existing = _psn_import_existing_playtime(
        request,
        default=account.import_existing_playtime,
    )
    if wants_existing != account.import_existing_playtime:
        account.import_existing_playtime = wants_existing
        account.save(update_fields=["import_existing_playtime"])

    _run_with_lock_retry("schedule PSN import", lambda: _sync_psn_now(request))
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
                **helpers.periodic_task_user_kwargs(request.user.id),
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
            if _queue_task_or_message(request,
                tasks.import_pocketcasts,
                user_id=request.user.id,
                mode="new",
            ) is not False:
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
            **helpers.periodic_task_user_kwargs(request.user.id),
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
                **helpers.periodic_task_user_kwargs(request.user.id),
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
            if _queue_task_or_message(request,
                tasks.import_gpodder, user_id=request.user.id, mode="new"
            ) is not False:
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
            **helpers.periodic_task_user_kwargs(request.user.id),
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
        poll_queued = _queue_task_or_message(request, tasks.poll_lastfm_for_user, user_id=request.user.id)
        history_queued = _queue_task_or_message(request,
            tasks.import_lastfm_history, user_id=request.user.id, reset=False
        )
        if poll_queued is not False and history_queued is not False:
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

    if _queue_task_or_message(request, tasks.poll_lastfm_for_user, user_id=request.user.id) is not False:
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
    if _queue_task_or_message(request,
        tasks.import_lastfm_history, user_id=request.user.id, reset=False
    ) is not False:
        messages.info(request, "Full Last.fm history import queued.")
    return redirect("import_data")


def _ensure_koito_poll_schedule(user):
    """Create the recurring Koito poll schedule for a user if missing."""
    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    existing_task = PeriodicTask.objects.filter(
        task=tasks.KOITO_POLL_TASK_NAME,
        **helpers.periodic_task_user_kwargs(user.id),
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
    poll_queued = _queue_task_or_message(request, tasks.poll_koito_for_user, user_id=request.user.id)
    history_queued = _queue_task_or_message(request,
        tasks.import_koito_history, user_id=request.user.id, reset=True
    )
    if poll_queued is not False and history_queued is not False:
        messages.success(request, "Connected Koito. Full history import queued.")
    return _integration_redirect(request, connected_slug="koito")


@require_POST
def koito_disconnect(request):
    """Disconnect the Koito integration."""
    from django_celery_beat.models import PeriodicTask

    def _disconnect():
        PeriodicTask.objects.filter(
            task=tasks.KOITO_POLL_TASK_NAME,
            **helpers.periodic_task_user_kwargs(request.user.id),
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

    if _queue_task_or_message(request, tasks.poll_koito_for_user, user_id=request.user.id) is not False:
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

    if _queue_task_or_message(request,
        tasks.import_koito_history, user_id=request.user.id, reset=True
    ) is not False:
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
        **helpers.periodic_task_user_kwargs(request.user.id),
        enabled=True,
    ).first()

    # Always use mode="new" for Pocket Casts
    mode = "new"

    if not existing_task:
        # First import - run immediately, then set up 2-hour schedule
        queued = _queue_task_or_message(request,
            tasks.import_pocketcasts,
            user_id=request.user.id,
            mode=mode,
        )
        if queued is not False:
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
    # Just run a manual import
    elif _queue_task_or_message(request,
        tasks.import_pocketcasts,
        user_id=request.user.id,
        mode=mode,
    ) is not False:
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
        **helpers.periodic_task_user_kwargs(request.user.id),
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
        queued = _queue_task_or_message(request, tasks.import_gpodder, user_id=request.user.id, mode="new")
        if queued is not False:
            messages.info(
                request,
                "The task to import media from GPodder has been queued. Recurring syncs will run every 2 hours.",
            )
    elif _queue_task_or_message(request,
        tasks.import_gpodder, user_id=request.user.id, mode="new"
    ) is not False:
        messages.info(request, "The task to import media from GPodder has been queued.")

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
def hardcover_sync(request):
    """Sync the user's Hardcover library now, or on the chosen import schedule."""
    if not credentials.has_user_value("hardcover", request.user):
        messages.error(request, "Save your Hardcover API key before syncing.")
        return _integration_redirect(request)

    mode = request.POST["mode"]
    frequency = request.POST["frequency"]
    if frequency == "once":
        if _queue_task_or_message(
            request,
            tasks.import_hardcover_account,
            user_id=request.user.id,
            mode=mode,
        ) is not False:
            messages.info(request, "Hardcover sync queued.")
    else:
        helpers.create_import_schedule(
            username=request.user.username,
            request=request,
            mode=mode,
            frequency=frequency,
            import_time=request.POST["time"],
            source="Hardcover Account",
            extra_kwargs={"user_id": request.user.id},
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
def import_youtube_takeout(request):
    """View for importing YouTube watch history from a Google Takeout file."""
    file = request.FILES.get("youtube_takeout")

    if not file:
        messages.error(request, "A YouTube watch history file is required.")
        return _integration_redirect(request)

    staged_file = _stage_upload_or_message(request, file, "YouTube watch history")
    if staged_file is None:
        return _integration_redirect(request)

    mode = request.POST["mode"]
    if _queue_staged_task_or_message(
        request,
        tasks.import_youtube_takeout,
        user_id=request.user.id,
        file=staged_file,
        mode=mode,
        staged_paths=(staged_file,),
    ) is False:
        return _integration_redirect(request)
    messages.info(
        request,
        "The task to import your YouTube watch history has been queued.",
    )
    return _integration_redirect(request)


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


def _match_destination_from_result(result, media_type, source):
    """Materialize a same-type search result for preview/apply."""
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
        source=source,
        media_type=media_type,
        defaults=defaults,
    )
    return destination


def _match_providers(user, source_item):
    """Return the providers this show can be matched on, TMDB first."""
    providers = [Sources.TMDB.value]
    if source_item.media_type == MediaTypes.TV.value and (
        metadata_resolution.provider_is_enabled(Sources.TVDB.value, user)
    ):
        providers.append(Sources.TVDB.value)
    return providers


def _match_candidate_rows(results):
    """Return renderable destination rows without persisting any Item.

    Rendering used to hand the template an Item pk per result, which meant a
    search wrote one Item (and its later metadata fan-out) for every hit.
    """
    rows = []
    for result in results:
        media_id = result.get("media_id") or result.get("id")
        title = result.get("title") or result.get("name")
        if not media_id or not title:
            continue
        rows.append({"media_id": str(media_id), "title": title, "result": result})
    return rows


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


def _match_review(source_item, preview):
    """Return the numbering rows and destination episodes for a TV correction."""
    catalogue = destination_episodes(preview["destination"])
    if not catalogue:
        raise InvalidMatchCorrectionError(
            gettext("The destination has no episodes to map your viewings onto."),
        )
    seen = {}
    for row in preview["episodes"]:
        seen.setdefault(row["key"], row)
    source_rows = sorted(seen.values(), key=lambda row: (row["season"], row["episode"]))
    proposals = suggest_mapping(source_rows, catalogue)
    rows = {}
    for row in source_rows:
        selected, kind = proposals.get(row["key"], ("", ""))
        row_id = f"{row['season']}_{row['episode']}"
        rows[row_id] = {
            "id": row_id,
            "key": row["key"],
            "season": row["season"],
            "code": f"S{int(row['season']):02d}E{int(row['episode']):02d}",
            "title": row["title"],
            "selected": selected,
            "kind": kind,
        }
    return {"rows": rows, "episodes": catalogue}


def _match_posted_mapping(post, catalogue_ids):
    """Read the numbering the user chose; every value must be a destination episode."""
    mapping = {}
    for name, value in post.items():
        if not name.startswith("map_"):
            continue
        season, _, episode = name.removeprefix("map_").partition("_")
        if value not in catalogue_ids:
            raise InvalidMatchCorrectionError(
                gettext("Choose an episode for every viewing."),
            )
        destination_season, _, destination_episode = value.partition(":")
        mapping[f"{season}:{episode}"] = {
            "season": int(destination_season),
            "episode": int(destination_episode),
        }
    return mapping


@login_required
def match_fix(request, item_id):
    """Search, preview, and apply a same-type match correction."""
    source_item = _match_source_for_user(request, item_id)
    providers = _match_providers(request.user, source_item)
    provider = request.POST.get("provider") or request.GET.get("provider")
    if provider not in providers:
        provider = Sources.TMDB.value
    provider_label = metadata_resolution.metadata_provider_label(provider)
    query = request.GET.get("q", "").strip()
    candidates = []
    if query:
        try:
            candidates = services.search(
                source_item.media_type,
                query,
                1,
                source=provider,
                user=request.user,
            ).get("results", [])
        except services.ProviderAPIError as error:
            messages.error(
                request,
                gettext("Could not search %(provider)s: %(error)s")
                % {"provider": provider_label, "error": error},
            )

    candidate_rows = _match_candidate_rows(candidates)

    destination = None
    apply_requested = False
    stored = {}
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "preview":
            chosen = next(
                (
                    row
                    for row in candidate_rows
                    if row["media_id"] == request.POST.get("destination_media_id")
                ),
                None,
            )
            destination = (
                _match_destination_from_result(
                    chosen["result"],
                    source_item.media_type,
                    provider,
                )
                if chosen
                else None
            )
            if destination is None:
                messages.error(
                    request,
                    gettext("Choose a valid same-type destination."),
                )
        elif action == "apply":
            stored = request.session.get("match_correction_preview") or {}
            if stored.get("source_item_id") != source_item.pk:
                messages.error(
                    request,
                    gettext("Refresh the correction preview before applying."),
                )
            else:
                apply_requested = True
                destination = Item.objects.filter(
                    pk=stored["destination_item_id"],
                ).first()

    preview = None
    review = None
    if destination is not None:
        try:
            preview = preview_match_correction(request.user, source_item, destination)
            if source_item.media_type == MediaTypes.TV.value:
                review = _match_review(source_item, preview)
            if apply_requested:
                mapping = (
                    _match_posted_mapping(
                        request.POST,
                        {row["id"] for row in review["episodes"]},
                    )
                    if review
                    else None
                )
                decisions = {
                    key.removeprefix("decision_"): value
                    for key, value in request.POST.items()
                    if key.startswith("decision_") and value
                }
                destination_item = apply_match_correction(
                    request.user,
                    source_item.pk,
                    destination.pk,
                    request.session["match_correction_preview"]["token"],
                    episode_mapping=mapping,
                    decisions=decisions,
                    reference_ids=stored.get("reference_ids", []),
                    note=request.POST.get("note", ""),
                )
            else:
                request.session["match_correction_preview"] = {
                    "source_item_id": source_item.pk,
                    "destination_item_id": destination.pk,
                    "token": preview["token"],
                    "reference_ids": _match_reference_ids(request.user, source_item),
                }
        except (
            InvalidMatchCorrectionError,
            MissingEpisodeMappingError,
            StaleCorrectionPreviewError,
            services.ProviderAPIError,
        ) as error:
            messages.error(request, str(error))
            if apply_requested and preview is not None and review is not None:
                # Keep the review on screen with the user's choices, and let the
                # next apply use the state the refreshed review now shows.
                for row_id, row in review["rows"].items():
                    row["selected"] = request.POST.get(f"map_{row_id}", row["selected"])
                request.session["match_correction_preview"] = {
                    **stored,
                    "token": preview["token"],
                }
            else:
                preview = review = None
        else:
            if apply_requested:
                request.session.pop("match_correction_preview", None)
                messages.success(
                    request,
                    gettext("Match corrected and future imports mapped."),
                )
                return redirect(
                    "media_details",
                    source=destination_item.source,
                    media_type=source_item.media_type,
                    media_id=destination_item.media_id,
                    title=destination_item.title,
                )

    context = {
        "source_item": source_item,
        "candidates": candidate_rows,
        "providers": [
            (key, metadata_resolution.metadata_provider_label(key))
            for key in providers
        ],
        "provider": provider,
        "provider_label": provider_label,
        "preview": preview,
        "review": review,
        "review_rows": list(review["rows"].values()) if review else [],
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


@require_http_methods(["GET", "POST"])
def seerr_request(request, media_type, media_id):
    """Show a title's Seerr state, and request it (or some seasons) on POST."""
    user = request.user
    if (
        media_type not in (MediaTypes.MOVIE.value, MediaTypes.TV.value)
        or not user.seerr_url
        or not user.seerr_api_key
        or not user.seerr_user_id
    ):
        return HttpResponseNotFound()

    error = None
    summary = None
    try:
        client = seerr_api.SeerrClient.for_user(user)
        if request.method == "POST":
            seasons = [
                int(number)
                for number in request.POST.getlist("season")
                if number.isdigit()
            ]
            client.request(
                media_type,
                media_id,
                user.seerr_user_id,
                seasons=seasons or None,
            )
        summary = seerr_api.summarize(media_type, client.media(media_type, media_id))
    except (seerr_api.SeerrError, helpers.MediaImportError) as exc:
        error = str(exc)

    return render(
        request,
        "integrations/seerr_request.html",
        {
            "media_type": media_type,
            "media_id": media_id,
            "summary": summary,
            "error": error,
            "seerr_page_url": f"{user.seerr_url}/{media_type}/{media_id}",
        },
    )


def _int_or_none(value):
    """Return `value` as an int, or None when it is blank or not a number."""
    return int(value) if str(value or "").isdigit() else None


@require_http_methods(["GET", "POST"])
def library_panel(request, source, media_type, media_id):
    """Show Radarr/Sonarr details and Seerr requests for a title; POST searches."""
    user = request.user
    params = request.POST if request.method == "POST" else request.GET
    season = _int_or_none(params.get("season_number"))
    episode = _int_or_none(params.get("episode_number"))

    message = error = ""
    if request.method == "POST":
        error = arr_library.start_search(
            user,
            params.get("app"),
            _int_or_none(params.get("instance_id")),
            params.get("kind"),
            _int_or_none(params.get("arr_id")),
            _int_or_none(params.get("season")),
        )
        message = "" if error else f"Search started in {params.get('app')}."

    panels = arr_library.library_panels(
        user, source, media_type, media_id, season, episode
    )

    seerr_requests = None
    seerr_error = ""
    if (
        user.seerr_url
        and user.seerr_api_key
        and source == Sources.TMDB.value
        and media_type
        in (
            MediaTypes.MOVIE.value,
            MediaTypes.TV.value,
            MediaTypes.SEASON.value,
            MediaTypes.EPISODE.value,
        )
    ):
        seerr_type = (
            MediaTypes.MOVIE.value
            if media_type == MediaTypes.MOVIE.value
            else MediaTypes.TV.value
        )
        try:
            seerr_requests = seerr_api.requests_for(
                seerr_api.SeerrClient.for_user(user).media(seerr_type, media_id),
                season_number=(
                    None if media_type == MediaTypes.TV.value else season
                ),
            )
        except (seerr_api.SeerrError, helpers.MediaImportError) as exc:
            seerr_error = str(exc)
        seerr_url = f"{user.seerr_url.rstrip('/')}/{seerr_type}/{media_id}"
    else:
        seerr_url = ""

    return render(
        request,
        "integrations/library_panel.html",
        {
            "panels": panels,
            "message": message,
            "error": error,
            "seerr_requests": seerr_requests,
            "seerr_error": seerr_error,
            "seerr_url": seerr_url,
            "panel_url": request.path,
            "season_number": season,
            "episode_number": episode,
            # Props for the shared ArrLibraryPanels island; the markup above is
            # its server fallback.
            "panel_props": {
                "panels": panels,
                "message": message,
                "error": error,
                "seerrRequests": seerr_requests,
                "seerrError": seerr_error,
                "seerrUrl": seerr_url,
                "panelUrl": request.path,
                "seasonNumber": season,
                "episodeNumber": episode,
                "labels": {
                    "requests": gettext("Requests"),
                    "notRequested": gettext("Not requested in Seerr."),
                    "searchNow": gettext("Search now"),
                    "copy": gettext("Copy"),
                    "copied": gettext("Copied"),
                    "activity": gettext("Activity"),
                    "hasFile": gettext("Has file"),
                    "downloading": gettext("Downloading"),
                    "missing": gettext("Missing"),
                    "notMonitored": gettext("Not monitored"),
                    "episodesHaveFiles": gettext("%s of %s episodes have files"),
                    "added": gettext("Added %s"),
                    "openIn": gettext("Open in %s"),
                    "notFound": gettext("Not in %s"),
                },
            },
        },
    )
