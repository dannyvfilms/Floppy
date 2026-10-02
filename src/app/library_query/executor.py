"""Run a ``LibraryQuery``: one page of ordered items and the total, in bounded work.

Two paths, chosen from the filter and sort registries rather than a list of
exceptions:

- **SQL**: every active filter and the sort compile to SQL. Filtering,
  ordering, ``COUNT`` and ``LIMIT``/``OFFSET`` all run in the database; only
  the page's items are loaded.
- **Scan**: a filter or the sort needs Python. Candidates are narrowed by
  every SQL-capable condition first, then read in fixed-size batches that
  keep only ``(sort value, title, id)`` per match. The page's items are
  loaded at the end. Memory and hydration are bounded by the batch and the
  page; computing Python values is still one pass over the SQL-narrowed
  candidates.

The executor returns ``Item`` rows. Decorating them (tracker rows, card
images, progress) is the calling surface's job, and it only ever sees a page.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from itertools import islice
from typing import TYPE_CHECKING

from django.db.models import Exists, F, OuterRef, Q
from django.db.models.functions import Coalesce, Lower
from django.utils import timezone

from app.library_query import filters as filter_registry
from app.library_query import sorts as sort_registry
from app.library_query.spec import ROUTING_MODEL, STATUS_MATCH_LATEST
from app.library_query.trackers import tracker_sources
from app.models.choices import MediaTypes, Sources
from app.models.item import Item

if TYPE_CHECKING:
    from app.library_query.spec import LibraryQuery

DEFAULT_BATCH_SIZE = 256
DESC = "desc"


@dataclass
class Candidate:
    """An item being evaluated, and its aggregated tracker row once loaded."""

    item: Item
    media: object | None = None


@dataclass
class Page:
    """One ordered page of items and the size of the full result."""

    items: list[Item]
    total: int
    used_sql: bool


class LibraryQueryExecutor:
    """Evaluate one ``LibraryQuery`` for one user."""

    def __init__(self, user, query: LibraryQuery, *, batch_size: int = DEFAULT_BATCH_SIZE):
        """Prepare ``query`` for ``user``; nothing runs until it is asked for."""
        self.user = user
        self.query = query
        self.batch_size = batch_size
        self.today = timezone.localdate()

    # -- compilation ----------------------------------------------------------

    @cached_property
    def contexts(self) -> list[filter_registry.TypeContext]:
        """Return one compilation context per requested media type."""
        return [
            filter_registry.TypeContext(
                user=self.user,
                media_type=media_type,
                sources=tuple(tracker_sources(self.user, media_type, self.query.routing)),
                today=self.today,
                provider_region=self.query.provider_region,
                pinned_providers=self.query.pinned_providers,
                sort_list_id=self.query.sort_list_id,
                filters=self.query.filters,
            )
            for media_type in self.query.media_types
        ]

    def _active(self, ctx):
        return filter_registry.active_filters(self.query.filters, ctx.media_type)

    def _membership_q(self, ctx) -> Q:
        """Return the condition for an item being in this type's candidates."""
        values = self.query.filters
        active = self._active(ctx)
        scope_q = self._scope_q()
        if scope_q is not None:
            # A list or id scope keeps untracked items; tracker rows are only
            # required when a row condition asks something of them.
            membership = scope_q & self._type_q(ctx)
            if self._row_conditions(ctx, active, scoped=True):
                membership &= self._tracked_q(ctx, active, scoped=True)
            return membership

        membership = self._tracked_q(ctx, active)
        if self.query.include_collection_only and filter_registry.collection_only_allowed(
            values,
        ):
            membership |= self._collection_only_q(ctx)
        return membership

    def _type_q(self, ctx) -> Q:
        """Return: the item itself belongs to this type's library."""
        if self.query.routing == ROUTING_MODEL:
            return Q(media_type=ctx.media_type)
        return Q(media_type=ctx.media_type) | Q(library_media_type=ctx.media_type)

    def _scope_q(self) -> Q | None:
        """Return the candidate scope, or ``None`` for the user's library."""
        if self.query.list_id is not None:
            from lists.models import CustomListItem

            return Q(
                pk__in=CustomListItem.objects.filter(
                    custom_list_id=self.query.list_id,
                ).values("item_id"),
            )
        if self.query.within is not None:
            return Q(pk__in=self.query.within)
        return None

    def _row_conditions(self, ctx, active, *, scoped: bool) -> dict:
        """Return each tracker source's combined row condition, if any."""
        conditions = {}
        for source in ctx.sources:
            row_q = Q()
            for definition in active:
                if definition.row is None:
                    continue
                if scoped and definition.key == "status" and (
                    self.query.filters.status_match == STATUS_MATCH_LATEST
                ):
                    # "Has a status" defines library membership, not a list's.
                    continue
                condition = definition.row(self.query.filters, source, ctx)
                if condition is not None:
                    row_q &= condition
            if row_q:
                conditions[source] = row_q
        return conditions

    def _tracked_q(self, ctx, active, *, scoped: bool = False) -> Q:
        """Return: a tracker row of this type satisfies every row condition."""
        conditions = self._row_conditions(ctx, active, scoped=scoped)
        return filter_registry.any_q(
            [
                source.item_q
                & Q(pk__in=source.item_ids(self.user, conditions.get(source)))
                for source in ctx.sources
            ],
        )

    def _collection_only_q(self, ctx) -> Q:
        """Return collected items of this type that have no tracker row."""
        from app.models.discovery import CollectionEntry

        collected = Q(
            pk__in=CollectionEntry.objects.filter(user=self.user).values("item_id"),
        ) & ~Q(media_type=MediaTypes.EPISODE.value)
        if ctx.media_type in (MediaTypes.TV.value, MediaTypes.ANIME.value):
            collected |= Q(
                media_type__in=(MediaTypes.TV.value, MediaTypes.ANIME.value),
                pk__in=filter_registry.shows_with_collected_episodes(self.user),
            )
        untracked = ~filter_registry.any_row(ctx)
        return self._type_q(ctx) & collected & untracked

    def _item_q(self, ctx) -> Q:
        """Return every SQL condition for this media type."""
        condition = self._membership_q(ctx)
        for definition in self._active(ctx):
            if definition.sql is None:
                continue
            compiled = definition.sql(self.query.filters, ctx)
            if compiled is not None:
                condition &= compiled
        return condition

    @cached_property
    def _predicates_by_type(self) -> dict[str, list]:
        return {
            ctx.media_type: [d for d in self._active(ctx) if d.predicate is not None]
            for ctx in self.contexts
        }

    def _predicates(self, ctx):
        return self._predicates_by_type[ctx.media_type]

    @cached_property
    def _needs_scan(self) -> bool:
        return any(self._predicates_by_type.values())

    def _union_ids(self):
        """Return ids of items in the lists the query always includes."""
        from lists.models import CustomListItem

        return CustomListItem.objects.filter(
            custom_list_id__in=self.query.union_list_ids,
        ).values("item_id")

    @cached_property
    def filtered(self):
        """Return the ``Item`` queryset narrowed by every SQL condition."""
        if not self.contexts:
            queryset = Item.objects.none()
        else:
            queryset = Item.objects.filter(
                filter_registry.any_q([self._item_q(ctx) for ctx in self.contexts]),
            )
        hidden_ids = self._cross_provider_hidden_ids(queryset)
        if hidden_ids:
            queryset = queryset.exclude(pk__in=hidden_ids)
        if self.query.union_list_ids:
            queryset = Item.objects.filter(
                Q(pk__in=queryset.values("pk")) | Q(pk__in=self._union_ids()),
            )
        return queryset

    @cached_property
    def sort(self):
        """Return the definition of the requested sort key."""
        return sort_registry.sort_def(self.query.sort.key)

    @cached_property
    def direction(self) -> str:
        """Return the requested direction, or the key's default."""
        from app.models import BasicMedia

        if self.sort.direction_in_value:
            return "asc"
        return BasicMedia.objects.resolve_direction(
            self.query.sort.key,
            self.query.sort.direction,
        )

    @cached_property
    def uses_sql(self) -> bool:
        """Return whether filters and sort all compile to SQL."""
        sortable = self._sort_expressions is not None or self._sql_order_keys is not None
        return bool(self.contexts) and sortable and not self._needs_scan

    @cached_property
    def _sql_order_keys(self) -> list | None:
        if self.sort.sql_order is None or len(self.contexts) != 1:
            return None
        return self.sort.sql_order(
            self.contexts[0],
            self.query.sort.seed,
            self.query.sort.direction,
        )

    @cached_property
    def _sort_expressions(self) -> list | None:
        if self.sort.sql is None:
            return None
        expressions = [self.sort.sql(ctx, self.query.sort.seed) for ctx in self.contexts]
        if any(expression is None for expression in expressions):
            return None
        return expressions

    def _sort_expression(self):
        expressions = self._sort_expressions
        if len(expressions) == 1 or not self.sort.tracker:
            return expressions[0]
        return Coalesce(*expressions)

    def _ordered(self, queryset):
        if self._sql_order_keys is not None:
            annotations, keys = self._sql_order_keys
            return queryset.annotate(**annotations).order_by(
                *keys,
                *tie_breakers(descending=False),
            )
        expression = self._sort_expression()
        descending = self.direction == DESC
        queryset = queryset.annotate(_library_sort=expression)
        value = F("_library_sort")
        return queryset.order_by(
            value.desc(nulls_last=True) if descending else value.asc(nulls_last=True),
            *tie_breakers(descending=descending),
        )

    # -- cross-provider aliases -----------------------------------------------

    def _cross_provider_hidden_ids(self, queryset) -> set[int]:
        """Return TMDB items hidden because their TVDB alias is also listed (#639)."""
        if not self.query.dedupe_cross_provider:
            return set()
        show_types = {
            MediaTypes.TV.value,
            MediaTypes.ANIME.value,
            MediaTypes.SEASON.value,
        }
        if not show_types.intersection(self.query.media_types):
            return set()
        from app.services.item_merge import dedupe_cross_provider_items

        rows = queryset.filter(
            media_type__in=(MediaTypes.TV.value, MediaTypes.SEASON.value),
            source__in=(Sources.TMDB.value, Sources.TVDB.value),
        ).only(
            "id",
            "media_id",
            "media_type",
            "season_number",
            "source",
            "provider_external_ids",
        )
        if not rows.filter(source=Sources.TVDB.value).exists():
            return set()
        items = list(rows)
        kept = dedupe_cross_provider_items(
            items,
            getattr(self.user, "tv_metadata_source_default", Sources.TMDB.value),
        )
        return {item.id for item in items} - {item.id for item in kept}

    # -- evaluation -----------------------------------------------------------

    def count(self) -> int:
        """Return how many items match."""
        if not self._needs_scan:
            return self.filtered.count()
        # A count is nearly always followed by ``page``; share its scan.
        return len(self._scan_ranked)

    def ids(self) -> set[int]:
        """Return every matching item id (for smart-list membership)."""
        if not self._needs_scan:
            return set(self.filtered.values_list("pk", flat=True))
        return {pk for *_rest, pk in self._scan(self.filtered, with_sort=False)}

    def ranked_ids(self) -> list[int]:
        """Return every matching item id in order (for caching an order)."""
        if self.uses_sql:
            return list(self._ordered(self.filtered).values_list("pk", flat=True))
        return [row[-1] for row in self._scan_ranked]

    def matches(self):
        """Return the matches as a scope for another query's ``within``.

        A ``pk`` subquery when every filter is SQL, so nothing is loaded;
        the matching ids when a Python filter had to run.
        """
        if not self._needs_scan:
            return self.filtered.values("pk")
        return self.ids()

    def contains(self, item_id: int) -> bool:
        """Return whether one item matches, without evaluating the others."""
        candidates = self.filtered.filter(pk=item_id)
        if not self._needs_scan:
            return candidates.exists()
        return bool(self._scan(candidates, with_sort=False))

    def page(
        self,
        offset: int,
        limit: int,
        *,
        defer: tuple[str, ...] = (),
        total: int | None = None,
    ) -> Page:
        """Return ``limit`` items starting at ``offset``, and the total.

        ``defer`` names ``Item`` columns the caller will not read. Pass
        ``total`` when the caller already counted, to skip a second count.
        """
        offset = max(0, offset)
        if self.uses_sql:
            ordered = self._ordered(self.filtered)
            if total is None:
                total = ordered.count()
            items = list(ordered.defer(*defer)[offset : offset + limit])
            return Page(items, total, used_sql=True)

        ranked = self._scan_ranked
        selected_ids = [pk for *_rest, pk in ranked[offset : offset + limit]]
        by_id = Item.objects.defer(*defer).in_bulk(selected_ids)
        return Page([by_id[i] for i in selected_ids if i in by_id], len(ranked), False)

    @cached_property
    def _scan_ranked(self) -> list[tuple]:
        """Return a ``rank_row`` for every match, in order."""
        return order_rows(
            self._scan(self.filtered, with_sort=True),
            descending=self.direction == DESC,
        )

    def _scan(self, queryset, *, with_sort: bool) -> list[tuple]:
        """Read candidates in batches; keep a compact ``rank_row`` per match."""
        sql_sort = with_sort and bool(self.contexts) and self._sort_expressions is not None
        if sql_sort:
            queryset = queryset.annotate(_library_sort=self._sort_expression())
        if self.query.union_list_ids:
            queryset = queryset.annotate(
                _in_union=Exists(self._union_ids().filter(item_id=OuterRef("pk"))),
            )

        needs = set(self.sort.needs) if with_sort else set()
        for ctx in self.contexts:
            for definition in self._predicates(ctx):
                needs |= definition.needs
        if filter_registry.NEEDS_WATCH_PROVIDERS not in needs:
            queryset = queryset.defer("watch_providers")
        contexts_by_type = {ctx.media_type: ctx for ctx in self.contexts}
        python_key = None
        batch_values = self.sort.batch_values if with_sort and not sql_sort else None
        if with_sort and not sql_sort and batch_values is None:
            python_key = sort_registry.python_key(self.query.sort.key)
            # A tracker value computed in Python reads the aggregated row.
            needs.add(filter_registry.NEEDS_MEDIA)
        requested_direction = self.query.sort.direction

        rows = []
        iterator = queryset.iterator(chunk_size=self.batch_size)
        while True:
            batch = [Candidate(item) for item in islice(iterator, self.batch_size)]
            if not batch:
                break
            if filter_registry.NEEDS_MEDIA in needs:
                _attach_media(self.user, batch, needs)
            for ctx in self.contexts:
                for definition in self._predicates(ctx):
                    if definition.prepare is not None:
                        definition.prepare(
                            [c for c in batch if _context_for(c.item, contexts_by_type) is ctx],
                            self.query.filters,
                            ctx,
                        )
            kept = []
            for candidate in batch:
                if not getattr(candidate.item, "_in_union", False):
                    ctx = _context_for(candidate.item, contexts_by_type)
                    if ctx is not None and not all(
                        definition.predicate(candidate, self.query.filters, ctx)
                        for definition in self._predicates(ctx)
                    ):
                        continue
                kept.append(candidate)
            if batch_values is not None:
                values = batch_values(self.user, kept, requested_direction)
                rows.extend(rank_row(value, c.item) for value, c in zip(values, kept, strict=True))
                continue
            for candidate in kept:
                if not with_sort:
                    value = None
                elif python_key is None:
                    value = candidate.item._library_sort
                elif candidate.media is None and self.sort.tracker:
                    # No tracker row, so no tracker value (not zero progress).
                    value = None
                else:
                    value = python_key(candidate)
                rows.append(rank_row(value, candidate.item))
        return rows


