# FORK: detail-page endpoints the native app needs that only existed as
# session HTML views. URL wiring lives in fork_urls.py.
from http import HTTPStatus as HTTP  # noqa: N814

from django.templatetags.static import static
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

from app.models import CollectionEntry, Item, MediaTypes
from integrations import seerr_api
from integrations.imports import helpers as import_helpers

from .contract_serializers import DetailErrorSerializer
from .fork_serializers import CollectionEntrySerializer
from .schema import MEDIA_TYPE_TV_ONLY_PARAM
from .serializers import serialize_data


def _seerr_configured(user):
    return bool(user.seerr_url and user.seerr_api_key and user.seerr_user_id)


# /api/v1/media/[type]/[source]/[id]/request/
class MediaSeerrRequestView(drf_views.APIView):
    """Show a title's Seerr state and request it (mirrors seerr_request).

    The web view takes a TMDB id; this one does too, so it applies to
    ``tmdb`` movies and shows only. Anything else, or a user without Seerr
    configured, is a 404 like the web panel.
    """

    def _client(self, request, media_type, source):
        if (
            media_type not in (MediaTypes.MOVIE.value, MediaTypes.TV.value)
            or source != "tmdb"
            or not _seerr_configured(request.user)
        ):
            return None
        return seerr_api.SeerrClient.for_user(request.user)

    def _summary(self, request, client, media_type, media_id):
        return {
            **seerr_api.summarize(media_type, client.media(media_type, media_id)),
            "seerr_url": f"{request.user.seerr_url}/{media_type}/{media_id}",
        }

    @extend_schema(
        operation_id="retrieveMediaSeerrRequest",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, media_type, source, media_id):
        """Return the Seerr request state for the title."""
        try:
            client = self._client(request, media_type, source)
            if client is None:
                return Response({"detail": "Seerr is not available."}, status=HTTP.NOT_FOUND)
            return Response(self._summary(request, client, media_type, media_id))
        except (seerr_api.SeerrError, import_helpers.MediaImportError) as error:
            return Response({"detail": str(error)}, status=HTTP.BAD_GATEWAY)

    @extend_schema(
        request=OpenApiTypes.OBJECT,
        operation_id="requestMediaInSeerr",
        responses={200: OpenApiTypes.OBJECT},
    )
    def post(self, request, media_type, source, media_id):
        """Request the title (all seasons, or the listed `seasons`)."""
        try:
            client = self._client(request, media_type, source)
            if client is None:
                return Response({"detail": "Seerr is not available."}, status=HTTP.NOT_FOUND)
            raw = request.data.get("seasons") or []
            seasons = [int(n) for n in raw if str(n).isdigit()] if isinstance(raw, list) else []
            client.request(
                media_type,
                media_id,
                request.user.seerr_user_id,
                seasons=seasons or None,
            )
            return Response(self._summary(request, client, media_type, media_id))
        except (seerr_api.SeerrError, import_helpers.MediaImportError) as error:
            return Response({"detail": str(error)}, status=HTTP.BAD_GATEWAY)


def _collection_stats(request, tracked_type, lookup):
    """Return the web Collection card's collected seasons and episodes counts, or None.

    Only shows and seasons have them; they are computed by the same helpers the
    detail page uses.
    """
    from app.helpers import get_season_collection_stats, get_tv_show_collection_stats
    from app.media_details_views import _metadata_episode_count
    from app.providers import services

    if tracked_type in (MediaTypes.TV.value, MediaTypes.ANIME.value):
        item = Item.objects.filter(media_type=tracked_type, **lookup).first()
        if not item:
            return None
        # The web card counts episodes from the provider metadata, like the Details card.
        try:
            metadata = services.get_media_metadata(tracked_type, item.media_id, item.source)
            episode_count = _metadata_episode_count(metadata)
        except Exception:
            episode_count = None
        return get_tv_show_collection_stats(
            request.user, item, metadata_episode_count=episode_count,
        )
    if tracked_type == MediaTypes.SEASON.value:
        item = Item.objects.filter(media_type=tracked_type, **lookup).first()
        return get_season_collection_stats(request.user, item) if item else None
    return None


