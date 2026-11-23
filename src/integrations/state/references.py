"""How a destination that identifies titles by TMDB names a Floppy item.

Two destinations (WeTrakr, SIMKL) take plays by TMDB id, so the rule for what
counts as a safely identified item, and the string the outbox stores for it, is
written once. Only native TMDB identities qualify: a guess from a title or year
would write to the wrong item, which cannot be undone.

The reference is ``kind:id`` for a movie or show and ``episode:id:season:episode``
for an episode, where ``id`` is the show's TMDB id.
"""

from app.models import MediaTypes, Sources


def tmdb_reference(item):
    """Return the reference for a native TMDB movie, show or episode, or None."""
    if item.source != Sources.TMDB.value or getattr(item, "episode_order_id", None):
        return None
    if not str(item.media_id).isdigit():
        return None
    if item.media_type == MediaTypes.MOVIE.value:
        return f"movie:{item.media_id}"
    if item.media_type == MediaTypes.TV.value:
        return f"show:{item.media_id}"
    if (
        item.media_type == MediaTypes.EPISODE.value
        and item.season_number is not None
        and item.season_number >= 0
        and item.episode_number is not None
        and item.episode_number > 0
    ):
        return f"episode:{item.media_id}:{item.season_number}:{item.episode_number}"
    return None


def parse_reference(reference):
    """Split a reference into ``(kind, tmdb, season, episode)``."""
    kind, tmdb, *rest = reference.split(":")
    season, episode = (int(rest[0]), int(rest[1])) if rest else (None, None)
    return kind, int(tmdb), season, episode
