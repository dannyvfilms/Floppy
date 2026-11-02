"""WeTrakr as a batching destination: dated plays, statuses and ratings.

Written against an unofficial transcription of WeTrakr's documentation (see
``integrations.wetrakr_api``). The shapes of WeTrakr's replies to a batch are
the least certain part, so the parsing here is deliberately cautious: a reply
it does not recognise is retried, never counted as delivered, and a count of
rejected items it cannot match to an item sends the whole request round again
(WeTrakr treats a repeat as "existing"). Mocked fixtures in the tests record
the assumed shapes; the first real account is what confirms them.

What this adapter will never send:

- a show-level ``watched`` status (WeTrakr would mark every episode watched);
  an episode play carries only its own season and episode;
- ``watched`` or ``watching`` as a status (a play is what makes something
  watched, and WeTrakr works out ``watching`` itself);
- anything for imported history (``ACCEPTS_IMPORTED_CHANGES``);
- a remove-all or remove-last call: a removal names one play, by its receipt
  or its exact date.
"""

from collections import Counter
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from app.models import MediaTypes, Sources, Status
from integrations.models import (
    CAPABILITY_PLAY_PUSH,
    CAPABILITY_PLAY_REMOVE,
    CAPABILITY_RATING_PUSH,
    CAPABILITY_STATUS_PUSH,
    WeTrakrAccount,
)
from integrations.state.adapters.base import (
    BATCH_DELIVERED,
    BATCH_FAILED,
    BATCH_RETRY,
    BATCH_SKIPPED,
    AdapterError,
    BatchResult,
    TerminalAdapterError,
)
from integrations.wetrakr_api import WeTrakrClient

MOVIE_STATUSES = {
    Status.PLANNING.value: "planning",
    Status.DROPPED.value: "dropped",
}
SHOW_STATUSES = {
    Status.PLANNING.value: "planning",
    Status.PAUSED.value: "paused",
    Status.DROPPED.value: "dropped",
}
RESPONSE_KEYS = ("added", "existing", "notFound", "errored")
MAX_RATING = Decimal(10)


def _ref(external_id):
    """Split ``kind:id[:season:episode]`` into ``(kind, tmdb, season, episode)``."""
    kind, tmdb, *rest = external_id.split(":")
    season, episode = (int(rest[0]), int(rest[1])) if rest else (None, None)
    return kind, int(tmdb), season, episode


def _walk_refs(section):
    """Yield ``(kind, tmdb, season, episode, reason)`` for each item in a reply.

    Understands the request's own layout (movies, shows with nested seasons and
    episodes) and a flat list of entries that carry ``ids``.
    """
    if isinstance(section, list):
        for entry in section:
            yield from _walk_refs({"movies": [entry]} if _is_entry(entry) else entry)
        return
    if not isinstance(section, dict):
        return
    for key, kind in (("movies", "movie"), ("shows", "show")):
        entries = section.get(key)
        for entry in entries if isinstance(entries, list) else []:
            if not _is_entry(entry):
                continue
            reason = _reason(entry)
            tmdb = entry["ids"]["tmdb"]
            seasons = entry.get("seasons") or []
            if not seasons:
                yield kind, int(tmdb), None, None, reason
            for season in seasons:
                for episode in season.get("episodes") or []:
                    yield (
                        "episode",
                        int(tmdb),
                        season.get("number"),
                        episode.get("number"),
                        _reason(episode) or reason,
                    )


def _instant(value):
    """Return a moment for an ISO timestamp, or None when it is absent or odd."""
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _is_entry(entry):
    ids = entry.get("ids") if isinstance(entry, dict) else None
    return isinstance(ids, dict) and str(ids.get("tmdb", "")).isdigit()


def _reason(entry):
    error = entry.get("error") or entry.get("reason") or entry.get("message") or ""
    if isinstance(error, dict):
        error = error.get("message") or error.get("code") or ""
    return str(error)