def _collection_entries(request, tracked_type, **lookup):
    item_ids = Item.objects.filter(media_type=tracked_type, **lookup).values("id")
    entries = (
        CollectionEntry.objects.filter(user=request.user, item_id__in=item_ids)
        .select_related("item")
        .order_by("-collected_at", "-id")
    )
    payload = {
        "results": serialize_data(
            list(entries),
            many=True,
            serializer_class=CollectionEntrySerializer,
        ),
    }
    stats = _collection_stats(request, tracked_type, lookup)
    if stats is not None:
        payload["stats"] = stats
    return Response(
        payload,
        status=HTTP.OK,
    )


# /api/v1/media/[type]/[source]/[id]/collection/entries/
class MediaCollectionEntriesView(drf_views.APIView):
    """List the caller's owned copies of one item, addressed by identity.

    ``GET /collection/`` pages the whole collection, so a client looking for
    one title past the first page never found it; this answers for the title
    itself, and the season and episode variants for a show's parts.
    """

    @extend_schema(
        operation_id="listMediaCollectionEntries",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, media_type, source, media_id):
        """Return the caller's collection entries for the item."""
        return _collection_entries(
            request,
            media_type,
            media_id=media_id,
            source=source,
        )


# /api/v1/media/tv/[source]/[id]/[season]/collection/entries/
class MediaSeasonCollectionEntriesView(drf_views.APIView):
    """Season variant of MediaCollectionEntriesView."""

    @extend_schema(
        parameters=[MEDIA_TYPE_TV_ONLY_PARAM],
        operation_id="listMediaSeasonCollectionEntries",
        responses={200: OpenApiTypes.OBJECT, 400: DetailErrorSerializer},
    )
    def get(self, request, media_type, source, media_id, season_number):
        """Return the caller's collection entries for one season."""
        if media_type != MediaTypes.TV.value:
            return Response(
                {"detail": "Seasons and episodes are supported only for 'tv'."},
                status=HTTP.BAD_REQUEST,
            )
        return _collection_entries(
            request,
            MediaTypes.SEASON.value,
            media_id=media_id,
            source=source,
            season_number=int(season_number),
        )


# /api/v1/media/tv/[source]/[id]/[season]/[episode]/collection/entries/
class MediaEpisodeCollectionEntriesView(drf_views.APIView):
    """Episode variant of MediaCollectionEntriesView."""

    @extend_schema(
        parameters=[MEDIA_TYPE_TV_ONLY_PARAM],
        operation_id="listMediaEpisodeCollectionEntries",
        responses={200: OpenApiTypes.OBJECT, 400: DetailErrorSerializer},
    )
    def get(self, request, media_type, source, media_id, season_number, episode_number):
        """Return the caller's collection entries for one episode."""
        if media_type != MediaTypes.TV.value:
            return Response(
                {"detail": "Seasons and episodes are supported only for 'tv'."},
                status=HTTP.BAD_REQUEST,
            )
        return _collection_entries(
            request,
            MediaTypes.EPISODE.value,
            media_id=media_id,
            source=source,
            season_number=int(season_number),
            episode_number=int(episode_number),
        )


def _progress_payload(breakdown_model):
    """Return the card plus the full breakdown the web dialog opens, in one payload."""
    model = breakdown_model["model"]
    summary = model["summary"]
    return {
        "card": {
            "percent": summary["percent"],
            "caughtUp": bool(summary["caughtUp"]),
            "runKey": model["runKey"],
            "rewatch": summary["rewatch"],
        },
        "model": model,
    }


