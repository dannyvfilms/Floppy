import calendar
import contextlib
import logging
import time
from collections import defaultdict
from datetime import date, timedelta
from itertools import pairwise
from urllib.parse import urlencode

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import EmptyPage, Paginator
from django.db.models.functions import ExtractDay, ExtractMonth
from django.db.utils import OperationalError
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotFound
from django.shortcuts import render
from django.utils import formats, timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_noop
from django.views.decorators.http import require_GET, require_http_methods

from app import (
    fork_services_history,
    helpers,
    history_cache,
    history_cache_reader,
    history_processor,
)
from app import statistics as stats
from app.models import (
    Anime,
    BasicMedia,
    BoardGame,
    Book,
    Comic,
    Episode,
    Game,
    Manga,
    MediaTypes,
    Movie,
    Podcast,
)

logger = logging.getLogger(__name__)

MONTHS_PER_YEAR = 12
SESSION_HISTORY_MAX_DAYS = 400

_MONTH_CACHE_UNSUPPORTED_FILTER_KEYS = frozenset(
    {
        "artist",
        "person_id",
        "person_source",
        "season",
        "season_number",
        "tv",
    },
)


@require_GET
def history_modal(
    request,
    source,
    media_type,
    media_id,
    season_number=None,
    episode_number=None,
):
    """Return the history page for a media item."""
    instance_id = request.GET.get("instance_id")
    if instance_id:
        try:
            media = BasicMedia.objects.get_media(
                request.user,
                media_type,
                instance_id,
            )
            user_medias = [media]
        except (ObjectDoesNotExist, ValueError, TypeError):
            user_medias = BasicMedia.objects.filter_media(
                request.user,
                media_id,
                media_type,
                source,
                season_number=season_number,
                episode_number=episode_number,
            )
    else:
        user_medias = BasicMedia.objects.filter_media(
            request.user,
            media_id,
            media_type,
            source,
            season_number=season_number,
            episode_number=episode_number,
        )

    try:
        total_medias = user_medias.count()
    except TypeError:
        total_medias = len(user_medias)
    timeline_entries = []
    for index, media in enumerate(user_medias, start=1):
        history = (
            media.history.filter(end_date__isnull=False)
            if hasattr(media.history, "filter")
            else [h for h in media.history.all() if h.end_date]
        )
        if history:
            media_entry_number = total_medias - index + 1
            timeline_entries.extend(
                history_processor.process_history_entries(
                    history,
                    media_type,
                    media_entry_number,
                    request.user,
                ),
            )
    return render(
        request,
        "app/components/fill_history.html",
        {
            "user": request.user,
            "media_type": media_type,
            "timeline": timeline_entries,
            "total_medias": total_medias,
            "return_url": request.GET.get("return_url", ""),
        },
    )


@require_http_methods(["DELETE"])
def delete_history_record(request, media_type, history_id):
    """Delete a specific history record."""
    music_id = request.GET.get("music_id")
    podcast_id = request.GET.get("podcast_id")

    # FORK: deletion core shared with the REST API.
    try:
        fork_services_history.delete_history_record_core(
            request.user,
            media_type,
            history_id,
        )
    except fork_services_history.HistoryRecordNotFoundError:
        logger.exception(
            "History record %s not found for user %s",
            str(history_id),
            str(request.user),
        )
        return HttpResponse("Record not found", status=404)
    except fork_services_history.HistoryDeletionError as e:
        return HttpResponse(str(e), status=500)

    if music_id and media_type.lower() == "music":
        from app.models import Music
        from users.templatetags.user_tags import user_date_format

        try:
            music = Music.objects.get(id=music_id, user=request.user)
            remaining_history = list(
                music.history.filter(
                    history_user=request.user,
                ).order_by("-end_date"),
            ) or list(
                music.history.filter(
                    history_user__isnull=True,
                ).order_by("-end_date"),
            )

            remaining_count = len(remaining_history)

            if remaining_count > 0:
                last_entry = remaining_history[0]
                last_date_formatted = (
                    user_date_format(last_entry.end_date, request.user)
                    if last_entry.end_date
                    else "No date provided"
                )

                if remaining_count == 1:
                    history_text = f"Last listened: {last_date_formatted}"
                else:
                    history_text = (
                        f"Last listened: {last_date_formatted} "
                        f"• Listened {remaining_count} times"
                    )

                response = HttpResponse()
                response.write(
                    f'<p id="track-history-{music_id}" hx-swap-oob="true" '
                    'class="text-xs text-gray-400 mt-2 px-4">'
                    f"{history_text}</p>",
                )
                modal_text = (
                    "Listened once"
                    if remaining_count == 1
                    else f"Listened {remaining_count} times"
                )
                response.write(
                    f'<p id="modal-listen-count-{music_id}" hx-swap-oob="true" '
                    'class="text-sm text-gray-400 mt-1">'
                    f"{modal_text}</p>",
                )
                return response
            response = HttpResponse()
            response.write(
                f'<p id="track-history-{music_id}" hx-swap-oob="true" '
                'class="text-xs text-gray-400 mt-2 px-4" style="display: none;"></p>',
            )
            response.write(
                f'<p id="modal-listen-count-{music_id}" hx-swap-oob="true" '
                'class="text-sm text-gray-400 mt-1">Not listened yet</p>',
            )
        except Music.DoesNotExist:
            pass
        else:
            return response

    if podcast_id and media_type.lower() == "podcast":
        from app.models import Podcast
        from users.templatetags.user_tags import user_date_format

        try:
            podcast = Podcast.objects.get(id=podcast_id, user=request.user)
            remaining_history = list(
                podcast.history.filter(
                    history_user=request.user,
                ).order_by("-end_date"),
            ) or list(
                podcast.history.filter(
                    history_user__isnull=True,
                ).order_by("-end_date"),
            )

            remaining_count = len(remaining_history)

            if remaining_count > 0:
                last_entry = remaining_history[0]
                last_date_formatted = (
                    user_date_format(last_entry.end_date, request.user)
                    if last_entry.end_date
                    else "No date provided"
                )

                if remaining_count == 1:
                    history_text = f"Last played: {last_date_formatted}"
                else:
                    history_text = (
                        f"Last played: {last_date_formatted} "
                        f"• Played {remaining_count} times"
                    )

                response = HttpResponse()
                modal_text = (
                    "Played once"
                    if remaining_count == 1
                    else f"Played {remaining_count} times"
                )
                response.write(
                    f'<p id="modal-listen-count-{podcast_id}" hx-swap-oob="true" '
                    'class="text-sm text-gray-400 mt-1">'
                    f"{modal_text}</p>",
                )
                response["HX-Trigger"] = "history-refresh-start"
                return response
            response = HttpResponse()
            response.write(
                f'<p id="modal-listen-count-{podcast_id}" hx-swap-oob="true" '
                'class="text-sm text-gray-400 mt-1">Not played yet</p>',
            )
            response["HX-Trigger"] = "history-refresh-start"
        except Podcast.DoesNotExist:
            pass
        else:
            return response

    response = HttpResponse()
    response["HX-Trigger"] = "history-refresh-start"
    return response


