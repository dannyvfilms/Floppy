"""Tie YouTube video watches to Floppy games and total the evidence on their plays."""

import logging
import re
import unicodedata
from collections import defaultdict
from hashlib import sha256
from uuid import uuid4

from django.core.cache import cache
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from app.cache_safety import cache_add
from app.helpers import minutes_to_hm
from app.models import MediaTypes, Sources, Video, VideoGameTag, VideoPlay
from app.services import youtube_game

logger = logging.getLogger(__name__)
SECONDS_PER_MINUTE = 60
SUMMARY_TTL = 300
GENERATION_TTL = SUMMARY_TTL * 2
TAG_GENERATION_KEY = "youtube-game-watch:tags"
GAME_BACKFILL_TTL = 180
GAME_BACKFILL_BATCH = 10

# YouTube dates the original PC release to 2009; IGDB dates Java Edition to
# the 2011 full release. IGDB lists Bedrock as "Minecraft", and "Dream it,
# Build it!" is Mojang's mobile Bedrock storefront title.
YOUTUBE_GAME_IDENTITIES = {
    "UCQvWX73GQygcwXOTSf_VDVg": (Sources.IGDB.value, "121"),  # Minecraft (2009)
    "UCQLJP2NLGXxEosSEW5vaohQ": (Sources.IGDB.value, "135400"),  # Dream it, Build it!
    "UCqLDGOjU4oxhd9M5hFPjwfw": (Sources.IGDB.value, "135400"),  # Bedrock Edition
    "UCq6HGbAAz7z5k6KxwwWC0tw": (Sources.IGDB.value, "204910"),  # Java & Bedrock for PC
    "UCbpAqBS5GnYp37Arz1hb6uA": (Sources.IGDB.value, "204910"),  # Java & Bedrock Edition
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


def _watch_cache_keys(user, games):
    keys = (_viewer_generation_key(user.pk), TAG_GENERATION_KEY)
    generations = cache.get_many(keys)
    viewer_generation, tag_generation = [
        generations.get(key) or cache.get_or_set(key, uuid4().hex, GENERATION_TTL)
        for key in keys
    ]
    for game in games:
        identity = sha256(f"{game.title}\n{game.release_datetime}".encode()).hexdigest()
        yield game.pk, f"youtube-game-watch:v3:{user.pk}:{game.pk}:{identity}:{viewer_generation}:{tag_generation}"


def cached_watched_for_game(user, game_item):
    """Cache the total and every channel together, including an empty result."""
    _, key = next(_watch_cache_keys(user, [game_item]))
    # The wrapper lets a cached None distinguish an empty result from a miss.
    return cache.get_or_set(
        key, lambda: {"watch": watched_for_game(user, game_item)}, SUMMARY_TTL,
    )["watch"]


def cached_watched_for_games(user, games):
    """Read the same summaries as game detail, filling any misses as a batch."""
    if not games:
        return {}
    keys = dict(_watch_cache_keys(user, games))
    stored = cache.get_many(keys.values())
    missing = [game for game in games if keys[game.pk] not in stored]
    if missing:
        fresh = {keys[pk]: {"watch": summary} for pk, summary in _watched_for_games(user, missing).items()}
        cache.set_many(fresh, SUMMARY_TTL)
        stored.update(fresh)
    return {pk: stored[key]["watch"] for pk, key in keys.items()}


def _tagged_games(games):
    by_title = defaultdict(list)
    by_identity = defaultdict(list)
    for game in games:
        by_title[normalize_title(game.title)].append(game)
        by_identity[game.source, game.media_id].append(game)
    tags = VideoGameTag.objects.filter(status=VideoGameTag.Status.FOUND).values_list(
        "item_id", "game_title", "release_year", "game_id",
    )
    for item_id, title, year, game_id in tags.iterator():
        identity = YOUTUBE_GAME_IDENTITIES.get(game_id)
        candidates = by_identity.get(identity, ()) if identity else by_title.get(normalize_title(title), ())
        for game in candidates:
            if tag_matches_game(title, year, game, youtube_game_id=game_id):
                yield item_id, game.pk


def _tagged_item_ids(game_item):
    return [item_id for item_id, _ in _tagged_games([game_item])]


def _game_backfill_key(user_id, game_id):
    return f"youtube-game-watch:backfill:{user_id}:{game_id}"


def request_game_backfill(user, game_item):
    """Queue one bounded chain for a private game page and report if it is active."""
    from app.tasks_youtube_game import backfill_youtube_game_detail

    key = _game_backfill_key(user.pk, game_item.pk)
    state = cache.get(key)
    if state is not None:
        return bool(state)
    if cache.get(youtube_game.RATE_LIMIT_KEY):
        return False
    token = uuid4().hex
    if not cache_add(key, token, timeout=GAME_BACKFILL_TTL):
        return bool(cache.get(key))
    try:
        backfill_youtube_game_detail.delay(user.pk, game_item.pk, token)
    except Exception:
        logger.exception("Could not queue YouTube game backfill game=%s", game_item.pk)
        cache.set(key, "", SUMMARY_TTL)
        return False
    return True


def game_backfill_candidates(user_id, game, limit=GAME_BACKFILL_BATCH):
    """Select eligible watches for runtime fill or tag discovery."""
    now = timezone.now()
    tags = _tagged_item_ids(game)
    # A title finds candidates only. The tag written from the watch page
    # decides whether they count for this game.
    is_minecraft = game.source == Sources.IGDB.value and game.media_id in {"121", "135400", "204910"}
    term = "Minecraft" if is_minecraft else game.title
    videos = Video.objects.filter(user_id=user_id, item__source=Sources.YOUTUBE.value)
    retry = Q(
        item__video_game_tag__failures__lt=youtube_game.MAX_FAILURES,
        item__video_game_tag__checked_at__lte=now - youtube_game.UNAVAILABLE_BACKOFF,
    )
    fresh = Q(item__video_game_tag__isnull=True)
    missing_runtime = Q(item__video_game_tag__runtime_seconds__isnull=True)
    matched = Q(game_link__game_item=game) | Q(game_link__isnull=True, item_id__in=tags)
    plays_needing_runtime = VideoPlay.objects.filter(
        video_id=OuterRef("pk"),
        progress=0,
    )
    timings = videos.filter(
        matched & (fresh | (missing_runtime & retry)),
        Exists(plays_needing_runtime),
        length_seconds=0,
    ).order_by("pk").values_list("item_id", flat=True)
    ids = list(timings[:limit])
    if len(ids) < limit and term:
        discovery = fresh | (retry & Q(item__video_game_tag__status=VideoGameTag.Status.UNAVAILABLE))
        # Revisit older checks made before runtime collection once, even if
        # the video was imported long ago. A current negative is left alone.
        discovery |= missing_runtime & Q(
            item__video_game_tag__status=VideoGameTag.Status.NOT_FOUND,
            item__video_game_tag__checked_at__lte=now - youtube_game.NOT_FOUND_RECHECK,
        )
        ids.extend(videos.filter(
            discovery, game_link__isnull=True, item__title__icontains=term,
        ).exclude(item_id__in=ids).order_by("pk").values_list("item_id", flat=True)[:limit - len(ids)])
    return ids


def watched_for_game(user, game_item):
    """Count dated plays using their reported positions or a runtime estimate.

    A video counts when the user linked it to this game, or when YouTube's tag
    matches it and the user has not unlinked or relinked it elsewhere.

    Returns the duration and the count of videos without usable timing data,
    or None when nothing matches.
    """
    if game_item.media_type != MediaTypes.GAME.value:
        return None
    return _watched_for_games(user, [game_item])[game_item.pk]


def _watched_for_games(user, games):
    rows_by_game = {game.pk: [] for game in games}
    videos = Video.objects.filter(user=user)
    fields = ("pk", "length_seconds", "channel", "item__video_game_tag__runtime_seconds")
    manual = videos.filter(game_link__game_item_id__in=rows_by_game)
    for game_id, *row in manual.values_list("game_link__game_item_id", *fields).iterator():
        rows_by_game[game_id].append(row)
    # Start from the (few) found tags, not the user's whole video table: walking
    # every video row to reach its tag is one random read per row on a cold disk.
    games_by_item = defaultdict(list)
    for item_id, game_id in _tagged_games(games):
        games_by_item[item_id].append(game_id)
    if games_by_item:
        tagged = videos.filter(item_id__in=games_by_item, game_link__isnull=True)
        for item_id, *row in tagged.values_list("item_id", *fields).iterator():
            for game_id in games_by_item[item_id]:
                rows_by_game[game_id].append(row)

    lengths = {
        pk: client_length or published_length or 0
        for rows in rows_by_game.values()
        for pk, client_length, _, published_length in rows
    }
    reported = defaultdict(int)
    runtime_estimates = defaultdict(int)
    untimed_plays = set()
    plays = VideoPlay.objects.filter(video_id__in=lengths).values_list("video_id", "progress")
    for video_id, position in plays.iterator():
        length = lengths[video_id]
        if position:
            # Seeking can put a reported position beyond the video's length.
            reported[video_id] += min(position, length) if length else position
        elif length:
            runtime_estimates[video_id] += length
        else:
            untimed_plays.add(video_id)
    return {
        pk: _summarize_watches(rows, reported, runtime_estimates, untimed_plays)
        for pk, rows in rows_by_game.items()
    }


def _summarize_watches(rows, reported, runtime_estimates, untimed_plays):
    if not rows:
        return None
    by_channel = {}
    reported_position_seconds = 0
    runtime_estimate_seconds = 0
    videos_without_time = 0
    for pk, _, channel, _ in rows:
        position_seconds = reported.get(pk, 0)
        estimate_seconds = runtime_estimates.get(pk, 0)
        watched = position_seconds + estimate_seconds
        name = (channel or "").strip()
        by_channel[name] = by_channel.get(name, 0) + watched
        reported_position_seconds += position_seconds
        runtime_estimate_seconds += estimate_seconds
        videos_without_time += int(pk in untimed_plays)
    seconds = reported_position_seconds + runtime_estimate_seconds
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
        "reported_position_seconds": reported_position_seconds,
        "runtime_estimate_seconds": runtime_estimate_seconds,
        "hours_label": (
            f"{seconds}s"
            if 0 < seconds < SECONDS_PER_MINUTE
            else minutes_to_hm(seconds // SECONDS_PER_MINUTE)
        ),
        "channels": channels,
        "estimated": bool(seconds),
    }