def _watched_text(instance):
    """Return the show hero's watched duration ("2h 48min"), as the web prints it."""
    from app.activity_builders import (
        _build_detail_activity_state,
        _format_detail_activity_duration,
    )
    from app.models import TV

    if not isinstance(instance, TV):
        return ""
    play_stats, _subtitle = _build_detail_activity_state(
        instance.item.media_type, {}, current_instance=instance, user_medias=[instance],
    )
    text = _format_detail_activity_duration((play_stats or {}).get("total_minutes"), "watched")
    return (text or "").removesuffix(" watched")


# /api/v1/media/tv/[source]/[id]/progress-card/
class MediaProgressCardView(drf_views.APIView):
    """The "Your Progress" card and breakdown of a tracked show or season.

    The same projection the web card and its dialog render
    (``app.progress_views``); 404 when the caller does not track the title.
    """

    def _instance(self, request, media_type, source, media_id, season_number):
        from app.models import TV, Season

        if media_type not in (MediaTypes.TV.value, MediaTypes.ANIME.value):
            return None
        lookup = {
            "user": request.user,
            "item__media_id": media_id,
            "item__source": source,
        }
        if season_number is None:
            return TV.objects.select_related("item").filter(
                item__media_type=media_type, **lookup,
            ).first()
        return Season.objects.select_related("item", "related_tv__item").filter(
            item__season_number=int(season_number), **lookup,
        ).first()

    @extend_schema(
        operation_id="retrieveMediaProgressCard",
        responses={200: OpenApiTypes.OBJECT, 404: DetailErrorSerializer},
    )
    def get(self, request, media_type, source, media_id, season_number=None):
        """Return the progress card and breakdown model."""
        from app.models import Season
        from app.progress_views import _presentation
        from app.services.progress_breakdown import build_progress_breakdown

        instance = self._instance(request, media_type, source, media_id, season_number)
        if instance is None:
            return Response({"detail": "Progress is not tracked."}, status=HTTP.NOT_FOUND)
        breakdown = build_progress_breakdown(
            **({"season": instance} if isinstance(instance, Season) else {"tv": instance}),
        )
        if breakdown.percent is None:
            return Response({"detail": "Progress is not tracked."}, status=HTTP.NOT_FOUND)
        payload = _progress_payload(_presentation(breakdown))
        payload["watched_text"] = _watched_text(instance)
        return Response(payload)


# /api/v1/media/tv/[source]/[id]/[season]/progress-card/
class MediaSeasonProgressCardView(MediaProgressCardView):
    """Season variant of MediaProgressCardView."""

    @extend_schema(
        operation_id="retrieveMediaSeasonProgressCard",
        parameters=[MEDIA_TYPE_TV_ONLY_PARAM],
        responses={200: OpenApiTypes.OBJECT, 404: DetailErrorSerializer},
    )
    def get(self, request, media_type, source, media_id, season_number):
        """Return the season's progress card and breakdown model."""
        return super().get(request, media_type, source, media_id, season_number)


