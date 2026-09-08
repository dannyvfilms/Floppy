"""Checks for the guided installer's shell helpers and generated files.

The installer cannot be exercised end to end from the test suite - it installs
packages and registers system services - but the parts that silently produce a
broken installation can be: the substitution that writes every generated file,
the state file that resumption reads back, and the shape of the configuration
handed to Compose, Supervisor, and Nginx.
"""

import configparser
import os
import pty
import re
import select
import subprocess
import tempfile
import time
from pathlib import Path

import yaml
from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[3]
INSTALL_DIR = ROOT / "scripts" / "install"
TEMPLATE_DIR = INSTALL_DIR / "templates"

SHELL_FILES = [
    ROOT / "scripts" / "install.sh",
    INSTALL_DIR / "common.sh",
    INSTALL_DIR / "main.sh",
    INSTALL_DIR / "docker.sh",
    INSTALL_DIR / "source_common.sh",
    INSTALL_DIR / "linux_source.sh",
    INSTALL_DIR / "macos_source.sh",
    INSTALL_DIR / "finish.sh",
]


def run_helper(body, root):
    """Run a snippet with the installer helpers loaded against a temp root."""
    script = (
        "set -euo pipefail\n"
        f'FLOPPY_ROOT="{root}"\n'
        f'. "{INSTALL_DIR / "common.sh"}"\n'
        f"{body}\n"
    )
    result = subprocess.run(  # noqa: S603 - test-controlled script
        ["bash", "-c", script],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        msg = f"helper failed: {result.stderr}"
        raise AssertionError(msg)
    return result.stdout


def run_over_pty(body, *, sends, timeout=5):
    """Run a snippet under a real pty and feed it keystrokes as it prompts.

    ask()/ask_choice()/ask_yes_no() read from /dev/tty specifically (see the
    comment above _tty_read in common.sh), so exercising them over a plain
    subprocess pipe takes the "no controlling tty" branch and always returns
    the default - it can look like a passing test while never touching the
    read path a real terminal session uses. `sends` is a list of byte strings
    written a beat apart, mimicking a person typing an answer per prompt.
    """
    script = (
        "set -euo pipefail\n"
        f'FLOPPY_ROOT="/tmp/floppy-installer-test-{os.getpid()}"\n'
        f'. "{INSTALL_DIR / "common.sh"}"\n'
        f"{body}\n"
    )
    script_path = Path(tempfile.mkstemp(suffix=".sh")[1])
    script_path.write_text(script, encoding="utf-8")

    pid, fd = pty.fork()
    if pid == 0:  # pragma: no cover - child process
        os.execvp("bash", ["bash", str(script_path)])  # noqa: S606, S607

    try:
        output = b""
        deadline = time.time() + timeout
        for chunk in sends:
            time.sleep(0.2)
            os.write(fd, chunk)
        while time.time() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.5)
            if not ready:
                continue
            try:
                read = os.read(fd, 4096)
            except OSError:
                break
            if not read:
                break
            output += read
        os.kill(pid, 9)
        os.waitpid(pid, 0)
    finally:
        script_path.unlink(missing_ok=True)
    return output.decode(errors="replace")


class PromptCaptureTests(SimpleTestCase):
    """Regression coverage for a variable-name collision that made every typed
    answer with no default (a username, most notably) silently disappear,
    and made every ask_choice() numeric selection fall back to the default
    no matter what was typed - see the fix in common.sh's _tty_read.
    """

    def test_ask_captures_a_typed_answer_with_no_default(self):
        output = run_over_pty(
            'ask NAME "Username" ""\necho "GOT:[$NAME]"\n',
            sends=[b"dannyvfilms\n"],
        )
        self.assertIn("GOT:[dannyvfilms]", output)

    def test_ask_choice_captures_a_typed_number(self):
        output = run_over_pty(
            'ask_choice PICK "Pick one" a "a|Alpha|" "b|Beta|"\n'
            'echo "GOT:[$PICK]"\n',
            sends=[b"2\n"],
        )
        self.assertIn("GOT:[b]", output)

    def test_ask_yes_no_captures_a_typed_no(self):
        output = run_over_pty(
            'if ask_yes_no "Continue?" yes; then echo GOT:[yes]; '
            "else echo GOT:[no]; fi\n",
            sends=[b"n\n"],
        )
        self.assertIn("GOT:[no]", output)


