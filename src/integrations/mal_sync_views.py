"""MyAnimeList two-way sync: connecting, settings, mapping, full syncs, exports.

The one-off import from a MyAnimeList username is import_mal in
integrations/views.py. The sync itself runs in integrations/mal_sync.py and
integrations/tasks/_mal_sync.py; these views start it and show its state.
"""

import json
import secrets
from urllib.parse import urlencode

from django.contrib import messages
from django.core import signing
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from kombu.exceptions import OperationalError as BrokerOperationalError

from app import helpers as app_helpers
from app.models import TV, MediaTypes, Sources
from app.providers import credentials, services
from app.templatetags.app_tags import media_url
from integrations import mal_sync, pending_auth, tasks
from integrations.view_helpers import (
    _consume_oauth_state,
    _integration_redirect,
    _periodic_task_filter_for_user,
)

# MyAnimeList search rejects shorter queries with HTTP 400.
MAL_MAPPING_MIN_QUERY_LENGTH = 3


@require_POST
def mal_oauth(request):
    """Initiate the MyAnimeList OAuth2 flow used for status syncing."""
    if not mal_sync.is_sync_configured(request.user):
        messages.error(
            request,
            "MyAnimeList sync isn't configured. Add your own MyAnimeList "
            "Client ID and Client secret under Settings > Metadata first.",
        )
        return _integration_redirect(request)

    redirect_uri = app_helpers.build_absolute_app_url(request, reverse("mal_callback"))
    if not app_helpers.supports_oauth_redirect(redirect_uri):
        # Unlike Trakt (#681), MyAnimeList has no device-code alternative, so
        # an HTTP-only instance simply can't complete this flow.
        messages.error(
            request,
            "MyAnimeList sync needs an HTTPS-accessible callback URL. This "
            "instance is served over plain HTTP, and MyAnimeList doesn't "
            "offer a device-code alternative the way Trakt does.",
        )
        return _integration_redirect(request)

    code_verifier = mal_sync.generate_code_verifier()
    state = {
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
        "return_to": request.POST.get("next"),
    }
    state_token = secrets.token_urlsafe(32)
    pending_auth.stash_state(request, state_token, state)

    query = urlencode({
        "response_type": "code",
        "client_id": mal_sync.client_id(request.user),
        "redirect_uri": redirect_uri,
        "state": state_token,
        "code_challenge": code_verifier,
        "code_challenge_method": "plain",
    })
    return redirect(f"{mal_sync.AUTHORIZE_URL}?{query}")


@require_GET
def mal_callback(request):
    """Handle the MyAnimeList OAuth2 callback and store the connection."""
    state_data = _consume_oauth_state(request, "MyAnimeList")
    if state_data is None:
        return _integration_redirect(request)

    return_to = state_data.get("return_to")
    code = request.GET.get("code")
    if not code:
        messages.error(request, "MyAnimeList authorization failed.")
        return _integration_redirect(request, next_url=return_to)

    try:
        mal_sync.connect_account(
            user=request.user,
            code=code,
            code_verifier=state_data["code_verifier"],
            redirect_uri=state_data["redirect_uri"],
        )
    except mal_sync.MALAuthError as error:
        messages.error(request, str(error))
        return _integration_redirect(request, next_url=return_to)
    except services.ProviderAPIError:
        messages.error(
            request,
            "Couldn't reach MyAnimeList to finish connecting. Please try again.",
        )
        return _integration_redirect(request, next_url=return_to)

    messages.success(
        request,
        "Connected to MyAnimeList. Status, progress and score changes on "
        "MAL-tracked anime and manga will now sync automatically.",
    )
    return _integration_redirect(request, connected_slug="mal", next_url=return_to)


