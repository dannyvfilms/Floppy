import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from decouple import UndefinedValueError
from django.test import SimpleTestCase

from config import settings
from config.settings import secret


class SecretFileTests(SimpleTestCase):
    def test_reads_the_configured_absolute_path_without_scanning_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            secret_dir = Path(temp_dir)
            secret_path = secret_dir / "tmdb_api_key"
            secret_path.write_text("tmdb-from-docker\n")
            (secret_dir / "unrelated_mount").mkdir()

            with patch.dict(
                os.environ,
                {"TMDB_API_FILE": str(secret_path)},
                clear=False,
            ):
                self.assertEqual(secret("TMDB_API_FILE"), "tmdb-from-docker")

    def test_reads_a_secret_name_from_the_docker_secrets_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            secret_path = Path(temp_dir) / "track_secret_key"
            secret_path.write_text("secret-from-docker\n")

            with (
                patch.object(settings, "DOCKER_SECRETS_DIR", Path(temp_dir)),
                patch.dict(
                    os.environ,
                    {"SECRET_FILE": "track_secret_key"},
                    clear=False,
                ),
            ):
                self.assertEqual(secret("SECRET_FILE"), "secret-from-docker")

    def test_missing_secret_file_reports_the_config_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir) / "missing_secret"
            with patch.dict(
                os.environ,
                {"MISSING_SECRET_FILE": str(missing_path)},
                clear=False,
            ):
                with self.assertRaisesRegex(
                    UndefinedValueError,
                    "File from MISSING_SECRET_FILE not found",
                ):
                    secret("MISSING_SECRET_FILE")
