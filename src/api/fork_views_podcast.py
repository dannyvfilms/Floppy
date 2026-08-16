# FORK: first-class podcast endpoints (shows, episodes, plays) mirroring
# the web podcast views. URL wiring lives in fork_urls.py.
import logging
from http import HTTPStatus as HTTP  # noqa: N814

from rest_framework import views as drf_views
from rest_framework.response import Response

from app import fork_services_podcast
from app.forms import PodcastShowTrackerForm
from app.models import PodcastEpisode, PodcastShow, PodcastShowTracker, Status
from app.podcast_views import podcast_episodes_api

from .helpers import paginate_data, parse_limit_offset, try_parse_datetime_input
from .serializers import serialize_data

logger = logging.getLogger(__name__)

_TRACKER_FIELDS = ("score", "status", "start_date", "end_date", "notes")


def _serialize_show(show, tracker=None):
    """Return a show payload with the caller's tracker."""
    tracker_payload = None
    if tracker is not None:
        tracker_payload = {
            "status": tracker.status,
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
        "rss_feed_url": show.rss_feed_url,
        "tracker": tracker_payload,
    }


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
        """Track a show by show_id (mirrors podcast_show_save)."""
        show_id = request.data.get("show_id")
        if not show_id:
            return Response(
                {"detail": "'show_id' is required."},
                status=HTTP.BAD_REQUEST,
            )
        show = PodcastShow.objects.filter(id=show_id).first()
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
        return Response(_serialize_show(show, tracker), status=HTTP.CREATED)


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
    (podcast_views.podcast_episodes_api, JSON format), so the payload shape
    is identical between surfaces.
    """

    def get(self, request, show_id):
        """Return catalog episodes with play state (page/page_size params)."""
        if not PodcastShow.objects.filter(id=show_id).exists():
            return Response({"detail": "Show not found."}, status=HTTP.NOT_FOUND)
        return podcast_episodes_api(request._request, show_id)


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
