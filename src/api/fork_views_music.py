# FORK: first-class music endpoints (artists, albums, songs, plays) that
# mirror the web music views. Trackers are per-user; Artist/Album/Track are
# global catalog rows. Scores use the raw 0-10 storage scale like the rest
# of this API. URL wiring lives in fork_urls.py.
import logging
from decimal import Decimal, InvalidOperation
from http import HTTPStatus as HTTP  # noqa: N814

from django.conf import settings
from rest_framework import views as drf_views
from rest_framework.response import Response

from app import fork_services_music, history_cache
from app.forms import AlbumTrackerForm, ArtistTrackerForm
from app.models import (
    Album,
    AlbumTracker,
    Artist,
    ArtistTracker,
    Music,
    Status,
    Track,
)
from app.score_views import (
    _collect_music_history_day_keys_for_album_ids,
    _collect_music_history_day_keys_for_artist,
)
from app.services.music import sync_artist_discography
from app.services.music_scrobble import dedupe_artist_albums
from app.tasks import bulk_music_plays_task

from .helpers import paginate_data, parse_limit_offset, try_parse_datetime_input
from .serializers import serialize_data

logger = logging.getLogger(__name__)

_TRACKER_FIELDS = ("score", "status", "start_date", "end_date", "notes")


def _serialize_tracker(tracker):
    """Return the per-user tracker fields as a plain payload."""
    if tracker is None:
        return None
    return {
        "status": tracker.status,
        "score": str(tracker.score) if tracker.score is not None else None,
        "start_date": tracker.start_date,
        "end_date": tracker.end_date,
        "notes": tracker.notes,
        "created_at": tracker.created_at,
        "updated_at": tracker.updated_at,
    }


def _serialize_artist(artist, tracker=None, *, include_albums=False):
    """Return an artist payload with optional tracker and album summaries."""
    payload = {
        "id": artist.id,
        "name": artist.name,
        "musicbrainz_id": artist.musicbrainz_id,
        "image": artist.image,
        "country": artist.country,
        "genres": artist.genres,
        "artist_type": artist.artist_type,
        "discography_synced_at": artist.discography_synced_at,
        "tracker": _serialize_tracker(tracker),
    }
    if include_albums:
        payload["albums"] = [_serialize_album(album) for album in artist.albums.all()]
    return payload


def _serialize_album(album, tracker=None):
    """Return an album payload with optional tracker."""
    return {
        "id": album.id,
        "title": album.title,
        "musicbrainz_release_id": album.musicbrainz_release_id,
        "musicbrainz_release_group_id": album.musicbrainz_release_group_id,
        "artist_id": album.artist_id,
        "artist_name": album.artist.name if album.artist else None,
        "release_date": album.release_date,
        "release_type": album.release_type,
        "image": album.image,
        "genres": album.genres,
        "tracker": _serialize_tracker(tracker),
    }


def _bind_tracker_form(form_class, data, instance, id_field, id_value):
    """Bind a tracker form with partial-update semantics.

    Missing fields fall back to the current instance values so PATCH can
    send only the fields being changed. Forms are bound without `user` so
    scores stay on the raw 0-10 storage scale.
    """
    merged = {id_field: id_value}
    for field in _TRACKER_FIELDS:
        current = getattr(instance, field, None) if instance else None
        merged[field] = current if current is not None else ""
    for field in _TRACKER_FIELDS:
        if field in data:
            merged[field] = data[field] if data[field] is not None else ""
    if not merged.get("status"):
        merged["status"] = Status.IN_PROGRESS.value  # model default
    return form_class(merged, instance=instance)


def _invalidate_music_score_days(user, day_keys, reason):
    """Invalidate music history days after a score change (web parity)."""
    if day_keys:
        history_cache.invalidate_history_days(
            user.id,
            day_keys=day_keys,
            logging_styles=("sessions", "repeats"),
            reason=reason,
        )


