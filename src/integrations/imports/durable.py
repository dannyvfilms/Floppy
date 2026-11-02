"""Durable prepared Trakt writes, bounded transactions and commit receipts."""

import contextlib
import hashlib
import json
import logging
import time
import uuid
from collections import Counter
from datetime import date, timedelta

from django.apps import apps
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, connection, connections, transaction
from django.db.models import F, Q
from django.db.models.deletion import Collector
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from app.models import Item, Status
from app.services.watch_state import PROJECTED_MEDIA_TYPES
from app.signals import importer_replacing_rows
from integrations import import_progress
from integrations.models import (
    ImportChunkReceipt,
    ImportOverwriteTarget,
    ImportRun,
    PreparedImportEntry,
)

from . import helpers

logger = logging.getLogger(__name__)
FORMAT_VERSION = 3
LEASE_SECONDS = 600
HEARTBEAT_SECONDS = 60
FAST_CHUNKS_TO_GROW = 8


@contextlib.contextmanager
def measure_transaction(metrics):
    """Observe SQL and actual commit before cache/broker on-commit callbacks."""
    database = connections[connection.alias]
    original_commit = database.commit
    started = time.perf_counter()
    first_write = None
    first_write_end = None
    committed_at = None
    statements = Counter()

    def observe(execute, sql, params, many, context):
        nonlocal first_write, first_write_end
        verb = sql.lstrip().split(None, 1)[0].lower()
        statements[verb] += 1
        is_first_write = verb in {"insert", "update", "delete"} and first_write is None
        if is_first_write:
            first_write = time.perf_counter()
        result = execute(sql, params, many, context)
        if is_first_write:
            first_write_end = time.perf_counter()
        return result

    def commit():
        nonlocal committed_at
        result = original_commit()
        committed_at = time.perf_counter()
        return result

    database.commit = commit
    try:
        with database.execute_wrapper(observe):
            yield
    finally:
        database.commit = original_commit
        ended = time.perf_counter()
        committed = committed_at or ended
        write = first_write or started
        acquired = first_write_end or write
        metrics.update({
            "statements": dict(statements),
            "total_statements": dict(Counter(metrics.get("total_statements", {})) + statements),
            "attempt_wall_ms": (ended - started) * 1000,
            "wait_before_first_write_ms": (write - started) * 1000,
            "first_write_call_ms": (acquired - write) * 1000,
            "first_write_to_commit_ms": (committed - write) * 1000,
            "after_first_write_ms": (committed - acquired) * 1000,
            "commit_observed": committed_at is not None,
        })


def digest(value):
    """Hash canonical prepared data without logging its contents."""
    encoded = json.dumps(value, cls=DjangoJSONEncoder, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def serialize(instance):
    """Persist concrete field values and unsaved parent catalogue identities."""
    fields = {field.attname: getattr(instance, field.attname) for field in instance._meta.concrete_fields}
    # DjangoJSONEncoder truncates datetime microseconds to milliseconds. Exact
    # watch/history timestamps are part of replay identity, so retain ISO precision.
    fields = {name: value.isoformat() if isinstance(value, date) else value for name, value in fields.items()}
    parents = {}
    for name in ("related_tv", "related_season"):
        parent = instance._state.fields_cache.get(name)
        if parent is not None:
            parents[name] = {"model": parent._meta.label_lower, "item_id": parent.item_id,
                             "tv_item_id": parent.related_tv.item_id if name == "related_season" else None}
    history = {name: getattr(instance, name) for name in ("_history_date", "_change_reason") if hasattr(instance, name)}
    history = {name: value.isoformat() if isinstance(value, date) else value for name, value in history.items()}
    return {"fields": fields, "parents": parents, "history": history}


def claim(run):
    """Acquire a fenced lease using a conditional write, including on SQLite."""
    owner = uuid.uuid4().hex
    now = timezone.now()
    try:
        claimed = ImportRun.objects.filter(pk=run.pk, cancel_requested=False).filter(
            Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now),
        ).update(lease_owner=owner, lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
                 fence=F("fence") + 1, status=ImportRun.Status.RUNNING, finished_at=None,
                 phase=run.phase or "preparing", terminal_error={})
    except IntegrityError as error:
        message = "Another Trakt import for this user is still active."
        raise helpers.MediaImportError(message) from error
    if not claimed:
        message = "This import already has an active worker."
        raise helpers.MediaImportError(message)
    run.refresh_from_db()
    return owner


