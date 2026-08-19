"""First-run setup wizard: choose media types, choose services, connect them.

Most steps here compose existing settings surfaces rather than
reimplementing them:
- media type selection reuses ``apply_media_type_preferences`` (the same
  logic backing Settings > Sidebar) and the
  ``users/components/media_type_picker.html`` partial.
- connecting a service renders one of a small set of generic connect forms
  inline (``users/onboarding/components/connect_*.html``), posting straight
  to the same per-source connect/import views Settings > Import uses, with
  a ``next`` field bringing the user back here on success. A source with
  ``inline_supported=False`` (currently just Storyteller's device-code
  flow) instead falls back to the old ``?open=<slug>`` deep link into
  Settings > Import.
- import progress shows a compact status chip per source connected this
  session (from ``ImportRun``), not the full account-wide Settings > Import
  activity panel.
- for a connected source with a separate realtime integration (currently
  just Plex's webhook), one more step renders that integration's setup
  instructions inline the same way (``users/onboarding/components/
  integration_*.html``); sources without one never show this step.

Wizard state lives on a handful of ``User`` fields
(``onboarding_status``/``onboarding_step``/``onboarding_selected_sources``/
``onboarding_skipped_sources``/``onboarding_connected_sources``/
``onboarding_skipped_integrations``); see ``users/models.py``.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods

from app.models import MediaTypes
from integrations.models import ImportRun
from integrations.onboarding import get_source, sources_for_media_type
from users.views import SIDEBAR_MEDIA_TYPES, apply_media_type_preferences

STEP_URL_NAMES = {
    "media_types": "onboarding_media_types",
    "services": "onboarding_services",
    "services_summary": "onboarding_services_summary",
    "service_setup": "onboarding_service_setup",
    "import_status": "onboarding_import_status",
    "integration_setup": "onboarding_integration_setup",
    "done": "home",
}

# TV Seasons isn't a real choice for a new user ("do you want to track TV
# Shows?" already implies seasons); Settings > Sidebar still offers it.
ONBOARDING_MEDIA_TYPES = [
    mt for mt in SIDEBAR_MEDIA_TYPES if mt != MediaTypes.SEASON.value
]

STEP_LABELS = [
    ("media_types", "Media Types"),
    ("services", "Services"),
    ("services_summary", "Summary"),
    ("service_setup", "Connect"),
    ("integration_setup", "Scrobbling"),
    ("import_status", "Import"),
]


def _wizard_progress(active_step):
    """Context for the shared step-progress header in ``onboarding/_layout.html``."""
    step_order = [slug for slug, _ in STEP_LABELS]
    active_index = step_order.index(active_step) if active_step in step_order else 0
    return {
        "onboarding_steps": STEP_LABELS,
        "onboarding_active_step": active_step,
        "onboarding_completed_steps": step_order[:active_index],
    }

# Order in which enabled media types are walked during the "services" step.
_MEDIA_TYPE_WALK_ORDER = [
    mt for mt in MediaTypes.values if mt not in (MediaTypes.EPISODE.value, MediaTypes.SEASON.value)
]


def _blocked_for_demo(request):
    """Demo accounts don't get a persisted wizard; send them straight home."""
    if request.user.is_demo:
        messages.info(request, "Guided setup isn't available for demo accounts.")
        return redirect("home")
    return None


def _enter_in_progress(user):
    if user.onboarding_status != "completed":
        user.onboarding_status = "in_progress"


def _step_redirect(step):
    if step == "services":
        return redirect(reverse("onboarding_services", args=[0]))
    return redirect(STEP_URL_NAMES[step])


def _advance(user, request, step, fields=()):
    user.onboarding_step = step
    _enter_in_progress(user)
    user.save(update_fields=[*fields, "onboarding_step", "onboarding_status"])
    return _step_redirect(step)


def _finish(user):
    user.onboarding_status = "completed"
    user.onboarding_step = "done"
    user.save(update_fields=["onboarding_status", "onboarding_step"])
    return redirect("home")


