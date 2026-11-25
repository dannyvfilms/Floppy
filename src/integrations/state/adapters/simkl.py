"""SIMKL as a batching destination: dated plays only.

SIMKL's history is a list of what was watched and when, so this sends plays and
nothing else. Statuses, ratings and removals are left for a later change on
purpose:

- a removal without an episode named removes the whole title from the user's
  SIMKL library, so an ordinary local delete is never sent;
- planning and in-progress items are not watch events, so they are never sent
  as watched;
- rewatch sessions need ``allow_rewatch=yes`` and a paid SIMKL plan, and a
  closer-than-two-days repeat is silently absorbed, so a repeat play of the
  same title is simply a no-op there and is never retried as a failure.

What this adapter always does:

- sends every episode under ``seasons[].episodes[]`` with its numbers, never a
  show or a season on its own (SIMKL would mark all of its episodes watched);
- sends each play's real ``watched_at``; a play with no date is left out unless
  the user chose to send it with SIMKL's "I don't remember" date;
- reads ``not_found`` in the reply, so a title SIMKL could not match is reported
  against its own delivery instead of counted as sent;
- never sends imported history (``ACCEPTS_IMPORTED_CHANGES``): a play imported
  from SIMKL itself would be sent straight back. History goes out only through
  "Send existing library".
"""

from integrations.models import CAPABILITY_PLAY_PUSH, SimklAccount
from integrations.simkl_api import SimklClient
from integrations.state.adapters.base import (
    BATCH_DELIVERED,
    BATCH_FAILED,
    BATCH_RETRY,
    BATCH_SKIPPED,
    BatchResult,
)
from integrations.state.references import parse_reference, tmdb_reference

#: SIMKL's own value for "I watched this a long time ago / I don't remember".
UNDATED_WATCHED_AT = "1970-01-01T00:00:01Z"


def _tmdb(entry):
    """Return the TMDB id of a reply entry, or None."""
    ids = entry.get("ids") if isinstance(entry, dict) else None
    value = ids.get("tmdb") if isinstance(ids, dict) else None
    return int(value) if str(value or "").isdigit() else None


def _missing(not_found):
    """Return what SIMKL could not match, as two sets.

    The first holds movie ids; the second holds ``(show, season, episode)``,
    where season and episode are None when the whole show was not found.
    """
    movies, episodes = set(), set()
    if not isinstance(not_found, dict):
        return movies, episodes
    for entry in not_found.get("movies") or []:
        if _tmdb(entry) is not None:
            movies.add(_tmdb(entry))
    for key in ("shows", "episodes"):
        for entry in not_found.get(key) or []:
            show = _tmdb(entry)
            if show is None:
                continue
            seasons = entry.get("seasons") or []
            listed = False
            for season in seasons:
                for episode in season.get("episodes") or []:
                    episodes.add((show, season.get("number"), episode.get("number")))
                    listed = True
            if not listed:
                if entry.get("season") is not None and entry.get("number") is not None:
                    episodes.add((show, entry["season"], entry["number"]))
                else:
                    episodes.add((show, None, None))
    return movies, episodes


class SimklAdapter:
    """Send plays to one connected SIMKL account."""

    CAPABILITIES = frozenset({CAPABILITY_PLAY_PUSH})
    # SIMKL accepts up to 20,000 items a request; stay far below it.
    BATCH_SIZE = 500
    ACCEPTS_IMPORTED_CHANGES = False

    def __init__(self, account):
        """Use one connected account."""
        self.account = account
        self.client = SimklClient(account)

    def resolve_external_id(self, item):
        """Use native TMDB identities only; SIMKL is told the type explicitly."""
        reference = tmdb_reference(item)
        # A show on its own is never a play: it would mean every episode.
        return None if reference and reference.startswith("show:") else reference

    def _watched_at(self, payload):
        """Return the date to send, or None when the play is to be left out."""
        watched_at = payload.get("watched_at")
        if watched_at:
            return watched_at
        return UNDATED_WATCHED_AT if self.account.send_undated else None

    def write_batch(self, items, *, idempotency_key):
        """Send one request for every play and report each on its own."""
        results = {}
        movies, shows, sent = [], {}, []
        for index, item in enumerate(items):
            if item.operation != "play":
                results[index] = BatchResult(
                    BATCH_SKIPPED,
                    error="Only plays are sent to SIMKL.",
                )
                continue
            watched_at = self._watched_at(item.payload)
            if watched_at is None:
                results[index] = BatchResult(
                    BATCH_SKIPPED,
                    error="The play has no date, and sending undated plays is off.",
                )
                continue
            kind, tmdb, season, episode = parse_reference(item.external_id)
            if kind == "movie":
                movies.append({"ids": {"tmdb": tmdb}, "watched_at": watched_at})
            elif kind == "episode":
                shows.setdefault(tmdb, {}).setdefault(season, []).append(
                    {"number": episode, "watched_at": watched_at},
                )
            else:
                results[index] = BatchResult(
                    BATCH_SKIPPED,
                    error="SIMKL plays are for movies and episodes.",
                )
                continue
            sent.append((index, kind, tmdb, season, episode))

        if sent:
            self._send(items, sent, movies, shows, results)
        return [
            results.get(index) or BatchResult(BATCH_RETRY, error="No result")
            for index in range(len(items))
        ]

    def _send(self, items, sent, movies, shows, results):
        body = {
            "movies": movies,
            "shows": [
                {
                    "ids": {"tmdb": tmdb},
                    "seasons": [
                        {"number": number, "episodes": episodes}
                        for number, episodes in seasons.items()
                    ],
                }
                for tmdb, seasons in shows.items()
            ],
        }
        # A failed request raises, and the engine retries or records it for the
        # whole batch: nothing was applied that we know of, and a rejected login
        # is rejected for every item.
        reply = self.client.request("POST", "/sync/history", json=body)

        if not isinstance(reply, dict) or not isinstance(reply.get("added"), dict):
            # An unrecognised reply is never counted as delivered.
            for index, *_ in sent:
                results[index] = BatchResult(
                    BATCH_RETRY,
                    error="SIMKL sent a reply Floppy does not recognise.",
                )
            return
        missing_movies, missing_episodes = _missing(reply.get("not_found"))
        missing_shows = {show for show, season, _ in missing_episodes if season is None}
        for index, kind, tmdb, season, episode in sent:
            absent = (
                tmdb in missing_movies
                if kind == "movie"
                else (tmdb, season, episode) in missing_episodes
                or tmdb in missing_shows
            )
            results[index] = (
                BatchResult(
                    BATCH_FAILED,
                    error="SIMKL could not find this title.",
                )
                if absent
                else BatchResult(BATCH_DELIVERED)
            )


def build_adapter(binding):
    """Return an adapter only for the exact connected SIMKL login."""
    account = SimklAccount.objects.filter(
        user=binding.user,
        profile_key=binding.profile_key,
    ).first()
    if account is None or not account.refresh_token:
        return None
    return SimklAdapter(account)
