"""Import a Netflix "viewing activity" CSV.

Netflix's export is a two-column, local-language CSV (``Title,Date``) with
no media type, no provider IDs and, for episodes, the season/episode encoded
in the title text.  German rows look like
``"Weeds - Kleine Deals unter Nachbarn: Staffel 8: Es ist Zeit: Teil 2"``
or ``"…: Folge 5"``; English rows use the same structure with ``Season`` /
``Episode`` / ``Limited Series`` / ``Part`` (``"Weeds: Season 8: It's Time"``).
Every row is therefore resolved by TMDB title search the same way TV Time's
import does (see tvtime.py).

Plays are idempotent per (item, day), so re-importing the same file never
doubles a play.  Series rows that carry a season but no episode number are
matched against the TMDB season's episode titles before giving up; rows that
still cannot be resolved automatically (no TMDB hit, an unparseable date, or
genuine ambiguity between candidates) are saved as ``NetflixPendingRow`` for
the interactive review page instead of dropped.
"""

import logging
import re
from csv import DictReader
from datetime import datetime, time
from difflib import SequenceMatcher

from billiard.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.utils import timezone

import app
from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Movie,
    Season,
    Sources,
    Status,
)
from app.providers import services
from integrations import import_progress
from integrations.imports.helpers import MediaImportError
from integrations.imports.trakt import TraktMetadataResolverMixin
from integrations.matching import normalize_title, title_matches
from integrations.models import NetflixPendingRow

logger = logging.getLogger(__name__)

# Labels that mark a row as a series episode, in German and English.  They
# are matched as whole words so a movie title that merely contains one of
# the words stays a movie.
_SEASON_RE = re.compile(r"\b(?:staffel|season)\s*(\d+)", re.IGNORECASE)
_EPISODE_RE = re.compile(r"\b(?:folge|episode)\s*(\d+)", re.IGNORECASE)
# A standalone "Part N"/"Teil N" segment names a season (Disenchantment,
# Inside Job); after a known season it names a part of one episode instead
# ("It's Time: Part 2") and is ignored.
_PART_SEGMENT_RE = re.compile(r"^(?:teil|part)\s*(\d+)$", re.IGNORECASE)
# Netflix labels anthology seasons as "Volume N" (Love, Death & Robots);
# like a part segment it only counts as a season with a trailing segment,
# so a two-part movie title keeps its movie status.
_VOL_SEGMENT_RE = re.compile(r"^volume\s*(\d+)$", re.IGNORECASE)
# A whole segment that is one of the labels, e.g. "Season 8", "Limited
# Series" or "Part 5".  Used to find the series prefix and the episode
# title; "Part N"/"Teil N"/"Volume N" are included because they carry the
# season.
_SEGMENT_MARKER_RE = re.compile(
    r"^(?:staffel|season|folge|episode|miniserie|limited series|teil|part)\b",
    re.IGNORECASE,
)
# A standalone "Part N"/"Teil N" or "Volume N" segment names a season and
# needs something after it; two segments could be a two-part movie title.
_STANDALONE_SEASON_MIN_SEGMENTS = 3
# A movie whose TMDB title continues the Netflix title with a part label
# only ("Mission: Impossible - Dead Reckoning" for "... Dead Reckoning
# Part One").
_PART_CONTINUATION_RE = re.compile(
    r"^(?:part|teil)\s*(?:\d+|one|two|three|four|five|six)$",
    re.IGNORECASE,
)
# Review-page search results: enough to pick from, few enough to stay one
# TMDB round-trip.
SEARCH_RESULT_LIMIT = 8
# The named-season chain's fuzzy episode bar: the closest-named episode in
# one season must clear the threshold and beat the runner-up.  Calibration
# knobs for provider name drift ("&" vs "and", dropped articles) — tighten
# them if false records ever show up.
FUZZY_EPISODE_THRESHOLD = 0.8
FUZZY_EPISODE_MARGIN = 0.1

# Netflix dates are slash-separated (M/D/YY or D/M/YY); a two-digit year is
# rolled to the 1900s at/above this pivot and to the 2000s below it.
_DATE_PARTS = 3
_MONTH_MAX = 12
_TWO_DIGIT_YEAR_MAX = 99
_YEAR_CENTURY_PIVOT = 70


