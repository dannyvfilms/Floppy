# ruff: noqa: S608
# Every statement here is assembled from table names that go through
# connection.ops.quote_name() and fixed SQL fragments; every value, the user id
# included, is bound through params.
"""Read-only checks of the facts Floppy's data should always satisfy.

Pass 10 of the data integrity review found three kinds of wrong data in a real
library with a handful of SQL counts. This module is those counts, kept so that
anyone can run them: ``manage.py check_data_invariants`` prints them, and a later
health page or ``floppy_preflight`` can call the same functions.

Every check is one aggregate query (plus, when examples are asked for, one
bounded query for up to ``examples`` ids). Nothing is loaded table by table into
Python, nothing is written, and no transaction is opened, so a check never takes
a write lock and is safe against a running instance. The SQL is plain enough to
run on SQLite and PostgreSQL; the one place they differ, the distance between
two timestamps, is chosen per vendor.

Each result says whether a non-zero count is ``always a fault`` or something to
``review``. Several rows for one user and one item are repeats by design
(``Movie``, ``Game``, ``Book``, ``Podcast`` and others store each viewing as a
row) and are not reported. A show stored in two library buckets is legitimate
for grouped anime only while both buckets are filled; a copy with an empty
bucket is always a fault.

Output carries ids, media types and table names only, never titles, usernames
or tokens. There is no repair mode: the fixes belong to the commands and
migrations that own each kind of data.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import timedelta

from django.apps import apps
from django.db import connection
from django.db.models import Q
from django.utils import timezone

FAULT = "fault"
REVIEW = "review"

KIND_LABELS = {FAULT: "always a fault", REVIEW: "review"}

DEFAULT_EXAMPLES = 10

# Two plays of the same episode on the same tracker that finished this close
# together are candidate duplicates. This is the rule the review used; prompt 67
# owns a sharper one.
NEAR_DUPLICATE_SECONDS = 300

STALE_DELIVERY_AGE = timedelta(hours=1)
STALE_IMPORT_AGE = timedelta(days=1)


@dataclass
class InvariantResult:
    """One check's answer: what it counted and, on request, which ids."""

    name: str
    kind: str
    count: int
    description: str
    example_label: str
    examples: list = field(default_factory=list)
    breakdown: dict = field(default_factory=dict)
    approximate: bool = False
    seconds: float = 0.0

    @property
    def failed(self) -> bool:
        """Return whether this is a fault that was found."""
        return self.kind == FAULT and self.count > 0

    def as_dict(self) -> dict:
        """Return the JSON form of this result."""
        return {
            "name": self.name,
            "kind": self.kind,
            "count": self.count,
            "description": self.description,
            "approximate": self.approximate,
            "breakdown": dict(sorted(self.breakdown.items())),
            "example_label": self.example_label,
            "examples": self.examples,
            "seconds": round(self.seconds, 3),
        }


# --------------------------------------------------------------------------
# SQL helpers


def _q(name: str) -> str:
    return connection.ops.quote_name(name)


def _table(label: str) -> str:
    return _q(apps.get_model(label)._meta.db_table)


def _fetchall(sql: str, params=()) -> list:
    with connection.cursor() as cursor:
        cursor.execute(sql, list(params))
        return cursor.fetchall()


def _scalar(sql: str, params=()) -> int:
    rows = _fetchall(sql, params)
    return int(rows[0][0] or 0) if rows else 0


def tracker_models() -> list:
    """Return every concrete tracker model with the media type it holds.

    A tracker is a row a user owns that points at one ``Item``: the concrete
    subclasses of ``app.models.Media``. Each one's model name is its media type.
    """
    from app.models import Media, MediaTypes

    return sorted(
        (
            (model._meta.model_name, model)
            for model in apps.get_models()
            if issubclass(model, Media) and model._meta.model_name in MediaTypes.values
        ),
        key=lambda pair: pair[0],
    )


def _user_items_sql(user_id) -> tuple[str, list]:
    """Return a subquery of item ids a user tracks or has played."""
    parts = []
    params = []
    for _media_type, model in tracker_models():
        parts.append(
            f"SELECT item_id FROM {_q(model._meta.db_table)} WHERE user_id = %s"
        )
        params.append(user_id)
    parts.append(
        f"SELECT e.item_id FROM {_table('app.Episode')} e "
        f"JOIN {_table('app.Season')} s ON s.id = e.related_season_id "
        "WHERE s.user_id = %s AND e.item_id IS NOT NULL"
    )
    params.append(user_id)
    return " UNION ".join(parts), params


