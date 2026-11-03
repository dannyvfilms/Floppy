"""What the sidebar shows, as plain data for the shared React sidebar.

The Django sidebar template and this module read the same helpers
(``get_sidebar_media_types``, ``get_history_saved_views``) so the links, their
order and the active page agree. Icons travel as parsed shapes, never as markup.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from django.conf import settings
from django.middleware.csrf import get_token
from django.templatetags.static import static
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import pgettext

from app.templatetags import app_tags

ICON_DIR = Path(settings.BASE_DIR) / "templates" / "app" / "icons"
SVG_ATTRS = ("fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin")
PIN_KEYS = ["calendar", "collection", "custom", "history", "lists", "statistics", "tags"]
SETTINGS_URLS = [
    "account",
    "notifications",
    "sidebar",
    "ui_preferences",
    "preferences",
    "home_screen",
    "integrations",
    "import_data",
    "export_data",
    "mal_export",
]


def icon_spec(markup):
    """Parse a trusted SVG icon into a root and its child shapes."""
    root = ET.fromstring(re.sub(r"\{\{\s*classes\s*\}\}", "", markup))  # noqa: S314

    def shape(node):
        return {
            "tag": node.tag.rsplit("}", 1)[-1],
            "attrs": dict(node.attrib),
            "children": [shape(child) for child in node],
        }

    return {
        "viewBox": root.get("viewBox", "0 0 24 24"),
        "root": {name: root.get(name) for name in SVG_ATTRS if root.get(name)},
        "children": [shape(child) for child in root],
    }


def file_icon(name):
    """Return the spec for ``app/icons/<name>.svg``."""
    return icon_spec((ICON_DIR / f"{name}.svg").read_text())


def type_icon(name):
    """Return the spec for a media-type icon from the ``icon`` tag."""
    return icon_spec(str(app_tags.icon(name, False, "")))


def _link(label, href, icon, *, active, pin_key=None):
    return {
        "type": "link",
        "label": str(label),
        "href": href,
        "icon": icon,
        "active": bool(active),
        "pinKey": pin_key,
    }


def _group(key, label, href, icon, views, *, active, request, pin_key=None):
    full_path = request.get_full_path()
    return {
        "type": "group",
        "key": key,
        "label": str(label),
        "href": href,
        "icon": icon,
        "active": bool(active),
        "pinKey": pin_key,
        "views": [
            {
                "id": view.id,
                "name": view.name,
                "href": view.get_absolute_url(),
                "current": full_path == view.get_absolute_url(),
                "deleteUrl": reverse("saved_view_delete", args=[view.id]),
            }
            for view in views
        ],
    }


def sidebar_model(request, user, media_type):
    """Return the sidebar's links, groups, labels and the current user's ids."""
    path = request.path
    primary = [_link(_("Home"), reverse("home"), file_icon("house"), active=path == "/")]
    if user.show_discover:
        discover = reverse("discover")
        primary.append(
            _link(_("Discover"), discover, file_icon("four-square"), active=path == discover),
        )
    for item in app_tags.get_sidebar_media_types(user):
        kind = item["media_type"]
        href = reverse("medialist", kwargs={"media_type": kind})
        active = media_type == kind
        icon = type_icon(kind)
        if item["saved_views"]:
            primary.append(
                _group(kind, item["display_name"], href, icon, item["saved_views"], active=active, request=request),
            )
        else:
            primary.append(_link(item["display_name"], href, icon, active=active))

    def secondary_link(key, label, name, icon):
        href = reverse(name)
        return _link(label, href, icon, active=path == href, pin_key=key)

    history_url = reverse("history")
    history_views = app_tags.get_history_saved_views(user)
    history = (
        _group("history", _("History"), history_url, type_icon("history"), history_views,
               active=path == history_url, request=request, pin_key="history")
        if history_views
        else _link(_("History"), history_url, type_icon("history"), active=path == history_url, pin_key="history")
    )
    lists_url = reverse("lists")
    secondary = [
        secondary_link("calendar", _("Calendar"), "calendar", file_icon("calendar")),
        secondary_link("collection", _("Collection"), "collection_list", file_icon("cube")),
        secondary_link("custom", pgettext("navigation", "Custom"), "create_entry", file_icon("circle-plus")),
        history,
        {
            **_link(_("Lists"), lists_url, file_icon("folder-plus"), active=path == lists_url, pin_key="lists"),
            "type": "lists",
        },
        secondary_link("statistics", _("Statistics"), "statistics", file_icon("bars-pyramid")),
        secondary_link("tags", _("Tags"), "tag_index", file_icon("tag")),
    ]
    settings_active = any(path == reverse(name) for name in SETTINGS_URLS)
    mono = user.is_authenticated and user.logo_style == "monochrome"
    return {
        "userId": str(user.pk),
        "logo": {
            "src": static("img/floppy-logo-white.png" if mono else "img/floppy-logo.png"),
            "srcSet": None if mono else f'{static("img/floppy-logo.png")} 1x, {static("img/floppy-logo@2x.png")} 2x',
            "mono": bool(mono),
        },
        "primary": primary,
        "secondary": secondary,
        "pinKeys": PIN_KEYS,
        "bottom": {
            "appearance": _link(_("Appearance"), reverse("appearance"), file_icon("moon"), active=path == reverse("appearance")),
            "settings": _link(_("Settings"), reverse("account"), file_icon("settings"), active=settings_active),
            "logoutAction": reverse("account_logout"),
            "logoutIcon": file_icon("logout"),
        },
        "icons": {
            "chevron": file_icon("chevron-down"),
            "ellipsis": file_icon("ellipsis"),
            "drag": file_icon("drag-handle"),
            "reorder": file_icon("arrows-up-down"),
            "trash": file_icon("trashcan"),
            "check": file_icon("checkmark"),
        },
        "csrfToken": get_token(request),
        "currentUrl": request.get_full_path(),
        # Only pages with saved views need the reorder endpoint.
        "reorderUrl": reverse("saved_view_reorder")
        if any(item["type"] == "group" for item in [*primary, *secondary])
        else None,
        "labels": {
            "explore": _("Explore"),
            "logout": _("Logout"),
            "pinnedLists": _("Pinned lists"),
            "navOptions": _("Navigation options"),
            "pin": _("Pin to sidebar"),
            "unpin": _("Unpin from sidebar"),
            "listOptions": _("List options"),
            "reorder": _("Reorder"),
            "delete": _("Delete"),
            "done": _("Done"),
            "savedViews": _("Saved %(name)s views"),
            "viewOptions": _("Options for %(name)s"),
            "confirmDelete": _("Delete the saved view “%(name)s”?"),
        },
    }
