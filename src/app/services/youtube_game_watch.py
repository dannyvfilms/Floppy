"""Tie the game YouTube tags on a user's videos to a Floppy game.

Matching uses known provider identities or normalized title and release year.
Watch time uses the recorded position or the published runtime for a completed
video with no recorded position.
"""

import re
import unicodedata
from hashlib import sha256
from uuid import uuid4

from django.core.cache import cache
from django.db import transaction

from app.helpers import minutes_to_hm
from app.models import MediaTypes, Sources, Status, Video, VideoGameTag

SECONDS_PER_MINUTE = 60
SUMMARY_TTL = 300
GENERATION_TTL = SUMMARY_TTL * 2
TAG_GENERATION_KEY = "youtube-game-watch:tags"

# YouTube dates the original PC release to 2009; IGDB dates Java Edition to
# the 2011 full release. IGDB lists Bedrock as "Minecraft", and "Dream it,
# Build it!" is Mojang's mobile Bedrock storefront title.
YOUTUBE_GAME_IDENTITIES = {
    "UCQvWX73GQygcwXOTSf_VDVg": (Sources.IGDB.value, "121"),  # Minecraft (2009)
    "UCQLJP2NLGXxEosSEW5vaohQ": (Sources.IGDB.value, "135400"),  # Dream it, Build it!
    "UCqLDGOjU4oxhd9M5hFPjwfw": (Sources.IGDB.value, "135400"),  # Bedrock Edition
}


def normalize_title(title):
    """Fold case, accents and punctuation so "Zelda: TotK" style variants compare."""
    folded = unicodedata.normalize("NFKD", title or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", folded.casefold())


def _year_matches(item, tag_year):
    if not tag_year.isdigit() or not item.release_datetime:
        return True
    return item.release_datetime.year == int(tag_year)


def tag_matches_game(tag_title, tag_year, game_item, *, youtube_game_id=""):
    """Whether a YouTube game tag names this Floppy game."""
    identity = YOUTUBE_GAME_IDENTITIES.get(youtube_game_id)
    if identity is not None:
        return identity == (game_item.source, game_item.media_id)
    wanted = normalize_title(game_item.title)
    return bool(wanted) and normalize_title(tag_title) == wanted and _year_matches(
        game_item, tag_year
    )


def _viewer_generation_key(user_id):
    return f"youtube-game-watch:viewer:{user_id}"


def invalidate_watch_summaries(user_id=None, *, using=None):
    """After commit, invalidate the viewer's summaries or those using shared tags."""
    key = TAG_GENERATION_KEY if user_id is None else _viewer_generation_key(user_id)
    transaction.on_commit(
        lambda: cache.set(key, uuid4().hex, GENERATION_TTL), using=using, robust=True,
    )


def cached_watched_for_game(user, game_item):
    """Cache the total and every channel together, including an empty result."""
    keys = (_viewer_generation_key(user.pk), TAG_GENERATION_KEY)
    generations = cache.get_many(keys)
    viewer_generation, tag_generation = [
        generations.get(key) or cache.get_or_set(key, uuid4().hex, GENERATION_TTL)
        for key in keys
    ]
    identity = sha256(f"{game_item.title}\n{game_item.release_datetime}".encode()).hexdigest()
    key = f"youtube-game-watch:v1:{user.pk}:{game_item.pk}:{identity}:{viewer_generation}:{tag_generation}"
    # The wrapper lets a cached None distinguish an empty result from a miss.
    return cache.get_or_set(
        key, lambda: {"watch": watched_for_game(user, game_item)}, SUMMARY_TTL,
    )["watch"]


def watched_for_game(user, game_item):
    """Estimate how long `user` watched videos about this game.

    A video counts when the user linked it to this game, or when YouTube's tag
    matches it and the user has not unlinked or relinked it elsewhere.

    Returns the duration and the count of videos without usable timing data,
    or None when nothing matches.
    """
    if game_item.media_type != MediaTypes.GAME.value:
        return None
    manual = Video.objects.filter(user=user, game_link__game_item=game_item)
    fields = ("progress", "length_seconds", "channel", "status", "item__video_game_tag__runtime_seconds")
    rows = list(manual.values_list(*fields))
    # Start from the (few) found tags, not the user's whole video table: walking
    # every video row to reach its tag is one random read per row on a cold disk.
    # The tag titles are matched here, then only the matching items' videos load.
    tagged_items = [
        item_id
        for item_id, title, year, game_id in VideoGameTag.objects.filter(
            status=VideoGameTag.Status.FOUND,
        ).values_list("item_id", "game_title", "release_year", "game_id")
        if tag_matches_game(title, year, game_item, youtube_game_id=game_id)
    ]
    if tagged_items:
        rows += list(
            Video.objects.filter(
                user=user,
                item_id__in=tagged_items,
                game_link__isnull=True,
            ).values_list(*fields),
        )
    if not rows:
        return None
    # Position can pass the runtime after a rewatch or a seek past the end.
    by_channel = {}
    seconds = 0
    videos_without_time = 0
    estimated = False
    for progress, client_length, channel, status, published_length in rows:
        length = client_length or published_length or 0
        watched = min(progress, length) if length else progress
        if watched:
            estimated = True
        elif status == Status.COMPLETED.value:
            watched = length
        name = (channel or "").strip()
        by_channel[name] = by_channel.get(name, 0) + watched
        seconds += watched
        videos_without_time += int(watched == 0)
    channels = [
        {
            "name": name,
            "seconds": watched,
            "percent": round(watched * 100 / seconds) if seconds else 0,
        }
        for name, watched in sorted(by_channel.items(), key=lambda entry: (-entry[1], entry[0]))
        if name
    ]
    return {
        "videos": len(rows),
        "videos_without_time": videos_without_time,
        "seconds": seconds,
        "hours_label": (
            f"{seconds}s"
            if 0 < seconds < SECONDS_PER_MINUTE
            else minutes_to_hm(seconds // SECONDS_PER_MINUTE)
        ),
        "channels": channels,
        "estimated": estimated,
    }
