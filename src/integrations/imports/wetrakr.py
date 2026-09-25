"""Import a WeTrakr data export (a ``.zip`` of flat ``.csv`` files).

WeTrakr has no public API yet, but its export carries the same kinds of data
as Trakt's: ``tracklog.csv`` (history, watchlist, dropped), ``ratings.csv``,
``notes.csv`` and ``lists.csv``. ``WeTrakrExport`` converts those rows into the
shapes the Trakt API returns, so ``WeTrakrImporter`` can run the standard
``TraktImporter`` unchanged, the same way ``trakt_export`` does.

Quirks of the format handled here:

- Episode rows carry the *episode's* TMDB id, and name their show only by
  ``show_title``. The show id comes from a show row in the same export, else a
  TMDB lookup of the episode's IMDb id, else the Trakt importer's title search.
- Season ratings carry an unusable ``season_number``, and list rows have no
  season number at all, so season rows are skipped with a warning.
- Dates are JavaScript ``Date.toString()`` text, and may be blank.
"""

import csv
import io
import logging
import zipfile
from datetime import datetime

from app.models import Status
from app.providers import services
from integrations.imports.helpers import MediaImportError, MediaImportUnexpectedError
from integrations.imports.trakt import TRAKT_UNKNOWN_DATE, TraktImporter

logger = logging.getLogger(__name__)

# The archive is read fully into memory, so cap what an upload can expand to.
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024

SECTIONS = ("tracklog", "ratings", "notes", "lists", "profile")

# How many of a show's episode IMDb ids to try against TMDB before giving up.
MAX_SHOW_LOOKUPS = 3


def parse_wetrakr_date(value):
    """Parse ``Wed Mar 21 2018 03:42:00 GMT+0000 (Coordinated Universal Time)``."""
    text = (value or "").split(" (", 1)[0].strip()
    if not text:
        return None
    for date_format in ("%a %b %d %Y %H:%M:%S GMT%z", "%a %B %d %Y %H:%M:%S GMT%z"):
        try:
            return datetime.strptime(text, date_format)  # noqa: DTZ007 - %z parses the offset
        except ValueError:
            continue
    return None


def _iso(value):
    """Return a WeTrakr date as the ISO text Trakt payloads use, or ``None``."""
    parsed = parse_wetrakr_date(value)
    return parsed.isoformat() if parsed else None


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ids(row):
    return {"tmdb": _int(row.get("tmdb_id")), "imdb": row.get("imdb_id") or None}


