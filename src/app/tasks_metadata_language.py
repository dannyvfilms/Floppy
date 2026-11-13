"""Bounded upgrade repair for metadata saved before language preferences worked."""

import logging
import math
from datetime import timedelta

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import CharField, Exists, OuterRef, Q, Value
from django.db.models.functions import Cast, Coalesce, Concat, NullIf
from django.utils import timezone

from app import reconcile_state
from app.interactive_requests import interactive_request_active
from app.log_safety import exception_summary
from app.models import (
    BackfillReconcileState,
    Item,
    MediaTypes,
    MetadataProviderPreference,
    Sources,
)
from app.providers import services
from app.tasks_backfill_state import is_terminal_backfill_error

logger = logging.getLogger(__name__)
REPAIR_PREFIX = "metadata_language:"
REPAIR_VERSION = 1
REPAIR_BATCH_DELAY_SECONDS = 60


def _schedule_repair(state_id, *, countdown):
    """Publish one continuation for the state that won the reconcile lock."""

    def schedule_repair():
        from app.tasks import backfill_item_metadata_task

        # A newer preference deletes the old state, including queued callbacks.
        if not BackfillReconcileState.objects.filter(pk=state_id).exists():
            return
        try:
            backfill_item_metadata_task.apply_async(
                kwargs={"batch_size": 25, "game_length_batch_size": 0},
                countdown=countdown,
                priority=getattr(settings, "CELERY_TASK_PRIORITY_BACKGROUND", 9),
            )
        except Exception as error:
            # The durable pending state is still picked up by the periodic pass.
            logger.warning(
                "Could not schedule metadata language repair: %s",
                exception_summary(error),
            )

    transaction.on_commit(schedule_repair)


def reset_metadata_language_repair(user_id):
    """Revisit a library after its global or per-item language changes."""
    BackfillReconcileState.objects.filter(
        key__startswith=f"{REPAIR_PREFIX}{user_id}:",
    ).delete()
    user = get_user_model().objects.filter(pk=user_id).only("metadata_language").first()
    if user is None:
        return
    language = user.metadata_language or settings.TMDB_LANG
    state = reconcile_state.get_state(
        f"{REPAIR_PREFIX}{user_id}:{language}", REPAIR_VERSION
    )
    _schedule_repair(state.pk, countdown=10)


def _shared_item_language(item, user_id):
    """Resolve one language only when all tracking owners agree."""
    if item.source != Sources.TMDB.value or item.manual_metadata:
        return None
    model = apps.get_model("app", item.media_type)
    user_field = (
        "related_season__user_id"
        if item.media_type == MediaTypes.EPISODE.value
        else "user_id"
    )
    owner_ids = model.objects.filter(item=item).values_list(user_field, flat=True)
    owners = list(get_user_model().objects.filter(pk__in=owner_ids))
    if user_id not in {owner.pk for owner in owners}:
        return None
    preferences = {
        preference.user_id: preference
        for preference in MetadataProviderPreference.objects.filter(item=item)
    }
    languages = set()
    for owner in owners:
        preference = preferences.get(owner.pk)
        if preference and preference.provider == Sources.MANUAL.value:
            return None
        languages.add(
            (preference.language if preference else "")
            or owner.metadata_language
            or settings.TMDB_LANG,
        )
    return languages.pop() if len(languages) == 1 else None


