"""Setup guides for webhook-style integrations, shared by the provider Connection tabs.

Each guide is data: ordered steps made of text, emphasis, links and copyable values.
Copyable values hold the webhook URL (which embeds the account token), so they are
never serialized; the server fallback renders them and the browser reads them from it.
"""

from django.urls import reverse
from django.utils.translation import gettext as _

from app import helpers as app_helpers

JELLYFIN_TEMPLATE = '{\n  "Event": "{{#if_equals NotificationType \'PlaybackStart\'}}Play{{/if_equals}}{{#if_equals NotificationType \'PlaybackStop\'}}Stop{{/if_equals}}{{#if_equals NotificationType \'PlaybackProgress\'}}{{#if IsPaused}}Pause{{else}}Play{{/if}}{{/if_equals}}{{#if_equals NotificationType \'UserDataSaved\'}}UserDataSaved{{/if_equals}}{{#if_equals NotificationType \'ItemAdded\'}}ItemAdded{{/if_equals}}{{#if_equals NotificationType \'ItemDeleted\'}}ItemDeleted{{/if_equals}}",\n  "PlaybackPositionTicks": "{{PlaybackPositionTicks}}",{{#if_equals NotificationType \'UserDataSaved\'}}\n  "SaveReason": "{{SaveReason}}",{{/if_equals}}\n  "Item": {\n    "Id": "{{ItemId}}",\n    "Type": "{{ItemType}}",\n    "Name": "{{Name}}",\n    "ProductionYear": "{{Year}}",\n    "ProviderIds": {\n      "Tmdb": "{{Provider_tmdb}}",\n      "Imdb": "{{Provider_imdb}}",\n      "Tvdb": "{{Provider_tvdb}}"\n    },\n    "UserData": {\n      "Played": {{#if_equals NotificationType \'UserDataSaved\'}}{{#if_equals Played \'True\'}}true{{else}}false{{/if_equals}}{{else}}{{#if_equals PlayedToCompletion \'True\'}}true{{else}}false{{/if_equals}}{{/if_equals}},\n      "LastPlayedDate": "{{LastPlayedDate}}"{{#if_equals NotificationType \'UserDataSaved\'}}{{#if Rating}},\n      "Rating": {{Rating}}{{/if}}{{/if_equals}}\n    }{{#if_equals ItemType \'Episode\'}},\n    "SeriesName": "{{SeriesName}}",\n    "ParentIndexNumber": {{SeasonNumber}},\n    "IndexNumber": {{EpisodeNumber}}\n    {{/if_equals}}\n  }\n}'

SEERR_TEMPLATE = """{
  "media_type": "{{media_type}}",
  "media_tmdbid": "{{media_tmdbid}}",
  "media_status": "{{media_status}}",
  "requestedBy_username": "{{requestedBy_username}}"
}"""


def _t(text):
    return ("t", _(text))


def _b(text):
    return ("b", _(text))


def _em(text):
    return ("em", _(text))


def _pre(text):
    return ("pre", text)


def _code(text):
    return ("code", text)


def _clink(text, key):
    """Return a link part whose address embeds the account token and comes from the server fallback."""
    return ("clink", _(text), key)


def _a(text, url):
    return ("a", _(text), url)


def _copy(key):
    return ("copy", key)


def _guide(title, description, steps, copy, warning=None, notes=()):
    return {
        "title": title, "description": description, "steps": steps, "warning": warning, "notes": list(notes),
        "heading": _("Setup Instructions"), "copyLabel": _("Copy"), "copiedLabel": _("Copied"),
    }, copy