class WeTrakrExport:
    """Read a WeTrakr export ``.zip`` and serve its rows as Trakt-shaped entries."""

    def __init__(self, file):
        """Open the archive and parse every known CSV section."""
        try:
            archive = zipfile.ZipFile(file)
        except zipfile.BadZipFile as error:
            msg = "The uploaded file is not a valid WeTrakr export."
            raise MediaImportError(msg) from error

        self.warnings = []
        self.rows = {section: [] for section in SECTIONS}
        # Sections present in the upload, even when a file has no rows.
        self.sections_found = set()

        total_size = 0
        for info in archive.infolist():
            if info.is_dir():
                continue
            total_size += info.file_size
            if total_size > MAX_UNCOMPRESSED_BYTES:
                msg = "The WeTrakr export is too large to import."
                raise MediaImportError(msg)

            name = info.filename.rsplit("/", 1)[-1].lower()
            if not name.endswith(".csv"):
                continue
            # Match "tracklog.csv" and also renamed or split files such as
            # "tracklog_2.csv".
            section = next((s for s in SECTIONS if name.startswith(s)), None)
            if section is None:
                continue
            try:
                text = archive.read(info.filename).decode("utf-8-sig")
            except UnicodeDecodeError:
                self.warnings.append(f"{info.filename}: could not be read, skipped.")
                continue
            self.rows[section].extend(csv.DictReader(io.StringIO(text)))
            self.sections_found.add(section)

        if not any(self.rows[s] for s in ("tracklog", "ratings", "notes", "lists")):
            msg = (
                "No WeTrakr data was found. Upload the export .zip, or its "
                "tracklog, ratings, notes or lists .csv files."
            )
            raise MediaImportError(msg)

        self._show_ids = self._index_show_ids()
        self._episodes = self._index_episodes()

    @property
    def username(self):
        """Return the WeTrakr username from ``profile.csv``, if present."""
        profile = self.rows["profile"]
        return (profile[0].get("username") if profile else None) or "WeTrakr export"

    def _index_show_ids(self):
        """Map a show title to its TMDB id, from rows that describe the show."""
        show_ids = {}
        for section in ("tracklog", "ratings", "notes", "lists"):
            for row in self.rows[section]:
                tmdb_id = _int(row.get("tmdb_id"))
                if row.get("type") in {"show", "season"} and row.get("title") and tmdb_id:
                    show_ids.setdefault(row["title"].casefold(), tmdb_id)
        return show_ids

    def _index_episodes(self):
        """Map an episode's TMDB id to its show title, season and number."""
        episodes = {}
        for section in ("tracklog", "ratings", "notes"):
            for row in self.rows[section]:
                if row.get("type") != "episode":
                    continue
                episode_id = _int(row.get("tmdb_id"))
                season = _int(row.get("season_number"))
                number = _int(row.get("episode_number"))
                if episode_id and row.get("show_title") and None not in (season, number):
                    episodes.setdefault(
                        episode_id,
                        (row["show_title"], season, number),
                    )
        return episodes

    def _show_payload(self, show_title):
        """Return a Trakt show payload for ``show_title``, resolving its TMDB id."""
        key = show_title.casefold()
        if key not in self._show_ids:
            self._show_ids[key] = self._find_show_id(show_title)
        return {"title": show_title, "ids": {"tmdb": self._show_ids[key]}}

    def _find_show_id(self, show_title):
        """Look a show up on TMDB through one of its episodes' IMDb ids."""
        imdb_ids = list(
            dict.fromkeys(
                row["imdb_id"]
                for section in ("tracklog", "ratings", "notes")
                for row in self.rows[section]
                if row.get("type") == "episode"
                and row.get("show_title") == show_title
                and row.get("imdb_id")
            ),
        )
        for imdb_id in imdb_ids[:MAX_SHOW_LOOKUPS]:
            episode = self._find_episode(imdb_id)
            if episode:
                return episode.get("show_id")
        # None lets the Trakt importer fall back to a TMDB title search.
        return None

    def _find_episode(self, imdb_id):
        """Return TMDB's episode match for an IMDb id, or ``None``."""
        try:
            results = services.tmdb.find(imdb_id, "imdb_id")
        except services.ProviderAPIError:
            logger.warning("TMDB lookup failed for WeTrakr episode %s", imdb_id)
            return None
        episodes = results.get("tv_episode_results") or []
        return episodes[0] if episodes else None

    def _entry(self, row, **extra):
        """Build a Trakt-shaped entry for a movie, show or episode row."""
        row_type = row.get("type")
        entry = {"type": row_type, **extra}
        if row_type in {"movie", "show"}:
            entry[row_type] = {
                "title": row.get("title") or "",
                "year": _int(row.get("year")),
                "ids": _ids(row),
            }
            return entry
        if row_type == "episode":
            season = _int(row.get("season_number"))
            number = _int(row.get("episode_number"))
            if not row.get("show_title") or None in (season, number):
                return None
            entry["episode"] = {
                "season": season,
                "number": number,
                "title": row.get("title") or "",
            }
            entry["show"] = self._show_payload(row["show_title"])
            return entry
        return None

    def history(self):
        """Return watched movie and episode rows, newest first like Trakt."""
        entries = []
        for row in self.rows["tracklog"]:
            if row.get("status") != "watched" or row.get("type") not in {
                "movie",
                "episode",
            }:
                # "watched"/"watching" show rows add nothing: a show's progress
                # and completion already follow from its watched episodes.
                continue
            watched_at = parse_wetrakr_date(row.get("tracked_at"))
            entry = self._entry(
                row,
                watched_at=watched_at.isoformat() if watched_at else TRAKT_UNKNOWN_DATE,
            )
            if entry:
                sort_key = watched_at.timestamp() if watched_at else float("-inf")
                entries.append((sort_key, entry))

        # Undated plays sort as the oldest; TraktImporter replays in reverse.
        entries.sort(key=lambda pair: pair[0], reverse=True)
        return [entry for _, entry in entries]

    def _tracklog_entries(self, status, types):
        entries = []
        for row in self.rows["tracklog"]:
            if row.get("status") == status and row.get("type") in types:
                entry = self._entry(row, listed_at=_iso(row.get("tracked_at")))
                if entry:
                    entries.append(entry)
        return entries

    def watchlist(self):
        """Return ``plantowatch`` movies and shows."""
        return self._tracklog_entries("plantowatch", {"movie", "show"})

    def dropped_shows(self):
        """Return ``discarded`` shows, shaped like Trakt's hidden progress items."""
        return self._tracklog_entries("discarded", {"show"})

    def dropped(self):
        """Return ``discarded`` movies and shows."""
        return self._tracklog_entries("discarded", {"movie", "show"})

    def ratings(self):
        """Return movie, show and episode ratings; season ratings are skipped."""
        entries = []
        skipped_seasons = 0
        for row in self.rows["ratings"]:
            rating = _int(row.get("rating"))
            if rating is None:
                continue
            if row.get("type") == "season":
                skipped_seasons += 1
                continue
            entry = self._entry(row, rating=rating, rated_at=_iso(row.get("rated_at")))
            if entry:
                entries.append(entry)
        if skipped_seasons:
            self.warnings.append(
                f"Skipped {skipped_seasons} season rating(s): WeTrakr's export "
                "does not say which season they belong to.",
            )
        return entries

    def notes(self):
        """Return notes as Trakt note entries."""
        entries = []
        skipped_episodes = 0
        for row in self.rows["notes"]:
            text = (row.get("text") or "").strip()
            if not text:
                continue
            if row.get("type") not in {"movie", "show"}:
                # The Trakt import stores notes on movies and shows only.
                skipped_episodes += 1
                continue
            entry = self._entry(row, note={"notes": text})
            if entry:
                entries.append(entry)
        if skipped_episodes:
            self.warnings.append(
                f"Skipped {skipped_episodes} note(s) on episodes or seasons: "
                "Floppy imports notes for movies and shows only.",
            )
        return entries

    def lists(self):
        """Return ``[(name, description, entries)]`` with items in rank order."""
        grouped = {}
        skipped = 0
        for row in self.rows["lists"]:
            name = (row.get("list_name") or "").strip()
            if not name:
                continue
            _, _, rows = grouped.setdefault(
                name,
                (name, row.get("list_description") or "", []),
            )
            rows.append(row)

        result = []
        for name, description, rows in grouped.values():
            rows.sort(key=lambda row: _int(row.get("rank")) or 0)
            entries = []
            for row in rows:
                entry = self._list_entry(row)
                if entry:
                    entries.append(entry)
                else:
                    skipped += 1
            result.append((name, description, entries))

        if skipped:
            self.warnings.append(
                f"Skipped {skipped} list item(s) whose show, season or episode "
                "could not be identified.",
            )
        return result

    def _list_entry(self, row):
        """Build a list entry; episodes are located through other export rows."""
        if row.get("type") in {"movie", "show"}:
            return self._entry(row)
        if row.get("type") != "episode":
            # Season rows have no season number in lists.csv.
            return None

        episode_id = _int(row.get("tmdb_id"))
        known = self._episodes.get(episode_id)
        if known:
            show_title, season, number = known
            return {
                "type": "episode",
                "episode": {"season": season, "number": number},
                "show": self._show_payload(show_title),
            }

        match = self._find_episode(row["imdb_id"]) if row.get("imdb_id") else None
        if not match or None in (
            match.get("show_id"),
            match.get("season_number"),
            match.get("episode_number"),
        ):
            return None
        return {
            "type": "episode",
            "episode": {
                "season": match["season_number"],
                "number": match["episode_number"],
            },
            "show": {"title": row.get("title") or "", "ids": {"tmdb": match["show_id"]}},
        }