@require_POST
def mal_disconnect(request):
    """Disconnect the user's MyAnimeList account."""
    from django_celery_beat.models import PeriodicTask

    from integrations.models import MALAccount

    MALAccount.objects.filter(user=request.user).delete()
    # The schedule would otherwise keep firing against a missing account.
    PeriodicTask.objects.filter(
        _periodic_task_filter_for_user(request.user.id),
        task=tasks.MAL_FULL_SYNC_TASK_NAME,
    ).delete()
    messages.success(request, "Disconnected from MyAnimeList.")
    return _integration_redirect(request)


@require_POST
def mal_toggle(request):
    """Pause or resume pushing status updates to MyAnimeList."""
    from integrations.models import MALAccount

    updated = MALAccount.objects.filter(user=request.user).update(
        sync_enabled=request.POST.get("enabled") == "true",
    )
    if not updated:
        messages.error(request, "Connect a MyAnimeList account first.")
    return _integration_redirect(request)


@require_POST
def mal_per_item_sync_toggle(request):
    """Pause or resume the automatic push that fires when an entry is edited.

    Independent of `mal_toggle`'s overall sync_enabled: this only affects the
    per-item push, not "Sync All Now" or the scheduled full sync.
    """
    from integrations.models import MALAccount

    updated = MALAccount.objects.filter(user=request.user).update(
        per_item_sync_enabled=request.POST.get("enabled") == "true",
    )
    if not updated:
        messages.error(request, "Connect a MyAnimeList account first.")
    return _integration_redirect(request)


@require_POST
def mal_sync_filters_save(request):
    """Save which statuses (and whether a rating is required) a full sync sends."""
    mal_account = getattr(request.user, "mal_account", None)
    if mal_account is None:
        messages.error(request, "Connect a MyAnimeList account first.")
        return redirect("mal_export")

    mal_account.sync_filter_completed = request.POST.get("completed") == "on"
    mal_account.sync_filter_in_progress = request.POST.get("in_progress") == "on"
    mal_account.sync_filter_dropped = request.POST.get("dropped") == "on"
    mal_account.sync_filter_planning = request.POST.get("planning") == "on"
    mal_account.sync_filter_paused = request.POST.get("paused") == "on"
    mal_account.sync_filter_rated_only = request.POST.get("rated_only") == "on"
    mal_account.sync_ratings_enabled = request.POST.get("sync_ratings") == "on"
    mal_account.pull_higher_progress_enabled = request.POST.get("pull_higher_progress") == "on"
    mal_account.pull_ratings_enabled = request.POST.get("pull_ratings") == "on"
    mal_account.save(
        update_fields=[
            "sync_filter_completed",
            "sync_filter_in_progress",
            "sync_filter_dropped",
            "sync_filter_planning",
            "sync_filter_paused",
            "sync_filter_rated_only",
            "sync_ratings_enabled",
            "pull_higher_progress_enabled",
            "pull_ratings_enabled",
            "updated_at",
        ]
    )
    messages.success(request, "MyAnimeList sync filters saved.")
    return redirect("mal_export")


@require_POST
def mal_mapping_ignore(request):
    """Ignore or restore a grouped anime's MAL mapping issues."""
    try:
        item_id = int(request.POST["item_id"])
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"error": "Choose a valid anime."}, status=400)

    ignored = request.POST.get("ignored") == "true"
    found = mal_sync.set_mapping_ignored(request.user, item_id, ignored=ignored)
    if not found and ignored:
        return JsonResponse({"error": "Tracked anime not found."}, status=404)
    return JsonResponse({"ignored": ignored})