# /api/v1/media/[type]/[source]/[id]/checkin/
class MediaCheckInView(drf_views.APIView):
    """The detail page's Check-in split button (mirrors ``checkin_views``).

    GET lists the actions the web button offers for the caller's entry; POST
    runs one of them. Anything that cannot be checked in, or is not tracked, is
    a 404 like the web, which shows no Check-in button there.
    """

    def _phase(self, request, media_type, source, media_id):
        from app import checkin
        from app.models import BasicMedia
        from app.services.completion import select_preferred_activity_entry

        current = select_preferred_activity_entry(
            BasicMedia.objects.filter_media_prefetch(
                request.user, media_id, media_type, source,
            ),
        )
        if current is None:
            return None, None
        return current, checkin.phase(request.user, current)

    @extend_schema(
        operation_id="retrieveMediaCheckIn",
        responses={200: OpenApiTypes.OBJECT, 404: DetailErrorSerializer},
    )
    def get(self, request, media_type, source, media_id):
        """Return the Check-in actions for the tracked entry."""
        from app import checkin_session
        from app.track_actions import track_actions

        checkin_session.settle(request.user.id)
        current, phase = self._phase(request, media_type, source, media_id)
        if current is None or phase is None:
            return Response({"detail": "Check-in is not available."}, status=HTTP.NOT_FOUND)
        actions = track_actions(current.item.media_type, current.status, phase)
        return Response({
            "phase": phase["phase"],
            "actions": [
                {key: str(value) for key, value in action.items()} for action in actions
            ],
        })

    @extend_schema(
        operation_id="createMediaCheckInAction",
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT, 400: DetailErrorSerializer, 404: DetailErrorSerializer},
    )
    def post(self, request, media_type, source, media_id):
        """Run one Check-in action (start, resume, pause, finish, stop, cancel, log_play)."""
        from app import checkin, checkin_session
        from app.checkin_views import ACTIONS, SESSION_ACTIONS

        name = request.data.get("action")
        if checkin_session.supports(media_type):
            action = SESSION_ACTIONS.get(name)
            arguments = (request.user, source, media_type, media_id)
        else:
            action = ACTIONS.get(name) if checkin.supports(media_type, source) else None
            arguments = (request.user, media_type, media_id)
        if action is None:
            return Response({"detail": "Unsupported check-in."}, status=HTTP.BAD_REQUEST)
        try:
            action(*arguments)
        except checkin.CheckInError as error:
            return Response({"detail": error.message}, status=HTTP.BAD_REQUEST)
        return self.get(request, media_type, source, media_id)


# /api/v1/media/tv/[source]/[id]/collect/
# /api/v1/media/tv/[source]/[id]/[season]/collect/
class MediaShowCollectView(drf_views.APIView):
    """Add a copy of every episode of a show or season to the collection.

    The detail page's Collection "add" for a show or season (web
    ``collection_add`` for a season or show item): each episode without a copy
    gets one carrying the sent format fields; episodes already collected are
    left alone. Fields are validated like ``MediaCollectionView``.
    """

    @extend_schema(
        operation_id="updateMediaShowCollection",
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT, 400: DetailErrorSerializer, 404: DetailErrorSerializer},
    )
    def put(self, request, media_type, source, media_id, season_number=None):
        """Collect every episode under the show or season."""
        from app.collection_views import _expand_collection_entry_to_episodes

        from .fork_views import MediaCollectionView

        if media_type not in (MediaTypes.TV.value, MediaTypes.ANIME.value):
            return Response({"detail": "Only shows are collected this way."}, status=HTTP.BAD_REQUEST)
        fields, error = MediaCollectionView()._entry_fields(request.data)
        if error is not None:
            return error
        lookup = {"media_id": media_id, "source": source}
        if season_number is None:
            lookup["media_type"] = media_type
        else:
            lookup.update(media_type=MediaTypes.SEASON.value, season_number=int(season_number))
        item = Item.objects.filter(**lookup).first()
        if item is None:
            return Response({"detail": "Title not found."}, status=HTTP.NOT_FOUND)
        created, skipped = _expand_collection_entry_to_episodes(
            request.user, item, cleaned_data=fields,
        )
        return Response({"created": len(created), "already_collected": skipped})


class MediaSeasonCollectView(MediaShowCollectView):
    """Season variant of MediaShowCollectView."""

    @extend_schema(
        operation_id="updateMediaSeasonCollection",
        parameters=[MEDIA_TYPE_TV_ONLY_PARAM],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT, 400: DetailErrorSerializer, 404: DetailErrorSerializer},
    )
    def put(self, request, media_type, source, media_id, season_number):
        """Collect every episode under the season."""
        return super().put(request, media_type, source, media_id, season_number)


def _stored_item(media_type, source, media_id, season_number=None):
    """Return the catalog Item behind a detail route, or None."""
    lookup = {"source": source, "media_id": str(media_id)}
    if season_number is not None:
        lookup.update(media_type=MediaTypes.SEASON.value, season_number=int(season_number))
    else:
        lookup["media_type"] = media_type
    return Item.objects.filter(**lookup).first()