def _seconds_apart(left: str, right: str) -> str:
    """Return SQL for the absolute distance in seconds between two datetimes."""
    if connection.vendor == "sqlite":
        return f"ABS(JULIANDAY({left}) - JULIANDAY({right})) * 86400"
    if connection.vendor == "postgresql":
        return f"ABS(EXTRACT(EPOCH FROM ({left} - {right})))"
    msg = f"check_data_invariants does not support {connection.vendor}"
    raise NotImplementedError(msg)


def _run(builder, *, user_id=None, examples=0) -> InvariantResult:
    started = time.perf_counter()
    result = builder(user_id=user_id, examples=examples)
    result.seconds = time.perf_counter() - started
    return result


# --------------------------------------------------------------------------
# 1. Items without a library bucket


# Every item has one of three shapes, which the item check constraints enforce:
# no season and no episode (shows, movies and every other top-level type), a
# season without an episode, or both. Each shape has its own partial unique
# index, so scanning shape by shape reads those indexes rather than the item
# table, which on a large library is the biggest table in the database.
_ITEM_SHAPES = (
    (
        "season_number IS NULL AND episode_number IS NULL",
        "media_id, source, media_type",
    ),
    (
        "season_number IS NOT NULL AND episode_number IS NULL",
        "media_id, source, media_type, season_number",
    ),
    (
        "season_number IS NOT NULL AND episode_number IS NOT NULL",
        "media_id, source, media_type, season_number, episode_number",
    ),
)


def items_without_bucket(*, user_id=None, examples=0) -> InvariantResult:
    """Count items whose ``library_media_type`` is empty, by media type."""
    item = _table("app.Item")
    selects, params = [], []
    for shape, _identity in _ITEM_SHAPES:
        where = f"{shape} AND library_media_type = %s"
        params.append("")
        if user_id is not None:
            sub, sub_params = _user_items_sql(user_id)
            where += f" AND id IN ({sub})"
            params += sub_params
        selects.append(f"SELECT id, media_type FROM {item} WHERE {where}")
    rows_sql = " UNION ALL ".join(selects)
    rows = _fetchall(
        f"SELECT media_type, COUNT(*) FROM ({rows_sql}) g GROUP BY media_type",
        params,
    )
    breakdown = {media_type: int(count) for media_type, count in rows}
    ids = []
    if examples and breakdown:
        ids = [
            row[0]
            for row in _fetchall(
                f"SELECT id FROM ({rows_sql}) g ORDER BY id DESC LIMIT %s",
                [*params, examples],
            )
        ]
    return InvariantResult(
        name="items_without_bucket",
        kind=FAULT,
        count=sum(breakdown.values()),
        description="Items stored with an empty library bucket",
        example_label="item ids, newest first",
        examples=ids,
        breakdown=breakdown,
    )


# --------------------------------------------------------------------------
# 2. One identity stored as several items


def _identity_copies(*, empty_bucket: bool, user_id, examples) -> InvariantResult:
    item = _table("app.Item")
    selects, params = [], []
    for shape, identity in _ITEM_SHAPES:
        having = (
            "COUNT(*) > 1 AND "
            "MAX(CASE WHEN library_media_type = %s THEN 1 ELSE 0 END) = %s"
        )
        params += ["", 1 if empty_bucket else 0]
        if user_id is not None:
            sub, sub_params = _user_items_sql(user_id)
            having += f" AND MAX(CASE WHEN id IN ({sub}) THEN 1 ELSE 0 END) = 1"
            params += sub_params
        selects.append(
            f"SELECT media_type AS media_type, MIN(id) AS first_id FROM {item} "
            f"WHERE {shape} GROUP BY {identity} HAVING {having}"
        )
    groups = " UNION ALL ".join(selects)
    rows = _fetchall(
        f"SELECT media_type, COUNT(*) FROM ({groups}) g GROUP BY media_type", params
    )
    breakdown = {media_type: int(count) for media_type, count in rows}
    ids = []
    if examples and breakdown:
        ids = [
            row[0]
            for row in _fetchall(
                f"SELECT first_id FROM ({groups}) g ORDER BY first_id LIMIT %s",
                [*params, examples],
            )
        ]
    if empty_bucket:
        return InvariantResult(
            name="identity_copies_with_empty_bucket",
            kind=FAULT,
            count=sum(breakdown.values()),
            description=(
                "Titles, seasons or episodes stored as several items where one "
                "copy has an empty bucket"
            ),
            example_label="lowest item id of each identity",
            examples=ids,
            breakdown=breakdown,
        )
    return InvariantResult(
        name="identity_copies_in_filled_buckets",
        kind=REVIEW,
        count=sum(breakdown.values()),
        description=(
            "Titles, seasons or episodes stored in several filled buckets "
            "(expected for grouped anime)"
        ),
        example_label="lowest item id of each identity",
        examples=ids,
        breakdown=breakdown,
    )


