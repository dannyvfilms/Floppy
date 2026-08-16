"""PlayStation Network importer for played games and hours played.

PSN exposes no clean purchase library, so "owned" is approximated by every
title the account has played (see :mod:`integrations.psn_api`). Hours played
come from ``title_stats``' cumulative play duration, which PSN reports for
every played title.

One game can appear under several title IDs -- the PS4 and PS5 releases, or
regional variants -- that all resolve to the same IGDB game, so matches are
aggregated by IGDB ID before anything is written: play durations add up,
the most recent last-played date wins.
"""

import logging
import re
from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

import app
from app.log_safety import exception_summary, redact_secrets
from app.models import MediaTypes, Sources, Status
from app.providers import services
from integrations import import_progress, psn_api
from integrations.imports import helpers, title_matching
from integrations.imports.helpers import MediaImportError
from integrations.models import PSNAccount

logger = logging.getLogger(__name__)

IMPORT_NOTE = "Imported from PlayStation Network"
RECENTLY_PLAYED_DAYS = 14

# last_error_message is rendered on the import page and kept until the next
# successful sync, so what lands there is scrubbed and bounded rather than
# whatever an exception happened to stringify to.
MAX_ERROR_MESSAGE_LENGTH = 500

# PSN reports a played library, so only the two library-sync modes mean
# anything here; "watchlist" and "update_collection" have nothing to act on and
# would otherwise be silently treated as "new".
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
            self._mark_broken(str(decrypt_error))
            raise

        self.existing_media = helpers.get_existing_media(user)
        # Track media the user explicitly deleted, so it isn't recreated
        self.deleted_media = helpers.get_deleted_media(user)
        self.to_update = []
        self.to_update_meta = []
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
            self._mark_broken(str(error))
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
            self._mark_broken(msg)
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

        matched = len(self.bulk_media[MediaTypes.GAME.value]) + len(self.to_update)
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
            self._mark_broken(msg)
            raise MediaImportError(msg)

        helpers.bulk_create_media(self.bulk_media, self.user)

        if self.to_update:
            app.models.Game.objects.bulk_update(
                self.to_update,
                fields=["progress"],
            )
            # Statuses are written with the Completed/Dropped guard enforced
            # by the database, not only by the snapshot read at the start of
            # the run: the IGDB matching phase is long, and a user marking a
            # game Completed or Dropped mid-sync must not have that clobbered
            # by a status computed from stale data.
            protected = {Status.COMPLETED.value, Status.DROPPED.value}
            pks_by_status = defaultdict(list)
            for game in self.to_update:
                if game.status not in protected:
                    pks_by_status[game.status].append(game.pk)
            for status_value, pks in pks_by_status.items():
                app.models.Game.objects.filter(pk__in=pks).exclude(
                    status__in=protected,
                ).update(status=status_value)
            logger.info(
                "Updated %d existing games for user %s",
                len(self.to_update),
                self.user.username,
            )

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
        logger.info(
            "PSN import completed for user %s: %s",
            self.user.username,
            imported_counts,
        )
        return imported_counts, "\n".join(dict.fromkeys(self.warnings))

    def _mark_synced(self):
        """Record a successful sync on the account row."""
        self.account.last_sync_at = timezone.now()
        self.account.connection_broken = False
        self.account.last_error_message = ""
        self.account.save(
            update_fields=[
                "last_sync_at",
                "connection_broken",
                "last_error_message",
                "updated_at",
            ],
        )

    def _mark_broken(self, message):
        """Flag the account as needing attention, storing a scrubbed reason."""
        self.account.connection_broken = True
        self.account.last_error_message = _safe_message(message)
        self.account.save(
            update_fields=["connection_broken", "last_error_message", "updated_at"],
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
                "last_played": None,
            },
        )
        aggregate["minutes"] += title["minutes"]
        last_played = title["last_played"]
        if last_played and (
            aggregate["last_played"] is None
            or last_played > aggregate["last_played"]
        ):
            aggregate["last_played"] = last_played

    def _store_game(self, media_id, aggregate):
        """Create or update the game a set of PSN titles resolved to."""
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

        minutes = aggregate["minutes"]
        last_played = aggregate["last_played"]
        existing = self.existing_media[MediaTypes.GAME.value][Sources.IGDB.value].get(
            media_id,
        )

        if existing:
            if self.mode == "overwrite":
                # PSN's cumulative play duration only ever grows, so an
                # aggregate below the stored progress never means the user
                # played less: it means incomplete data -- a sibling title ID
                # whose IGDB lookup failed this run, or a title whose
                # playDuration PSN reports as absent (psnawp collapses that
                # to zero). Mirror the Xbox importer's invariant that unknown
                # playtime must never overwrite tracked hours: progress is
                # only ever raised.
                minutes = max(existing.progress, minutes)
                existing.progress = minutes
                if existing.status not in {
                    Status.COMPLETED.value,
                    Status.DROPPED.value,
                }:
                    existing.status = self._determine_game_status(minutes, last_played)
                self.to_update.append(existing)

            item = existing.item
            item.title = aggregate["title"]
            item.image = aggregate["image"]
            self.to_update_meta.append(item)
            return

        item, _ = app.models.Item.objects.get_or_create(
            media_id=media_id,
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            defaults={"title": aggregate["title"], "image": aggregate["image"]},
        )
        self.bulk_media[MediaTypes.GAME.value].append(
            app.models.Game(
                item=item,
                user=self.user,
                status=self._determine_game_status(minutes, last_played),
                score=None,
                progress=minutes,
                notes=IMPORT_NOTE,
                start_date=None,
                end_date=None,
            ),
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