def repair_metadata_language_batch(batch_size=10):
    """Repair one due user's bounded page within the existing backfill budget.

    Durable cursor/completion state survives Redis eviction. Failed fetches do
    not advance the cursor, and normal reconcile backoff bounds retries. This
    is an upgrade sweep; new entries use language-aware tracking hydration.
    """
    result = {"attempted": 0, "success": 0, "errors": 0}
    batch_size = max(int(batch_size), 0)
    if not batch_size:
        return result

    user_model = get_user_model()
    users = user_model.objects.filter(is_active=True)
    # Skip completed/backing-off users in SQL so one finished library cannot
    # starve other users, without reading every user's Item table each tick.
    users = users.annotate(
        _repair_key=Concat(
            Value(REPAIR_PREFIX),
            Cast("pk", output_field=CharField()),
            Value(":"),
            Coalesce(NullIf("metadata_language", Value("")), Value(settings.TMDB_LANG)),
        ),
    )
    if settings.TMDB_LANG.lower().startswith("en"):
        overrides = MetadataProviderPreference.objects.filter(
            user_id=OuterRef("pk"),
        ).exclude(language="")
        requested_repairs = BackfillReconcileState.objects.filter(
            key=OuterRef("_repair_key"),
        )
        users = users.annotate(
            _has_override=Exists(overrides),
            _requested_repair=Exists(requested_repairs),
        ).filter(
            ~Q(metadata_language="") | Q(_has_override=True) | Q(_requested_repair=True)
        )
    blocked = BackfillReconcileState.objects.filter(
        key=OuterRef("_repair_key"),
        strategy_version=REPAIR_VERSION,
    ).filter(Q(completed_at__isnull=False) | Q(next_run_after__gt=timezone.now()))
    user = users.annotate(_blocked=Exists(blocked)).filter(_blocked=False).first()
    if user is None:
        return result

    key = user._repair_key
    state = reconcile_state.should_run(key, REPAIR_VERSION)
    if state is None or not reconcile_state.acquire(key, state):
        return result

    cursor = state.last_cursor_item_id
    changed_history_owner_ids = set()
    try:
        if interactive_request_active():
            BackfillReconcileState.objects.filter(pk=state.pk).update(
                next_run_after=timezone.now()
                + timedelta(seconds=REPAIR_BATCH_DELAY_SECONDS),
            )
            _schedule_repair(state.pk, countdown=REPAIR_BATCH_DELAY_SECONDS)
            return result
        items = list(
            Item.objects.filter(
                Q(movie__user=user)
                | Q(tv__user=user)
                | Q(season__user=user)
                | Q(episode__related_season__user=user),
                source=Sources.TMDB.value,
                media_type__in=(
                    MediaTypes.MOVIE.value,
                    MediaTypes.TV.value,
                    MediaTypes.SEASON.value,
                    MediaTypes.EPISODE.value,
                ),
                id__gt=cursor,
            )
            .distinct()
            .order_by("id")[:batch_size],
        )
        if not items:
            reconcile_state.mark_complete(key, REPAIR_VERSION)
            return result

        for item in items:
            if interactive_request_active():
                break
            language = _shared_item_language(item, user.pk)
            if language is None:
                cursor = item.pk
                continue
            result["attempted"] += 1
            try:
                metadata = services.get_media_metadata(
                    item.media_type,
                    item.media_id,
                    item.source,
                    season_numbers=(
                        [item.season_number]
                        if item.media_type in (MediaTypes.SEASON, MediaTypes.EPISODE)
                        else None
                    ),
                    episode_number=item.episode_number,
                    language=language,
                    user=user,
                )
                if not isinstance(metadata, dict) or not metadata:
                    result["errors"] += 1
                    logger.warning(
                        "No metadata returned for language repair item_id=%s", item.pk
                    )
                    break
                item.refresh_from_db()
                # A preference reset deletes this state. Never let an old
                # in-flight fetch overwrite that newer choice or custom edits.
                if not BackfillReconcileState.objects.filter(pk=state.pk).exists():
                    return result
                if _shared_item_language(item, user.pk) != language:
                    return result
                title_fields = (
                    Item.title_fields_from_episode_metadata(metadata, item.title)
                    if item.media_type == MediaTypes.EPISODE.value
                    else Item.title_fields_from_metadata(metadata, item.title)
                )
                if metadata.get("synopsis"):
                    title_fields["synopsis"] = metadata["synopsis"]
                changed = []
                for name, value in title_fields.items():
                    if value and getattr(item, name) != value:
                        setattr(item, name, value)
                        changed.append(name)
                if changed:
                    if {"title", "original_title", "localized_title"}.intersection(
                        changed
                    ):
                        model = apps.get_model("app", item.media_type)
                        user_field = (
                            "related_season__user_id"
                            if item.media_type == MediaTypes.EPISODE.value
                            else "user_id"
                        )
                        changed_history_owner_ids.update(
                            model.objects.filter(item=item).values_list(
                                user_field, flat=True
                            ),
                        )
                    item.save(update_fields=changed)
                result["success"] += 1
                cursor = item.pk
            except Exception as error:
                result["errors"] += 1
                logger.warning(
                    "metadata_language_repair_failed item_id=%s language=%s error=%s",
                    item.pk,
                    language,
                    exception_summary(error),
                )
                if is_terminal_backfill_error(error):
                    cursor = item.pk
                    continue
                break
        reconcile_state.mark_progress(
            key,
            REPAIR_VERSION,
            cursor=cursor,
            enqueued=0 if result["errors"] else cursor > state.last_cursor_item_id,
        )
        pending = BackfillReconcileState.objects.filter(pk=state.pk)
        if not result["errors"]:
            # Cursor progress includes intentionally skipped shared/custom items.
            # Continue the bounded sweep promptly instead of waiting for beat.
            pending.update(
                next_run_after=timezone.now()
                + timedelta(seconds=REPAIR_BATCH_DELAY_SECONDS),
            )
        next_run = pending.values_list("next_run_after", flat=True).first()
        if next_run:
            _schedule_repair(
                state.pk,
                countdown=max(
                    1, math.ceil((next_run - timezone.now()).total_seconds())
                ),
            )
        return result
    finally:
        try:
            # Only stored title fields appear in History. Flush earlier writes
            # even if a later fetch fails or a preference reset ends this page.
            from app import history_cache

            for owner_id in sorted(changed_history_owner_ids):
                try:
                    history_cache.invalidate_history_cache(
                        owner_id,
                        reason="metadata_language_repair",
                    )
                    history_cache.schedule_history_refresh(owner_id)
                except Exception as error:
                    logger.warning(
                        "Could not refresh history after language repair: %s",
                        exception_summary(error),
                    )
        finally:
            reconcile_state.release(key)