# /api/v1/music/artists/
class MusicArtistsView(drf_views.APIView):
    """List tracked artists or start tracking one."""

    def get(self, request):
        """Return the caller's artist trackers."""
        limit, offset, err = parse_limit_offset(request)
        if err:
            return err
        trackers = ArtistTracker.objects.filter(user=request.user).select_related(
            "artist",
        )
        results = [_serialize_artist(tracker.artist, tracker) for tracker in trackers]
        return Response(
            paginate_data(request, results, limit, offset),
            status=HTTP.OK,
        )

    def post(self, request):
        """Track an artist by artist_id or musicbrainz_id (mirrors artist_save)."""
        artist = None
        artist_id = request.data.get("artist_id")
        musicbrainz_id = request.data.get("musicbrainz_id")
        if artist_id:
            artist = Artist.objects.filter(id=artist_id).first()
        elif musicbrainz_id:
            try:
                artist = fork_services_music.get_or_create_artist_from_musicbrainz(
                    musicbrainz_id,
                )
            except Exception as e:
                return Response(
                    {"detail": "Could not fetch artist.", "errors": str(e)},
                    status=HTTP.BAD_GATEWAY,
                )
        else:
            return Response(
                {"detail": "'artist_id' or 'musicbrainz_id' is required."},
                status=HTTP.BAD_REQUEST,
            )
        if artist is None:
            return Response({"detail": "Artist not found."}, status=HTTP.NOT_FOUND)

        tracker = ArtistTracker.objects.filter(
            user=request.user,
            artist=artist,
        ).first()
        form = _bind_tracker_form(
            ArtistTrackerForm,
            request.data,
            tracker,
            "artist_id",
            artist.id,
        )
        if not form.is_valid():
            return Response(
                {"detail": "Invalid tracker data.", "errors": form.errors},
                status=HTTP.BAD_REQUEST,
            )
        tracker = form.save(commit=False)
        tracker.user = request.user
        tracker.artist = artist
        tracker.save()
        return Response(_serialize_artist(artist, tracker), status=HTTP.CREATED)


# /api/v1/music/artists/[artist_id]/
class MusicArtistDetailView(drf_views.APIView):
    """Artist detail with the caller's tracker; PATCH/DELETE act on the tracker."""

    def _get_artist(self, artist_id):
        return Artist.objects.filter(id=artist_id).first()

    def get(self, request, artist_id):
        """Return the artist, tracker, and album summaries."""
        artist = self._get_artist(artist_id)
        if artist is None:
            return Response({"detail": "Artist not found."}, status=HTTP.NOT_FOUND)
        tracker = ArtistTracker.objects.filter(
            user=request.user,
            artist=artist,
        ).first()
        return Response(
            _serialize_artist(artist, tracker, include_albums=True),
            status=HTTP.OK,
        )

    def patch(self, request, artist_id):
        """Update the caller's tracker (creates one if missing)."""
        artist = self._get_artist(artist_id)
        if artist is None:
            return Response({"detail": "Artist not found."}, status=HTTP.NOT_FOUND)
        tracker = ArtistTracker.objects.filter(
            user=request.user,
            artist=artist,
        ).first()
        old_score = tracker.score if tracker else None
        form = _bind_tracker_form(
            ArtistTrackerForm,
            request.data,
            tracker,
            "artist_id",
            artist.id,
        )
        if not form.is_valid():
            return Response(
                {"detail": "Invalid tracker data.", "errors": form.errors},
                status=HTTP.BAD_REQUEST,
            )
        tracker = form.save(commit=False)
        tracker.user = request.user
        tracker.artist = artist
        tracker.save()
        if tracker.score != old_score:
            _invalidate_music_score_days(
                request.user,
                _collect_music_history_day_keys_for_artist(request.user, artist),
                "artist_score_change",
            )
        return Response(_serialize_artist(artist, tracker), status=HTTP.OK)

    def delete(self, request, artist_id):
        """Remove the caller's tracker (mirrors artist_delete)."""
        artist = self._get_artist(artist_id)
        if artist is None:
            return Response({"detail": "Artist not found."}, status=HTTP.NOT_FOUND)
        tracker = ArtistTracker.objects.filter(
            user=request.user,
            artist=artist,
        ).first()
        if tracker is None:
            return Response(
                {"detail": "Artist is not tracked."},
                status=HTTP.NOT_FOUND,
            )
        tracker.delete()
        return Response(status=HTTP.NO_CONTENT)


