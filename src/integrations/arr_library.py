"""Live Radarr/Sonarr details for one title, shown in the track modal (#1323).

Everything here is read when the tab opens and nothing is stored, so there is
nothing to go stale and missing titles (which the collection sync skips) show
up too. The one write is "Search now", a search command sent to Radarr/Sonarr.

A panel is a plain dict the template renders. Failures never raise: a server
that cannot be reached becomes a panel with an ``error`` so one dead instance
does not hide the others. Messages are fixed text, never the exception, so the
configured URL is not echoed (docs/architecture/outbound-fetch.md).
"""

import logging

from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from app.models import MediaTypes, Sources
from integrations.imports.helpers import (
    ConnectionAuthError,
    MediaImportError,
    decrypt_or_raise,
)
from integrations.imports.radarr import RadarrClient
from integrations.imports.sonarr import SonarrClient
from integrations.safe_fetch import SelfHostedUrlError

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 8
SERIES_CACHE_SECONDS = 60
# Skipped as noise: a rename or an unknown event says nothing about downloading.
HIDDEN_EVENTS = {"unknown", "movieFileRenamed", "episodeFileRenamed"}
EVENT_LABELS = {
    "grabbed": ("Grabbed", "info"),
    "downloadFolderImported": ("Imported", "ok"),
    "movieFolderImported": ("Imported", "ok"),
    "seriesFolderImported": ("Imported", "ok"),
    "downloadFailed": ("Failed", "bad"),
    "downloadIgnored": ("Ignored", "warn"),
    "movieFileDeleted": ("File deleted", "warn"),
    "episodeFileDeleted": ("File deleted", "warn"),
}
SEARCH_KINDS = {"movie", "episode", "season", "series"}


def _when(value):
    """Parse an ISO timestamp from an Arr API, or return None."""
    return parse_datetime(value) if isinstance(value, str) else None


def _quality(row):
    quality = row.get("quality") or {}
    return (quality.get("quality") or {}).get("name") or ""


def _file_fields(file_row):
    file_row = file_row or {}
    return {
        "path": file_row.get("path") or "",
        "size": file_row.get("size") or 0,
        "quality": _quality(file_row),
        "added": _when(file_row.get("dateAdded")),
    }


def _queue_rows(rows):
    result = []
    for row in rows or []:
        size = row.get("size") or 0
        left = row.get("sizeleft") or 0
        result.append(
            {
                "title": row.get("title") or "",
                "state": row.get("trackedDownloadState") or row.get("status") or "",
                "percent": round(100 * (size - left) / size) if size else 0,
                "client": row.get("downloadClient") or "",
                "timeleft": row.get("timeleft") or "",
                "size": size,
            },
        )
    return result


def _history_rows(rows):
    result = []
    for row in sorted(rows or [], key=lambda r: r.get("date") or "", reverse=True):
        event = row.get("eventType") or "unknown"
        if event in HIDDEN_EVENTS:
            continue
        label, tone = EVENT_LABELS.get(event, (event, "info"))
        data = row.get("data") or {}
        result.append(
            {
                "when": _when(row.get("date")),
                "label": label,
                "tone": tone,
                "quality": _quality(row),
                "detail": data.get("message")
                or data.get("downloadClientName")
                or data.get("indexer")
                or "",
            },
        )
        if len(result) == HISTORY_LIMIT:
            break
    return result


def _status(has_file, queue):
    if queue:
        return "downloading", "Downloading"
    if has_file:
        return "has_file", "Has file"
    return "missing", "Missing"


def _panel(app, instance, **fields):
    return {
        "app": app,
        "name": instance.display_name,
        "instance_id": instance.pk,
        "error": "",
        "found": True,
        "queue": [],
        "history": [],
        "search": None,
        "url": "",
        **fields,
    }


def _web_url(instance, path):
    """Return the Radarr/Sonarr page for a title, on the address Floppy uses."""
    return f"{instance.base_url.rstrip('/')}/{path}"


def _absent_panel(app, instance, url=""):
    """Return the panel for a connected server that lacks this title."""
    return _panel(app, instance, found=False, status="absent", url=url)


def _error_panel(app, instance, error):
    if isinstance(error, ConnectionAuthError):
        message = f"{app} rejected the API key."
    elif isinstance(error, SelfHostedUrlError):
        message = f"Floppy is not allowed to call this {app} address."
    else:
        message = f"Can't reach {app}."
    return _panel(app, instance, error=message, found=False)


def _client(cls, instance):
    return cls(instance.base_url, decrypt_or_raise(instance.api_key))


def _radarr_panel(instance, tmdb_id):
    client = _client(RadarrClient, instance)
    row = client.movie_by_tmdb_id(tmdb_id)
    if not row:
        return _absent_panel("Radarr", instance)
    queue = _queue_rows(client.queue(row["id"]))
    status, label = _status(bool(row.get("hasFile")), queue)
    return _panel(
        "Radarr",
        instance,
        status=status,
        status_label=label,
        monitored=bool(row.get("monitored")),
        queue=queue,
        history=_history_rows(client.history(row["id"])),
        search={"kind": "movie", "arr_id": row["id"]},
        url=_web_url(instance, f"movie/{row.get('titleSlug') or tmdb_id}"),
        **_file_fields(row.get("movieFile")),
    )