class WeTrakrImporter(TraktImporter):
    """Run the standard Trakt import over a WeTrakr export instead of the API."""

    def __init__(self, export, user, mode):
        """Initialize from ``export``; the only network use is TMDB."""
        self.export = export
        super().__init__(export.username, user, mode)
        # Saved match decisions are keyed by Trakt ids, which WeTrakr lacks.
        self.external_reference_integration = None

    def _validate_username(self):
        """No account to validate for a file import."""

    def _supports_hidden_sections(self):
        """Read dropped shows unconditionally: they come from the tracklog."""
        return True

    def _make_api_request(self, url):
        """Guard against an unconverted code path silently calling Trakt."""
        msg = f"WeTrakr import attempted a Trakt request to {url}."
        raise MediaImportUnexpectedError(msg)

    def _get_paginated_data(self, endpoint, item_type="items"):
        """Serve the export rows standing in for a Trakt ``endpoint``."""
        path = endpoint.removeprefix(self.user_base_url)
        sections = {
            "/history": self.export.history,
            "/watchlist": self.export.watchlist,
            "/ratings": self.export.ratings,
            "/notes": self.export.notes,
            "/hidden/progress_watched": self.export.dropped_shows,
        }
        reader = sections.get(path)
        return reader() if reader else []

    def process_watchlist(self):
        """Import the watchlist, then mark discarded items as dropped.

        Trakt's dropped list only marks shows that history creates; a WeTrakr
        user can also discard a movie, or a show they never started.
        """
        super().process_watchlist()
        for entry in self.export.dropped():
            self._process_generic_entry(
                entry,
                "watchlist",
                {"status": Status.DROPPED.value},
            )

    def import_data(self):
        """Import the export, adding the export's own skip warnings."""
        imported_counts, messages = super().import_data()
        extra = [w for w in self.export.warnings if w not in messages]
        if extra:
            messages = "\n".join(filter(None, [messages, *dict.fromkeys(extra)]))
        return imported_counts, messages


