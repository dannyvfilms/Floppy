"""Safe, scoped view models for the fully React-owned AniList provider region."""

from datetime import timedelta

from celery import states
from django.db.models import Q
from django.middleware.csrf import get_token
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django_celery_beat.models import PeriodicTask
from django_celery_results.models import TaskResult

from app.log_safety import redact_secrets
from app.providers import credentials
from app.templatetags.app_tags import media_type_readable
from integrations.models import ImportRun
from users import helpers, views
from users.templatetags.user_tags import (
    SOURCES_CONFIG,
    translate_import_summary,
    user_datetime_format,
)

ACTIVITY_PAGE_SIZE = 50
MAX_ACTIVITY_PAGES = 1000


def directory_page(context):
    """Expose only directory presentation and filter state, never account data."""
    return {
        "url": reverse("providers"), "setupUrl": reverse("onboarding_restart"),
        "filters": {"q": context["query"], "capability": context["capability"], "media": context["media"]},
        "capabilities": [{"value": row["key"], "label": _(row["label"])} for row in context["capability_options"]],
        "media": [{"value": row["key"], "label": _(row["label"])} for row in context["media_options"]],
        "items": [{
            "slug": item["slug"], "title": item["label"], "description": item["card_description"],
            "logo": SOURCES_CONFIG.get(item.get("logo_slug") or item["slug"], {}).get("logo"),
            "url": reverse("provider_detail", args=[item["slug"]]) +
                ("?" + urlencode({"tab": context["capability"]}) if context["capability"] else ""),
            "attention": _(item["state"]["summary"]) if item["state"]["attention"] else "",
            "status": {
                "label": _(item["state"]["connection"]),
                "tone": item["state"]["connection_tone"],
            } if context["capability"] == "connection" else None,
            "openLabel": _("Open %(name)s") % {"name": item["label"]},
        } for item in context["providers"]],
        "labels": {text: _(text) for text in (
            "Providers", "Run guided setup", "Find services and their available settings.",
            "Search providers", "Search providers...", "Filter by capability", "Filter by media type",
            "No providers match these filters.", "Could not load providers. Try again.", "Retry",
        )},
    }


def _schedules(user):
    """Read enabled AniList schedules without exposing their stored OAuth tokens."""
    candidates = PeriodicTask.objects.filter(
        task="Import from AniList", enabled=True, one_off=False,
        kwargs__regex=rf"[\"']user_id[\"']:\s*{user.pk}\s*[,}}]",
    ).select_related("crontab", "interval")
    return [task for task in candidates if helpers.task_kwargs_belong_to_user(task.kwargs, user.pk)]


def _latest_import(user):
    """Include old imports and newly queued tasks, rather than only recent results."""
    run = ImportRun.objects.filter(user=user, source="anilist").only(
        "id", "task_id", "status", "started_at", "finished_at", "created_count", "updated_count",
    ).order_by("-started_at", "-id").first()
    candidates = TaskResult.objects.filter(task_name="Import from AniList",
        task_kwargs__regex=rf"[\"']user_id[\"']:\s*{user.pk}\s*[,}}]",
    ).exclude(
        Q(status=states.PENDING) & Q(date_created__lt=timezone.now() - timedelta(minutes=30)),
    ).only("task_id", "task_kwargs", "status", "date_created").order_by("-date_created", "-id")
    task = next((row for row in candidates.iterator() if helpers.task_kwargs_belong_to_user(row.task_kwargs, user.pk)), None)
    if task and (not run or (task.task_id != run.task_id and task.date_created > run.started_at)):
        return {"status": _status(task.status), "date": user_datetime_format(task.date_created, user)}
    if run:
        return {"status": _status(run.status), "date": user_datetime_format(run.started_at, user)}
    return None


def _status(value):
    """Localize the existing task/run vocabulary at the server boundary."""
    return {
        "SUCCESS": _("Success"), "STARTED": _("Started"), "PENDING": _("Pending"),
        "FAILURE": _("Failed"), "REVOKED": _("Cancelled"), "running": _("Running"),
        "completed": _("Completed"), "failed": _("Failed"), "cancelled": _("Cancelled"),
    }.get(value, value)


