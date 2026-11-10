"""Structured, permission-aware detail data for non-browser clients."""

import logging
from datetime import date, datetime
from decimal import Decimal
from http import HTTPStatus as HTTP  # noqa: N814

from django.apps import apps
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

from app import carousel
from app import models as app_models
from app.activity_builders import (
    _build_detail_activity_state,
    _normalize_detail_episode_actions,
    _paginate_detail_episodes,
)
from app.detail_builders import (
    _apply_cached_hltb_link,
    _build_detail_link_sections,
    _build_detail_person_rows,
    _build_game_lengths_context,
    _build_imdb_rating_context,
    _build_mal_rating_context,
    _build_opencritic_context,
    _build_trakt_popularity_context,
    build_book_formats,
)
from app.detail_related import enrich_detail_related_cards, enrich_detail_seasons
from app.providers import manual, services, tmdb
from app.services import metadata_resolution, youtube_game_watch
from app.services.metadata_fallback import stored_metadata_fallback
from app.tag_views import _build_detail_tag_sections
from app.templatetags.app_tags import media_url

from .authentication import HasScope
from .helpers import check_source_type, check_valid_type

logger = logging.getLogger(__name__)


class PublicDetailRead(HasScope):
    """Allow public metadata while retaining scope checks for authenticated tokens."""

    def has_permission(self, request, view):
        """Permit anonymous reads; scoped tokens still need the mapped scope."""
        if not getattr(request.user, "is_authenticated", False):
            return True
        return super().has_permission(request, view)


def _owned_media(user, item):
    """Return the caller's tracking row without exposing another user's state."""
    if not getattr(user, "is_authenticated", False) or item is None:
        return None
    try:
        model = apps.get_model("app", item.media_type)
    except LookupError:
        return None
    queryset = model.objects.filter(item=item)
    if item.media_type == app_models.MediaTypes.EPISODE.value:
        return queryset.filter(related_season__user=user).first()
    return queryset.filter(user=user).first()


def _nonempty_list(value):
    if isinstance(value, (tuple, list)):
        return [entry for entry in value if entry not in (None, "", [], {})]
    return [value] if value not in (None, "", [], {}) else []