# /api/v1/music/artists/[artist_id]/sync-discography/
class MusicArtistSyncView(drf_views.APIView):
    """Force a discography sync for an artist (mirrors the web sync view)."""

    def post(self, _request, artist_id):
        """Sync albums from MusicBrainz; returns the synced album count."""
        artist = Artist.objects.filter(id=artist_id).first()
        if artist is None:
            return Response({"detail": "Artist not found."}, status=HTTP.NOT_FOUND)
        try:
            count = sync_artist_discography(artist, force=True)
        except Exception as e:
            return Response(
                {"detail": "Discography sync failed.", "errors": str(e)},
                status=HTTP.BAD_GATEWAY,
            )
        if count:
            dedupe_artist_albums(artist)
        return Response({"synced_albums": count or 0}, status=HTTP.OK)


# /api/v1/music/artists/[artist_id]/plays/
class MusicArtistPlaysView(drf_views.APIView):
    """Delete all of the caller's plays for an artist."""

    def delete(self, request, artist_id):
        """Remove every Music play for the artist's albums."""
        artist = Artist.objects.filter(id=artist_id).first()
        if artist is None:
            return Response({"detail": "Artist not found."}, status=HTTP.NOT_FOUND)
        entries = Music.objects.filter(user=request.user, album__artist=artist)
        count = entries.count()
        entries.delete()
        return Response({"deleted_plays": count}, status=HTTP.OK)


# /api/v1/music/albums/
class MusicAlbumsView(drf_views.APIView):
    """List tracked albums or start tracking one."""

    def get(self, request):
        """Return the caller's album trackers."""
        limit, offset, err = parse_limit_offset(request)
        if err:
            return err
        trackers = AlbumTracker.objects.filter(user=request.user).select_related(
            "album",
            "album__artist",
        )
        results = [_serialize_album(tracker.album, tracker) for tracker in trackers]
        return Response(
            paginate_data(request, results, limit, offset),
            status=HTTP.OK,
        )

    def post(self, request):
        """Track an album by album_id (mirrors album_save)."""
        album_id = request.data.get("album_id")
        if not album_id:
            return Response(
                {"detail": "'album_id' is required."},
                status=HTTP.BAD_REQUEST,
            )
        album = Album.objects.filter(id=album_id).select_related("artist").first()
        if album is None:
            return Response({"detail": "Album not found."}, status=HTTP.NOT_FOUND)

        tracker = AlbumTracker.objects.filter(user=request.user, album=album).first()
        form = _bind_tracker_form(
            AlbumTrackerForm,
            request.data,
            tracker,
            "album_id",
            album.id,
        )
        if not form.is_valid():
            return Response(
                {"detail": "Invalid tracker data.", "errors": form.errors},
                status=HTTP.BAD_REQUEST,
            )
        tracker = form.save(commit=False)
        tracker.user = request.user
        tracker.album = album
        tracker.save()
        return Response(_serialize_album(album, tracker), status=HTTP.CREATED)