def _build_anniversary_history_days(user, month, day, logging_style=None):
    day_keys = history_cache.build_history_index(
        user, logging_style_override=logging_style
    )
    history_days = []
    for day_key in day_keys:
        try:
            day_date = date.fromisoformat(day_key)
        except ValueError:
            continue
        if day_date.month != month or day_date.day != day:
            continue
        day_payload = history_cache.build_history_day(
            user,
            day_date,
            logging_style_override=logging_style,
        )
        if day_payload and day_payload.get("entries"):
            history_days.append(day_payload)
    return history_days


def _build_release_history_days(
    user, month=None, day=None, date_filters=None, filters=None
):
    active_types = list(getattr(user, "get_active_media_types", list)())
    if not active_types:
        active_types = list(MediaTypes.values)
    include_podcasts = MediaTypes.PODCAST.value in active_types
    active_types = [
        media_type
        for media_type in active_types
        if media_type not in (MediaTypes.EPISODE.value, MediaTypes.PODCAST.value)
    ]

    media_type_filter_raw = (filters or {}).get("media_type")
    media_type_filters = (
        {t.strip() for t in media_type_filter_raw.split(",") if t.strip()}
        if media_type_filter_raw
        else set()
    )
    include_episodes = True
    if media_type_filters:
        tv_like_types = {
            MediaTypes.TV.value,
            MediaTypes.SEASON.value,
            MediaTypes.EPISODE.value,
        }
        other_types = media_type_filters - tv_like_types - {MediaTypes.PODCAST.value}
        include_episodes = bool(media_type_filters & tv_like_types)
        include_podcasts = MediaTypes.PODCAST.value in media_type_filters
        active_types = (
            [mt for mt in active_types if mt in other_types] if other_types else []
        )

    def _matches_genre_filters(item, *, album=None):
        active_filters = filters or {}
        genre_filter = active_filters.get("genre")
        if genre_filter:
            requested = {
                g.strip().lower() for g in genre_filter.split(",") if g.strip()
            }
            values = getattr(item, "genres", None) or []
            if album is not None:
                values = list(values) + list(getattr(album, "genres", None) or [])
            if not ({str(g).lower() for g in values} & requested):
                return False
        implied_genre_filter = active_filters.get("implied_genre")
        if implied_genre_filter:
            requested = {
                g.strip().lower() for g in implied_genre_filter.split(",") if g.strip()
            }
            values = getattr(item, "implied_genres", None) or []
            if album is not None:
                values = list(values) + list(
                    getattr(album, "implied_genres", None) or []
                )
            if not ({str(g).lower() for g in values} & requested):
                return False
        return True

    start_date = None
    end_date = None
    if date_filters:
        start_date = parse_date(date_filters.get("start_date") or "")
        end_date = parse_date(date_filters.get("end_date") or "")

    release_days = defaultdict(list)
    seen_item_ids = set()
    for media_type in active_types:
        model = apps.get_model("app", media_type)
        queryset = model.objects.filter(
            user=user, item__release_datetime__isnull=False
        ).select_related("item")
        if month and day:
            queryset = queryset.annotate(
                release_month=ExtractMonth("item__release_datetime"),
                release_day=ExtractDay("item__release_datetime"),
            ).filter(release_month=month, release_day=day)
        elif start_date or end_date:
            if start_date:
                queryset = queryset.filter(item__release_datetime__date__gte=start_date)
            if end_date:
                queryset = queryset.filter(item__release_datetime__date__lte=end_date)

        for media in queryset:
            item = getattr(media, "item", None)
            if not item or item.id in seen_item_ids:
                continue
            if not _matches_genre_filters(item):
                continue
            seen_item_ids.add(item.id)
            release_dt = getattr(item, "release_datetime", None)
            localized = stats._localize_datetime(release_dt) if release_dt else None
            if not localized:
                continue
            release_date = localized.date()
            entry = {
                "item": item,
                "media_type": item.media_type,
                "title": item.title,
                "display_title": item.title,
                "poster": item.image,
                "played_at_local": localized,
                "entry_key": f"release-{item.id}-{release_date.isoformat()}",
            }
            release_days[release_date].append(entry)

    if include_episodes:
        Episode = apps.get_model("app", "Episode")
        episode_qs = Episode.objects.filter(
            related_season__user=user,
            item__release_datetime__isnull=False,
        ).select_related(
            "item",
            "related_season__item",
            "related_season__related_tv__item",
        )
        if month and day:
            episode_qs = episode_qs.annotate(
                release_month=ExtractMonth("item__release_datetime"),
                release_day=ExtractDay("item__release_datetime"),
            ).filter(release_month=month, release_day=day)
        elif start_date or end_date:
            if start_date:
                episode_qs = episode_qs.filter(
                    item__release_datetime__date__gte=start_date
                )
            if end_date:
                episode_qs = episode_qs.filter(
                    item__release_datetime__date__lte=end_date
                )

        for episode in episode_qs:
            episode_item = getattr(episode, "item", None)
            if not episode_item or episode_item.id in seen_item_ids:
                continue
            if not _matches_genre_filters(
                episode_item,
                album=None,
            ):
                continue
            seen_item_ids.add(episode_item.id)
            release_dt = getattr(episode_item, "release_datetime", None)
            localized = stats._localize_datetime(release_dt) if release_dt else None
            if not localized:
                continue
            release_date = localized.date()
            season_item = getattr(episode.related_season, "item", None)
            tv_item = getattr(
                getattr(episode.related_season, "related_tv", None), "item", None
            )
            title = (
                episode_item.title
                or (season_item.title if season_item else None)
                or (tv_item.title if tv_item else "")
            )
            display_title = history_cache._get_episode_display_title(episode)
            entry = {
                "item": episode_item,
                "media_type": MediaTypes.EPISODE.value,
                "title": title,
                "display_title": display_title or title,
                "poster": history_cache._get_episode_poster(episode),
                "played_at_local": localized,
                "entry_key": f"release-episode-{episode.id}-{release_date.isoformat()}",
            }
            release_days[release_date].append(entry)

    if include_podcasts:
        Podcast = apps.get_model("app", "Podcast")
        podcast_base = Podcast.objects.filter(user=user).select_related(
            "item", "episode", "show"
        )
        podcast_qs = podcast_base.filter(episode__published__isnull=False)
        if month and day:
            podcast_qs = podcast_qs.annotate(
                release_month=ExtractMonth("episode__published"),
                release_day=ExtractDay("episode__published"),
            ).filter(release_month=month, release_day=day)
        elif start_date or end_date:
            if start_date:
                podcast_qs = podcast_qs.filter(episode__published__date__gte=start_date)
            if end_date:
                podcast_qs = podcast_qs.filter(episode__published__date__lte=end_date)

        for podcast in podcast_qs:
            item = getattr(podcast, "item", None)
            if not item or item.id in seen_item_ids:
                continue
            if not _matches_genre_filters(item):
                continue
            release_dt = getattr(getattr(podcast, "episode", None), "published", None)
            localized = stats._localize_datetime(release_dt) if release_dt else None
            if not localized:
                continue
            release_date = localized.date()
            show = None
            if getattr(podcast, "episode", None) and podcast.episode.show:
                show = podcast.episode.show
            if not show:
                show = podcast.show
            poster = settings.IMG_NONE
            if show and show.image:
                poster = show.image
            elif item.image:
                poster = item.image
            title = item.title or getattr(
                getattr(podcast, "episode", None), "title", ""
            )
            entry = {
                "item": item,
                "media_type": MediaTypes.PODCAST.value,
                "title": title,
                "display_title": title,
                "show": show,
                "poster": poster,
                "played_at_local": localized,
                "entry_key": f"release-podcast-{podcast.id}-{release_date.isoformat()}",
            }
            seen_item_ids.add(item.id)
            release_days[release_date].append(entry)

        podcast_fallback_qs = podcast_base.filter(
            episode__published__isnull=True,
            item__release_datetime__isnull=False,
        )
        if month and day:
            podcast_fallback_qs = podcast_fallback_qs.annotate(
                release_month=ExtractMonth("item__release_datetime"),
                release_day=ExtractDay("item__release_datetime"),
            ).filter(release_month=month, release_day=day)
        elif start_date or end_date:
            if start_date:
                podcast_fallback_qs = podcast_fallback_qs.filter(
                    item__release_datetime__date__gte=start_date,
                )
            if end_date:
                podcast_fallback_qs = podcast_fallback_qs.filter(
                    item__release_datetime__date__lte=end_date,
                )

        for podcast in podcast_fallback_qs:
            item = getattr(podcast, "item", None)
            if not item or item.id in seen_item_ids:
                continue
            if not _matches_genre_filters(item):
                continue
            release_dt = getattr(item, "release_datetime", None)
            localized = stats._localize_datetime(release_dt) if release_dt else None
            if not localized:
                continue
            release_date = localized.date()
            show = None
            if getattr(podcast, "episode", None) and podcast.episode.show:
                show = podcast.episode.show
            if not show:
                show = podcast.show
            poster = settings.IMG_NONE
            if show and show.image:
                poster = show.image
            elif item.image:
                poster = item.image
            title = item.title or getattr(
                getattr(podcast, "episode", None), "title", ""
            )
            entry = {
                "item": item,
                "media_type": MediaTypes.PODCAST.value,
                "title": title,
                "display_title": title,
                "show": show,
                "poster": poster,
                "played_at_local": localized,
                "entry_key": f"release-podcast-{podcast.id}-{release_date.isoformat()}",
            }
            seen_item_ids.add(item.id)
            release_days[release_date].append(entry)

    history_days = []
    for release_date, entries in sorted(
        release_days.items(),
        key=lambda item: item[0],
        reverse=True,
    ):
        entries.sort(key=lambda entry: entry.get("played_at_local"), reverse=True)
        release_display_dt = entries[0]["played_at_local"]
        history_days.append(
            {
                "date": release_date,
                "weekday": formats.date_format(release_display_dt, "l"),
                "date_display": formats.date_format(release_display_dt, "F j, Y"),
                "entries": entries,
                "total_minutes": 0,
                "total_runtime_display": f"{len(entries)} release{'s' if len(entries) != 1 else ''}",
                "release_count": len(entries),
            },
        )
    return history_days


