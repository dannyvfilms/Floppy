"""Exercise the published install line without downloading or installing anything.

The opening quote is escaped in Unix shells but closes in PowerShell, whose
comment then hides the Unix branch. Test the actual published text: changing
its quotes or wrapping it across lines can change which commands execute.
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMAND = re.search(
    r"```text\n([^\n]+)\n```", (ROOT / "docs/install.md").read_text()
).group(1)
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


class InstallCommandTests(unittest.TestCase):
    def test_readme_uses_the_same_command(self):
        self.assertIn(COMMAND, (ROOT / "README.md").read_text())

    @unittest.skipIf(os.name == "nt", "Unix shell dispatch")
    def test_unix_dispatch_input_failure_status_and_cleanup(self):
        for name in ("bash", "zsh", "sh"):
            shell = shutil.which(name)
            if not shell:
                continue
            for download_status, install_status in ((0, 0), (22, 0), (0, 7)):
                with self.subTest(
                    shell=name, download=download_status, install=install_status
                ):
                    with tempfile.TemporaryDirectory(
                        prefix="floppy install "
                    ) as directory:
                        root = Path(directory)
                        scratch = root / "temporary files"
                        scratch.mkdir()
                        curl = root / "curl"
                        curl.write_text(
                            "#!/bin/sh\n"
                            'if [ "$DOWNLOAD_STATUS" != 0 ]; then exit "$DOWNLOAD_STATUS"; fi\n'
                            'while [ "$1" != -o ]; do shift; done\n'
                            "cat > \"$2\" <<'INSTALLER'\n"
                            "#!/bin/bash\n"
                            "IFS= read -r answer\n"
                            'printf "UNIX:%s\\n" "$answer"\n'
                            'exit "$INSTALL_STATUS"\n'
                            "INSTALLER\n"
                        )
                        curl.chmod(0o755)
                        # Execute the repository's documented command with a mocked downloader.
                        result = subprocess.run(  # noqa: S603
                            [shell, "-c", COMMAND],
                            input="interactive answer\n",
                            capture_output=True,
                            text=True,
                            timeout=30,
                            check=False,
                            env=dict(
                                os.environ,
                                PATH=str(root) + os.pathsep + os.environ["PATH"],
                                TMPDIR=str(scratch),
                                DOWNLOAD_STATUS=str(download_status),
                                INSTALL_STATUS=str(install_status),
                            ),
                        )
                        self.assertEqual(
                            result.returncode,
                            download_status or install_status,
                            result.stderr,
                        )
                        self.assertEqual(
                            result.stdout,
                            "" if download_status else "UNIX:interactive answer\n",
                        )
                        self.assertEqual(result.stderr, "")
                        self.assertEqual(list(scratch.iterdir()), [])

    @unittest.skipUnless(POWERSHELL, "PowerShell runtime unavailable")
    def test_powershell_selects_only_its_installer_and_stops_on_download_failure(self):
        for fail in (False, True):
            with self.subTest(download_failure=fail):
                download = (
                    "throw 'Download failed'"
                    if fail
                    else "'Write-Output WINDOWS_DISPATCH_OK'"
                )
                harness = (
                    "$ErrorActionPreference = 'Stop'\n"
                    "function Invoke-RestMethod { [CmdletBinding()] param([string]$Uri)\n"
                    "if ($Uri -ne 'https://raw.githubusercontent.com/dannyvfilms/Floppy/latest/scripts/install.ps1') "
                    "{ throw 'Wrong installer endpoint' }\n" + download + "\n}\n"
                    "function bash { throw 'Unix branch ran in PowerShell' }\n"
                    + COMMAND
                )
                # Downloads are mocked above; no installer or network access runs.
                result = subprocess.run(  # noqa: S603
                    [POWERSHELL, "-NoLogo", "-NoProfile", "-Command", harness],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                if fail:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn("WINDOWS_DISPATCH_OK", result.stdout)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), "WINDOWS_DISPATCH_OK")
                    self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