# /api/v1/media/[type]/[source]/[id]/artwork/
class MediaArtworkView(drf_views.APIView):
    """Backdrop hero, title logo, trailer and gallery behind a detail page.

    The data the web ``detail_carousel_fragment.html`` renders
    (``app.carousel.resolve_carousel_media``). ``available`` is false when the
    source has no gallery (manual items, non TMDB/IGDB sources).
    """

    @extend_schema(
        operation_id="retrieveMediaArtwork",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, media_type, source, media_id, season_number=None):
        """Return the carousel media of one title."""
        from app import carousel as carousel_media

        lookup_type = MediaTypes.SEASON.value if season_number is not None else media_type
        empty = {"available": False, "video": None, "overview": None, "hero": None, "photos": []}
        if not carousel_media.carousel_supported(lookup_type, source):
            return Response(empty)
        data = carousel_media.resolve_carousel_media(
            lookup_type, source, media_id,
            season_number=int(season_number) if season_number is not None else None,
        )
        if not data:
            return Response(empty)
        return Response({
            "available": True,
            "video": data.get("video"),
            "overview": data.get("overview"),
            "hero": data.get("hero"),
            "photos": data.get("photos") or [],
        })


# /api/v1/media/tv/[source]/[id]/[season]/artwork/
class MediaSeasonArtworkView(MediaArtworkView):
    """Season variant of MediaArtworkView."""

    @extend_schema(
        operation_id="retrieveMediaSeasonArtwork",
        parameters=[MEDIA_TYPE_TV_ONLY_PARAM],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, media_type, source, media_id, season_number):
        """Return the season's carousel media."""
        return super().get(request, media_type, source, media_id, season_number)


# Static logo of each score chip, as the web chip shows it (others show the source's initials).
_SCORE_LOGOS = {
    "tmdb": "img/tmdb-logo.png",
    "mal": "img/myanimelist-logo.svg",
    "igdb": "img/igdb-logo.png",
    "trakt": "img/trakt-logo.svg",
    "imdb": "img/imdb-logo.png",
    "opencritic": "img/opencritic-logo.svg",
}


# /api/v1/media/comic/[source]/[id]/issues/
class MediaIssuesView(drf_views.APIView):
    """A comic volume's issues, as the web "Issues" list reads them (cover, number, date, read)."""

    @extend_schema(
        operation_id="listMediaIssues",
        responses={200: OpenApiTypes.OBJECT, 400: DetailErrorSerializer},
    )
    def get(self, request, media_type, source, media_id):
        """Return one page of the volume's issues with the viewer's read state."""
        if media_type != MediaTypes.COMIC.value:
            return Response(
                {"detail": "Issues are supported only for 'comic'."}, status=HTTP.BAD_REQUEST,
            )
        from app.media_details_views import _enrich_comic_issues
        from app.providers import services

        try:
            limit = max(1, min(int(request.query_params.get("limit", 20)), 100))
            offset = max(0, int(request.query_params.get("offset", 0)))
        except ValueError:
            return Response({"detail": "limit and offset must be integers."}, status=HTTP.BAD_REQUEST)
        metadata = services.get_media_metadata(media_type, media_id, source)
        issues = _enrich_comic_issues(metadata.get("issues") or [], request.user, source)
        return Response({
            "pagination": {"total": len(issues), "limit": limit, "offset": offset},
            "results": [
                {
                    "media_id": str(issue["media_id"]),
                    "source": issue["source"],
                    "title": issue.get("title") or "",
                    "issue_number": str(issue.get("issue_number") or ""),
                    "cover_date": issue.get("cover_date") or "",
                    "image": issue.get("image") or "",
                    "read": bool(issue.get("history")),
                }
                for issue in issues[offset:offset + limit]
            ],
        })


