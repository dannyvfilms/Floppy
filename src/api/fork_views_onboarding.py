# FORK: first-run setup wizard as JSON for the native app.
#
# The web wizard lives in ``users.onboarding_views`` as HTML redirects. This
# view exposes the same state machine and reuses its helpers, so the step order,
# skipping rules and persistence cannot drift between the web and the app.
from http import HTTPStatus as HTTP  # noqa: N814

from django.templatetags.static import static
from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

from app.icon_specs import type_icon
from app.models import MediaTypes
from app.providers import credentials
from integrations.models import ImportRun
from integrations.oauth_scope_info import has_full_account_access
from integrations.onboarding import get_source, sources_for_media_type
from users import onboarding_views as wizard
from users.templatetags.user_tags import SOURCES_CONFIG
from users.views import apply_media_type_preferences

DEMO_MESSAGE = "Guided setup isn't available for demo accounts."
TOKEN_KEYS_MESSAGE = "Provider keys can only be saved from a signed-in session."  # noqa: S105


def _source_payload(source):
    info = SOURCES_CONFIG.get(source.slug)
    return {
        "slug": source.slug,
        "name": info["name"] if info else source.slug,
        "inlineSupported": source.inline_supported,
        "logo": info.get("logo", "") if info else "",
        "providerSlug": "mal" if source.slug == "myanimelist" else source.slug,
        "isOauth": source.is_oauth,
        "uploadFieldName": source.upload_field_name,
        "uploadAccept": source.upload_accept,
        "connectFields": [{"name": name, "label": label, "type": kind} for name, label, kind in source.connect_fields],
        "setupCopy": (
            "Public profile, private profile (OAuth), or a data export file." if source.slug == "trakt"
            else "Connect with your account (OAuth)." if source.is_oauth
            else "Requires uploading an export file." if source.upload_field_name
            else "Requires an API key." if source.setup_kind == "api_key"
            else "Requires your server URL and an API key." if source.setup_kind == "host_url"
            else "Requires your account credentials."
        ),
    }


def _media_label(media_type):
    # Plural, as the web setup list prints it ("TV Shows").
    return _walk_label(MediaTypes(media_type).value)


def _walk_label(media_type):
    # Same plural wording as ``media_type_readable_plural`` on the web.
    from app.templatetags.app_tags import media_type_readable_plural

    return str(media_type_readable_plural(media_type))


def _advance(user, step, fields=()):
    # The web helper only touches the user; the request argument is unused.
    wizard._advance(user, None, step, fields)


def _resolve_step(user):
    """Skip steps with nothing to ask, exactly like the web views do."""
    step = user.onboarding_step
    if step not in wizard.STEP_URL_NAMES or step == "done":
        step = "media_types"
    if step == "import_status":
        step = "integration_setup"
    for _ in range(6):
        if step == "metadata" and not wizard._metadata_suggestions(user):
            step = "services"
        elif step == "services" and not wizard._walk_media_types(user):
            step = "services_summary"
        elif step == "service_setup" and not wizard._remaining_sources(user):
            step = "integration_setup"
        elif step == "integration_setup" and not wizard._remaining_integrations(user):
            step = "import_status"
        else:
            break
    return step


def _progress(step):
    progress = wizard._wizard_progress(step)
    return {
        "steps": [{"slug": slug, "label": label} for slug, label in progress["onboarding_steps"]],
        "activeStep": progress["onboarding_active_step"],
        "completedSteps": progress["onboarding_completed_steps"],
    }


def _state(user, index=0):
    base = {
        "status": user.onboarding_status,
        "demo": bool(user.is_demo),
        "offer": user.onboarding_status != "completed" and not user.is_demo,
        "heroUrl": static("img/floppy-hero.png"),
    }
    if user.is_demo:
        return {**base, "step": "done", "message": DEMO_MESSAGE}
    if user.onboarding_status == "completed":
        step = "done"
    else:
        step = _resolve_step(user)
        if step != user.onboarding_step:
            _advance(user, step)
    payload = {**base, "step": step, **_progress("import_status" if step == "done" else step)}
    if step == "done":
        payload.update(_complete_payload(user))
    elif step == "media_types":
        order = [m for m in (user.sidebar_media_type_order or []) if m in wizard.ONBOARDING_MEDIA_TYPES]
        order += [m for m in wizard.ONBOARDING_MEDIA_TYPES if m not in order]
        payload["mediaTypes"] = {
            "options": [{"value": m, "label": _media_label(m), "icon": type_icon(m)} for m in order],
            "selected": [m for m in order if getattr(user, f"{m}_enabled", False)],
        }
    elif step == "metadata":
        payload["metadata"] = {
            "suggestions": [
                {
                    "slug": item["slug"],
                    "label": item["spec"].label,
                    "badge": item["badge"],
                    "why": item["why"],
                    "docsUrl": item["spec"].docs_url,
                    "fields": [
                        {"name": f.name, "label": f.label, "secret": bool(f.secret)}
                        for f in item["fields"]
                    ],
                }
                for item in wizard._metadata_suggestions(user)
            ],
        }
    elif step == "services":
        walk = wizard._walk_media_types(user)
        index = max(0, min(index, len(walk) - 1))
        media_type = walk[index]
        payload["services"] = {
            "index": index,
            "total": len(walk),
            "isLast": index + 1 == len(walk),
            "mediaType": media_type,
            "mediaTypeLabel": _walk_label(media_type),
            "candidates": [_source_payload(s) for s in sources_for_media_type(media_type)],
            "selected": list(user.onboarding_selected_sources),
        }
    elif step == "services_summary":
        payload["summary"] = _summary_payload(user)
    elif step == "service_setup":
        remaining = wizard._remaining_sources(user)
        payload["serviceSetup"] = {
            "source": _source_payload(remaining[0]),
            "remainingCount": len(remaining),
            "traktConfigured": bool(credentials.get("trakt", "client_id")),
        }
    elif step == "integration_setup":
        remaining = wizard._remaining_integrations(user)
        payload["integration"] = {
            "source": _source_payload(remaining[0]),
            "remainingCount": len(remaining),
        }
    elif step == "import_status":
        payload["importStatus"] = {"sources": _import_status(user)}
    return payload