def renew(run, owner):
    """First write acquires the writer before any transactional reads."""
    updated = ImportRun.objects.filter(pk=run.pk, fence=run.fence, lease_owner=owner,
                                      cancel_requested=False).update(
        lease_expires_at=timezone.now() + timedelta(seconds=LEASE_SECONDS),
    )
    if not updated:
        message = "Import cancelled or superseded; committed chunks remain recoverable."
        raise helpers.MediaImportError(message)


def release(run, owner):
    """Leave prepared input and receipts for a later retry."""
    ImportRun.objects.filter(pk=run.pk, fence=run.fence, lease_owner=owner).update(
        lease_owner="", lease_expires_at=None,
    )


def publish_pending(run):
    """Replay receipt outbox work outside every media transaction, at least once."""
    from app import history_cache, statistics_cache
    from events.tasks import reload_calendar

    pending = run.chunk_receipts.filter(publication_pending=True)
    last = pending.order_by("-pk").values_list("pk", flat=True).first()
    if last is None:
        return False
    owner = uuid.uuid4().hex
    now = timezone.now()
    claimed = ImportRun.objects.filter(pk=run.pk).filter(
        Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now),
    ).update(lease_owner=owner, lease_expires_at=now + timedelta(seconds=LEASE_SECONDS))
    if not claimed:
        return False
    try:
        history_cache.invalidate_history_cache(run.user_id, force=True)
        statistics_cache.invalidate_all_statistics_days(run.user_id, reason="media_import")
        reload_calendar.delay()
        pending.filter(pk__lte=last).update(publication_pending=False)
        return True
    finally:
        ImportRun.objects.filter(pk=run.pk, lease_owner=owner).update(lease_owner="", lease_expires_at=None)


def recover_outboxes():
    """Bound recovery to ten inactive runs per existing cleanup invocation."""
    now = timezone.now()
    runs = ImportRun.objects.filter(chunk_receipts__publication_pending=True).filter(
        Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now),
    ).distinct().order_by("pk")[:10]
    for run in runs:
        try:
            publish_pending(run)
        except Exception as error:
            logger.warning("import_outbox_retry error=%s", type(error).__name__)
    # Failed prefixes remain recoverable. Only successful/cancelled terminal
    # staging expires, after its outbox and lease are clear; audit receipts stay.
    terminal = ImportRun.objects.filter(
        status__in=[ImportRun.Status.COMPLETED, ImportRun.Status.CANCELLED],
        finished_at__lt=now - timedelta(days=7),
    ).filter(Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now)).exclude(
        chunk_receipts__publication_pending=True,
    ).exclude(phase="expired").order_by("pk").first()
    if terminal is not None:
        owner = uuid.uuid4().hex
        claimed = ImportRun.objects.filter(
            pk=terminal.pk, status=terminal.status,
        ).filter(Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now)).update(
            lease_owner=owner, lease_expires_at=now + timedelta(seconds=LEASE_SECONDS), fence=F("fence") + 1,
        )
        if not claimed:
            return
        try:
            for model, relation in ((PreparedImportEntry, "prepared_entries"), (ImportOverwriteTarget, "overwrite_targets")):
                with transaction.atomic():
                    # Acquire the writer before the bounded read, and verify
                    # cleanup still owns the terminal run after a manual retry.
                    owned = ImportRun.objects.filter(pk=terminal.pk, status=terminal.status, lease_owner=owner).update(
                        lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
                    )
                    if not owned:
                        return
                    ids = list(getattr(terminal, relation).values_list("pk", flat=True)[:500])
                    model.objects.filter(pk__in=ids).delete()
            with transaction.atomic():
                owned = ImportRun.objects.filter(pk=terminal.pk, status=terminal.status, lease_owner=owner).update(
                    lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
                )
                if owned and not terminal.prepared_entries.exists() and not terminal.overwrite_targets.exists():
                    ImportRun.objects.filter(pk=terminal.pk).update(phase="expired", prepared_state={}, prepared_digest="")
        finally:
            ImportRun.objects.filter(pk=terminal.pk, lease_owner=owner).update(lease_owner="", lease_expires_at=None)