def identity_copies_with_empty_bucket(*, user_id=None, examples=0):
    """Count identities stored more than once where one copy has no bucket."""
    return _identity_copies(empty_bucket=True, user_id=user_id, examples=examples)


def identity_copies_in_filled_buckets(*, user_id=None, examples=0):
    """Count identities stored in more than one filled bucket."""
    return _identity_copies(empty_bucket=False, user_id=user_id, examples=examples)


# --------------------------------------------------------------------------
# 3. Plays of one episode split across item copies


def plays_split_across_copies(*, user_id=None, examples=0) -> InvariantResult:
    """Count episodes whose plays, for one user, point at different items."""
    episode, season, item = (
        _table("app.Episode"),
        _table("app.Season"),
        _table("app.Item"),
    )
    where = "e.rating_only = %s"
    params = [False]
    if user_id is not None:
        where += " AND s.user_id = %s"
        params.append(user_id)
    groups = (
        f"SELECT MIN(e.id) AS first_id FROM {episode} e "
        f"JOIN {season} s ON s.id = e.related_season_id "
        f"JOIN {item} i ON i.id = e.item_id "
        f"WHERE {where} "
        "GROUP BY s.user_id, i.media_id, i.source, i.media_type, "
        "i.season_number, i.episode_number "
        "HAVING COUNT(DISTINCT e.item_id) > 1"
    )
    count = _scalar(f"SELECT COUNT(*) FROM ({groups}) g", params)
    ids = []
    if examples and count:
        ids = [
            row[0]
            for row in _fetchall(
                f"SELECT first_id FROM ({groups}) g ORDER BY first_id LIMIT %s",
                [*params, examples],
            )
        ]
    return InvariantResult(
        name="plays_split_across_copies",
        kind=FAULT,
        count=count,
        description="Episodes one user played whose plays point at different items",
        example_label="lowest episode play id of each episode",
        examples=ids,
    )


# --------------------------------------------------------------------------
# 4. One user tracking several copies of one title


def _tracked_copies(*, empty_bucket: bool, user_id, examples) -> InvariantResult:
    item = _table("app.Item")
    selects = []
    params = []
    for media_type, model in tracker_models():
        # Parameters in statement order: tracker name, user, HAVING values.
        where = ""
        params.append(media_type)
        if user_id is not None:
            where = "WHERE t.user_id = %s "
            params.append(user_id)
        params += ["", 1 if empty_bucket else 0]
        selects.append(
            f"SELECT CAST(%s AS VARCHAR(20)) AS tracker, MIN(t.id) AS first_id "
            f"FROM {_q(model._meta.db_table)} t JOIN {item} i ON i.id = t.item_id "
            f"{where}"
            "GROUP BY t.user_id, i.media_id, i.source, i.media_type, "
            "i.season_number, i.episode_number "
            "HAVING COUNT(DISTINCT t.item_id) > 1 AND "
            "MAX(CASE WHEN i.library_media_type = %s THEN 1 ELSE 0 END) = %s"
        )
    groups = " UNION ALL ".join(selects)
    rows = _fetchall(
        f"SELECT tracker, COUNT(*) FROM ({groups}) g GROUP BY tracker", params
    )
    breakdown = {tracker: int(count) for tracker, count in rows}
    ids = []
    if examples and breakdown:
        ids = [
            f"{tracker}:{first_id}"
            for tracker, first_id in _fetchall(
                f"SELECT tracker, first_id FROM ({groups}) g "
                "ORDER BY tracker, first_id LIMIT %s",
                [*params, examples],
            )
        ]
    if empty_bucket:
        return InvariantResult(
            name="tracked_copies_with_empty_bucket",
            kind=FAULT,
            count=sum(breakdown.values()),
            description=(
                "Users tracking two items of one title where one copy has an "
                "empty bucket"
            ),
            example_label="tracker table:lowest tracker id",
            examples=ids,
            breakdown=breakdown,
        )
    return InvariantResult(
        name="tracked_copies_in_filled_buckets",
        kind=REVIEW,
        count=sum(breakdown.values()),
        description=(
            "Users tracking one title in two filled buckets (expected only for "
            "grouped anime)"
        ),
        example_label="tracker table:lowest tracker id",
        examples=ids,
        breakdown=breakdown,
    )