# /api/v1/music/albums/[album_id]/
class MusicAlbumDetailView(drf_views.APIView):
    """Album detail with the caller's tracker; PATCH/DELETE act on the tracker."""

    def _get_album(self, album_id):
        return Album.objects.filter(id=album_id).select_related("artist").first()

    def get(self, request, album_id):
        """Return the album and the caller's tracker."""
        album = self._get_album(album_id)
        if album is None:
            return Response({"detail": "Album not found."}, status=HTTP.NOT_FOUND)
        tracker = AlbumTracker.objects.filter(user=request.user, album=album).first()
        return Response(_serialize_album(album, tracker), status=HTTP.OK)

    def patch(self, request, album_id):
        """Update the caller's tracker (creates one if missing)."""
        album = self._get_album(album_id)
        if album is None:
            return Response({"detail": "Album not found."}, status=HTTP.NOT_FOUND)
        tracker = AlbumTracker.objects.filter(user=request.user, album=album).first()
        old_score = tracker.score if tracker else None
        form = _bind_tracker_form(
            AlbumTrackerForm,
            request.data,
            tracker,
            "album_id",
            album.id,
        )
        if not form.is_valid():
            return Response(
                {"detail": "Invalid tracker data.", "errors": form.errors},
                status=HTTP.BAD_REQUEST,
            )
        tracker = form.save(commit=False)
        tracker.user = request.user
        tracker.album = album
        tracker.save()
        if tracker.score != old_score:
            _invalidate_music_score_days(
                request.user,
                _collect_music_history_day_keys_for_album_ids(
                    request.user,
                    [album.id],
                ),
                "album_score_change",
            )
        return Response(_serialize_album(album, tracker), status=HTTP.OK)

    def delete(self, request, album_id):
        """Remove the caller's tracker (mirrors album_delete)."""
        album = self._get_album(album_id)
        if album is None:
            return Response({"detail": "Album not found."}, status=HTTP.NOT_FOUND)
        tracker = AlbumTracker.objects.filter(user=request.user, album=album).first()
        if tracker is None:
            return Response(
                {"detail": "Album is not tracked."},
                status=HTTP.NOT_FOUND,
            )
        tracker.delete()
        return Response(status=HTTP.NO_CONTENT)


# /api/v1/music/albums/[album_id]/tracks/
class MusicAlbumTracksView(drf_views.APIView):
    """Tracklist for an album with the caller's play state."""

    def get(self, request, album_id):
        """Return catalog tracks plus the user's Music entry per track."""
        album = Album.objects.filter(id=album_id).first()
        if album is None:
            return Response({"detail": "Album not found."}, status=HTTP.NOT_FOUND)

        music_by_track = {
            music.track_id: music
            for music in Music.objects.filter(
                user=request.user,
                album=album,
                track__isnull=False,
            )
        }
        results = []
        for track in Track.objects.filter(album=album):
            music = music_by_track.get(track.id)
            results.append(
                {
                    "id": track.id,
                    "title": track.title,
                    "track_number": track.track_number,
                    "disc_number": track.disc_number,
                    "duration_ms": track.duration_ms,
                    "musicbrainz_recording_id": track.musicbrainz_recording_id,
                    "music_id": music.id if music else None,
                    "last_played": music.end_date if music else None,
                    "play_count": music.history.count() if music else 0,
                    "score": str(music.score)
                    if music and music.score is not None
                    else None,
                },
            )
        return Response({"results": results}, status=HTTP.OK)


# /api/v1/music/albums/[album_id]/plays/
class MusicAlbumPlaysView(drf_views.APIView):
    """Delete all of the caller's plays for an album."""

    def delete(self, request, album_id):
        """Remove every Music play for the album."""
        album = Album.objects.filter(id=album_id).first()
        if album is None:
            return Response({"detail": "Album not found."}, status=HTTP.NOT_FOUND)
        entries = Music.objects.filter(user=request.user, album=album)
        count = entries.count()
        entries.delete()
        return Response({"deleted_plays": count}, status=HTTP.OK)