def stage(run, owner, bulk_media, updates, state, *, append=False, operation_prefix=""):
    """Seal all original eligibility/mapping/order decisions before media writes."""
    limit = max(1, min(500, getattr(settings, "TRAKT_IMPORT_CHUNK_ROWS", 100)))
    # Incomplete staging has made no tracking-row commits. Discard it in bounded
    # writes; after sealing, staging is immutable and never fetched remotely.
    base = run.prepared_state.get("entries", 0) if append else 0
    while True:
        ids = list(run.prepared_entries.filter(ordinal__gte=base).values_list("pk", flat=True)[:limit])
        if not ids:
            break
        with transaction.atomic():
            renew(run, owner)
            PreparedImportEntry.objects.filter(pk__in=ids).delete()
    ordinal = base
    buffer = []
    root = hashlib.sha256()
    staging_bytes = run.prepared_state.get("staging_bytes", 0) if append else 0
    normalized = set()
    if append:
        normalized.update(run.prepared_entries.filter(
            ordinal__lt=base, payload__normalization_first=True,
        ).values_list("model_label", "payload__fields__item_id"))

    def flush():
        with transaction.atomic():
            renew(run, owner)
            PreparedImportEntry.objects.bulk_create(buffer, batch_size=limit)
        buffer.clear()

    operations = [(kind, "create", helpers._deduplicate_unique_user_item_rows(apps.get_model("app", kind), rows))
                  for kind, rows in bulk_media.items()]
    for kind, _operation, rows in operations:
        if kind == "season":
            canonical = {}
            retained = []
            for row in rows:
                key = (row.user_id, row.related_tv.item_id, row.item_id)
                if key in canonical:
                    helpers._merge_duplicate_media_row(canonical[key], row)
                else:
                    canonical[key] = row
                    retained.append(row)
            rows[:] = retained
    operations.extend((kind, "update", rows) for kind, rows in updates)
    ordered = helpers._ordered_media_types(bulk_media)
    operations.sort(key=lambda entry: (entry[1] != "create", ordered.index(entry[0]) if entry[0] in ordered else len(ordered)))
    for _kind, operation, rows in operations:
        for row in rows:
            payload = serialize(row)
            identity = (row._meta.label_lower, row.item_id)
            normalizable = (_kind not in {"tv", "season"} and operation == "create"
                            and operation_prefix in {"", "backfill_"} and row.status == Status.COMPLETED.value)
            payload["normalization_first"] = normalizable and identity not in normalized
            if payload["normalization_first"]:
                normalized.add(identity)
            staging_bytes += len(json.dumps(payload, cls=DjangoJSONEncoder).encode())
            if staging_bytes > getattr(settings, "TRAKT_IMPORT_STAGING_BYTES", 512 * 1024 * 1024):
                message = "Prepared import exceeds the configured staging quota; no unsealed entries were committed to the library."
                raise helpers.MediaImportError(message)
            prepared_operation = operation_prefix + operation
            entry_digest = digest([row._meta.label_lower, prepared_operation, payload])
            root.update(entry_digest.encode())
            buffer.append(PreparedImportEntry(run=run, ordinal=ordinal, model_label=row._meta.label_lower,
                                             operation=prepared_operation, payload=payload, digest=entry_digest))
            ordinal += 1
            if len(buffer) >= limit:
                flush()
    if buffer:
        flush()
    state = (run.prepared_state if append else {}) | state | {"version": FORMAT_VERSION, "entries": ordinal, "staging_bytes": staging_bytes}
    state["segments"] = (run.prepared_state.get("segments", []) if append else []) + [{"start": base, "end": ordinal, "digest": root.hexdigest()}]
    with transaction.atomic():
        renew(run, owner)
        ImportRun.objects.filter(pk=run.pk).update(phase="prepared", prepared_state=state,
                                                 prepared_digest=digest(state), commit_cursor=run.commit_cursor if append else 0,
                                                 chunk_rows=limit)
    run.refresh_from_db()


