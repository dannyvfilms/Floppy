"""Setup guides for webhook-style integrations, shared by the provider Connection tabs.

Each guide is data: ordered steps made of text, emphasis, links and copyable values.
Copyable values hold the webhook URL (which embeds the account token), so they are
never serialized; the server fallback renders them and the browser reads them from it.
"""

from django.urls import reverse
from django.utils.translation import gettext as _

from app import helpers as app_helpers


def _t(text):
    return ("t", _(text))


def _b(text):
    return ("b", _(text))


def _em(text):
    return ("em", _(text))


def _a(text, url):
    return ("a", _(text), url)


def _copy(key):
    return ("copy", key)


def _guide(title, description, steps, copy):
    return {
        "title": title, "description": description, "steps": steps,
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