@require_POST
def mal_episode_mapping_save(request):
    """Persist a user-owned grouped episode or whole-season MAL override."""
    from integrations.models import ExternalReference, ExternalReferenceReviewStatus

    try:
        item_id = int(request.POST["item_id"])
        season = int(request.POST["season"])
        episode = int(request.POST["episode"])
        mal_id = int(request.POST["mal_id"])
        mal_episode = int(request.POST["mal_episode"])
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"error": "Enter valid episode and MAL numbers."}, status=400)
    if min(item_id, season, episode, mal_id, mal_episode) < 1:
        return JsonResponse({"error": "Episode and MAL numbers must be positive."}, status=400)

    from app.models import Episode, WatchState

    show = TV.objects.filter(
        user=request.user,
        item_id=item_id,
        item__library_media_type=MediaTypes.ANIME.value,
    ).select_related("item").first()
    # The same two sources grouped_sync_entries reads, so every episode it
    # reports as a mapping issue can be fixed here.
    tracked_episodes = set()
    if show is not None:
        tracked_episodes = set(
            Episode.objects.filter(
                related_season__related_tv=show,
                related_season__order_archived=False,
                item__season_number=season,
            ).values_list("item__episode_number", flat=True)
        ) | set(
            WatchState.objects.filter(
                user=request.user,
                item__media_type=MediaTypes.EPISODE.value,
                item__library_media_type=MediaTypes.ANIME.value,
                item__source=show.tracking_source,
                item__media_id=show.tracking_media_id,
                item__season_number=season,
            ).values_list("item__episode_number", flat=True)
        )
        tracked_episodes.discard(None)
    if episode not in tracked_episodes:
        return JsonResponse({"error": "Tracked anime episode not found."}, status=404)

    scope = request.POST.get("scope", "episode")
    if scope not in {"episode", "season"}:
        return JsonResponse({"error": "Unsupported mapping scope."}, status=400)
    source_episodes = [episode]
    if scope == "season":
        # The report behind the wizard can be stale, so only episodes that
        # still don't resolve get an override; working mappings are kept.
        issues = []
        try:
            mal_sync.grouped_sync_entries(request.user, tv=show, mapping_issues=issues)
        except services.ProviderAPIError:
            return JsonResponse(
                {"error": "Couldn't check the current MAL mappings. Please try again."},
                status=502,
            )
        # Counted from the episode the user aligned in the wizard, so an
        # earlier one that became unresolved since doesn't shift the rest.
        source_episodes = sorted({
            number
            for issue in issues
            for issue_season in issue.get("seasons", [])
            if issue_season["season"] == season
            for number in issue_season["episodes"]
            if number >= episode
        })
        if episode not in source_episodes:
            return JsonResponse(
                {"error": "This season is already mapped. Refresh the page."},
                status=409,
            )

    first_episode = episode
    references = [
        ExternalReference(
            user=request.user,
            integration="mal_sync",
            source_account="",
            external_namespace="grouped_anime_episode",
            external_identity=f"{item_id}:{season}:{source_episode}",
            media_type=MediaTypes.EPISODE.value,
            matched_item=show.item,
            corrected_item=show.item,
            review_status=ExternalReferenceReviewStatus.CORRECTED.value,
            episode_mapping={
                "mal_id": mal_id,
                # Offset by episode number, not list position, so an
                # untracked episode keeps its slot for when it's watched.
                "episode": mal_episode + source_episode - first_episode,
            },
            metadata={
                "series_title": show.item.title,
                "season_number": season,
                "episode_number": source_episode,
            },
        )
        for source_episode in source_episodes
    ]
    ExternalReference.objects.bulk_create(
        references,
        update_conflicts=True,
        unique_fields=[
            "user", "integration", "source_account", "external_namespace",
            "external_identity", "media_type",
        ],
        update_fields=[
            "matched_item", "corrected_item", "review_status", "episode_mapping",
            "metadata", "updated_at",
        ],
    )
    return JsonResponse({
        "saved": True,
        "mapped": len(references),
        "manual_mappings": mal_sync.manual_episode_mappings(request.user),
    })


@require_POST
def mal_episode_mapping_revert(request):
    """Delete user-created grouped episode mappings so automatic mapping resumes."""
    from integrations.models import ExternalReference, ExternalReferenceReviewStatus

    try:
        reference_ids = [int(value) for value in request.POST.getlist("reference_id")]
    except (TypeError, ValueError):
        reference_ids = []
    if not reference_ids:
        return JsonResponse({"error": "Choose a valid mapping."}, status=400)

    deleted, _ = ExternalReference.objects.filter(
        pk__in=reference_ids,
        user=request.user,
        integration="mal_sync",
        external_namespace="grouped_anime_episode",
        review_status=ExternalReferenceReviewStatus.CORRECTED.value,
    ).delete()
    if not deleted:
        return JsonResponse({"error": "Manual mapping not found."}, status=404)
    return JsonResponse({"reverted": True})


