"""Projection of the detail sidebar's facts, shared by the API and the web page."""

from datetime import date, datetime
from decimal import Decimal

from django.utils.translation import gettext, ngettext

from app.templatetags.app_tags import (
    country_code,
    detail_promoted_facts,
    iso_date_format,
    safe_count,
    translate_detail_value,
    translate_language_code,
)
from users.templatetags.user_tags import user_date_format


def primitive(value):
    """Convert builder output to JSON-safe values without leaking model objects."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): primitive(entry) for key, entry in value.items()}
    if isinstance(value, (list, tuple)):
        return [primitive(entry) for entry in value]
    return str(value)


def nonempty_list(value):
    """Return a list of the non-empty entries of ``value``."""
    if isinstance(value, (tuple, list)):
        return [entry for entry in value if entry not in (None, "", [], {})]
    return [value] if value not in (None, "", [], {}) else []


def platform_collection_counts(viewer, item, details):
    """Return, per listed platform, how many of the viewer's games are collected on it."""
    names = [name for name in nonempty_list((details or {}).get("platforms")) if isinstance(name, str)]
    if not getattr(viewer, "is_authenticated", False) or item is None or not names:
        return {}
    from django.db.models import Count

    from app.models import CollectionEntry, MediaTypes

    rows = (
        CollectionEntry.objects.filter(
            user=viewer, item__media_type=MediaTypes.GAME.value, resolution__in=names,
        )
        .values("resolution")
        .annotate(games=Count("item", distinct=True))
    )
    return dict.fromkeys(names, 0) | {row["resolution"]: row["games"] for row in rows}


def genre_library_counts(viewer, item, media_type, genres):
    """Return, per genre, how many of the viewer's items of this type carry it."""
    names = [name for name in nonempty_list(genres) if isinstance(name, str)]
    if not getattr(viewer, "is_authenticated", False) or item is None or not names:
        return {}
    from django.apps import apps

    from app.models.manager import item_ids_with_json_array_value_ci

    try:
        model = apps.get_model("app", media_type)
    except LookupError:
        return {}
    return {
        name: model.objects.filter(
            user=viewer, item_id__in=item_ids_with_json_array_value_ci("genres", name.strip().lower()),
        ).count()
        for name in names
    }


def sidebar_labels():
    """Return the sidebar's translated labels."""
    return {
        "unknown": gettext("Unknown"),
        "airDates": gettext("AIR DATES"),
        "runtime": gettext("RUNTIME"),
        "anime": gettext("Anime"),
        "format": gettext("Format"),
        "author": gettext("AUTHOR"),
        "authors": gettext("AUTHORs"),
        "details": gettext("Details"),
        "noDetails": gettext("No details available"),
        "streaming": gettext("STREAMING"),
        "noWatchProviders": gettext("No watch providers"),
    }


def project_details(metadata_details, media_type, viewer):
    """Return ``(details, display_details, promotion)`` for a detail payload."""
    details = metadata_details or {}
    if not isinstance(details, dict):
        details = {}
    display_details = {}
    for key, value in details.items():
        if key in {"first_air_date", "last_air_date"}:
            display = user_date_format(value, viewer) if viewer else value
            if key == "first_air_date" and details.get("last_air_date"):
                end = details["last_air_date"]
                display = f"{display} \u2013 {user_date_format(end, viewer) if viewer else end}"
        elif key in {"total_runtime", "runtime"} and details.get("episodes"):
            count = details["episodes"]
            display = str(value if value is not None else gettext("Unknown")) + " · " + ngettext("%(count)s episode", "%(count)s episodes", safe_count(count)) % {"count": count}
        elif key in {"start_date", "end_date", "publish_date", "release_date", "last_updated"}:
            display = iso_date_format(value, viewer)
        elif key == "language":
            display = translate_language_code(value)
        elif key in {"season", "broadcast", "source", "players"}:
            display = translate_detail_value(value)
        elif key == "format" and media_type == "anime":
            display = gettext("Anime")
        elif key in {"format", "status", "country", "countries", "production_countries", "origin_country", "languages"}:
            display = [gettext(str(entry)) if entry else gettext("Unknown") for entry in value] if isinstance(value, list) else gettext(str(value)) if value else gettext("Unknown")
        else:
            display = value
        display_details[key] = primitive(display)
    promotion = detail_promoted_facts(media_type, details)
    for field in promotion["fields"]:
        key, value = field["key"], field["value"]
        if key == "locale":
            languages = ", ".join(translate_detail_value(entry) for entry in nonempty_list(value.get("languages")))
            countries = ", ".join(translate_detail_value(country_code(entry)) for entry in nonempty_list(value.get("country")))
            display = f"{languages} ({countries})" if languages and countries else languages or countries
        elif key == "air_dates":
            display = " \u2013 ".join(str(user_date_format(entry, viewer) if viewer else entry) for entry in value if entry)
        elif key == "release_date":
            display = iso_date_format(value, viewer)
        elif key == "episodes":
            display = ngettext("%(count)s episode", "%(count)s episodes", safe_count(value)) % {"count": value}
        elif key == "total_runtime" and media_type == "tv" and details.get("episodes"):
            count = details["episodes"]
            display = str(value) + " · " + ngettext("%(count)s episode", "%(count)s episodes", safe_count(count)) % {"count": count}
        elif isinstance(value, list):
            display = ", ".join(str(entry) for entry in value)
        else:
            display = display_details.get(key, value)
        field["display_value"] = primitive(display)
    return details, display_details, promotion