def _filter_history_by_enabled_media_types(history_days, user):
    """Filter history entries to only include enabled media types."""
    enabled_types = user.get_enabled_media_types()
    if not enabled_types:
        return history_days

    allowed_types = set(enabled_types)
    if MediaTypes.TV.value in allowed_types:
        allowed_types.add(MediaTypes.EPISODE.value)
        allowed_types.add(MediaTypes.SEASON.value)

    filtered_days = []
    for day in history_days:
        if isinstance(day, dict):
            entries = day.get("entries", [])
            filtered_entries = [
                entry for entry in entries if entry.get("media_type") in allowed_types
            ]
            if filtered_entries:
                filtered_day = day.copy()
                filtered_day["entries"] = filtered_entries
                total_minutes = sum(
                    entry.get("runtime_minutes") or 0 for entry in filtered_entries
                )
                filtered_day["total_minutes"] = total_minutes
                filtered_day["total_runtime_display"] = (
                    helpers.minutes_to_hhmm(total_minutes) if total_minutes else "0min"
                )
                filtered_days.append(filtered_day)
        else:
            filtered_days.append(day)

    return filtered_days


def _can_use_cached_month_history(
    history_mode,
    filters,
    date_filters,
    anniversary_month,
    anniversary_day,
):
    if history_mode != "activity":
        return False
    if date_filters or anniversary_month or anniversary_day:
        return False
    if any(key in filters for key in _MONTH_CACHE_UNSUPPORTED_FILTER_KEYS):
        return False
    return not (filters.get("media_id") or filters.get("source"))