def tie_breakers(*, descending: bool) -> list:
    """Return the SQL ordering after the sort value: title, season, episode, id.

    Seasons and episodes of one show share a title, so they fall back to
    their numbers (a missing number first when ascending) before the id.
    """
    if descending:
        return [
            Lower("title").desc(),
            F("season_number").desc(nulls_last=True),
            F("episode_number").desc(nulls_last=True),
            F("pk").desc(),
        ]
    return [
        Lower("title").asc(),
        F("season_number").asc(nulls_first=True),
        F("episode_number").asc(nulls_first=True),
        F("pk").asc(),
    ]


def rank_row(value, item) -> tuple:
    """Return a scan row that orders like ``tie_breakers`` after ``value``."""
    season = -1 if item.season_number is None else item.season_number
    episode = -1 if item.episode_number is None else item.episode_number
    return (value, (item.title or "").lower(), season, episode, item.pk)


def order_rows(rows: list[tuple], *, descending: bool) -> list[tuple]:
    """Order ``rank_row`` rows like the SQL path: value (nulls last), then ties."""
    present = [row for row in rows if row[0] is not None]
    missing = [row for row in rows if row[0] is None]
    present.sort(reverse=descending)
    missing.sort(key=lambda row: row[1:], reverse=descending)
    return present + missing


