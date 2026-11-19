"""Push Floppy watched state to one chosen Plex user, on request.

Manual only: nothing here runs from the delivery engine, so no write reaches
Plex without a person confirming it. This module picks *who* is written to,
plans what would change, and sends only what was confirmed. A token that acts
as a Home user is built per request and never stored.
"""

import re
import time
from collections import defaultdict
from dataclasses import dataclass, field

from celery.exceptions import SoftTimeLimitExceeded

from app.models import Item, MediaTypes, Sources, WatchState
from integrations import external_references
from integrations import plex as plex_api
from integrations.models import (
    ExternalReference,
    ExternalReferenceReviewStatus,
    PlexWatchedPush,
)
from integrations.safe_fetch import UnsafeUrlError

PLEX_EPISODE_TYPE = 4
# Gives Plex a moment before items it reported as already watched are read again.
RECHECK_DELAY_SECONDS = 10
_PLEX_TYPE_BY_MEDIA_TYPE = {
    MediaTypes.MOVIE.value: "movie",
    MediaTypes.EPISODE.value: "episode",
}

_SOURCE_BY_ID_KEY = {
    "tmdb_id": Sources.TMDB.value,
    "tvdb_id": Sources.TVDB.value,
    "imdb_id": Sources.IMDB.value,
}
_GENERIC_EPISODE_TITLE = re.compile(r"episode\d+")


class PlexPushError(Exception):
    """The push cannot be prepared as requested."""


class PinRequiredError(PlexPushError):
    """The chosen Home user is PIN protected and no PIN was given."""


# A send runs in a background task that shares these cache keys with the views.
# The lock covers the wait in the queue; a running send renews it after every item.
# A send still queued when it lapses does not run, and the popup says it stopped.
LOCK_SECONDS = 30 * 60
# The result stays readable for a while after the popup stops polling.
STATUS_SECONDS = 60 * 60


def lock_key(user_id):
    """Held while a check or send runs, so only one runs per user."""
    return f"plex_push:{user_id}"


def status_key(user_id):
    """Progress, then the result, of the user's latest send."""
    return f"plex_push_status:{user_id}"


def pin_key(user_id):
    """Hand the Home user PIN to the task, which deletes it on first read."""
    return f"plex_push_pin:{user_id}"


def describe_error(error):
    """Return the message shown for an error that stops a check or send."""
    if isinstance(error, PlexPushError):
        return str(error)
    if isinstance(error, plex_api.PlexAuthError):
        return "Plex refused access. Check the PIN, or reconnect Plex."
    return "Plex could not be reached. Try again."


@dataclass(frozen=True)
class PushTarget:
    """One Plex user Floppy can write watched state for."""

    uuid: str
    title: str
    is_owner: bool
    protected: bool


@dataclass(frozen=True)
class PushServer:
    """One Plex server the connected account owns."""

    machine_identifier: str
    name: str


@dataclass(frozen=True)
class PushSession:
    """Where and as whom a push writes. Held in memory only."""

    target: PushTarget
    server: PushServer
    uri: str
    token: str


def list_targets(account):
    """Return (users, servers) the account may push to.

    Users are the owner and their Plex Home users; friends a server is shared
    with are out of scope. Servers are only the ones the account owns, so a
    push can never write into someone else's server.
    """
    # The saved token is the owner's, so match its account id when it is known;
    # the Home admin is only a fallback, and may not be the connected account.
    owner_id = str(account.plex_account_id or "")
    users = [
        PushTarget(
            uuid=str(user.get("uuid")),
            title=user.get("title") or user.get("username") or "",
            is_owner=(
                str(user.get("id")) == owner_id if owner_id else bool(user.get("admin"))
            ),
            protected=bool(user.get("protected")),
        )
        for user in plex_api.list_home_users(account.plex_token)
        if user.get("uuid")
    ]
    servers = [
        PushServer(
            machine_identifier=server["machine_identifier"],
            name=server.get("name") or "",
        )
        for server in plex_api.list_resources(account.plex_token)
        if server.get("owned") and server.get("machine_identifier")
    ]
    return users, servers


