"""Shared filesystem staging for uploads handed to background tasks."""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
import time
import zipfile
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

STAGING_DIRECTORY_NAME = "import-staging"
UPLOAD_COPY_CHUNK_SIZE = 1024 * 1024
STALE_UPLOAD_AGE_SECONDS = 24 * 60 * 60
MAX_UPLOAD_SUFFIX_LENGTH = 32
SAFE_SUFFIX_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-",
)
OUTSIDE_STAGING_DIRECTORY_MESSAGE = "Uploaded file path is outside the staging directory"


def staging_directory() -> Path:
    """Return the private, shared directory used for staged uploads."""
    directory = Path(settings.FLOPPY_DATA_DIR) / STAGING_DIRECTORY_NAME
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        directory.chmod(0o700)
    return directory


def _suffix_for_upload(upload_name) -> str:
    """Return a safe suffix so importers can retain format detection."""
    suffixes = "".join(Path(str(upload_name or "")).suffixes)
    if not suffixes or len(suffixes) > MAX_UPLOAD_SUFFIX_LENGTH:
        return ".upload"
    if any(character not in SAFE_SUFFIX_CHARACTERS for character in suffixes):
        return ".upload"
    return suffixes


def prune_staged_uploads(*, now=None) -> int:
    """Remove abandoned staged files older than the retention window."""
    directory = staging_directory()
    cutoff = (time.time() if now is None else now) - STALE_UPLOAD_AGE_SECONDS
    removed = 0
    try:
        entries = directory.iterdir()
    except OSError:
        return 0

    for entry in entries:
        if not entry.is_file():
            continue
        try:
            if entry.stat().st_mtime >= cutoff:
                continue
            entry.unlink()
        except OSError:
            logger.warning("Could not prune staged upload %s", entry, exc_info=True)
        else:
            removed += 1
    return removed


def stage_uploaded_file(upload) -> Path:
    """Copy an uploaded file to shared storage without materializing it."""
    prune_staged_uploads()
    directory = staging_directory()
    descriptor, path = tempfile.mkstemp(
        prefix=".upload-",
        suffix=_suffix_for_upload(getattr(upload, "name", None)),
        dir=directory,
    )
    try:
        with os.fdopen(descriptor, "wb") as destination:
            descriptor = None
            if hasattr(upload, "seek"):
                with contextlib.suppress(AttributeError, OSError):
                    upload.seek(0)

            chunks = getattr(upload, "chunks", None)
            if chunks is not None:
                iterator = chunks(UPLOAD_COPY_CHUNK_SIZE)
            else:
                iterator = iter(
                    lambda: upload.read(UPLOAD_COPY_CHUNK_SIZE),
                    b"",
                )
            for chunk in iterator:
                destination.write(chunk)
    except Exception:
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        with contextlib.suppress(OSError):
            Path(path).unlink()
        raise
    return Path(path)


def discard_staged_upload(path) -> None:
    """Delete a staged upload if it belongs to the staging directory."""
    try:
        validated = _validate_staged_path(path, require_exists=False)
    except (TypeError, ValueError, OSError):
        return
    with contextlib.suppress(OSError):
        validated.unlink()


def _is_staged_path(value) -> bool:
    """Return whether *value* looks like a path produced by this module."""
    if not isinstance(value, (str, os.PathLike)):
        return False
    try:
        candidate = Path(value)
        root = staging_directory()
        return candidate.is_absolute() and candidate.parent == root
    except (TypeError, ValueError, OSError):
        return False


def _validate_staged_path(path, *, require_exists=True) -> Path:
    """Validate that a task path stays inside the private staging directory."""
    candidate = Path(path)
    root = staging_directory().resolve()
    resolved = candidate.resolve(strict=require_exists)
    if not resolved.is_relative_to(root):
        raise ValueError(OUTSIDE_STAGING_DIRECTORY_MESSAGE)
    return resolved


@contextmanager
def open_import_file(payload):
    """Open a staged task payload and clean it up when the task exits.

    Bytes and file-like objects remain supported for direct task callers and
    older integrations. Only paths created by :func:`stage_uploaded_file` are
    deleted automatically.
    """
    if _is_staged_path(payload) or (
        isinstance(payload, (str, os.PathLike)) and Path(payload).is_absolute()
    ):
        path = _validate_staged_path(payload)
        try:
            with path.open("rb") as file:
                yield file
        finally:
            discard_staged_upload(path)
        return

    if hasattr(payload, "read"):
        with contextlib.suppress(AttributeError, OSError):
            payload.seek(0)
        yield payload
        return

    if isinstance(payload, bytes):
        with BytesIO(payload) as file:
            yield file
        return

    if isinstance(payload, str):
        with BytesIO(payload.encode("utf-8")) as file:
            yield file
        return

    msg = f"Unsupported uploaded file payload type: {type(payload)!r}"
    raise TypeError(msg)


def enqueue_staged_task(task, *args, staged_paths=(), **kwargs):
    """Queue a task and remove staged files if publishing fails."""
    try:
        return task.delay(*args, **kwargs)
    except Exception:
        for path in staged_paths:
            discard_staged_upload(path)
        raise


def build_staged_zip(payloads) -> Path:
    """Build a ZIP from staged ``(name, path)`` pairs without loading bytes."""
    directory = staging_directory()
    descriptor, path = tempfile.mkstemp(
        prefix=".upload-",
        suffix=".zip",
        dir=directory,
    )
    try:
        os.close(descriptor)
        descriptor = None
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, source_path in payloads:
                validated = _validate_staged_path(source_path)
                archive.write(validated, arcname=Path(name).name)
    except Exception:
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        with contextlib.suppress(OSError):
            Path(path).unlink()
        raise
    return Path(path)


def staged_payload_is_zip(path) -> bool:
    """Check a staged payload's ZIP signature without reading it into memory."""
    validated = _validate_staged_path(path)
    with validated.open("rb") as file:
        return file.read(4) == b"PK\x03\x04"