def _cached_history_entry_matches_filters(entry, filters):
    entry = entry or {}
    item = entry.get("item") or {}
    album = entry.get("album") or {}
    show = entry.get("show") or {}
    entry_media_type = entry.get("media_type")
    media_type_filter_raw = filters.get("media_type")
    if media_type_filter_raw:
        media_type_filters = {
            t.strip() for t in media_type_filter_raw.split(",") if t.strip()
        }
        allowed_media_types = set(media_type_filters)
        if MediaTypes.TV.value in media_type_filters:
            allowed_media_types.update(
                {MediaTypes.EPISODE.value, MediaTypes.SEASON.value},
            )
        if entry_media_type not in allowed_media_types:
            return False

    genre_filter = filters.get("genre")
    if genre_filter:
        genre_filters = {
            g.strip().lower() for g in genre_filter.split(",") if g.strip()
        }
        genres = entry.get("genres") or item.get("genres") or []
        item_genre_set = {str(g).lower() for g in genres}
        if not (item_genre_set & genre_filters):
            return False
    implied_genre_filter = filters.get("implied_genre")
    if implied_genre_filter:
        implied_genre_filters = {
            g.strip().lower() for g in implied_genre_filter.split(",") if g.strip()
        }
        implied_genres = entry.get("implied_genres") or item.get("implied_genres") or []
        item_implied_genre_set = {str(g).lower() for g in implied_genres}
        if not (item_implied_genre_set & implied_genre_filters):
            return False

    album_filter = filters.get("album")
    if album_filter is not None:
        if entry_media_type != MediaTypes.MUSIC.value:
            return False
        if album.get("id") != album_filter:
            return False

    podcast_show_filter = filters.get("podcast_show")
    if podcast_show_filter is not None:
        if entry_media_type != MediaTypes.PODCAST.value:
            return False
        if show.get("id") != podcast_show_filter:
            return False

    target_media_id = filters.get("media_id")
    if target_media_id is not None and str(item.get("media_id")) != str(
        target_media_id
    ):
        return False

    target_source = filters.get("source")
    return not (
        target_source is not None and str(item.get("source")) != str(target_source)
    )


