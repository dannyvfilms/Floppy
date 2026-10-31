"""Provider settings navigation using the existing forms and action handlers."""

from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_GET

from users import metadata_views, views
from users.provider_catalog import (
    ACCOUNT_IMPORTS,
    CAPABILITIES,
    MEDIA_CHOICES,
    catalog,
    provider_state,
)


@require_GET
def providers(request):
    """Search all supported providers by capability and library type."""
    query = request.GET.get("q", "").strip()
    capability = request.GET.get("capability", "")
    if capability not in CAPABILITIES:
        capability = ""
    media = request.GET.get("media", "")
    if media not in dict(MEDIA_CHOICES):
        media = ""
    items = catalog()
    if query:
        items = [
            item
            for item in items
            if query.casefold()
            in (
                item["label"] + " " + item["description"] + " " + item["card_description"]
            ).casefold()
        ]
    if capability in CAPABILITIES:
        items = [item for item in items if item.get(capability)]
    if media:
        items = [item for item in items if media in item["media_types"]]
    for item in items:
        item["state"] = provider_state(item, request.user)
    context = {
        "providers": items,
        "query": query,
        "capability": capability,
        "media": media,
        "capability_options": [{"key": "", "label": "All Capabilities"}]
        + [{"key": key, "label": key.title()} for key in CAPABILITIES],
        "media_options": [{"key": "", "label": "All Types"}]
        + [{"key": key, "label": label} for key, label in MEDIA_CHOICES],
        "capability_label": capability.title() if capability else "All Capabilities",
        "media_label": dict(MEDIA_CHOICES).get(media, "All Types"),
    }
    template = (
        "users/components/provider_results.html"
        if request.headers.get("HX-Target") == "provider-results"
        else "users/providers.html"
    )
    return render(request, template, context)


@require_GET
def provider_detail(request, slug):
    """Render one provider with only its supported capability tabs."""
    provider = next((item for item in catalog() if item["slug"] == slug), None)
    if provider is None:
        raise Http404
    provider["state"] = provider_state(provider, request.user)
    tab = request.GET.get("tab", "overview")
    if tab not in provider["tabs"]:
        raise Http404
    context = {
        "provider": provider,
        "provider_slug": slug,
        "provider_tab": tab,
        "activity_source": slug,
        "provider_navigation": True,
        "capability_rows": [
            {"key": key, "label": key.title(), "state": state}
            for key, state in provider["state"]["capabilities"].items()
        ],
    }
    if tab == "metadata" or (tab == "connection" and provider.get("credential")):
        context.update(metadata_views.metadata_context(request.user, slug))
    if (
        tab == "import"
        or (tab == "connection" and slug in ACCOUNT_IMPORTS and slug != "mal")
    ) and provider.get("import_slug"):
        context.update(views.import_data_context(request))
        context["import_slug"] = provider["import_slug"]
    if tab == "activity" or (
        provider.get("integration")
        and tab in {"connection", "import", "tracking", "sync"}
    ):
        context.update(
            views.integrations_context(
                request, slug, refresh_plex=tab not in {"import", "activity"}
            )
        )
    if slug in {"mal", "tmdb", "wetrakr"} and tab in {"connection", "sync", "activity"}:
        context.update(views.mal_export_context(request, slug))
    return render(request, "users/provider_detail.html", context)


@require_GET
def activity(request):
    """Show the same operational records used by provider Activity tabs."""
    context = views.integrations_context(request, refresh_plex=False)
    context.update(views.mal_export_context(request))
    return render(request, "users/provider_activity.html", context)


@require_GET
def data_management(request):
    """Keep file exports, restore and library repair together."""
    context = views.export_data_context(request)
    context.update(views.import_data_context(request))
    context.update(metadata_views.metadata_context(request.user))
    context.update(
        {
            "import_slug": "yamtrack",
            "deletable_media_types": views.DELETABLE_MEDIA_TYPES,
            "import_source_media": views._import_source_media_summary(request.user),
        }
    )
    return render(request, "users/data_management.html", context)


@require_GET
def access_tokens(request):
    """Manage credentials granting clients access to Floppy."""
    context = views.integrations_context(
        request, include_tokens=True, refresh_plex=False
    )
    return render(request, "users/access_tokens.html", context)


@require_GET
def legacy_settings(request, section):
    """Keep bookmarks and action redirects working during settings relocation."""
    params = request.GET.copy()
    if params.get("onboarding"):
        params["setup_flow"] = "import" if section == "import" else "tracking"
    opened = params.get("open", "")
    slug = {"myanimelist": "mal"}.get(opened, opened)
    known = {item["slug"]: item for item in catalog()}
    destination = "providers"
    args = []
    if section == "import" and opened == "yamtrack":
        destination = "data_management"
    elif section == "integrations" and not opened:
        params["capability"] = "tracking"
    elif section == "export":
        destination = "data_management"
    elif section == "metadata" and opened.startswith("media-type-"):
        media_type = opened.removeprefix("media-type-")
        candidates = [
            item
            for item in catalog()
            if item.get("metadata") and media_type in item["media_types"]
        ]
        if candidates:
            slug = candidates[0]["slug"]
            params["tab"] = "metadata"
            destination, args = "provider_detail", [slug]
    elif slug in known:
        destination, args = "provider_detail", [slug]
        params["tab"] = {
            "metadata": "connection",
            "import": "import",
            "integrations": "tracking",
            "sync": "sync",
        }[section]
        if params["tab"] not in known[slug]["tabs"]:
            params["tab"] = "overview"
    elif section == "sync":
        destination, args = "provider_detail", ["mal"]
        params["tab"] = "sync"
    else:
        params["capability"] = {"metadata": "metadata", "import": "import"}.get(
            section, ""
        )
    url = reverse(destination, args=args)
    if params:
        url += "?" + urlencode(params, doseq=True)
    return redirect(url)
