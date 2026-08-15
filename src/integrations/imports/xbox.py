"""Xbox importer for played games and hours played.

Xbox Live exposes no purchase library, so "owned" is approximated by every title
the account has played (see :mod:`integrations.xbox_api`). Hours played come
from the per-title ``MinutesPlayed`` stat, which not every title publishes -- a
missing value means unknown and must never overwrite existing progress.
"""

import logging
import re
from collections import defaultdict
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

import app
from app.log_safety import exception_summary, redact_secrets
from app.models import MediaTypes, Sources, Status
from app.providers import services
from app.providers.igdb import ExternalGameSource, external_game
from integrations import import_progress, xbox_api
from integrations.imports import helpers, title_matching
from integrations.imports.helpers import MediaImportError
from integrations.models import XboxAccount

logger = logging.getLogger(__name__)

IMPORT_NOTE = "Imported from Xbox"
RECENTLY_PLAYED_DAYS = 14

# last_error_message is rendered on the import page and kept until the next
# successful sync, so what lands there is scrubbed and bounded rather than
# whatever an exception happened to stringify to.
MAX_ERROR_MESSAGE_LENGTH = 500

# Xbox reports a played library, so only the two library-sync modes mean
# anything here; "watchlist" and "update_collection" have nothing to act on and
# would otherwise be silently treated as "new".
SUPPORTED_MODES = frozenset({"new", "overwrite"})

# 360-era marketplace product GUIDs are this prefix plus the title ID in hex;
# IGDB indexes them as its Xbox Marketplace external-game source.
XBOX_MARKETPLACE_GUID_PREFIX = "66acd000-77fe-1000-9115-d802"
MAX_TITLE_ID = 0xFFFFFFFF
LEGACY_DEVICES = {"Xbox", "Xbox360"}

# The Xbox store decorates titles in ways IGDB doesn't ("Isonzo (Windows)",
# "Battlefield 2042 Xbox Series X|S"); stripping these recovers matches.
STORE_SUFFIX_RE = re.compile(
    r"\s*(?:"
    r"\([^)]*\)"
    r"|(?:[" + title_matching.DASHES + r":]\s*|\bfor\s+)(?:xbox|windows|pc)\b.*"
    r"|xbox\s+(?:series\s+[xs](?:\|[xs])?|one|360)\b.*"
    r")\s*$",
    re.IGNORECASE,
)


def _safe_message(message):
    """Return a message fit to persist on the account and show to the user."""
    scrubbed = redact_secrets(str(message)).strip()
    if len(scrubbed) > MAX_ERROR_MESSAGE_LENGTH:
        return scrubbed[: MAX_ERROR_MESSAGE_LENGTH - 1].rstrip() + "…"
    return scrubbed


def _search_names(name):
    """Yield search candidates for an Xbox store title, most faithful first."""
    return title_matching.search_names(name, STORE_SUFFIX_RE)


def _simplify_title(name):
    """Strip trademark symbols and Xbox store decorations from a title."""
    return title_matching.simplify_title(name, STORE_SUFFIX_RE)


def _strip_decorations(name):
    """Strip edition suffixes and publisher brand prefixes from a title."""
    return title_matching.strip_decorations(name)


def _marketplace_guid(title_id):
    """Return the Xbox 360 marketplace product GUID for a title ID, if valid."""
    try:
        numeric = int(str(title_id))
    except (TypeError, ValueError):
        return None
    if not 0 < numeric <= MAX_TITLE_ID:
        return None
    return f"{XBOX_MARKETPLACE_GUID_PREFIX}{numeric:08x}"


def importer(identifier, user, mode):
    """Import the user's played games from their connected Xbox account."""
    return XboxImporter(user, mode).import_data()