def _filter_cached_history_days(history_days, filters):
    if not filters:
        return history_days

    filtered_days = []
    for day in history_days:
        if not isinstance(day, dict):
            continue

        filtered_entries = [
            entry
            for entry in day.get("entries", [])
            if _cached_history_entry_matches_filters(entry, filters)
        ]
        if not filtered_entries:
            continue

        total_minutes = sum(
            entry.get("runtime_minutes") or 0 for entry in filtered_entries
        )
        filtered_day = day.copy()
        filtered_day["entries"] = filtered_entries
        filtered_day["total_minutes"] = total_minutes
        filtered_day["total_runtime_display"] = (
            helpers.minutes_to_hhmm(total_minutes) if total_minutes else "0min"
        )
        filtered_days.append(filtered_day)

    return filtered_days


def _history_day_key(day):
    """Return the canonical cache key for a rendered history day."""
    if not isinstance(day, dict):
        return None
    return history_cache.history_day_key(day.get("date"))


def _annotate_history_day_for_template(day):
    """Add stable template metadata without changing the entry list."""
    if not isinstance(day, dict):
        return None
    annotated_day = day.copy()
    entries = list(annotated_day.get("entries", []))
    annotated_day.update(
        {
            "day_key": _history_day_key(annotated_day),
            "entry_count": len(entries),
            "entry_offset": 0,
            "next_entry_offset": len(entries),
            "has_more": False,
            "remaining_entry_count": 0,
        },
    )
    return annotated_day


def _attach_session_notes(days):
    """Attach current per-instance notes without changing cached history payloads."""
    ids_by_media_type = defaultdict(set)
    for day in days:
        for entry in day.get("entries", []):
            instance_id = entry.get("instance_id")
            media_type = entry.get("media_type")
            if instance_id is not None and media_type != MediaTypes.MUSIC.value:
                ids_by_media_type[media_type].add(instance_id)

    model_by_media_type = {
        MediaTypes.MOVIE.value: Movie,
        MediaTypes.EPISODE.value: Episode,
        MediaTypes.GAME.value: Game,
        MediaTypes.BOARDGAME.value: BoardGame,
        MediaTypes.BOOK.value: Book,
        MediaTypes.COMIC.value: Comic,
        MediaTypes.MANGA.value: Manga,
        MediaTypes.ANIME.value: Anime,
        MediaTypes.PODCAST.value: Podcast,
    }
    notes_by_media_type = {}
    for media_type, instance_ids in ids_by_media_type.items():
        model = model_by_media_type.get(media_type)
        if model is None:
            continue
        notes_by_media_type[media_type] = dict(
            model.objects.filter(id__in=instance_ids).values_list("id", "notes"),
        )

    for day in days:
        for entry in day.get("entries", []):
            media_notes = notes_by_media_type.get(entry.get("media_type"), {})
            entry["notes"] = media_notes.get(entry.get("instance_id"), "")


def _build_session_history_stats(history_days):
    """Build display-ready statistics for the filtered session history."""
    dated_days = [day for day in history_days if day.get("date")]
    dates = sorted({day["date"] for day in dated_days})
    activity_entries = sum(len(day.get("entries", [])) for day in history_days)
    total_minutes = sum(day.get("total_minutes") or 0 for day in history_days)

    gaps = [(current - previous).days for previous, current in pairwise(dates)]
    average_gap = sum(gaps) / len(gaps) if gaps else None

    longest_streak = 0
    current_streak = 0
    for index, current in enumerate(dates):
        previous = dates[index - 1] if index else None
        if previous is not None and (current - previous).days == 1:
            current_streak += 1
        else:
            current_streak = 1
        longest_streak = max(longest_streak, current_streak)

    entries_by_weekday = defaultdict(int)
    for day in dated_days:
        entries_by_weekday[day["date"].weekday()] += len(day.get("entries", []))
    most_active_weekday = None
    if entries_by_weekday:
        weekday = max(
            entries_by_weekday,
            key=lambda value: (entries_by_weekday[value], -value),
        )
        most_active_weekday = formats.date_format(
            date(2024, 1, 1) + timedelta(days=weekday),
            "l",
        )

    def format_minutes(minutes):
        return helpers.minutes_to_hhmm(round(minutes)) if minutes is not None else "—"

    def format_days(days):
        if days is None:
            return "—"
        rounded = round(days, 1)
        return f"{rounded:g} day{'s' if rounded != 1 else ''}"

    return [
        {"label": gettext_noop("Active days"), "value": str(len(dates))},
        {"label": gettext_noop("Activity entries"), "value": str(activity_entries)},
        {
            "label": gettext_noop("Tracked time"),
            "value": format_minutes(total_minutes if activity_entries else None),
        },
        {
            "label": gettext_noop("Average per active day"),
            "value": format_minutes(total_minutes / len(dates)) if dates else "—",
        },
        {"label": gettext_noop("Average gap"), "value": format_days(average_gap)},
        {
            "label": gettext_noop("Longest streak"),
            "value": (
                f"{longest_streak} day{'s' if longest_streak != 1 else ''}"
                if longest_streak
                else "—"
            ),
        },
        {
            "label": gettext_noop("Most active weekday"),
            "value": most_active_weekday or "—",
        },
    ]