def _series_row(client, instance, source, media_id):
    """Find the Sonarr series for a Floppy show; the list is cached briefly."""
    key = f"arr-series:{instance.pk}"
    rows = cache.get(key)
    if rows is None:
        rows = client.series()
        cache.set(key, rows, SERIES_CACHE_SECONDS)
    field = "tvdbId" if source == Sources.TVDB.value else "tmdbId"
    for row in rows:
        if str(row.get(field) or "") == str(media_id):
            return row
    return None


def _aired(episode, now):
    aired = _when(episode.get("airDateUtc"))
    return aired is None or aired <= now


def _sonarr_panel(instance, source, media_id, media_type, season, episode_number):
    client = _client(SonarrClient, instance)
    series = _series_row(client, instance, source, media_id)
    if not series:
        return _absent_panel("Sonarr", instance)
    series_id = series["id"]
    url = (
        _web_url(instance, f"series/{series['titleSlug']}")
        if series.get("titleSlug")
        else ""
    )
    queue_rows = client.queue(series_id)
    fields = {"monitored": bool(series.get("monitored"))}

    if media_type == MediaTypes.TV.value:
        stats = series.get("statistics") or {}
        have, total = stats.get("episodeFileCount") or 0, stats.get("episodeCount") or 0
        history = client.history(series_id)
        search = {"kind": "series", "arr_id": series_id}
        queue = _queue_rows(queue_rows)
        fields["summary"] = (have, total)
        fields["path"] = series.get("path") or ""
        has_file = total > 0 and have >= total
    else:
        episodes = [
            e for e in client.episodes(series_id) if e.get("seasonNumber") == season
        ]
        now = timezone.now()
        if media_type == MediaTypes.EPISODE.value:
            episode = next(
                (e for e in episodes if e.get("episodeNumber") == episode_number),
                None,
            )
            if not episode:
                return _absent_panel("Sonarr", instance, url)
            episode_id = episode["id"]
            queue = _queue_rows(
                [r for r in queue_rows if r.get("episodeId") == episode_id]
            )
            history = [
                r
                for r in client.history(series_id, season)
                if r.get("episodeId") == episode_id
            ]
            has_file = bool(episode.get("hasFile"))
            fields.update(
                monitored=bool(episode.get("monitored")),
                **_file_fields(episode.get("episodeFile")),
            )
            search = {"kind": "episode", "arr_id": episode_id}
        else:
            aired = [e for e in episodes if e.get("monitored") and _aired(e, now)]
            have = sum(1 for e in aired if e.get("hasFile"))
            queue = _queue_rows(
                [r for r in queue_rows if r.get("seasonNumber") == season]
            )
            history = client.history(series_id, season)
            has_file = bool(aired) and have == len(aired)
            fields["summary"] = (have, len(aired))
            search = {"kind": "season", "arr_id": series_id, "season": season}

    status, label = _status(has_file, queue)
    return _panel(
        "Sonarr",
        instance,
        status=status,
        status_label=label,
        queue=queue,
        history=_history_rows(history),
        search=search,
        url=url,
        **fields,
    )


def library_panels(user, source, media_type, media_id, season=None, episode=None):
    """Return one panel per connected Radarr/Sonarr, marking titles it lacks."""
    panels = []
    if media_type == MediaTypes.MOVIE.value and source == Sources.TMDB.value:
        for instance in user.radarr_instances.all():
            if not instance.is_connected():
                continue
            try:
                panel = _radarr_panel(instance, media_id)
            except (MediaImportError, SelfHostedUrlError) as error:
                panel = _error_panel("Radarr", instance, error)
            if panel:
                panels.append(panel)
    elif media_type in (
        MediaTypes.TV.value,
        MediaTypes.SEASON.value,
        MediaTypes.EPISODE.value,
    ) and source in (Sources.TMDB.value, Sources.TVDB.value):
        for instance in user.sonarr_instances.all():
            if not instance.is_connected():
                continue
            try:
                panel = _sonarr_panel(
                    instance, source, media_id, media_type, season, episode
                )
            except (MediaImportError, SelfHostedUrlError) as error:
                panel = _error_panel("Sonarr", instance, error)
            if panel:
                panels.append(panel)
    return panels


def start_search(user, app, instance_id, kind, arr_id, season=None):
    """Send a search command to one of the user's own Radarr/Sonarr instances.

    Returns an error message, or "" when the search was started.
    """
    if kind not in SEARCH_KINDS or (kind == "movie") != (app == "Radarr"):
        return "Unknown search."
    if kind == "season" and season is None:
        return "Unknown search."
    instances = user.radarr_instances if app == "Radarr" else user.sonarr_instances
    instance = instances.filter(pk=instance_id).first()
    if instance is None or not instance.is_connected():
        return f"{app} is not connected."
    try:
        if kind == "movie":
            _client(RadarrClient, instance).search_movie(arr_id)
        else:
            command = {
                "episode": {"name": "EpisodeSearch", "episodeIds": [arr_id]},
                "season": {
                    "name": "SeasonSearch",
                    "seriesId": arr_id,
                    "seasonNumber": season,
                },
                "series": {"name": "SeriesSearch", "seriesId": arr_id},
            }[kind]
            _client(SonarrClient, instance).search(command)
    except (MediaImportError, SelfHostedUrlError) as error:
        logger.warning("%s search failed: %s", app, type(error).__name__)
        return f"Couldn't start the search in {app}."
    return ""