def verify_prepared(run):
    """Verify a retained sealed manifest without hydrating its watch payloads."""
    if digest(run.prepared_state) != run.prepared_digest:
        message = "Prepared import manifest changed."
        raise helpers.MediaImportError(message)
    for segment in run.prepared_state["segments"]:
        root = hashlib.sha256()
        entries = run.prepared_entries.filter(ordinal__gte=segment["start"], ordinal__lt=segment["end"])
        count = 0
        for entry_digest in entries.values_list("digest", flat=True).iterator(chunk_size=500):
            root.update(entry_digest.encode())
            count += 1
        if count != segment["end"] - segment["start"] or root.hexdigest() != segment["digest"]:
            message = "Prepared import segment changed."
            raise helpers.MediaImportError(message)


def hydrate(entries, user):
    """Rebuild only one bounded batch; use the original reference fix-up hooks."""
    item_ids = {entry.payload["fields"]["item_id"] for entry in entries}
    for entry in entries:
        item_ids.update(parent["item_id"] for parent in entry.payload["parents"].values())
    items = Item.objects.in_bulk(item_ids)
    parent_ids = {}
    for entry in entries:
        for parent in entry.payload["parents"].values():
            parent_ids.setdefault(parent["model"], set()).add(parent["item_id"])
    parents = {}
    for label, ids in parent_ids.items():
        parent_model = apps.get_model(label)
        queryset = getattr(parent_model, "all_objects", parent_model.objects).filter(user=user, item_id__in=ids).select_related("item")
        if parent_model._meta.model_name == "season":
            queryset = queryset.select_related("related_tv__item")
        for parent in queryset:
            parents[label, parent.item_id, parent.related_tv.item_id if parent_model._meta.model_name == "season" else None] = parent
    rows = []
    for entry in entries:
        model = apps.get_model(entry.model_label)
        fields = {field.attname: field.to_python(entry.payload["fields"][field.attname])
                  for field in model._meta.concrete_fields}
        row = model(**fields)
        for name, value in entry.payload.get("history", {}).items():
            setattr(row, name, parse_datetime(value) if name == "_history_date" and isinstance(value, str) else value)
        row.item = items[row.item_id]
        for name, parent in entry.payload["parents"].items():
            parent_model = apps.get_model(parent["model"])
            # The helper resolves this catalogue identity to the persisted row.
            resolved = parents.get((parent["model"], parent["item_id"], parent.get("tv_item_id")))
            setattr(row, name, resolved or parent_model(item=items[parent["item_id"]], user=user))
        rows.append(row)
    return rows


def snapshot_overwrite(run, owner, scopes, user):
    """Retain original deletion identities, including dependent tracking rows."""
    # A pre-seal retry may have left only a partial snapshot. None of these
    # targets have been deleted, so rebuild rather than combine two baselines.
    while True:
        ids = list(run.overwrite_targets.values_list("pk", flat=True)[:run.chunk_rows])
        if not ids:
            break
        with transaction.atomic():
            renew(run, owner)
            ImportOverwriteTarget.objects.filter(pk__in=ids).delete()
    collector = Collector(using=connection.alias)
    for kind, sources in scopes.items():
        model = apps.get_model("app", kind)
        for source, identities in sources.items():
            if identities:
                collector.collect(model.objects.filter(user=user, item__source=source, item__media_id__in=identities))
    collector.sort()
    ordered = [(model, list(rows)) for model, rows in collector.data.items()]
    # Fast-delete children have no model hooks; retain their PKs too rather than
    # letting a later parent deletion sweep in newly created children.
    ordered = [(query.model, list(query)) for query in collector.fast_deletes] + ordered
    # simple-history cascades are signal-driven, not FK cascades visible to
    # Collector. Snapshot and delete them first so a parent with many status
    # revisions cannot hide an unbounded history delete in its final chunk.
    histories = []
    for model, rows in ordered:
        history = getattr(model, "history", None)
        if history is None:
            continue
        for start in range(0, len(rows), run.chunk_rows):
            identities = [row.pk for row in rows[start:start + run.chunk_rows]]
            records = list(history.filter(**{f"{model._meta.pk.name}__in": identities}))
            if records:
                histories.append((history.model, records))
    ordered = histories + ordered
    ordinal = 0
    batch = []
    for model, rows in ordered:
        for row in rows:
            fields = serialize(row)["fields"]
            batch.append(ImportOverwriteTarget(run=run, ordinal=ordinal, model_label=model._meta.label_lower,
                                               original_pk=row.pk, fingerprint=digest(fields)))
            ordinal += 1
            if len(batch) >= run.chunk_rows:
                with transaction.atomic():
                    renew(run, owner)
                    ImportOverwriteTarget.objects.bulk_create(batch, ignore_conflicts=True)
                batch.clear()
    if batch:
        with transaction.atomic():
            renew(run, owner)
            ImportOverwriteTarget.objects.bulk_create(batch, ignore_conflicts=True)


