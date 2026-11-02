"""PlayStation Network importer for played games and hours played.

PSN exposes no clean purchase library, so "owned" is approximated by every
title the account has played (see :mod:`integrations.psn_api`). Hours played
come from ``title_stats``' cumulative play duration, which PSN reports for
every played title.

One game can appear under several title IDs -- the PS4 and PS5 releases, or
regional variants -- that all resolve to the same IGDB game, so matches are
aggregated by IGDB ID before anything is written: play durations add up,
the most recent last-played date wins.

PSN only reports lifetime totals, so each sync remembers the total it saw
(:class:`PlaytimeSnapshot`) and logs the difference as a new, dated play entry.
Existing entries are never edited. The first time a game is seen its total is
only remembered, plus -- when the account's setup choice asks for it -- written
as one entry spanning its first to last played dates.
"""

import logging
import re
from collections import defaultdict
from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

import app
from app.log_safety import exception_summary, redact_secrets
from app.models import MediaTypes, Sources, Status
from app.providers import services
from integrations import connection_health, import_progress, psn_api
from integrations.imports import helpers, title_matching
from integrations.imports.helpers import MediaImportError
from integrations.models import PlaytimeSnapshot, PSNAccount

logger = logging.getLogger(__name__)

IMPORT_NOTE = "Imported from PlayStation Network"
RECENTLY_PLAYED_DAYS = 14
SNAPSHOT_SOURCE = "psn"
# How often a connected account syncs. PSN only reports lifetime totals, so
# each sync's new entry covers the window since the previous one: a shorter
# interval gives finer time-of-day data at the cost of more requests.
SYNC_EVERY_HOURS = 3

# last_error_message is rendered on the import page and kept until the next
# successful sync, so what lands there is scrubbed and bounded rather than
# whatever an exception happened to stringify to.
MAX_ERROR_MESSAGE_LENGTH = 500

# PSN reports a played library, so only the two library-sync modes mean
# anything here; "watchlist" and "update_collection" have nothing to act on and
# would otherwise be silently treated as "new". Both modes behave the same: a
# sync only ever adds entries, so there is nothing for "overwrite" to replace.
SUPPORTED_MODES = frozenset({"new", "overwrite"})

# The PlayStation store decorates titles in ways IGDB doesn't
# ("It Takes Two  PS4™ & PS5™"); stripping these recovers matches. IGDB's
# PlayStation-store external IDs are numeric store product IDs, not the
# CUSA/PPSA title IDs PSN reports, so unlike Xbox's 360-era GUIDs there is no
# exact-ID fallback -- matching is by name only.
STORE_SUFFIX_RE = re.compile(
    r"\s*(?:"
    r"\([^)]*\)"
    r"|(?:[" + title_matching.DASHES + r":]\s*|\bfor\s+|\s)"
    r"(?:playstation\s*[45]|ps[45])"
    r"(?:\s*&\s*(?:playstation\s*[45]|ps[45]))*"
    r")\s*$",
    re.IGNORECASE,
)

# PSN store names use characters IGDB doesn't: single-codepoint Roman numerals
# ("FINAL FANTASY Ⅻ") and trademark symbols glued between words
# ("Gran Turismo™SPORT", which must become "Gran Turismo SPORT", not
# "Gran TurismoSPORT").
ROMAN_NUMERALS = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
                  "XI", "XII")
ROMAN_NUMERAL_NORMALIZATIONS = str.maketrans(
    {chr(0x2160 + index): numeral for index, numeral in enumerate(ROMAN_NUMERALS)},
)
SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"\s+([:,!?])")


def _safe_message(message):
    """Return a message fit to persist on the account and show to the user."""
    scrubbed = redact_secrets(str(message)).strip()
    if len(scrubbed) > MAX_ERROR_MESSAGE_LENGTH:
        return scrubbed[: MAX_ERROR_MESSAGE_LENGTH - 1].rstrip() + "…"
    return scrubbed


def _normalize_name(name):
    """Replace PSN store characters that never appear in IGDB names."""
    name = name.translate(ROMAN_NUMERAL_NORMALIZATIONS)
    name = title_matching.TRADEMARK_RE.sub(" ", name)
    return SPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", " ".join(name.split()))


def _search_names(name):
    """Yield search candidates for a PSN store title, most faithful first."""
    return title_matching.search_names(_normalize_name(name), STORE_SUFFIX_RE)


def importer(identifier, user, mode):
    """Import the user's played games from their connected PSN account."""
    return PSNImporter(user, mode).import_data()


