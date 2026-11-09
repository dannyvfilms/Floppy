"""Podcast episode listens: one ``PodcastPlay`` row per listen.

``Podcast`` is the per-user tracker of an episode (score, notes, current
state). A listen is a ``PodcastPlay``. The web views, the REST API and the
importers all go through this module, so a listen is created, changed and
deleted the same way everywhere, and the tracker always shows what its plays
say. Editing a play never creates another one; deleting a play removes only
that play.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from app.models import Item, MediaTypes, Podcast, PodcastPlay, Status

logger = logging.getLogger(__name__)

DUPLICATE_PLAY_WINDOW_SECONDS = 300

_UNSET = object()

_in_service_write = ContextVar("podcast_plays_service_write", default=False)


@contextmanager
def service_write():
    """Mark tracker saves made by this module, so the save signal skips them."""
    token = _in_service_write.set(True)
    try:
        yield
    finally:
        _in_service_write.reset(token)


def in_service_write():
    """Return whether this module is writing the tracker right now."""
    return _in_service_write.get()


BAD_STATUS = "bad_status"
OPEN_WITH_END_DATE = "open_with_end_date"
DATES_REVERSED = "dates_reversed"
ALREADY_OPEN = "already_open"

PLAY_ERROR_MESSAGES = {
    BAD_STATUS: "'status' must be 'In progress' or 'Completed'.",
    OPEN_WITH_END_DATE: "An In progress play cannot have an end_date.",
    DATES_REVERSED: "'start_date' must not be after 'end_date'.",
    ALREADY_OPEN: "This episode already has a play in progress.",
}


class PodcastPlayError(ValueError):
    """Raised when a play change is not valid.

    ``code`` keys ``PLAY_ERROR_MESSAGES``, so a caller can show the fixed
    message without echoing the exception.
    """

    def __init__(self, code):
        """Store the error code."""
        super().__init__(code)
        self.code = code

    @property
    def message(self):
        """Return the fixed message for this error."""
        return PLAY_ERROR_MESSAGES[self.code]


def episode_runtime_minutes(episode):
    """Return the episode's runtime in whole minutes, or None."""
    if episode and episode.duration:
        return episode.duration // 60
    return None


def ensure_episode_item(show, episode=None, episode_uuid=None):
    """Return the Item for an episode, creating it and refreshing its facts."""
    runtime_minutes = episode_runtime_minutes(episode)
    media_id = episode_uuid or (episode.episode_uuid if episode else None)
    defaults = {
        "title": episode.title if episode else "Unknown Episode",
        "image": (episode.image if episode else "") or show.image or settings.IMG_NONE,
    }
    if runtime_minutes:
        defaults["runtime_minutes"] = runtime_minutes
    if episode and episode.published:
        defaults["release_datetime"] = episode.published

    item, created = Item.objects.get_or_create(
        media_id=media_id,
        source=show.source,
        media_type=MediaTypes.PODCAST.value,
        defaults=defaults,
    )
    if not created:
        update_fields = []
        if runtime_minutes and item.runtime_minutes != runtime_minutes:
            item.runtime_minutes = runtime_minutes
            update_fields.append("runtime_minutes")
        if episode and episode.published and item.release_datetime != episode.published:
            item.release_datetime = episode.published
            update_fields.append("release_datetime")
        if update_fields:
            item.save(update_fields=update_fields)
    return item, created


def ensure_tracker(user, show, episode, item):
    """Return the user's Podcast tracker for the episode, creating it."""
    tracker = (
        Podcast.objects.filter(user=user, item=item)
        .order_by("-created_at", "-id")
        .first()
    )
    if tracker is not None:
        return tracker
    with service_write():
        return Podcast.objects.create(
            item=item,
            user=user,
            show=show,
            episode=episode,
            status=Status.PLANNING.value,
            progress=0,
        )


def sync_tracker(podcast, *, keep_status=False):
    """Make the tracker show what its plays say.

    An open (In Progress) play is the current state. Otherwise the newest
    completed play is. With no plays the tracker is back to Planning.
    ``keep_status`` leaves the status as the user set it (an edit of the
    tracker itself) and mirrors only dates and progress.
    """
    plays = list(podcast.plays.all())
    open_play = next(
        (p for p in plays if p.status == Status.IN_PROGRESS.value and not p.end_date),
        None,
    )
    completed = [p for p in plays if p.end_date]
    latest = max(completed, key=lambda p: (p.end_date, p.id)) if completed else None

    current = open_play or latest
    if current is None:
        status, start_date, end_date, progress, seconds = (
            Status.PLANNING.value,
            None,
            None,
            0,
            None,
        )
        inferred = False
    else:
        status = Status.IN_PROGRESS.value if open_play else Status.COMPLETED.value
        start_date = current.start_date
        end_date = latest.end_date if latest else None
        progress = current.progress
        seconds = current.played_up_to_seconds
        inferred = latest.is_end_date_inferred if latest else False

    if keep_status:
        status = podcast.status
    podcast.status = status
    podcast.start_date = start_date
    podcast.end_date = end_date
    podcast.progress = progress
    podcast.played_up_to_seconds = seconds
    podcast.is_end_date_inferred = inferred
    with service_write():
        podcast.save()

        if not keep_status and podcast.status != status:
            # Media.process_progress completes a tracker whose progress reached
            # the runtime. An open play is still a listen in progress.
            podcast.status = status
            podcast.save_without_historical_record(update_fields=["status"])
    return podcast


