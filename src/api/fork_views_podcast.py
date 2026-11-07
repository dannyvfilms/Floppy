# FORK: first-class podcast endpoints (shows, episodes, plays) mirroring
# the web podcast views. URL wiring lives in fork_urls.py.
import json
import logging
from http import HTTPStatus as HTTP  # noqa: N814

from django.core.cache import cache
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import views as drf_views
from rest_framework.response import Response

from app import fork_services_podcast, helpers
from app.forms import PodcastShowTrackerForm
from app.log_safety import safe_url
from app.models import PodcastEpisode, PodcastShow, PodcastShowTracker, Status
from app.podcast_views import podcast_episodes_api
from app.providers import pocketcasts, services
from app.services import podcast_import
from integrations import podcast_rss

from .helpers import (
    get_media_status,
    make_page_url,
    paginate_data,
    parse_limit_offset,
    try_parse_datetime_input,
)
from .serializers import serialize_data

logger = logging.getLogger(__name__)

_TRACKER_FIELDS = ("score", "status", "start_date", "end_date", "notes")


def _serialize_show(show, tracker=None):
    """Return a show payload with the caller's tracker."""
    tracker_payload = None
    if tracker is not None:
        tracker_payload = {
            "status": get_media_status(tracker.status),
            "score": str(tracker.score) if tracker.score is not None else None,
            "start_date": tracker.start_date,
            "end_date": tracker.end_date,
            "notes": tracker.notes,
            "created_at": tracker.created_at,
            "updated_at": tracker.updated_at,
        }
    return {
        "id": show.id,
        "podcast_uuid": show.podcast_uuid,
        "source": show.source,
        "title": show.title,
        "author": show.author,
        "image": show.image,
        "description": show.description,
        "genres": show.genres,
        "language": show.language,
        # No rss_feed_url: shows are a shared catalog and an imported
        # feed URL can carry the importing user's private token.
        "website_url": show.website_url,
        "tracker": tracker_payload,
    }


class _PlaceholderShow:
    """Stand-in for pre-validating tracker fields before a show exists."""

    id = 0


def _bind_show_form(data, instance, show):
    """Bind PodcastShowTrackerForm with partial-update semantics (raw scores)."""
    merged = {"show_id": show.id}
    for field in _TRACKER_FIELDS:
        current = getattr(instance, field, None) if instance else None
        merged[field] = current if current is not None else ""
    for field in _TRACKER_FIELDS:
        if field in data:
            merged[field] = data[field] if data[field] is not None else ""
    if not merged.get("status"):
        merged["status"] = Status.IN_PROGRESS.value  # model default
    return PodcastShowTrackerForm(merged, instance=instance)


# /api/v1/podcasts/shows/
class PodcastShowsView(drf_views.APIView):
    """List tracked shows or start tracking one."""

    def get(self, request):
        """Return the caller's show trackers."""
        limit, offset, err = parse_limit_offset(request)
        if err:
            return err
        trackers = PodcastShowTracker.objects.filter(
            user=request.user,
        ).select_related("show")
        results = [_serialize_show(tracker.show, tracker) for tracker in trackers]
        return Response(
            paginate_data(request, results, limit, offset),
            status=HTTP.OK,
        )

    def post(self, request):
        """Track a show by show_id, or import+track one by itunes_id.

        Mirrors podcast_show_save. When 'itunes_id' is given instead of
        'show_id', resolves it the same way the web search-result page
        does: reuse an already-imported show with the same RSS feed, or
        create the show and import its episode catalog from the feed.
        """
        show_id = request.data.get("show_id")
        itunes_id = request.data.get("itunes_id")
        if not show_id and not itunes_id:
            return Response(
                {"detail": "'show_id' or 'itunes_id' is required."},
                status=HTTP.BAD_REQUEST,
            )

        if show_id:
            show = PodcastShow.objects.filter(id=show_id).first()
            if show is None:
                return Response({"detail": "Show not found."}, status=HTTP.NOT_FOUND)
        else:
            # Validate the tracker payload before importing: a bad score/status
            # shouldn't leave a freshly-created show and its imported episode
            # catalog behind just to fail form validation afterwards. show_id
            # is a plain IntegerField (no FK check), so a placeholder id is
            # safe to validate against.
            precheck_form = _bind_show_form(request.data, None, _PlaceholderShow)
            if not precheck_form.is_valid():
                return Response(
                    {"detail": "Invalid tracker data.", "errors": precheck_form.errors},
                    status=HTTP.BAD_REQUEST,
                )
            try:
                show = podcast_import.import_show_from_itunes_id(itunes_id)
            except podcast_import.PodcastImportError as e:
                return Response({"detail": str(e)}, status=HTTP.BAD_REQUEST)

        tracker = PodcastShowTracker.objects.filter(
            user=request.user,
            show=show,
        ).first()
        form = _bind_show_form(request.data, tracker, show)
        if not form.is_valid():
            return Response(
                {"detail": "Invalid tracker data.", "errors": form.errors},
                status=HTTP.BAD_REQUEST,
            )
        tracker = form.save(commit=False)
        tracker.user = request.user
        tracker.show = show
        tracker.save()
        return Response(_serialize_show(show, tracker), status=HTTP.CREATED)