def delete_overwrite(run, owner):
    """Delete only snapshot rows; refuse changed rows or new cascade children."""
    while True:
        targets = list(run.overwrite_targets.filter(deleted=False).order_by("ordinal")[:run.chunk_rows])
        if not targets:
            return
        label = targets[0].model_label
        targets = [target for target in targets if target.model_label == label]
        model = apps.get_model(label)
        identities = [target.original_pk for target in targets]
        chunk_digest = digest([[target.original_pk, target.fingerprint] for target in targets])
        metrics = {}
        started = time.perf_counter()

        def commit(targets=targets, model=model, identities=identities, metrics=metrics, chunk_digest=chunk_digest):
            with measure_transaction(metrics), transaction.atomic():
                renew(run, owner)
                rows = list(model.objects.filter(pk__in=identities))
                metrics["rows_deleted"] = len(rows)
                fingerprints = {target.original_pk: target.fingerprint for target in targets}
                for row in rows:
                    fields = serialize(row)["fields"]
                    if digest(fields) != fingerprints[row.pk]:
                        message = "Overwrite target changed after preparation; import stopped without deleting the changed row."
                        raise helpers.MediaImportError(message)
                history = getattr(model, "history", None)
                if history is not None and history.filter(**{f"{model._meta.pk.name}__in": identities}).exists():
                    message = "Overwrite scope received new history records; import stopped without deleting them."
                    raise helpers.MediaImportError(message)
                collector = Collector(using=connection.alias)
                collector.collect(rows)
                related = [(kind, list(objects)) for kind, objects in collector.data.items()]
                related += [(query.model, list(query)) for query in collector.fast_deletes]
                for kind, objects in related:
                    pks = {row.pk for row in objects}
                    known = set(run.overwrite_targets.filter(model_label=kind._meta.label_lower,
                                                             original_pk__in=pks).values_list("original_pk", flat=True))
                    if pks - known:
                        message = "Overwrite scope received new dependent rows; import stopped without deleting them."
                        raise helpers.MediaImportError(message)
                with importer_replacing_rows():
                    model.objects.filter(pk__in=identities).delete()
                ImportOverwriteTarget.objects.filter(pk__in=[target.pk for target in targets]).update(deleted=True)
                ImportChunkReceipt.objects.create(run=run, phase="delete", start=targets[0].ordinal,
                                                 end=targets[-1].ordinal + 1, digest=chunk_digest, fence=run.fence)
                ImportRun.objects.filter(pk=run.pk).update(phase="delete")

        helpers.retry_on_lock(commit)
        metrics.update({"chunk_rows": len(targets),
                        "wall_ms": (time.perf_counter() - started) * 1000})
        run.chunk_receipts.filter(phase="delete", start=targets[0].ordinal).update(metrics=metrics)


