"""Tie the game YouTube tags on a user's videos to a Floppy game.

Matching is by normalized title and release year, read when asked, so a corrected
game or a new tag needs no stored link. Watch time is an estimate: a video's
progress is the furthest position reached, not seconds actually watched.
"""

import re
import unicodedata

from django.db.models import Q

from app.models import Item, MediaTypes, Video, VideoGameLink, VideoGameTag


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


def _seconds_watched(progress, length):
    """Furthest position, capped at the runtime. A rewatch can pass the runtime."""
    return min(progress, length) if length else progress


def _hours_label(seconds):
    hours, minutes = divmod(seconds // 60, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


def watched_for_game(user, game_item):
    """Estimate how long `user` watched videos about this game.

    A video counts when the user linked it to the game, or when YouTube's tag
    names it and the user has not linked it elsewhere or said it is not about a
    game. Takeout imports carry no position, so those videos add to the count
    but not to the time.

    @returns `{"videos", "seconds", "hours_label", "estimated", "items"}`, or
    None when nothing matches. `items` lists each video, newest first.
    """
    if game_item.media_type != MediaTypes.GAME.value:
        return None
    overrides = {
        link.video_item_id: link.game_item_id
        for link in VideoGameLink.objects.filter(user=user)
    }
    rows = (
        Video.objects.filter(user=user)
        .filter(
            Q(item__video_game_tag__status=VideoGameTag.Status.FOUND)
            | Q(item__video_game_links__user=user, item__video_game_links__game_item=game_item)
        )
        .select_related("item", "item__video_game_tag")
        .distinct()
    )
    items = []
    seconds = 0
    for video in rows:
        override = overrides.get(video.item_id, "none")
        if override != "none":
            matched = override == game_item.pk
            how = "linked"
        else:
            tag = getattr(video.item, "video_game_tag", None)
            matched = bool(
                tag
                and tag.status == VideoGameTag.Status.FOUND
                and tag_matches_game(tag.game_title, tag.release_year, game_item)
            )
            how = "tagged"
        if not matched:
            continue
        watched = _seconds_watched(video.progress, video.length_seconds)
        seconds += watched
        items.append(
            {
                "video": video,
                "item": video.item,
                "seconds": watched,
                "label": _hours_label(watched) if watched else "",
                "how": how,
                "when": video.end_date,
            }
        )
    if not items:
        return None
    items.sort(
        key=lambda row: (row["when"] is not None, row["when"] or row["video"].pk),
        reverse=True,
    )
    return {
        "videos": len(items),
        "seconds": seconds,
        "hours_label": _hours_label(seconds),
        "estimated": True,
        "items": items,
    }


def game_for_video(user, video_item):
    """Return what a video is about for `user`.

    @returns `{"game", "how", "tag"}`. `game` is the Floppy game Item or None.
    `how` is "linked" (user's choice), "none" (user said no game), "tagged"
    (matched from YouTube's tag), or "" (nothing known).
    """
    tag = VideoGameTag.objects.filter(
        item=video_item, status=VideoGameTag.Status.FOUND
    ).first()
    link = VideoGameLink.objects.filter(user=user, video_item=video_item).select_related(
        "game_item"
    ).first()
    if link:
        return {
            "game": link.game_item,
            "how": "linked" if link.game_item else "none",
            "tag": tag,
        }
    if tag:
        candidates = Item.objects.filter(
            media_type=MediaTypes.GAME.value, title__icontains=tag.game_title
        )[:20]
        for game in candidates:
            if tag_matches_game(tag.game_title, tag.release_year, game):
                return {"game": game, "how": "tagged", "tag": tag}
    return {"game": None, "how": "", "tag": tag}
