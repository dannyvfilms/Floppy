"""Reuse an image's static collection only while its inputs and output match.

The record is written at image build time, never during startup. A mismatch
falls back to Django's normal collectstatic command. Metadata uses whole-second
mtimes, as collectstatic does when deciding whether a file is unmodified.
Invoke this file directly so a check does not import config's Celery bootstrap.
"""

import hashlib
import json
import os
import stat
import sys
from pathlib import Path

from decouple import AutoConfig, Csv

_BASE_DIR = Path(__file__).resolve().parent.parent
_SETTINGS = _BASE_DIR / "config/settings.py"
_STATIC_ROOT = _BASE_DIR / "staticfiles"
_RECORD = Path("/etc/floppy/static-collection.json")
_OWNER = (1000, 1000)


def _mode() -> dict | None:
    """Match the runtime settings which select static-file applications."""
    if os.environ.get("DJANGO_SETTINGS_MODULE", "config.settings") != "config.settings":
        return None
    config = AutoConfig(search_path=str(_SETTINGS.parent))
    debug = config("DEBUG", default=False, cast=bool)
    return {
        "debug": debug,
        "toolbar": debug and config("ENABLE_DEBUG_TOOLBAR", default=True, cast=bool),
        "providers": config("SOCIAL_PROVIDERS", default="", cast=Csv()),
        "role": os.environ.get("FLOPPY_PROCESS_ROLE", ""),
    }


def _tree(root: Path) -> dict | None:
    """Snapshot files and directory ownership without reading asset bodies."""
    if root.is_symlink():
        message = "static symlinks require collectstatic"
        raise ValueError(message)
    if not root.exists():
        return None
    result = {}
    for path in [root, *sorted(root.rglob("*"))]:
        info = path.lstat()
        regular = stat.S_ISREG(info.st_mode)
        if not (regular or stat.S_ISDIR(info.st_mode)):
            message = "non-regular static files require collectstatic"
            raise ValueError(message)
        result[str(path.relative_to(root))] = [
            info.st_mode,
            info.st_size if regular else 0,
            int(info.st_mtime) if regular else 0,
            info.st_uid,
            info.st_gid,
        ]
    return result


def collection_is_current() -> bool:
    """Validate the build record without initializing Django or writing state."""
    try:
        mode = _mode()
        record = json.loads(_RECORD.read_text())
        if (
            mode is None
            or not isinstance(record, dict)
            or record.get("version") != 1
            or record.get("mode") != mode
            or record.get("settings")
            != hashlib.sha256(_SETTINGS.read_bytes()).hexdigest()
            or record.get("owner") != list(_OWNER)
            or not isinstance(record.get("inputs"), dict)
            or not record["inputs"]
            or not isinstance(record.get("output"), dict)
            or not record["output"]
        ):
            return False
        return (
            all(row[-2:] == list(_OWNER) for row in record["output"].values())
            and _tree(_STATIC_ROOT) == record["output"]
            and all(
                _tree(Path(root)) == tree for root, tree in record["inputs"].items()
            )
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def record_collection() -> bool:
    """Record only the default local storage and supported filesystem finders."""
    from django.apps import apps
    from django.conf import settings
    from django.contrib.staticfiles.finders import (
        AppDirectoriesFinder,
        FileSystemFinder,
        get_finders,
    )
    from django.contrib.staticfiles.storage import StaticFilesStorage
    from django.core.files.storage import storages

    _RECORD.unlink(missing_ok=True)
    mode = _mode()
    if (
        mode is None
        or Path(settings.STATIC_ROOT) != _STATIC_ROOT
        or type(storages["staticfiles"]) is not StaticFilesStorage
    ):
        return False
    roots = set()
    for finder in get_finders():
        if type(finder) is FileSystemFinder:
            roots.update(Path(root) for _prefix, root in finder.locations)
        elif type(finder) is AppDirectoriesFinder:
            # Include absent directories so adding one also invalidates the record.
            roots.update(Path(app.path) / "static" for app in apps.get_app_configs())
        else:
            return False
    try:
        inputs = {str(root): _tree(root) for root in sorted(roots)}
        output = _tree(_STATIC_ROOT)
    except (OSError, ValueError):
        return False
    if not output or any(row[-2:] != list(_OWNER) for row in output.values()):
        return False
    _RECORD.write_text(
        json.dumps(
            {
                "version": 1,
                "mode": mode,
                "settings": hashlib.sha256(_SETTINGS.read_bytes()).hexdigest(),
                "owner": list(_OWNER),
                "inputs": inputs,
                "output": output,
            },
            sort_keys=True,
        )
        + "\n",
    )
    return True


if __name__ == "__main__":
    if sys.argv[1:] == ["--record"]:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
        # Run as a script, sys.path[0] is config/: `config` is not importable
        # and config/celery.py would shadow the celery package.
        sys.path[0] = str(_BASE_DIR)
        sys.argv = ["manage.py", "collectstatic"]
        import django

        django.setup()
        record_collection()
    else:
        raise SystemExit(0 if collection_is_current() else 1)