def open_session(account, user_uuid, machine_identifier, pin=None):
    """Return a PushSession for one Plex user on one owned server."""
    users, servers = list_targets(account)
    target = next((user for user in users if user.uuid == user_uuid), None)
    if target is None:
        msg = "That Plex user is not part of this account's Plex Home"
        raise PlexPushError(msg)
    server = next(
        (s for s in servers if s.machine_identifier == machine_identifier),
        None,
    )
    if server is None:
        msg = "That Plex server is not owned by this account"
        raise PlexPushError(msg)

    user_token = account.plex_token
    if not target.is_owner:
        if target.protected and not pin:
            msg = f"{target.title} needs their Plex PIN"
            raise PinRequiredError(msg)
        user_token = plex_api.switch_home_user(account.plex_token, user_uuid, pin)

    # The server token comes from the user's own resource list, so every
    # write is made as that user and lands in their watched state only.
    resource = next(
        (
            r
            for r in plex_api.list_resources(user_token)
            if r.get("machine_identifier") == machine_identifier
        ),
        None,
    )
    if resource is None or not resource.get("access_token"):
        msg = f"{target.title} has no access to {server.name}"
        raise PlexPushError(msg)

    section = plex_api.find_cached_section(account.sections, machine_identifier)
    if not section:
        msg = "Refresh your Plex libraries in Floppy first"
        raise PlexPushError(msg)

    return PushSession(
        target=target,
        server=server,
        uri=section["uri"],
        token=resource["access_token"],
    )


@dataclass(frozen=True)
class PlannedWrite:
    """One Plex item the dry run would mark watched."""

    rating_key: str
    item_id: int
    media_type: str
    library: str
    plex_title: str
    floppy_title: str
    #: Non-empty when the match deserves a look; the row starts unticked.
    warning: str = ""


@dataclass
class PushPlan:
    """What a push would change. Building it writes nothing to Plex."""

    writes: list[PlannedWrite] = field(default_factory=list)
    already_watched: int = 0
    ignored: int = 0
    #: (Plex title, reason) for Floppy-watched items deliberately left alone.
    not_matched: list[tuple[str, str]] = field(default_factory=list)
    failed_libraries: list[str] = field(default_factory=list)


@dataclass
class PushResult:
    """What a send did, item by item."""

    sent: list[str] = field(default_factory=list)
    #: (Plex title, reason) for selected items that were not written.
    skipped: list[tuple[str, str]] = field(default_factory=list)
    #: Selected items a fresh plan no longer contains.
    stale: int = 0
    #: Libraries the fresh plan could not read; their ticked items count as stale.
    failed_libraries: list[str] = field(default_factory=list)
    #: Set when a Plex error stopped the send; what was sent before it stays.
    stopped: str = ""


def send(user, account, session, selected, progress=None):
    """Mark the selected (rating key, item id) pairs watched for the session's user.

    Only pairs a fresh plan still contains are written, so anything that
    changed since the preview is dropped. Each item is read right before its
    write, because ``/:/scrobble`` adds a play every time it is called.
    ``progress(done, total)`` is called after each item.

    Plex sometimes answers that read with "watched" for an item its library
    listing still shows unwatched. Those items are read once more after the
    main pass and sent only if Plex then agrees they are unwatched.
    """
    plan = build_plan(user, account, session)
    planned = [
        write for write in plan.writes if (write.rating_key, write.item_id) in selected
    ]
    result = PushResult(
        stale=len(selected) - len(planned),
        failed_libraries=plan.failed_libraries,
    )
    recheck = []

    def attempt(write, *, last_try):
        current = plex_api.fetch_metadata(session.token, session.uri, write.rating_key)
        if (
            current is None
            or current.get("type") != _PLEX_TYPE_BY_MEDIA_TYPE[write.media_type]
        ):
            result.skipped.append((write.plex_title, "No longer found in Plex"))
            return
        if _is_watched(current):
            if last_try:
                result.skipped.append((write.plex_title, "Already watched in Plex"))
            else:
                recheck.append(write)
            return

        # Recorded before the write: a write that lands while its response
        # is lost must still be recognized as Floppy's echo on import.
        PlexWatchedPush.objects.create(
            user=user,
            item_id=write.item_id,
            machine_identifier=session.server.machine_identifier,
            rating_key=write.rating_key,
            plex_user_uuid=session.target.uuid,
            plex_user_title=session.target.title,
        )
        plex_api.mark_watched(session.token, session.uri, write.rating_key)

        try:
            readback = plex_api.fetch_metadata(
                session.token,
                session.uri,
                write.rating_key,
            )
        except SoftTimeLimitExceeded:
            result.skipped.append(
                (write.plex_title, "Sent, but not read back: the send ran out of time"),
            )
            raise
        if readback is None or not _is_watched(readback):
            result.skipped.append(
                (write.plex_title, "Sent, but Plex does not show it as watched"),
            )
            return
        result.sent.append(write.plex_title)

    def run(writes, *, last_try):
        for done, write in enumerate(writes):
            if progress:
                progress(done, len(writes))
            try:
                attempt(write, last_try=last_try)
            except plex_api.PlexAuthError:
                result.stopped = "Plex refused access. Nothing after this item was sent."
            except (plex_api.PlexClientError, UnsafeUrlError):
                result.stopped = (
                    "Plex stopped responding. Nothing after this item was sent."
                )
            except SoftTimeLimitExceeded:
                result.stopped = "The send ran out of time. Check again to send the rest."
            if result.stopped:
                return

    run(planned, last_try=False)
    if recheck and not result.stopped:
        try:
            time.sleep(RECHECK_DELAY_SECONDS)
        except SoftTimeLimitExceeded:
            result.stopped = "The send ran out of time. Check again to send the rest."
    if recheck and not result.stopped:
        run(recheck, last_try=True)
    elif recheck:
        result.skipped.extend(
            (write.plex_title, "Not checked again: the send stopped")
            for write in recheck
        )
    return result


