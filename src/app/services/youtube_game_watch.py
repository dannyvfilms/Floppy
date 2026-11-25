"""Tie the game YouTube tags on a user's videos to a Floppy game.

Matching is by normalized title and release year, read when asked, so a corrected
game or a new tag needs no stored link. Watch time is an estimate: a video's
progress is the furthest position reached, not seconds actually watched.
"""

import re
import unicodedata

from django.db.models import Q

from app.helpers import minutes_to_hm
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

    @returns `{"videos", "seconds", "hours_label", "channels", "estimated"}`, or None when nothing matches.
    """
    if game_item.media_type != MediaTypes.GAME.value:
        return None
    manual = Video.objects.filter(user=user, game_link__game_item=game_item)
    rows = list(manual.values_list("progress", "length_seconds", "channel"))
    # Start from the (few) found tags, not the user's whole video table: walking
    # every video row to reach its tag is one random read per row on a cold disk.
    # The tag titles are matched here, then only the matching items' videos load.
    tagged_items = [
        item_id
        for item_id, title, year in VideoGameTag.objects.filter(
            status=VideoGameTag.Status.FOUND,
        ).values_list("item_id", "game_title", "release_year")
        if tag_matches_game(title, year, game_item)
    ]
    if tagged_items:
        rows += list(
            Video.objects.filter(
                user=user,
                item_id__in=tagged_items,
                game_link__isnull=True,
            )
            .filter(~Q(pk__in=manual.values("pk")))
            .values_list("progress", "length_seconds", "channel"),
        )
    if not rows:
        return None
    videos = len(rows)
    # Position can pass the runtime after a rewatch or a seek past the end.
    by_channel = {}
    for progress, length, channel in rows:
        watched = min(progress, length) if length else progress
        name = (channel or "").strip()
        by_channel[name] = by_channel.get(name, 0) + watched
    seconds = sum(by_channel.values())
    label = minutes_to_hm(seconds // 60)
    channels = [
        {"name": name, "seconds": watched, "percent": round(watched * 100 / seconds) if seconds else 0}
        for name, watched in sorted(by_channel.items(), key=lambda entry: (-entry[1], entry[0]))
        if name
    ]
    return {
        "videos": videos,
        "seconds": seconds,
        "hours_label": label,
        "channels": channels,
        "estimated": True,
    }