class XboxImporter:
    """Import played games and hours played from Xbox Live via OpenXBL."""

    def __init__(self, user, mode):
        """Initialize the importer and validate account access."""
        if mode not in SUPPORTED_MODES:
            msg = (
                f"Unsupported Xbox import mode {mode!r}. "
                f"Choose one of: {', '.join(sorted(SUPPORTED_MODES))}."
            )
            raise MediaImportError(msg)

        self.user = user
        self.mode = mode
        self.warnings = []

        try:
            self.account = user.xbox_account
        except XboxAccount.DoesNotExist as error:
            msg = "Connect Xbox before importing"
            raise MediaImportError(msg) from error

        if not self.account.api_key:
            msg = "Connect Xbox before importing"
            raise MediaImportError(msg)

        try:
            self.api_key = helpers.decrypt_or_raise(self.account.api_key)
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
            "Initialized Xbox importer for user %s with mode %s",
            user.username,
            mode,
        )

    def import_data(self):
        """Import the account's played Xbox titles."""
        try:
            xuid = self._resolve_xuid()
            titles = xbox_api.get_played_titles(self.api_key, xuid)
            minutes_by_title = xbox_api.get_minutes_played(
                self.api_key,
                xuid,
                titles.keys(),
            )
        except MediaImportError as error:
            self._mark_broken(str(error))
            raise
        except Exception as error:
            # xbox_api translates the failures it knows about; anything else
            # would otherwise leave the account reading as connected while
            # every scheduled run keeps failing. The summary names the
            # exception type only -- the traceback goes to the log.
            logger.exception(
                "Xbox library fetch failed for user %s",
                self.user.username,
            )
            msg = (
                "Xbox import failed while fetching your library "
                f"({exception_summary(error)}). Check the logs for details."
            )
            self._mark_broken(msg)
            raise MediaImportError(msg) from error

        if not titles:
            logger.info("No Xbox titles found for user %s", self.user.username)
            self._mark_synced()
            return {}, ""

        total = len(titles)
        for index, (title_id, title) in enumerate(titles.items(), start=1):
            import_progress.report(index, total, "Xbox")
            self._process_title(title_id, title, minutes_by_title.get(title_id))

        matched = len(self.bulk_media[MediaTypes.GAME.value]) + len(self.to_update)
        logger.info(
            "Xbox: %d titles, %d matched, %d lookup failures (%d provider errors)",
            total,
            matched,
            self.lookup_failures,
            self.provider_failures,
        )

        if not matched and self.lookup_failures:
            if self.provider_failures == self.lookup_failures:
                msg = (
                    f"Could not reach {Sources.IGDB.label}: all "
                    f"{self.lookup_failures} of {total} Xbox titles failed to "
                    f"look up. Check the {Sources.IGDB.label} credentials on "
                    f"this instance."
                )
            else:
                msg = (
                    f"All {self.lookup_failures} of {total} Xbox titles failed "
                    f"to import. First error: {self.first_failure}"
                )
            self._mark_broken(msg)
            raise MediaImportError(msg)

        helpers.bulk_create_media(self.bulk_media, self.user)

        if self.to_update:
            app.models.Game.objects.bulk_update(
                self.to_update,
                fields=["progress", "status"],
            )
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
            "Xbox import completed for user %s: %s",
            self.user.username,
            imported_counts,
        )
        return imported_counts, "\n".join(dict.fromkeys(self.warnings))

    def _resolve_xuid(self):
        """Return the account's XUID, refusing to import without one.

        Every title endpoint is keyed by XUID, and an empty one silently
        requests a truncated path instead of failing, so it must be caught here.
        """
        xuid = str(self.account.xuid or "").strip()
        if not xuid:
            xuid = str(xbox_api.get_account(self.api_key)[0] or "").strip()
        if not xuid:
            msg = (
                "OpenXBL returned no XUID for this API key. "
                "Reconnect your Xbox account."
            )
            raise MediaImportError(msg)
        return xuid

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

    def _process_title(self, title_id, title, minutes):
        """Process a single Xbox title from the played-titles list."""
        name = title.get("name") or f"Unknown Game {title_id}"

        try:
            igdb_game = self._match_with_igdb(title, name)
        except services.ProviderAPIError as e:
            # ProviderAPIError writes its own user-facing message and keeps the
            # response body out of it; scrub it anyway before it is persisted.
            logger.warning(
                "IGDB lookup failed for Xbox title %s: %s",
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
                "Failed to process Xbox title %s (%s)",
                name,
                title_id,
            )
            detail = exception_summary(e)
            self.warnings.append(f"{name} ({title_id}): {detail}")
            self._record_failure(f"{name}: {detail}")
            return

        if not igdb_game:
            logger.debug(
                "Skipping Xbox title %s (titleId: %s) - no IGDB match found",
                name,
                title_id,
            )
            self.warnings.append(
                f"{name} ({title_id}): Couldn't find a match in {Sources.IGDB.label}",
            )
            return

        last_played = self._last_time_played(title)
        media_id = str(igdb_game["media_id"])

        if media_id in self.deleted_media[MediaTypes.GAME.value][Sources.IGDB.value]:
            # Xbox keeps reporting a title forever once it has been launched,
            # so without this every scheduled sync resurrects a game the user
            # deleted here on purpose.
            logger.debug(
                "Skipping deleted Xbox game: %s (%s) - deleted locally",
                name,
                media_id,
            )
            return

        existing = self.existing_media[MediaTypes.GAME.value][Sources.IGDB.value].get(
            media_id,
        )

        if existing:
            if self.mode == "overwrite":
                # Xbox only reports MinutesPlayed for titles that publish it;
                # leave progress alone rather than zeroing tracked hours.
                if minutes is not None:
                    existing.progress = minutes
                if existing.status not in {
                    Status.COMPLETED.value,
                    Status.DROPPED.value,
                }:
                    existing.status = self._determine_game_status(minutes, last_played)
                self.to_update.append(existing)

            item = existing.item
            item.title = igdb_game["title"]
            item.image = igdb_game["image"]
            self.to_update_meta.append(item)
            return

        item, _ = app.models.Item.objects.get_or_create(
            media_id=media_id,
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            defaults={"title": igdb_game["title"], "image": igdb_game["image"]},
        )
        self.bulk_media[MediaTypes.GAME.value].append(
            app.models.Game(
                item=item,
                user=self.user,
                status=self._determine_game_status(minutes, last_played),
                score=None,
                progress=minutes or 0,
                notes=IMPORT_NOTE,
                start_date=None,
                end_date=None,
            ),
        )

    def _last_time_played(self, title):
        """Return the title's last played datetime, if Xbox reported one."""
        raw = (title.get("titleHistory") or {}).get("lastTimePlayed")
        if not raw:
            return None
        try:
            return parse_datetime(raw)
        except ValueError:
            return None

    def _determine_game_status(self, minutes, last_played):
        """Determine game status from Xbox playtime and last played date.

        Args:
            minutes (int | None): Total minutes played, or None if unreported
            last_played (datetime | None): When the title was last launched

        Returns:
            str: Status value from Status choices
        """
        # Never launched and no playtime reported.
        if not minutes and last_played is None:
            return Status.PLANNING.value

        if last_played is not None:
            cutoff = timezone.now() - timedelta(days=RECENTLY_PLAYED_DAYS)
            if timezone.is_naive(last_played):
                last_played = timezone.make_aware(last_played)
            if last_played >= cutoff:
                return Status.IN_PROGRESS.value

        return Status.PAUSED.value

    def _match_with_igdb(self, title, name):
        """Match an Xbox title to IGDB.

        360-era titles resolve by marketplace GUID first, sidestepping that
        era's truncated store names ("MCLA: Complete"). Modern titles expose
        no identifier IGDB indexes (``detail`` is always null, and neither
        the PFN nor the raw title ID resolves), so they match by name, with
        the GUID lookup as a last resort.
        """
        is_legacy = bool(LEGACY_DEVICES & set(title.get("devices") or []))
        if is_legacy:
            match = self._match_by_marketplace_guid(title, name)
            if match:
                return match

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
                "Matched Xbox title %s with IGDB ID %s by name %r",
                name,
                match["media_id"],
                candidate,
            )
            return {
                "media_id": match["media_id"],
                "title": match.get("title", name),
                "image": match["image"],
            }

        if not is_legacy:
            return self._match_by_marketplace_guid(title, name)
        return None

    def _match_by_marketplace_guid(self, title, name):
        """Match a title via IGDB's Xbox Marketplace external-game source."""
        guid = _marketplace_guid(title.get("titleId"))
        if not guid:
            return None

        igdb_game_id = external_game(guid, ExternalGameSource.XBOX_MARKETPLACE)
        if not igdb_game_id:
            return None

        game_details = services.get_media_metadata(
            MediaTypes.GAME.value,
            str(igdb_game_id),
            Sources.IGDB.value,
        )
        logger.info(
            "Matched Xbox title %s with IGDB ID %s via marketplace GUID %s",
            name,
            igdb_game_id,
            guid,
        )
        return {
            "media_id": igdb_game_id,
            "title": game_details.get("title", name),
            "image": game_details["image"],
        }