def build_plan(user, account, session):
    """Compare Floppy's watched movies and episodes with the session's Plex user.

    Read only. A Plex item is planned only when it is unwatched for that user
    and resolves to a Floppy item the user has watched — through the saved
    Plex match decisions first, so corrections and ignores hold, and otherwise
    by exact provider id plus season and episode numbers.
    """
    watched = _WatchedIndex(user)
    references = _plex_references(user, account, session.server.machine_identifier)
    plan = PushPlan()

    for section in account.sections or []:
        if section.get("machine_identifier") != session.server.machine_identifier:
            continue
        kind = section.get("type")
        if kind not in ("movie", "show"):
            continue
        library = section.get("title") or ""
        try:
            if kind == "movie":
                _plan_movies(plan, session, section, library, watched, references)
            else:
                _plan_episodes(plan, session, section, library, watched, references)
        except plex_api.PlexClientError:
            plan.failed_libraries.append(library)

    return plan


class _WatchedIndex:
    """The user's watched movies and episodes, keyed the ways Plex can match."""

    def __init__(self, user):
        self.by_id = {}
        self.movies = defaultdict(list)
        self.episodes = defaultdict(list)
        states = (
            WatchState.objects.filter(
                user=user,
                watched=True,
                item__media_type__in=(
                    MediaTypes.MOVIE.value,
                    MediaTypes.EPISODE.value,
                ),
            )
            .select_related("item")
            .only(
                "item__id",
                "item__source",
                "item__media_id",
                "item__media_type",
                "item__library_media_type",
                "item__season_number",
                "item__episode_number",
                "item__episode_order_id",
                "item__title",
                "item__original_title",
                "item__localized_title",
            )
        )
        for state in states.iterator():
            item = state.item
            self.by_id[item.id] = item
            if item.media_type == MediaTypes.MOVIE.value:
                self.movies[(item.source, str(item.media_id))].append(item)
            else:
                key = (
                    item.source,
                    str(item.media_id),
                    item.season_number,
                    item.episode_number,
                )
                self.episodes[key].append(item)

    def target(self, item):
        """Return the watched item a saved decision points at, if watched."""
        return self.by_id.get(item.id) if item else None


def _plex_references(user, account, machine_identifier):
    """Return saved Plex decisions keyed by (rating key, media type)."""
    source_account = external_references.plex_source_account(
        account,
        machine_identifier=machine_identifier,
    )
    return {
        (reference.external_identity, reference.media_type): reference
        for reference in ExternalReference.objects.filter(
            user=user,
            integration="plex",
            source_account=source_account,
            external_namespace="plex_rating_key",
        ).select_related("matched_item", "corrected_item")
    }


def _is_ignored(reference):
    return (
        reference is not None
        and reference.review_status == ExternalReferenceReviewStatus.IGNORED.value
    )


def _paged(session, section, item_type=None):
    """Yield every entry of one library as the session's user sees it."""
    start = 0
    while True:
        entries, total = plex_api.fetch_section_all_items(
            session.token,
            session.uri,
            str(section.get("id")),
            start=start,
            item_type=item_type,
        )
        yield from entries
        start += len(entries)
        if not entries or start >= total:
            return


def _rating_key(entry):
    return str(entry.get("ratingKey") or "")


def _is_watched(entry):
    try:
        return int(entry.get("viewCount") or 0) > 0
    except (TypeError, ValueError):
        # Unknown is never treated as unwatched.
        return True


def _id_candidates(index, entry, *suffix):
    """Return watched items sharing one of the entry's provider ids."""
    ids = plex_api.extract_external_ids_from_guids(entry.get("Guid") or [])
    found = []
    for id_key, source in _SOURCE_BY_ID_KEY.items():
        if ids.get(id_key):
            found.extend(index.get((source, str(ids[id_key]), *suffix), []))
    return found