# /api/v1/podcasts/lookup/[itunes_id]/
class PodcastLookupView(drf_views.APIView):
    """Preview an iTunes search result before importing it.

    A read-only counterpart to the itunes_id branch of PodcastShowsView.post:
    it wraps pocketcasts.lookup_by_itunes_id (a cached iTunes API call) and,
    when the lookup has a feed, reads the RSS feed directly — the same feed
    `import_show_from_itunes_id` would import from — for the metadata
    fallbacks and the episode list. Nothing here creates a PodcastShow or a
    PodcastEpisode row; that still only happens once the caller adds it.
    `show_id` reports the show an import would reuse, or null.

    Episodes come back in the standard limit/offset envelope, because a feed
    can run past a thousand of them.
    """

    # Both feed reads land in the request/response cycle, and this endpoint
    # gets hit while paging through search results, so cache what the feed
    # gave us. A preview never needs to be fresher than the import that
    # follows it, and the iTunes half of the lookup is already cached for a
    # week in pocketcasts.lookup_by_itunes_id.
    _FEED_CACHE_SECONDS = 15 * 60

    def _read_feed(self, itunes_id, itunes_data, rss_feed_url):
        """Return (metadata, episodes) for a feed, caching the pair briefly."""
        cache_key = f"podcast_lookup_feed_{itunes_id}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        metadata = podcast_import.resolve_show_metadata(itunes_data, rss_feed_url)
        episodes = self._feed_episodes(rss_feed_url)
        cache.set(cache_key, (metadata, episodes), self._FEED_CACHE_SECONDS)
        return metadata, episodes

    def _feed_episodes(self, rss_feed_url):
        """Serialize a feed's episodes; an unreadable feed previews as none."""
        try:
            episodes = podcast_rss.fetch_episodes_from_rss(rss_feed_url)
        except Exception:
            logger.warning(
                "Failed to preview episodes from %s",
                safe_url(rss_feed_url),
            )
            return []

        return [
            {
                "title": episode.get("title", ""),
                "published": episode.get("published"),
                "duration": helpers.seconds_to_hm(episode.get("duration")),
                "duration_seconds": episode.get("duration"),
                "episode_number": episode.get("episode_number"),
                "season_number": episode.get("season_number"),
                "website_url": episode.get("website_url", ""),
            }
            for episode in episodes
        ]

    def get(self, request, itunes_id):
        """Return iTunes + RSS metadata for the given collection id."""
        limit, offset, err = parse_limit_offset(request)
        if err:
            return err

        try:
            itunes_data = pocketcasts.lookup_by_itunes_id(itunes_id)
        except services.ProviderAPIError as error:
            if error.status_code == HTTP.NOT_FOUND:
                return Response({"detail": "Podcast not found."}, status=HTTP.NOT_FOUND)
            # Names the provider and nothing else. str(error) is only
            # sanitised when the provider answered: with no response at all
            # ProviderAPIError builds "Could not reach X (<exception>)", so
            # returning it really would put exception text in a response body,
            # which is what CodeQL's py/stack-trace-exposure flags. The error
            # is already logged with its status and body shape, and there is
            # nothing here a caller can act on beyond the status code, so this
            # follows the provider-search handler in views.py and reports the
            # label alone.
            return Response(
                {"detail": f"{error.provider_label} lookup failed."},
                status=HTTP.INTERNAL_SERVER_ERROR,
            )

        rss_feed_url = itunes_data.get("feed_url", "")
        metadata, episodes = itunes_data, []
        if rss_feed_url:
            metadata, episodes = self._read_feed(itunes_id, itunes_data, rss_feed_url)

        existing_show = podcast_import.find_existing_show(itunes_id, rss_feed_url)

        return Response(
            {
                "itunes_id": itunes_id,
                "title": metadata.get("title", ""),
                "author": metadata.get("author", ""),
                "image": metadata.get("artwork_url", ""),
                "description": metadata.get("description", ""),
                "genres": metadata.get("genres", []),
                "language": metadata.get("language", ""),
                "rss_feed_url": rss_feed_url,
                "website_url": metadata.get("website_url", ""),
                "show_id": existing_show.id if existing_show else None,
                "episodes": paginate_data(request, episodes, limit, offset),
            },
            status=HTTP.OK,
        )


