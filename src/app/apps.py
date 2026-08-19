import logging
import os
import sys
from importlib import import_module

from django.apps import AppConfig
from django.conf import settings
from django.core.cache import cache

from app.log_safety import exception_summary

logger = logging.getLogger(__name__)

# Five whole-library sweeps used to be enqueued at startup within 30 seconds of
# each other, so a restart put the container's heaviest work on the queue exactly
# when it was still warming up. Spacing them lets the web tier become responsive
# first, and beat picks up anything skipped soon enough now that the reconcilers
# gate on durable state (issue #521).
STARTUP_SWEEP_COUNTDOWNS = {
    "imdb_person": 60,
    "genre": 180,
    "trakt_popularity": 300,
    "igdb_ratings": 420,
    "provider": 540,
}


def _is_celery_worker_process() -> bool:
    """Return whether the current process is a Celery worker or beat.

    Real invocations split "celery" and "worker"/"beat" across separate argv
    tokens (e.g. ["celery", "-A", "config", "worker", ...]), so this checks
    across the whole argv list rather than requiring both substrings in a
    single token.
    """
    lowered_args = [arg.lower() for arg in sys.argv]
    has_celery = any("celery" in arg for arg in lowered_args)
    has_worker_or_beat = any(arg in {"worker", "beat"} for arg in lowered_args)
    return has_celery and has_worker_or_beat


def _is_runserver_parent_process() -> bool:
    """Return whether this is Django's autoreload parent for runserver."""
    return "runserver" in sys.argv and os.environ.get("RUN_MAIN") != "true"


def _is_management_command_process() -> bool:
    """Return whether this is a manage.py command other than runserver.

    One-off commands (migrate, check, shell, ...) must not enqueue startup
    tasks: publishing writes a TaskResult row mid-initialization and opens a
    Postgres connection pool inside a short-lived process (issue #341).
    Production gunicorn is launched without a manage.py token, so this never
    suppresses the preloaded master's scheduling.
    """
    if not sys.argv or not sys.argv[0].endswith("manage.py"):
        return False
    return "runserver" not in sys.argv