@require_GET
def activity_sessions_modal(request):
    """Return the in-place, date-grouped activity history for one media item."""
    filters, logging_style = _parse_history_filters(request)
    history_days = history_cache_reader.get_history_days(
        request.user,
        filters,
        None,
        logging_style,
        cap_entries_per_day=False,
    )
    history_days = _filter_history_by_enabled_media_types(
        history_days,
        request.user,
    )
    _attach_session_notes(history_days)
    history_days = [
        annotated_day
        for day in history_days
        if (annotated_day := _annotate_history_day_for_template(day))
    ]
    session_history_stats = _build_session_history_stats(history_days)

    marker_days = sorted(
        {day["date"].isoformat() for day in history_days if day.get("date")},
    )
    newest_dated_day = next(
        (day["date"] for day in history_days if day.get("date")),
        timezone.localdate(),
    )
    visible_days = history_days[:SESSION_HISTORY_MAX_DAYS]
    visible_marker_days = sorted(
        {day["date"].isoformat() for day in visible_days if day.get("date")},
    )
    return render(
        request,
        "app/components/session_history_modal.html",
        {
            "user": request.user,
            "history_days": visible_days,
            "marker_days": marker_days,
            "visible_marker_days": visible_marker_days,
            "session_history_stats": session_history_stats,
            "initial_month": newest_dated_day.strftime("%Y-%m"),
            "history_capped": len(history_days) > SESSION_HISTORY_MAX_DAYS,
            "history_querystring": request.GET.urlencode(),
        },
    )


def _prepare_history_day_page(day, user, filters, offset=0):
    """Filter and bound one cached month-view day for HTML rendering."""
    filtered_days = _filter_cached_history_days([day], filters)
    filtered_days = _filter_history_by_enabled_media_types(filtered_days, user)
    if not filtered_days:
        return None

    annotated_day = _annotate_history_day_for_template(filtered_days[0])
    if annotated_day is None:
        return None

    try:
        offset = int(offset)
    except (TypeError, ValueError):
        offset = 0
    offset = max(offset, 0)

    page_size = history_cache.HISTORY_ENTRIES_PER_DAY_PAGE
    entries = annotated_day["entries"]
    annotated_day["entries"] = entries[offset : offset + page_size]
    annotated_day["entry_offset"] = offset
    annotated_day["next_entry_offset"] = offset + page_size
    annotated_day["has_more"] = offset + page_size < annotated_day["entry_count"]
    annotated_day["remaining_entry_count"] = max(
        annotated_day["entry_count"] - annotated_day["next_entry_offset"],
        0,
    )
    return annotated_day


def _history_day_fragment_query(request, offset):
    """Preserve the current history filters for the next day fragment."""
    query = request.GET.copy()
    query.pop("entry_offset", None)
    query.pop("page", None)
    query["entry_offset"] = str(offset)
    return query.urlencode()


def _parse_history_filters(request):
    """Parse filters shared by the full history page and day fragments."""
    filters = {}
    int_params = (
        "album",
        "artist",
        "tv",
        "season",
        "season_number",
        "podcast_show",
    )
    str_params = (
        "genre",
        "implied_genre",
        "media_type",
        "media_id",
        "source",
        "person_source",
        "person_id",
    )
    for param in int_params:
        value = request.GET.get(param)
        if value:
            with contextlib.suppress(TypeError, ValueError):
                filters[param] = int(value)
    for param in str_params:
        value = request.GET.get(param)
        if value:
            filters[param] = value

    logging_style = request.GET.get("logging_style")
    if logging_style not in ("sessions", "repeats"):
        logging_style = None
    return filters, logging_style


@require_GET
def history_genres(request):
    """Return sorted list of unique genres from the user's tracked items."""
    from django.http import JsonResponse

    from app.models import (
        BoardGame,
        Episode,
        Game,
        Movie,
        Music,
        Podcast,
    )

    def _is_valid_genre(value) -> bool:
        s = str(value).strip()
        return bool(s) and not s.lstrip("-").isdigit()

    genres: set[str] = set()
    implied_genres: set[str] = set()
    # Book, Comic, and Manga use Library of Congress subject headings in their genres
    # field rather than real genre names, so exclude them from the genre list.
    for model_cls in [Movie, Game, Music, BoardGame, Podcast]:
        for genres_list in model_cls.objects.filter(user=request.user).values_list(
            "item__genres", flat=True
        ):
            if genres_list:
                genres.update(str(g).strip() for g in genres_list if _is_valid_genre(g))
        for implied_genres_list in model_cls.objects.filter(
            user=request.user
        ).values_list(
            "item__implied_genres",
            flat=True,
        ):
            if implied_genres_list:
                implied_genres.update(
                    str(g).strip() for g in implied_genres_list if _is_valid_genre(g)
                )

    for genres_list in Episode.objects.filter(
        related_season__user=request.user
    ).values_list("related_season__related_tv__item__genres", flat=True):
        if genres_list:
            genres.update(str(g).strip() for g in genres_list if _is_valid_genre(g))

    genres.discard("")
    implied_genres.discard("")
    return JsonResponse(
        {
            "genres": sorted(genres, key=str.lower),
            "implied_genres": sorted(implied_genres, key=str.lower),
        },
    )