def setup_guide(request, slug):
    """Return (guide model, {copy key: value}) for a provider, or (None, {})."""
    absolute = lambda path: app_helpers.build_absolute_app_url(request, path)  # noqa: E731
    tokens = reverse("access_tokens") + "#app-tokens"
    if slug == "emby":
        url = absolute(reverse("emby_webhook", args=[request.user.token]))
        return _guide(_("Emby Integration"), _("Connect Emby to automatically track your watching progress."), [
            [_t("In Emby, go to"), _b("Settings > Notifications"), _t(".")],
            [_t("Click"), _b("Add Notification"), _t(".")],
            {"parts": [_t("Configure the notification with the following settings:")], "items": [
                [_t("Request content type:"), _b("multipart/form-data")],
                [_t("Events:"), _b("Play"), _t("and"), _b("Stop")],
                [_t("Limit user events to: your Emby user")],
                [_b("Limit library events to"), _t("and"), _b("Limit devices events to"), _t("are optional.")],
            ]},
            [_t("Set the webhook URL to:"), _copy("webhook")],
        ], {"webhook": url})
    if slug == "kodi":
        url = absolute(reverse("kodi_webhook", args=[request.user.token]))
        return _guide(_("Kodi Integration"), _("Connect Kodi to automatically track your watching progress."), [
            [_t("You will need TMDB and/or TVDB metadata sources enabled in Kodi so that external IDs are included in webhook payloads.")],
            [_t("Download and install the"), _a("HTTP Scrobbler add-on", "https://github.com/sboddy/KodiAddon-HttpScrobbler"), _t(".")],
            [_t("In Kodi, go to"), _b("Settings > Services > Control"), _t("and enable"), _b("Allow remote control via HTTP"), _t(".")],
            [_t("In the HTTP Scrobbler add-on settings, set the webhook URL to:"), _copy("webhook")],
            [_em("Tip: open the Kodi web interface at"), ("code", "http://<kodi-ip>:8080"), _em("to configure the add-on — easier than using the remote.")],
            [_t("Leave the username and password fields blank.")],
            [_t("If you use the add-on's"), _b("Skip all events after sending stop/end"),
             _t("option, turn it off — it can suppress the events Floppy needs to mark an episode watched.")],
            [_t("An item is marked watched when playback reaches 80% or Kodi reports"), _em("Playback finished"), _t(".")],
        ], {"webhook": url})
    if slug == "navidrome":
        url = absolute("/apis/listenbrainz/1/")
        return _guide(_("Navidrome Integration"),
                      _("Record what you play in Navidrome through its built-in ListenBrainz scrobbler. Needs music tracking turned on."), [
            [_t("Set ND_LISTENBRAINZ_BASEURL in Navidrome to this address and restart it. This applies to every Navidrome user."), _copy("webhook")],
            [_t("Create an"), _a("app token", tokens), _t("in Access & Tokens and copy its secret.")],
            [_t("In Navidrome, go to Personal, turn on Scrobble to ListenBrainz and paste the secret.")],
        ], {"webhook": url})
    if slug == "nuvio":
        url = absolute("/")
        return _guide(_("Nuvio Integration"),
                      _("Not supported yet. A Floppy tracker for Nuvio TV has been proposed but isn't in any Nuvio release."), [
            [_t("Create an"), _a("app token", tokens),
             _t("in Access & Tokens, named after the device. The default permissions already cover everything Nuvio needs.")],
            [_t("Copy the token secret when it's shown — Floppy only displays it once.")],
            [_t("In a Nuvio TV build with the Floppy tracker, enter this Server URL and the token secret you copied:"), _copy("webhook")],
            [_t("Revoke the token in"), _a("App tokens", tokens), _t("to disconnect the device. This never deletes your tracking data.")],
        ], {"webhook": url})
    return None, {}


