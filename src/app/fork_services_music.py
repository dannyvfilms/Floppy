# FORK: shared music domain logic used by the web music views and the REST
# API — song play recording (extracted from music_album_views.song_save) and
# MusicBrainz artist creation (extracted from music_views.create_artist_from_search).
import logging

from django.conf import settings
from django.utils import timezone

from app.models import Artist, Item, MediaTypes, Music, Sources, Status

logger = logging.getLogger(__name__)


def record_song_play(user, album, track=None, recording_id=None, end_date=None):
    """Record a listen for a song on an album; returns the Music row.

    Mirrors the web song_save core: one Music row exists per
    (user, album, track); a new listen updates end_date (each save adds a
    history record), and the first listen creates the row Completed. The
    backing Item is keyed on the MusicBrainz recording id when available,
    else a track_{id} synthetic id.

    Uses the current server time when the caller supplies no completion date.
    Listen counts read history records that have an end_date, so a completed
    listen stored without one is invisible, and a later dateless listen used to
    clear a timestamp an earlier listen had already recorded.
    """
    completed_at = end_date if end_date is not None else timezone.now()
    existing_music = Music.objects.filter(
        user=user,
        album=album,
        track=track,
    ).first()

    runtime_minutes = None
    if track and track.duration_ms:
        runtime_minutes = track.duration_ms // 60000  # Convert ms to minutes

    if existing_music:
        existing_music.end_date = completed_at
        existing_music.status = Status.COMPLETED.value
        existing_music.save()

        if (
            runtime_minutes
            and existing_music.item
            and not existing_music.item.runtime_minutes
        ):
            existing_music.item.runtime_minutes = runtime_minutes
            existing_music.item.save(update_fields=["runtime_minutes"])
        return existing_music

    item_defaults = {
        "title": track.title if track else "Unknown Track",
        "image": album.image or settings.IMG_NONE,
    }
    if runtime_minutes:
        item_defaults["runtime_minutes"] = runtime_minutes

    media_id = recording_id or f"track_{track.id if track else ''}"
    item, created = Item.objects.get_or_create(
        media_id=media_id,
        source=Sources.MUSICBRAINZ.value,
        media_type=MediaTypes.MUSIC.value,
        defaults=item_defaults,
    )
    if not created and not item.runtime_minutes and runtime_minutes:
        item.runtime_minutes = runtime_minutes
        item.save(update_fields=["runtime_minutes"])

    return Music.objects.create(
        item=item,
        user=user,
        artist=album.artist,
        album=album,
        track=track,
        status=Status.COMPLETED.value,
        end_date=completed_at,
    )


def music_entry_for_track(user, track):
    """Return this user's Music row for a catalog track, or None."""
    by_track_id = {}
    entries = Music.objects.filter(
        user=user,
        album=track.album,
    ).select_related("item", "track")
    for music in entries:
        if music.track_id:
            by_track_id[music.track_id] = music
        if music.item and music.item.media_id:
            by_track_id[f"recording_{music.item.media_id}"] = music

    music = by_track_id.get(track.id)
    if not music and track.musicbrainz_recording_id:
        music = by_track_id.get(f"recording_{track.musicbrainz_recording_id}")
    return music


def set_track_notes(user, track, notes):
    """Save private track notes without recording a listen.

    Mirrors music_views.music_track_notes: a note edit never creates a
    history record, and a blank note leaves an untracked track untouched.
    """
    notes = notes or ""
    music = music_entry_for_track(user, track)
    if music is None and not notes:
        return None
    if music is None:
        music = Music(
            user=user,
            album=track.album,
            artist=track.album.artist,
            track=track,
            status=Status.PLANNING.value,
        )
        music.item, _ = Item.objects.get_or_create(
            source=Sources.MUSICBRAINZ.value,
            media_type=MediaTypes.MUSIC.value,
            media_id=track.musicbrainz_recording_id or f"track_{track.id}",
            defaults={
                "title": track.title,
                "image": track.album.image or settings.IMG_NONE,
            },
        )
    music.notes = notes
    music.save_without_historical_record(
        update_fields=["notes"] if music.pk else None,
    )
    return music


def get_or_create_artist_from_musicbrainz(musicbrainz_artist_id):
    """Return the Artist for a MusicBrainz id, creating and syncing if new.

    Mirrors the web create_artist_from_search: a newly created artist gets
    an immediate discography sync.
    """
    from app.providers import musicbrainz
    from app.services.music import sync_artist_discography

    artist = Artist.objects.filter(musicbrainz_id=musicbrainz_artist_id).first()
    if artist:
        return artist

    artist_data = musicbrainz.get_artist(musicbrainz_artist_id)
    artist = Artist.objects.create(
        name=artist_data.get("name", "Unknown Artist"),
        sort_name=artist_data.get("sort_name", ""),
        musicbrainz_id=musicbrainz_artist_id,
        country=artist_data.get("country", "") or "",
        genres=[g.get("name") for g in artist_data.get("genres", []) if g.get("name")]
        if artist_data.get("genres")
        else [],
    )
    logger.info("Created artist %s from MusicBrainz", artist.name)
    sync_artist_discography(artist)
    return artist