def _connected_slugs(user):
    connected = set(user.onboarding_connected_sources)
    return [
        s.slug
        for s in (get_source(slug) for slug in user.onboarding_selected_sources)
        if s and (s.is_connected(user) or s.slug in connected)
    ]


def _summary_payload(user):
    return {
        "mediaTypeCount": len(wizard._walk_media_types(user)),
        "selectedSources": [
            _source_payload(s)
            for s in (get_source(slug) for slug in user.onboarding_selected_sources)
            if s
        ],
        "connectedSources": _connected_slugs(user),
    }


def _complete_payload(user):
    connected = [get_source(slug) for slug in _connected_slugs(user)]
    return {
        "summary": {
            **_summary_payload(user),
            "connectedSourceList": [_source_payload(s) for s in connected if s],
        },
    }


def _import_status(user):
    slugs = _connected_slugs(user)
    latest = {}
    if slugs:
        runs = ImportRun.objects.filter(user=user, source__in=slugs).order_by("source", "-started_at")
        for run in runs:
            latest.setdefault(run.source, run)
    result = []
    for slug in slugs:
        run = latest.get(slug)
        result.append(
            {
                "source": _source_payload(get_source(slug)),
                "run": {"status": run.status, "error": getattr(run, "error", "") or ""} if run else None,
            },
        )
    return result


def _bad(message, errors=None):
    body = {"detail": message}
    if errors:
        body["errors"] = errors
    return Response(body, status=HTTP.BAD_REQUEST)


# /api/v1/user/onboarding/
class UserOnboardingView(drf_views.APIView):
    """Read the first-run setup state, or perform one wizard action."""

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        """Return the current step with the data it needs."""
        try:
            index = int(request.query_params.get("index", 0))
        except (TypeError, ValueError):
            index = 0
        return Response(_state(request.user, index))

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        """Apply one action and return the next state.

        Actions: ``media_types``, ``skip``, ``metadata``, ``skip_metadata``,
        ``services``, ``later``, ``setup_now``, ``skip_service``,
        ``connect_service``, ``skip_integration``, ``integration_done``, ``finish``, ``restart``.
        """
        user = request.user
        if user.is_demo:
            return _bad(DEMO_MESSAGE)
        data = dict(request.data) if isinstance(request.data, dict) else {}
        action = str(data.get("action") or "")
        handler = _ACTIONS.get(action)
        if handler is None:
            return _bad("Unknown setup action.")
        try:
            data["nextIndex"] = int(data.get("nextIndex") or 0)
        except (TypeError, ValueError):
            return _bad("'nextIndex' must be an integer.")
        error = handler(request, user, data)
        if error is not None:
            return error
        # A handler may advance nextIndex (the services walk does).
        return Response(_state(user, int(data["nextIndex"])))


def _act_media_types(request, user, data):
    selected = [m for m in (data.get("mediaTypes") or []) if m in wizard.ONBOARDING_MEDIA_TYPES]
    if not selected:
        return _bad("Choose at least one media type to continue.")
    order = [m for m in (data.get("order") or selected) if isinstance(m, str)]
    fields = apply_media_type_preferences(user, selected, order, media_types=wizard.ONBOARDING_MEDIA_TYPES)
    _advance(user, "metadata", fields)
    return None


def _act_finish(request, user, data):
    wizard._finish(user)