def anilist_overview(user):
    """Use resolved credential tiers, enabled schedules and persisted import activity."""
    configured = credentials.is_configured("anilist", user)
    sources = {credentials.source_of("anilist", field.name, user) for field in credentials.REGISTRY["anilist"].fields}
    source = "none"
    if configured:
        source = "personal" if credentials.SOURCE_USER in sources else "instance"
    schedules = list(_schedules(user))
    next_runs = [info["next_run"] for task in schedules if (info := helpers.get_next_run_info(task))]
    return {
        "connection": source,
        "instanceFallback": source == "personal" and bool(sources - {credentials.SOURCE_USER}),
        "scheduleCount": len(schedules),
        "scheduleSummary": ngettext("%(count)s enabled schedule", "%(count)s enabled schedules", len(schedules)) % {"count": len(schedules)},
        "nextImport": user_datetime_format(min(next_runs), user) if next_runs else "",
        "latestImport": _latest_import(user),
    }


def anilist_activity(user, page=1):
    """Serialize existing activity controls with owned rows and bounded history pages."""
    activity = user.get_import_tasks(sources={"anilist"}, result_limit=ACTIVITY_PAGE_SIZE + 1,
                                   result_offset=(page - 1) * ACTIVITY_PAGE_SIZE)
    runs = list(ImportRun.objects.filter(user=user, source="anilist").defer(
        "prepared_state", "terminal_error",
    ).order_by("-started_at", "-id")[:10])
    active_tasks = TaskResult.objects.filter(task_name="Import from AniList", status__in=[states.PENDING, states.STARTED],
        task_kwargs__regex=rf"[\"']user_id[\"']:\s*{user.pk}\s*[,}}]",
    ).exclude(Q(status=states.PENDING) & Q(date_created__lt=timezone.now() - timedelta(minutes=30)))
    active = ImportRun.objects.filter(user=user, source="anilist", status="running").exists() or any(
        helpers.task_kwargs_belong_to_user(kwargs, user.pk) for kwargs in active_tasks.values_list("task_kwargs", flat=True).iterator()
    )
    return {
        "page": page,
        "hasMore": len(activity["results"]) > ACTIVITY_PAGE_SIZE and page < MAX_ACTIVITY_PAGES,
        "active": active,
        "schedules": [{
            "id": row["task"].pk, "name": row["task"].name, "schedule": _(row["schedule"]),
            "username": row["username"], "mode": _(row["mode"]),
            "lastRun": user_datetime_format(row["last_run"], user),
            "nextRun": user_datetime_format(row["next_run"], user),
            "action": reverse("delete_import_schedule"),
        } for row in activity["schedules"]],
        "results": [{
            "id": row["task_id"], "status": row["status"], "statusLabel": _status(row["status"]),
            "date": user_datetime_format(row["date"], user),
            "summary": redact_secrets(str(translate_import_summary(row["summary"]) or "")),
            "errors": redact_secrets(str(row["errors"] or "")),
            "current": row.get("progress_current"), "total": row.get("progress_total"),
            "progressLabel": row.get("progress_label"), "percent": row.get("progress_percent"),
            "cancelAction": reverse("cancel_pending_import", args=[row["task_id"]]) if row["status"] == states.PENDING else "",
        } for row in activity["results"][:ACTIVITY_PAGE_SIZE]],
        "runs": [{
            "id": run.pk, "status": run.status, "statusLabel": _status(run.status),
            "date": user_datetime_format(run.started_at, user), "created": run.created_count,
            "updated": run.updated_count, "skipped": run.skipped_count, "failed": run.failed_count,
            "remaining": run.remaining_estimate,
            "action": reverse("cancel_import_run" if run.status == "running" else "rollback_import_run", args=[run.pk]),
        } for run in runs],
        "cleanup": [{
            "mediaType": row["media_type"], "mediaLabel": str(media_type_readable(row["media_type"])), "count": row["count"],
            "action": reverse("bulk_delete_by_import_source", args=[row["media_type"], "anilist"]),
        } for row in views._import_source_media_summary(user, sources={"anilist"})],
    }