# /api/v1/podcasts/shows/[show_id]/
class PodcastShowDetailView(drf_views.APIView):
    """Show detail with the caller's tracker; PATCH/DELETE act on the tracker."""

    def _get_show(self, show_id):
        return PodcastShow.objects.filter(id=show_id).first()

    def get(self, request, show_id):
        """Return the show and the caller's tracker."""
        show = self._get_show(show_id)
        if show is None:
            return Response({"detail": "Show not found."}, status=HTTP.NOT_FOUND)
        tracker = PodcastShowTracker.objects.filter(
            user=request.user,
            show=show,
        ).first()
        return Response(_serialize_show(show, tracker), status=HTTP.OK)

    def patch(self, request, show_id):
        """Update the caller's tracker (creates one if missing)."""
        show = self._get_show(show_id)
        if show is None:
            return Response({"detail": "Show not found."}, status=HTTP.NOT_FOUND)
        tracker = PodcastShowTracker.objects.filter(
            user=request.user,
            show=show,
        ).first()
        form = _bind_show_form(request.data, tracker, show)
        if not form.is_valid():
            return Response(
                {"detail": "Invalid tracker data.", "errors": form.errors},
                status=HTTP.BAD_REQUEST,
            )
        tracker = form.save(commit=False)
        tracker.user = request.user
        tracker.show = show
        tracker.save()
        return Response(_serialize_show(show, tracker), status=HTTP.OK)

    def delete(self, request, show_id):
        """Remove the caller's tracker (mirrors podcast_show_delete)."""
        show = self._get_show(show_id)
        if show is None:
            return Response({"detail": "Show not found."}, status=HTTP.NOT_FOUND)
        tracker = PodcastShowTracker.objects.filter(
            user=request.user,
            show=show,
        ).first()
        if tracker is None:
            return Response(
                {"detail": "Show is not tracked."},
                status=HTTP.NOT_FOUND,
            )
        tracker.delete()
        return Response(status=HTTP.NO_CONTENT)


# /api/v1/podcasts/shows/[show_id]/episodes/
class PodcastShowEpisodesView(drf_views.APIView):
    """Paginated episode list with per-user play state.

    Delegates to the same view the web episode list uses
    (podcast_views.podcast_episodes_api, JSON format) but adapts its
    page/page_size response into the standard limit/offset envelope used
    by the rest of the API, so clients don't need a podcast-specific
    pagination contract.
    """

    def get(self, request, show_id):
        """Return catalog episodes with play state (limit/offset params)."""
        if not PodcastShow.objects.filter(id=show_id).exists():
            return Response({"detail": "Show not found."}, status=HTTP.NOT_FOUND)

        limit, offset, err = parse_limit_offset(request)
        if err:
            return err

        # podcast_episodes_api only understands page/page_size, and every
        # episode it returns gets enriched via Item.objects.get_or_create(),
        # so fetching from page 1 up to `offset` would do DB writes
        # proportional to the offset on every request. Instead, land on the
        # page_size-sized page containing `offset` and pull a second page
        # only if this window straddles a page boundary — bounding the work
        # to ~2*limit episodes regardless of how deep the offset is.
        page_size = max(limit, 1)
        start_page = offset // page_size + 1
        remainder = offset % page_size

        def _fetch_page(page):
            inner_request = request._request
            query = inner_request.GET.copy()
            query["page"] = str(page)
            query["page_size"] = str(page_size)
            query["format"] = "json"
            inner_request.GET = query
            inner_response = podcast_episodes_api(inner_request, show_id)
            return json.loads(inner_response.content)

        first_payload = _fetch_page(start_page)
        total_count = first_payload["pagination"]["total_count"]
        episodes = first_payload["episodes"]

        if (
            remainder + limit > len(episodes)
            and first_payload["pagination"]["has_more"]
        ):
            second_payload = _fetch_page(start_page + 1)
            episodes = episodes + second_payload["episodes"]

        results = episodes[remainder : remainder + limit]

        next_url = None
        prev_url = None
        end = offset + limit
        if end < total_count:
            next_url = make_page_url(request, limit, end)
        if offset > 0:
            prev_url = make_page_url(request, limit, max(0, offset - limit))

        return Response(
            {
                "pagination": {
                    "total": total_count,
                    "limit": limit,
                    "offset": offset,
                    "next": next_url,
                    "previous": prev_url,
                },
                "results": results,
            },
            status=HTTP.OK,
        )