@require_GET
def mal_mapping_search(request):
    """Search MAL anime titles for the manual episode-mapping wizard."""
    query = request.GET.get("q", "").strip()
    if len(query) < MAL_MAPPING_MIN_QUERY_LENGTH:
        return JsonResponse({"error": "Enter at least three characters."}, status=400)
    try:
        from app.providers import mal as mal_provider

        with credentials.current_user_scope(request.user), services.interactive_request_scope():
            response = mal_provider.search(
                MediaTypes.ANIME.value,
                query,
                1,
                include_nsfw=True,
            )
    except services.ProviderAPIError:
        return JsonResponse({"error": "MyAnimeList search is unavailable. Please try again."}, status=502)
    return JsonResponse({"results": response.get("results", [])})


@require_GET
def mal_mapping_episodes(request):
    """Return numbered episode choices for a selected MAL anime title."""
    try:
        mal_id = int(request.GET["mal_id"])
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"error": "Choose a valid MyAnimeList title."}, status=400)
    try:
        with credentials.current_user_scope(request.user), services.interactive_request_scope():
            metadata = services.get_media_metadata(
                MediaTypes.ANIME.value,
                str(mal_id),
                Sources.MAL.value,
            )
    except services.ProviderAPIError:
        return JsonResponse({"error": "Could not load MyAnimeList episodes."}, status=502)
    try:
        episode_count = int(metadata.get("max_progress") or 0)
    except (TypeError, ValueError):
        episode_count = 0
    episode_count = max(0, min(episode_count, 10000))
    return JsonResponse({
        "title": metadata["title"],
        "image": metadata.get("image"),
        "episodes": list(range(1, episode_count + 1)),
    })


@require_POST
def mal_full_sync(request):
    """Trigger a one-off full sync of every MAL-backed anime/manga entry."""
    mal_account = getattr(request.user, "mal_account", None)
    if mal_account is None:
        messages.error(request, "Connect a MyAnimeList account first.")
    elif mal_account.connection_broken:
        messages.error(request, "Reconnect your MyAnimeList account first.")
    elif not mal_account.sync_enabled:
        messages.error(request, "Turn sync back on before running a full sync.")
    elif mal_sync.reconcile_stale_full_sync(mal_account).full_sync_is_active:
        messages.info(request, "A full MyAnimeList sync is already in progress.")
    elif request.POST.get("confirmed") != "true":
        messages.error(request, "Review the MyAnimeList changes before syncing.")
    else:
        from integrations.models import MALFullSyncStatus

        queued = type(mal_account).objects.filter(pk=mal_account.pk).exclude(
            full_sync_status__in=[MALFullSyncStatus.QUEUED, MALFullSyncStatus.RUNNING],
        ).update(
            full_sync_status=MALFullSyncStatus.QUEUED,
            full_sync_total=0,
            full_sync_processed=0,
            full_sync_succeeded=0,
            full_sync_failed=0,
            full_sync_results=[],
            full_sync_started_at=None,
            full_sync_completed_at=None,
            updated_at=timezone.now(),
        )
        if not queued:
            messages.info(request, "A full MyAnimeList sync is already in progress.")
            return _integration_redirect(request)
        # The review form always posts `selective`; without it (older pages,
        # scripts) every entry syncs as before.
        selected = (
            request.POST.getlist("selected")
            if request.POST.get("selective") == "true"
            else None
        )
        try:
            tasks.bulk_sync_mal_status.delay(
                user_id=request.user.pk,
                selected=selected,
                pull=request.POST.getlist("pull"),
                queued=True,
            )
        except BrokerOperationalError:
            # Release the claim, or every sync is refused as "in progress"
            # until it goes stale.
            type(mal_account).objects.filter(
                pk=mal_account.pk, full_sync_status=MALFullSyncStatus.QUEUED,
            ).update(
                full_sync_status=MALFullSyncStatus.FAILED,
                full_sync_completed_at=timezone.now(),
                updated_at=timezone.now(),
            )
            messages.error(
                request,
                "Could not queue the sync. Check the background worker and Redis.",
            )
            return _integration_redirect(request)
        messages.success(
            request,
            "Full sync to MyAnimeList started in the background. This can "
            "take a while for large libraries.",
        )
    return _integration_redirect(request)