@require_GET
def history(request):
    """Show a day-by-day history of episode and movie plays."""
    # Surface the media type the user came from (e.g. "view your activity
    # history" on a movie page) so the navbar search type stays in context
    # instead of falling back to a stale last_search_type. Invalid values are
    # dropped so the search bar falls back to last_search_type.
    requested_media_type = request.GET.get("media_type")
    context_media_type = (
        requested_media_type if requested_media_type in MediaTypes.values else None
    )
    try:
        view_start = time.perf_counter()
        history_mode = request.GET.get("history_mode")
        if history_mode != "release":
            history_mode = "activity"

        filters, logging_style = _parse_history_filters(request)

        date_filters = {}
        start_date_str = request.GET.get("start-date")
        end_date_str = request.GET.get("end-date")
        if start_date_str:
            date_filters["start_date"] = start_date_str
        if end_date_str:
            date_filters["end_date"] = end_date_str

        anniversary_month = request.GET.get("month")
        anniversary_day = request.GET.get("day")
        try:
            anniversary_month = int(anniversary_month) if anniversary_month else None
            anniversary_day = int(anniversary_day) if anniversary_day else None
        except (TypeError, ValueError):
            anniversary_month = None
            anniversary_day = None

        now = timezone.localtime()
        try:
            view_year = int(request.GET.get("year", now.year))
            view_month = int(request.GET.get("m", now.month))
            if view_month < 1 or view_month > MONTHS_PER_YEAR:
                view_month = now.month
        except (TypeError, ValueError):
            view_year = now.year
            view_month = now.month

        logger.info(
            "history_view_start user_id=%s year=%s month=%s filters=%s date_filters=%s logging_style=%s",
            request.user.id,
            view_year,
            view_month,
            filters,
            date_filters,
            logging_style,
        )

        use_month_cache = _can_use_cached_month_history(
            history_mode,
            filters,
            date_filters,
            anniversary_month,
            anniversary_day,
        )
        history_refreshing = False

        if use_month_cache:
            history_days, cache_meta = history_cache.get_month_history(
                request.user,
                view_year,
                view_month,
                logging_style_override=logging_style,
            )
            history_days = [
                prepared_day
                for day in history_days
                if (
                    prepared_day := _prepare_history_day_page(
                        day,
                        request.user,
                        filters,
                    )
                )
            ]
            history_refreshing = cache_meta.get("refreshing", False)

            page_obj = None
            current_page = 1
            total_pages = 1
            total_days = len(history_days)

            if view_month == 1:
                prev_year, prev_month = view_year - 1, 12
            else:
                prev_year, prev_month = view_year, view_month - 1
            if view_month == MONTHS_PER_YEAR:
                next_year, next_month = view_year + 1, 1
            else:
                next_year, next_month = view_year, view_month + 1

            prev_month_name = calendar.month_abbr[prev_month]
            next_month_name = calendar.month_abbr[next_month]
            is_current_month = view_year == now.year and view_month == now.month
            show_next_month = next_year < now.year or (
                next_year == now.year and next_month <= now.month
            )
        else:
            try:
                page_number = int(request.GET.get("page", 1))
            except (TypeError, ValueError):
                page_number = 1

            if history_mode == "release":
                history_days_all = _build_release_history_days(
                    request.user,
                    month=anniversary_month,
                    day=anniversary_day,
                    date_filters=date_filters,
                    filters=filters,
                )
                history_refreshing = False
            elif anniversary_month and anniversary_day:
                history_days_all = _build_anniversary_history_days(
                    request.user,
                    month=anniversary_month,
                    day=anniversary_day,
                    logging_style=logging_style,
                )
                history_refreshing = False
            else:
                history_days_all = history_cache.get_history_days(
                    request.user,
                    filters=filters,
                    date_filters=date_filters,
                    logging_style_override=logging_style,
                )

            history_days_all = _filter_history_by_enabled_media_types(
                history_days_all,
                request.user,
            )

            paginator = Paginator(history_days_all, history_cache.HISTORY_DAYS_PER_PAGE)

            if paginator.count == 0:
                page_obj = None
                history_days = []
                current_page = 1
                total_pages = 1
                total_days = 0
            else:
                try:
                    page_obj = paginator.page(page_number)
                except EmptyPage:
                    page_obj = paginator.page(paginator.num_pages)

                history_days = page_obj.object_list
                current_page = page_obj.number
                total_pages = paginator.num_pages
                total_days = paginator.count

            history_days = [
                annotated_day
                for day in history_days
                if (annotated_day := _annotate_history_day_for_template(day))
            ]

            prev_year = prev_month = next_year = next_month = None
            prev_month_name = next_month_name = None
            show_next_month = False
            is_current_month = False

        active_filters = filters.copy()
        if date_filters.get("start_date"):
            active_filters["start-date"] = date_filters["start_date"]
        if date_filters.get("end_date"):
            active_filters["end-date"] = date_filters["end_date"]
        if logging_style:
            active_filters["logging_style"] = logging_style
        if anniversary_month and anniversary_day:
            active_filters["month"] = anniversary_month
            active_filters["day"] = anniversary_day
        if history_mode == "release":
            active_filters["history_mode"] = "release"
        month_nav_query = urlencode(active_filters)
        month_name = calendar.month_name[view_month] if use_month_cache else None

        for day in history_days:
            if day.get("has_more"):
                day["next_entry_query"] = _history_day_fragment_query(
                    request,
                    day["next_entry_offset"],
                )

        context = {
            "user": request.user,
            "history_days": history_days,
            "page_obj": page_obj,
            "current_page": current_page,
            "total_pages": total_pages,
            "total_days": total_days,
            "active_filters": active_filters,
            "history_refreshing": history_refreshing,
            "history_mode": history_mode,
            "media_type": context_media_type,
            "use_month_view": use_month_cache,
            "view_year": view_year,
            "view_month": view_month,
            "month_name": month_name,
            "prev_year": prev_year,
            "prev_month": prev_month,
            "prev_month_name": prev_month_name,
            "next_year": next_year,
            "next_month": next_month,
            "next_month_name": next_month_name,
            "show_next_month": show_next_month,
            "is_current_month": is_current_month,
            "current_year": now.year,
            "current_month_num": now.month,
            "month_nav_query": month_nav_query,
        }
        day_entry_counts = []
        total_entries = 0
        rendered_entries = 0
        for day in history_days:
            entries = (
                day.get("entries", [])
                if isinstance(day, dict)
                else getattr(day, "entries", [])
            )
            count = (
                day.get("entry_count", len(entries))
                if isinstance(day, dict)
                else len(entries)
            )
            total_entries += count
            rendered_entries += len(entries)
            day_entry_counts.append((day.get("date_display") or day.get("date"), count))
        top_days = sorted(day_entry_counts, key=lambda item: item[1], reverse=True)[:3]
        logger.info(
            "history_page_entry_counts user_id=%s page=%s total_entries=%s top_days=%s",
            request.user.id,
            current_page,
            total_entries,
            top_days,
        )
        logger.info(
            "history_page_rendered_entry_counts user_id=%s page=%s rendered_entries=%s",
            request.user.id,
            current_page,
            rendered_entries,
        )
        render_start = time.perf_counter()
        logger.info(
            "history_render_start user_id=%s page=%s",
            request.user.id,
            current_page,
        )
        response = render(request, "app/history.html", context)
        render_ms = (time.perf_counter() - render_start) * 1000
        response_bytes = len(response.content)
        logger.info(
            "history_render_end user_id=%s page=%s render_ms=%.2f response_bytes=%s",
            request.user.id,
            current_page,
            render_ms,
            response_bytes,
        )
        logger.info(
            "history_view_end user_id=%s page=%s total_days=%s page_days=%s total_pages=%s elapsed_ms=%.2f response_bytes=%s",
            request.user.id,
            current_page,
            total_days,
            len(history_days),
            total_pages,
            (time.perf_counter() - view_start) * 1000,
            response_bytes,
        )
    except OperationalError:
        logger.exception("Database error in history view")
        context = {
            "user": request.user,
            "history_days": [],
            "page_obj": None,
            "current_page": 1,
            "total_pages": 0,
            "total_days": 0,
            "days_per_page": history_cache.HISTORY_DAYS_PER_PAGE,
            "active_filters": {},
            "database_error": True,
            "history_refreshing": False,
            "media_type": context_media_type,
        }
        return render(request, "app/history.html", context)
    else:
        return response


