"""Views for the MDBList import flow.

Covers: connecting an MDBList API key, disconnecting, triggering a manual
sync, and importing a single public list by URL or ID. Connecting also
registers a per-user recurring sync via django-celery-beat.
"""

import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from integrations.imports import helpers as import_helpers
from integrations.models import MDBListAccount
from lists import tasks as list_tasks
from lists.imports import mdblist as mdblist_imports

logger = logging.getLogger(__name__)

MDBLIST_SYNC_TASK_NAME = "Import MDBList Lists"

FREQUENCY_CRONTABS = {
    "6h": {"minute": "0", "hour": "*/6"},
    "12h": {"minute": "0", "hour": "*/12"},
    "24h": {"minute": "0", "hour": "3"},
    "weekly": {"minute": "0", "hour": "3", "day_of_week": "1"},
}


def _periodic_task_filter_for_user(user_id):
    """Match a user's periodic task regardless of JSON spacing/quotes."""
    return Q(kwargs__contains=f'"user_id": {user_id},') | Q(
        kwargs__contains=f'"user_id": {user_id}' + "}",
    )


def _ensure_mdblist_schedule(user, account):
    """Create or replace the per-user recurring MDBList sync task."""
    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    crontab_kwargs = FREQUENCY_CRONTABS.get(
        account.sync_frequency,
        FREQUENCY_CRONTABS["24h"],
    )
    crontab, _ = CrontabSchedule.objects.get_or_create(
        minute=crontab_kwargs.get("minute", "0"),
        hour=crontab_kwargs.get("hour", "3"),
        day_of_week=crontab_kwargs.get("day_of_week", "*"),
        day_of_month="*",
        month_of_year="*",
        timezone=timezone.get_default_timezone(),
    )
    _remove_mdblist_schedule(user)
    return PeriodicTask.objects.create(
        name=(
            f"{MDBLIST_SYNC_TASK_NAME} for {user.username} "
            f"({account.get_sync_frequency_display().lower()})"
        ),
        task=MDBLIST_SYNC_TASK_NAME,
        crontab=crontab,
        kwargs=json.dumps({"user_id": user.id}),
        enabled=True,
    )


def _remove_mdblist_schedule(user):
    """Delete any per-user recurring MDBList sync tasks."""
    from django_celery_beat.models import PeriodicTask

    return PeriodicTask.objects.filter(
        _periodic_task_filter_for_user(user.id),
        task=MDBLIST_SYNC_TASK_NAME,
    ).delete()


@login_required
@require_POST
def mdblist_connect(request):
    """Store the MDBList API key and start the initial import."""
    api_key = request.POST.get("api_key", "").strip()
    sync_frequency = request.POST.get("sync_frequency", "24h")
    if sync_frequency not in FREQUENCY_CRONTABS:
        sync_frequency = "24h"

    if not api_key:
        messages.error(request, "An MDBList API key is required.")
        return redirect("lists")

    try:
        mdblist_imports.validate_api_key(api_key)
    except import_helpers.MediaImportError:
        messages.error(
            request,
            "Could not validate the MDBList API key. Check it and try again.",
        )
        return redirect("lists")

    account, _ = MDBListAccount.objects.update_or_create(
        user=request.user,
        defaults={
            "api_key": import_helpers.encrypt(api_key),
            "sync_frequency": sync_frequency,
            "connection_broken": False,
            "last_error_message": "",
        },
    )
    _ensure_mdblist_schedule(request.user, account)
    list_tasks.import_mdblist_lists_task.delay(request.user.id)
    messages.success(
        request,
        "MDBList connected. Your lists are being imported in the background.",
    )
    return redirect("lists")


@login_required
@require_POST
def mdblist_disconnect(request):
    """Remove the MDBList account and its recurring sync."""
    _remove_mdblist_schedule(request.user)
    MDBListAccount.objects.filter(user=request.user).delete()
    messages.success(
        request,
        "MDBList disconnected. Imported lists were kept but will no longer sync.",
    )
    return redirect("lists")


@login_required
@require_POST
def mdblist_sync_now(request):
    """Queue an immediate MDBList sync."""
    account = MDBListAccount.objects.filter(user=request.user).first()
    if not account:
        messages.error(request, "Connect your MDBList account first.")
        return redirect("lists")

    if account.connection_broken:
        account.connection_broken = False
        account.last_error_message = ""
        account.save(update_fields=["connection_broken", "last_error_message"])
    _ensure_mdblist_schedule(request.user, account)
    list_tasks.import_mdblist_lists_task.delay(request.user.id)
    messages.info(request, "MDBList sync started in the background.")
    return redirect("lists")


@login_required
@require_POST
def mdblist_import_url(request):
    """Import a single public MDBList list by URL or ID."""
    reference = request.POST.get("list_reference", "").strip()
    if not reference:
        messages.error(request, "Provide an MDBList list URL or ID.")
        return redirect("lists")

    if not MDBListAccount.objects.filter(user=request.user).exists():
        messages.error(request, "Connect your MDBList account first.")
        return redirect("lists")

    list_tasks.import_mdblist_list_by_reference_task.delay(request.user.id, reference)
    messages.info(request, "MDBList list import started in the background.")
    return redirect("lists")
