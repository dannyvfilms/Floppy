"""Import Jellyfin Playback Reporting TSV backups."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from django.utils import timezone

from app import fork_services_episode, fork_services_movie
from app.models import Episode, MediaTypes, MoviePlay
from integrations import import_progress
from integrations.imports.helpers import MediaImportError, decrypt_or_raise
from integrations.jellyfin_client import (
    JellyfinAuthError,
    JellyfinClient,
    JellyfinClientError,
)
from integrations.jellyfin_sync import (
    _PROVIDER_FIELD_ORDER,
    _SOURCE_TO_JELLYFIN_PROVIDER,
)
from integrations.models import ImportRun

logger = logging.getLogger(__name__)

PLAYBACK_REPORTING_SOURCE = "jellyfin-playback-reporting"
MAX_WARNING_SAMPLES = 20
MIN_COLUMNS = 9
_JELLYFIN_PROVIDER_TO_SOURCE = {
    provider: source for source, provider in _SOURCE_TO_JELLYFIN_PROVIDER.items()
}


class PlaybackReportingRowError(ValueError):
    """Raised when one exported row cannot be normalized."""


@dataclass(frozen=True, slots=True)
class PlaybackReportingRow:
    """One normalized row from Playback Reporting's nine-column TSV export."""

    date_created: datetime
    user_id: str
    item_id: str
    item_type: str
    item_name: str
    playback_method: str
    client_name: str
    device_name: str
    play_duration: int
    line_number: int

    def source_identity(self, *, rowid: str | int | None = None) -> str:
        """Return a stable identity for this source event.

        TSV backups do not contain SQLite's ``rowid``. The optional argument
        keeps the identity rule explicit for a future supported API adapter.
        """
        if rowid is not None:
            return f"{PLAYBACK_REPORTING_SOURCE}:rowid:{rowid}"

        fields = (
            self.date_created.isoformat(),
            self.user_id,
            self.item_id,
            self.item_type,
            self.item_name,
            self.playback_method,
            self.client_name,
            self.device_name,
            str(self.play_duration),
        )
        digest = hashlib.sha256("\x1f".join(fields).encode("utf-8")).hexdigest()
        return f"{PLAYBACK_REPORTING_SOURCE}:hash:{digest}"


@dataclass(frozen=True, slots=True)
class PlaybackReportingParseResult:
    """Parsed rows plus bounded diagnostics for rejected export lines."""

    rows: list[PlaybackReportingRow]
    warnings: list[str]
    rejected_count: int


def _parse_datetime(value: str) -> datetime:
    """Parse Playback Reporting/.NET timestamps and retain their wall time."""
    value = value.strip()
    if not value or (" " not in value and "T" not in value):
        message = "missing or invalid DateCreated"
        raise PlaybackReportingRowError(message)

    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"

    # Python accepts microseconds up to six digits. .NET's ``fffffff`` can
    # contain seven; truncating the final digit preserves the representable
    # timestamp without changing the second or first six fractional digits.
    match = re.search(r"\.(\d+)(?P<suffix>(?:[+-]\d\d:\d\d)?)$", value)
    if match:
        fraction = match.group(1)[:6].ljust(6, "0")
        value = f"{value[:match.start() + 1]}{fraction}{match.group('suffix')}"

    parsed = datetime.fromisoformat(value.replace(" ", "T", 1))
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
    return parsed


def _append_warning(warnings: list[str], message: str) -> None:
    """Keep diagnostics bounded so a bad export cannot flood task output."""
    if len(warnings) < MAX_WARNING_SAMPLES:
        warnings.append(message)


def _validate_row_fields(
    user_id: str,
    item_id: str,
    item_type: str,
    duration_value: str,
) -> int:
    """Validate structural row fields and return a positive duration."""
    play_duration = int(duration_value)
    if play_duration <= 0:
        message = "PlayDuration must be positive"
        raise PlaybackReportingRowError(message)
    if not user_id or not item_id or not item_type:
        message = "UserId, ItemId, and ItemType are required"
        raise PlaybackReportingRowError(message)
    return play_duration