def rating_breakdown(user, entry):
    """Return the custom-scale breakdown for the sidebar, or None without one."""
    from users import rating_scales

    if entry is None or not getattr(user, "custom_rating_scale_id", None):
        return None
    payload = rating_scales.entry_payload(user, entry)
    if payload is None or not payload["values"]:
        return None
    payload["overall"] = None if entry.score is None else float(entry.score)
    return payload


def web_sidebar_payload(context, kind, title=""):
    """Return the detail sidebar's data in the shape the shared React cards read.

    The web page already holds these values in its template context; this only
    projects them (formatted details, links, image URLs) so the React cards need
    no second fetch.
    """
    if kind == "heading":
        return {"kind": kind, "title": title, "payload": {}}
    if kind == "rating":
        return {"kind": kind, "title": title, "payload": {
            "rating": rating_breakdown(context.get("user"), context.get("current_instance")),
        }}

    from urllib.parse import quote

    from django.urls import reverse
    from django.utils.text import slugify

    from app.templatetags.app_tags import image_url, studio_url

    media = context.get("media") or {}
    media_type = context.get("media_type")
    viewer = context.get("user")
    viewer = viewer if getattr(viewer, "is_authenticated", False) else None
    details, display_details, promotion = project_details(
        media.get("details"), media_type, viewer,
    )
    authors = [
        {
            "name": author.get("name", ""),
            "href": reverse("person_detail", kwargs={
                "source": author["source"],
                "person_id": author["person_id"],
                "name": slugify(author.get("name", "")),
            }),
        }
        for author in context.get("authors_linked") or []
    ]
    studios = [
        {
            "name": studio.get("name") or gettext("Unknown Studio"),
            "href": studio_url(studio),
            "logo": image_url(studio.get("logo")) if studio.get("logo") else "",
        }
        for studio in (context.get("studios_linked") or [])[:12]
    ]
    region = context.get("watch_provider_region")
    providers = context.get("watch_providers")
    if providers is not None:
        providers = [
            {**provider, "image": image_url(provider.get("image"))}
            for provider in providers
        ]
    list_url = reverse(
        "medialist",
        kwargs={"media_type": context.get("parent_media_type") or media_type},
    )
    genre_counts = genre_library_counts(
        viewer, context.get("match_item"), media_type, media.get("genres"),
    )
    genres = [
        {
            "label": gettext(genre),
            "url": f"{list_url}?genre={quote(str(genre))}",
            "count": genre_counts.get(genre, 0),
        }
        for genre in media.get("genres") or []
    ]
    stats = context.get("collection_stats") or {}
    collection_rows = []
    for key, label in (
        ("seasons", gettext("Collected seasons")),
        ("episodes", gettext("Collected episodes")),
    ):
        if key == "seasons" and media_type == "season":
            continue
        if not stats:
            continue
        collected = stats.get(f"collected_{key}") or 0
        total = stats.get(f"total_{key}") or 0
        value = f"{collected}/{total}"
        if total > 0:
            value += f" \u2022 {round(collected * 100 / total)}%"
        collection_rows.append({"key": key, "label": label, "value": value})
    return {"kind": kind, "title": title, "payload": primitive({
        "collection_rows": collection_rows,
        "identity": {"media_type": media_type},
        "public_view": bool(context.get("public_view")),
        "secondary": {
            "details": details,
            "display_details": display_details,
            "labels": sidebar_labels(),
            "authors_linked": authors,
            "studios_linked": studios,
            "author_detail_keys": ["author", "authors", "people"],
            "studio_detail_keys": ["studios", "companies"],
            "book_formats_replaces": "format" if context.get("book_formats") else "",
            "promotion": {
                "fields": promotion["fields"],
                "suppressed_keys": sorted(promotion["suppressed_keys"]),
            },
            "watch_providers": providers,
            "watch_provider_region": region or "UNSET",
            "platform_counts": platform_collection_counts(
                viewer, context.get("match_item"), media.get("details"),
            ),
        },
        "collected_platforms": [
            entry.resolution
            for entry in context.get("collection_entries") or []
            if media_type == "game" and getattr(entry, "resolution", "")
        ],
        "book_formats": context.get("book_formats") or [],
        "tag_sections": [{"title": "Genres", "entries": genres}] if genres else [],
        "titles": {
            "genres": gettext("Genres"),
            "studios": gettext("Studios"),
        },
    })}
