import subprocess
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[3]
ENTRYPOINT = ROOT / "entrypoint.sh"
BOOTSTRAP_END = "\nreject_unsafe_managed_directory() {"


class ContainerEntrypointPathTests(SimpleTestCase):
    def run_bootstrap(self, *, path, virtual_env):
        source = ENTRYPOINT.read_text(encoding="utf-8")
        bootstrap, separator, _rest = source.partition(BOOTSTRAP_END)
        self.assertEqual(separator, BOOTSTRAP_END)

        with tempfile.TemporaryDirectory() as temp_dir:
            script = Path(temp_dir) / "entrypoint-bootstrap.sh"
            script.write_text(
                f'{bootstrap}\nprintf "%s\\n" "$PATH"\ncommand -v python\n',
                encoding="utf-8",
            )
            script.chmod(0o755)
            result = subprocess.run(  # noqa: S603 - test-controlled script
                [str(script)],
                env={"PATH": path, "VIRTUAL_ENV": str(virtual_env)},
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.splitlines()

    @staticmethod
    def write_executable(path):
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)

    def test_virtualenv_moves_to_front_when_it_is_already_later_in_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            system_bin = root / "system-bin"
            virtual_env_bin = root / "virtual-env" / "bin"
            system_bin.mkdir()
            virtual_env_bin.mkdir(parents=True)
            self.write_executable(system_bin / "python")
            self.write_executable(virtual_env_bin / "python")

            path, resolved_python = self.run_bootstrap(
                path=f"{system_bin}:{virtual_env_bin}:/usr/bin:/bin",
                virtual_env=virtual_env_bin.parent,
            )

            self.assertEqual(Path(path.split(":", 1)[0]), virtual_env_bin)
            self.assertEqual(Path(resolved_python), virtual_env_bin / "python")

    def test_virtualenv_is_not_duplicated_when_it_is_already_first(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            system_bin = root / "system-bin"
            virtual_env_bin = root / "virtual-env" / "bin"
            system_bin.mkdir()
            virtual_env_bin.mkdir(parents=True)
            self.write_executable(system_bin / "python")
            self.write_executable(virtual_env_bin / "python")
            original_path = f"{virtual_env_bin}:{system_bin}:/usr/bin:/bin"

            path, resolved_python = self.run_bootstrap(
                path=original_path,
                virtual_env=virtual_env_bin.parent,
            )

            self.assertEqual(path, original_path)
            self.assertEqual(Path(resolved_python), virtual_env_bin / "python")

    def test_virtualenv_prepended_when_absent_from_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            system_bin = root / "system-bin"
            virtual_env_bin = root / "virtual-env" / "bin"
            system_bin.mkdir()
            virtual_env_bin.mkdir(parents=True)
            self.write_executable(virtual_env_bin / "python")
            original_path = f"{system_bin}:/usr/bin:/bin"

            path, resolved_python = self.run_bootstrap(
                path=original_path,
                virtual_env=virtual_env_bin.parent,
            )

            self.assertEqual(path, f"{virtual_env_bin}:{original_path}")
            self.assertEqual(Path(resolved_python), virtual_env_bin / "python")

    def test_empty_path_prepends_virtualenv_cleanly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            virtual_env_bin = root / "virtual-env" / "bin"
            virtual_env_bin.mkdir(parents=True)
            self.write_executable(virtual_env_bin / "python")

            path, resolved_python = self.run_bootstrap(
                path="",
                virtual_env=virtual_env_bin.parent,
            )

            self.assertEqual(path, str(virtual_env_bin))
            self.assertEqual(Path(resolved_python), virtual_env_bin / "python")