def parse_tsv(payload: bytes | str) -> PlaybackReportingParseResult:
    """Parse a Playback Reporting export, which has no header row.

    The plugin writes nine tab-separated fields. Item names are not escaped,
    so a literal tab in a title is handled by treating the first four and last
    four columns as structural and joining the middle columns back together.
    """
    if isinstance(payload, bytes):
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            message = "Playback Reporting export is not valid UTF-8."
            raise MediaImportError(message) from error
    else:
        text = payload.lstrip("\ufeff")

    rows: list[PlaybackReportingRow] = []
    warnings: list[str] = []
    rejected_count = 0

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip("\r\n")
        if not line.strip():
            continue

        parts = line.split("\t")
        if line_number == 1 and parts[0].strip().casefold() == "datecreated":
            _append_warning(warnings, "Line 1: skipped a Playback Reporting header row.")
            continue
        if len(parts) < MIN_COLUMNS:
            rejected_count += 1
            _append_warning(
                warnings,
                f"Line {line_number}: expected at least 9 tab-separated columns.",
            )
            continue

        date_created, user_id, item_id, item_type = (part.strip() for part in parts[:4])
        item_name = "\t".join(parts[4:-4])
        playback_method, client_name, device_name, duration_value = (
            part.strip() for part in parts[-4:]
        )
        try:
            date_value = _parse_datetime(date_created)
            play_duration = _validate_row_fields(
                user_id,
                item_id,
                item_type,
                duration_value,
            )
        except (TypeError, PlaybackReportingRowError, ValueError) as error:
            rejected_count += 1
            _append_warning(warnings, f"Line {line_number}: {error}.")
            continue

        rows.append(
            PlaybackReportingRow(
                date_created=date_value,
                user_id=user_id,
                item_id=item_id,
                item_type=item_type,
                item_name=item_name,
                playback_method=playback_method,
                client_name=client_name,
                device_name=device_name,
                play_duration=play_duration,
                line_number=line_number,
            ),
        )

    if rejected_count > len(warnings):
        warnings.append(
            f"{rejected_count - len(warnings)} additional malformed or invalid row(s) were skipped."
        )
    return PlaybackReportingParseResult(rows, warnings, rejected_count)


def _provider_candidates(item: dict) -> list[tuple[str, str]]:
    """Return supported provider IDs in the same deterministic order as push."""
    provider_ids = item.get("ProviderIds") or {}
    candidates = []
    for provider in _PROVIDER_FIELD_ORDER:
        value = provider_ids.get(provider)
        source = _JELLYFIN_PROVIDER_TO_SOURCE.get(provider)
        if value and source:
            candidates.append((source, str(value)))
    return candidates


def _episode_numbers(item: dict) -> tuple[int, int] | None:
    """Return Jellyfin's season/episode numbers when both are usable."""
    try:
        season_number = int(item.get("ParentIndexNumber"))
        episode_number = int(item.get("IndexNumber"))
    except (TypeError, ValueError):
        return None
    if season_number < 0 or episode_number <= 0:
        return None
    return season_number, episode_number