PLEX_WEB = "https://app.plex.tv/desktop/#!/server/{machine}/details?key=%2Flibrary%2Fmetadata%2F{key}"


def _plex_link(user, source, item_type, media_id):
    """Return the Plex web page for the viewer's copy, from the cached rating key."""
    from app.models import CollectionEntry

    # The copy is looked up before the account: most titles have no Plex copy,
    # and the missing account would cost its own query on every detail page.
    entry = (
        CollectionEntry.objects.filter(
            user=user,
            item__source=source,
            item__media_type=item_type,
            item__media_id=str(media_id),
            plex_rating_key__isnull=False,
        )
        .exclude(plex_rating_key="")
        .values("plex_rating_key", "plex_uri")
        .first()
    )
    if entry is None:
        return None
    account = getattr(user, "plex_account", None)
    if account is None:
        return None
    # A copy is on the server whose connection URI cached it.
    machine = next(
        (
            section.get("machine_identifier")
            for section in account.sections or []
            if isinstance(section, dict)
            and entry["plex_uri"]
            and section.get("uri") == entry["plex_uri"]
        ),
        None,
    ) or account.machine_identifier
    if not machine:
        return None
    return ("Plex", PLEX_WEB.format(machine=machine, key=entry["plex_rating_key"]), "plex")


def server_link_groups(user, source, media_type, media_id):
    """Return ``(title, [(label, url, brand)])`` groups for the detail links menu.

    Built from saved data only, so a detail page makes no call to any server:
    the Seerr address, the pages Radarr/Sonarr imports and the Jellyfin webhook
    record (``SourcePage``), and the rating key Plex caches on a copy.
    """
    if not getattr(user, "is_authenticated", False) or source not in (
        Sources.TMDB.value,
        Sources.TVDB.value,
    ):
        return []
    if media_type == MediaTypes.MOVIE.value:
        arr, item_type = "radarr", MediaTypes.MOVIE.value
    elif media_type in (
        MediaTypes.TV.value,
        MediaTypes.SEASON.value,
        MediaTypes.EPISODE.value,
    ):
        arr, item_type = "sonarr", MediaTypes.TV.value
    else:
        return []

    from integrations.models import SourcePage

    pages = list(
        SourcePage.objects.filter(
            user=user,
            source__in=(arr, "jellyfin"),
            provider=source,
            media_type=item_type,
            media_id=str(media_id),
        ).values_list("source", "source_instance_id", "path")
    )
    groups = []

    players = []
    plex = _plex_link(user, source, item_type, media_id)
    if plex:
        players.append(plex)
    # Emby is left out: it reports playback only, so it cannot say what is
    # on the server.
    jellyfin_pages = [
        (instance_id, path) for app, instance_id, path in pages if app == "jellyfin"
    ]
    jellyfin_accounts = list(user.jellyfin_accounts.order_by("id")) if jellyfin_pages else []
    # Page id 0 is the oldest connection, whose pages predate per-server keys.
    by_instance = {account.id: account for account in jellyfin_accounts}
    if jellyfin_accounts:
        by_instance[0] = jellyfin_accounts[0]
    for instance_id, path in jellyfin_pages:
        jellyfin = by_instance.get(instance_id)
        if jellyfin is not None:
            url = _web_url(jellyfin, path)
            if jellyfin.server_id:
                url += f"&serverId={jellyfin.server_id}"
            label = "Jellyfin"
            if len(jellyfin_accounts) > 1:
                label = f"Jellyfin ({jellyfin.display_name})"
            players.append((label, url, "jellyfin"))
    if players:
        groups.append(("Players", players))

    if user.seerr_url and source == Sources.TMDB.value:
        seerr_type = "movie" if arr == "radarr" else "tv"
        url = f"{user.seerr_url.rstrip('/')}/{seerr_type}/{media_id}"
        groups.append(("Requests", [("Seerr", url, "seerr")]))

    arr_pages = [(instance_id, path) for app, instance_id, path in pages if app == arr]
    instances = (
        {instance.pk: instance for instance in getattr(user, f"{arr}_instances").all()}
        if arr_pages
        else {}
    )
    label = "Radarr" if arr == "radarr" else "Sonarr"
    downloads = []
    for instance_id, path in arr_pages:
        instance = instances.get(instance_id)
        if instance is not None:
            name = f"{label} ({instance.name})" if instance.name else label
            downloads.append((name, _web_url(instance, path), arr))
    if downloads:
        groups.append(("Downloads", downloads))
    return groups
