"""Import a Trakt data export archive (the ``.zip`` of flat ``.json`` files).

Trakt's export ships one JSON file per section, paginated across numbered
suffixes (``watched-history-1.json`` … ``watched-history-51.json``).  Each
payload is shaped exactly like the corresponding Trakt API response, so this
module reuses ``TraktImporter`` wholesale and only swaps its fetch layer:
``TraktExportImporter`` overrides ``_get_paginated_data`` to read files out of
the archive instead of paging over HTTP.
"""

import json
import logging
import re
import zipfile

from integrations.imports.helpers import MediaImportError, MediaImportUnexpectedError
from integrations.imports.trakt import TraktImporter

logger = logging.getLogger(__name__)

# The archive is read fully into memory, so cap what a single upload can expand
# to. A large real-world export is a few hundred MB decompressed at most.
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024

# Trakt endpoint path (relative to the user base URL) -> export file prefixes.
ENDPOINT_FILES = {
    "/history": ("watched-history",),
    "/watchlist": ("lists-watchlist",),
    "/ratings": (
        "ratings-movies",
        "ratings-shows",
        "ratings-seasons",
        "ratings-episodes",
    ),
    "/comments": (
        "comments-movies",
        "comments-shows",
        "comments-seasons",
        "comments-episodes",
    ),
    "/notes": (
        "notes-movies",
        "notes-shows",
        "notes-seasons",
        "notes-episodes",
    ),
    "/collection/movies": ("collection-movies",),
    "/collection/shows": ("collection-shows",),
    "/hidden/progress_watched": ("hidden-progress-watched",),
    "/hidden/progress_watched_reset": ("hidden-progress-watched-reset",),
}

LIST_ITEMS_PATTERN = re.compile(r"^lists-list-(\d+)-")
PAGE_SUFFIX_PATTERN = re.compile(r"^(?P<prefix>.+)-(?P<page>\d+)$")


class TraktExportArchive:
    """Read-only view over a Trakt export ``.zip``.

    Members are addressed by *prefix*: a prefix matches a file whose basename
    (minus ``.json``) is either the prefix itself or the prefix followed by
    ``-<page number>``. That exact-or-numbered rule is what keeps
    ``hidden-progress-watched`` from also matching
    ``hidden-progress-watched-reset``, and ``watched-history`` from matching
    ``watched-movies``.
    """

    def __init__(self, file):
        """Open the archive and index its JSON members by base name."""
        try:
            self.zipfile = zipfile.ZipFile(file)
        except zipfile.BadZipFile as error:
            msg = "The uploaded file is not a valid Trakt export archive."
            raise MediaImportError(msg) from error

        self.warnings = []
        self._members = {}

        total_size = 0
        for info in self.zipfile.infolist():
            if info.is_dir():
                continue
            total_size += info.file_size
            if total_size > MAX_UNCOMPRESSED_BYTES:
                msg = "The Trakt export archive is too large to import."
                raise MediaImportError(msg)

            # Trakt's archive is flat, but tolerate one wrapped in a folder.
            name = info.filename.rsplit("/", 1)[-1]
            if not name.lower().endswith(".json"):
                continue
            self._members[name[: -len(".json")]] = info.filename

    def read_json(self, base_name, default=None):
        """Return the parsed contents of a single member, or ``default``."""
        filename = self._members.get(base_name)
        if filename is None:
            return default

        try:
            return json.loads(self.zipfile.read(filename))
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.exception("Skipping unreadable Trakt export file %s", filename)
            self.warnings.append(f"{filename}: could not be read, skipped.")
            return default

    def load(self, *prefixes):
        """Concatenate every member matching any of ``prefixes``, in page order."""
        entries = []
        for prefix in prefixes:
            for base_name in self._matching_names(prefix):
                page = self.read_json(base_name, default=[])
                if isinstance(page, list):
                    entries.extend(page)
                else:
                    self.warnings.append(
                        f"{base_name}.json: unexpected contents, skipped.",
                    )
        return entries

    def list_item_files(self):
        """Group ``lists-list-<trakt_id>-<slug>[-<page>].json`` members by list id."""
        grouped = {}
        for base_name in self._members:
            match = LIST_ITEMS_PATTERN.match(base_name)
            if match:
                grouped.setdefault(match.group(1), []).append(base_name)
        for base_names in grouped.values():
            base_names.sort()
        return grouped

    def _matching_names(self, prefix):
        """Return base names for ``prefix``, unnumbered first then by page."""
        names = []
        if prefix in self._members:
            names.append((0, prefix))

        for base_name in self._members:
            match = PAGE_SUFFIX_PATTERN.match(base_name)
            if match and match.group("prefix") == prefix:
                names.append((int(match.group("page")), base_name))

        names.sort()
        return [name for _, name in names]


class TraktExportImporter(TraktImporter):
    """Run the standard Trakt import against an export archive instead of the API."""

    def __init__(self, archive, user, mode):
        """Initialize from ``archive``; no network access is performed."""
        self.archive = archive
        profile = archive.read_json("user-profile", default={}) or {}
        username = profile.get("username") or "Trakt export"
        super().__init__(username, user, mode)
        self.warnings.extend(archive.warnings)

    def _supports_hidden_sections(self):
        """Read hidden sections unconditionally: the export always includes them."""
        return True

    def _validate_username(self):
        """No user endpoint to validate against for a file import."""

    def _make_api_request(self, url):
        """Guard against an unconverted code path silently hitting the network."""
        msg = f"Trakt export import attempted a network request to {url}."
        raise MediaImportUnexpectedError(msg)

    def _get_paginated_data(self, endpoint, item_type="items"):
        """Read the export files standing in for ``endpoint``."""
        path = endpoint.removeprefix(self.user_base_url)
        prefixes = ENDPOINT_FILES.get(path)
        if prefixes is None:
            logger.warning("No Trakt export file mapped for endpoint %s", endpoint)
            return []

        entries = self.archive.load(*prefixes)
        logger.info(
            "Read %s %s from the Trakt export for user %s",
            len(entries),
            item_type,
            self.username,
        )
        return entries

    def import_data(self):
        """Import the archive, surfacing any file-level read warnings."""
        imported_counts, messages = super().import_data()
        # Warnings raised while reading files during the import itself.
        extra = [w for w in self.archive.warnings if w not in messages]
        if extra:
            messages = "\n".join(filter(None, [messages, *dict.fromkeys(extra)]))
        return imported_counts, messages


def importer(file, user, mode):
    """Import media and custom lists from a Trakt data export archive."""
    # Imported here to keep the integrations -> lists dependency at call time.
    from lists.imports.trakt import import_trakt_lists_from_export

    archive = TraktExportArchive(file)

    export_importer = TraktExportImporter(archive, user, mode)
    imported_counts, messages = export_importer.import_data()

    lists_created, list_warnings = import_trakt_lists_from_export(user, archive)
    if lists_created:
        imported_counts["lists"] = lists_created
    if list_warnings:
        messages = "\n".join(
            filter(None, [messages, *dict.fromkeys(list_warnings)]),
        )

    return imported_counts, messages