def _primitive(value):
    """Convert builder output to JSON-safe values without leaking model objects."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _primitive(entry) for key, entry in value.items()}
    if isinstance(value, (list, tuple)):
        return [_primitive(entry) for entry in value]
    return str(value)


def _media_card(entry, *, public_view):
    """Build the shared MediaCard model used by related/recommendation rails."""
    raw = entry.get("item") if isinstance(entry, dict) and "item" in entry else entry
    tracked = entry.get("media") if isinstance(entry, dict) else None
    if not isinstance(raw, dict):
        return None
    media_type = raw.get("media_type") or "movie"
    source = raw.get("source")
    media_id = str(raw.get("media_id") or "")
    title = raw.get("card_title") or raw.get("title") or ""
    image = raw.get("image") or ""
    if not source or not media_id or not title:
        return None
    try:
        href = media_url(raw)
    except (KeyError, TypeError, ValueError):
        href = ""
    status = getattr(tracked, "status", None)
    score = getattr(tracked, "score", None)
    progress = getattr(tracked, "progress", None)
    max_progress = getattr(tracked, "max_progress", None)
    release_date = raw.get("release_date") or raw.get("release_datetime") or ""
    year = str(release_date)[:4] if release_date else ""
    return {
        "key": f"{media_type}-{source}-{media_id}-{raw.get('season_number', '')}",
        "active": False,
        "model": {
            "cardKey": f"{media_type}-{source}-{media_id}",
            "identity": {"mediaType": media_type, "source": source, "mediaId": media_id},
            "mediaType": media_type,
            "shape": "square" if media_type in {"music", "podcast"} else "poster",
            "href": href,
            "image": {"src": image, "fallback": "", "source": "primary"},
            "title": title,
            "altTitle": raw.get("original_title") or raw.get("alternative_title"),
            "statusChip": {"kind": "status", "status": status, "hideOnMobile": False}
            if status and not public_view
            else None,
            "cornerChips": [],
            "titleLinks": [],
            "progressBar": None,
            "lines": [{"join": "plain", "parts": [{"text": year}]}] if year else [],
            "rating": {"label": str(score), "value": score, "scaleMax": 10, "rateLabel": "Rate"}
            if score is not None and not public_view
            else None,
            "ratingEditable": bool(tracked and not public_view),
            "actions": None,
            "readOnly": public_view,
            "trackedProgress": progress,
            "maxProgress": max_progress,
        },
    }


def _child_row(raw, *, media_type, parent_media_type, source, media_id, public_view, can_write):
    """Normalize provider season/episode data for the shared detail child cards."""
    if not isinstance(raw, dict):
        return None
    tracking = raw.get("media") if isinstance(raw.get("item"), dict) else None
    raw = raw.get("item") if isinstance(raw.get("item"), dict) else raw
    number = raw.get("episode_number") if media_type == "episode" else raw.get("season_number")
    identity = {
        "mediaType": parent_media_type,
        "detailType": media_type,
        "source": source,
        "mediaId": str(raw.get("media_id") or media_id),
        "seasonNumber": raw.get("season_number"),
        "episodeNumber": raw.get("episode_number"),
    }
    title = raw.get("title") or raw.get("name") or raw.get("season_title") or (
        f"Season {number}" if media_type == "season" and number is not None else
        f"Episode {number}" if number is not None else ""
    )
    image = raw.get("image") or ""
    date_value = raw.get("air_date") or raw.get("first_air_date") or raw.get("release_date") or ""
    overview = raw.get("overview") or raw.get("description") or ""
    progress = getattr(tracking, "progress", None)
    max_progress = getattr(tracking, "max_progress", None)
    try:
        percent = min(100, round(progress / max_progress * 100)) if progress is not None and max_progress else None
    except (TypeError, ZeroDivisionError):
        percent = None
    editable_episode = can_write and not public_view and media_type == "episode" and parent_media_type == "tv"
    plays = raw.get("history") or []
    watched = bool(raw.get("watched") or plays)
    score = raw.get("score")
    if score is None and plays:
        score = getattr(plays[0], "score", None)
    return {
        "key": f"{media_type}-{source}-{identity['mediaId']}-{number}",
        "number": number,
        "identity": identity,
        "title": title,
        "image": {"src": image, "fallback": ""},
        "overview": overview,
        "dateLabel": date_value,
        "code": raw.get("code") or (f"S{raw['season_number']}E{raw['episode_number']}" if media_type == "episode" and raw.get("season_number") is not None and raw.get("episode_number") is not None else ""),
        "runtime": raw.get("runtime") or "",
        "countLabel": raw.get("episode_count") or raw.get("details", {}).get("episodes") or "",
        "statusLabel": getattr(tracking, "status", None) if not public_view else None,
        "dropped": getattr(tracking, "status", None) == app_models.Status.DROPPED.value if not public_view else False,
        "percent": percent,
        "score": _primitive(score) if editable_episode else None,
        "canRate": editable_episode,
        "actions": ([{"key": "unwatch", "label": "Mark unwatched", "tone": "surface"}]
                    if editable_episode and watched else
                    [{"key": "watch", "label": "Mark watched", "tone": "primary"}]
                    if editable_episode else []),
        "unreleased": bool(raw.get("unreleased")),
        "publicView": public_view,
    }


class DetailPageView(drf_views.APIView):
    """Project provider detail metadata and the caller's own tracking state."""

    permission_classes = [PublicDetailRead]

    @extend_schema(
        parameters=[
            OpenApiParameter("public_view", bool, required=False),
            OpenApiParameter("detail_type", str, required=False),
            OpenApiParameter("season_number", int, required=False),
            OpenApiParameter("episode_number", int, required=False),
            OpenApiParameter("episode_page", int, required=False),
        ],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, media_type, source, media_id):
        """Return serializable detail sections and permission capabilities."""
        detail_type = request.query_params.get("detail_type") or media_type
        season_number = request.query_params.get("season_number")
        episode_number = request.query_params.get("episode_number")
        provider_metadata = {}
        try:
            season_number = int(season_number) if season_number is not None else None
            episode_number = int(episode_number) if episode_number is not None else None
        except (TypeError, ValueError):
            return Response({"detail": "Invalid season or episode number."}, status=HTTP.BAD_REQUEST)
        is_video = media_type == app_models.MediaTypes.VIDEO.value
        if not check_valid_type(media_type) and not is_video:
            return Response({"detail": "Unsupported media type."}, status=HTTP.BAD_REQUEST)
        if detail_type in {
            app_models.MediaTypes.SEASON.value,
            app_models.MediaTypes.EPISODE.value,
        }:
            if media_type not in {
                app_models.MediaTypes.TV.value,
                app_models.MediaTypes.ANIME.value,
            }:
                return Response({"detail": "Unsupported detail type."}, status=HTTP.BAD_REQUEST)
            if season_number is None or (
                detail_type == app_models.MediaTypes.EPISODE.value
                and episode_number is None
            ):
                return Response({"detail": "A season and episode number are required."}, status=HTTP.BAD_REQUEST)
        elif detail_type != media_type:
            return Response({"detail": "Unsupported detail type."}, status=HTTP.BAD_REQUEST)
        if (is_video and source != app_models.Sources.YOUTUBE.value) or (
            not is_video and not check_source_type(media_type, source)
        ):
            return Response(
                {"detail": f"Cannot query `{source}` for `{media_type}` media type"},
                status=HTTP.BAD_REQUEST,
            )

        item_query = app_models.Item.objects.filter(
            media_type=detail_type,
            source=source,
            media_id=media_id,
        )
        if detail_type in {
            app_models.MediaTypes.SEASON.value,
            app_models.MediaTypes.EPISODE.value,
        } and season_number is not None:
            item_query = item_query.filter(
                season_number=season_number,
            )
            if media_type == app_models.MediaTypes.ANIME.value:
                item_query = item_query.filter(library_media_type=app_models.MediaTypes.ANIME.value)
            else:
                item_query = item_query.exclude(library_media_type=app_models.MediaTypes.ANIME.value)
        if (
            detail_type == app_models.MediaTypes.EPISODE.value
            and episode_number is not None
        ):
            item_query = item_query.filter(
                episode_number=episode_number,
            )
        item = item_query.first()
        viewer = request.user if getattr(request.user, "is_authenticated", False) else None
        public_view = request.query_params.get("public_view") == "1" or viewer is None
        tracked = None if public_view else _owned_media(viewer, item)

        try:
            with services.interactive_request_scope():
                is_child_detail = detail_type in {
                    app_models.MediaTypes.SEASON.value,
                    app_models.MediaTypes.EPISODE.value,
                }
                provider_metadata = services.get_media_metadata(
                    "tv_with_seasons" if is_child_detail else media_type,
                    media_id,
                    source,
                    language=metadata_resolution.metadata_language_default(viewer, item),
                    user=viewer,
                    **({"season_numbers": [season_number]} if is_child_detail else {}),
                )
                if is_child_detail:
                    metadata = provider_metadata.get(f"season/{season_number}")
                    if not metadata:
                        if item is None:
                            return Response({"detail": "Media not found."}, status=HTTP.NOT_FOUND)
                        metadata = stored_metadata_fallback(item)
                    else:
                        metadata = dict(metadata)
                        season_items = app_models.Item.objects.filter(
                            media_type="season", source=source, media_id=media_id, season_number=season_number,
                        )
                        season_items = (season_items.filter(library_media_type="anime") if media_type == "anime"
                                        else season_items.exclude(library_media_type="anime"))
                        season_item = item if detail_type == "season" else season_items.first()
                        season = None if public_view else _owned_media(viewer, season_item)
                        if metadata.get("episodes"):
                            processor = manual.process_episodes if source == "manual" else tmdb.process_episodes
                            metadata["episodes"] = processor(
                                metadata, season.episodes.all() if season else [], season=season,
                            )
                        if detail_type == "episode":
                            episode = next((entry for entry in metadata.get("episodes", [])
                                            if entry.get("episode_number") == episode_number), None)
                            if episode is None and item is None:
                                return Response({"detail": "Media not found."}, status=HTTP.NOT_FOUND)
                            metadata = dict(episode or stored_metadata_fallback(item))
                            metadata.setdefault("synopsis", metadata.get("overview") or "")
                else:
                    metadata = provider_metadata
        except services.ProviderAPIError as error:
            if item is not None:
                metadata = stored_metadata_fallback(item)
            elif error.status_code == HTTP.NOT_FOUND:
                return Response({"detail": "Media not found."}, status=HTTP.NOT_FOUND)
            else:
                return Response(
                    {"detail": "The provider could not load this detail."},
                    status=HTTP.BAD_GATEWAY,
                )
        except Exception:
            logger.exception("Structured detail projection failed for %s/%s", media_type, source)
            if item is None:
                return Response(
                    {"detail": "The provider could not load this detail."},
                    status=HTTP.BAD_GATEWAY,
                )
            metadata = stored_metadata_fallback(item)

        metadata = metadata if isinstance(metadata, dict) else {}
        metadata.setdefault("source", source)
        metadata.setdefault("media_type", media_type)
        metadata.setdefault("media_id", media_id)
        if not isinstance(metadata.get("related"), dict):
            metadata["related"] = {}
        if media_type in {app_models.MediaTypes.TV.value, app_models.MediaTypes.ANIME.value}:
            try:
                enrich_detail_seasons(
                    metadata,
                    media_id=media_id,
                    source=source,
                    user=viewer,
                    detail_item=item,
                    render_secondary_only=True,
                )
            except services.ProviderAPIError:
                logger.warning("Unable to enrich detail seasons for %s/%s", source, media_id)
        if viewer is not None and not getattr(viewer, "show_recommendations", True):
            metadata["related"].pop("recommendations", None)
        if not public_view:
            try:
                enrich_detail_related_cards(
                    request,
                    metadata,
                    media_type=media_type,
                    tracking_user=viewer,
                )
            except Exception:
                logger.exception("Unable to enrich detail cards for %s/%s", source, media_id)

        title_fields = app_models.Item.title_fields_from_metadata(
            metadata,
            fallback_title=item.title if item else "",
        )
        facts = []
        details = metadata.get("details") or {}
        if isinstance(details, dict):
            facts = [
                {"label": str(label), "value": str(value)}
                for label, value in details.items()
                if value not in (None, "", [], {})
            ]
        try:
            gallery = carousel.resolve_carousel_media(
                detail_type if detail_type in {"season", "episode"} else media_type,
                source,
                media_id,
                season_number=season_number,
                cached_only=True,
            )
        except Exception:
            logger.exception("Unable to resolve detail gallery for %s/%s", source, media_id)
            gallery = None
        if media_type == app_models.MediaTypes.VIDEO.value and not metadata.get("image"):
            metadata["image"] = f"https://i.ytimg.com/vi/{media_id}/hqdefault.jpg"

        score_chips = []
        score_builders = (
            ("Trakt", _build_trakt_popularity_context(item, media_type)),
            ("IMDb", _build_imdb_rating_context(item, media_type)),
            ("MyAnimeList", _build_mal_rating_context(item, media_type)),
            ("OpenCritic", _build_opencritic_context(item, media_type)),
        )
        for label, score in score_builders:
            if score:
                score_chips.append({"label": label, **_primitive(score)})
        if not public_view and tracked is not None and tracked.score is not None:
            score_chips.insert(0, {"label": "Your score", "value": _primitive(tracked.score), "kind": "viewer"})

        related_sections = []
        related = metadata.get("related") or {}
        section_labels = {
            "recommendations": "Recommendations",
            "sequels": "Sequels",
            "prequels": "Prequels",
            "similar": "Similar media",
            "related": "Related media",
            "dlcs": "DLCs",
            "expansions": "Standalone expansions",
            "remakes": "Remakes",
            "soundtracks": "Soundtracks",
            "collections": "Collections",
        }
        if isinstance(related, dict):
            for key, entries in related.items():
                if key == "seasons":
                    continue
                cards = [card for entry in _nonempty_list(entries) if (card := _media_card(entry, public_view=public_view))]
                if cards:
                    related_sections.append({"id": key, "label": section_labels.get(key, key.replace("_", " ").title()), "items": cards})

        people = {
            "cast": _primitive(metadata.get("cast") or []),
            "crew": _primitive(metadata.get("crew") or []),
        }
        person_rows = _build_detail_person_rows(metadata, item=item)
        if item is not None and item.media_type == app_models.MediaTypes.GAME.value and not people["cast"] and not people["crew"]:
            people["cast"] = _primitive(person_rows.get("cast_row", {}).get("items", []))
            people["crew"] = _primitive(person_rows.get("crew_row", {}).get("items", []))

        raw_episodes = _normalize_detail_episode_actions(metadata.get("episodes") or [])
        requested_page = request.query_params.get("episode_page", 1)
        try:
            episode_page = max(1, int(requested_page))
        except (TypeError, ValueError):
            episode_page = 1
        episode_rows, episode_load_more = _paginate_detail_episodes(request, raw_episodes)
        token = request.auth
        can_write = not hasattr(token, "has_scope") or token.has_scope("watchlist:write")
        children_kind = "issue" if media_type == app_models.MediaTypes.COMIC.value else "episode"
        child_media_type = "issue" if children_kind == "issue" else "episode"
        children = {
            "kind": children_kind,
            "seasons": [row for value in _nonempty_list(related.get("seasons")) if (row := _child_row(value, media_type="season", parent_media_type=media_type, source=source, media_id=media_id, public_view=public_view, can_write=can_write))],
            "episodes": [row for value in episode_rows if (row := _child_row(value, media_type=child_media_type, parent_media_type=media_type, source=source, media_id=media_id, public_view=public_view, can_write=can_write))],
            "next_page": episode_page + 1 if episode_load_more else None,
            "next_label": episode_load_more.get("label") if episode_load_more else None,
        }

        tag_sections = _build_detail_tag_sections(
            metadata,
            item,
            None if public_view else viewer,
            genre_list_media_type=media_type,
        )
        links = _build_detail_link_sections(
            metadata,
            media_type,
            source,
            metadata.get("display_provider") or source,
            item=item,
        )
        _apply_cached_hltb_link(metadata, item)
        game_lengths = _build_game_lengths_context(item) if media_type == app_models.MediaTypes.GAME.value else None
        youtube_watch = None
        if media_type == app_models.MediaTypes.GAME.value and tracked is not None and not public_view:
            try:
                youtube_watch = youtube_game_watch.watched_for_game(viewer, item)
            except Exception:
                logger.exception("Unable to build game YouTube activity for %s/%s", source, media_id)
        book_formats = [] if public_view else build_book_formats(viewer, item)
        providers = _primitive(metadata.get("providers") or {})
        activity_subtitle = None
        if tracked is not None and detail_type == "season":
            activity_subtitle = {
                "primary_text": f"Progress: {tracked.completed_episode_count}"
                + (f"/{metadata['max_progress']}" if metadata.get("max_progress") else ""),
                "date_start": tracked.start_date,
                "date_end": tracked.end_date,
            }
        elif tracked is not None and detail_type == media_type:
            try:
                _play_stats, activity_subtitle = _build_detail_activity_state(
                    media_type,
                    metadata,
                    current_instance=tracked,
                    user_medias=[tracked],
                )
            except Exception:
                logger.exception("Unable to build detail activity for %s/%s", source, media_id)
        collections = []
        if not public_view and viewer is not None and item is not None:
            collections = list(
                app_models.CollectionEntry.objects.filter(user=viewer, item=item)
                .order_by("-updated_at")
                .values(
                    "media_type",
                    "resolution",
                    "hdr",
                    "is_3d",
                    "audio_codec",
                    "audio_channels",
                    "bitrate",
                    "purchase_price",
                    "purchase_location",
                    "collected_at",
                ),
            )

        sections = []
        for section_id, label, value in (
            ("genres", "Genres", metadata.get("genres")),
            ("studios", "Studios", metadata.get("studios_full") or metadata.get("studios")),
        ):
            values = _nonempty_list(value)
            if values:
                sections.append({"id": section_id, "title": label, "items": _primitive(values)})

        progress = getattr(tracked, "progress", None)
        tracking = None if tracked is None else {
            "status": getattr(tracked, "status", None),
            "score": getattr(tracked, "score", None),
            "progress": progress,
            "max_progress": metadata.get("max_progress"),
            "notes": getattr(tracked, "notes", ""),
        }
        history = []
        if tracked is not None and not public_view:
            history = [
                {
                    "date": _primitive(entry.history_date),
                    "end_date": _primitive(getattr(entry, "end_date", None)),
                    "status": getattr(entry, "status", None),
                    "progress": getattr(entry, "progress", None),
                    "score": _primitive(getattr(entry, "score", None)),
                    "history_type": getattr(entry, "history_type", ""),
                }
                for entry in tracked.history.all().order_by("-history_date")[:8]
            ]
        is_authenticated = bool(viewer)
        return Response({
            "identity": {
                "media_type": detail_type,
                "parent_media_type": media_type if detail_type != media_type else None,
                "source": source,
                "media_id": media_id,
                "season_number": season_number,
                "episode_number": episode_number,
            },
            "title": title_fields.get("title") or metadata.get("title") or "",
            "alt_title": metadata.get("original_title") or "",
            "subtitle": metadata.get("subtitle") or metadata.get("series_name") or "",
            "season_title": metadata.get("season_header_title") or metadata.get("season_title") or "",
            "season_options": [
                row for value in _nonempty_list((provider_metadata.get("related") or {}).get("seasons"))
                if (row := _child_row(value, media_type="season", parent_media_type=media_type,
                                      source=source, media_id=media_id, public_view=public_view,
                                      can_write=can_write))
            ] if detail_type == "season" and isinstance(provider_metadata, dict) else [],
            "artwork": {
                "src": metadata.get("image") or "",
                "aspect": "poster",
                "backdrop": (gallery or {}).get("hero", {}).get("url") or (gallery or {}).get("overview", {}).get("url") or "",
                "logo": (gallery or {}).get("overview", {}).get("logo_url") or (gallery or {}).get("hero", {}).get("logo_url") or "",
                "gallery": _primitive(gallery or {"photos": [], "video": None}),
                "gallery_supported": carousel.carousel_supported(media_type, source),
            },
            "synopsis": metadata.get("synopsis") or "",
            "facts": facts,
            "sections": sections,
            "score_chips": _primitive(score_chips),
            "tag_sections": _primitive(tag_sections),
            "related_sections": related_sections,
            "people": people,
            "children": children,
            "providers": providers,
            "link_sections": _primitive(links),
            "game_lengths": _primitive(game_lengths),
            "youtube_watch": _primitive(youtube_watch),
            "book_formats": _primitive(book_formats),
            "detail_links": _primitive(person_rows),
            "media_details": _primitive(details),
            "activity_subtitle": _primitive(activity_subtitle),
            "collections": _primitive(collections),
            "tracking": tracking,
            "history": history,
            "read_only": public_view or not is_authenticated,
            "public_view": public_view or not is_authenticated,
            "capabilities": {
                "can_track": (
                    is_authenticated
                    and can_write
                    and not public_view
                    and tracked is None
                    and detail_type not in {
                        app_models.MediaTypes.VIDEO.value,
                        app_models.MediaTypes.EPISODE.value,
                    }
                ),
                "can_update": (
                    is_authenticated
                    and can_write
                    and not public_view
                    and tracked is not None
                    and (detail_type != app_models.MediaTypes.EPISODE.value or media_type == app_models.MediaTypes.TV.value)
                ),
            },
        }, status=HTTP.OK)


