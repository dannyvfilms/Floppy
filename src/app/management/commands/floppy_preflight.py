import json
import sqlite3
import sys

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor

class Command(BaseCommand):
    help = "Run preflight checks for the desktop supervisor"

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output as JSON",
        )

    def handle(self, *args, **options):
        # 1. DB Path
        db_path = settings.DATABASES["default"]["NAME"]

        # 2. SQLite integrity
        integrity_ok = False
        integrity_error = None
        if settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
            try:
                connection = connections[DEFAULT_DB_ALIAS]
                # Ensure connection is established
                if connection.connection is None:
                    connection.connect()
                
                with connection.cursor() as cursor:
                    cursor.execute("PRAGMA quick_check")
                    result = cursor.fetchone()
                    if result and result[0] == "ok":
                        integrity_ok = True
                    else:
                        integrity_error = str(result)
            except Exception as e:
                # If file doesn't exist yet, it's technically OK (it will be created)
                if "unable to open database file" in str(e).lower() or "no such table" in str(e).lower():
                    integrity_ok = True
                else:
                    integrity_error = str(e)
        else:
            integrity_ok = True  # Not SQLite

        # 3. Migrations state
        # We only check migrations if the DB is ok.
        needs_migration = False
        unapplied_count = 0
        if integrity_ok:
            try:
                connection = connections[DEFAULT_DB_ALIAS]
                connection.prepare_database()
                executor = MigrationExecutor(connection)
                targets = executor.loader.graph.leaf_nodes()
                unapplied_migrations = executor.migration_plan(targets)
                needs_migration = len(unapplied_migrations) > 0
                unapplied_count = len(unapplied_migrations)
            except Exception:
                # Usually means tables don't exist yet, which means needs migration
                needs_migration = True
                unapplied_count = -1

        data = {
            "db_path": str(db_path),
            "integrity_ok": integrity_ok,
            "integrity_error": integrity_error,
            "needs_migration": needs_migration,
            "unapplied_count": unapplied_count,
        }

        if options["json"]:
            self.stdout.write(json.dumps(data))
        else:
            for k, v in data.items():
                self.stdout.write(f"{k}: {v}")

        if not integrity_ok:
            sys.exit(1)