def extract_resume_update_commands():
    """Pull the exact fetch/merge invocation resuming an install runs.

    Extracted from the source rather than duplicated by hand, so a future
    edit to scripts/install.sh's resume-update step is exercised by the same
    text this test runs - not a copy that can silently drift from it.
    """
    text = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    start = text.index('step "Checking for installer updates"')
    marker = "\n    fi\n"
    end = text.index(marker, start) + len(marker)
    return text[start:end]


class BranchAndImageDefaultsTests(SimpleTestCase):
    """The cloned branch and the pulled image tag must name the same release.

    Regression coverage for a live failure: the checkout defaulted to
    "latest" (this file's own earlier TODO) while the image tag stayed
    "release", an older image that predates commands the installer runs
    (promote_superuser) and failed with "Unknown command". Whichever branch
    scripts/install/ currently ships from, common.sh's defaults must name it
    on both axes together.
    """

    def test_branch_and_image_tag_agree(self):
        text = (INSTALL_DIR / "common.sh").read_text(encoding="utf-8")
        branch = re.search(
            r"FLOPPY_REPO_BRANCH=\$\{FLOPPY_REPO_BRANCH:-(\w+)\}", text
        ).group(1)
        image_tag = re.search(
            r"FLOPPY_IMAGE=\$\{FLOPPY_IMAGE:-ghcr\.io/dannyvfilms/floppy:(\w+)\}",
            text,
        ).group(1)
        self.assertEqual(
            branch,
            image_tag,
            "the cloned branch and the pulled image tag must name the same "
            "release, or an installed instance can be missing commands the "
            "installer itself relies on",
        )