def tracked_copies_with_empty_bucket(*, user_id=None, examples=0):
    """Count users tracking two copies of a title, one without a bucket."""
    return _tracked_copies(empty_bucket=True, user_id=user_id, examples=examples)


def tracked_copies_in_filled_buckets(*, user_id=None, examples=0):
    """Count users tracking one title in two filled buckets."""
    return _tracked_copies(empty_bucket=False, user_id=user_id, examples=examples)


# --------------------------------------------------------------------------
# 5. Tracked and tombstoned at once


def tracked_and_tombstoned(*, user_id=None, examples=0) -> InvariantResult:
    """Count tombstones whose title the same user still tracks, per tracker."""
    item, deleted = _table("app.Item"), _table("app.DeletedMedia")
    selects = []
    params = []
    for media_type, model in tracker_models():
        where = ""
        params.append(media_type)
        if user_id is not None:
            where = "WHERE d.user_id = %s"
            params.append(user_id)
        selects.append(
            f"SELECT DISTINCT CAST(%s AS VARCHAR(20)) AS tracker, d.id AS tombstone_id "
            f"FROM {deleted} d "
            f"JOIN {item} i ON i.media_type = d.media_type "
            "AND i.source = d.source AND i.media_id = d.media_id "
            f"JOIN {_q(model._meta.db_table)} t "
            "ON t.item_id = i.id AND t.user_id = d.user_id "
            f"{where}"
        )
    rows_sql = " UNION ALL ".join(selects)
    rows = _fetchall(
        f"SELECT tracker, COUNT(*) FROM ({rows_sql}) g GROUP BY tracker", params
    )
    breakdown = {tracker: int(count) for tracker, count in rows}
    ids = []
    if examples and breakdown:
        ids = [
            row[0]
            for row in _fetchall(
                f"SELECT DISTINCT tombstone_id FROM ({rows_sql}) g "
                "ORDER BY tombstone_id LIMIT %s",
                [*params, examples],
            )
        ]
    return InvariantResult(
        name="tracked_and_tombstoned",
        kind=FAULT,
        count=sum(breakdown.values()),
        description="Titles marked deleted that the same user still tracks",
        example_label="deleted media ids",
        examples=ids,
        breakdown=breakdown,
    )


# --------------------------------------------------------------------------
# 6. Structure


def _structure(name, description, example_label, sql, params, examples):
    count = _scalar(f"SELECT COUNT(*) FROM ({sql}) g", params)
    ids = []
    if examples and count:
        ids = [
            row[0]
            for row in _fetchall(
                f"SELECT id FROM ({sql}) g ORDER BY id LIMIT %s", [*params, examples]
            )
        ]
    return InvariantResult(
        name=name,
        kind=FAULT,
        count=count,
        description=description,
        example_label=example_label,
        examples=ids,
    )


def season_user_differs_from_show(*, user_id=None, examples=0):
    """Count seasons whose user is not their show's user."""
    where, params = "s.user_id <> t.user_id", []
    if user_id is not None:
        where += " AND (s.user_id = %s OR t.user_id = %s)"
        params += [user_id, user_id]
    sql = (
        f"SELECT s.id AS id FROM {_table('app.Season')} s "
        f"JOIN {_table('app.TV')} t ON t.id = s.related_tv_id WHERE {where}"
    )
    return _structure(
        "season_user_differs_from_show",
        "Seasons owned by a different user than their show",
        "season tracker ids",
        sql,
        params,
        examples,
    )


def season_item_not_its_shows(*, user_id=None, examples=0):
    """Count seasons whose item belongs to a different title than their show's."""
    item = _table("app.Item")
    where = "(si.media_id <> ti.media_id OR si.source <> ti.source)"
    params = []
    if user_id is not None:
        where += " AND s.user_id = %s"
        params.append(user_id)
    sql = (
        f"SELECT s.id AS id FROM {_table('app.Season')} s "
        f"JOIN {_table('app.TV')} t ON t.id = s.related_tv_id "
        f"JOIN {item} si ON si.id = s.item_id JOIN {item} ti ON ti.id = t.item_id "
        f"WHERE {where}"
    )
    return _structure(
        "season_item_not_its_shows",
        "Seasons whose item is another title than their show's",
        "season tracker ids",
        sql,
        params,
        examples,
    )


