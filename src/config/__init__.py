import logging
import os
import sqlite3
from importlib import import_module

from decouple import config

from config.sqlite_safety import prepare_sqlite_environment

# Install the shared log boundary before Django, Celery, or Gunicorn configures
# handlers. Every Python log record is redacted once before any handler writes
# it.
try:
    from app.log_safety import install_redacting_log_record_factory
except ModuleNotFoundError as error:
    # The data path checks import config with only config on sys.path, so the
    # app package is absent by design. Any other missing module is a fault:
    # raise it, or the process starts with no redaction and no warning.
    if error.name != "app":
        raise
else:
    install_redacting_log_record_factory()

_sqlite_policy = prepare_sqlite_environment(config, os.environ)
if _sqlite_policy is not None:
    (
        _requested_journal,
        _effective_journal,
        _effective_synchronous,
        _fallback_applied,
    ) = _sqlite_policy
    if _fallback_applied:
        logging.getLogger(__name__).warning(
            "SQLite %s is affected by the WAL-reset corruption bug. "
            "Floppy requested %s but will use %s journal mode with "
            "synchronous=%s for data safety. Upgrade SQLite to 3.51.3 or "
            "later, or a fixed 3.44.6/3.50.7 backport, to restore WAL mode.",
            sqlite3.sqlite_version,
            _requested_journal,
            _effective_journal,
            _effective_synchronous,
        )

# Load Celery only after the SQLite policy has been published. import_module()
# keeps this required runtime order without a late module-level import.
celery_app = import_module("config.celery").app

__all__ = ("celery_app",)