class ResumeUpdateTests(SimpleTestCase):
    """A resumed installation must pick up installer fixes on every run.

    Regression coverage for two bugs found from a live install: first, that
    resuming never updated the cloned checkout at all, so a fix pushed after
    someone's first run stayed invisible to them forever; second, once fixed
    with a second `--depth 1` fetch, that git refuses to fast-forward a
    shallow clone's second `--depth 1` fetch ("unrelated histories"), so the
    "fix" silently never applied either. Both were confirmed against a real
    git remote before landing the corrected unbounded fetch below.
    """

    def _make_remote_and_shallow_clone(self, root):
        remote = root / "remote"
        repo = root / "repo"
        subprocess.run(  # noqa: S603
            ["git", "init", "--quiet", "-b", "latest", str(remote)],  # noqa: S607
            check=True,
        )
        subprocess.run(  # noqa: S603
            ["git", "-C", str(remote), "config", "user.email", "t@t.com"],  # noqa: S607
            check=True,
        )
        subprocess.run(  # noqa: S603
            ["git", "-C", str(remote), "config", "user.name", "t"],  # noqa: S607
            check=True,
        )
        (remote / "f").write_text("v1", encoding="utf-8")
        subprocess.run(  # noqa: S603
            ["git", "-C", str(remote), "add", "f"],  # noqa: S607
            check=True,
        )
        subprocess.run(  # noqa: S603
            ["git", "-C", str(remote), "commit", "--quiet", "-m", "v1"],  # noqa: S607
            check=True,
        )
        subprocess.run(  # noqa: S603
            [  # noqa: S607
                "git",
                "clone",
                "--quiet",
                "--branch",
                "latest",
                "--depth",
                "1",
                "--single-branch",
                f"file://{remote}",
                str(repo),
            ],
            check=True,
        )
        return remote, repo

    def _advance_remote(self, remote, contents):
        (remote / "f").write_text(contents, encoding="utf-8")
        subprocess.run(["git", "-C", str(remote), "add", "f"], check=True)  # noqa: S603, S607
        subprocess.run(  # noqa: S603
            ["git", "-C", str(remote), "commit", "--quiet", "-m", contents],  # noqa: S607
            check=True,
        )

    def test_resuming_brings_a_stale_shallow_checkout_forward(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            remote, repo = self._make_remote_and_shallow_clone(root)
            self._advance_remote(remote, "v2")
            self._advance_remote(remote, "v3")

            snippet = extract_resume_update_commands()
            # step/say/warn are installer-wide helpers, irrelevant to what
            # this test checks; stub them so the extracted snippet runs
            # standalone.
            script = (
                'step() { :; }\nsay() { :; }\nwarn() { echo "WARN: $*"; }\n'
                f'REPO_DIR="{repo}"\nREPO_BRANCH="latest"\n{snippet}\n'
            )
            result = subprocess.run(  # noqa: S603
                ["bash", "-c", script],  # noqa: S607
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertNotIn("WARN:", result.stdout + result.stderr)
            self.assertEqual((repo / "f").read_text(encoding="utf-8"), "v3")

    def test_the_update_fetch_is_not_depth_limited(self):
        # A second --depth-1 fetch against an already-shallow clone gives git
        # no visible ancestry to the first, so it refuses to fast-forward
        # even on a clean, linear branch. This is a static trip-wire against
        # reintroducing that exact regression.
        snippet = extract_resume_update_commands()
        fetch_line = next(
            line
            for line in snippet.splitlines()
            if "git" in line and "fetch" in line and not line.lstrip().startswith("#")
        )
        self.assertNotIn("--depth", fetch_line)


class InstallerShellSyntaxTests(SimpleTestCase):
    def test_every_installer_file_parses(self):
        for path in SHELL_FILES:
            with self.subTest(script=path.name):
                self.assertTrue(path.exists(), f"{path} is missing")
                result = subprocess.run(  # noqa: S603 - test-controlled script
                    ["bash", "-n", str(path)],  # noqa: S607
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_bootstrap_is_executable(self):
        self.assertTrue(ROOT.joinpath("scripts", "install.sh").stat().st_mode & 0o111)


class RenderTemplateTests(SimpleTestCase):
    def test_placeholders_are_replaced_including_paths_with_spaces(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "My Floppy"
            root.mkdir()
            template = root / "t.tmpl"
            template.write_text("dir=@@DIR@@\nport=@@PORT@@\n", encoding="utf-8")
            output = root / "out"
            run_helper(
                f'render_template "{template}" "{output}" "DIR={root}" "PORT=8123"',
                root,
            )
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                f"dir={root}\nport=8123\n",
            )

    def test_unused_placeholder_is_left_alone_rather_than_emptied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            template = root / "t.tmpl"
            template.write_text("a=@@A@@ b=@@B@@\n", encoding="utf-8")
            output = root / "out"
            run_helper(f'render_template "{template}" "{output}" "A=1"', root)
            self.assertEqual(output.read_text(encoding="utf-8"), "a=1 b=@@B@@\n")


class InstallStateTests(SimpleTestCase):
    def test_values_survive_a_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "My Floppy"
            root.mkdir()
            output = run_helper(
                "state_set METHOD docker\n"
                f'state_set ROOT "{root}"\n'
                "state_set PORT 8123\n"
                "state_get METHOD\n"
                "state_get ROOT\n"
                "state_get PORT\n",
                root,
            )
            self.assertEqual(output.splitlines(), ["docker", str(root), "8123"])

    def test_rewriting_a_key_keeps_only_the_new_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = run_helper(
                "state_set PORT 8000\nstate_set PORT 9000\nstate_get PORT\n",
                root,
            )
            self.assertEqual(output.strip(), "9000")
            self.assertEqual(
                (root / "install.conf").read_text(encoding="utf-8").count("PORT="),
                1,
            )

    def test_state_file_is_not_world_readable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_helper("state_set METHOD docker", root)
            mode = (root / "install.conf").stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)


class PortHelperTests(SimpleTestCase):
    def test_a_listening_port_is_skipped(self):
        import socket

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            busy = sock.getsockname()[1]
            with tempfile.TemporaryDirectory() as temp_dir:
                chosen = run_helper(f"first_free_port {busy}", Path(temp_dir)).strip()
            self.assertNotEqual(chosen, str(busy))
            self.assertGreater(int(chosen), busy)


def run_docker_helper(body, root):
    """Like run_helper, but with docker.sh's functions loaded too."""
    return run_helper(f'. "{INSTALL_DIR / "docker.sh"}"\n{body}', root)


class ExistingComposeImageUpdateTests(SimpleTestCase):
    """A resumed install's Compose file must not stay pinned to a dead tag.

    Regression coverage for a live failure: the checkout and the image-tag
    *default* were fixed to track the same branch, but an already-generated
    docker-compose.yml keeps whatever tag it was written with forever - the
    "Keeping the existing docker-compose.yml" resume path never regenerates
    it, precisely so a hand customization (an extra volume, say) survives.
    That meant the default's fix never reached an installation that already
    existed: Settings > Metadata's own promote_superuser instructions failed
    with "Unknown command" because the container was still running the tag
    baked in on day one. _docker_update_image_tag brings forward only that
    one line.
    """

    def _compose_file(self, root, image):
        path = root / "docker-compose.yml"
        path.write_text(
            "name: floppy-test\n"
            "services:\n"
            "  floppy:\n"
            f"    image: {image}\n"
            "    restart: unless-stopped\n"
            "  redis:\n"
            "    image: redis:8-alpine\n",
            encoding="utf-8",
        )
        return path

    def test_resuming_an_existing_compose_file_calls_the_update(self):
        # The function working in isolation (below) proves nothing if
        # install_docker()'s "Keeping the existing docker-compose.yml" branch
        # never actually calls it - which is exactly how this regressed once
        # already: the helper existed and worked, the call site did not.
        text = (INSTALL_DIR / "docker.sh").read_text(encoding="utf-8")
        existing_branch = text[text.index('if [ -f "$COMPOSE_FILE" ]; then') :]
        keeping_to_else = existing_branch[: existing_branch.index("\n    else\n")]
        self.assertIn("_docker_update_image_tag", keeping_to_else)

    def test_an_old_tag_is_brought_forward(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            compose = self._compose_file(root, "ghcr.io/dannyvfilms/floppy:release")
            run_docker_helper(
                'FLOPPY_IMAGE="ghcr.io/dannyvfilms/floppy:latest"\n'
                "_docker_update_image_tag\n",
                root,
            )
            text = compose.read_text(encoding="utf-8")
        self.assertIn("image: ghcr.io/dannyvfilms/floppy:latest", text)
        self.assertIn("image: redis:8-alpine", text)

    def test_an_already_current_tag_is_left_alone(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            compose = self._compose_file(root, "ghcr.io/dannyvfilms/floppy:latest")
            before = compose.read_text(encoding="utf-8")
            run_docker_helper(
                'FLOPPY_IMAGE="ghcr.io/dannyvfilms/floppy:latest"\n'
                "_docker_update_image_tag\n",
                root,
            )
            after = compose.read_text(encoding="utf-8")
        self.assertEqual(before, after)

    def test_other_customization_in_the_file_survives(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            compose = root / "docker-compose.yml"
            compose.write_text(
                "name: floppy-test\n"
                "services:\n"
                "  floppy:\n"
                "    image: ghcr.io/dannyvfilms/floppy:release\n"
                "    volumes:\n"
                "      - ./hand-added-extra:/custom\n"
                "  redis:\n"
                "    image: redis:8-alpine\n",
                encoding="utf-8",
            )
            run_docker_helper(
                'FLOPPY_IMAGE="ghcr.io/dannyvfilms/floppy:latest"\n'
                "_docker_update_image_tag\n",
                root,
            )
            text = compose.read_text(encoding="utf-8")
        self.assertIn("./hand-added-extra:/custom", text)
        self.assertIn("image: ghcr.io/dannyvfilms/floppy:latest", text)


class GeneratedComposeTests(SimpleTestCase):
    def render(self, root):
        output = root / "docker-compose.yml"
        run_helper(
            "render_template "
            f'"{TEMPLATE_DIR / "docker-compose.install.yml.tmpl"}" "{output}" '
            f'"ROOT={root}" "IMAGE=ghcr.io/dannyvfilms/floppy:release" '
            f'"ENV_FILE={root}/floppy.env" "DATA_DIR={root}/db" '
            f'"BACKUP_DIR={root}/backups" "REDIS_DIR={root}/redis" '
            '"BIND=127.0.0.1" "PORT=8123" "PROJECT=floppy-my-floppy"',
            root,
        )
        return yaml.safe_load(output.read_text(encoding="utf-8"))

    def test_generated_stack_is_valid_yaml_with_the_expected_wiring(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "My Floppy"
            root.mkdir()
            compose = self.render(root)

        floppy = compose["services"]["floppy"]
        self.assertEqual(floppy["image"], "ghcr.io/dannyvfilms/floppy:release")
        self.assertEqual(floppy["ports"], ["127.0.0.1:8123:8000"])
        self.assertIn(f"{root}/db:/floppy/db", floppy["volumes"])
        self.assertIn(f"{root}/backups:/floppy/backups", floppy["volumes"])
        self.assertEqual(floppy["env_file"], [f"{root}/floppy.env"])

        redis = compose["services"]["redis"]
        self.assertIn(f"{root}/redis:/data", redis["volumes"])
        self.assertIn("--appendonly yes", redis["command"])
        self.assertIn("--maxmemory-policy volatile-lru", redis["command"])

    def test_floppy_waits_for_a_healthy_redis(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            compose = self.render(root)
        self.assertEqual(
            compose["services"]["floppy"]["depends_on"]["redis"]["condition"],
            "service_healthy",
        )
        self.assertIn("healthcheck", compose["services"]["redis"])

    def test_installation_owns_its_own_project_and_no_fixed_container_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "My Floppy"
            root.mkdir()
            compose = self.render(root)
        # A fixed container_name would collide with, or take over, an existing
        # Floppy stack on the same host.
        self.assertEqual(compose["name"], "floppy-my-floppy")
        for name, service in compose["services"].items():
            with self.subTest(service=name):
                self.assertNotIn("container_name", service)

    def test_no_build_section_so_cloning_never_builds_an_image(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            compose = self.render(Path(temp_dir))
        for name, service in compose["services"].items():
            with self.subTest(service=name):
                self.assertNotIn("build", service)


class GeneratedSupervisorTests(SimpleTestCase):
    def render(self, root):
        output = root / "supervisord.conf"
        run_helper(
            "render_template "
            f'"{TEMPLATE_DIR / "supervisord.install.conf.tmpl"}" "{output}" '
            f'"RUN_DIR={root}/run" "LOG_DIR={root}/logs" "REDIS_DIR={root}/redis" '
            '"REDIS_SERVER=/usr/bin/redis-server" "NGINX=/usr/sbin/nginx" '
            f'"SRC_DIR={root}/repo/src" "VENV_DIR={root}/repo/.venv"',
            root,
        )
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(output.read_text(encoding="utf-8"))
        return parser

    def test_every_process_is_defined_and_runs_from_the_installation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "My Floppy"
            root.mkdir()
            parser = self.render(root)

        expected = {
            "program:redis",
            "program:nginx",
            "program:gunicorn",
            "program:celery",
            "program:celery-interactive",
            "program:celery-discover",
        }
        self.assertTrue(expected.issubset(set(parser.sections())))

        self.assertEqual(
            parser["program:gunicorn"]["directory"],
            f"{root}/repo/src",
        )
        self.assertIn(
            f"{root}/repo/.venv/bin",
            parser["supervisord"]["environment"],
        )
        # Unquoted, because Supervisor takes these options literally: quoting
        # them would make the quotes part of the path.
        self.assertEqual(parser["supervisord"]["logfile"], f"{root}/logs/supervisord.log")

    def test_optional_workers_follow_the_resource_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            parser = self.render(Path(temp_dir))
        self.assertEqual(
            parser["program:celery-interactive"]["autostart"],
            "%(ENV_FLOPPY_START_INTERACTIVE_WORKER)s",
        )
        self.assertEqual(
            parser["program:celery-discover"]["autostart"],
            "%(ENV_FLOPPY_START_DISCOVER_WORKER)s",
        )

    def test_the_interactive_worker_never_takes_background_queues(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            parser = self.render(Path(temp_dir))
        command = parser["program:celery-interactive"]["command"]
        self.assertIn("--queues interactive", command)
        self.assertNotIn("celery,", command)


class GeneratedNginxTests(SimpleTestCase):
    def render(self, root, *, bind="0.0.0.0", port="8123"):  # noqa: S104
        output = root / "nginx.conf"
        run_helper(
            "render_template "
            f'"{TEMPLATE_DIR / "nginx.install.conf.tmpl"}" "{output}" '
            f'"RUN_DIR={root}/run" "LOG_DIR={root}/logs" '
            '"MIME_TYPES=/etc/nginx/mime.types" '
            f'"STATIC_ROOT={root}/repo/src/staticfiles" '
            f'"BIND={bind}" "PORT={port}"',
            root,
        )
        return output.read_text(encoding="utf-8")

    def test_listener_and_static_root_follow_the_answers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "My Floppy"
            root.mkdir()
            conf = self.render(root, bind="127.0.0.1", port="9001")
        self.assertIn("listen 127.0.0.1:9001;", conf)
        self.assertIn(f'alias "{root}/repo/src/staticfiles/";', conf)
        self.assertIn("server 127.0.0.1:8001;", conf)

    def test_access_log_keeps_query_strings_out(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            conf = self.render(Path(temp_dir))
        self.assertIn("$request_method $uri $server_protocol", conf)
        self.assertNotIn("$request ", conf)
        self.assertNotIn("$query_string", conf)
        self.assertNotIn("$http_referer", conf)


class GeneratedServiceUnitTests(SimpleTestCase):
    def test_systemd_unit_runs_the_wrapper_as_the_installing_user(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "My Floppy"
            root.mkdir()
            output = root / "floppy.service"
            run_helper(
                "render_template "
                f'"{TEMPLATE_DIR / "floppy.service.tmpl"}" "{output}" '
                '"RUN_USER=media" "RUN_GROUP=media" '
                f'"SRC_DIR={root}/repo/src" "RUN_DIR={root}/run"',
                root,
            )
            unit = output.read_text(encoding="utf-8")
        self.assertIn("User=media", unit)
        self.assertIn(f"ExecStart={root}/run/floppy-supervisord", unit)
        self.assertIn("WantedBy=multi-user.target", unit)

    def test_launch_daemon_runs_the_wrapper_as_the_installing_user(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "My Floppy"
            root.mkdir()
            output = root / "com.floppy.app.plist"
            run_helper(
                "render_template "
                f'"{TEMPLATE_DIR / "com.floppy.app.plist.tmpl"}" "{output}" '
                '"RUN_USER=media" "RUN_GROUP=staff" '
                f'"SRC_DIR={root}/repo/src" "RUN_DIR={root}/run" '
                f'"LOG_DIR={root}/logs" "VENV_DIR={root}/repo/.venv" '
                '"EXTRA_PATH=/opt/homebrew/bin"',
                root,
            )
            plist = output.read_text(encoding="utf-8")
        import plistlib

        parsed = plistlib.loads(plist.encode("utf-8"))
        self.assertEqual(parsed["Label"], "com.floppy.app")
        self.assertEqual(parsed["UserName"], "media")
        self.assertEqual(
            parsed["ProgramArguments"],
            [f"{root}/run/floppy-supervisord"],
        )
        self.assertTrue(parsed["RunAtLoad"])
        self.assertTrue(parsed["KeepAlive"])


class GeneratedWrapperTests(SimpleTestCase):
    def test_wrapper_loads_configuration_and_probes_the_resource_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "My Floppy"
            root.mkdir()
            output = root / "floppy-supervisord"
            run_helper(
                "render_template "
                f'"{TEMPLATE_DIR / "floppy-supervisord.tmpl"}" "{output}" '
                f'"ENV_FILE={root}/floppy.env" "VENV_DIR={root}/repo/.venv" '
                f'"SRC_DIR={root}/repo/src" "RUN_DIR={root}/run" '
                f'"LOG_DIR={root}/logs"',
                root,
            )
            wrapper = output.read_text(encoding="utf-8")
            syntax = subprocess.run(  # noqa: S603 - test-controlled script
                ["bash", "-n", str(output)],  # noqa: S607
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        self.assertIn(f'. "{root}/floppy.env"', wrapper)
        self.assertIn("from config.runtime_profile import emit_env", wrapper)
        self.assertIn("FLOPPY_START_INTERACTIVE_WORKER", wrapper)
        self.assertIn(f'exec supervisord -c "{root}/run/supervisord.conf"', wrapper)