def play_item_outside_its_season(*, user_id=None, examples=0):
    """Count episode plays whose item is not an episode of their season."""
    item = _table("app.Item")
    where = (
        "(ei.media_id <> si.media_id OR ei.source <> si.source "
        "OR ei.season_number <> si.season_number)"
    )
    params = []
    if user_id is not None:
        where += " AND s.user_id = %s"
        params.append(user_id)
    sql = (
        f"SELECT e.id AS id FROM {_table('app.Episode')} e "
        f"JOIN {_table('app.Season')} s ON s.id = e.related_season_id "
        f"JOIN {item} ei ON ei.id = e.item_id JOIN {item} si ON si.id = s.item_id "
        f"WHERE {where}"
    )
    return _structure(
        "play_item_outside_its_season",
        "Episode plays whose item is not an episode of their season",
        "episode play ids",
        sql,
        params,
        examples,
    )


def play_without_item(*, user_id=None, examples=0):
    """Count episode plays with no item."""
    where, params = "e.item_id IS NULL", []
    join = ""
    if user_id is not None:
        join = f"JOIN {_table('app.Season')} s ON s.id = e.related_season_id "
        where += " AND s.user_id = %s"
        params.append(user_id)
    sql = f"SELECT e.id AS id FROM {_table('app.Episode')} e {join}WHERE {where}"
    return _structure(
        "play_without_item",
        "Episode plays that point at no item",
        "episode play ids",
        sql,
        params,
        examples,
    )


def tracker_item_wrong_type(*, user_id=None, examples=0) -> InvariantResult:
    """Count trackers whose item has another media type than their table's."""
    from app.models import MediaTypes

    item = _table("app.Item")
    tables = [
        (media_type, _q(model._meta.db_table)) for media_type, model in tracker_models()
    ]
    tables.append((MediaTypes.EPISODE.value, _table("app.Episode")))
    selects, params = [], []
    for media_type, table in tables:
        join = ""
        where = "i.media_type <> %s"
        params += [media_type, media_type]
        if user_id is not None:
            if media_type == MediaTypes.EPISODE.value:
                join = f"JOIN {_table('app.Season')} s ON s.id = t.related_season_id "
                where += " AND s.user_id = %s"
            else:
                where += " AND t.user_id = %s"
            params.append(user_id)
        selects.append(
            f"SELECT CAST(%s AS VARCHAR(20)) AS tracker, t.id AS tracker_id FROM {table} t "
            f"JOIN {item} i ON i.id = t.item_id {join}WHERE {where}"
        )
    rows_sql = " UNION ALL ".join(selects)
    rows = _fetchall(
        f"SELECT tracker, COUNT(*) FROM ({rows_sql}) g GROUP BY tracker", params
    )
    breakdown = {tracker: int(count) for tracker, count in rows}
    ids = []
    if examples and breakdown:
        ids = [
            f"{tracker}:{tracker_id}"
            for tracker, tracker_id in _fetchall(
                f"SELECT tracker, tracker_id FROM ({rows_sql}) g "
                "ORDER BY tracker, tracker_id LIMIT %s",
                [*params, examples],
            )
        ]
    return InvariantResult(
        name="tracker_item_wrong_type",
        kind=FAULT,
        count=sum(breakdown.values()),
        description="Trackers whose item is a different media type than their table",
        example_label="tracker table:tracker id",
        examples=ids,
        breakdown=breakdown,
    )


# --------------------------------------------------------------------------
# 7. Candidate duplicate plays