def _counted(section):
    """Return how many items a reply section claims, when it only gives counts."""
    if isinstance(section, int):
        return section
    if isinstance(section, dict):
        return sum(v for v in section.values() if isinstance(v, int))
    return 0


class WeTrakrAdapter:
    """Send plays, statuses and ratings to one connected WeTrakr account."""

    CAPABILITIES = frozenset(
        {
            CAPABILITY_PLAY_PUSH,
            CAPABILITY_PLAY_REMOVE,
            CAPABILITY_STATUS_PUSH,
            CAPABILITY_RATING_PUSH,
        },
    )
    # Well under WeTrakr's 5,000 items / 1 MB per request.
    BATCH_SIZE = 1000
    # WeTrakr shows a play as activity on the date it is sent, so imported
    # history only goes out through the explicit "Send existing library".
    ACCEPTS_IMPORTED_CHANGES = False

    def __init__(self, account):
        """Use one connected account."""
        self.account = account
        self.client = WeTrakrClient(account)

    def resolve_external_id(self, item):
        """Use native TMDB identities only; WeTrakr is told the type explicitly."""
        if item.source != Sources.TMDB.value or getattr(item, "episode_order_id", None):
            return None
        if not str(item.media_id).isdigit():
            return None
        if item.media_type == MediaTypes.MOVIE.value:
            return f"movie:{item.media_id}"
        if item.media_type == MediaTypes.TV.value:
            return f"show:{item.media_id}"
        if (
            item.media_type == MediaTypes.EPISODE.value
            and item.season_number is not None
            and item.season_number >= 0
            and item.episode_number is not None
            and item.episode_number > 0
        ):
            return f"episode:{item.media_id}:{item.season_number}:{item.episode_number}"
        return None

    def normalize_rating(self, score):
        """Use one decimal on WeTrakr's 0 to 10 scale; None stays a clear."""
        if score is None:
            return None
        rounded = Decimal(str(score)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        return max(Decimal(0), min(MAX_RATING, rounded))

    # --- building requests ---------------------------------------------------

    def _plan(self, items):
        """Sort items into the three requests; return skipped results by index."""
        tracking = {"movies": [], "shows": {}, "show_statuses": []}
        rated, cleared = {"movies": [], "shows": []}, {"movies": [], "shows": []}
        groups = {"tracking": [], "rated": [], "cleared": []}
        results = {}

        for index, item in enumerate(items):
            kind, tmdb, season, episode = _ref(item.external_id)
            ids = {"tmdb": tmdb}
            if item.operation == "play":
                watched_at = item.payload.get("watched_at")
                if not watched_at:
                    results[index] = BatchResult(
                        BATCH_FAILED,
                        error="The play has no date.",
                    )
                elif kind == "movie":
                    tracking["movies"].append(
                        {"ids": ids, "status": "watched", "tracked_at": watched_at},
                    )
                    groups["tracking"].append(index)
                elif kind == "episode":
                    show = tracking["shows"].setdefault(tmdb, {})
                    show.setdefault(season, []).append(
                        {
                            "number": episode,
                            "status": "watched",
                            "tracked_at": watched_at,
                        },
                    )
                    groups["tracking"].append(index)
                else:
                    results[index] = BatchResult(
                        BATCH_SKIPPED,
                        error="WeTrakr plays are for movies and episodes.",
                    )
            elif item.operation == "status":
                mapped = (MOVIE_STATUSES if kind == "movie" else SHOW_STATUSES).get(
                    item.payload.get("status"),
                )
                if kind not in {"movie", "show"} or mapped is None:
                    results[index] = BatchResult(
                        BATCH_SKIPPED,
                        error="WeTrakr works this status out from your plays.",
                    )
                elif kind == "movie":
                    tracking["movies"].append({"ids": ids, "status": mapped})
                    groups["tracking"].append(index)
                else:
                    # Its own entry, never combined with nested episodes: a
                    # status beside seasons would be ambiguous.
                    tracking["show_statuses"].append({"ids": ids, "status": mapped})
                    groups["tracking"].append(index)
            elif item.operation == "rating":
                if kind == "episode":
                    results[index] = BatchResult(
                        BATCH_SKIPPED,
                        error="Episode ratings are not sent to WeTrakr yet.",
                    )
                    continue
                target = rated if item.rating is not None else cleared
                entry = {"ids": ids}
                if item.rating is not None:
                    entry["rating"] = float(item.rating)
                target["movies" if kind == "movie" else "shows"].append(entry)
                groups["rated" if item.rating is not None else "cleared"].append(index)
            elif item.operation != "play_remove":  # sent one by one in write_batch
                results[index] = BatchResult(
                    BATCH_SKIPPED,
                    error="This kind of change is not sent to WeTrakr.",
                )
        return tracking, rated, cleared, groups, results

    @staticmethod
    def _tracking_body(tracking):
        shows = [
            {
                "ids": {"tmdb": tmdb},
                "seasons": [
                    {"number": number, "episodes": episodes}
                    for number, episodes in seasons.items()
                ],
            }
            for tmdb, seasons in tracking["shows"].items()
        ]
        return {
            "movies": tracking["movies"],
            "shows": shows + tracking["show_statuses"],
        }

    # --- sending -------------------------------------------------------------

    def write_batch(self, items, *, idempotency_key):
        """Send up to three requests and report each item on its own."""
        tracking, rated, cleared, groups, results = self._plan(items)
        requests_to_send = [
            ("/sync/tracking", self._tracking_body(tracking), groups["tracking"]),
            ("/sync/ratings", rated, groups["rated"]),
            ("/sync/ratings/remove", cleared, groups["cleared"]),
        ]
        errors = []
        sent = 0
        for path, body, indexes in requests_to_send:
            if not indexes:
                continue
            sent += 1
            try:
                reply = self.client.request(
                    "POST",
                    path,
                    json=body,
                    idempotency_key=f"{idempotency_key}{path.replace('/', '-')}",
                )
            except AdapterError as error:
                errors.append(error)
                outcome = (
                    BATCH_FAILED
                    if isinstance(error, TerminalAdapterError)
                    else BATCH_RETRY
                )
                for index in indexes:
                    results[index] = BatchResult(outcome, error=str(error))
                continue
            self._read_reply(path, reply, items, indexes, results)

        for index, item in enumerate(items):
            if item.operation != "play_remove":
                continue
            sent += 1
            try:
                results[index] = self._remove_play(item)
            except AdapterError as error:
                errors.append(error)
                outcome = (
                    BATCH_FAILED
                    if isinstance(error, TerminalAdapterError)
                    else BATCH_RETRY
                )
                results[index] = BatchResult(outcome, error=str(error))

        if errors and len(errors) == sent:
            # Nothing was applied, so let the engine retry the whole request.
            raise errors[0]
        return [
            results.get(index) or BatchResult(BATCH_RETRY, error="No result")
            for index in range(len(items))
        ]

    def _remove_play(self, item):
        """Remove exactly one play: by its receipt, else by its exact date.

        Never the latest play and never all of them, whatever is left on the
        account. A play WeTrakr no longer has counts as removed.
        """
        receipt = item.payload.get("receipt")
        if receipt:
            self.client.request(
                "DELETE",
                f"/sync/tracklogs/{receipt}",
                missing_ok=True,
            )
            return BatchResult(BATCH_DELIVERED)

        kind, tmdb, season, episode = _ref(item.external_id)
        watched_at = item.payload.get("watched_at")
        if not watched_at or kind not in {"movie", "episode"}:
            return BatchResult(BATCH_FAILED, error="The play cannot be identified.")
        entry = {"status": "watched", "tracked_at": watched_at}
        if kind == "movie":
            body = {"movies": [{"ids": {"tmdb": tmdb}, **entry}]}
        else:
            body = {
                "shows": [
                    {
                        "ids": {"tmdb": tmdb},
                        "seasons": [
                            {
                                "number": season,
                                "episodes": [{"number": episode, **entry}],
                            },
                        ],
                    },
                ],
            }
        reply = self.client.request(
            "POST",
            "/sync/tracking/remove",
            json=body,
            idempotency_key=f"remove-{item.delivery_id}",
        )
        if any(_walk_refs(reply.get("notFound"))):
            return BatchResult(BATCH_SKIPPED, error="WeTrakr had no such play.")
        if any(_walk_refs(reply.get("errored"))):
            return BatchResult(BATCH_FAILED, error="WeTrakr rejected the removal.")
        return BatchResult(BATCH_DELIVERED)

    def _read_reply(self, path, reply, items, indexes, results):
        """Turn one reply into per-item results for the items it covered."""
        if not any(key in reply for key in RESPONSE_KEYS):
            message = "WeTrakr sent a reply this version of Floppy does not understand."
            for index in indexes:
                results[index] = BatchResult(BATCH_RETRY, error=message)
            return

        by_ref = {}
        for index in indexes:
            by_ref.setdefault(_ref(items[index].external_id), []).append(index)

        rejected = {}
        for key, outcome, text in (
            ("notFound", BATCH_SKIPPED, "WeTrakr could not find this title."),
            ("errored", BATCH_FAILED, "WeTrakr rejected this item."),
        ):
            section = reply.get(key)
            found = False
            for kind, tmdb, season, episode, reason in _walk_refs(section):
                found = True
                for index in by_ref.get((kind, tmdb, season, episode), []):
                    rejected[index] = BatchResult(
                        outcome,
                        error=f"{text} {reason}".strip(),
                    )
            if not found and _counted(section):
                # It says some were rejected but not which: send them all again.
                message = f"WeTrakr rejected {_counted(section)} items."
                for index in indexes:
                    rejected.setdefault(index, BatchResult(BATCH_RETRY, error=message))

        dated, undated = self._receipts(reply.get("added"))
        asked = Counter(
            _ref(items[i].external_id)
            for i in indexes
            if items[i].operation == "play" and i not in rejected
        )
        for index in indexes:
            item = items[index]
            if index in rejected:
                results[index] = rejected[index]
                continue
            receipt = ""
            if item.operation == "play":
                ref = _ref(item.external_id)
                # Two plays of one title at one instant each take their own id.
                same_time = dated.get(
                    (ref, _instant(item.payload.get("watched_at"))),
                    [],
                )
                receipt = same_time.pop(0) if same_time else ""
                if not receipt and asked[ref] == 1 and len(undated.get(ref, [])) == 1:
                    # The reply named the play but not its date, and only one
                    # play of this title was sent, so there is no mix-up.
                    receipt = undated[ref][0]
            results[index] = BatchResult(BATCH_DELIVERED, receipt=receipt)

    @staticmethod
    def _receipts(added):
        """Return the ids WeTrakr gave new plays, by title and date.

        The second map holds plays the reply named without a date.
        """
        dated, undated = {}, {}
        plays = added.get("plays") if isinstance(added, dict) else None
        for play in plays or []:
            if not isinstance(play, dict) or not play.get("play_id"):
                continue
            ids = play.get("ids") or {}
            tmdb = ids.get("tmdb")
            if not str(tmdb or "").isdigit():
                continue
            kind = "episode" if play.get("episode") is not None else "movie"
            ref = (kind, int(tmdb), play.get("season"), play.get("episode"))
            when = _instant(play.get("tracked_at"))
            if when is None:
                undated.setdefault(ref, []).append(str(play["play_id"]))
            else:
                dated.setdefault((ref, when), []).append(str(play["play_id"]))
        return dated, undated


def build_adapter(binding):
    """Return an adapter only for the exact connected WeTrakr login."""
    account = WeTrakrAccount.objects.filter(
        user=binding.user,
        profile_key=binding.profile_key,
    ).first()
    if account is None or not account.refresh_token:
        return None
    return WeTrakrAdapter(account)
