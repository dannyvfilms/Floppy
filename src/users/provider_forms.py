"""Settings forms on integration tabs, described as data for the shared form component.

Each form posts to the same view as the legacy markup it replaces. Secret values
(for example the Seerr API key) are never included; their fields stay blank and the
view keeps the saved value when the field is left empty.
"""

from django.middleware.csrf import get_token
from django.urls import reverse
from django.utils.translation import gettext as _


def _form(request, form_id, action, fields, hidden=None, submit="Save Changes"):
    return {
        "id": form_id, "action": reverse(action), "csrf": get_token(request), "next": request.get_full_path(),
        "fields": fields, "hidden": hidden or {}, "submit": _(submit),
    }


def build(request, slug, tab, context):
    """Return {form key: model} for the integration forms a provider tab shows."""
    user = request.user
    forms = {}
    if slug == "plex":
        forms["plex_usernames"] = _form(request, "plex-usernames", "update_plex_usernames", [{
            "name": "plex_usernames", "type": "text", "label": _("Plex Usernames"), "value": user.plex_usernames,
            "help": _("This username (or several, comma-separated) will be used to filter which events are sent to your webhook."),
            "placeholder": _("username1, username2, username3"),
        }])
        if context.get("plex_connected"):
            account = getattr(user, "plex_account", None)
            forms["plex_mark_watched"] = _form(request, "plex-mark-watched", "update_plex_mark_watched", [{
                "name": "plex_mark_watched_enabled", "type": "toggle", "label": _("Sync items marked watched"),
                "help": _("Mark media as watched when it is manually marked watched in Plex."),
                "value": bool(account and account.mark_watched_sync_enabled),
            }])
    elif slug == "hardcover" and context.get("hardcover_personal_key"):
        forms["hardcover_sync"] = _form(request, "hardcover-sync", "hardcover_sync", [
            {"name": "frequency", "type": "select", "label": _("Import Frequency"), "value": "once",
             "options": [{"value": "once", "label": _("One Time Import")}, {"value": "daily", "label": _("Every Day")},
                         {"value": "2days", "label": _("Every 2 Days")}]},
            {"name": "time", "type": "time", "label": _("Import Time"), "value": str(user.import_time)[:5], "required": True,
             "showWhen": {"name": "frequency", "not": "once"}},
        ], {"mode": user.import_mode}, submit="Sync now")
        forms["hardcover_sync"]["followPreferences"] = True
        forms["hardcover_sync"]["blockedLabel"] = _("This import mode is not supported by this provider.")
    elif slug == "koreader":
        account = context.get("koreader_account")
        connected = bool(account and (account.is_connected() if callable(account.is_connected) else account.is_connected))
        prefs = {"frequency": user.import_frequency, "time": str(user.import_time)[:5], "mode": user.import_mode}
        flags = (("verify_ssl", _("Verify TLS certificate"), True), ("create_missing", _("Add matched books that are not already in my library"), False),
                 ("skip_finished_books", _("Skip books already marked completed (fewer server requests)"), True))
        fields = [
            {"name": "server_url", "type": "url", "label": _("Server URL"), "required": True,
             "placeholder": "https://kosync.example.com:7200", "value": account.server_url if connected else ""},
            {"name": "username", "type": "text", "label": _("Username"), "required": True, "autoComplete": "username",
             "value": account.username if connected else ""},
            {"name": "password", "type": "password", "label": _("Password"), "required": not connected, "autoComplete": "current-password",
             "placeholder": _("Leave blank to keep current password") if connected else ""},
            *[{"name": name, "type": "toggle", "label": label, "value": getattr(account, name) if connected else default} for name, label, default in flags],
            {"name": "finished_threshold_percent", "type": "number", "label": _("Mark completed at (%)"), "required": True,
             "attrs": {"min": 1, "max": 100, "step": 1},
             "value": round(account.finished_threshold * 100) if connected else 100,
             "help": _("Synced progress at or above this percentage is marked completed.")},
        ]
        forms["koreader"] = _form(request, "koreader", "koreader_settings" if connected else "koreader_connect", fields,
                                  None if connected else prefs, submit="Save settings" if connected else "Connect & Import")
    elif slug == "jellyfin":
        forms["jellyfin_events"] = _form(request, "jellyfin-events", "update_jellyfin_webhook_events", [
            {"name": "jellyfin_mark_played_enabled", "type": "toggle", "label": _("Process MarkPlayed events"),
             "help": _("Mark media as watched when it is manually marked played in Jellyfin."), "value": bool(user.jellyfin_mark_played_enabled)},
            {"name": "jellyfin_mark_unplayed_enabled", "type": "toggle", "tone": "warning", "label": _("Process MarkUnplayed events"),
             "help": _("Remove watched progress when it is manually marked unplayed in Jellyfin. This event can delete media from Floppy."),
             "value": bool(user.jellyfin_mark_unplayed_enabled)},
        ])
    elif slug == "seerr":
        automation = [
            {"name": "jellyseerr_enabled", "type": "select", "label": _("Auto-add requested media"),
             "help": _("Controls whether Seerr webhooks are allowed to add items to your Floppy list."),
             "value": "enabled" if user.jellyseerr_enabled else "disabled",
             "options": [{"value": "enabled", "label": _("Enabled - Allow Seerr to automatically add media")},
                         {"value": "disabled", "label": _("Disabled - Do not allow Seerr to add media")}]},
            {"name": "jellyseerr_trigger_statuses", "type": "text", "label": _("Trigger statuses (comma-separated)"),
             "help": _("Examples: PENDING,PROCESSING,PARTIALLY_AVAILABLE,AVAILABLE. Leave blank for default behaviour (UNKNOWN is ignored)."),
             "placeholder": _("PENDING,PROCESSING,PARTIALLY_AVAILABLE,AVAILABLE"), "value": user.jellyseerr_trigger_statuses},
            {"name": "jellyseerr_allowed_usernames", "type": "text", "label": _("Allowed Seerr usernames (comma-separated)"),
             "help": _("Leave blank to allow any requester. If set, only those usernames can trigger adds."),
             "placeholder": _("john, someoneelse"), "value": user.jellyseerr_allowed_usernames},
            {"name": "jellyseerr_default_added_status", "type": "select", "label": _("Default Floppy status for added items"),
             "value": user.jellyseerr_default_added_status or "Planning",
             "options": [{"value": "Planning", "label": _("Planning")}, {"value": "In progress", "label": _("In progress")}]},
        ]
        connection = [
            {"name": "seerr_url", "type": "url", "label": _("Seerr URL"), "placeholder": "http://192.168.1.10:5055", "value": user.seerr_url,
             "help": _("Connect Seerr to request movies and shows from their Floppy page.")},
            {"name": "seerr_api_key", "type": "password", "label": _("Seerr API key"),
             "placeholder": _("Saved - leave blank to keep") if user.seerr_api_key else _("Settings > General > API Key")},
            {"name": "seerr_username", "type": "text", "label": _("Seerr username"), "value": user.seerr_username,
             "help": _("Required. The username or email you sign in to Seerr with (Plex and Jellyfin logins work too). Requests are made as this user, with their permissions, quotas and approval rules.")},
        ]
        carry_automation = {"jellyseerr_enabled": "1" if user.jellyseerr_enabled else "0",
                            "jellyseerr_trigger_statuses": user.jellyseerr_trigger_statuses,
                            "jellyseerr_allowed_usernames": user.jellyseerr_allowed_usernames,
                            "jellyseerr_default_added_status": user.jellyseerr_default_added_status}
        carry_connection = {"seerr_url": user.seerr_url, "seerr_username": user.seerr_username}
        if tab == "tracking":
            forms["seerr_settings"] = _form(request, "seerr-automation", "update_jellyseerr_settings", automation, carry_connection)
        elif tab == "connection":
            forms["seerr_settings"] = _form(request, "seerr-connection", "update_jellyseerr_settings", connection, carry_automation)
    return forms