@require_POST
def mal_full_sync_retry_failed(request):
    """Retry only the entries marked failed on the last full MyAnimeList sync."""
    mal_account = getattr(request.user, "mal_account", None)
    if mal_account is None:
        messages.error(request, "Connect a MyAnimeList account first.")
    elif mal_account.connection_broken:
        messages.error(request, "Reconnect your MyAnimeList account first.")
    elif not mal_account.sync_enabled:
        messages.error(request, "Turn sync back on before retrying.")
    elif mal_sync.reconcile_stale_full_sync(mal_account).full_sync_is_active:
        messages.info(request, "A MyAnimeList sync is already in progress.")
    elif not mal_sync.retryable_failures(mal_account):
        messages.error(
            request,
            "No failed MyAnimeList entries to retry. If the whole sync failed, "
            "run a full sync again.",
        )
    else:
        from integrations.models import MALFullSyncStatus

        previous_status = mal_account.full_sync_status
        queued = type(mal_account).objects.filter(pk=mal_account.pk).exclude(
            full_sync_status__in=[MALFullSyncStatus.QUEUED, MALFullSyncStatus.RUNNING],
        ).update(
            full_sync_status=MALFullSyncStatus.QUEUED,
            updated_at=timezone.now(),
        )
        if not queued:
            messages.info(request, "A MyAnimeList sync is already in progress.")
            return _integration_redirect(request)
        try:
            tasks.retry_failed_mal_status.delay(user_id=request.user.pk, queued=True)
        except BrokerOperationalError:
            type(mal_account).objects.filter(
                pk=mal_account.pk, full_sync_status=MALFullSyncStatus.QUEUED,
            ).update(full_sync_status=previous_status, updated_at=timezone.now())
            messages.error(
                request,
                "Could not queue the retry. Check the background worker and Redis.",
            )
            return _integration_redirect(request)
        messages.success(
            request,
            "Retrying failed MyAnimeList entries in the background.",
        )
    return _integration_redirect(request)


@require_GET
def mal_full_sync_status(request):
    """Return durable progress and outcomes for the latest manual MAL sync."""
    mal_account = getattr(request.user, "mal_account", None)
    if mal_account is None:
        return JsonResponse({"error": "Connect a MyAnimeList account first."}, status=404)

    mal_account = mal_sync.reconcile_stale_full_sync(mal_account)
    return JsonResponse(mal_sync.full_sync_report(mal_account))


