"""What an idle instance's Celery workers, Beat and broker do between tasks.

Measured in docs/plans OPS-12 (prompt 53): worker heartbeat events nobody
read, a BRPOP re-issued every second per worker, and Beat re-reading the
schedule table every 5 s were most of the idle worker and Redis cost. Each
default below is a Celery or Kombu option whose old value is one environment
variable away.
"""

import configparser
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[3]
CELERY_PROGRAMS = ("celery", "celery-interactive", "celery-discover")


def _docker_command(program, env):
    """Run a supervisord celery command with ``exec celery`` swapped for echo."""
    parser = configparser.RawConfigParser(strict=False)
    parser.read(ROOT / "supervisord.conf", encoding="utf-8")
    command = parser[f"program:{program}"]["command"].replace("%%", "%")
    argv = shlex.split(command)
    if argv[:2] != ["sh", "-c"]:
        raise AssertionError(argv)
    script = argv[2].replace("exec celery", "echo celery")
    clean = {k: v for k, v in os.environ.items() if not k.startswith("FLOPPY_")}
    result = subprocess.run(  # noqa: S603 - test-controlled script
        ["sh", "-c", script],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
        env={**clean, **env},
    )
    return result.stdout.strip().splitlines()[-1]


class WorkerHeartbeatTests(SimpleTestCase):
    def test_workers_send_no_heartbeat_by_default(self):
        for program in CELERY_PROGRAMS:
            with self.subTest(program):
                line = _docker_command(program, {})
                self.assertTrue(line.startswith("celery --app config worker"))
                self.assertIn("--without-heartbeat", line.split())

    def test_heartbeat_can_be_turned_back_on(self):
        for program in CELERY_PROGRAMS:
            with self.subTest(program):
                line = _docker_command(program, {"FLOPPY_CELERY_HEARTBEAT": "on"})
                self.assertNotIn("--without-heartbeat", line.split())
                self.assertIn("--without-gossip", line.split())

    def test_installer_template_passes_the_same_flag(self):
        text = (
            ROOT / "scripts/install/templates/supervisord.install.conf.tmpl"
        ).read_text(encoding="utf-8")
        commands = [
            line for line in text.splitlines() if line.startswith("command=celery")
        ]
        self.assertEqual(len(commands), 3)
        for line in commands:
            self.assertTrue(line.endswith("%(ENV_FLOPPY_CELERY_HEARTBEAT_ARG)s"))

    def test_installer_wrapper_sets_the_flag_from_one_variable(self):
        wrapper = (
            ROOT / "scripts/install/templates/floppy-supervisord.tmpl"
        ).read_text(encoding="utf-8")
        start = wrapper.index('if [ "${FLOPPY_CELERY_HEARTBEAT')
        block = wrapper[start : wrapper.index("\nfi\n", start) + 4]
        script = block + 'printf "%s" "$FLOPPY_CELERY_HEARTBEAT_ARG"'
        for value, expected in (("", "--without-heartbeat"), ("on", "")):
            with self.subTest(value=value):
                env = {"PATH": os.environ["PATH"]}
                if value:
                    env["FLOPPY_CELERY_HEARTBEAT"] = value
                result = subprocess.run(  # noqa: S603 - test-controlled script
                    ["bash", "-c", script],  # noqa: S607
                    capture_output=True,
                    text=True,
                    check=True,
                    env=env,
                )
                self.assertEqual(result.stdout, expected)


def _transport_options(role):
    """Load settings in a fresh process with ``FLOPPY_PROCESS_ROLE`` = role."""
    env = {k: v for k, v in os.environ.items() if k != "FLOPPY_PROCESS_ROLE"}
    env.pop("CELERY_BROKER_POLLING_INTERVAL", None)
    if role:
        env["FLOPPY_PROCESS_ROLE"] = role
    env["DJANGO_SETTINGS_MODULE"] = "config.settings"
    code = (
        "import json, django; django.setup();"
        "from django.conf import settings;"
        "print(json.dumps(settings.CELERY_BROKER_TRANSPORT_OPTIONS))"
    )
    result = subprocess.run(  # noqa: S603 - fixed interpreter and code
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=ROOT / "src",
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


class IdlePollingTests(SimpleTestCase):
    def test_an_idle_worker_re_asks_the_broker_every_ten_seconds(self):
        for role in ("background", "interactive", "combined"):
            with self.subTest(role):
                options = _transport_options(role)
                self.assertEqual(options["polling_interval"], 10)
                # A blocking read longer than the socket timeout would look
                # like a dead connection.
                self.assertLess(
                    options["polling_interval"], options["socket_timeout"]
                )

    def test_web_and_shell_processes_keep_kombus_pace(self):
        # A caller's leftover 10 s BRPOP on its reply queue swallowed the next
        # control.ping's replies, so the health check saw no workers.
        for role in ("web", ""):
            with self.subTest(role=role or "unset"):
                self.assertNotIn("polling_interval", _transport_options(role))

    def test_kombu_turns_the_polling_interval_into_the_brpop_timeout(self):
        from kombu import Connection

        conn = Connection(
            "redis://localhost:6379/0",
            transport_options={"polling_interval": 10},
        )
        self.assertEqual(conn.transport.brpop_timeout, 10)

    def test_beat_rereads_the_schedule_once_a_minute(self):
        from config.celery import app

        self.assertEqual(settings.CELERY_BEAT_MAX_LOOP_INTERVAL, 60)
        self.assertEqual(app.conf.beat_max_loop_interval, 60)
        # Beat still wakes for its most frequent entries on time.
        shortest = min(
            entry["schedule"]
            for entry in settings.CELERY_BEAT_SCHEDULE.values()
            if isinstance(entry["schedule"], int | float)
        )
        self.assertLessEqual(settings.CELERY_BEAT_MAX_LOOP_INTERVAL, shortest)