class PSNImporter:
    """Import played games and hours played from PlayStation Network."""

    def __init__(self, user, mode):
        """Initialize the importer and validate account access."""
        if mode not in SUPPORTED_MODES:
            msg = (
                f"Unsupported PSN import mode {mode!r}. "
                f"Choose one of: {', '.join(sorted(SUPPORTED_MODES))}."
            )
            raise MediaImportError(msg)

        self.user = user
        self.mode = mode
        self.warnings = []

        try:
            self.account = user.psn_account
        except PSNAccount.DoesNotExist as error:
            msg = "Connect PlayStation Network before importing"
            raise MediaImportError(msg) from error

        if not self.account.npsso:
            msg = "Connect PlayStation Network before importing"
            raise MediaImportError(msg)

        try:
            self.npsso = helpers.decrypt_or_raise(self.account.npsso)
        except MediaImportError as decrypt_error:
            self._mark_failed(str(decrypt_error), auth=True)
            raise

        self.existing_media = helpers.get_existing_media(user)
        # Track media the user explicitly deleted, so it isn't recreated
        self.deleted_media = helpers.get_deleted_media(user)
        self.to_update_meta = []
        self.snapshots = {
            snapshot.media_id: snapshot
            for snapshot in PlaytimeSnapshot.objects.filter(
                user=user,
                source=SNAPSHOT_SOURCE,
            )
        }
        self.sync_time = timezone.now()
        # Read before this sync stamps the account: it is when the last sync (a
        # sync from before totals were remembered, for an upgrading account) ran.
        self.previous_sync_at = self.account.last_sync_at
        self.created = 0
        self.unchanged = 0
        self.baseline = 0
        self.bulk_media = defaultdict(list)
        self.lookup_failures = 0
        # Provider errors point at IGDB; anything else is a bug on our side and
        # must not be reported as an unreachable provider.
        self.provider_failures = 0
        self.first_failure = ""

        logger.info(
            "Initialized PSN importer for user %s with mode %s",
            user.username,
            mode,
        )

    def import_data(self):
        """Import the account's played PSN titles."""
        try:
            titles, skipped = psn_api.get_played_games(self.npsso)
        except MediaImportError as error:
            self._mark_failed(
                str(error),
                auth=isinstance(error, helpers.ConnectionAuthError),
            )
            raise
        except Exception as error:
            # psn_api translates the failures it knows about; anything else
            # would otherwise leave the account reading as connected while
            # every scheduled run keeps failing. The summary names the
            # exception type only -- the traceback goes to the log.
            logger.exception(
                "PSN library fetch failed for user %s",
                self.user.username,
            )
            msg = (
                "PSN import failed while fetching your library "
                f"({exception_summary(error)}). Check the logs for details."
            )
            self._mark_failed(msg, auth=False)
            raise MediaImportError(msg) from error

        if skipped:
            # The genre heuristic behind the app filter is best-effort; a
            # misclassified game must be auditable by the user, not only
            # visible in the server log.
            self.warnings.append(
                f"Skipped {len(skipped)} non-game apps (no genres in the "
                f"PlayStation store): {', '.join(sorted(skipped))}",
            )

        if not titles:
            logger.info("No PSN titles found for user %s", self.user.username)
            self._mark_synced()
            return {}, "\n".join(dict.fromkeys(self.warnings))

        total = len(titles)
        aggregated = {}
        for index, title in enumerate(titles, start=1):
            import_progress.report(index, total, "PSN")
            self._process_title(title, aggregated)

        for media_id, aggregate in aggregated.items():
            self._store_game(media_id, aggregate)

        matched = len(aggregated)
        logger.info(
            "PSN: %d titles, %d matched, %d lookup failures (%d provider errors)",
            total,
            matched,
            self.lookup_failures,
            self.provider_failures,
        )

        if not matched and self.lookup_failures:
            if self.provider_failures == self.lookup_failures:
                msg = (
                    f"Could not reach {Sources.IGDB.label}: all "
                    f"{self.lookup_failures} of {total} PSN titles failed to "
                    f"look up. Check the {Sources.IGDB.label} credentials on "
                    f"this instance."
                )
            else:
                msg = (
                    f"All {self.lookup_failures} of {total} PSN titles failed "
                    f"to import. First error: {self.first_failure}"
                )
            self._mark_failed(msg, auth=False)
            raise MediaImportError(msg)

        # One transaction, so a failed snapshot save can't leave logged play
        # without its remembered total (it would be logged again next sync).
        with transaction.atomic():
            helpers.bulk_create_media(self.bulk_media, self.user)
            self._save_snapshots()

        if self.to_update_meta:
            app.models.Item.objects.bulk_update(
                self.to_update_meta,
                fields=["title", "image"],
            )

        self._mark_synced()

        imported_counts = {
            media_type: len(media_list)
            for media_type, media_list in self.bulk_media.items()
        }
        # "created"/"skipped" make a sync that only touched snapshots read as
        # unchanged instead of "No media was imported" with no explanation.
        imported_counts["created"] = self.created
        imported_counts["skipped"] = self.unchanged
        imported_counts["baseline"] = self.baseline
        logger.info(
            "PSN import completed for user %s: %s",
            self.user.username,
            imported_counts,
        )
        return imported_counts, "\n".join(dict.fromkeys(self.warnings))

    def _mark_synced(self):
        """Record a successful sync on the account row."""
        self.account.last_sync_at = timezone.now()
        connection_health.record_success(self.account, extra_fields=["last_sync_at"])

    def _mark_failed(self, message, *, auth):
        """Store a scrubbed failure; only rejected credentials mark it broken."""
        connection_health.record_failure(
            self.account,
            _safe_message(message),
            auth=auth,
        )

    def _record_failure(self, detail):
        """Count a title that couldn't be processed, keeping the first reason."""
        self.lookup_failures += 1
        if not self.first_failure:
            self.first_failure = detail

    def _process_title(self, title, aggregated):
        """Match a PSN title to IGDB and fold it into the aggregate."""
        title_id = title["title_id"]
        name = title["name"] or f"Unknown Game {title_id}"

        try:
            igdb_game = self._match_with_igdb(name)
        except services.ProviderAPIError as e:
            # ProviderAPIError writes its own user-facing message and keeps the
            # response body out of it; scrub it anyway before it is persisted.
            logger.warning(
                "IGDB lookup failed for PSN title %s: %s",
                name,
                exception_summary(e),
            )
            detail = f"{Sources.IGDB.label} error: {_safe_message(e)}"
            self.warnings.append(f"{name} ({title_id}): {detail}")
            self._record_failure(f"{name}: {detail}")
            self.provider_failures += 1
            return
        except Exception as e:
            # An unexpected exception's message is not written for display: it
            # can carry the request URL, the response body, or the credentials
            # sent with it, and the first one seen ends up on the account row.
            logger.exception(
                "Failed to process PSN title %s (%s)",
                name,
                title_id,
            )
            detail = exception_summary(e)
            self.warnings.append(f"{name} ({title_id}): {detail}")
            self._record_failure(f"{name}: {detail}")
            return

        if not igdb_game:
            logger.debug(
                "Skipping PSN title %s (titleId: %s) - no IGDB match found",
                name,
                title_id,
            )
            self.warnings.append(
                f"{name} ({title_id}): Couldn't find a match in {Sources.IGDB.label}",
            )
            return

        media_id = str(igdb_game["media_id"])
        aggregate = aggregated.setdefault(
            media_id,
            {
                "title": igdb_game["title"],
                "image": igdb_game["image"],
                "minutes": 0,
                "first_played": None,
                "last_played": None,
            },
        )
        aggregate["minutes"] += title["minutes"]
        first_played = title.get("first_played")
        if first_played and (
            aggregate["first_played"] is None
            or first_played < aggregate["first_played"]
        ):
            aggregate["first_played"] = first_played
        last_played = title["last_played"]
        if last_played and (
            aggregate["last_played"] is None
            or last_played > aggregate["last_played"]
        ):
            aggregate["last_played"] = last_played

    def _store_game(self, media_id, aggregate):
        """Log the playtime a set of PSN titles added since the last sync."""
        minutes = aggregate["minutes"]
        snapshot = self.snapshots.get(media_id)
        previous = snapshot.minutes if snapshot else None
        previous_sync = snapshot.seen_at if snapshot else None
        # PSN's lifetime total only ever grows, so a lower figure means
        # incomplete data (a sibling title ID whose IGDB lookup failed this
        # run): remember the higher one and log nothing.
        self._remember(media_id, max(minutes, previous or 0))

        if media_id in self.deleted_media[MediaTypes.GAME.value][Sources.IGDB.value]:
            # PSN keeps reporting a title forever once it has been launched,
            # so without this every scheduled sync resurrects a game the user
            # deleted here on purpose.
            logger.debug(
                "Skipping deleted PSN game: %s (%s) - deleted locally",
                aggregate["title"],
                media_id,
            )
            return

        existing = self.existing_media[MediaTypes.GAME.value][Sources.IGDB.value].get(
            media_id,
        )
        if existing:
            item = existing.item
            item.title = aggregate["title"]
            item.image = aggregate["image"]
            self.to_update_meta.append(item)

        last_played = self._aware(aggregate["last_played"])
        if previous is None:
            # First sighting. A tracked game keeps its own history, and its PSN
            # total is the starting point, except for play since the account's
            # last sync (the gap). Otherwise only the setup choice makes an
            # untracked game an entry.
            gap = self._gap_since_last_sync(existing, minutes, last_played)
            if gap:
                start_date = self.previous_sync_at
                end_date = (
                    last_played
                    if start_date <= last_played <= self.sync_time
                    else self.sync_time
                )
                logged = gap
            elif existing or not self.account.import_existing_playtime:
                self.baseline += 1
                return
            else:
                start_date = self._aware(aggregate["first_played"])
                end_date = last_played
                logged = minutes
        elif minutes > previous:
            # The new time happened somewhere between the previous sync and
            # the last time PSN says the game was launched.
            start_date = previous_sync
            end_date = (
                last_played
                if last_played and start_date <= last_played <= self.sync_time
                else self.sync_time
            )
            logged = minutes - previous
        else:
            self.unchanged += 1
            return

        if start_date and end_date and start_date > end_date:
            start_date, end_date = end_date, start_date

        item, _ = app.models.Item.objects.get_or_create(
            media_id=media_id,
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            defaults={"title": aggregate["title"], "image": aggregate["image"]},
        )
        self.created += 1
        self.bulk_media[MediaTypes.GAME.value].append(
            app.models.Game(
                item=item,
                user=self.user,
                status=self._determine_game_status(logged, last_played),
                score=None,
                progress=logged,
                notes=IMPORT_NOTE,
                start_date=start_date,
                end_date=end_date,
            ),
        )

    def _gap_since_last_sync(self, existing, minutes, last_played):
        """Return the minutes played since the last sync for a tracked game.

        The first sync that remembers totals can't see what was played between
        the account's previous sync and now, but a tracked game whose hours were
        close to PSN's at the time shows it as the difference. It counts only
        when the game was launched since that sync and the difference is no
        bigger than the hours already tracked; a bigger one is a library that
        was never in step with PSN, not new play.
        """
        if not existing or not self.previous_sync_at or not last_played:
            return 0
        if last_played <= self.previous_sync_at:
            return 0
        tracked = (
            app.models.Game.objects.filter(user=self.user, item=existing.item)
            .aggregate(total=Sum("progress"))["total"]
            or 0
        )
        gap = minutes - tracked
        return gap if 0 < gap <= tracked else 0

    @staticmethod
    def _aware(value):
        """Return a timezone-aware datetime, leaving None alone."""
        if value is not None and timezone.is_naive(value):
            return timezone.make_aware(value)
        return value

    def _remember(self, media_id, minutes):
        """Record the total PSN reported for a game, as of this sync."""
        snapshot = self.snapshots.get(media_id)
        if snapshot:
            snapshot.minutes = minutes
            snapshot.seen_at = self.sync_time
        else:
            self.snapshots[media_id] = PlaytimeSnapshot(
                user=self.user,
                source=SNAPSHOT_SOURCE,
                media_id=media_id,
                minutes=minutes,
                seen_at=self.sync_time,
            )

    def _save_snapshots(self):
        """Persist the totals seen this sync, after the entries they explain."""
        PlaytimeSnapshot.objects.bulk_create(
            [snapshot for snapshot in self.snapshots.values() if snapshot.pk is None],
        )
        PlaytimeSnapshot.objects.bulk_update(
            [snapshot for snapshot in self.snapshots.values() if snapshot.pk],
            fields=["minutes", "seen_at"],
        )

    def _determine_game_status(self, minutes, last_played):
        """Determine game status from PSN playtime and last played date.

        Args:
            minutes (int): Total minutes played across all title IDs
            last_played (datetime | None): When the game was last launched

        Returns:
            str: Status value from Status choices
        """
        # Never meaningfully launched.
        if not minutes and last_played is None:
            return Status.PLANNING.value

        if last_played is not None:
            cutoff = timezone.now() - timedelta(days=RECENTLY_PLAYED_DAYS)
            if timezone.is_naive(last_played):
                last_played = timezone.make_aware(last_played)
            if last_played >= cutoff:
                return Status.IN_PROGRESS.value

        return Status.PAUSED.value

    def _match_with_igdb(self, name):
        """Match a PSN title to IGDB by name.

        PSN's CUSA/PPSA title IDs have no IGDB counterpart (IGDB's
        PlayStation-store external IDs are numeric store product IDs), so
        name search is the only option.
        """
        # Pin the source: the Item below is written as IGDB either way.
        for candidate in _search_names(name):
            results = services.search(
                MediaTypes.GAME.value,
                candidate,
                1,
                source=Sources.IGDB.value,
            ).get("results", [])
            if not results:
                continue

            match = results[0]
            logger.info(
                "Matched PSN title %s with IGDB ID %s by name %r",
                name,
                match["media_id"],
                candidate,
            )
            return {
                "media_id": match["media_id"],
                "title": match.get("title", name),
                "image": match["image"],
            }

        return None