def importer(file, user, mode):
    """Import history, ratings, notes and lists from a WeTrakr export."""
    # Imported here to keep the integrations -> lists dependency at call time.
    from lists.imports.wetrakr import import_wetrakr_lists

    export = WeTrakrExport(file)
    overwrite_skipped = mode == "overwrite" and "tracklog" not in export.sections_found
    if overwrite_skipped:
        # Overwrite replaces each item it touches with what the upload says.
        # Without the tracklog, that would wipe the watch status of every
        # rated or noted item, so only add what is new.
        mode = "new"
    imported_counts, messages = WeTrakrImporter(export, user, mode).import_data()
    if overwrite_skipped:
        messages = "\n".join(
            filter(
                None,
                [
                    "No tracklog.csv was uploaded, so existing items were kept "
                    "instead of overwritten.",
                    messages,
                ],
            ),
        )

    if "lists" not in export.sections_found:
        # Keep lists from an earlier import when this upload has no lists file.
        return imported_counts, messages

    before = set(export.warnings)
    lists_created, items_skipped = import_wetrakr_lists(user, export.lists())
    if lists_created:
        imported_counts["lists"] = lists_created
    list_warnings = [w for w in export.warnings if w not in before]
    if items_skipped:
        list_warnings.append(
            f"Skipped {items_skipped} list item(s) that could not be matched in TMDB.",
        )
    if list_warnings:
        messages = "\n".join(filter(None, [messages, *list_warnings]))

    return imported_counts, messages