# /api/v1/podcasts/shows/[show_id]/mark-all-played/
class PodcastMarkAllPlayedView(drf_views.APIView):
    """Mark every unplayed episode of a show as completed.

    Note: refreshes the episode catalog from the show's RSS feed first, so
    this request performs a network fetch and can take several seconds.
    """

    def post(self, request, show_id):
        """Mark all episodes played; returns the number marked."""
        show = PodcastShow.objects.filter(id=show_id).first()
        if show is None:
            return Response({"detail": "Show not found."}, status=HTTP.NOT_FOUND)
        created_count = fork_services_podcast.mark_all_episodes_played(
            request.user,
            show,
        )
        return Response({"marked_played": created_count}, status=HTTP.OK)


# /api/v1/podcasts/episodes/[episode_id]/notes/
class PodcastEpisodeNotesView(drf_views.APIView):
    """Edit private episode notes without recording a play."""

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def patch(self, request, episode_id):
        """Save notes on the caller's Podcast tracker for the episode."""
        episode = (
            PodcastEpisode.objects.select_related("show")
            .filter(id=episode_id)
            .first()
        )
        if episode is None:
            return Response({"detail": "Episode not found."}, status=HTTP.NOT_FOUND)
        if "notes" not in request.data:
            return Response(
                {"detail": "'notes' is required."},
                status=HTTP.BAD_REQUEST,
            )
        notes = request.data.get("notes")
        if notes is not None and not isinstance(notes, str):
            return Response(
                {"detail": "'notes' must be a string or null."},
                status=HTTP.BAD_REQUEST,
            )
        podcast = fork_services_podcast.set_episode_notes(
            request.user,
            episode.show,
            episode,
            notes or "",
        )
        return Response(
            {
                "episode_id": episode.id,
                "notes": podcast.notes if podcast is not None else "",
            },
            status=HTTP.OK,
        )


# /api/v1/podcasts/episodes/plays/
class PodcastEpisodePlayView(drf_views.APIView):
    """Record a completed podcast episode play."""

    def post(self, request):
        """Add a completed play.

        If end_date is omitted or blank, use the current server time. Report
        a repeat within five minutes as HTTP 200 with duplicate set to true.
        """
        show_id = request.data.get("show_id")
        if not show_id:
            return Response(
                {"detail": "'show_id' is required."},
                status=HTTP.BAD_REQUEST,
            )
        show = PodcastShow.objects.filter(id=show_id).first()
        if show is None:
            return Response({"detail": "Show not found."}, status=HTTP.NOT_FOUND)

        episode = None
        episode_id = request.data.get("episode_id")
        episode_uuid = request.data.get("episode_uuid")
        if episode_id:
            episode = PodcastEpisode.objects.filter(id=episode_id, show=show).first()
            if episode is None:
                return Response(
                    {"detail": "Episode not found on this show."},
                    status=HTTP.NOT_FOUND,
                )
            episode_uuid = episode.episode_uuid
        elif episode_uuid:
            episode = PodcastEpisode.objects.filter(
                show=show,
                episode_uuid=episode_uuid,
            ).first()
        if not episode_uuid:
            return Response(
                {"detail": "'episode_id' or 'episode_uuid' is required."},
                status=HTTP.BAD_REQUEST,
            )

        end_date = None
        raw_end_date = request.data.get("end_date")
        if raw_end_date not in (None, ""):
            try:
                end_date = try_parse_datetime_input(raw_end_date)
            except (TypeError, ValueError):
                return Response(
                    {"detail": "Invalid end_date format."},
                    status=HTTP.BAD_REQUEST,
                )

        podcast, duplicate = fork_services_podcast.record_podcast_play(
            request.user,
            show,
            episode=episode,
            episode_uuid=episode_uuid,
            end_date=end_date,
        )
        payload = serialize_data(podcast)
        payload["duplicate"] = duplicate
        return Response(
            payload,
            status=HTTP.OK if duplicate else HTTP.CREATED,
        )