def persist(run, owner, user):
    """Commit data, history, normalization, dirty tokens and cursor atomically."""
    from simple_history.utils import bulk_create_with_history, bulk_update_with_history

    from app import statistics_sync
    from app.models import StatisticsDirtyDay

    warnings = []
    fast_chunks = 0
    while run.commit_cursor < run.prepared_state["entries"]:
        candidates = list(run.prepared_entries.filter(ordinal__gte=run.commit_cursor)[:run.chunk_rows])
        # Never mix model types/operations in a persistence transaction.
        first = candidates[0]
        entries = []
        for entry in candidates:
            if (entry.model_label, entry.operation) != (first.model_label, first.operation):
                break
            if digest([entry.model_label, entry.operation, entry.payload]) != entry.digest:
                message = "Prepared import identity mismatch."
                raise helpers.MediaImportError(message)
            entries.append(entry)
        chunk_digest = digest([entry.digest for entry in entries])
        started = time.perf_counter()
        metrics = {}
        attempts = 0

        def commit(entries=entries, first=first, chunk_digest=chunk_digest, metrics=metrics):
            nonlocal attempts
            attempts += 1
            with measure_transaction(metrics), transaction.atomic():
                renew(run, owner)
                existing = run.chunk_receipts.filter(phase="persist", start=entries[0].ordinal).first()
                if existing:
                    if existing.digest != chunk_digest:
                        message = "Committed import chunk identity mismatch."
                        raise helpers.MediaImportError(message)
                    return
                rows = hydrate(entries, user)
                from app.services.completion import normalize_completed_entries

                normalize_rows = [row for entry, row in zip(entries, rows, strict=True)
                                  if entry.payload.get("normalization_first", True)]
                if first.operation == "create":
                    warnings.extend(helpers.bulk_create_media({rows[0]._meta.model_name: rows}, user, backfill_completed=False, prepared=True, normalize=False))
                    normalize_completed_entries(normalize_rows)
                elif first.operation.endswith("create"):
                    bulk_create_with_history(rows, rows[0].__class__, batch_size=run.chunk_rows)
                    if first.operation == "backfill_create":
                        normalize_completed_entries(normalize_rows)
                    # bulk_create fires no save signal, so project here as
                    # bulk_create_media does for the main manifest.
                    if rows[0]._meta.model_name in PROJECTED_MEDIA_TYPES:
                        helpers.project_imported_watch_state(user, {row.item_id for row in rows})
                else:
                    bulk_update_with_history(rows, rows[0].__class__, fields=["status"],
                                             default_change_reason=f"Trakt import ({run.prepared_state['mode']})" if first.operation == "update" else None)
                if any(row.pk is None for row in rows):
                    message = "Prepared watch could not be persisted; chunk was rolled back."
                    raise helpers.MediaImportError(message)
                days = {timezone.localdate(row.end_date or row.start_date) for row in rows
                        if getattr(row, "end_date", None) or getattr(row, "start_date", None)}
                StatisticsDirtyDay.objects.bulk_create(
                    [StatisticsDirtyDay(user=user, day=day, token=uuid.uuid4(), marked_at=timezone.now()) for day in days],
                    update_conflicts=True, unique_fields=["user", "day"], update_fields=["token", "marked_at"],
                )
                for entry, row in zip(entries, rows, strict=True):
                    entry.persisted_pk = row.pk
                PreparedImportEntry.objects.bulk_update(entries, ["persisted_pk"], batch_size=run.chunk_rows)
                ImportChunkReceipt.objects.create(run=run, start=entries[0].ordinal, end=entries[-1].ordinal + 1,
                                                 digest=chunk_digest, fence=run.fence,
                                                 rows_persisted=sum(row.pk is not None for row in rows))
                ImportRun.objects.filter(pk=run.pk).update(commit_cursor=entries[-1].ordinal + 1, phase="persist")

        helpers.retry_on_lock(commit)
        metrics.update({"chunk_rows": len(entries), "rows_persisted": len(entries),
                        "wall_ms": (time.perf_counter() - started) * 1000, "attempts": attempts})
        run.chunk_receipts.filter(phase="persist", start=entries[0].ordinal).update(metrics=metrics)
        statistics_sync.mark_aggregate(user.pk, reason="import_chunk")
        logger.debug("import_chunk rows=%s wall_ms=%.1f write_ms=%.1f", len(entries), metrics["wall_ms"], metrics["first_write_to_commit_ms"])
        run.refresh_from_db()
        target_ms = getattr(settings, "TRAKT_IMPORT_CHUNK_TARGET_MS", 100)
        if metrics["after_first_write_ms"] > target_ms and run.chunk_rows > 1:
            run.chunk_rows = max(1, run.chunk_rows // 2)
            fast_chunks = 0
            ImportRun.objects.filter(pk=run.pk).update(chunk_rows=run.chunk_rows)
        elif metrics["after_first_write_ms"] < target_ms / 2 and len(entries) == run.chunk_rows:
            fast_chunks += 1
            ceiling = max(1, min(500, getattr(settings, "TRAKT_IMPORT_CHUNK_ROWS", 100)))
            if fast_chunks >= FAST_CHUNKS_TO_GROW and run.chunk_rows < ceiling:
                run.chunk_rows = min(ceiling, run.chunk_rows * 2)
                fast_chunks = 0
                ImportRun.objects.filter(pk=run.pk).update(chunk_rows=run.chunk_rows)
        else:
            fast_chunks = 0
    return warnings


def parent_rows(run, label, user, *, created_only=False):
    """Restore the original touched-parent order without loading watch graphs."""
    entries = list(run.prepared_entries.filter(model_label=label, operation__in=["create"] if created_only else ["create", "update"]))
    rows = hydrate(entries, user)
    for entry, row in zip(entries, rows, strict=True):
        row.pk = entry.persisted_pk or row.pk
    return rows


def run_import(importer, *, prepare_input=True):
    """Persist a sealed import or resume its committed prefix on the same run."""
    import requests

    from app.providers import services

    from .trakt import _phase

    run_id = import_progress.get_current_import_run_id()
    owned = run_id is None
    run = (ImportRun.objects.create(user=importer.user, source="trakt") if owned else
           ImportRun.objects.get(pk=run_id, user=importer.user))
    if run.source != "trakt":
        message = "Import checkpoint belongs to another source."
        raise helpers.MediaImportError(message)
    owner = claim(run)
    last_heartbeat = time.monotonic()

    def heartbeat():
        nonlocal last_heartbeat
        now = time.monotonic()
        if now - last_heartbeat >= HEARTBEAT_SECONDS:
            renew(run, owner)
            last_heartbeat = now

    try:
        with import_progress.tracking(run.task_id, run.pk, heartbeat=heartbeat):
            if not run.prepared_digest:
                if prepare_input:
                    importer._validate_username()
                    importer.process_dropped()
                    for stage_name in ("history", "watchlist", "ratings", "notes", "comments", "collection"):
                        renew(run, owner)
                        with _phase(stage_name, importer.username):
                            getattr(importer, f"process_{stage_name}")()
                scopes = {kind: {source: list(identities) for source, identities in sources.items()}
                          for kind, sources in importer.to_delete.items()}
                with transaction.atomic():
                    renew(run, owner)
                    run.prepared_state = run.prepared_state | {"mode": importer.mode, "overwrite_scopes": scopes}
                    ImportRun.objects.filter(pk=run.pk).update(prepared_state=run.prepared_state)
                snapshot_overwrite(run, owner, scopes, importer.user)
                deleted_tvs = list(run.overwrite_targets.filter(model_label="app.tv").values_list("original_pk", flat=True))
                deleted_seasons = list(run.overwrite_targets.filter(model_label="app.season").values_list("original_pk", flat=True))
                mapping_parents = helpers.prepare_bulk_media(importer.bulk_media, importer.user, exclude_tv_ids=deleted_tvs,
                                                            exclude_season_ids=deleted_seasons, prepare_only=True)
                automatic_parent_ids = {id(parent) for parent in mapping_parents}
                state = run.prepared_state | {
                    "mode": importer.mode, "username": importer.username,
                    "counts": {kind: sum(id(row) not in automatic_parent_ids for row in rows)
                               for kind, rows in importer.bulk_media.items()},
                    "warnings": importer.warnings,
                    "completion_dates": {key: value.isoformat() if isinstance(value, date) else value
                                         for key, value in importer.tv_completion_dates.items()},
                    "backfill_sealed": False, "fanout_sealed": False,
                }
                stage(run, owner, importer.bulk_media,
                      [("season", importer.completed_seasons), ("tv", importer.completed_tvs), ("tv", importer.dropped_tvs)], state)
            elif run.prepared_state.get("version") != FORMAT_VERSION:
                message = "This import checkpoint uses an unsupported format."
                raise helpers.MediaImportError(message)  # noqa: TRY301 -- fenced failure is recorded below
            elif (run.prepared_state["mode"], run.prepared_state["username"]) != (importer.mode, importer.username):
                message = "Import options do not match the sealed checkpoint."
                raise helpers.MediaImportError(message)  # noqa: TRY301 -- fenced failure is recorded below
            else:
                verify_prepared(run)
            if run.phase != "complete":
                delete_overwrite(run, owner)
                with _phase("save media", importer.username):
                    persist(run, owner, importer.user)
                if not run.prepared_state.get("backfill_sealed"):
                    seasons = [row for row in parent_rows(run, "app.season", importer.user, created_only=True) if row.status == Status.COMPLETED]
                    episodes, _warnings = helpers._backfill_completed_season_episodes(seasons, prepare_only=True)
                    stage(run, owner, {"episode": episodes}, [], {"backfill_sealed": True}, append=True, operation_prefix="backfill_")
                    persist(run, owner, importer.user)
                if not run.prepared_state.get("fanout_sealed"):
                    with _phase("finish shows", importer.username):
                        touched = {tv.pk: tv for tv in parent_rows(run, "app.tv", importer.user) if tv.pk}
                        creates = {"season": [], "episode": []}
                        updates = []
                        for tv in touched.values():
                            if tv.status == Status.COMPLETED:
                                pending_date = run.prepared_state["completion_dates"].get(str(tv.item.media_id))
                                if pending_date is not None:
                                    tv._pending_end_date = parse_datetime(pending_date) if isinstance(pending_date, str) else pending_date
                                try:
                                    plan = tv._completed(prepare_only=True)
                                except (services.ProviderAPIError, requests.exceptions.RequestException, KeyError, TypeError, ValueError):
                                    logger.warning("Trakt completion metadata unavailable; retaining the original incomplete fan-out behavior")
                                    continue
                                if plan is not None:
                                    additions, changed = plan
                                    for kind, rows in additions.items():
                                        creates[kind].extend(rows)
                                    updates.extend(changed)
                            elif tv.status == Status.DROPPED:
                                dropped = list(tv.seasons.filter(status=Status.IN_PROGRESS))
                                for season in dropped:
                                    season.status = Status.DROPPED
                                updates.extend(dropped)
                        stage(run, owner, creates, [("season", updates)], {"fanout_sealed": True}, append=True, operation_prefix="fanout_")
                        persist(run, owner, importer.user)
                with transaction.atomic():
                    renew(run, owner)
                    ImportRun.objects.filter(pk=run.pk).update(phase="complete")
            state = run.prepared_state
            importer.warnings = state["warnings"]
            if owned:
                completed = ImportRun.objects.filter(pk=run.pk, status=ImportRun.Status.RUNNING, cancel_requested=False).update(
                    status=ImportRun.Status.COMPLETED, finished_at=timezone.now(),
                )
                if not completed:
                    message = "Import cancelled; committed chunks remain recoverable."
                    raise helpers.MediaImportError(message)  # noqa: TRY301 -- record the fenced terminal outcome below
            return state["counts"], "\n".join(dict.fromkeys(state["warnings"]))
    except BaseException as error:
        if not run.prepared_digest:
            # Before sealing no tracking writes have occurred. A failed
            # preparation must not fence an unrelated future import forever.
            run.prepared_state = run.prepared_state | {"overwrite_scopes": {}}
            ImportRun.objects.filter(pk=run.pk, fence=run.fence, lease_owner=owner).update(prepared_state=run.prepared_state)
        current = ImportRun.objects.filter(pk=run.pk).values("phase", "commit_cursor", "cancel_requested").get()
        ImportRun.objects.filter(pk=run.pk, fence=run.fence, lease_owner=owner, status=ImportRun.Status.RUNNING).update(
            status=ImportRun.Status.CANCELLED if current["cancel_requested"] else ImportRun.Status.FAILED,
            finished_at=timezone.now(),
            terminal_error={"type": type(error).__name__, "phase": current["phase"], "committed_entries": current["commit_cursor"]},
        )
        raise
    finally:
        release(run, owner)
