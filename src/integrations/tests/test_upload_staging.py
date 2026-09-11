import os
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from integrations.tasks._import_helpers import _run_file_import
from integrations.upload_staging import (
    STALE_UPLOAD_AGE_SECONDS,
    _validate_staged_path,
    build_staged_zip,
    discard_staged_upload,
    enqueue_staged_task,
    open_import_file,
    prune_staged_uploads,
    stage_uploaded_file,
    staging_directory,
)


class ChunkedUpload:
    """Small UploadedFile stand-in that exposes Django's chunked contract."""

    name = "backup.csv"

    def __init__(self, chunks):
        """Store the chunks that should be yielded by the upload."""
        self._chunks = chunks
        self.chunk_sizes = []

    def chunks(self, chunk_size):
        self.chunk_sizes.append(chunk_size)
        yield from self._chunks


class UploadStagingTests(SimpleTestCase):
    """Filesystem staging keeps large task payloads out of the broker."""

    def setUp(self):
        self.data_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.data_dir.cleanup)
        self.settings = override_settings(FLOPPY_DATA_DIR=self.data_dir.name)
        self.settings.enable()
        self.addCleanup(self.settings.disable)

    def test_stage_writes_chunks_and_preserves_extension(self):
        upload = ChunkedUpload([b"first", b"second"])

        staged = stage_uploaded_file(upload)

        self.addCleanup(discard_staged_upload, staged)
        self.assertEqual(staged.read_bytes(), b"firstsecond")
        self.assertTrue(staged.name.endswith(".csv"))
        self.assertTrue(upload.chunk_sizes)

    def test_task_payload_is_deleted_after_success_and_failure(self):
        successful = stage_uploaded_file(ChunkedUpload([b"ok"]))
        with open_import_file(str(successful)) as file:
            self.assertEqual(file.read(), b"ok")
        self.assertFalse(successful.exists())

        failed = stage_uploaded_file(ChunkedUpload([b"failed"]))
        with self.assertRaises(RuntimeError), open_import_file(str(failed)) as file:
            file.read()
            raise RuntimeError("import failed")
        self.assertFalse(failed.exists())

    def test_file_import_task_wrapper_cleans_staged_path(self):
        staged = stage_uploaded_file(ChunkedUpload([b"task payload"]))

        with self.subTest(result="success"):
            with patch(
                "integrations.tasks._media_imports.import_media",
                return_value="done",
            ) as import_media:
                result = _run_file_import(object(), str(staged), 1, "new")

            self.assertEqual(result, "done")
            import_media.assert_called_once()
            self.assertFalse(staged.exists())

        failed = stage_uploaded_file(ChunkedUpload([b"task failure"]))
        with (
            patch(
                "integrations.tasks._media_imports.import_media",
                side_effect=RuntimeError("import failed"),
            ),
            self.assertRaises(RuntimeError),
        ):
            _run_file_import(object(), str(failed), 1, "new")
        self.assertFalse(failed.exists())

    def test_failed_queue_deletes_staged_payload(self):
        staged = stage_uploaded_file(ChunkedUpload([b"queued"]))

        class FailedTask:
            @staticmethod
            def delay(*_args, **_kwargs):
                raise RuntimeError("broker unavailable")

        with self.assertRaises(RuntimeError):
            enqueue_staged_task(
                FailedTask,
                file=str(staged),
                staged_paths=(str(staged),),
            )
        self.assertFalse(staged.exists())

    def test_stale_files_are_pruned_but_current_files_remain(self):
        directory = staging_directory()
        stale = directory / ".upload-stale.csv"
        stale.write_bytes(b"stale")
        current = directory / ".upload-current.csv"
        current.write_bytes(b"current")
        now = 1_000_000
        os.utime(stale, (now - STALE_UPLOAD_AGE_SECONDS - 1,) * 2)
        os.utime(current, (now,) * 2)

        self.assertEqual(prune_staged_uploads(now=now), 1)
        self.assertFalse(stale.exists())
        self.assertTrue(current.exists())

    def test_paths_outside_staging_directory_are_rejected(self):
        descriptor, outside_path = tempfile.mkstemp(
            prefix="not-staged-",
            suffix=".csv",
            dir=self.data_dir.name,
        )
        os.close(descriptor)
        outside = Path(outside_path)
        self.addCleanup(outside.unlink)

        with self.assertRaises(ValueError):
            _validate_staged_path(outside)
        discard_staged_upload(outside)
        self.assertTrue(outside.exists())

    def test_legacy_bytes_and_file_like_payloads_remain_supported(self):
        with open_import_file(b"legacy bytes") as file:
            self.assertEqual(file.read(), b"legacy bytes")

        source = self.enterContext(tempfile.SpooledTemporaryFile())
        source.write(b"legacy file")
        with open_import_file(source) as file:
            self.assertEqual(file.read(), b"legacy file")

    def test_zip_is_built_on_disk_from_staged_files(self):
        first = stage_uploaded_file(ChunkedUpload([b"one"]))
        second = stage_uploaded_file(ChunkedUpload([b"two"]))
        archive = build_staged_zip(
            [("nested/one.json", first), ("two.json", second)],
        )
        self.addCleanup(discard_staged_upload, archive)
        self.addCleanup(discard_staged_upload, first)
        self.addCleanup(discard_staged_upload, second)

        with zipfile.ZipFile(archive) as zip_file:
            self.assertEqual(zip_file.read("one.json"), b"one")
            self.assertEqual(zip_file.read("two.json"), b"two")

    def test_nginx_templates_have_the_bounded_large_upload_limit(self):
        repository_root = Path(__file__).resolve().parents[3]
        template_paths = (
            repository_root / "nginx.conf",
            repository_root / "scripts/install/templates/nginx.install.conf.tmpl",
        )

        for template_path in template_paths:
            template = template_path.read_text(encoding="utf-8")
            self.assertIn("client_max_body_size 512M;", template)
            self.assertNotIn("client_max_body_size 50M;", template)