@require_GET
def history_day_fragment(request, day_key):
    """Render one bounded page of a month-view history day."""
    normalized_day_key = history_cache.history_day_key(day_key)
    if normalized_day_key != day_key:
        return HttpResponseBadRequest("Invalid history day key.")
    try:
        history_cache._date_from_day_key(normalized_day_key)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Invalid history day key.")

    raw_offset = request.GET.get("entry_offset", "0")
    try:
        entry_offset = int(raw_offset)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Invalid history entry offset.")
    if entry_offset < 0:
        return HttpResponseBadRequest("Invalid history entry offset.")

    filters, logging_style = _parse_history_filters(request)
    if not _can_use_cached_month_history(
        "activity",
        filters,
        date_filters={},
        anniversary_month=None,
        anniversary_day=None,
    ):
        return HttpResponseBadRequest("History filters are not supported here.")

    day = history_cache.get_cached_history_day(
        request.user,
        normalized_day_key,
        logging_style_override=logging_style,
    )
    prepared_day = _prepare_history_day_page(
        day,
        request.user,
        filters,
        offset=entry_offset,
    )
    if prepared_day is None:
        return HttpResponseNotFound("History day not found.")
    if entry_offset > prepared_day["entry_count"]:
        return HttpResponseBadRequest("Invalid history entry offset.")

    prepared_day["next_entry_query"] = _history_day_fragment_query(
        request,
        prepared_day["next_entry_offset"],
    )
    return render(
        request,
        "app/components/history_day.html",
        {
            "day": prepared_day,
            "history_mode": "activity",
            "user": request.user,
        },
    )