def candidate_duplicate_plays(*, user_id=None, examples=0) -> InvariantResult:
    """Count pairs of plays of one episode that finished within five minutes.

    Approximate: two genuine viewings can finish this close together, and a
    duplicate recorded hours apart is missed. Archived and rating-only rows are
    left out.
    """
    episode = _table("app.Episode")
    join, params = "", []
    apart = _seconds_apart("a.end_date", "b.end_date")
    where = (
        "a.rating_only = %s AND b.rating_only = %s "
        "AND a.order_archived = %s AND b.order_archived = %s "
        "AND a.end_date IS NOT NULL AND b.end_date IS NOT NULL "
        f"AND {apart} <= %s"
    )
    params = [False, False, False, False, NEAR_DUPLICATE_SECONDS]
    if user_id is not None:
        join = f"JOIN {_table('app.Season')} s ON s.id = a.related_season_id "
        where += " AND s.user_id = %s"
        params.append(user_id)
    pairs = (
        f"SELECT b.id AS id, CASE WHEN a.end_date = b.end_date THEN 1 ELSE 0 END "
        f"AS exact FROM {episode} a JOIN {episode} b "
        "ON b.related_season_id = a.related_season_id "
        "AND b.item_id = a.item_id AND b.id > a.id "
        f"{join}WHERE {where}"
    )
    rows = _fetchall(f"SELECT COUNT(*), SUM(exact) FROM ({pairs}) g", params)
    total, exact = (int(rows[0][0] or 0), int(rows[0][1] or 0)) if rows else (0, 0)
    ids = []
    if examples and total:
        ids = [
            row[0]
            for row in _fetchall(
                f"SELECT DISTINCT id FROM ({pairs}) g ORDER BY id LIMIT %s",
                [*params, examples],
            )
        ]
    return InvariantResult(
        name="candidate_duplicate_plays",
        kind=REVIEW,
        count=total,
        description=(
            "Pairs of plays of one episode on one tracker that finished within "
            "five minutes of each other"
        ),
        example_label="later episode play id of each pair",
        examples=ids,
        breakdown={"same end time": exact, "within five minutes": total - exact},
        approximate=True,
    )


# --------------------------------------------------------------------------
# 8. Work that stopped moving


def stale_outbound_deliveries(*, user_id=None, examples=0) -> InvariantResult:
    """Count outbound writes still in flight more than an hour after starting."""
    from integrations.models import OutboundDeliveryStatus, OutboundStateDelivery

    cutoff = timezone.now() - STALE_DELIVERY_AGE
    queryset = OutboundStateDelivery._base_manager.filter(
        Q(claimed_at__lt=cutoff) | Q(claimed_at__isnull=True, updated_at__lt=cutoff),
        status=OutboundDeliveryStatus.IN_FLIGHT.value,
    )
    if user_id is not None:
        queryset = queryset.filter(user_id=user_id)
    count = queryset.count()
    ids = (
        list(queryset.order_by("pk").values_list("pk", flat=True)[:examples])
        if examples and count
        else []
    )
    return InvariantResult(
        name="stale_outbound_deliveries",
        kind=REVIEW,
        count=count,
        description="Writes to a connected service still in flight after an hour",
        example_label="outbound delivery ids",
        examples=ids,
    )


def stale_import_runs(*, user_id=None, examples=0) -> InvariantResult:
    """Count import runs still running a day after their lease or start."""
    from integrations.models import ImportRun

    cutoff = timezone.now() - STALE_IMPORT_AGE
    queryset = ImportRun._base_manager.filter(
        Q(lease_expires_at__lt=cutoff)
        | Q(lease_expires_at__isnull=True, started_at__lt=cutoff),
        status=ImportRun.Status.RUNNING.value,
    )
    if user_id is not None:
        queryset = queryset.filter(user_id=user_id)
    count = queryset.count()
    ids = (
        list(queryset.order_by("pk").values_list("pk", flat=True)[:examples])
        if examples and count
        else []
    )
    return InvariantResult(
        name="stale_import_runs",
        kind=REVIEW,
        count=count,
        description=(
            "Imports still marked running a day after their lease ran out, or a "
            "day after starting when they hold none"
        ),
        example_label="import run ids",
        examples=ids,
    )


# --------------------------------------------------------------------------

CHECKS = (
    items_without_bucket,
    identity_copies_with_empty_bucket,
    identity_copies_in_filled_buckets,
    plays_split_across_copies,
    tracked_copies_with_empty_bucket,
    tracked_copies_in_filled_buckets,
    tracked_and_tombstoned,
    season_user_differs_from_show,
    season_item_not_its_shows,
    play_item_outside_its_season,
    play_without_item,
    tracker_item_wrong_type,
    candidate_duplicate_plays,
    stale_outbound_deliveries,
    stale_import_runs,
)


def run_checks(*, user_id=None, examples=0) -> list[InvariantResult]:
    """Run every check and return the results in a fixed order."""
    return [_run(check, user_id=user_id, examples=examples) for check in CHECKS]
