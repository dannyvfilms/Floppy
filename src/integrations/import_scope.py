"""Cooperative tracking-write fence for destructive durable import scopes."""

from django.db import models
from django.db.models import Q

TRACKING_MODELS = frozenset({"tv", "season", "episode", "movie", "movieplay", "anime"})


class ImportOverwriteConflictError(Exception):
    """A replacement is active; callers may retry after it finishes."""


def _runs():
    from integrations import import_progress
    from integrations.models import ImportRun

    return ImportRun.objects.filter(
        source="trakt",
        status__in=[ImportRun.Status.RUNNING, ImportRun.Status.FAILED],
        prepared_state__mode="overwrite",
    ).exclude(phase__in=["", "complete", "expired"]).exclude(
        pk=import_progress.get_current_import_run_id(),
    ).values("user_id", "prepared_state")


def _scopes(run, kind):
    scopes = run["prepared_state"].get("overwrite_scopes", {})
    kinds = ["movie" if kind == "movieplay" else kind]
    if kind in {"season", "episode"}:
        kinds.append("tv")
    if kind == "episode":
        kinds.append("season")
    for scope_kind in kinds:
        yield from scopes.get(scope_kind, {}).items()


def guard_queryset(queryset):
    """Cover bulk update/delete writers that bypass model signals."""
    kind = queryset.model._meta.model_name
    if queryset.model._meta.app_label != "app" or kind not in TRACKING_MODELS:
        return
    owner = "related_season__user_id" if kind == "episode" else "movie__user_id" if kind == "movieplay" else "user_id"
    item = "movie__item" if kind == "movieplay" else "item"
    for run in _runs():
        scope = Q(pk__in=[])
        for source, identities in _scopes(run, kind):
            scope |= Q(**{f"{item}__source": source, f"{item}__media_id__in": identities})
        if queryset.filter(scope, **{owner: run["user_id"]}).exists():
            message = "This title is being replaced by an import. Retry after the import finishes or resumes."
            raise ImportOverwriteConflictError(message)


def guard_instances(rows):
    """Cover save/bulk-create writers, including newly introduced children."""
    if not rows:
        return
    kind = rows[0]._meta.model_name
    if rows[0]._meta.app_label != "app" or kind not in TRACKING_MODELS:
        return
    runs = list(_runs())
    if not runs:
        return
    # Resolve identities only when there is an actual destructive fence.
    for row in rows:
        identity = row.movie if kind == "movieplay" else row
        user_id = row.related_season.user_id if kind == "episode" else identity.user_id
        for run in runs:
            if run["user_id"] == user_id and any(
                identity.item.source == source and identity.item.media_id in identities
                for source, identities in _scopes(run, kind)
            ):
                message = "This title is being replaced by an import. Retry after the import finishes or resumes."
                raise ImportOverwriteConflictError(message)


class ImportScopedQuerySet(models.QuerySet):
    """Keep ORM bulk writers inside the same overwrite conflict contract."""

    def update(self, **kwargs):
        """Reject changes within an active replacement scope."""
        guard_queryset(self)
        from app.services.sync_lock import tracking_mutation

        with tracking_mutation(self):
            return super().update(**kwargs)

    def delete(self):
        """Reject deletion within an active replacement scope."""
        guard_queryset(self)
        from app.services.sync_lock import tracking_mutation

        with tracking_mutation(self, publish_quiet=True):
            return super().delete()

    def bulk_create(self, objs, *args, **kwargs):
        """Reject new tracking rows within an active replacement scope."""
        objs = list(objs)
        guard_instances(objs)
        from app.services.sync_lock import tracking_mutation

        with tracking_mutation(self, instances=objs):
            return super().bulk_create(objs, *args, **kwargs)

    def bulk_update(self, objs, fields, *args, **kwargs):
        """Check existing scope as well as reassigned item/owner identities."""
        objs = list(objs)
        guard_instances(objs)
        guard_queryset(self.filter(pk__in=[row.pk for row in objs]))
        from app.services.sync_lock import tracking_mutation

        with tracking_mutation(self.filter(pk__in=[row.pk for row in objs]), instances=objs):
            return super().bulk_update(objs, fields, *args, **kwargs)


ImportScopedManager = models.Manager.from_queryset(ImportScopedQuerySet)