def _resolve_progress(minutes, seconds, default):
    if minutes is _UNSET and seconds is _UNSET:
        return default, _UNSET
    if minutes is _UNSET:
        return (seconds or 0) // 60, seconds
    return minutes, seconds


def _validate(status, start_date, end_date):
    if status not in (Status.IN_PROGRESS.value, Status.COMPLETED.value):
        raise PodcastPlayError(BAD_STATUS)
    if status == Status.IN_PROGRESS.value and end_date:
        raise PodcastPlayError(OPEN_WITH_END_DATE)
    if start_date and end_date and start_date > end_date:
        raise PodcastPlayError(DATES_REVERSED)


def _find_duplicate(podcast, completed_at):
    window = timedelta(seconds=DUPLICATE_PLAY_WINDOW_SECONDS)
    # Compare against the plays near this timestamp, not the newest one, so an
    # import that re-delivers a 2020 play is measured against the stored 2020
    # play.
    return podcast.plays.filter(
        end_date__gt=completed_at - window,
        end_date__lt=completed_at + window,
    ).first()


@transaction.atomic
def create_play(
    user,
    show,
    *,
    episode=None,
    episode_uuid=None,
    status=Status.COMPLETED.value,
    start_date=None,
    end_date=None,
    progress=_UNSET,
    played_up_to_seconds=_UNSET,
    external_id=None,
    entry_source="",
    is_end_date_inferred=False,
):
    """Create one listen of an episode; returns ``(play, created)``.

    A completed play without ``end_date`` ends now and defaults its progress to
    the runtime. An In Progress play has no end date; a second request while
    one is open returns the open play instead of starting another listen. A
    completed play within five minutes of an existing one, or repeating an
    ``external_id``, returns that play with ``created`` False.
    """
    if status == Status.COMPLETED.value and end_date is None:
        end_date = timezone.now()
    _validate(status, start_date, end_date)

    item, _ = ensure_episode_item(show, episode, episode_uuid)
    tracker = ensure_tracker(user, show, episode, item)
    runtime = item.runtime_minutes if status == Status.COMPLETED.value else None
    minutes, seconds = _resolve_progress(progress, played_up_to_seconds, runtime or 0)

    if external_id:
        existing = tracker.plays.filter(external_id=external_id).first()
        if existing:
            return existing, False
    if status == Status.IN_PROGRESS.value:
        open_play = tracker.plays.filter(
            status=Status.IN_PROGRESS.value,
            end_date__isnull=True,
        ).first()
        if open_play:
            return open_play, False
    else:
        duplicate = _find_duplicate(tracker, end_date)
        if duplicate:
            logger.debug("Skipping duplicate podcast play near %s", end_date)
            return duplicate, False

    with service_write():
        play = PodcastPlay.objects.create(
            podcast=tracker,
            status=status,
            start_date=start_date,
            end_date=end_date,
            progress=minutes or 0,
            played_up_to_seconds=None if seconds is _UNSET else seconds,
            external_id=external_id or None,
            entry_source=entry_source,
            is_end_date_inferred=is_end_date_inferred,
        )
    sync_tracker(tracker)
    return play, True