def _decode_csv(file):
    """Decode an uploaded CSV file's bytes, tolerating non-UTF-8 exports."""
    raw_file = file.read()
    try:
        return raw_file.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError:
        return raw_file.decode("latin-1").splitlines()


def _normalize_rows(rows):
    """Map localized headers (e.g. German ``Titel,Datum``) onto Title/Date."""
    if not rows:
        return rows
    header_map = {}
    for key in rows[0]:
        if key is None:
            continue
        lowered = key.strip().casefold()
        if lowered in ("title", "titel"):
            header_map[key] = "Title"
        elif lowered in ("date", "datum"):
            header_map[key] = "Date"
    if not header_map:
        return rows
    return [
        {header_map.get(key, key): value for key, value in row.items() if key is not None}
        for row in rows
    ]


def _detect_date_layout(dates):
    """Guess ``mdy`` vs ``dmy`` from any component that can only be a day.

    Netflix exports dates in the account's locale, both two-digit
    (``11/20/26``) and single-digit (``10/7/18``).  When neither component
    ever exceeds 12 the file is ambiguous; ``mdy`` is Netflix's US default
    and the safe pick there.
    """
    for raw in dates:
        parts = raw.split("/")
        if len(parts) != _DATE_PARTS:
            continue
        try:
            first, second = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if first > _MONTH_MAX:
            return "dmy"
        if second > _MONTH_MAX:
            return "mdy"
    return "mdy"


def _parse_netflix_date(raw, layout):
    """Parse a ``M/D/YY`` or ``D/M/YY`` date, or None when unparseable."""
    parts = [part.strip() for part in (raw or "").split("/")]
    if len(parts) != _DATE_PARTS:
        return None
    try:
        first, second, year = (int(part) for part in parts)
    except ValueError:
        return None
    if year <= _TWO_DIGIT_YEAR_MAX:
        year += 1900 if year >= _YEAR_CENTURY_PIVOT else 2000
    month, day = (first, second) if layout == "mdy" else (second, first)
    try:
        return datetime(
            year,
            month,
            day,
            tzinfo=timezone.get_current_timezone(),
        )
    except ValueError:
        return None


def _marker_segment(part, total_segments):
    """Check whether a title segment starts the coordinate part of a title.

    Numbered label segments always count; a standalone ``Part N``/``Teil
    N``/``Volume N`` counts only with a trailing segment, because two
    segments could be a two-part movie title.
    """
    if _PART_SEGMENT_RE.match(part) or _VOL_SEGMENT_RE.match(part):
        return total_segments >= _STANDALONE_SEASON_MIN_SEGMENTS
    return _SEGMENT_MARKER_RE.match(part) is not None


def _split_title(title):
    """Split a Netflix title into (query, media_type, season, episode).

    A plain title is a movie.  The first labelled segment ends the series
    name, so a show whose own name contains a colon keeps it ("Tour de
    France: Unchained: Season 3: …"); the coordinates come from the labels.
    A standalone ``Part``/``Teil``/``Volume`` segment after the series name
    is a season (``Disenchantment: Part 5: …``); ``Teil 2`` inside an
    already labelled episode names a part of that episode, not its number.
    A limited series that labels its episodes ``Part 1`` … ``Part N``
    carries the episode number there.
    """
    lowered = title.lower()
    limited_series = "miniserie" in lowered or "limited series" in lowered
    season_match = _SEASON_RE.search(title)
    episode_match = _EPISODE_RE.search(title)
    parts = [part.strip() for part in title.split(":")]
    first_marker = next(
        (
            index
            for index in range(1, len(parts))
            if _marker_segment(parts[index], len(parts))
        ),
        None,
    )
    if not limited_series and first_marker is None:
        return title, MediaTypes.MOVIE.value, None, None
    query = (
        ": ".join(parts[:first_marker]) if first_marker is not None else title
    )
    season_number = int(season_match.group(1)) if season_match else None
    if season_number is None and first_marker is not None:
        standalone = (
            _PART_SEGMENT_RE.match(parts[first_marker])
            or _VOL_SEGMENT_RE.match(parts[first_marker])
        )
        if standalone:
            season_number = int(standalone.group(1))
    if limited_series and season_number is None:
        season_number = 1
    episode_number = int(episode_match.group(1)) if episode_match else None
    if (
        episode_number is None
        and season_number == 1
        and first_marker is not None
    ):
        tail = parts[first_marker + 1 :]
        if tail and all(
            _SEGMENT_MARKER_RE.match(part) or _PART_SEGMENT_RE.match(part)
            for part in parts[first_marker:]
        ):
            # "…: Limited Series: Part 6": the part label is the episode.
            part_match = _PART_SEGMENT_RE.match(tail[-1])
            if part_match:
                episode_number = int(part_match.group(1))
    return (
        query,
        MediaTypes.TV.value,
        season_number,
        episode_number,
    )


