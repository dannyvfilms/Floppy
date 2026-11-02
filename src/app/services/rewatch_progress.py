"""Read-only, occurrence-ordered rewatch runs for the detail progress displays.

Tracking status deliberately does not depend on this interpretation. Canceled
and superseded runs still consume their continuations while replaying history.
"""

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from itertools import groupby

from app.models import Episode, RewatchCancellation, Status

CONFIRMATION_EPISODES = 2

@dataclass
class RewatchRun:
    """One scope's restart and the first witness for each replayed episode."""

    keys: tuple
    anchor: datetime
    season_number: int | None
    plays: dict = field(default_factory=dict)
    anchor_plays: dict = field(default_factory=dict)
    explicit: bool = False
    explicit_completed: set = field(default_factory=set)

    def record(self, row):
        """Retain prefix witnesses and duplicate anchors for stable cancellation."""
        key = (row[1], row[2])
        self.plays.setdefault(key, row)
        if key == self.keys[0]:
            self.anchor_plays[row[0]] = row

    @property
    def completed(self):
        """Only a gap-free prefix advances an inferred run."""
        if self.explicit:
            return self.explicit_completed
        result = set()
        for key in self.keys:
            if key not in self.plays:
                break
            result.add(key)
        return result

    @property
    def next_key(self):
        """The next logical continuation, even when this run is suppressed."""
        done = len(self.completed)
        return self.keys[done] if done < len(self.keys) else None

    @property
    def key(self):
        """Stable across added duplicate plays and later continuations."""
        scope = f"explicit:{self.keys}" if self.explicit else str(self.season_number)
        return sha256(f"{scope}:{self.anchor.isoformat()}".encode()).hexdigest()

    @property
    def evidence(self):
        """Keep occurrence identities as well as row ids for cancellation."""
        witnesses = {row[0]: row for row in self.plays.values()} | self.anchor_plays
        return [
            {"id": row[0], "season": row[1], "episode": row[2], "at": row[3].isoformat()}
            for row in witnesses.values()
        ]


def tracking_order_key(tv):
    """Isolate cancellations to the current tracking catalogue."""
    return f"order:{tv.active_episode_order_id}" if tv.active_episode_order_id else f"item:{tv.item_id}"


def _cancelled(run, cancellations):
    for cancellation in cancellations:
        if cancellation.run_key == run.key:
            return True
        # Backfilling an earlier duplicate can move the anchor, but two shared
        # episode witnesses still identify the same run, even if catalogue
        # growth changes a whole-show interpretation into a season scope.
        # A fresh restart has fresh witnesses and cannot match this test.
        old = {
            (ep["season"], ep["episode"], ep["at"])
            for ep in cancellation.evidence
        }
        overlap = {
            (ep["season"], ep["episode"])
            for ep in run.evidence
            if (ep["season"], ep["episode"], ep["at"]) in old
        }
        if len(overlap) >= CONFIRMATION_EPISODES:
            return True
    return False


def _infer_runs(keys, rows, *, include_candidates=False):
    """Replay occurrence history; retain old runs to recognize continuations."""
    scopes = {}
    for key in keys:
        scopes.setdefault(key[0], []).append(key)
    scopes = {number: tuple(values) for number, values in scopes.items()}
    seen = set()
    runs = []
    candidates = {}
    for at, batch in groupby(rows, key=lambda row: row[3]):
        batch_seen = set()
        for row in batch:
            key = (row[1], row[2])
            if key not in keys:
                continue
            batch_seen.add(key)
            owners = [run for run in reversed(runs) if key in run.keys]
            expected = next((run for run in owners if run.next_key == key), None)
            confirmed = False
            for scope, candidate in list(candidates.items()):
                if key not in candidate.keys:
                    continue
                candidate.record(row)
                first = candidate.keys[0]
                absorbed = any(
                    first in run.completed
                    and run.plays.get(first) == candidate.plays[first]
                    for run in runs
                )
                if absorbed:
                    del candidates[scope]
                elif len(candidate.completed) >= CONFIRMATION_EPISODES:
                    runs.append(candidate)
                    del candidates[scope]
                    confirmed = True
            if confirmed:
                # An old unconfirmed shuffle cannot become "newest" merely
                # because its missing second episode is played years later.
                candidates = {
                    scope: candidate for scope, candidate in candidates.items()
                    if candidate.anchor > runs[-1].anchor
                }
                continue
            if expected is not None:
                expected.record(row)
                continue
            season_keys = scopes[key[0]]
            if key == season_keys[0]:
                scope = key[0]
                scope_keys = season_keys
                if key == keys[0] and set(keys) <= seen:
                    scope, scope_keys = None, keys
                if len(scope_keys) >= CONFIRMATION_EPISODES and set(scope_keys) <= seen:
                    if scope not in candidates:
                        candidates[scope] = RewatchRun(scope_keys, at, scope)
                    candidates[scope].record(row)
            if owners:
                owners[0].record(row)
        # Tied/date-only batches can demonstrate a replay, never an earlier
        # watch of another occurrence in that very same batch.
        seen.update(batch_seen)
    latest = runs[-1] if runs else None
    if include_candidates:
        pending = max(candidates.values(), key=lambda run: run.anchor, default=None)
        if pending is not None and (latest is None or pending.anchor > latest.anchor):
            return pending
    return latest


def resolve_rewatch(tv, seasons, *, include_explicit=True, include_candidates=False):
    """Resolve the latest run using the catalogue already loaded by breakdown.

    One narrow history query; no Item instances or library prefetch changes.
    ``seasons`` are SeasonProgress objects with their tracked model attached.
    """
    eligible = [season for season in seasons if season.counts_toward_overall]
    keys = tuple(
        (season.number, episode["number"])
        for season in eligible for episode in season.counted
    )
    tracked = [season.tracker for season in seasons if season.tracker is not None]
    if include_explicit:
        open_seasons = [season for season in seasons if season.tracker and season.tracker.is_rewatching]
        if open_seasons:
            explicit_keys = tuple(
                (season.number, episode["number"])
                for season in open_seasons for episode in season.counted
            )
            return RewatchRun(
                explicit_keys,
                min(season.tracker.rewatch_started_at for season in open_seasons),
                open_seasons[0].number if len(open_seasons) == 1 else None,
                explicit=True,
                explicit_completed={
                    (season.number, episode["number"])
                    for season in open_seasons
                    for episode in season.episodes if episode["rewatched"]
                },
            )
    if not keys or any(season.catalogue_missing for season in seasons if not season.is_specials):
        return None
    rows = (
        Episode.objects.filter(
            related_season_id__in=[season.pk for season in tracked],
            status=Status.COMPLETED.value,
            end_date__isnull=False,
        )
        .order_by("end_date", "item__season_number", "item__episode_number", "pk")
        .values_list("pk", "item__season_number", "item__episode_number", "end_date")
        .iterator(chunk_size=1000)
    )
    run = _infer_runs(keys, rows, include_candidates=include_candidates)
    if run is None or len(run.completed) == len(run.keys):
        return None
    cancellations = RewatchCancellation.objects.filter(tv=tv, order_key=tracking_order_key(tv))
    return None if _cancelled(run, cancellations) else run


def cancel_run(tv, run):
    """Save a run interpretation, never delete plays or alter inferred status."""
    return RewatchCancellation.objects.get_or_create(
        tv=tv,
        order_key=tracking_order_key(tv),
        run_key=run.key,
        defaults={
            "season_number": run.season_number,
            "anchor": run.anchor,
            "evidence": run.evidence,
        },
    )[0]