def anilist_page(request, provider, tab, credential_context=None):
    """Build safe browser props. Saved credential values/previews are never serialized."""
    user = request.user
    base = reverse("provider_detail", args=["anilist"])
    page = {
        "provider": {"label": provider["label"], "description": provider["description"],
                     "logo": static("img/anilist-logo.svg"), "media": provider["media_labels"]},
        "tab": tab,
        "tabs": [{"key": key, "label": _(key.title()), "url": f"{base}?tab={key}"} for key in provider["tabs"]],
        "urls": {key: f"{base}?tab={key}" for key in provider["tabs"]},
        "activityUrl": f"{base}?tab=activity&format=json",
        "csrf": get_token(request), "next": request.get_full_path(),
        "labels": _labels(),
    }
    if request.GET.get("onboarding"):
        page["onboardingUrl"] = reverse("onboarding_service_setup" if request.GET.get("setup_flow") == "import" else "onboarding_integration_setup")
    if tab == "overview":
        page["overview"] = anilist_overview(user)
    elif tab == "connection":
        context = credential_context
        provider = context["metadata_provider"]
        page["credentials"] = {
            "editable": context["can_edit_instance"] and not provider["locked"],
            "canClear": context["can_edit_instance"] and provider["has_instance_value"],
            "getKeyUrl": provider["docs_url"],
            "fields": [{
                "name": field["name"], "label": _(field["label"]), "secret": field["secret"],
                "disabled": field["locked"] or not context["can_edit_instance"],
                "environment": field["locked"], "setting": field["setting"],
                "stored": field["has_instance_value"], "personalStored": field["has_personal_value"],
            } for field in provider["fields"]],
            "saveUrl": reverse("save_provider_credential", args=["anilist"]),
            "clearUrl": reverse("clear_provider_credential", args=["anilist"]),
            "personalUrl": reverse("save_personal_credential", args=["anilist"]),
            "superuser": user.is_superuser, "promoteCommand": context.get("promote_command", ""),
            "hasSuperuser": context.get("instance_has_superuser", True),
            "inContainer": context.get("in_container", False),
        }
    elif tab == "import":
        configured = credentials.is_configured("anilist", user)
        page["imports"] = {
            "frequency": user.import_frequency, "time": str(user.import_time)[:5],
            "mode": user.import_mode, "configured": configured,
            "saveUrl": reverse("save_import_settings"),
            "publicUrl": reverse("import_anilist_public"), "privateUrl": reverse("import_anilist_oauth") if configured else "",
        }
    return page


