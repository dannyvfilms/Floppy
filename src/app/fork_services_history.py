# FORK: shared history-record deletion logic used by the web history page
# (history_views.delete_history_record) and the REST API, so both surfaces
# delete plays and invalidate caches identically.
import logging

from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist

from app import cache_utils, history_cache, statistics_cache
from app.models import BasicMedia, MediaTypes

logger = logging.getLogger(__name__)


class HistoryRecordNotFoundError(LookupError):
    """The history record does not exist or belongs to another user."""


class HistoryDeletionError(RuntimeError):
    """The record was found but could not be deleted."""


def delete_history_record_core(user, media_type, history_id):
    """Delete a consumption-history record for the user.

    For play-per-instance types (movie, episode, game, boardgame) the media
    instance itself is deleted; other types delete only the historical
    record. History and statistics caches are invalidated either way.
    """
    media_type_lower = media_type.lower()
    historical_model = apps.get_model(
        app_label="app",
        model_name=f"historical{media_type_lower}",
    )

    try:
        history_record = historical_model.objects.get(
            history_id=history_id,
            history_user=user,
        )
    except historical_model.DoesNotExist:
        try:
            history_record = historical_model.objects.get(
                history_id=history_id,
                history_user__isnull=True,
            )
            BasicMedia.objects.get_media(
                user,
                media_type_lower,
                history_record.id,
            )
        except ObjectDoesNotExist as exc:
            msg = f"History record {history_id} not found for user {user}"
            raise HistoryRecordNotFoundError(msg) from exc

    media_instance_id = history_record.id
    start_date = getattr(history_record, "start_date", None)
    end_date = getattr(history_record, "end_date", None)
    created_at = getattr(history_record, "created_at", None)

    instance_delete_types = {
        MediaTypes.MOVIE.value,
        MediaTypes.EPISODE.value,
        MediaTypes.GAME.value,
        MediaTypes.BOARDGAME.value,
    }
    delete_instance = media_type_lower in instance_delete_types

    logger.info(
        "Attempting to delete history record %s (media_type=%s, "
        "media_instance_id=%s, user=%s)",
        str(history_id),
        media_type_lower,
        media_instance_id,
        str(user),
    )

    if delete_instance:
        try:
            media_instance = BasicMedia.objects.get_media(
                user,
                media_type_lower,
                media_instance_id,
            )
        except (ObjectDoesNotExist, ValueError, TypeError) as exc:
            logger.exception(
                "Media instance %s not found for history record %s "
                "(media_type=%s, user=%s)",
                str(media_instance_id),
                str(history_id),
                media_type_lower,
                str(user),
            )
            msg = "Record not found"
            raise HistoryRecordNotFoundError(msg) from exc

        related_season = (
            getattr(media_instance, "related_season", None)
            if media_type_lower == MediaTypes.EPISODE.value
            else None
        )

        try:
            media_instance.delete()
        except Exception as exc:
            logger.exception(
                "Failed to delete media instance %s for history record %s",
                str(media_instance_id),
                str(history_id),
            )
            msg = "Failed to delete record"
            raise HistoryDeletionError(msg) from exc

        if related_season:
            related_season._sync_status_after_episode_change()
            cache_utils.clear_time_left_cache_for_user(related_season.user_id)
            cache_utils.clear_media_list_cache_for_user(related_season.user_id)

        try:
            model = apps.get_model(app_label="app", model_name=media_type_lower)
            verification_query = model.objects.filter(id=media_instance_id)
            if media_type_lower == MediaTypes.EPISODE.value:
                verification_query = verification_query.filter(
                    related_season__user=user,
                )
            else:
                verification_query = verification_query.filter(user=user)

            if verification_query.exists():
                logger.error(
                    "Deletion verification failed: media instance %s still "
                    "exists after delete() call",
                    str(media_instance_id),
                )
                msg = "Deletion failed"
                raise HistoryDeletionError(msg)  # noqa: TRY301
        except HistoryDeletionError:
            raise
        except Exception as exc:
            logger.warning(
                "Could not verify deletion of media instance %s: %s",
                str(media_instance_id),
                str(exc),
            )
    else:
        try:
            history_record.delete()
        except Exception as exc:
            logger.exception(
                "Failed to delete history record %s",
                str(history_id),
            )
            msg = "Failed to delete record"
            raise HistoryDeletionError(msg) from exc

        try:
            verification_query = historical_model.objects.filter(
                history_id=history_id,
            )
            if verification_query.exists():
                logger.error(
                    "Deletion verification failed: history record %s still "
                    "exists after delete() call",
                    str(history_id),
                )
                msg = "Deletion failed"
                raise HistoryDeletionError(msg)  # noqa: TRY301
        except HistoryDeletionError:
            raise
        except Exception as exc:
            logger.warning(
                "Could not verify deletion of history record %s: %s",
                str(history_id),
                str(exc),
            )

    logger.info(
        "Successfully deleted %s %s (media_type=%s, media_instance_id=%s)",
        "media instance" if delete_instance else "history record",
        str(history_id),
        media_type_lower,
        media_instance_id,
    )

    logging_styles = ("sessions", "repeats")
    if media_type_lower in ("game", "boardgame"):
        start_dt = start_date or end_date
        end_dt = end_date or start_date
        history_day_keys = history_cache.history_day_keys_for_range(
            start_dt,
            end_dt,
        )
    else:
        activity_dt = end_date or start_date or created_at
        history_day_key = history_cache.history_day_key(activity_dt)
        history_day_keys = [history_day_key] if history_day_key else []

    history_cache.invalidate_history_days(
        user.id,
        day_keys=history_day_keys,
        logging_styles=logging_styles,
        reason="history_delete",
        force=True,
    )
    statistics_cache.invalidate_statistics_days(
        user.id,
        day_values=history_day_keys,
        reason="history_delete",
    )
    statistics_cache.schedule_all_ranges_refresh(user.id)