@require_http_methods(["GET", "POST"])
def onboarding_media_types(request):
    """Step 1: choose which media types to track."""
    blocked = _blocked_for_demo(request)
    if blocked:
        return blocked

    if request.method == "POST":
        if request.POST.get("action") == "skip":
            return _finish(request.user)

        selected_media_types = request.POST.getlist("media_types_checkboxes")
        if not selected_media_types:
            messages.error(request, "Choose at least one media type to continue.")
            return redirect("onboarding_media_types")

        fields = apply_media_type_preferences(
            request.user,
            selected_media_types,
            request.POST.get("sidebar_media_type_order", "").split(","),
            media_types=ONBOARDING_MEDIA_TYPES,
        )
        return _advance(request.user, request, "services", fields)

    preferred_order = request.user.sidebar_media_type_order or []
    media_types = [mt for mt in preferred_order if mt in ONBOARDING_MEDIA_TYPES]
    media_types += [mt for mt in ONBOARDING_MEDIA_TYPES if mt not in media_types]
    return render(
        request,
        "users/onboarding/media_types.html",
        {"media_types": media_types, **_wizard_progress("media_types")},
    )


def _walk_media_types(user):
    """Return enabled media types (excluding season/episode) in wizard walk order."""
    enabled = set(user.get_enabled_media_types())
    return [mt for mt in _MEDIA_TYPE_WALK_ORDER if mt in enabled]


@require_http_methods(["GET", "POST"])
def onboarding_services(request, index=0):
    """Step 2: for each enabled media type, ask which apps the user uses."""
    blocked = _blocked_for_demo(request)
    if blocked:
        return blocked

    walk = _walk_media_types(request.user)
    if not walk:
        return _advance(request.user, request, "services_summary")

    index = max(0, min(index, len(walk) - 1))
    current_media_type = walk[index]
    candidates = sources_for_media_type(current_media_type)

    if request.method == "POST":
        chosen = set(request.user.onboarding_selected_sources)
        candidate_slugs = {source.slug for source in candidates}
        chosen -= candidate_slugs
        chosen |= set(request.POST.getlist("sources")) & candidate_slugs

        request.user.onboarding_selected_sources = sorted(chosen)
        if index + 1 < len(walk):
            request.user.save(update_fields=["onboarding_selected_sources"])
            return redirect("onboarding_services", index=index + 1)
        return _advance(
            request.user, request, "services_summary", ["onboarding_selected_sources"]
        )

    already_selected = set(request.user.onboarding_selected_sources)
    return render(
        request,
        "users/onboarding/services.html",
        {
            "current_media_type": current_media_type,
            "candidates": candidates,
            "already_selected": already_selected,
            "step_number": index + 1,
            "step_total": len(walk),
            "is_last_step": index + 1 == len(walk),
            **_wizard_progress("services"),
        },
    )


@require_http_methods(["GET", "POST"])
def onboarding_services_summary(request):
    """Step 3: summarize what's about to be tracked, offer now/later."""
    blocked = _blocked_for_demo(request)
    if blocked:
        return blocked

    if request.method == "POST":
        if request.POST.get("action") == "later":
            return _finish(request.user)
        return _advance(request.user, request, "service_setup")

    selected_sources = [
        source
        for slug in request.user.onboarding_selected_sources
        if (source := get_source(slug))
    ]
    return render(
        request,
        "users/onboarding/services_summary.html",
        {
            "media_type_count": len(_walk_media_types(request.user)),
            "selected_sources": selected_sources,
            **_wizard_progress("services_summary"),
        },
    )


def _remaining_sources(user):
    """Return selected sources that still need a connect/import pass."""
    skipped = set(user.onboarding_skipped_sources)
    connected = set(user.onboarding_connected_sources)
    remaining = []
    for slug in user.onboarding_selected_sources:
        source = get_source(slug)
        if not source or slug in skipped:
            continue
        if source.is_connected(user) or slug in connected:
            continue
        remaining.append(source)
    return remaining


@require_GET
def onboarding_service_setup(request):
    """Step 4: connect the selected services one at a time.

    Recomputes the remaining queue on every visit (selected minus already
    connected minus explicitly skipped) instead of tracking a position, so
    resuming or connecting a shared source from elsewhere always shows the
    correct next step with no risk of a stale index.
    """
    blocked = _blocked_for_demo(request)
    if blocked:
        return blocked

    remaining = _remaining_sources(request.user)
    if not remaining:
        return _advance(request.user, request, "integration_setup")

    current = remaining[0]
    return render(
        request,
        "users/onboarding/service_setup.html",
        {
            "current_source": current,
            "remaining_count": len(remaining),
            "trakt_configured": bool(settings.TRAKT_API and settings.TRAKT_API_SECRET),
            **_wizard_progress("service_setup"),
        },
    )