@require_http_methods(["GET", "POST"])
def mal_full_sync_preview(request):
    """Queue or poll a user-bound, read-only MAL preview."""
    mal_account = getattr(request.user, "mal_account", None)
    if mal_account is None:
        return JsonResponse(
            {"error": "Connect a MyAnimeList account first."}, status=400
        )
    if mal_account.connection_broken:
        return JsonResponse(
            {"error": "Reconnect your MyAnimeList account first."}, status=400
        )
    if not mal_account.sync_enabled:
        return JsonResponse(
            {"error": "Turn sync back on before running a full sync."}, status=400
        )

    salt = "mal-sync-preview"
    if request.method == "POST":
        try:
            job = tasks.preview_mal_sync.delay(request.user.pk)
        except BrokerOperationalError:
            return JsonResponse({"error": "Could not queue preview. Check the background worker and Redis."}, status=503)
        token = signing.dumps(
            {"user_id": request.user.pk, "task_id": job.id}, salt=salt,
        )
        return JsonResponse({"pending": True, "token": token}, status=202)

    try:
        payload = signing.loads(request.GET.get("token", ""), salt=salt, max_age=3600)
    except signing.BadSignature:
        return JsonResponse({"error": "Preview expired. Start a new preview."}, status=400)
    if payload["user_id"] != request.user.pk:
        return JsonResponse({"error": "Preview not found."}, status=404)
    job = tasks.preview_mal_sync.AsyncResult(payload["task_id"])
    if not job.ready():
        info = job.info if isinstance(job.info, dict) else {}
        return JsonResponse({
            "pending": True,
            "progress": info.get("percent", 0),
            "message": info.get(
                "message",
                "Waiting for the background worker to finish its current task"
                if job.state == "PENDING" else "Preparing preview",
            ),
        }, status=202)
    if job.failed():
        return JsonResponse({"error": "Preview worker failed. Check the worker logs."}, status=502)
    result = job.result
    # The worker can't reverse() URLs (its URLconf is empty), so pages are linked here.
    for entry in result.get("changes", []):
        entry["url"] = media_url(entry.pop("link"))
    return JsonResponse(result, status=502 if "error" in result else 200)


@require_POST
def mal_export_schedule_save(request):
    """Create or update the user's recurring full sync to MyAnimeList."""
    import datetime as dt

    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    mal_account = getattr(request.user, "mal_account", None)
    if mal_account is None or not mal_account.is_connected:
        messages.error(request, "Connect a MyAnimeList account first.")
        return redirect("mal_export")

    frequency = request.POST.get("frequency", "daily")
    export_time = request.POST.get("time", "03:00")

    try:
        parsed_time = dt.datetime.strptime(export_time, "%H:%M").time()  # noqa: DTZ007  # date-only value; no timezone applies
    except ValueError:
        messages.error(request, "Invalid schedule time.")
        return redirect("mal_export")

    if frequency == "daily":
        day_of_week = "*"
    elif frequency == "2days":
        day_of_week = "*/2"
    elif frequency == "weekly":
        day_of_week = "0"  # Sunday
    else:
        messages.error(request, "Invalid schedule frequency.")
        return redirect("mal_export")

    crontab, _ = CrontabSchedule.objects.get_or_create(
        hour=parsed_time.hour,
        minute=parsed_time.minute,
        day_of_week=day_of_week,
        timezone=timezone.get_default_timezone(),
    )

    task_name = f"Scheduled export to MyAnimeList for {request.user.username}"
    existing_task = PeriodicTask.objects.filter(
        _periodic_task_filter_for_user(request.user.id),
        task=tasks.MAL_FULL_SYNC_TASK_NAME,
    ).first()

    if existing_task:
        existing_task.name = task_name
        existing_task.crontab = crontab
        existing_task.kwargs = json.dumps({"user_id": request.user.id})
        existing_task.enabled = True
        existing_task.start_time = timezone.now()
        existing_task.save(
            update_fields=["name", "crontab", "kwargs", "enabled", "start_time"],
        )
    else:
        PeriodicTask.objects.create(
            name=task_name,
            task=tasks.MAL_FULL_SYNC_TASK_NAME,
            crontab=crontab,
            kwargs=json.dumps({"user_id": request.user.id}),
            start_time=timezone.now(),
            enabled=True,
        )

    messages.success(request, "MyAnimeList export schedule saved.")
    return redirect("mal_export")


@require_POST
def mal_export_schedule_delete(request):
    """Delete the user's recurring full sync to MyAnimeList."""
    from django_celery_beat.models import PeriodicTask

    deleted, _ = PeriodicTask.objects.filter(
        _periodic_task_filter_for_user(request.user.id),
        task=tasks.MAL_FULL_SYNC_TASK_NAME,
    ).delete()
    if deleted:
        messages.success(request, "MyAnimeList export schedule deleted.")
    else:
        messages.error(request, "MyAnimeList export schedule not found.")
    return redirect("mal_export")