def _episode_title(title, query):
    """Return the trailing episode title of a series row, or None.

    Drops the series prefix, the label segments (``Season 8``,
    ``Limited Series``, ``Volume 3`` …) and a trailing part-of-episode
    segment, so ``"Weeds: Season 8: It's Time: Part 2"`` yields
    ``"It's Time"``.
    """
    if query == title:
        return None
    title_parts = [part.strip() for part in title.split(":")]
    tail = title_parts[len(query.split(":")):]
    while tail and (
        _SEGMENT_MARKER_RE.match(tail[0]) or _VOL_SEGMENT_RE.match(tail[0])
    ):
        tail = tail[1:]
    if len(tail) > 1 and _PART_SEGMENT_RE.match(tail[-1]):
        tail = tail[:-1]
    return " ".join(part for part in tail if part) or None


def _normalize_match(text):
    """Alphanumerics only, so case and punctuation never block a match."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _result_id_str(result):
    """Return the provider id of one search result as a string, or None."""
    value = result.get("media_id") or result.get("id")
    return str(value) if value not in (None, "") else None


def _result_title_values(result):
    """Yield every title field a search result can carry."""
    for key in ("title", "original_title", "localized_title", "name", "original_name"):
        if result.get(key):
            yield result[key]


class NetflixResolver(TraktMetadataResolverMixin):
    """TMDB search and play recording shared by the importer and review page.

    Stands in for the Trakt-specific state the mixin would otherwise expect:
    no ``external_reference_integration``, so every lookup is a plain title
    search (the same fallback TV Time's import runs through).
    """

    def __init__(self, user, import_run_id=None):
        """Bind the resolver to a user; the mixin needs ``user`` and ``warnings``.

        ``import_run_id`` tags the rows a recorded play creates, so an undo
        can remove exactly what one import run (or its review resolutions)
        wrote.
        """
        self.user = user
        self.warnings = []
        self.import_run_id = import_run_id

    def _search_results(self, title, media_type):
        """Return page one of the provider search for a title, memoized.

        The app-level TMDB search cache makes repeat calls within one
        import cheap; the memo keeps the parsed list at hand.
        """
        if not hasattr(self, "_netflix_search_memo"):
            self._netflix_search_memo = {}
        key = (media_type, title)
        if key not in self._netflix_search_memo:
            try:
                self._netflix_search_memo[key] = services.search(
                    media_type,
                    title,
                    1,
                    source=Sources.TMDB.value,
                ).get("results", [])
            except services.ProviderAPIError:
                self._netflix_search_memo[key] = []
        return self._netflix_search_memo[key]

    def _show_seasons(self, tmdb_id):
        """Return the set of the show's season numbers, memoized."""
        if not hasattr(self, "_netflix_show_seasons"):
            self._netflix_show_seasons = {}
        if tmdb_id not in self._netflix_show_seasons:
            metadata = self._get_metadata(MediaTypes.TV.value, tmdb_id, "")
            seasons = (metadata or {}).get("related", {}).get("seasons", [])
            self._netflix_show_seasons[tmdb_id] = {
                season["season_number"]
                for season in seasons
                if season.get("season_number")
            }
        return self._netflix_show_seasons[tmdb_id]

    def _season_count(self, tmdb_id, season_number):
        """Return how many episodes TMDB lists for one season of a show."""
        if not hasattr(self, "_netflix_season_count"):
            self._netflix_season_count = {}
        key = (tmdb_id, season_number)
        if key not in self._netflix_season_count:
            metadata = self._get_metadata(MediaTypes.TV.value, tmdb_id, "")
            seasons = (metadata or {}).get("related", {}).get("seasons", [])
            entry = next(
                (
                    season
                    for season in seasons
                    if season.get("season_number") == season_number
                ),
                None,
            )
            self._netflix_season_count[key] = (
                entry.get("episode_count", 0) if entry else 0
            )
        return self._netflix_season_count[key]

    def _season_episode_names(self, tmdb_id, season_number, title="",
                              language=None):
        """Return ``{episode_number: normalized name}`` for one season.

        An empty mapping means the season is absent from the provider,
        which callers treat like a missing season.
        """
        metadata = self._get_metadata(
            MediaTypes.SEASON.value, tmdb_id, title, season_number,
            language=language,
        )
        if not metadata:
            return {}
        return {
            episode["episode_number"]: _normalize_match(
                episode.get("name") or episode.get("title") or ""
            )
            for episode in metadata.get("episodes", [])
        }

    def _match_languages(self):
        """Languages for episode-name matching, the configured one first.

        Netflix exports mix languages (German productions keep their
        German episode titles) while TMDB_LANG is one language per
        instance; the other of the two gets one extra chance, only when
        the configured language does not carry the name.
        """
        primary = settings.TMDB_LANG
        if primary in ("en", "de"):
            return (primary, "de" if primary == "en" else "en")
        return (primary,)

    def _season_names_candidates(self, tmdb_id, season_number, target,
                                  title=""):
        """Yield one season's episode names, configured language first.

        The fallback language follows only when the configured language
        does not name the target at all: a language that names it is the
        authoritative one for that row.
        """
        names = self._season_episode_names(tmdb_id, season_number, title)
        yield names
        if not names or any(name == target for name in names.values()):
            return
        for language in self._match_languages()[1:]:
            yield self._season_episode_names(
                tmdb_id, season_number, title, language,
            )

    def _episode_name_agrees(self, tmdb_id, season_number, episode_number,
                              target):
        """Whether one episode's TMDB name matches ``target``.

        The configured language decides; the fallback language gets one
        extra chance when the configured one does not name it.
        """
        if self._season_episode_names(tmdb_id, season_number).get(
            episode_number,
        ) == target:
            return True
        return any(
            self._season_episode_names(
                tmdb_id, season_number, "", language,
            ).get(episode_number)
            == target
            for language in self._match_languages()[1:]
        )

    def _seasons_for_episode(self, tmdb_id, episode_number, target):
        """Return the seasons of a show that carry episode ``episode_number``.

        With a ``target``, the episode's TMDB name must agree as well; this
        keeps a show that reuses episode numbers across seasons from
        collapsing into a guess.
        """
        seasons = []
        for season_number in sorted(self._show_seasons(tmdb_id)):
            if self._season_count(tmdb_id, season_number) < episode_number:
                continue
            if target is not None and not self._episode_name_agrees(
                tmdb_id, season_number, episode_number, target,
            ):
                continue
            seasons.append(season_number)
        return seasons

    def _part_continuation_matches(self, title):
        """Match a movie title that TMDB only lists with a part suffix.

        Netflix drops the part label ("Mission: Impossible - Dead
        Reckoning") while TMDB keeps it ("… Part One"); a unique result
        that continues the title with nothing but a part label is the
        same work, so it may be recorded.
        """
        normalized = normalize_title(title)
        matches = []
        for result in self._search_results(title, MediaTypes.MOVIE.value):
            for candidate_title in _result_title_values(result):
                candidate = normalize_title(candidate_title)
                if (
                    candidate.startswith(normalized)
                    and _PART_CONTINUATION_RE.match(
                        candidate[len(normalized):].lstrip(),
                    )
                ):
                    matches.append(result)
                    break
        return matches

    def _match_unlabelled_episode(self, query):
        """Match a colon-titled row that no movie search can find.

        Anthology docuseries export their parts as "Show: Part title"
        without season or episode labels.  The show is found by the title
        before the last segment; the dropped segment must name a unique
        episode across all of the show's seasons, so a movie whose name
        happens to contain a colon can only ever become a play if the
        episode name is an exact, unambiguous match.
        """
        parts = [part.strip() for part in query.split(":")]
        prefix, dropped = ": ".join(parts[:-1]), parts[-1]
        matches = title_matches(
            self._search_results(prefix, MediaTypes.TV.value), prefix,
        )
        if len(matches) != 1:
            return None
        tmdb_id = _result_id_str(matches[0])
        target = _normalize_match(dropped)
        found = []
        for language in self._match_languages():
            found = []
            for season_number in sorted(self._show_seasons(tmdb_id)):
                for episode_number, name in self._season_episode_names(
                    tmdb_id, season_number, "", language,
                ).items():
                    if name == target:
                        found.append((season_number, episode_number))
            if found:
                break
        if len(found) != 1:
            return None
        return tmdb_id, MediaTypes.TV.value, *found[0]

    def _match_named_season_episode(self, query):
        """Match a "Show: SeasonName: EpisodeTitle" row without markers.

        Anime and docuseries name their seasons instead of numbering them
        ("Food Wars!: Shokugeki no Soma: The Second Plate: …"), which the
        movie path can never find.  The show must be a unique exact title
        match and the season name a unique match among the show's named
        seasons; the episode then has to be an exact, or the clearly best
        fuzzy, match within that one season.  A split with a unique show
        and season keeps that season for the review page even when no
        episode qualifies.
        """
        parts = [part.strip() for part in query.split(":")]
        for split in range(len(parts) - 2, 0, -1):
            prefix = ": ".join(parts[:split])
            season_name = parts[split]
            episode_title = " ".join(parts[split + 1:])
            matches = title_matches(
                self._search_results(prefix, MediaTypes.TV.value), prefix,
            )
            if len(matches) != 1:
                continue
            tmdb_id = _result_id_str(matches[0])
            metadata = self._get_metadata(MediaTypes.TV.value, tmdb_id, "")
            seasons = (metadata or {}).get("related", {}).get("seasons", [])
            target = _normalize_match(season_name)
            hits = {
                season["season_number"]
                for season in seasons
                if season.get("season_number")
                and _normalize_match(
                    season.get("season_title") or "",
                ) == target
            }
            if len(hits) != 1:
                continue
            season_number = hits.pop()
            episode_number = self._fuzzy_episode_number(
                tmdb_id, season_number, episode_title,
            )
            return tmdb_id, MediaTypes.TV.value, season_number, episode_number
        return None

    def _fuzzy_episode_number(self, tmdb_id, season_number, episode_title):
        """Match one episode title inside one season, exact or clearly best."""
        if not episode_title:
            return None
        target = _normalize_match(episode_title)
        names = None
        for names in self._season_names_candidates(
            tmdb_id, season_number, target,
        ):
            exact = {
                number for number, name in names.items() if name == target
            }
            if exact:
                return exact.pop() if len(exact) == 1 else None
        if not names:
            return None
        scored = sorted(
            (
                (SequenceMatcher(None, target, name).ratio(), number)
                for number, name in names.items()
            ),
            reverse=True,
        )
        best_score, best_number = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        if (
            best_score >= FUZZY_EPISODE_THRESHOLD
            and best_score - runner_up >= FUZZY_EPISODE_MARGIN
        ):
            return best_number
        return None

    def resolve_row(self, title, query, media_type, season_number,
                    episode_number):
        """Resolve one row to a TMDB work with safe, narrow shortcuts.

        Returns ``(tmdb_id, media_type, season_number, episode_number)``
        or None.  A unique exact title match is always used.  Otherwise
        four non-guessing shortcuts apply: a known season disambiguates
        same-title shows (a show without that season cannot hold the
        row), a movie title missing only its part suffix matches the
        unique result that continues it, a series row with an episode
        number but no season is matched to the single season that
        carries it, and a colon-titled row no movie search can find may
        be an unlabelled anthology episode.
        """
        if (
            media_type == MediaTypes.TV.value
            and season_number is None
            and episode_number is None
        ):
            return None
        matches = title_matches(self._search_results(query, media_type), query)
        if not matches and media_type == MediaTypes.MOVIE.value:
            matches = self._part_continuation_matches(query)
        if not matches and media_type == MediaTypes.MOVIE.value and ":" in query:
            unlabelled = self._match_unlabelled_episode(query)
            if unlabelled is not None:
                return unlabelled
            return self._match_named_season_episode(query)
        if not matches:
            return None
        if len(matches) > 1:
            if media_type == MediaTypes.TV.value and season_number is not None:
                narrowed = [
                    match
                    for match in matches
                    if season_number in self._show_seasons(
                        _result_id_str(match),
                    )
                ]
                if len(narrowed) != 1:
                    return None
                matches = narrowed
            elif (
                media_type == MediaTypes.TV.value
                and episode_number is not None
            ):
                pairs = []
                target = self._episode_match_target(title, query)
                for match in matches:
                    show_id = _result_id_str(match)
                    pairs.extend(
                        (show_id, found_season)
                        for found_season in self._seasons_for_episode(
                            show_id, episode_number, target,
                        )
                    )
                if len(pairs) != 1:
                    return None
                return pairs[0][0], MediaTypes.TV.value, pairs[0][1], episode_number
            else:
                return None
        tmdb_id = _result_id_str(matches[0])
        if (
            media_type == MediaTypes.TV.value
            and season_number is None
            and episode_number is not None
        ):
            seasons = self._seasons_for_episode(
                tmdb_id,
                episode_number,
                self._episode_match_target(title, query),
            )
            if len(seasons) != 1:
                return None
            return tmdb_id, MediaTypes.TV.value, seasons[0], episode_number
        return tmdb_id, media_type, season_number, episode_number

    def _episode_match_target(self, title, query):
        """Return the normalized trailing episode title, or None."""
        episode_title = _episode_title(title, query)
        if not episode_title:
            return None
        return _normalize_match(episode_title)

    def search_results(self, title, media_type):
        """Return the provider search results for the review page's pick list."""
        results = services.search(
            media_type,
            title,
            1,
            source=Sources.TMDB.value,
        ).get("results", [])
        return results[:SEARCH_RESULT_LIMIT]

    def match_episode_number(self, tmdb_id, series_title, season_number,
                             episode_title):
        """Match an episode title to its number within one TMDB season.

        Netflix rows often carry the season and the episode title but no
        number.  A unique normalized match against the season's episode
        names is safe to record; anything ambiguous is left for review.
        The fallback language may name the episode when the configured
        one does not (a German row against TMDB_LANG=en).
        """
        if not episode_title:
            return None
        target = _normalize_match(episode_title)
        for names in self._season_names_candidates(
            tmdb_id, season_number, target, series_title,
        ):
            matches = {
                episode_number
                for episode_number, name in names.items()
                if name == target
            }
            if matches:
                return matches.pop() if len(matches) == 1 else None
        return None

    def _attempt_record(self, title, watched_at):
        """Run one row through the resolve + record pipeline.

        Returns ``(True, media_type)`` when a play was recorded, or
        ``(False, (media_type, season_number, episode_number))`` with the
        fields to park for review.  Shared by the import and the pending
        row retry so both run the exact same matching.
        """
        query, media_type, season_number, episode_number = _split_title(title)
        # resolve_row adds safe shortcuts on top of the unique exact match
        # (a known season filters same-title shows, a missing part suffix,
        # a single season carrying the episode, an unlabelled anthology
        # episode, a named season chain); None means the row must go to
        # the review page.
        resolved = self.resolve_row(
            title, query, media_type, season_number, episode_number,
        )
        if (
            resolved is None
            or (
                media_type == MediaTypes.TV.value
                and resolved[2] is None
            )
        ):
            return False, (media_type, season_number, episode_number)
        tmdb_id, media_type, season_number, episode_number = resolved

        # Many rows carry the season and the episode title but no number
        # ("Weeds: Season 8: It's Time"); the number comes from matching
        # the title within the season.
        if media_type == MediaTypes.TV.value and episode_number is None:
            episode_number = self.match_episode_number(
                tmdb_id, query, season_number, _episode_title(title, query),
            )
            if episode_number is None:
                return False, (media_type, season_number, episode_number)

        _item, error = self.record_play(
            query, watched_at, media_type, tmdb_id,
            season_number=season_number, episode_number=episode_number,
        )
        if error:
            logger.info("Netflix row %r needs review: %s", title, error)
            return False, (media_type, season_number, episode_number)
        return True, media_type

    def resolve_pending_row(self, row):
        """Re-run one parked row through the current matching pipeline.

        Returns True when a play was recorded and the row can be removed.
        """
        if not row.watched_at:
            return False
        watched_at = timezone.make_aware(
            datetime.combine(row.watched_at, time.min),
        )
        recorded, _fields = self._attempt_record(row.title, watched_at)
        return recorded

    def record_play(self, title, watched_at, media_type, tmdb_id,
                    season_number=None, episode_number=None):
        """Record one play for a resolved title.

        Returns ``(item, None)`` on success or ``(None, message)`` when the
        provider cannot back the row.  Re-recording the same (item, day) is
        a no-op, which is what makes re-imports idempotent.
        """
        if media_type == MediaTypes.MOVIE.value:
            return self._record_movie_play(title, watched_at, tmdb_id)
        if season_number is None or episode_number is None:
            return None, "Season and episode are required for a TV show."
        return self._record_episode_play(
            title, watched_at, tmdb_id, season_number, episode_number,
        )

    def _record_movie_play(self, title, watched_at, tmdb_id):
        metadata = self._get_metadata(MediaTypes.MOVIE.value, tmdb_id, title)
        if metadata is None:
            return None, f"{title}: not found in {Sources.TMDB.label} with ID {tmdb_id}."
        item = self._get_or_create_item(MediaTypes.MOVIE.value, tmdb_id, metadata)
        already = Movie.objects.filter(
            user=self.user,
            item=item,
            end_date__date=watched_at.date(),
        ).exists()
        if not already:
            movie = Movie(
                item=item,
                user=self.user,
                end_date=watched_at,
                status=Status.COMPLETED.value,
                progress=1,
                import_run_id=self.import_run_id,
            )
            movie._history_date = watched_at
            movie.save()
        return item, None

    def _record_episode_play(
        self, title, watched_at, tmdb_id, season_number, episode_number,
    ):
        tv_metadata = self._get_metadata(MediaTypes.TV.value, tmdb_id, title)
        if tv_metadata is None:
            return None, f"{title}: not found in {Sources.TMDB.label} with ID {tmdb_id}."
        season_metadata = self._get_metadata(
            MediaTypes.SEASON.value, tmdb_id, title, season_number,
        )
        if season_metadata is None:
            return None, f"{title} S{season_number}: not found in {Sources.TMDB.label}."
        matched_episode = next(
            (
                ep
                for ep in season_metadata["episodes"]
                if ep["episode_number"] == episode_number
            ),
            None,
        )
        if matched_episode is None:
            return None, (
                f"{title} S{season_number}E{episode_number}: not found in "
                f"{Sources.TMDB.label} with ID {tmdb_id}."
            )

        tv_item = self._get_or_create_item(MediaTypes.TV.value, tmdb_id, tv_metadata)
        tv_obj = TV.objects.filter(user=self.user, item=tv_item).first()
        if tv_obj is None:
            tv_obj = TV(
                item=tv_item,
                user=self.user,
                status=Status.IN_PROGRESS.value,
                import_run_id=self.import_run_id,
            )
            tv_obj.save()

        season_item = self._get_or_create_item(
            MediaTypes.SEASON.value, tmdb_id, season_metadata, season_number,
        )
        season_obj = Season.objects.filter(user=self.user, item=season_item).first()
        if season_obj is None:
            season_obj = Season(
                item=season_item,
                user=self.user,
                related_tv=tv_obj,
                status=Status.IN_PROGRESS.value,
                import_run_id=self.import_run_id,
            )
            season_obj.save()

        episode_metadata = {
            **Item.title_fields_from_episode_metadata(
                matched_episode,
                fallback_title=tv_metadata["title"],
            ),
            "image": self._get_episode_image(episode_number, season_metadata),
        }
        episode_item = self._get_or_create_item(
            MediaTypes.EPISODE.value,
            tmdb_id,
            episode_metadata,
            season_number,
            episode_number,
        )
        already = Episode.objects.filter(
            related_season=season_obj,
            item=episode_item,
            end_date__date=watched_at.date(),
        ).exists()
        if not already:
            episode = Episode(
                item=episode_item,
                related_season=season_obj,
                end_date=watched_at,
                import_run_id=self.import_run_id,
            )
            episode._history_date = watched_at
            episode.save()
        return episode_item, None


class NetflixImporter(NetflixResolver):
    """Class to handle importing a Netflix viewing-history CSV."""

    def __init__(self, file, user, mode):
        """Initialize with the uploaded CSV, user, and import mode.

        ``mode`` is accepted for the shared task signature; plays are
        idempotent, so nothing is ever deleted or overwritten.
        """
        # The task wrapper (imports/_media_imports.py) tracks the active
        # ImportRun in a context var; stamping rows with it is what makes
        # "undo this import" able to find exactly this run's writes.
        super().__init__(user, import_run_id=import_progress.get_current_import_run_id())
        self.file = file
        self.mode = mode
        self.counts = {MediaTypes.MOVIE.value: 0, MediaTypes.TV.value: 0}
        self.pending_count = 0
        self.skipped_count = 0

        logger.info(
            "Initialized Netflix importer for user %s",
            user.username,
        )

    def import_data(self):
        """Import every resolvable row, parking the rest for review."""
        rows = _normalize_rows(list(DictReader(_decode_csv(self.file))))
        layout = _detect_date_layout(
            (row.get("Date") or "").strip() for row in rows
        )
        total = len(rows)
        for i, row in enumerate(rows, start=1):
            import_progress.report(i, total, "Netflix")
            try:
                self._process_row(row, layout)
            except SoftTimeLimitExceeded:
                logger.warning(
                    "Netflix import for %s hit the time limit at entry %s/%s",
                    self.user.username,
                    i,
                    total,
                )
                self.warnings.append(
                    "Import stopped partway through because it was taking too "
                    "long. Run the import again to pick up the remaining entries.",
                )
                break

        counts = dict(self.counts)
        messages = list(self.warnings)
        if self.pending_count:
            messages.append(
                f"{self.pending_count} row(s) could not be matched "
                "automatically; resolve them on the Netflix review page.",
            )
        if self.skipped_count:
            messages.append(
                f"{self.skipped_count} row(s) with an empty title were skipped.",
            )
        return counts, "\n".join(dict.fromkeys(messages)) or None

    def _process_row(self, row, layout):
        title = (row.get("Title") or "").strip()
        if not title:
            self.skipped_count += 1
            return
        raw_date = (row.get("Date") or "").strip()
        watched_at = _parse_netflix_date(raw_date, layout)

        # A broken date cannot be recorded; park it for the review page.
        if watched_at is None:
            _query, media_type, season_number, episode_number = _split_title(
                title,
            )
            self._add_pending(title, watched_at, raw_date, media_type,
                              season_number, episode_number)
            return

        recorded, fields = self._attempt_record(title, watched_at)
        if not recorded:
            media_type, season_number, episode_number = fields
            self._add_pending(title, watched_at, raw_date, media_type,
                              season_number, episode_number)
            return
        self.counts[fields] += 1

    def _add_pending(self, title, watched_at, raw_date, media_type,
                     season_number, episode_number):
        """Park one unresolved row; get_or_create keeps re-imports quiet."""
        self.pending_count += 1
        NetflixPendingRow.objects.get_or_create(
            user=self.user,
            title=title,
            watched_at=watched_at.date() if watched_at else None,
            defaults={
                "raw_date": raw_date,
                "media_type": media_type,
                "season_number": season_number,
                "episode_number": episode_number,
                "import_run_id": self.import_run_id,
            },
        )


def importer(file, user, mode):
    """Import a Netflix viewing-history CSV. ``mode`` does not matter: plays are idempotent."""
    # Every row is resolved through TMDB, so an unconfigured provider would
    # otherwise fail mid-file with an unexpected error.
    if not app.providers.tmdb.enabled(user):
        msg = (
            "TMDB is not configured. Add a TMDB API key in Settings → "
            "Metadata providers before importing your Netflix history."
        )
        raise MediaImportError(msg)
    return NetflixImporter(file, user, mode).import_data()