def setup_guides(request, slug, context):
    """Return ([guide models], {copy key: value}); a provider can show several guides."""
    if slug == "jellyfin":
        url = app_helpers.build_absolute_app_url(request, reverse("jellyfin_webhook", args=[request.user.token]))
        warning = {"title": _("Webhook template needs updating"),
                   "text": _("Floppy is receiving updates from an older Jellyfin webhook template. Re-copy the template below into the Webhook plugin so the watched checkmark you set in Jellyfin can sync.")} \
            if context.get("jellyfin_template_outdated") else None
        official, _copy_values = _guide(
            _("Jellyfin Integration (Official Repo)"),
            _("Connect Jellyfin to automatically track your watching progress. Use this method if your server has access to the official Jellyfin plugin repository."), [
                [_t("You will need to have TMDB and TVDB as metadata providers in Jellyfin.")],
                [_t("Install the Webhook plugin from the Jellyfin Stable repo via your server's Plugin Catalog.")],
                [_t("Restart your server, then open the Webhook plugin and click"), _b("Add Generic Destination"), _t(".")],
                {"parts": [_t("Configure the webhook with the following settings:")], "items": [
                    [_t("Name:"), _b("Floppy")],
                    [_t("Notification Type:"), _b("Playback Start"), _b("Playback Stop"), _b("Playback Progress"), _b("User Data Saved"),
                     _b("Item Added"), _t(", and"), _b("Item Deleted")],
                    [_t("User Filter: your Jellyfin user")],
                ]},
                [_t("Set the webhook URL to:"), _copy("webhook")],
                [_t("Under the"), _b("Template"), _t("section, paste the following JSON:"), _pre(JELLYFIN_TEMPLATE)],
            ], {"webhook": url}, warning=warning)
        unofficial, _copy_values = _guide(
            _("Jellyfin Integration (Unofficial Repo)"),
            _("An alternative setup using an unofficial webhook plugin from a community repository. Use this method if the official Jellyfin plugin repository is not accessible from your server."), [
                [_t("You will need to have TMDB and TVDB as metadata providers in Jellyfin.")],
                [_t("In Jellyfin, go to"), _b("Dashboard > Plugins > Repositories"), _t("and add the following repository URL:"),
                 _a("https://raw.githubusercontent.com/shemanaev/jellyfin-plugin-repo/master/manifest.json",
                    "https://raw.githubusercontent.com/shemanaev/jellyfin-plugin-repo/master/manifest.json")],
                [_t("From the Plugin Catalog, install the"), _a("Unofficial Webhooks plugin", "https://github.com/shemanaev/jellyfin-plugin-webhooks"), _t(".")],
                {"parts": [_t("Restart your server, then open the Unofficial Webhooks plugin and configure it:")], "items": [
                    [_t("Payload format:"), _b("Default")],
                    [_t("Listen to events only for: your Jellyfin user")],
                    [_t("Events:"), _b("Play"), _b("Stop"), _b("MarkPlayed"), _b("MarkUnplayed"), _b("ItemAdded"), _t(", and"), _b("ItemRemoved")],
                ]},
                [_t("Set the webhook URL to:"), _copy("webhook")],
            ], {"webhook": url})
        return [official, unofficial], {"webhook": url}
    if slug == "seerr":
        url = app_helpers.build_absolute_app_url(request, reverse("jellyseerr_webhook", args=[request.user.token]))
        copy = {"webhook": url}
        guides = [_guide(
            _("Seerr Integration"), _("Use a Seerr webhook to automatically add requested/approved media into Floppy."), [
                [_t("In Seerr, go to"), _b("Settings > Notifications > Webhook"), _t(".")],
                [_t("Create a webhook with method"), _b("POST"), _t("and content type"), _b("application/json"), _t(".")],
                [_t("Set the webhook URL to:"), _copy("webhook")],
                [_t("Paste this"), _b("JSON Payload"), _t("template into Seerr:"), _pre(SEERR_TEMPLATE),
                 _t("Important: Seerr's default payload will not work with Floppy. You must use the template above. If you see logs like"),
                 _code("unsupported media_type='{media_type}'"), _t(", Seerr is sending the literal template (it was pasted/escaped incorrectly).")],
                [_t("Select the notification types you want (commonly request/approval events).")],
            ], copy)[0]]
        if context.get("seerr_global_webhook_enabled"):
            copy["global"] = app_helpers.build_absolute_app_url(request, reverse("seerr_global_webhook"))
            guides.append(_guide(
                _("Global Webhook (multi-user households)"),
                _("Seerr only supports one webhook per instance. If multiple Floppy users share the same Seerr/Overseerr instance, point Seerr at this single global URL instead of a per-user one."), [
                    [_t("In Seerr, go to"), _b("Settings > Notifications > Webhook"), _t(".")],
                    [_t("Create a webhook with method"), _b("POST"), _t("and content type"), _b("application/json"), _t(".")],
                    [_t("Set the webhook URL to:"), _copy("global")],
                    [_t("Paste this"), _b("JSON Payload"), _t("template into Seerr, replacing"), _code("REPLACE_WITH_SHARED_SECRET"),
                     _t("with the value your administrator configured in"), _code("SEERR_GLOBAL_WEBHOOK_SECRET"), _t(":"),
                     _pre(SEERR_TEMPLATE.replace('"{{requestedBy_username}}"', '"{{requestedBy_username}}",\n  "secret": "REPLACE_WITH_SHARED_SECRET"'))],
                ], copy)[0])
        return guides, copy
    if slug == "stremio":
        grants = context.get("catalog_grants")
        credential = grants[0].token if grants else request.user.token
        addon = app_helpers.build_absolute_app_url(request, reverse("stremio_addon_manifest", args=[credential]))
        configure = reverse("stremio_addon_configure", args=[request.user.token])
        guide, _copy_values = _guide(
            _("Stremio Integration"),
            _("Install the Floppy Scrobbler addon in Stremio to mark movies and episodes as in progress the moment playback starts."), [
                [_t("Copy your personal addon URL:"), _copy("webhook")],
                [_t("Optional:"), _clink("choose which catalogs", "configure"),
                 _t("the addon publishes, then use the URL it gives you in place of the one above.")],
                [_t("In Stremio, open"), _b("Addons"), _t(", paste the URL into the search box at the top, and click"), _b("Install"), _t(".")],
                [_t("Floppy must be reachable from your Stremio device over"), _b("HTTPS"), _t("(plain HTTP only works for localhost).")],
                [_t("Playback start marks the item in progress; the recurring library import marks items watched.")],
            ], {"webhook": addon})
        guide["bare"] = True
        return [guide], {"webhook": addon, "configure": configure}
    guide, copy = setup_guide(request, slug)
    return ([guide] if guide else []), copy