class MediaAnimeEpisodesView(drf_views.APIView):
    """The read-only grouped episode preview of a flat anime detail page."""

    @extend_schema(operation_id="listMediaAnimeEpisodes", parameters=[OpenApiParameter("episode_page", int, OpenApiParameter.QUERY)], responses={200: OpenApiTypes.OBJECT})
    def get(self, request, media_type, source, media_id):
        """Reuse the web preview and retain each mapped provider identity."""
        from django.db.models import OuterRef, Q, Subquery

        from app.activity_builders import _paginate_detail_episodes
        from app.metadata_sync_views import _build_flat_anime_episode_preview
        from app.models import BasicMedia, Episode
        from app.providers import services
        from app.services import metadata_resolution
        from users.appearance import resolved_detail_layouts

        if media_type != MediaTypes.ANIME.value:
            return Response({"detail": "Episode previews are supported only for 'anime'."}, status=HTTP.BAD_REQUEST)
        metadata = services.get_media_metadata(media_type, media_id, source)
        detail_item = _stored_item(media_type, source, media_id)
        resolved = metadata_resolution.resolve_detail_metadata(
            request.user, item=detail_item, route_media_type=media_type,
            media_id=media_id, source=source, base_metadata=metadata,
            persistence_mode="best_effort", persist_links=False,
        ) if detail_item else None
        display_metadata = resolved.header_metadata if resolved else metadata
        rows = metadata.get("episodes")
        if not isinstance(rows, list):
            rows = _build_flat_anime_episode_preview(
                request, detail_item=detail_item,
                media_id=media_id, base_metadata=metadata, metadata_resolution_result=resolved,
            ) or []
        total = len(rows)
        rows, load_more = _paginate_detail_episodes(request, rows)
        # A rating without a watch is deliberately absent from Episode.objects
        # and the web preview's history. Resolve only this page's identities,
        # selecting at most one viewer-owned rating per catalog episode.
        coordinates = Q(pk__in=[])
        for row in rows:
            if row.get("season_number") is not None and row.get("episode_number") is not None:
                coordinates |= Q(source=row.get("source") or source, media_id=str(row.get("media_id") or media_id),
                                 season_number=row["season_number"], episode_number=row["episode_number"])
        rating_rows = Episode.ratings.filter(
            related_season__user=request.user, item_id=OuterRef("pk"), rating_only=True,
        ).order_by("-scored_at", "-pk")
        page_ratings = {
            (episode.source, str(episode.media_id), episode.season_number, episode.episode_number): episode
            for episode in Item.objects.filter(coordinates, media_type=MediaTypes.EPISODE.value).annotate(
                preview_score=Subquery(rating_rows.values("score")[:1]),
                preview_rating_season=Subquery(rating_rows.values("related_season_id")[:1]),
            ).only("source", "media_id", "season_number", "episode_number")
        }
        for index, row in enumerate(rows):
            rating = page_ratings.get((row.get("source") or source, str(row.get("media_id") or media_id),
                                       row.get("season_number"), row.get("episode_number")))
            if rating is not None and rating.preview_rating_season:
                rows[index] = {**row, "unwatched_score": rating.preview_score,
                               "rating_season_id": row.get("rating_season_id") or rating.preview_rating_season}
        visible_content = resolved_detail_layouts(request.user.detail_page_layouts).get("series", {}).get("content", [])
        related = display_metadata.get("related") or {} if "related" in visible_content else {}
        tracked = BasicMedia.objects.filter_media(request.user, media_id, media_type, source).exists()
        return Response({"pagination": {"total": total}, "load_more": load_more,
                         "related": related, "results": [
            {
                "item": {
                    "media_id": str(row.get("media_id") or media_id),
                    "source": row.get("source") or source,
                    "title": row.get("title") or "",
                    "season_number": row.get("season_number"),
                    "episode_number": row.get("episode_number"),
                    "image": row.get("image") or "",
                },
                "display_episode_number": row.get("display_episode_number") or row.get("episode_number"),
                "overview": row.get("overview") or "",
                "air_date": row.get("air_date"),
                "runtime": row.get("runtime"),
                "watched": bool(row.get("history") or row.get("watched_by_progress")),
                "collected": bool(row.get("collection_entry")),
                "can_list": bool(row.get("item")),
                "can_rate": bool(request.user.ratings_enabled and (tracked or row.get("rating_season_id"))),
                "score": next((entry.score for entry in row.get("history") or [] if getattr(entry, "score", None) is not None), row.get("unwatched_score")),
            }
            for row in rows
        ]})


