"""Tie the game YouTube tags on a user's videos to a Floppy game.

Matching is by normalized title and release year, read when asked, so a corrected
game or a new tag needs no stored link. Watch time is an estimate: a video's
progress is the furthest position reached, not seconds actually watched.
"""

import re
import unicodedata

from django.db.models import Q

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
    """Estimate how long `user` watched videos about this game.

    A video counts when the user linked it to this game, or when YouTube's tag
    matches it and the user has not unlinked or relinked it elsewhere.

    @returns `{"videos", "seconds", "hours_label", "estimated"}`, or None when nothing matches.
    """
    if game_item.media_type != MediaTypes.GAME.value:
        return None
    manual = Video.objects.filter(user=user, game_link__game_item=game_item)
    tagged = Video.objects.filter(
        user=user,
        game_link__isnull=True,
        item__video_game_tag__status=VideoGameTag.Status.FOUND,
    ).filter(~Q(pk__in=manual.values("pk")))
    rows = [(v.progress, v.length_seconds) for v in manual]
    rows += [
        (progress, length)
        for progress, length, title, year in tagged.values_list(
            "progress",
            "length_seconds",
            "item__video_game_tag__game_title",
            "item__video_game_tag__release_year",
        )
        if tag_matches_game(title, year, game_item)
    ]
    if not rows:
        return None
    videos = len(rows)
    # Position can pass the runtime after a rewatch or a seek past the end.
    seconds = sum(min(p, n) if n else p for p, n in rows)
    hours, minutes = divmod(seconds // 60, 60)
    label = f"{hours}h {minutes}m" if hours else f"{minutes}m"
    return {
        "videos": videos,
        "seconds": seconds,
        "hours_label": label,
        "estimated": True,
    }
