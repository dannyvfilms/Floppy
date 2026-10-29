"""Compose Home display levels using compact ranks and page-sized cards."""

import hashlib
import json
from copy import copy
from dataclasses import replace
from datetime import datetime, time
from itertools import islice
from types import SimpleNamespace

from django.core.cache import cache
from django.db.models import Min, Q
from django.utils import timezone

from app import cache_utils
from app.library_query import LibraryQueryExecutor
from app.library_query.adapters import from_home_row_filters
from app.library_query.executor import order_rows, rank_row
from app.library_query.filters import TypeContext, collected_q
from app.library_query.sorts import random_rank
from app.library_query.spec import ROUTING_LIBRARY
from app.library_query.trackers import tracker_sources
from app.models import (
    AlbumTracker,
    ArtistTracker,
    Episode,
    Item,
    PodcastShowTracker,
    Season,
)
from app.models.discovery import ItemTag
from users import home_screen as home
from users.models import DirectionChoices, HomeSortChoices, MediaSortChoices

BATCH_SIZE = 200
PROJECTION_KINDS = {"albums": "album", "artists": "artist", "shows": "podcast_show"}
PROJECTION_MODELS = {
    "album": AlbumTracker,
    "artist": ArtistTracker,
    "podcast_show": PodcastShowTracker,
}


def _projection_batches(user, kind, *, ids=None, persist=False):
    """Reuse Home's adapters and shell items, retaining one batch of trackers."""
    model = PROJECTION_MODELS[kind]
    relation = {"album": "album", "artist": "artist", "podcast_show": "show"}[kind]
    rows = model.objects.filter(user=user).select_related(relation).order_by("pk")
    if ids is not None:
        rows = rows.filter(pk__in=ids)
    if kind == "album":
        rows = rows.select_related("album__artist")
    if kind == "podcast_show":
        rows = rows.annotate(first_published=Min("show__episodes__published"))
    iterator = rows.iterator(chunk_size=BATCH_SIZE)
    while batch := list(islice(iterator, BATCH_SIZE)):
        if kind == "podcast_show":
            shows = [tracker.show for tracker in batch]
            shells = home._podcast_show_shell_items_bulk(
                shows, persist=None if persist else set()
            )
        else:
            specs = [
                (
                    f"{kind}_{getattr(tracker, relation).pk}",
                    getattr(tracker, relation).title
                    if kind == "album"
                    else tracker.artist.name,
                    getattr(tracker, relation).image,
                )
                for tracker in batch
            ]
            shells = home._music_shell_items_bulk(
                specs, persist=None if persist else set()
            )
        entries = []
        for tracker in batch:
            entity = getattr(tracker, relation)
            key = (
                (entity.source, entity.podcast_uuid)
                if kind == "podcast_show"
                else f"{kind}_{entity.pk}"
            )
            item = copy(shells[key])
            if not item.title:
                continue
            if kind == "album":
                item.release_datetime = (
                    timezone.make_aware(datetime.combine(entity.release_date, time.min))
                    if entity.release_date
                    else None
                )
                media = home._AlbumHomeAdapter(item, tracker, entity)
            elif kind == "artist":
                item.release_datetime = None
                media = home._ArtistHomeAdapter(item, tracker, entity)
            else:
                item.release_datetime = tracker.first_published
                media = home._PodcastShowHomeAdapter(item, tracker, entity)
            entries.append(
                (
                    tracker.pk,
                    home.HomeRowEntry(
                        item=item,
                        media=media,
                        show_progress_controls=False,
                        use_podcast_show=kind == "podcast_show",
                        podcast_show=entity if kind == "podcast_show" else None,
                    ),
                )
            )
        yield entries


def _filter_projection_batch(user, entries, filters):
    """Status/rating belong to the tracker; membership belongs to its shell."""
    item_ids = [entry.item.pk for _, entry in entries if entry.item.pk]
    ctx = TypeContext(
        user=user, media_type="music", sources=(), today=timezone.localdate()
    )
    collected = set(
        Item.objects.filter(pk__in=item_ids)
        .filter(collected_q(ctx))
        .values_list("pk", flat=True)
    )
    tags = filters.get("tag") or []
    tagged = {
        tag: set(
            ItemTag.objects.filter(
                tag__user=user,
                tag__name__iexact=tag,
                item_id__in=item_ids,
            ).values_list("item_id", flat=True)
        )
        for tag in tags
    }
    for identity, entry in entries:
        media, item = entry.media, entry.item
        if filters.get("status") and media.status not in filters["status"]:
            continue
        rated = media.score is not None
        if (filters.get("rating") == "rated" and not rated) or (
            filters.get("rating") == "not_rated" and rated
        ):
            continue
        if filters.get("collection") == "collected" and item.pk not in collected:
            continue
        if filters.get("collection") == "not_collected" and item.pk in collected:
            continue
        matches = [item.pk in tagged[tag] for tag in tags]
        mode = filters.get("tag_mode", "or")
        if matches and (
            (mode == "and" and not all(matches))
            or (mode == "or" and not any(matches))
            or (mode == "not" and any(matches))
        ):
            continue
        released = (
            item.release_datetime is not None
            and timezone.localdate(item.release_datetime) <= ctx.today
        )
        if (filters.get("release") == "released" and not released) or (
            filters.get("release") == "not_released" and released
        ):
            continue
        yield identity, entry


def _normal_rank(value):
    """Normalize SQL date values to Home's Python timestamps."""
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, tuple):
        return tuple(_normal_rank(part) for part in value)
    return value