# /api/v1/media/[type]/[source]/[id]/scores/
class MediaScoresView(drf_views.APIView):
    """Stored provider score chips and series graphs, as the web chip row reads them.

    Chips: Trakt, IMDb, MyAnimeList and OpenCritic from the stored Item fields
    (``app.detail_builders._build_*_context``). Graphs (TV and anime only) are
    the stored episode-rating grids behind the web "View series graph" popover.
    """

    @extend_schema(
        operation_id="retrieveMediaScores",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, media_type, source, media_id, season_number=None):
        """Return the stored score chips, series graphs and game lengths of one title."""
        from app.detail_builders import (
            _build_game_lengths_context,
            _build_imdb_rating_context,
            _build_mal_rating_context,
            _build_opencritic_context,
            _build_series_graph_data,
            _build_stored_season_scores_graph,
            _build_trakt_popularity_context,
        )

        item = _stored_item(media_type, source, media_id, season_number)
        route_type = MediaTypes.SEASON.value if season_number is not None else media_type
        chips = []
        if item is not None:
            if item.provider_rating is not None and item.provider_rating_count is not None:
                chips.append({
                    "key": "provider",
                    "label": source,
                    "rating": round(float(item.provider_rating), 1),
                    "count": item.provider_rating_count,
                })
            trakt = _build_trakt_popularity_context(item, route_type)
            if trakt:
                chips.append({"key": "trakt", "label": "Trakt",
                              "rating": trakt["rating"], "count": trakt["rating_count"]})
            imdb = _build_imdb_rating_context(item, route_type)
            if imdb:
                chips.append({"key": "imdb", "label": "IMDb",
                              "rating": imdb["rating"], "count": imdb["rating_count"]})
            mal = _build_mal_rating_context(item, route_type)
            if mal:
                chips.append({"key": "mal", "label": "MyAnimeList",
                              "rating": mal["rating"], "count": mal["rating_count"]})
            critic = _build_opencritic_context(item, route_type)
            if critic:
                chips.append({
                    "key": "opencritic", "label": "OpenCritic", "rating": critic["score"],
                    "count": None, "percentRecommended": critic["percent_recommended"],
                    "tier": critic["tier"], "url": critic["url"],
                })
        graphs = {}
        if route_type in (MediaTypes.TV.value, MediaTypes.ANIME.value):
            for key, flags in (("provider", {}), ("trakt", {"use_trakt": True}),
                               ("imdb", {"use_imdb": True})):
                graph = _build_series_graph_data(source, media_id, **flags) \
                    or _build_stored_season_scores_graph(source, media_id, **flags)
                if graph:
                    graphs[key] = graph
        lengths = (
            _build_game_lengths_context(item)
            if item is not None and route_type == MediaTypes.GAME.value else None
        )
        game_lengths = None
        if lengths:
            game_lengths = {
                "available": bool(lengths.get("available")),
                "sourceLabel": lengths.get("source_label") or "",
                "sourceUrl": lengths.get("source_url") or "",
                "cards": [
                    {"label": card["label"], "value": card["value"], "count": card["count"]}
                    for card in lengths.get("cards") or []
                ],
            }
        logos = {
            key: request.build_absolute_uri(static(path))
            for key, path in {
                "provider": _SCORE_LOGOS.get(source),
                **{key: _SCORE_LOGOS[key] for key in ("trakt", "imdb", "mal", "opencritic")},
            }.items()
            if path
        }
        return Response({
            "chips": chips, "graphs": graphs, "gameLengths": game_lengths, "logos": logos,
        })


