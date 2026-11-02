"""Private temporary history pages, retaining only one decoded page at a time."""

import json
from tempfile import TemporaryFile


class HistoryPages:
    """Append provider pages and traverse their entries in reverse order.

    The unlinked temporary file is not a resumable import checkpoint. Its
    descriptors grow with pages, rather than retaining every decoded watch.
    """

    def __init__(self):
        """Open a private spool whose lifecycle belongs to the import stage."""
        self._file = TemporaryFile(mode="w+b")  # noqa: SIM115 - closed by stage ExitStack
        self._pages = []
        self._count = 0

    def extend(self, entries):
        """Store a JSON provider page without retaining its Python objects."""
        payload = json.dumps(entries, separators=(",", ":")).encode("utf-8")
        self._file.seek(0, 2)
        offset = self._file.tell()
        self._file.write(payload)
        self._pages.append((offset, len(payload)))
        self._count += len(entries)

    def __len__(self):
        """Return the exact number of gathered watches."""
        return self._count

    def __reversed__(self):
        """Decode one page at a time in the original reversed-list order."""
        for offset, size in reversed(self._pages):
            self._file.seek(offset)
            entries = json.loads(self._file.read(size))
            yield from reversed(entries)
            del entries

    def close(self):
        """Release history on normal completion, failure, or cancellation."""
        self._file.close()