def _projection_value(user, entry, sort_by, direction, seed, identity):
    if sort_by == HomeSortChoices.RECENT:
        return home._recent_values(
            user, [SimpleNamespace(item=entry.item, media=entry.media)], direction
        )[0]
    if sort_by == HomeSortChoices.RANDOM:
        # Separate namespaces stay stable before and after a shell is saved.
        kind, pk = identity
        virtual_id = -(pk * 4 + tuple(PROJECTION_MODELS).index(kind) + 1)
        return random_rank(virtual_id, seed)
    getters = {
        MediaSortChoices.TITLE: lambda e: e.item.title.lower(),
        MediaSortChoices.SCORE: home._entry_score,
        MediaSortChoices.END_DATE: home._entry_last_watched_timestamp,
        MediaSortChoices.DATE_ADDED: home._entry_date_added_timestamp,
    }
    return getters[sort_by](entry)


def _item_executors(user, row, filters, families, seed):
    """Keep normal libraries together and scope TV children through their owner."""
    subviews = filters["media_subviews"]
    ordinary = [
        family
        for family in families
        if not (
            (family == "tv" and subviews["tv"] != "shows")
            or (family == "music" and subviews["music"] != "tracks")
            or (family == "podcast" and subviews["podcast"] == "shows")
        )
    ]
    kwargs = {
        "sort_key": home.HOME_ENGINE_SORT_KEYS.get(row.sort_by, row.sort_by),
        "direction": home.resolve_home_row_direction(row.sort_by, row.direction),
        "seed": seed,
        "mixed": True,
    }
    if ordinary:
        yield LibraryQueryExecutor(
            user, from_home_row_filters(user, filters, tuple(ordinary), **kwargs)
        )
    if "tv" not in families or subviews["tv"] == "shows":
        return
    tv_scope = Q(pk__in=[])
    for source in tracker_sources(user, "tv", ROUTING_LIBRARY):
        tv_scope |= Q(pk__in=source.item_ids(user)) & source.item_q
    show_ids = Item.objects.filter(tv_scope).values("pk")
    if subviews["tv"] == "seasons":
        media_type = "season"
        child_ids = Season.objects.filter(
            user=user, related_tv__item_id__in=show_ids
        ).values("item_id")
    else:
        media_type = "episode"
        child_ids = Episode.objects.filter(
            related_season__user=user, related_season__related_tv__item_id__in=show_ids
        ).values("item_id")
    query = from_home_row_filters(user, filters, (media_type,), **kwargs)
    yield LibraryQueryExecutor(user, replace(query, within=child_ids))


def mixed_row_window(user, row, filters, offset, limit, *, seed):
    """Rank once, then hydrate only this page across all selected display levels."""
    families = home._all_media_type_selection(user, row.filters)
    signature = hashlib.sha256(
        json.dumps(
            [
                families,
                filters,
                row.sort_by,
                row.direction,
                user.anime_library_mode,
                user.tv_metadata_source_default,
            ],
            sort_keys=True,
        ).encode()
    ).hexdigest()[:16]
    updated = int(row.updated_at.timestamp() * 1_000_000) if row.updated_at else 0
    key = f"{cache_utils.HOME_ROW_CACHE_PREFIX}_mixed_{user.pk}_{row.pk}_{updated}_{signature}_{seed}"
    identities = cache.get(key)
    if identities is None:
        ranks = {}
        for executor in _item_executors(user, row, filters, families, seed):
            for value, title, season, episode, pk in executor.rank_rows():
                identity = ("item", pk)
                ranks[identity] = (
                    _normal_rank(value),
                    title,
                    season,
                    episode,
                    identity,
                )
        for family in families:
            level = filters["media_subviews"].get(family)
            if not (
                (family == "music" and level in ("artists", "albums"))
                or (family == "podcast" and level == "shows")
            ):
                continue
            kind = PROJECTION_KINDS[level]
            for batch in _projection_batches(user, kind):
                for pk, entry in _filter_projection_batch(user, batch, filters):
                    identity = (kind, pk)
                    value = _projection_value(
                        user, entry, row.sort_by, row.direction, seed, identity
                    )
                    ranked = rank_row(value, entry.item)
                    ranks[identity] = (*ranked[:-1], identity)
        direction = home.home_engine_direction(row.sort_by, row.direction)
        if row.sort_by == HomeSortChoices.RECENT:
            direction = DirectionChoices.ASC  # the composite value encodes direction
        identities = [
            rank[-1]
            for rank in order_rows(
                list(ranks.values()), descending=direction == DirectionChoices.DESC
            )
        ]
        cache.set(
            key,
            identities,
            cache_utils.HOME_ROW_CACHE_TTL
            if row.sort_by == HomeSortChoices.RANDOM
            else cache_utils.HOME_ROW_ORDER_CACHE_TTL,
        )
        cache_utils.register_home_row_cache_key(user.pk, key)
    selected = identities[offset : offset + limit]
    item_ids = [pk for kind, pk in selected if kind == "item"]
    items = Item.objects.defer(*home.HOME_CARD_UNREAD_ITEM_FIELDS).in_bulk(item_ids)
    entries = {
        ("item", entry.item.pk): entry
        for entry in home._row_entries(
            user, list(items.values()), podcast_episodes=True
        )
    }
    for kind in PROJECTION_MODELS:
        ids = [pk for selected_kind, pk in selected if selected_kind == kind]
        if ids:
            for batch in _projection_batches(user, kind, ids=ids, persist=True):
                entries.update({(kind, pk): entry for pk, entry in batch})
    return [entries[identity] for identity in selected if identity in entries], len(
        identities
    )