class DetailGalleryView(drf_views.APIView):
    """Resolve deferred detail-gallery media without returning HTML."""

    permission_classes = [PublicDetailRead]

    @extend_schema(
        parameters=[OpenApiParameter("season_number", int, required=False)],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, media_type, source, media_id):
        """Return clearlogo, backdrop, photos and trailer data for the hero."""
        season_number = request.query_params.get("season_number")
        try:
            season_number = int(season_number) if season_number is not None else None
            if not check_valid_type(media_type) or not check_source_type(media_type, source):
                return Response({"detail": "Unsupported media identity."}, status=HTTP.BAD_REQUEST)
            if not carousel.carousel_supported(media_type, source):
                return Response({"gallery": None}, status=HTTP.OK)
            gallery = carousel.resolve_carousel_media(
                media_type,
                source,
                media_id,
                season_number=season_number,
                cached_only=False,
            )
        except (TypeError, ValueError):
            return Response({"detail": "Invalid season number."}, status=HTTP.BAD_REQUEST)
        except Exception:
            logger.exception("Deferred detail gallery failed for %s/%s", source, media_id)
            return Response({"detail": "The artwork gallery could not be loaded."}, status=HTTP.BAD_GATEWAY)
        if gallery is None:
            return Response({"gallery": None}, status=HTTP.OK)
        return Response({"gallery": _primitive(gallery)}, status=HTTP.OK)