@transaction.atomic
def update_play(
    play,
    *,
    status=_UNSET,
    start_date=_UNSET,
    end_date=_UNSET,
    progress=_UNSET,
    played_up_to_seconds=_UNSET,
    keep_tracker_status=False,
):
    """Change one listen in place. Only the fields given are touched.

    Completing a play without an ``end_date`` ends it now; leaving In Progress
    for Completed also defaults progress to the runtime. Moving back to
    In Progress clears the end date.
    """
    new_status = play.status if status is _UNSET else status
    new_start = play.start_date if start_date is _UNSET else start_date
    new_end = play.end_date if end_date is _UNSET else end_date

    if new_status == Status.IN_PROGRESS.value and end_date is _UNSET:
        new_end = None
    if new_status == Status.COMPLETED.value and new_end is None:
        new_end = timezone.now()
    _validate(new_status, new_start, new_end)

    if new_status == Status.IN_PROGRESS.value:
        clash = (
            play.podcast.plays.filter(
                status=Status.IN_PROGRESS.value,
                end_date__isnull=True,
            )
            .exclude(pk=play.pk)
            .exists()
        )
        if clash:
            raise PodcastPlayError(ALREADY_OPEN)

    default_progress = play.progress
    if (
        new_status == Status.COMPLETED.value
        and play.status != Status.COMPLETED.value
        and play.podcast.item.runtime_minutes
    ):
        default_progress = play.podcast.item.runtime_minutes
    minutes, seconds = _resolve_progress(
        progress,
        played_up_to_seconds,
        default_progress,
    )

    play.status = new_status
    play.start_date = new_start
    play.end_date = new_end
    play.progress = minutes or 0
    if seconds is not _UNSET:
        play.played_up_to_seconds = seconds
    if end_date is not _UNSET:
        play.is_end_date_inferred = False
    with service_write():
        play.save()
    sync_tracker(play.podcast, keep_status=keep_tracker_status)
    return play


@transaction.atomic
def delete_play(play):
    """Delete one listen and bring the tracker back in step."""
    podcast = play.podcast
    with service_write():
        play.delete()
    sync_tracker(podcast)
    return podcast


def apply_tracker_edit(podcast, previous_end_date=None):
    """Carry a save of the tracker row over to the listen it describes.

    Importers, webhooks and the track form write the tracker directly. Without
    this a changed date or status left the plays as they were, and showed up
    as a second listen. The play being edited is the open one, or the one that
    ended at ``previous_end_date``; with none, a play is created. The tracker
    is the source of truth here, so it is not re-synced from its plays.
    """
    if podcast.end_date:
        fields = {
            "status": Status.COMPLETED.value,
            "start_date": podcast.start_date,
            "end_date": podcast.end_date,
            "progress": podcast.progress or 0,
            "played_up_to_seconds": podcast.played_up_to_seconds,
            "is_end_date_inferred": podcast.is_end_date_inferred,
        }
    elif podcast.status == Status.IN_PROGRESS.value:
        fields = {
            "status": Status.IN_PROGRESS.value,
            "start_date": podcast.start_date,
            "end_date": None,
            "progress": podcast.progress or 0,
            "played_up_to_seconds": podcast.played_up_to_seconds,
            "is_end_date_inferred": False,
        }
    else:
        return podcast

    plays = podcast.plays
    open_play = plays.filter(
        status=Status.IN_PROGRESS.value,
        end_date__isnull=True,
    ).first()
    previous = (
        plays.filter(end_date=previous_end_date).first() if previous_end_date else None
    )
    target = open_play or previous
    if target is None and fields["end_date"]:
        # A tracker saved again at a date a play already holds is not a new play.
        target = plays.filter(end_date=fields["end_date"]).first()

    try:
        _validate(fields["status"], fields["start_date"], fields["end_date"])
    except PodcastPlayError:
        logger.warning("Podcast %s dates do not describe a play; skipped", podcast.pk)
        return podcast

    if target is None:
        with service_write():
            PodcastPlay.objects.create(podcast=podcast, **fields)
        return podcast

    changed = [name for name, value in fields.items() if getattr(target, name) != value]
    if changed:
        for name in changed:
            setattr(target, name, fields[name])
        with service_write():
            target.save(update_fields=[*changed, "updated_at"])
    return podcast


def create_plays_for_trackers(trackers):
    """Create the plays for tracker rows written with bulk_create.

    ``bulk_create`` sends no save signal, so importers call this once with the
    rows they wrote. Trackers that already have a play are left alone.
    """
    trackers = [
        t
        for t in trackers
        if t.pk and (t.end_date or t.status == Status.IN_PROGRESS.value)
    ]
    have_plays = set(
        PodcastPlay.objects.filter(podcast_id__in=[t.pk for t in trackers])
        .values_list("podcast_id", flat=True)
        .distinct(),
    )
    plays = [
        PodcastPlay(
            podcast=tracker,
            status=(
                Status.COMPLETED.value if tracker.end_date else Status.IN_PROGRESS.value
            ),
            start_date=tracker.start_date,
            end_date=tracker.end_date,
            progress=tracker.progress or 0,
            played_up_to_seconds=tracker.played_up_to_seconds,
            is_end_date_inferred=tracker.is_end_date_inferred,
            entry_source=tracker.entry_source or "",
        )
        for tracker in trackers
        if tracker.pk not in have_plays
    ]
    return PodcastPlay.objects.bulk_create(plays, batch_size=500)
