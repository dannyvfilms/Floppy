import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase, skipIf

import sys

class WritablePathsTest(TestCase):
    """Test that the application can start and migrate with a read-only source directory."""

    @skipIf(os.name == "nt", "chmod a-w behavior differs on Windows")
    def test_readonly_source_with_xdg_paths(self):
        # We need the absolute path to the real src directory
        real_src_dir = Path(__file__).resolve().parent.parent.parent.parent
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            tmp_src = tmp_path / "src"
            tmp_data = tmp_path / "data"
            tmp_logs = tmp_path / "state" / "logs"

            # Copy src
            shutil.copytree(real_src_dir, tmp_src, ignore=shutil.ignore_patterns('db', 'logs', 'staticfiles', '__pycache__', '*.pyc'))
            
            # Create writable directories
            tmp_data.mkdir(parents=True)
            tmp_logs.mkdir(parents=True)

            # Make src read-only
            # In Python, we can use subprocess to run chmod
            subprocess.run(["chmod", "-R", "a-w", str(tmp_src)], check=True)

            # Environment for the subprocess
            env = os.environ.copy()
            env["SECRET"] = "desktop-test-secret"
            env["FLOPPY_DATA_DIR"] = str(tmp_data)
            env["FLOPPY_DB_PATH"] = str(tmp_data / "db.sqlite3")
            env["LOG_DIR"] = str(tmp_logs)
            
            # Run checks
            try:
                subprocess.run(
                    [sys.executable, "manage.py", "check"],
                    cwd=str(tmp_src),
                    env=env,
                    check=True,
                    capture_output=True,
                    text=True
                )
                
                subprocess.run(
                    [sys.executable, "manage.py", "migrate", "--noinput"],
                    cwd=str(tmp_src),
                    env=env,
                    check=True,
                    capture_output=True,
                    text=True
                )
            finally:
                # Restore permissions so TemporaryDirectory can clean up
                subprocess.run(["chmod", "-R", "u+w", str(tmp_src)], check=True)

            # Assert database was created in the expected location
            self.assertTrue((tmp_data / "db.sqlite3").exists())
            
            # Assert nothing was written to the source tree
            self.assertFalse((tmp_src / "db").exists())
            self.assertFalse((tmp_src / "db" / "db.sqlite3").exists())
