import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config import settings as project_settings

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
ENTRYPOINT = ROOT / "entrypoint.sh"

SETTINGS_PROBE = """
import json
from config import settings

print(json.dumps({
    "data_dir": str(settings.FLOPPY_DATA_DIR),
    "database_name": str(settings.DATABASES["default"]["NAME"]),
    "database_engine": settings.DATABASES["default"]["ENGINE"],
}))
"""

DOCKER_SECRET_PROBE = """
from pathlib import Path
from unittest.mock import patch

real_exists = Path.exists

def exists(path):
    if path == Path("/.dockerenv"):
        return True
    return real_exists(path)

with patch.object(Path, "exists", exists):
    from config import settings
    print(settings.SECRET_KEY)
"""


class DataPathSettingsTests(SimpleTestCase):
    def run_settings(self, *, cwd, python_path=SRC, **overrides):
        environment = {
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(python_path),
            "PYTHONDONTWRITEBYTECODE": "1",
            "SECRET": "data-path-test-secret",
            "LOG_DIR": str(Path(cwd) / "logs"),
        }
        environment.update(overrides)
        result = subprocess.run(  # noqa: S603 - test-controlled executable
            [sys.executable, "-c", SETTINGS_PROBE],
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_defaults_and_empty_overrides_use_the_existing_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            for overrides in ({}, {"FLOPPY_DATA_DIR": "", "FLOPPY_DB_PATH": ""}):
                with self.subTest(overrides=overrides):
                    settings = self.run_settings(cwd=temp_dir, **overrides)

                self.assertEqual(settings["data_dir"], str(SRC / "db"))
                self.assertEqual(settings["database_name"], str(SRC / "db/db.sqlite3"))

    def test_data_directory_and_database_file_have_independent_overrides(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            external_database = root / "database" / "floppy.sqlite3"

            data_settings = self.run_settings(
                cwd=root,
                FLOPPY_DATA_DIR=str(data_dir),
            )
            database_settings = self.run_settings(
                cwd=root,
                FLOPPY_DATA_DIR=str(data_dir),
                FLOPPY_DB_PATH=str(external_database),
            )

            self.assertEqual(data_settings["data_dir"], str(data_dir))
            self.assertEqual(
                data_settings["database_name"],
                str(data_dir / "db.sqlite3"),
            )
            self.assertEqual(database_settings["data_dir"], str(data_dir))
            self.assertEqual(
                database_settings["database_name"],
                str(external_database),
            )
            self.assertTrue(external_database.parent.is_dir())

    def test_read_only_source_uses_external_writable_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            read_only_source = root / "source"
            shutil.copytree(SRC / "config", read_only_source / "config")
            read_only_directories = [
                read_only_source,
                *(path for path in read_only_source.rglob("*") if path.is_dir()),
            ]
            for path in read_only_source.rglob("*"):
                path.chmod(0o555 if path.is_dir() else 0o444)
            read_only_source.chmod(0o555)
            data_dir = root / "data"
            database_path = root / "database" / "db.sqlite3"
            log_dir = root / "logs"
            try:
                settings = self.run_settings(
                    cwd=root,
                    python_path=read_only_source,
                    FLOPPY_DATA_DIR=str(data_dir),
                    FLOPPY_DB_PATH=str(database_path),
                    LOG_DIR=str(log_dir),
                )
            finally:
                for directory in read_only_directories:
                    directory.chmod(0o755)

            self.assertEqual(settings["database_name"], str(database_path))
            self.assertTrue(database_path.parent.is_dir())
            self.assertTrue(log_dir.is_dir())
            self.assertFalse((read_only_source / "db").exists())

    def test_postgresql_does_not_touch_sqlite_override_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            protected = root / "protected"
            protected.mkdir()
            protected.chmod(0o555)
            data_dir = protected / "data"
            database_path = protected / "database" / "db.sqlite3"
            try:
                settings = self.run_settings(
                    cwd=root,
                    FLOPPY_DATA_DIR=str(data_dir),
                    FLOPPY_DB_PATH=str(database_path),
                    DB_HOST="postgres",
                    DB_NAME="floppy",
                    DB_USER="floppy",
                    DB_PASSWORD="password",
                    DB_PORT="5432",
                )
            finally:
                protected.chmod(0o755)

            self.assertEqual(
                settings["database_engine"],
                "django.db.backends.postgresql",
            )
            self.assertFalse(data_dir.exists())
            self.assertFalse(database_path.parent.exists())

    def test_generated_secret_is_created_and_corrected_to_mode_0600(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            secret_path = Path(temp_dir) / "data" / "secret_key"

            value, created = project_settings._load_or_create_docker_secret(
                secret_path,
            )
            self.assertTrue(created)
            self.assertEqual(secret_path.read_text(encoding="utf-8"), value)
            self.assertEqual(stat.S_IMODE(secret_path.stat().st_mode), 0o600)

            secret_path.chmod(0o644)
            same_value, created = project_settings._load_or_create_docker_secret(
                secret_path,
            )
            self.assertFalse(created)
            self.assertEqual(same_value, value)
            self.assertEqual(stat.S_IMODE(secret_path.stat().st_mode), 0o600)

    def test_generated_secret_uses_the_configured_data_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "configured data"
            environment = {
                "PATH": os.environ["PATH"],
                "PYTHONPATH": str(SRC),
                "PYTHONDONTWRITEBYTECODE": "1",
                "FLOPPY_DATA_DIR": str(data_dir),
                "LOG_DIR": str(root / "logs"),
            }

            result = subprocess.run(  # noqa: S603 - test-controlled executable
                [sys.executable, "-c", DOCKER_SECRET_PROBE],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            secret_path = data_dir / "secret_key"
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip().splitlines()[-1],
                secret_path.read_text(encoding="utf-8"),
            )
            self.assertEqual(stat.S_IMODE(secret_path.stat().st_mode), 0o600)

    def test_generated_secret_failure_names_the_path_and_next_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            blocked_parent = Path(temp_dir) / "not-a-directory"
            blocked_parent.write_text("keep", encoding="utf-8")
            secret_path = blocked_parent / "secret_key"

            with self.assertRaisesRegex(
                ImproperlyConfigured,
                rf"{secret_path}.*Make FLOPPY_DATA_DIR writable or set SECRET",
            ):
                project_settings._load_or_create_docker_secret(secret_path)

            self.assertEqual(blocked_parent.read_text(encoding="utf-8"), "keep")

    def test_generated_secret_rejects_symlink_without_touching_its_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "operator-secret"
            target.write_text("do-not-read", encoding="utf-8")
            target.chmod(0o644)
            secret_path = root / "data" / "secret_key"
            secret_path.parent.mkdir()
            secret_path.symlink_to(target)

            with self.assertRaisesRegex(ImproperlyConfigured, rf"{secret_path}"):
                project_settings._load_or_create_docker_secret(secret_path)

            self.assertEqual(target.read_text(encoding="utf-8"), "do-not-read")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)

    def test_generated_secret_rejects_non_regular_and_empty_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name, create in (
                ("directory", lambda path: path.mkdir()),
                ("empty", lambda path: path.touch()),
            ):
                with self.subTest(name=name):
                    secret_path = root / name
                    create(secret_path)
                    with self.assertRaisesRegex(
                        ImproperlyConfigured,
                        rf"{secret_path}",
                    ):
                        project_settings._load_or_create_docker_secret(secret_path)

    def test_generated_secret_is_published_complete_under_concurrency(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            secret_path = Path(temp_dir) / "data" / "secret_key"
            barrier = threading.Barrier(2)
            real_link = os.link

            def synchronized_link(*args, **kwargs):
                barrier.wait(timeout=5)
                return real_link(*args, **kwargs)

            with (
                mock.patch.object(
                    project_settings.os,
                    "link",
                    side_effect=synchronized_link,
                ),
                ThreadPoolExecutor(max_workers=2) as executor,
            ):
                results = list(
                    executor.map(
                        project_settings._load_or_create_docker_secret,
                        (secret_path, secret_path),
                    )
                )

            values = {value for value, _created in results}
            self.assertEqual(len(values), 1)
            self.assertNotEqual(values, {""})
            self.assertEqual(
                sorted(created for _value, created in results), [False, True]
            )
            self.assertEqual(secret_path.read_text(encoding="utf-8"), values.pop())


class EntrypointDataPathTests(SimpleTestCase):
    def run_entrypoint(self, root, **overrides):
        fake_bin = root / "bin"
        fake_bin.mkdir(exist_ok=True)
        log_path = root / "commands.log"
        log_path.unlink(missing_ok=True)
        script_path = root / "entrypoint.sh"
        script_path.write_text(
            ENTRYPOINT.read_text(encoding="utf-8").replace(
                "exec /usr/local/bin/supervisord -c /etc/supervisord.conf",
                "exec supervisord -c /etc/supervisord.conf",
            ),
            encoding="utf-8",
        )
        script_path.chmod(0o755)

        self.write_command(
            fake_bin / "python",
            f"""#!/bin/sh
if [ "$1" = "-c" ]; then
    exec {sys.executable} "$@"
fi
{{ printf 'python'; printf ' <%s>' "$@"; printf '\n'; }} >> "$FAKE_LOG"
exit 0
""",
        )
        self.write_command(
            fake_bin / "timeout",
            """#!/bin/sh
shift
exec "$@"
""",
        )
        self.write_command(
            fake_bin / "sleep",
            """#!/bin/sh
exec /bin/sleep 0.05
""",
        )
        self.write_command(
            fake_bin / "chown",
            """#!/bin/sh
{ printf 'chown'; printf ' <%s>' "$@"; printf '\n'; } >> "$FAKE_LOG"
last=""
for argument in "$@"; do last=$argument; done
if [ -n "$FAIL_CHOWN_PATH" ] && [ "$last" = "$FAIL_CHOWN_PATH" ]; then
    exit 1
fi
""",
        )
        for command in ("groupmod", "usermod", "supervisord"):
            self.write_command(
                fake_bin / command,
                f"""#!/bin/sh
{{ printf '{command}'; printf ' <%s>' "$@"; printf '\n'; }} >> "$FAKE_LOG"
""",
            )

        environment = {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "PYTHONPATH": str(SRC),
            "FAKE_LOG": str(log_path),
            "SECRET": "entrypoint-test-secret",
            "LOG_DIR": str(root / "logs"),
        }
        environment.update(overrides)
        result = subprocess.run(  # noqa: S603 - test-controlled script
            [str(script_path)],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        commands = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
        return result, commands

    @staticmethod
    def write_command(path, content):
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def test_paths_with_spaces_and_leading_dash_remain_single_arguments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "-managed data"
            database_parent = root / "external data"
            database_path = database_parent / "-db.sqlite3"
            data_dir.mkdir()
            database_parent.mkdir()
            database_path.touch()
            database_wal_path = Path(f"{database_path}-wal")
            database_wal_path.touch()
            database_shm_path = Path(f"{database_path}-shm")
            database_shm_path.touch()
            (database_parent / "unrelated").mkdir()
            secret_path = data_dir / "secret_key"
            secret_path.touch()
            log_dir = root / "logs"
            log_dir.mkdir()
            log_file = log_dir / "floppy.log"
            log_file.touch()
            (log_dir / "unrelated.log").touch()

            result, commands = self.run_entrypoint(
                root,
                FLOPPY_DATA_DIR="-managed data",
                FLOPPY_DB_PATH=str(database_path),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                f"Checking SQLite storage and relationships for {database_path}",
                result.stderr,
            )
            self.assertIn(f"chown <abc:abc> <--> <{data_dir}>", commands)
            self.assertIn(f"chown <-h> <abc:abc> <--> <{secret_path}>", commands)
            self.assertIn(f"chown <abc:abc> <--> <{database_parent}>", commands)
            self.assertIn(f"chown <-h> <abc:abc> <--> <{database_path}>", commands)
            self.assertIn(f"chown <-h> <abc:abc> <--> <{database_wal_path}>", commands)
            self.assertIn(f"chown <-h> <abc:abc> <--> <{database_shm_path}>", commands)
            self.assertIn(f"chown <abc:abc> <--> <{log_dir}>", commands)
            self.assertIn(f"chown <-h> <abc:abc> <--> <{log_file}>", commands)
            self.assertNotIn(f"chown <-R> <abc:abc> <--> <{data_dir}>", commands)
            self.assertNotIn(f"chown <-R> <abc:abc> <--> <{log_dir}>", commands)
            self.assertNotIn(str(database_parent / "unrelated"), commands)
            self.assertNotIn(str(log_dir / "unrelated.log"), commands)

    def test_system_root_and_symlink_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            root_link = root / "root-link"
            root_link.symlink_to("/")
            system_link = root / "system-link"
            system_link.symlink_to("/etc")
            safe_data = root / "data"
            safe_data.mkdir()

            cases = (
                ({"FLOPPY_DATA_DIR": "/"}, "FLOPPY_DATA_DIR"),
                ({"FLOPPY_DATA_DIR": str(root_link)}, "FLOPPY_DATA_DIR"),
                ({"FLOPPY_DATA_DIR": "/etc"}, "FLOPPY_DATA_DIR"),
                ({"LOG_DIR": "/"}, "LOG_DIR"),
                ({"LOG_DIR": str(root_link)}, "LOG_DIR"),
                ({"LOG_DIR": str(system_link)}, "LOG_DIR"),
                (
                    {
                        "FLOPPY_DATA_DIR": str(safe_data),
                        "FLOPPY_DB_PATH": "/db.sqlite3",
                    },
                    "FLOPPY_DB_PATH",
                ),
                (
                    {
                        "FLOPPY_DATA_DIR": str(safe_data),
                        "FLOPPY_DB_PATH": "/etc/db.sqlite3",
                    },
                    "FLOPPY_DB_PATH",
                ),
            )
            for environment, setting_name in cases:
                with self.subTest(environment=environment):
                    result, commands = self.run_entrypoint(root, **environment)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(setting_name, result.stderr)
                self.assertNotIn("supervisord", commands)

    def test_dedicated_directory_below_system_root_is_allowed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result, commands = self.run_entrypoint(
                Path(temp_dir),
                FLOPPY_DATA_DIR="/var/lib/floppy",
                FLOPPY_DB_PATH="/var/lib/floppy/db.sqlite3",
                LOG_DIR="/var/log/floppy",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("supervisord", commands)

    def test_external_database_parent_ownership_failure_stops_startup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            database_parent = root / "database"
            database_path = database_parent / "db.sqlite3"
            data_dir.mkdir()
            database_parent.mkdir()
            database_path.touch()

            result, commands = self.run_entrypoint(
                root,
                FLOPPY_DATA_DIR=str(data_dir),
                FLOPPY_DB_PATH=str(database_path),
                FAIL_CHOWN_PATH=str(database_parent),
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "Cannot set ownership for FLOPPY_DB_PATH parent", result.stderr
            )
            self.assertNotIn("supervisord", commands)

    def test_postgresql_does_not_resolve_or_own_the_sqlite_override(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            data_dir.mkdir()

            result, commands = self.run_entrypoint(
                root,
                DB_HOST="postgres",
                FLOPPY_DATA_DIR=str(data_dir),
                FLOPPY_DB_PATH="/db.sqlite3",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("FLOPPY_DB_PATH", result.stderr)
            self.assertNotIn("/db.sqlite3", commands)
