import concurrent.futures
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.contrib.staticfiles.finders import AppDirectoriesFinder, FileSystemFinder
from django.test import SimpleTestCase

from config import static_collection


class CustomFinder(FileSystemFinder):
    pass


class StaticCollectionTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = self.root / "source"
        self.output = self.root / "collected"
        self.record = self.root / "collection.json"
        self.settings_file = self.root / "config/settings.py"
        self.settings_file.parent.mkdir()
        self.settings_file.write_text("# fixture settings\n")
        self.source.mkdir()
        self.output.mkdir()
        (self.source / "example.css").write_text("body { color: red; }\n")
        shutil.copy2(self.source / "example.css", self.output / "example.css")
        self.enterContext(
            self.settings(STATIC_ROOT=str(self.output), STATICFILES_DIRS=[self.source]),
        )
        self.enterContext(
            mock.patch.multiple(
                static_collection,
                _RECORD=self.record,
                _STATIC_ROOT=self.output,
                _SETTINGS=self.settings_file,
                _OWNER=(os.getuid(), os.getgid()),
            ),
        )
        self.enterContext(
            mock.patch.dict(
                os.environ,
                {
                    "DEBUG": "false",
                    "ENABLE_DEBUG_TOOLBAR": "true",
                    "SOCIAL_PROVIDERS": "",
                    "FLOPPY_PROCESS_ROLE": "",
                    "DJANGO_SETTINGS_MODULE": "config.settings",
                },
            ),
        )
        self.write_record()

    def write_record(self, finders=None):
        with mock.patch(
            "django.contrib.staticfiles.finders.get_finders",
            return_value=finders or [FileSystemFinder()],
        ):
            return static_collection.record_collection()

    def test_current_image_can_be_checked_without_importing_django(self):
        code = (
            "import os,sys,importlib.util; from pathlib import Path; "
            f"spec=importlib.util.spec_from_file_location('static_fixture', {static_collection.__file__!r}); "
            "c=importlib.util.module_from_spec(spec); spec.loader.exec_module(c); "
            f"c._RECORD=Path({str(self.record)!r}); "
            f"c._STATIC_ROOT=Path({str(self.output)!r}); "
            f"c._SETTINGS=Path({str(self.settings_file)!r}); "
            "c._OWNER=(os.getuid(),os.getgid()); "
            "assert c.collection_is_current(); assert 'django' not in sys.modules"
        )
        result = subprocess.run(  # noqa: S603 - test-controlled code
            [sys.executable, "-c", code],
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_source_addition_change_or_removal_requires_collection(self):
        source = self.source / "example.css"
        original = source.read_bytes()
        for action in ("add", "change", "remove"):
            with self.subTest(action=action):
                source.write_bytes(original)
                (self.source / "new.css").unlink(missing_ok=True)
                self.assertTrue(self.write_record())
                if action == "add":
                    (self.source / "new.css").write_text("new")
                elif action == "change":
                    source.write_text("changed and longer")
                else:
                    source.unlink()
                self.assertFalse(static_collection.collection_is_current())

    def test_missing_or_altered_output_requires_collection(self):
        path = self.output / "example.css"
        path.write_text("damaged and longer")
        self.assertFalse(static_collection.collection_is_current())
        path.unlink()
        self.assertFalse(static_collection.collection_is_current())

    def test_new_app_static_directory_invalidates_record(self):
        app = SimpleNamespace(path=str(self.root / "fixture_app"), name="fixture")
        with mock.patch("django.apps.apps.get_app_configs", return_value=[app]):
            self.assertTrue(
                self.write_record([FileSystemFinder(), AppDirectoriesFinder()])
            )
        self.assertTrue(static_collection.collection_is_current())
        folder = Path(app.path) / "static"
        folder.mkdir(parents=True)
        (folder / "added.js").write_text("new")
        self.assertFalse(static_collection.collection_is_current())

    def test_debug_provider_role_or_settings_module_change_requires_collection(self):
        for env in (
            {"DEBUG": "True"},
            {"SOCIAL_PROVIDERS": "allauth.socialaccount.providers.google"},
            {"FLOPPY_PROCESS_ROLE": "background"},
            {"DJANGO_SETTINGS_MODULE": "custom.settings"},
            {"DEBUG": "not-a-boolean"},
        ):
            with self.subTest(env=env), mock.patch.dict(os.environ, env):
                self.assertFalse(static_collection.collection_is_current())

    def test_dotenv_debug_configuration_is_honored(self):
        (self.settings_file.parent / ".env").write_text("DEBUG=true\n")
        with mock.patch.dict(os.environ):
            os.environ.pop("DEBUG")
            self.assertFalse(static_collection.collection_is_current())

    def test_changed_settings_code_requires_collection(self):
        self.settings_file.write_text("# different static settings\n")
        self.assertFalse(static_collection.collection_is_current())

    def test_changed_ownership_or_permissions_requires_repair(self):
        with mock.patch.object(static_collection, "_OWNER", (-1, -1)):
            self.assertFalse(static_collection.collection_is_current())
        path = self.output / "example.css"
        path.chmod((path.stat().st_mode & 0o777) ^ 0o040)
        self.assertFalse(static_collection.collection_is_current())

    def test_symlink_requires_normal_collection(self):
        path = self.output / "example.css"
        path.unlink()
        path.symlink_to(self.source / "example.css")
        self.assertFalse(static_collection.collection_is_current())
        self.assertFalse(self.write_record())
        self.assertFalse(self.record.exists())

    def test_bad_or_incomplete_record_falls_back_and_can_be_retried(self):
        original = self.record.read_text()
        for invalid in ("{", "[]", "{}", '{"version": 2}'):
            with self.subTest(invalid=invalid):
                self.record.write_text(invalid)
                self.assertFalse(static_collection.collection_is_current())
                self.record.write_text(original)
                self.assertTrue(static_collection.collection_is_current())
        self.record.unlink()
        self.assertFalse(static_collection.collection_is_current())

    def test_unreadable_record_falls_back(self):
        with mock.patch.object(
            Path, "read_text", side_effect=PermissionError("denied")
        ):
            self.assertFalse(static_collection.collection_is_current())

    def test_custom_finder_or_postprocessing_storage_is_not_cached(self):
        self.assertFalse(self.write_record([CustomFinder()]))
        self.assertFalse(self.record.exists())
        with self.settings(
            STORAGES={
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                "staticfiles": {
                    "BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage",
                },
            },
        ):
            self.assertFalse(self.write_record())
        self.assertFalse(self.record.exists())

    def test_concurrent_checks_leave_the_record_unchanged(self):
        original = self.record.read_bytes()
        modified = self.record.stat().st_mtime_ns
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(
                pool.map(lambda _: static_collection.collection_is_current(), range(8))
            )
        self.assertEqual(results, [True] * 8)
        self.assertEqual(self.record.read_bytes(), original)
        self.assertEqual(self.record.stat().st_mtime_ns, modified)