class JellyfinPlaybackReportingImporter:
    """Replay Playback Reporting rows for one connected Jellyfin user."""

    def __init__(self, user, account):
        """Store the Floppy user and connected Jellyfin account."""
        self.user = user
        self.account = account
        self.counts = {MediaTypes.MOVIE.value: 0, MediaTypes.EPISODE.value: 0}
        self.skipped_count = 0
        self.warnings: list[str] = []

    def import_data(self, payload: bytes | str) -> tuple[dict[str, int], str]:
        """Import rows and return created counts plus human-readable diagnostics."""
        parse_result = parse_tsv(payload)
        self.warnings.extend(parse_result.warnings)
        self.skipped_count = parse_result.rejected_count

        if not self.account or not self.account.is_connected:
            message = "Connect Jellyfin before importing Playback Reporting data."
            raise MediaImportError(message)
        if not self.account.jellyfin_user_id:
            message = "Jellyfin user identity is missing. Reconnect Jellyfin before importing."
            raise MediaImportError(message)

        api_key = decrypt_or_raise(self.account.api_key)
        client = JellyfinClient(
            self.account.base_url,
            api_key,
            self.account.jellyfin_user_id,
        )
        library = self._load_library(client)
        user_id = str(self.account.jellyfin_user_id)

        total = len(parse_result.rows)
        for index, row in enumerate(parse_result.rows, start=1):
            import_progress.report(index, total, "Jellyfin Playback Reporting")
            if row.user_id != user_id:
                self._skip(f"Line {row.line_number}: row belongs to another Jellyfin user.")
                continue
            self._import_row(row, library)

        self._save_skipped_count()
        if self.skipped_count:
            self.warnings.append(
                f"Playback Reporting skipped {self.skipped_count} row(s); see the details above."
            )
        return self.counts, "\n".join(dict.fromkeys(self.warnings))

    def _load_library(self, client: JellyfinClient) -> dict[str, dict]:
        """Hydrate source ItemIds from the connected user's Jellyfin library."""
        try:
            return {
                str(item["Id"]): item
                for item in client.iter_library_items()
                if item.get("Id")
            }
        except (JellyfinAuthError, JellyfinClientError) as error:
            message = f"Could not read Jellyfin library: {error}"
            raise MediaImportError(message) from error

    def _import_row(self, row: PlaybackReportingRow, library: dict[str, dict]) -> None:
        item = library.get(row.item_id)
        normalized_type = row.item_type.casefold()
        if item is None:
            self._skip(f"Line {row.line_number}: Jellyfin item {row.item_id} was not found.")
            return
        if normalized_type not in {"movie", "episode"}:
            self._skip(f"Line {row.line_number}: unsupported item type {row.item_type!r}.")
            return
        if str(item.get("Type", "")).casefold() != normalized_type:
            self._skip(f"Line {row.line_number}: Jellyfin item type did not match the export.")
            return

        candidates = _provider_candidates(item)
        series_item = None
        episode_numbers = None
        if normalized_type == "episode":
            series_item = library.get(str(item.get("SeriesId")))
            episode_numbers = _episode_numbers(item)
            if series_item is None or str(series_item.get("Type", "")).casefold() != "series":
                self._skip(f"Line {row.line_number}: parent Jellyfin series was not found.")
                return
            if episode_numbers is None:
                self._skip(f"Line {row.line_number}: season/episode numbers were invalid.")
                return
            candidates = _provider_candidates(series_item)

        if not candidates:
            self._skip(f"Line {row.line_number}: no supported provider ID was found.")
            return

        source, media_id = candidates[0]
        source_id = row.source_identity()
        try:
            if normalized_type == "movie":
                self._import_movie(row, media_id, source, source_id)
            else:
                self._import_episode(
                    row,
                    media_id,
                    source,
                    source_id,
                    episode_numbers,
                )
        except Exception as error:  # provider metadata failures are row-level skips
            logger.warning(
                "Playback Reporting row %s could not be imported: %s",
                row.line_number,
                error,
            )
            self._skip(f"Line {row.line_number}: could not resolve metadata ({error}).")

    def _import_movie(
        self,
        row: PlaybackReportingRow,
        media_id: str,
        source: str,
        source_id: str,
    ) -> None:
        if MoviePlay.objects.filter(
            movie__user=self.user,
            external_id=source_id,
        ).exists():
            self._skip(f"Line {row.line_number}: already imported.")
            return

        movie = fork_services_movie.resolve_or_create_movie(self.user, media_id, source)
        import_run_id = import_progress.get_current_import_run_id()
        if import_run_id and movie.import_run_id != import_run_id:
            movie.import_run_id = import_run_id
            movie.save(update_fields=["import_run"])
        _, created = movie.watch(row.date_created, external_id=source_id)
        if created:
            self.counts[MediaTypes.MOVIE.value] += 1
        else:
            self._skip(f"Line {row.line_number}: already imported.")

    def _import_episode(
        self,
        row: PlaybackReportingRow,
        media_id: str,
        source: str,
        source_id: str,
        episode_numbers: tuple[int, int] | None,
    ) -> None:
        if episode_numbers is None:
            self._skip(f"Line {row.line_number}: season/episode numbers were invalid.")
            return
        season_number, episode_number = episode_numbers
        operation_id = uuid5(NAMESPACE_URL, source_id)
        if Episode.objects.filter(watch_operation_id=operation_id).exists():
            self._skip(f"Line {row.line_number}: already imported.")
            return

        season = fork_services_episode.resolve_or_create_season(
            self.user,
            media_id,
            source,
            season_number,
        )
        result = season.watch(
            episode_number,
            row.date_created,
            watch_operation_id=operation_id,
        )
        if result.created:
            self.counts[MediaTypes.EPISODE.value] += 1
        else:
            self._skip(f"Line {row.line_number}: already imported.")

    def _skip(self, message: str) -> None:
        self.skipped_count += 1
        _append_warning(self.warnings, message)

    def _save_skipped_count(self) -> None:
        import_run_id = import_progress.get_current_import_run_id()
        if import_run_id:
            ImportRun.objects.filter(id=import_run_id).update(
                skipped_count=self.skipped_count,
            )


def importer(file, user, mode):
    """Import a Playback Reporting TSV for the user's connected Jellyfin account."""
    del mode  # Playback Reporting identities make repeated uploads idempotent.
    payload = file.read() if hasattr(file, "read") else file
    return JellyfinPlaybackReportingImporter(
        user,
        getattr(user, "jellyfin_account", None),
    ).import_data(payload)