def _labels():
    """Mark presentation text for translation before it reaches shared components."""
    return {
        "Connection": _("Connection"),
        "Automatic import": _("Automatic import"),
        "Last active import": _("Last active import"),
        "Active": _("Active"),
        "Inactive": _("Inactive"),
        "Personal credentials active": _("Personal credentials active"),
        "Instance credentials active": _("Instance credentials active"),
        "No credentials active": _("No credentials active"),
        "Uses instance fallback for fields without a personal value.": _("Uses instance fallback for fields without a personal value."),
        "Public username imports do not require provider credentials.": _("Public username imports do not require provider credentials."),
        "No automatic imports configured": _("No automatic imports configured"),
        "Next import": _("Next import"),
        "No imports yet": _("No imports yet"),
        "Provider credentials": _("Provider credentials"),
        "Get a key from AniList": _("Get a key from AniList"),
        "Instance credentials": _("Instance credentials"),
        "Personal credentials": _("Personal credentials"),
        "Editable": _("Editable"),
        "Read-only": _("Read-only"),
        "Read-only: explain instance credential access": _("Read-only: explain instance credential access"),
        "Instance credential access": _("Instance credential access"),
        "Close": _("Close"),
        "These credentials are shared across the instance.": _("These credentials are shared across the instance."),
        "Environment": _("Environment"),
        "Stored": _("Stored"),
        "Not set": _("Not set"),
        "Save": _("Save"),
        "Remove stored credentials": _("Remove stored credentials"),
        "Your": _("Your"),
        "Save personal key": _("Save personal key"),
        "Your personal key is used for your own requests instead of the instance key. Background jobs keep using the instance key.": _("Your personal key is used for your own requests instead of the instance key. Background jobs keep using the instance key."),
        "Leave a field blank to keep the current fallback.": _("Leave a field blank to keep the current fallback."),
        "Saved — enter a new value to replace": _("Saved — enter a new value to replace"),
        "Only superusers can change instance-wide credentials. Values set in the environment are read-only here and take precedence over stored credentials.": _("Only superusers can change instance-wide credentials. Values set in the environment are read-only here and take precedence over stored credentials."),
        "You are not a superuser": _("You are not a superuser"),
        "Ask an administrator, or promote your own account": _("Ask an administrator, or promote your own account"),
        "This instance has no superuser yet": _("This instance has no superuser yet"),
        "Instance-wide keys can only be changed by a superuser. You can still add your own personal key.": _("Instance-wide keys can only be changed by a superuser. You can still add your own personal key."),
        "Run this on the host running the container:": _("Run this on the host running the container:"),
        "Run this where Floppy is installed:": _("Run this where Floppy is installed:"),
        "Then sign out and back in. Add --list to see accounts first.": _("Then sign out and back in. Add --list to see accounts first."),
        "Import settings": _("Import settings"),
        "Import preferences": _("Import preferences"),
        "Import options": _("Import options"),
        "Import Frequency": _("Import Frequency"),
        "Import Time": _("Import Time"),
        "Import Mode": _("Import Mode"),
        "One Time Import": _("One Time Import"),
        "Every Day": _("Every Day"),
        "Every 2 Days": _("Every 2 Days"),
        "Only Sync New Items": _("Only Sync New Items"),
        "Sync New Items and Overwrite Existing": _("Sync New Items and Overwrite Existing"),
        "Import Watchlist Data Only": _("Import Watchlist Data Only"),
        "Update Collection Metadata Only": _("Update Collection Metadata Only"),
        "Saving…": _("Saving…"),
        "Saved": _("Saved"),
        "Could not save preferences. Try again.": _("Could not save preferences. Try again."),
        "Retry": _("Retry"),
        "Import anime and manga from your AniList profile.": _("Import anime and manga from your AniList profile."),
        "Import private profile (requires authentication)": _("Import private profile (requires authentication)"),
        "Public": _("Public"),
        "Private": _("Private"),
        "Public username": _("Public username"),
        "Public AniList username": _("Public AniList username"),
        "Import": _("Import"),
        "Connect with AniList & Import": _("Connect with AniList & Import"),
        "Private imports require provider credentials.": _("Private imports require provider credentials."),
        "Configure Connection": _("Configure Connection"),
        "This import mode is not supported by AniList.": _("This import mode is not supported by AniList."),
        "Continue Guided Setup": _("Continue Guided Setup"),
        "Active Periodic Imports": _("Active Periodic Imports"),
        "Import History": _("Import History"),
        "Recent Import Runs": _("Recent Import Runs"),
        "Imported Media by Source": _("Imported Media by Source"),
        "Loading import activity…": _("Loading import activity…"),
        "Could not load import activity.": _("Could not load import activity."),
        "No periodic imports configured": _("No periodic imports configured"),
        "Showing import activity from the last 7 days.": _("Showing import activity from the last 7 days."),
        "No imports in the last 7 days": _("No imports in the last 7 days"),
        "Username": _("Username"),
        "Mode": _("Mode"),
        "Last Import": _("Last Import"),
        "Next Import": _("Next Import"),
        "Remove schedule": _("Remove schedule"),
        "Show details": _("Show details"),
        "Hide details": _("Hide details"),
        "Show traceback": _("Show traceback"),
        "Hide traceback": _("Hide traceback"),
        "Copy": _("Copy"),
        "Copied!": _("Copied!"),
        "Cancel import": _("Cancel import"),
        "Cancel this import?": _("Cancel this import?"),
        "Undo this import": _("Undo this import"),
        "Remove the items this import created? This cannot be undone.": _("Remove the items this import created? This cannot be undone."),
        "Created": _("Created"),
        "Updated": _("Updated"),
        "Skipped": _("Skipped"),
        "Failed": _("Failed"),
        "Remaining": _("Remaining"),
        "Delete all": _("Delete all"),
        "Previous": _("Previous"),
        "Next": _("Next"),
        "Permanently delete all items of this media type imported from AniList? This cannot be undone.": _("Permanently delete all items of this media type imported from AniList? This cannot be undone."),
        "Permanently delete everything of a media type imported from this source.": _("Permanently delete everything of a media type imported from this source."),
        "Could not copy details.": _("Could not copy details."),
        "Media types": _("Media types"),
        "Provider sections": _("Provider sections"),
    }