def _act_metadata(request, user, data):
    if hasattr(request.auth, "has_scope") and not has_full_account_access(request.auth):
        return Response({"detail": TOKEN_KEYS_MESSAGE}, status=HTTP.FORBIDDEN)
    submitted = data.get("values") if isinstance(data.get("values"), dict) else {}
    errors = {}
    for suggestion in wizard._metadata_suggestions(user):
        spec = suggestion["spec"]
        values = {
            f.name: str(submitted.get(f"{spec.slug}-{f.name}", "")).strip()
            for f in suggestion["fields"]
        }
        if not any(values.values()):
            continue
        missing = any(f.required and not values[f.name] for f in suggestion["fields"])
        error = "fill in every field" if missing else (spec.validator(values) if spec.validator else None)
        if error:
            errors[spec.slug] = f"{spec.label}: {error}"
            continue
        credentials.set_user(spec.slug, user, values)
    if errors:
        return _bad(next(iter(errors.values())), errors)
    _advance(user, "services")
    return None


def _act_skip_metadata(request, user, data):
    _advance(user, "services")


def _act_services(request, user, data):
    walk = wizard._walk_media_types(user)
    if not walk:
        _advance(user, "services_summary")
        return
    try:
        index = max(0, min(int(data.get("index", 0)), len(walk) - 1))
    except (TypeError, ValueError):
        index = 0
    candidates = {s.slug for s in sources_for_media_type(walk[index])}
    chosen = set(user.onboarding_selected_sources) - candidates
    chosen |= {s for s in (data.get("sources") or []) if isinstance(s, str)} & candidates
    user.onboarding_selected_sources = sorted(chosen)
    if index + 1 < len(walk):
        user.save(update_fields=["onboarding_selected_sources"])
        data["nextIndex"] = index + 1
        return
    _advance(user, "services_summary", ["onboarding_selected_sources"])
    return


def _act_later(request, user, data):
    wizard._finish(user)


def _act_setup_now(request, user, data):
    _advance(user, "service_setup")


def _act_connect_service(request, user, data):
    """Use the same inline import/connect handler as the web setup form."""
    from api.fork_views_providers import ProviderFileImportView, _call, _view_for

    if hasattr(request.auth, "has_scope") and not has_full_account_access(request.auth):
        return Response({"detail": TOKEN_KEYS_MESSAGE}, status=HTTP.FORBIDDEN)
    source = get_source(str(data.get("slug") or ""))
    if user.onboarding_step != "service_setup" or source not in wizard._remaining_sources(user):
        return _bad("Choose a service from the current setup queue.")
    if not source.inline_supported:
        return _bad("Connect this service from its provider page.")
    if source.upload_field_name or (source.slug == "trakt" and data.get("profile") == "csv"):
        # File bounds, type checks, staging and queue failure handling stay owned
        # by the existing provider upload API. Only record successful queueing.
        request.data["mode"] = source.recommended_import_mode
        response = ProviderFileImportView().post(request, source.slug)
    else:
        if source.is_oauth and source.slug != "trakt":
            return _bad("Finish connecting through the provider sign-in flow.")
        if source.slug == "trakt" and data.get("profile") != "public":
            return _bad("Finish connecting through the provider sign-in flow.")
        view = _view_for("import_trakt_public" if source.slug == "trakt" else source.connect_url_name)
        if view is None:
            return _bad("This service cannot be connected inline.")
        values = data.get("values") if isinstance(data.get("values"), dict) else {}
        names = {name for name, _label, _kind in source.connect_fields}
        if source.slug == "trakt":
            names = {"user"}
        post = {name: values.get(name, "") for name in names}
        post.update(mode=source.recommended_import_mode, frequency="once", time="00:00", next=reverse("onboarding_service_setup"))
        response = _call(request, view, post=post)
    if response.status_code >= HTTP.BAD_REQUEST:
        return response
    if source.slug not in user.onboarding_connected_sources:
        user.onboarding_connected_sources = [*user.onboarding_connected_sources, source.slug]
        user.save(update_fields=["onboarding_connected_sources"])
    return None


def _act_skip_service(request, user, data):
    slug = str(data.get("slug") or "")
    skipped = set(user.onboarding_skipped_sources)
    skipped.add(slug)
    user.onboarding_skipped_sources = sorted(skipped)
    user.save(update_fields=["onboarding_skipped_sources"])


def _act_skip_integration(request, user, data):
    slug = str(data.get("slug") or "")
    skipped = set(user.onboarding_skipped_integrations)
    skipped.add(slug)
    user.onboarding_skipped_integrations = sorted(skipped)
    user.save(update_fields=["onboarding_skipped_integrations"])


def _act_integration_done(request, user, data):
    _advance(user, "import_status")


def _act_restart(request, user, data):
    user.onboarding_status = "in_progress"
    user.onboarding_step = "media_types"
    user.save(update_fields=["onboarding_status", "onboarding_step"])


_ACTIONS = {
    "media_types": _act_media_types,
    "skip": _act_finish,
    "metadata": _act_metadata,
    "skip_metadata": _act_skip_metadata,
    "services": _act_services,
    "later": _act_later,
    "setup_now": _act_setup_now,
    "connect_service": _act_connect_service,
    "skip_service": _act_skip_service,
    "skip_integration": _act_skip_integration,
    "integration_done": _act_integration_done,
    "finish": _act_finish,
    "restart": _act_restart,
}