@require_http_methods(["POST"])
def onboarding_skip_service(request, slug):
    """Skip a queued source without losing progress on the others."""
    blocked = _blocked_for_demo(request)
    if blocked:
        return blocked

    skipped = set(request.user.onboarding_skipped_sources)
    skipped.add(slug)
    request.user.onboarding_skipped_sources = sorted(skipped)
    request.user.save(update_fields=["onboarding_skipped_sources"])
    return redirect("onboarding_service_setup")


@require_http_methods(["GET", "POST"])
def onboarding_import_status(request):
    """Step 6: show import progress/history for connected services, then continue."""
    blocked = _blocked_for_demo(request)
    if blocked:
        return blocked

    if request.method == "POST":
        return _finish(request.user)

    connected_slugs = set(request.user.onboarding_connected_sources)
    connected_sources = [
        source
        for slug in request.user.onboarding_selected_sources
        if (source := get_source(slug))
        and (source.is_connected(request.user) or slug in connected_slugs)
    ]

    latest_run_by_source = {}
    if connected_sources:
        runs = ImportRun.objects.filter(
            user=request.user,
            source__in=[source.slug for source in connected_sources],
        ).order_by("source", "-started_at")
        for run in runs:
            latest_run_by_source.setdefault(run.source, run)

    connected_sources_with_status = [
        {"source": source, "run": latest_run_by_source.get(source.slug)}
        for source in connected_sources
    ]

    return render(
        request,
        "users/onboarding/import_status.html",
        {
            "connected_sources": connected_sources_with_status,
            **_wizard_progress("import_status"),
        },
    )


def _remaining_integrations(user):
    """Return connected sources with an unconfigured realtime integration.

    Automatically empty (and so automatically skipped) unless a connected
    source actually has a companion integration — most sources are import-
    only and never appear here.
    """
    skipped = set(user.onboarding_skipped_integrations)
    return [
        source
        for slug in user.onboarding_selected_sources
        if (source := get_source(slug))
        and source.has_integration()
        and source.is_connected(user)
        and not source.is_integration_configured(user)
        and slug not in skipped
    ]


@require_GET
def onboarding_integration_setup(request):
    """Step 5: for connected services with a realtime integration, set it up too.

    Recomputes the remaining queue on every visit, same as
    ``onboarding_service_setup``: an empty queue (the common case, since
    most sources have no separate integration) advances straight through
    to the import status step without the user ever seeing this one.
    """
    blocked = _blocked_for_demo(request)
    if blocked:
        return blocked

    remaining = _remaining_integrations(request.user)
    if not remaining:
        return _advance(request.user, request, "import_status")

    current = remaining[0]
    return render(
        request,
        "users/onboarding/integration_setup.html",
        {
            "current_source": current,
            "remaining_count": len(remaining),
            **_wizard_progress("integration_setup"),
        },
    )


@require_http_methods(["POST"])
def onboarding_skip_integration(request, slug):
    """Skip a queued integration without losing progress on the others."""
    blocked = _blocked_for_demo(request)
    if blocked:
        return blocked

    skipped = set(request.user.onboarding_skipped_integrations)
    skipped.add(slug)
    request.user.onboarding_skipped_integrations = sorted(skipped)
    request.user.save(update_fields=["onboarding_skipped_integrations"])
    return redirect("onboarding_integration_setup")


@require_GET
def onboarding_resume(request):
    """Redirect to wherever the user left off in the wizard."""
    blocked = _blocked_for_demo(request)
    if blocked:
        return blocked

    step = request.user.onboarding_step
    if step not in STEP_URL_NAMES:
        step = "media_types"
    elif step == "import_status":
        # Scrobbling (integration_setup) used to come after Import; a step
        # persisted before that reorder would otherwise resume past it
        # entirely. integration_setup re-validates its own queue and
        # advances straight through if there's nothing pending, so this is
        # safe even for users who never had anything to configure there.
        step = "integration_setup"
    return _step_redirect(step)


@require_GET
def onboarding_restart(request):
    """Re-enter the wizard from Settings, even after it's already completed."""
    blocked = _blocked_for_demo(request)
    if blocked:
        return blocked

    request.user.onboarding_status = "in_progress"
    request.user.onboarding_step = "media_types"
    request.user.save(update_fields=["onboarding_status", "onboarding_step"])
    return redirect("onboarding_media_types")
