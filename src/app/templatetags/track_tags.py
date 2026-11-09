"""Shared tracking-form presentation for the song and episode web modals.

The server keeps the Django forms, permissions and htmx responses. These tags
serialize the same values into the shared TrackForm model so the browser adapter
can render the form while the legacy markup stays as the no-JavaScript fallback.
"""

from datetime import date, datetime
from urllib.parse import quote
from uuid import uuid4

from django import template
from django.conf import settings
from django.middleware.csrf import get_token
from django.urls import reverse
from django.utils.translation import gettext, pgettext

from app.track_modal_views import _track_form_date_value, _track_form_labels

register = template.Library()


def _csrf_token(context):
    request = context.get("request")
    if request is not None:
        return get_token(request)
    return str(context.get("csrf_token") or "")


def _iso_date(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value or "")[:10]


def _date_field(name, label, value, *, suggestion_date="", suggestion_label=""):
    quick_actions = [
        {
            "id": "just-finished",
            "label": str(pgettext("date picker shortcut", "Just Finished")),
        },
    ]
    if suggestion_date:
        quick_actions.append(
            {
                "id": "release-date",
                "label": str(
                    pgettext("date picker shortcut", suggestion_label or "Release Date"),
                ),
                "requiresSuggestion": True,
            },
        )
    return {
        "name": name,
        "label": label,
        "type": "date",
        "value": value,
        "required": False,
        "options": [],
        "help": "",
        "min": None,
        "max": None,
        "step": None,
        "placeholder": "",
        "quickActions": quick_actions,
        "suggestionDate": suggestion_date,
        "suggestionLabel": suggestion_label if suggestion_date else "",
        "suggestionExtras": [],
    }


@register.simple_tag(takes_context=True)
def song_track_form(context, album, track, music):
    """Serialize a song or podcast-episode listen/play form."""
    if track is None:
        return None
    is_podcast = bool(
        (music and getattr(getattr(music, "item", None), "media_type", "") == "podcast")
        or getattr(track, "episode_uuid", None)
    )
    track_time = bool(settings.TRACK_TIME)
    if is_podcast:
        hidden = {
            "episode_uuid": getattr(track, "episode_uuid", "") or "",
            "show_id": str(getattr(album, "id", "") or ""),
            "episode_id": str(getattr(track, "id", "") or ""),
        }
        action = reverse("podcast_save")
        target = (
            f'[data-episode-uuid="{track.episode_uuid}"]'
            if getattr(track, "episode_uuid", None)
            else ""
        )
        swap = "outerHTML"
        title = str(gettext("Track Episode"))
        date_label = str(gettext("Play Date"))
        submit_label = str(gettext("Add play"))
        suggestion = _iso_date(getattr(track, "published", None))
    else:
        hidden = {
            "recording_id": getattr(track, "musicbrainz_recording_id", "") or "",
            "album_id": str(getattr(album, "id", "") or ""),
            "track_id": str(getattr(track, "id", "") or ""),
        }
        action = reverse("song_save")
        target = ""
        swap = "none"
        title = str(gettext("Track Song"))
        date_label = str(gettext("Listen Date"))
        submit_label = str(gettext("Add listen"))
        suggestion = _iso_date(getattr(album, "release_date", None))

    end_date = getattr(music, "end_date", None) if music else None
    form_id = f"track-song-form-{getattr(track, 'id', 'track')}"
    return {
        "mediaType": "podcast" if is_podcast else "music",
        "variant": "song",
        "title": title,
        "titleSubtitle": "",
        "formId": form_id,
        "instanceId": str(getattr(music, "id", "") or ""),
        "isNew": music is None,
        "action": action,
        "deleteAction": "",
        "csrfToken": _csrf_token(context),
        "fields": [
            _date_field(
                "end_date",
                date_label,
                _track_form_date_value(end_date, track_time),
                suggestion_date=suggestion,
                suggestion_label=str(gettext("Release Date")),
            ),
        ],
        "hidden": hidden,
        "notes": None,
        "submitLabel": submit_label,
        "deleteLabel": str(gettext("Delete")),
        "trackTime": track_time,
        "labels": _track_form_labels(),
        "repeatIdentity": None,
        "secondaryActions": [],
        "target": target,
        "swap": swap,
        "legacyIds": [],
    }


@register.simple_tag(takes_context=True)
def episode_track_form(context, media, episode):
    """Serialize an episode watch/drop form."""
    if media is None or episode is None:
        return None
    request = context.get("request")
    next_path = getattr(request, "path", "") or ""
    next_query = f"?next={quote(next_path)}" if next_path else ""
    track_time = bool(settings.TRACK_TIME)
    hidden = {
        "media_id": getattr(media, "media_id", "") or "",
        "season_number": str(getattr(media, "season_number", "") or ""),
        "source": getattr(media, "source", "") or "",
        "episode_number": str(getattr(episode, "episode_number", "") or ""),
        "watch_operation_id": str(uuid4()),
    }
    library_media_type = getattr(media, "library_media_type", "") or ""
    if library_media_type:
        hidden["library_media_type"] = library_media_type
    form_id = (
        f"track-episode-form-{getattr(media, 'season_number', '')}"
        f"-{getattr(episode, 'episode_number', '')}"
    )
    action = reverse("episode_save") + next_query
    drop_action = reverse("episode_drop") + next_query
    return {
        "mediaType": "episode",
        "variant": "episode",
        "title": str(gettext("Track Episode")),
        "titleSubtitle": "",
        "formId": form_id,
        "instanceId": "",
        "isNew": True,
        "action": action,
        "deleteAction": "",
        "csrfToken": _csrf_token(context),
        "fields": [
            _date_field(
                "end_date",
                str(gettext("Watch Date")),
                "",
                suggestion_date=_iso_date(getattr(episode, "air_date", None)),
                suggestion_label=str(gettext("Release Date")),
            ),
        ],
        "hidden": hidden,
        "notes": None,
        "submitLabel": str(gettext("Add watch")),
        "deleteLabel": str(gettext("Delete")),
        "trackTime": track_time,
        "labels": _track_form_labels(),
        "repeatIdentity": None,
        "secondaryActions": [
            {
                "key": "drop",
                "label": str(gettext("Drop")),
                "tone": "surface",
                "url": drop_action,
                "body": {},
            },
        ],
        "target": "",
        "swap": "none",
        "legacyIds": [
            f"episode-watch-{getattr(media, 'season_number', '')}"
            f"-{getattr(episode, 'episode_number', '')}",
            f"episode-drop-{getattr(media, 'season_number', '')}"
            f"-{getattr(episode, 'episode_number', '')}",
            f"episode-track-legacy-actions-{getattr(media, 'season_number', '')}"
            f"-{getattr(episode, 'episode_number', '')}",
        ],
    }
