"""Tie the game YouTube tags on a user's videos to a Floppy game.

Matching is by normalized title and release year, read when asked, so a corrected
game or a new tag needs no stored link. Watch time is an estimate: a video's
progress is the furthest position reached, not seconds actually watched.
"""

import re
import unicodedata

from app.models import MediaTypes, Video, VideoGameTag


def normalize_title(title):
    """Fold case, accents and punctuation so "Zelda: TotK" style variants compare."""
    folded = unicodedata.normalize("NFKD", title or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", folded.casefold())


def _year_matches(item, tag_year):
    if not tag_year.isdigit() or not item.release_datetime:
        return True
    return item.release_datetime.year == int(tag_year)


def tag_matches_game(tag_title, tag_year, game_item):
    """Whether a YouTube game tag names this Floppy game."""
    wanted = normalize_title(game_item.title)
    return bool(wanted) and normalize_title(tag_title) == wanted and _year_matches(
        game_item, tag_year
    )


def watched_for_game(user, game_item):
    """Estimate how long `user` watched videos YouTube tags with this game.

    @returns `{"videos", "seconds", "hours_label", "estimated"}`, or None when nothing matches.
    """
    if game_item.media_type != MediaTypes.GAME.value:
        return None
    rows = (
        Video.objects.filter(
            user=user,
            item__video_game_tag__status=VideoGameTag.Status.FOUND,
        )
        .values_list(
            "progress",
            "length_seconds",
            "item__video_game_tag__game_title",
            "item__video_game_tag__release_year",
        )
    )
    videos = 0
    seconds = 0
    for progress, length, title, year in rows:
        if not tag_matches_game(title, year, game_item):
            continue
        videos += 1
        # Position can pass the runtime after a rewatch or a seek past the end.
        seconds += min(progress, length) if length else progress
    if not videos:
        return None
    hours, minutes = divmod(seconds // 60, 60)
    label = f"{hours}h {minutes}m" if hours else f"{minutes}m"
    return {
        "videos": videos,
        "seconds": seconds,
        "hours_label": label,
        "estimated": True,
    }