# /api/v1/music/songs/plays/
class MusicSongPlayView(drf_views.APIView):
    """Record a listen for a song (mirrors web song_save)."""

    def post(self, request):
        """Add a play for a track on an album."""
        album_id = request.data.get("album_id")
        if not album_id:
            return Response(
                {"detail": "'album_id' is required."},
                status=HTTP.BAD_REQUEST,
            )
        album = Album.objects.filter(id=album_id).select_related("artist").first()
        if album is None:
            return Response({"detail": "Album not found."}, status=HTTP.NOT_FOUND)

        track = None
        track_id = request.data.get("track_id")
        if track_id:
            track = Track.objects.filter(id=track_id, album=album).first()
            if track is None:
                return Response(
                    {"detail": "Track not found on this album."},
                    status=HTTP.NOT_FOUND,
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

        music = fork_services_music.record_song_play(
            request.user,
            album,
            track=track,
            recording_id=request.data.get("recording_id"),
            end_date=end_date,
        )
        return Response(serialize_data(music), status=HTTP.CREATED)


# /api/v1/music/tracks/[music_id]/score/
class MusicTrackScoreView(drf_views.APIView):
    """Set or clear the score on a Music play row."""

    def patch(self, request, music_id):
        """Update the score (raw 0-10 scale; null clears)."""
        music = Music.objects.filter(id=music_id, user=request.user).first()
        if music is None:
            return Response({"detail": "Music entry not found."}, status=HTTP.NOT_FOUND)

        if "score" not in request.data:
            return Response(
                {"detail": "'score' is required (number or null)."},
                status=HTTP.BAD_REQUEST,
            )
        raw_score = request.data.get("score")
        score = None
        if raw_score is not None:
            try:
                score = Decimal(str(raw_score))
            except (InvalidOperation, TypeError, ValueError):
                return Response({"detail": "Invalid score."}, status=HTTP.BAD_REQUEST)
            if not (Decimal(0) <= score <= Decimal(10)):
                return Response(
                    {"detail": "Score must be between 0 and 10."},
                    status=HTTP.BAD_REQUEST,
                )
        music.score = score
        music.save()
        return Response(
            {"score": str(score) if score is not None else None},
            status=HTTP.OK,
        )


# /api/v1/music/bulk-plays/
class MusicBulkPlaysView(drf_views.APIView):
    """Dispatch a bulk music play range as a background task.

    Mirrors the web music_bulk_save. Disc/track positions map to the task's
    season/episode numbering. Returns 202 with a pollable task_id.
    """

    def post(self, request):
        """Queue bulk plays for an artist or album context."""
        context_kind = (request.data.get("context_kind") or "").strip()
        if context_kind not in ("artist", "album"):
            return Response(
                {"detail": "context_kind must be 'artist' or 'album'."},
                status=HTTP.BAD_REQUEST,
            )
        try:
            context_id = int(request.data.get("context_id"))
        except (TypeError, ValueError):
            return Response(
                {"detail": "Invalid context_id."},
                status=HTTP.BAD_REQUEST,
            )

        start_date = (str(request.data.get("start_date") or "")).strip()
        end_date = (str(request.data.get("end_date") or "")).strip()
        if not start_date or not end_date:
            return Response(
                {"detail": "start_date and end_date are required."},
                status=HTTP.BAD_REQUEST,
            )

        try:
            first_disc = int(request.data["first_disc_number"])
            first_track = int(request.data["first_track_number"])
            last_disc = int(request.data["last_disc_number"])
            last_track = int(request.data["last_track_number"])
        except (KeyError, TypeError, ValueError):
            return Response(
                {"detail": "Invalid track range."},
                status=HTTP.BAD_REQUEST,
            )

        write_mode = request.data.get("write_mode", "add")
        distribution_mode = request.data.get("distribution_mode", "even")
        if write_mode not in ("add", "replace"):
            return Response(
                {"detail": "write_mode must be 'add' or 'replace'."},
                status=HTTP.BAD_REQUEST,
            )
        if distribution_mode not in ("even", "air_date"):
            return Response(
                {"detail": "distribution_mode must be 'even' or 'air_date'."},
                status=HTTP.BAD_REQUEST,
            )

        task = bulk_music_plays_task.apply_async(
            kwargs={
                "user_id": request.user.id,
                "context_kind": context_kind,
                "context_id": context_id,
                "first_season_number": first_disc,
                "first_episode_number": first_track,
                "last_season_number": last_disc,
                "last_episode_number": last_track,
                "write_mode": write_mode,
                "distribution_mode": distribution_mode,
                "start_date_str": start_date,
                "end_date_str": end_date,
            },
            priority=settings.CELERY_TASK_PRIORITY_INTERACTIVE,
        )
        return Response({"task_id": task.id}, status=HTTP.ACCEPTED)
