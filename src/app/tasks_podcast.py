"""One-shot backfill of podcast show/episode website links.

``website_url`` was added to ``PodcastShow``/``PodcastEpisode`` for issue #1014,
but every code path only wrote it when a row was first created, so libraries
that predate the field kept blank links forever. The refresh paths now update
existing rows too, which repairs a show the moment anything re-reads its feed --
but that only happens when a user opens the show, syncs it, or re-runs a
provider import. This sweep walks every show with a feed once so the repair does
not wait on any of that.

It is deliberately one-shot rather than an ongoing reconcile: unlike the genre
and watch-provider sweeps, whose candidate sets shrink as items succeed, a feed
that simply has no <link> element (Apple's and Spotify's do not) never stops
qualifying, so a "still missing a website" filter would re-fetch those feeds
forever. Completion is recorded durably by ``app.reconcile_state``; re-running
the sweep later is a ``PODCAST_WEBSITE_BACKFILL_VERSION`` bump, which
``reconcile_state.get_state`` already treats as a reset.
"""

import logging

from celery import shared_task
from django.conf import settings

from app import reconcile_state
from app.interactive_requests import interactive_request_active
from app.log_safety import exception_summary
from app.models import PodcastShow

logger = logging.getLogger(__name__)

BACKGROUND_TASK_PRIORITY = getattr(settings, "CELERY_TASK_PRIORITY_BACKGROUND", 9)

PODCAST_WEBSITE_BACKFILL_VERSION = 1
RECONCILE_KEY = "podcast_website"
# See tasks_providers.RECONCILE_MAX_CHUNKS_PER_RUN.
RECONCILE_MAX_CHUNKS_PER_RUN = settings.RECONCILE_MAX_CHUNKS_PER_RUN
# Smaller than the metadata sweeps' batches: each show here is one outbound HTTP
# request to a third-party feed host, not a row read.
PODCAST_WEBSITE_BATCH_SIZE = 20


def _shows_with_feeds():
    """Return shows whose feed can be read, oldest id first."""
    return PodcastShow.objects.exclude(rss_feed_url="").order_by("id")


@shared_task(name="app.tasks.backfill_podcast_show_websites")
def backfill_podcast_show_websites(show_ids):
    """Re-read each show's feed, applying show and episode website links."""
    from app.fork_services_podcast import refresh_show_from_rss

    processed = 0
    for show in PodcastShow.objects.filter(id__in=list(show_ids or [])):
        try:
            refresh_show_from_rss(show)
        except Exception as error:
            # One unreachable feed must not cost the rest of the batch; the
            # sweep is one-shot, so the show simply keeps its blank link until
            # something else re-reads it.
            logger.warning(
                "podcast_website_backfill_failed show_id=%s error=%s",
                show.id,
                exception_summary(error),
            )
            continue
        processed += 1
    return {"processed": processed}


@shared_task(name="app.tasks.reconcile_podcast_website_backfill")
def reconcile_podcast_website_backfill(
    strategy_version: int | None = None,
    batch_size: int = PODCAST_WEBSITE_BATCH_SIZE,
    max_chunks: int | None = None,
):
    """Queue a bounded slice of shows for the website backfill."""
    batch_size = max(int(batch_size), 1)
    max_chunks = RECONCILE_MAX_CHUNKS_PER_RUN if max_chunks is None else max_chunks
    resolved_version = int(strategy_version or PODCAST_WEBSITE_BACKFILL_VERSION)
    state = reconcile_state.get_state(RECONCILE_KEY, resolved_version)

    cursor = state.last_cursor_item_id
    enqueued = 0

    for chunk_index in range(max_chunks):
        batch_ids = list(
            _shows_with_feeds()
            .filter(id__gt=cursor)
            .values_list("id", flat=True)[:batch_size],
        )
        if not batch_ids:
            # Every show with a feed has been queued once, which is the whole
            # job. No wrap-around pass: the candidate set here never shrinks,
            # so a second lap would only re-fetch every feed.
            reconcile_state.mark_complete(RECONCILE_KEY, resolved_version)
            logger.info(
                "reconcile_podcast_website_backfill complete version=%s",
                resolved_version,
            )
            return {"enqueued": enqueued, "complete": True}

        cursor = batch_ids[-1]
        # Stagger the chunks so a large library doesn't fire every feed request
        # at once.
        backfill_podcast_show_websites.apply_async(
            args=[batch_ids],
            countdown=10 + chunk_index * 30,
            priority=BACKGROUND_TASK_PRIORITY,
        )
        enqueued += len(batch_ids)

    reconcile_state.mark_progress(
        RECONCILE_KEY,
        resolved_version,
        cursor=cursor,
        enqueued=enqueued,
    )
    logger.info(
        "reconcile_podcast_website_backfill enqueued=%d cursor=%d version=%s",
        enqueued,
        cursor,
        resolved_version,
    )
    return {"enqueued": enqueued, "complete": False}


@shared_task(name="Ensure podcast website backfill reconcile")
def ensure_podcast_website_backfill_reconcile(
    strategy_version: int | None = None,
    batch_size: int = PODCAST_WEBSITE_BATCH_SIZE,
):
    """Run a podcast website backfill pass unless one isn't needed."""
    if interactive_request_active():
        logger.info(
            "ensure_podcast_website_backfill_reconcile skipped "
            "reason=interactive_request_active",
        )
        return {"skipped": True, "reason": "interactive_request_active"}

    resolved_version = int(strategy_version or PODCAST_WEBSITE_BACKFILL_VERSION)
    state = reconcile_state.should_run(RECONCILE_KEY, resolved_version)
    if state is None:
        return {"skipped": True, "reason": "not_due"}

    if not reconcile_state.acquire(RECONCILE_KEY, state):
        return {"skipped": True, "reason": "already_running"}

    try:
        return reconcile_podcast_website_backfill(
            strategy_version=resolved_version,
            batch_size=batch_size,
        )
    finally:
        reconcile_state.release(RECONCILE_KEY)


@shared_task(name="Refresh podcast show from RSS", ignore_result=True)
def refresh_podcast_show_from_rss_task(show_id: int):
    """Reconcile a podcast show against its feed off the detail request path."""
    from app.fork_services_podcast import refresh_show_from_rss
    from app.models import PodcastShow

    show = PodcastShow.objects.filter(pk=show_id).first()
    if show is not None:
        refresh_show_from_rss(show)