def _context_for(item, contexts_by_type):
    for media_type in (item.library_media_type, item.media_type):
        ctx = contexts_by_type.get(media_type)
        if ctx is not None:
            return ctx
    return None


def _attach_media(user, batch: list[Candidate], needs: set[str]) -> None:
    """Load each candidate's aggregated tracker row, for this batch only."""
    from django.apps import apps

    from app.models import BasicMedia

    by_type: dict[str, list[Candidate]] = {}
    for candidate in batch:
        if candidate.item.media_type == MediaTypes.EPISODE.value:
            continue
        by_type.setdefault(candidate.item.media_type, []).append(candidate)

    for media_type, candidates in by_type.items():
        model = apps.get_model("app", media_type)
        rows = model.objects.filter(
            user=user,
            item_id__in=[candidate.item.pk for candidate in candidates],
        ).select_related("item")
        # Progress and derived status read episodes and seasons; fetch them
        # once for the batch instead of once per row.
        rows = BasicMedia.objects._apply_prefetch_related(rows, media_type)
        aggregated = BasicMedia.objects._aggregate_duplicate_data(rows, user, media_type)
        latest = {}
        for media in aggregated:
            current = latest.get(media.item_id)
            if current is None or media.created_at > current.created_at:
                latest[media.item_id] = media
        tracked = []
        for candidate in candidates:
            candidate.media = latest.get(candidate.item.pk)
            if candidate.media is not None:
                tracked.append(candidate.media)
        if tracked and filter_registry.NEEDS_MAX_PROGRESS in needs:
            BasicMedia.objects.annotate_max_progress(tracked, media_type)
        if tracked and filter_registry.NEEDS_RUNTIME in needs:
            from app.models import prefill_episode_runtime_index

            prefill_episode_runtime_index(tracked)