# /api/v1/media/tv/[source]/[id]/[season]/scores/
class MediaSeasonScoresView(MediaScoresView):
    """Season variant of MediaScoresView."""

    @extend_schema(
        operation_id="retrieveMediaSeasonScores",
        parameters=[MEDIA_TYPE_TV_ONLY_PARAM],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, media_type, source, media_id, season_number):
        """Return the season's stored score chips."""
        return super().get(request, media_type, source, media_id, season_number)


# /api/v1/media/[type]/[source]/[id]/activity-timeline/
class MediaActivityTimelineView(drf_views.APIView):
    """The "Activity History" dialog entries, as the web ``history_modal`` builds them.

    Same ``history_processor`` output (formatted change descriptions per
    record), newest first, grouped by the day of the record in the viewer's
    zone and date format. ``id`` deletes through the ``history`` endpoint.
    """

    @extend_schema(
        operation_id="retrieveMediaActivityTimeline",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, media_type, source, media_id, season_number=None, episode_number=None):
        """Return the viewer's activity entries for one title."""
        from django.utils import timezone

        from app import history_processor
        from app.models import BasicMedia
        from users.templatetags.user_tags import user_date_format, user_datetime_format

        lookup_type = media_type
        if season_number is not None:
            lookup_type = (
                MediaTypes.EPISODE.value if episode_number is not None else MediaTypes.SEASON.value
            )
        medias = list(
            BasicMedia.objects.filter_media(
                request.user, media_id, lookup_type, source,
                season_number=season_number, episode_number=episode_number,
            ).order_by("created_at", "pk")
        )
        entries = []
        for number, media in enumerate(medias, start=1):
            history = media.history.all()
            if lookup_type == MediaTypes.PODCAST.value:
                history = history.filter(end_date__isnull=False)
            entries.extend(
                {
                    "id": entry["id"],
                    "instanceId": entry["instance_id"],
                    "instance": number,
                    "when": entry["date"],
                    "date": user_datetime_format(entry["date"], request.user),
                    "changes": [str(change["description"]) for change in entry["changes"]],
                }
                for entry in history_processor.process_history_entries(
                    history, lookup_type, number, request.user,
                )
            )
        entries.sort(key=lambda row: row["when"], reverse=True)
        days = []
        for row in entries:
            day = timezone.localtime(row["when"]).strftime("%Y-%m-%d")
            if not days or days[-1]["day"] != day:
                days.append({"day": day, "label": user_date_format(row["when"], request.user), "entries": []})
            days[-1]["entries"].append({**row, "when": row["when"].isoformat()})
        return Response({"multipleInstances": len(medias) > 1, "days": days})


# /api/v1/media/tv/[source]/[id]/[season]/activity-timeline/
class MediaSeasonActivityTimelineView(MediaActivityTimelineView):
    """Season variant with a distinct schema operation."""

    @extend_schema(
        operation_id="retrieveMediaSeasonActivityTimeline",
        parameters=[MEDIA_TYPE_TV_ONLY_PARAM],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, media_type, source, media_id, season_number):
        """Return the activity entries of a season."""
        return super().get(request, media_type, source, media_id, season_number)


# /api/v1/media/tv/[source]/[id]/[season]/[episode]/activity-timeline/
class MediaEpisodeActivityTimelineView(MediaActivityTimelineView):
    """Episode variant of MediaActivityTimelineView."""

    @extend_schema(
        operation_id="retrieveMediaEpisodeActivityTimeline",
        parameters=[MEDIA_TYPE_TV_ONLY_PARAM],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, media_type, source, media_id, season_number, episode_number=None):
        """Return the activity entries of a season or episode."""
        return super().get(request, media_type, source, media_id, season_number, episode_number)
