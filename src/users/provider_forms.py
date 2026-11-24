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


def _connection_status(user, account):
    """One status line per fact worth showing about a saved Jellyfin connection."""
    from users.templatetags.user_tags import user_datetime_format

    parts = [account.base_url]
    if account.jellyfin_username:
        parts.append(account.jellyfin_username)
    if account.last_sync_at:
        parts.append(_("Last sync: %(when)s") % {"when": user_datetime_format(account.last_sync_at, user)})
    lines = [" • ".join(parts)]
    if account.connection_broken:
        lines.append(_("Jellyfin rejected the API key. Floppy re-checks it on every scheduled run; reconnect if the key was changed or revoked."))
    if account.last_error_message:
        lines.append(_("Error: %(message)s") % {"message": account.last_error_message})
    return "\n".join(lines)


def _pull_status(user, account):
    """Describe the history pull's mode, last run and last error for one connection."""
    from users.templatetags.user_tags import user_datetime_format

    if account.playback_reporting_available:
        line = _("Using Playback Reporting's API (full per-play history).")
    elif account.playback_reporting_available is False:
        line = _("Playback Reporting's API isn't reachable with this key, so Floppy is using the current-watched-state backfill instead (one event per item).")
    else:
        line = _("Not yet run.")
    if account.last_pull_at:
        line += " " + _("Last run: %(when)s.") % {"when": user_datetime_format(account.last_pull_at, user)}
    if account.last_pull_error_message:
        line += "\n" + _("Error: %(message)s") % {"message": account.last_pull_error_message}
    return line


def jellyfin_connection_forms(request, tab, accounts, pull_interval_minutes):
    """Ordered ``[(key, form)]`` for each Jellyfin connection's Sync or Import tab.

    One form set per connection, every action addressed by ``account_id``, so the
    web islands and the native client render the same cards. Each model carries its
    ``tab`` so a client shows only the forms that belong to the tab it is on. A
    toggle left off is simply not posted, which the views read as off.
    """
    user = request.user
    several = len(accounts) > 1
    forms = []
    for account in accounts:
        name = account.display_name if several or account.name else ""

        def titled(heading, name=name):
            return f"{heading}: {name}" if name else heading

        base = {"account_id": account.id}
        toggles = {
            "pull_history_enabled": account.pull_history_enabled,
            "push_watched_enabled": account.push_watched_enabled,
            "push_unwatched_enabled": account.push_unwatched_enabled,
            "scheduled_push_enabled": account.scheduled_push_enabled,
            "instant_push_enabled": account.instant_push_enabled,
        }

        def carry(*names, toggles=toggles):
            return {name: "on" for name in names if toggles[name]}

        if tab == "sync":
            sync = _form(request, f"jellyfin-sync-{account.id}", "jellyfin_settings", [
                {"name": "push_watched_enabled", "type": "toggle", "onValue": "on",
                 "label": _("Push watched status to Jellyfin"), "value": account.push_watched_enabled},
                {"name": "push_unwatched_enabled", "type": "toggle", "onValue": "on",
                 "label": _("Push unwatched status to Jellyfin"), "value": account.push_unwatched_enabled},
                {"name": "scheduled_push_enabled", "type": "toggle", "onValue": "on",
                 "label": _("Sync on a schedule (hourly)"), "value": account.scheduled_push_enabled},
                {"name": "instant_push_enabled", "type": "toggle", "onValue": "on",
                 "label": _("Instant push after playback events"), "value": account.instant_push_enabled},
            ], {**base, **carry("pull_history_enabled")}, submit="Save Settings")
            sync.update(tab="sync", title=titled(_("Floppy → Jellyfin")), intro=_connection_status(user, account))
            forms.append((f"jellyfin_sync_{account.id}", sync))
            push = _form(request, f"jellyfin-push-{account.id}", "jellyfin_push_now", [], base, submit="Sync Now")
            push.update(tab="sync", title=titled(_("Push watched status now")), intro=_("Push your Floppy watched status onto this Jellyfin server now, e.g. after re-adding media or setting up a fresh Jellyfin instance."))
            forms.append((f"jellyfin_push_{account.id}", push))
        elif tab == "import":
            history = _form(request, f"jellyfin-history-{account.id}", "jellyfin_settings", [
                {"name": "pull_history_enabled", "type": "toggle", "onValue": "on",
                 "label": _("Automatically import new Jellyfin history (every %(minutes)s minutes)") % {"minutes": pull_interval_minutes},
                 "value": account.pull_history_enabled},
            ], {**base, **carry("push_watched_enabled", "push_unwatched_enabled",
                                "scheduled_push_enabled", "instant_push_enabled")}, submit="Save Settings")
            history.update(tab="import", title=titled(_("Jellyfin → Floppy")), intro=_pull_status(user, account))
            forms.append((f"jellyfin_history_{account.id}", history))
            pull = _form(request, f"jellyfin-pull-{account.id}", "jellyfin_pull_now", [], base, submit="Import history now")
            pull.update(tab="import", title=titled(_("Import history now")), intro=_(
                "No manual export needed. Floppy pulls your watch history straight from your Jellyfin server: full per-play history via the Playback Reporting plugin's API when it's reachable with an admin key, otherwise a one-event-per-item backfill of what Jellyfin currently marks as watched."))
            forms.append((f"jellyfin_pull_{account.id}", pull))
    return forms


def build(request, slug, tab, context):
    """Return {form key: model} for the integration forms a provider tab shows."""
    user = request.user
    forms = {}
    if slug == "jellyfin":
        forms.update(jellyfin_connection_forms(
            request, tab, context.get("jellyfin_accounts") or [], context.get("jellyfin_pull_interval_minutes", 15)))
    if slug in {"plex", "jellyfin", "emby", "kodi", "stremio"}:
        # The web shows this as a standalone card on the tracking tab; it is
        # an option form for clients that render forms from data.
        forms["group_scrobbled_anime"] = _form(
            request, "group-scrobbled-anime", "update_group_scrobbled_anime", [{
                "name": "enabled", "type": "toggle", "onValue": "true",
                "label": _("Track scrobbled anime per episode"), "value": bool(user.group_scrobbled_anime),
                "help": _("When a media server or scrobbler reports an episode of an anime you track as a MAL entry, or you mark that entry completed, convert it to per-episode tracking so each watched episode shows as watched. This is the same conversion as marking an episode by hand. MAL sync keeps working after the conversion."),
            }], submit="Save")
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
