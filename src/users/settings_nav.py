"""Settings navigation as plain data for the shared React page composition.

The Django settings navigation, the Expo settings tab and the shared
``frontend/pages/SettingsView.jsx`` read the same groups, item order, labels,
permissions and URLs. Icons travel as parsed shapes, never as markup.
"""

from django.urls import reverse
from django.utils.translation import gettext as _

from app.icon_specs import file_icon

# (group id, group title, [(item id, label, page id, icon file, url name)])
SETTINGS_NAVIGATION = [
    (
        "general",
        _("General"),
        [
            ("account", _("Account"), "settingsAccount", "person", "account"),
            (
                "preferences",
                _("Preferences"),
                "settingsPreferences",
                "vertical-sliders",
                "preferences",
            ),
            (
                "notifications",
                _("Notifications"),
                "settingsNotifications",
                "bell",
                "notifications",
            ),
        ],
    ),
    (
        "display",
        _("Display"),
        [
            ("appearance", _("Appearance"), "settingsAppearance", "sun", "appearance"),
            ("cards", _("Media Cards"), "settingsCards", "grid", "cards"),
            ("sidebar", _("Sidebar"), "settingsSidebar", "sidebar", "sidebar"),
            ("home", _("Home Screen"), "settingsHome", "house", "home_screen"),
        ],
    ),
    (
        "providers-data",
        _("Providers & Data"),
        [
            ("providers", _("Providers"), "providers", "database", "providers"),
            (
                "activity",
                _("Activity"),
                "providerActivity",
                "clock",
                "provider_activity",
            ),
            (
                "data",
                _("Data Management"),
                "settingsData",
                "database",
                "data_management",
            ),
            (
                "access",
                _("Access & Tokens"),
                "settingsAccess",
                "padlock",
                "access_tokens",
            ),
        ],
    ),
    (
        "system",
        _("System"),
        [
            ("advanced", _("Advanced"), "settingsAdvanced", "shield-alert", "advanced"),
            (
                "users",
                _("Users"),
                "settingsUsers",
                "persons",
                "manage_users",
            ),
            ("about", _("About"), "settingsAbout", "info", "about"),
        ],
    ),
]

# Resolver url names that render under the settings shell.
PAGE_BY_URL_NAME = {
    "account": ("settingsAccount", "account"),
    "preferences": ("settingsPreferences", "preferences"),
    "notifications": ("settingsNotifications", "notifications"),
    "appearance": ("settingsAppearance", "appearance"),
    "cards": ("settingsCards", "cards"),
    "cards_type": ("settingsCards", "cards"),
    "cards_preview": ("settingsCards", "cards"),
    "sidebar": ("settingsSidebar", "sidebar"),
    "home_screen": ("settingsHome", "home"),
    "providers": ("providers", "providers"),
    "provider_detail": ("providers", "providers"),
    "provider_activity": ("providerActivity", "activity"),
    "data_management": ("settingsData", "data"),
    "rss_settings": ("settingsData", "data"),
    "access_tokens": ("settingsAccess", "access"),
    "oauth_applications": ("settingsAccess", "access"),
    "advanced": ("settingsAdvanced", "advanced"),
    "about": ("settingsAbout", "about"),
    "manage_users": ("settingsUsers", "users"),
}


def settings_view_model(request):
    """Return the shared settings page, navigation, URLs and icon shapes."""
    url_name = getattr(request.resolver_match, "url_name", "")
    page, active = PAGE_BY_URL_NAME.get(url_name, ("", ""))
    navigation = []
    for group_id, title, items in SETTINGS_NAVIGATION:
        navigation.append(
            {
                "id": group_id,
                "title": str(title),
                "items": [
                    {
                        "id": item_id,
                        "label": str(label),
                        "page": page_id,
                        "icon": icon,
                        "iconSpec": file_icon(icon),
                        "url": reverse(url_name_value),
                        **({"permission": "superuser"} if item_id == "users" else {}),
                    }
                    for item_id, label, page_id, icon, url_name_value in items
                    if item_id != "users" or request.user.is_superuser
                ],
            }
        )
    return {
        "page": page,
        "active": active,
        "navigation": navigation,
        "availablePages": [
            item["page"] for group in navigation for item in group["items"]
        ],
        "permissions": {"superuser": bool(request.user.is_superuser)},
        "labels": {
            "title": str(_("Settings")),
            "subtitle": str(_("Configure your account and preferences")),
            "menu": str(_("Menu")),
            "serverOnly": str(_("Server only")),
        },
        "icons": {"chevron": file_icon("chevron-down")},
    }