def _plan_movies(plan, session, section, library, watched, references):
    for entry in _paged(session, section):
        rating_key = _rating_key(entry)
        reference = references.get((rating_key, MediaTypes.MOVIE.value))
        if _is_ignored(reference):
            plan.ignored += 1
            continue

        target = external_references.reference_target(reference)
        if target:
            item = watched.target(target)
            candidates = [item] if item else []
        else:
            candidates = _id_candidates(watched.movies, entry)
        if not candidates or not rating_key:
            continue
        if _is_watched(entry):
            plan.already_watched += 1
            continue

        year = entry.get("year")
        plex_title = entry.get("title") or ""
        plan.writes.append(
            PlannedWrite(
                rating_key=rating_key,
                item_id=candidates[0].id,
                media_type=MediaTypes.MOVIE.value,
                library=library,
                plex_title=f"{plex_title} ({year})" if year else plex_title,
                floppy_title=candidates[0].title,
            ),
        )


def _plan_episodes(plan, session, section, library, watched, references):
    shows = {_rating_key(show): show for show in _paged(session, section)}

    for entry in _paged(session, section, PLEX_EPISODE_TYPE):
        rating_key = _rating_key(entry)
        reference = references.get(
            (rating_key, MediaTypes.EPISODE.value),
        ) or references.get((rating_key, MediaTypes.TV.value))
        show_key = str(entry.get("grandparentRatingKey") or "")
        show_reference = references.get((show_key, MediaTypes.TV.value))
        if _is_ignored(reference) or _is_ignored(show_reference):
            plan.ignored += 1
            continue

        try:
            plex_season = int(entry.get("parentIndex"))
            plex_number = int(entry.get("index"))
        except (TypeError, ValueError):
            continue

        target = external_references.reference_target(reference)
        exact = bool(target and target.media_type == MediaTypes.EPISODE.value)
        if exact:
            item = watched.target(target)
            candidates = [item] if item else []
        else:
            # An episode reference without a target decides nothing, so the
            # show's correction and episode mapping still apply.
            season, number = external_references.map_episode_coordinates(
                reference if target else show_reference or reference,
                plex_season,
                plex_number,
            )
            show_target = target or external_references.reference_target(
                show_reference,
            )
            if show_target:
                candidates = watched.episodes.get(
                    (show_target.source, str(show_target.media_id), season, number),
                    [],
                )
            else:
                candidates = _id_candidates(
                    watched.episodes,
                    shows.get(show_key) or {},
                    season,
                    number,
                )
        if not candidates or not rating_key:
            continue
        if _is_watched(entry):
            plan.already_watched += 1
            continue

        item = candidates[0]
        show_title = entry.get("grandparentTitle") or ""
        episode_title = entry.get("title") or ""
        # Plex's own numbers: this is the row the user checks in Plex.
        plex_title = (
            f"{show_title} S{plex_season:02d}E{plex_number:02d} {episode_title}".strip()
        )
        if not exact and (
            item.library_media_type == MediaTypes.ANIME.value or item.episode_order_id
        ):
            # Plex and Floppy may number these differently; only a saved
            # episode-level decision is precise enough to write to.
            plan.not_matched.append(
                (plex_title, "Anime or custom episode order: numbering may differ"),
            )
            continue

        plan.writes.append(
            PlannedWrite(
                rating_key=rating_key,
                item_id=item.id,
                media_type=MediaTypes.EPISODE.value,
                library=library,
                plex_title=plex_title,
                floppy_title=item.title,
                warning="" if exact else _title_warning(item, entry),
            ),
        )


def _title_warning(item, entry):
    """Flag a numbers-only episode match whose titles visibly disagree."""
    plex_key = Item._title_comparison_key(entry.get("title"))
    show_key = Item._title_comparison_key(entry.get("grandparentTitle"))
    floppy_keys = {
        Item._title_comparison_key(title)
        for title in (item.title, item.original_title, item.localized_title)
    } - {""}
    # No real title on one side, or Floppy only knowing the show's title, is
    # not evidence of a mismatch.
    if not plex_key or not floppy_keys or show_key in floppy_keys:
        return ""
    if _GENERIC_EPISODE_TITLE.fullmatch(plex_key) or any(
        _GENERIC_EPISODE_TITLE.fullmatch(key) for key in floppy_keys
    ):
        return ""
    if plex_key in floppy_keys:
        return ""
    return "Episode titles differ between Floppy and Plex"