class AppConfig(AppConfig):
    """Default app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "app"

    def ready(self):
        """Import signals when the app is ready."""
        import_module("app.signals")
        if _is_management_command_process():
            # One-off manage.py commands (migrate, shell, check, ...) must
            # not enqueue startup tasks or consume the once-per-day startup
            # cache keys the serving process needs (issue #341).
            return
        if not settings.TESTING:
            self._repair_celery_redis_bindings()
            self._tune_redis()
        is_celery_worker = _is_celery_worker_process()
        is_runserver_parent = _is_runserver_parent_process()

        runtime_cache_available = self._add_startup_cache_key(
            "runtime_population_startup_scheduled",
        )
        discover_cache_available = self._add_startup_cache_key(
            "discover_tab_startup_scheduled",
        )
        history_cache_available = self._add_startup_cache_key(
            "history_day_coverage_startup_scheduled",
        )

        if (
            not settings.TESTING
            and not getattr(settings, "RUNTIME_POPULATION_DISABLED", False)
            and getattr(settings, "RUNTIME_POPULATION_ON_STARTUP", False)
            and not is_celery_worker
            and not is_runserver_parent
            and runtime_cache_available
        ):
            self._schedule_runtime_population()

        if (
            not settings.TESTING
            and not is_celery_worker
            and not is_runserver_parent
            and getattr(settings, "DISCOVER_WARMUP_ON_STARTUP", False)
            and discover_cache_available
        ):
            self._schedule_discover_startup_warmup()

        if (
            not settings.TESTING
            and not is_celery_worker
            and not is_runserver_parent
            and history_cache_available
        ):
            self._schedule_history_day_coverage_warmup()

        if not settings.TESTING and not is_celery_worker and not is_runserver_parent:
            self._schedule_imdb_game_person_profile_backfill()
            self._schedule_genre_backfill_reconcile()
            self._schedule_trakt_popularity_reconcile()
            self._schedule_igdb_rating_backfill_reconcile()
            self._schedule_provider_backfill_reconcile()

    def _add_startup_cache_key(
        self,
        cache_key: str,
        timeout: int = 86400,
        *,
        fail_open: bool = False,
    ) -> bool:
        """Return whether a once-per-period startup task can be scheduled."""
        try:
            return bool(cache.add(cache_key, 1, timeout=timeout))
        except Exception as error:
            logger.debug(
                "Startup cache key write failed for %s (%s). Check REDIS_CACHE_URL.",
                cache_key,
                exception_summary(error),
            )
            return fail_open

    def _repair_celery_redis_bindings(self):
        """Normalize persisted Kombu Redis bindings after separator changes."""
        try:
            from app.celery_broker import repair_celery_redis_bindings

            repair_summary = repair_celery_redis_bindings()
            if repair_summary["repaired"] or repair_summary["removed"]:
                logger.info(
                    (
                        "Normalized Kombu Redis bindings "
                        "(keys=%s members=%s repaired=%s removed=%s)"
                    ),
                    repair_summary["keys"],
                    repair_summary["members"],
                    repair_summary["repaired"],
                    repair_summary["removed"],
                )
        except Exception as error:
            logger.warning(
                "Failed to normalize Kombu Redis bindings: %s",
                exception_summary(error),
            )

    def _tune_redis(self):
        """Give Redis a memory ceiling if the operator hasn't set one.

        Guarded by the same atomic startup key the scheduling helpers use, so
        only one of the container's processes issues the CONFIG SET even though
        every one of them runs ready(). Redis restarting resets its config, so
        the key's TTL is short enough that the next process start re-applies it.
        If the cache guard raises, tuning continues because CONFIG operations
        are idempotent and the administration Redis can still be available.
        """
        if not self._add_startup_cache_key(
            "redis_tuning_applied",
            timeout=300,
            fail_open=True,
        ):
            return
        try:
            from app.redis_tuning import tune_redis

            tune_redis()
        except Exception as error:
            logger.warning(
                "Redis memory tuning failed (%s). Run manage.py tune_redis --dry-run.",
                exception_summary(error),
            )

    def _schedule_runtime_population(self):
        """Schedule runtime population task to run once on startup."""
        try:
            tasks = import_module("app.tasks")

            # Delay startup work until Django is fully initialized.
            tasks.populate_runtime_data_continuous.apply_async(
                countdown=60,
                priority=getattr(settings, "CELERY_TASK_PRIORITY_BACKGROUND", 9),
            )
            logger.info("Scheduled runtime population task to run on startup")
        except Exception as error:
            logger.warning("Failed to schedule runtime population task: %s", error)

    def _schedule_discover_startup_warmup(self):
        """Schedule default Discover tab warmup shortly after startup."""
        try:
            tasks = import_module("app.tasks")
            tasks.warm_discover_startup_tabs.apply_async(
                countdown=90,
                priority=getattr(settings, "CELERY_TASK_PRIORITY_BACKGROUND", 9),
            )
            logger.info("Scheduled Discover startup warmup")
        except Exception as error:
            logger.warning("Failed to schedule Discover startup warmup: %s", error)

    def _schedule_history_day_coverage_warmup(self):
        """Schedule low-priority history day cache coverage repair after startup."""
        try:
            tasks = import_module("app.tasks")
            tasks.warm_history_day_cache_coverage.apply_async(
                countdown=300,
                priority=getattr(settings, "CELERY_TASK_PRIORITY_BACKGROUND", 9),
            )
            logger.info("Scheduled history day coverage warmup")
        except Exception as error:
            logger.warning("Failed to schedule history day coverage warmup: %s", error)

    def _schedule_imdb_game_person_profile_backfill(self):
        """Schedule IMDB person profile repair when gender/image data is missing.

        The missing-profile count check itself runs inside the Celery task
        (not here) so no DB query happens during ``ready()``, which executes
        pre-fork in the Gunicorn master under ``preload_app``.
        """
        try:
            tasks_imdb = import_module("app.tasks_imdb")
            tasks_imdb.schedule_imdb_game_person_profile_backfill_if_needed.apply_async(
                countdown=STARTUP_SWEEP_COUNTDOWNS["imdb_person"],
                priority=getattr(settings, "CELERY_TASK_PRIORITY_BACKGROUND", 9),
            )
            logger.info("Scheduled IMDB person profile backfill check on startup")
        except Exception as error:
            logger.warning("Failed to schedule IMDB person profile backfill: %s", error)

    def _schedule_genre_backfill_reconcile(self):
        """Queue the genre reconcile gate for a worker to evaluate."""
        try:
            tasks = import_module("app.tasks")
            version = tasks.GENRE_BACKFILL_VERSION
            # Atomic, so two gunicorn workers starting together can't both
            # enqueue - the get-then-set this replaces had exactly that race.
            if not self._add_startup_cache_key(
                f"genre_reconcile_startup_v{version}",
                timeout=3600,
            ):
                return

            # The worker-side ensure task owns the durable state gate. Keeping
            # that DB query out of ready() avoids checking out a pool
            # connection during process startup.
            tasks.ensure_genre_backfill_reconcile.apply_async(
                kwargs={"strategy_version": version},
                countdown=STARTUP_SWEEP_COUNTDOWNS["genre"],
                priority=getattr(settings, "CELERY_TASK_PRIORITY_BACKGROUND", 9),
            )

            logger.info(
                "Scheduled genre backfill reconcile (version=%s)",
                version,
            )
        except Exception as error:
            logger.warning("Failed to schedule genre backfill reconcile: %s", error)

    def _schedule_igdb_rating_backfill_reconcile(self):
        """Schedule a one-time backfill of IGDB critic/user ratings for existing games.

        Games tracked before the IGDB rating/aggregated_rating field split have stale
        or missing igdb_user_rating data that would otherwise only refresh when their
        detail page happens to be visited. Runs once per strategy version.
        """
        try:
            from app.tasks_igdb_ratings import (
                IGDB_RATINGS_BACKFILL_VERSION,
                reconcile_igdb_rating_backfill,
            )

            version_key = f"igdb_ratings_backfilled_v{IGDB_RATINGS_BACKFILL_VERSION}"
            status = cache.get(version_key)

            if status in {"done", "pending"}:
                return

            cache.set(version_key, "pending", timeout=300)

            try:
                reconcile_igdb_rating_backfill.apply_async(
                    kwargs={"strategy_version": IGDB_RATINGS_BACKFILL_VERSION},
                    countdown=STARTUP_SWEEP_COUNTDOWNS["igdb_ratings"],
                    priority=getattr(settings, "CELERY_TASK_PRIORITY_BACKGROUND", 9),
                )
            except Exception:
                cache.delete(version_key)
                raise

            logger.info(
                "Scheduled IGDB ratings backfill reconcile (version=%s)",
                IGDB_RATINGS_BACKFILL_VERSION,
            )
        except Exception as error:
            logger.warning(
                "Failed to schedule IGDB ratings backfill reconcile: %s", error
            )

    def _schedule_provider_backfill_reconcile(self):
        """Queue the watch-provider reconcile gate for a worker to evaluate.

        Items tracked before watch-provider data was persisted have no
        streaming-service info until their detail page happens to be visited
        or the periodic beat sweep reaches them; this kicks a reconcile pass
        off immediately so the new filter isn't empty until then.
        """
        try:
            from app.tasks_providers import (
                WATCH_PROVIDERS_BACKFILL_VERSION,
                ensure_provider_backfill_reconcile,
            )

            version = WATCH_PROVIDERS_BACKFILL_VERSION
            if not self._add_startup_cache_key(
                f"provider_reconcile_startup_v{version}",
                timeout=3600,
            ):
                return

            # The worker-side ensure task owns the durable state gate. Keeping
            # that DB query out of ready() avoids checking out a pool
            # connection during process startup.
            ensure_provider_backfill_reconcile.apply_async(
                kwargs={"strategy_version": version},
                countdown=STARTUP_SWEEP_COUNTDOWNS["provider"],
                priority=getattr(settings, "CELERY_TASK_PRIORITY_BACKGROUND", 9),
            )

            logger.info(
                "Scheduled watch provider backfill reconcile (version=%s)",
                version,
            )
        except Exception as error:
            logger.warning(
                "Failed to schedule watch provider backfill reconcile: %s", error
            )

    def _schedule_trakt_popularity_reconcile(self):
        """Schedule Trakt popularity reconciliation on startup.

        Fires immediately when the formula version advances; once per day otherwise
        for catch-up.  Cache keys are only written after the task is successfully
        queued so a broker hiccup at startup never silently blocks future restarts.
        """
        try:
            from app.services.trakt_popularity import (
                TRAKT_POPULARITY_SCORE_VERSION,
            )

            version_key = (
                f"trakt_popularity_reconciled_v{TRAKT_POPULARITY_SCORE_VERSION}"
            )
            daily_key = "trakt_popularity_reconcile_daily"

            version_status = cache.get(version_key)  # None | "pending" | "done"
            daily_status = cache.get(daily_key)  # None | 1

            version_done = version_status == "done"
            version_pending = version_status == "pending"

            if version_done and daily_status:
                return  # Already reconciled this version; daily catch-up also ran

            if version_pending and daily_status:
                return  # Task queued in the last 5 minutes; don't queue again

            is_version_recompute = not version_done

            tasks = import_module("app.tasks")
            tasks.reconcile_trakt_popularity.apply_async(
                kwargs={"score_version": TRAKT_POPULARITY_SCORE_VERSION},
                countdown=STARTUP_SWEEP_COUNTDOWNS["trakt_popularity"],
                priority=getattr(settings, "CELERY_TASK_PRIORITY_BACKGROUND", 9),
            )

            # Set keys only after successful queue so a failed apply_async
            # doesn't permanently block the next restart from trying again.
            if is_version_recompute:
                cache.set(version_key, "pending", timeout=300)
            cache.set(daily_key, 1, timeout=86400)

            logger.info(
                "Scheduled Trakt popularity reconcile (version_trigger=%s)",
                is_version_recompute,
            )
        except Exception as error:
            logger.warning("Failed to schedule Trakt popularity reconcile: %s", error)
