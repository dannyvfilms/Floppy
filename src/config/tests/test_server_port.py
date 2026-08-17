import json
import os
import stat
import tempfile
from pathlib import Path
from unittest import mock, skipIf

from django.test import SimpleTestCase

from config import server_port


class ServerPortValidationTests(SimpleTestCase):
    def test_accepts_tcp_port_boundaries(self):
        self.assertEqual(server_port.validate_port(1), 1)
        self.assertEqual(server_port.validate_port("65535"), 65535)

    def test_rejects_invalid_values(self):
        invalid_values = (
            0,
            65536,
            "",
            " ",
            "not-a-port",
            "8000; daemon off;",
            "-1",
            "1.5",
            True,
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(server_port.ServerPortError):
                server_port.validate_port(value)


class ServerPortResolutionTests(SimpleTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()
        super().tearDown()

    def _save(self, port):
        server_port.save_server_port(port, data_dir=self.data_dir, environ={})

    def test_default_is_8000(self):
        self.assertEqual(
            server_port.resolve_server_port(environ={}, data_dir=self.data_dir),
            8000,
        )

    def test_saved_value_overrides_default(self):
        self._save(9123)

        self.assertEqual(
            server_port.resolve_server_port(environ={}, data_dir=self.data_dir),
            9123,
        )

    def test_environment_overrides_saved_value(self):
        self._save(9123)

        status = server_port.get_server_port_status(
            environ={"FLOPPY_PORT": "8443"},
            data_dir=self.data_dir,
        )

        self.assertEqual(status.effective_port, 8443)
        self.assertEqual(status.environment_port, 8443)
        self.assertEqual(status.saved_port, 9123)
        self.assertEqual(status.source, "environment")

    def test_invalid_environment_never_falls_back_silently(self):
        self._save(9123)

        with self.assertRaisesRegex(server_port.ServerPortError, "FLOPPY_PORT"):
            server_port.resolve_server_port(
                environ={"FLOPPY_PORT": "8000; exit 0"},
                data_dir=self.data_dir,
            )

    def test_reset_restores_default_without_environment_override(self):
        self._save(9123)

        self.assertTrue(
            server_port.clear_saved_port(environ={}, data_dir=self.data_dir),
        )
        self.assertFalse(
            server_port.clear_saved_port(environ={}, data_dir=self.data_dir),
        )
        self.assertEqual(
            server_port.resolve_server_port(environ={}, data_dir=self.data_dir),
            8000,
        )

    def test_malformed_saved_configuration_fails_closed(self):
        path = server_port.config_path(environ={}, data_dir=self.data_dir)
        path.write_text("{not json", encoding="utf-8")

        with self.assertRaisesRegex(server_port.ServerPortError, "invalid JSON"):
            server_port.resolve_server_port(environ={}, data_dir=self.data_dir)

    def test_missing_saved_port_fails_closed(self):
        path = server_port.config_path(environ={}, data_dir=self.data_dir)
        path.write_text('{"other": 8000}\n', encoding="utf-8")

        with self.assertRaisesRegex(server_port.ServerPortError, "must contain"):
            server_port.resolve_server_port(environ={}, data_dir=self.data_dir)

    def test_environment_can_keep_runtime_available_when_saved_file_is_bad(self):
        path = server_port.config_path(environ={}, data_dir=self.data_dir)
        path.write_text("{not json", encoding="utf-8")

        status = server_port.get_server_port_status(
            environ={"FLOPPY_PORT": "9000"},
            data_dir=self.data_dir,
        )

        self.assertEqual(status.effective_port, 9000)
        self.assertEqual(status.source, "environment")
        self.assertIsNotNone(status.saved_error)

    @skipIf(os.name == "nt", "POSIX file permissions are not portable to Windows")
    def test_saved_file_is_private_and_atomic_write_leaves_no_temp_file(self):
        self._save(8123)
        path = server_port.config_path(environ={}, data_dir=self.data_dir)

        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"port": 8123})
        self.assertEqual(
            list(path.parent.glob(f".{path.name}.*")),
            [],
        )

    @skipIf(
        not hasattr(os, "O_NOFOLLOW") or os.name == "nt",
        "Symlink-safe open is not available on this platform",
    )
    def test_saved_configuration_symlink_is_rejected(self):
        target = self.data_dir / "target.json"
        target.write_text('{"port": 9000}\n', encoding="utf-8")
        path = server_port.config_path(environ={}, data_dir=self.data_dir)
        path.symlink_to(target)

        with self.assertRaises(server_port.ServerPortError):
            server_port.load_saved_port(environ={}, data_dir=self.data_dir)


class NginxServerPortTests(SimpleTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.template = self.root / "nginx.conf.template"
        self.ipv4 = self.root / "nginx.conf"
        self.ipv6 = self.root / "nginx.ipv6.conf"
        self.runtime_port = self.root / "run" / "server-port"

    def tearDown(self):
        self.temp_dir.cleanup()
        super().tearDown()

    def test_renders_ipv4_and_ipv6_from_one_validated_value(self):
        self.template.write_text(
            "events {}\nhttp {\n    server {\n        listen 8000;\n    }\n}\n",
            encoding="utf-8",
        )

        server_port.render_nginx_configs(
            self.template,
            self.ipv4,
            self.ipv6,
            8123,
        )

        self.assertIn("listen 8123;", self.ipv4.read_text(encoding="utf-8"))
        ipv6_content = self.ipv6.read_text(encoding="utf-8")
        self.assertIn("listen 8123;", ipv6_content)
        self.assertIn("listen [::]:8123;", ipv6_content)
        self.assertNotIn("listen 8000;", ipv6_content)

    def test_rejects_template_with_ambiguous_listener_marker(self):
        self.template.write_text(
            "listen 8000;\nlisten 8000;\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(server_port.ServerPortError, "exactly one"):
            server_port.render_nginx_configs(
                self.template,
                self.ipv4,
                self.ipv6,
                8123,
            )

    def test_prepare_runtime_writes_health_check_port(self):
        self.template.write_text("server { listen 8000; }\n", encoding="utf-8")

        with mock.patch.dict(
            os.environ,
            {
                "FLOPPY_DATA_DIR": str(self.root / "data"),
                "FLOPPY_PORT": "9010",
            },
            clear=True,
        ):
            port = server_port.prepare_runtime(
                self.template,
                self.ipv4,
                self.ipv6,
                self.runtime_port,
            )

        self.assertEqual(port, 9010)
        self.assertEqual(self.runtime_port.read_text(encoding="ascii"), "9010\n")


class ServerPortCliTests(SimpleTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.env_patch = mock.patch.dict(
            os.environ,
            {"FLOPPY_DATA_DIR": str(self.data_dir)},
            clear=True,
        )
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.temp_dir.cleanup()
        super().tearDown()

    def test_json_status_is_machine_readable(self):
        with mock.patch("sys.stdout") as stdout:
            exit_code = server_port.main(["--json"])

        self.assertEqual(exit_code, 0)
        output = "".join(call.args[0] for call in stdout.write.call_args_list)
        payload = json.loads(output)
        self.assertEqual(payload["effective_port"], 8000)
        self.assertEqual(payload["source"], "default")

    def test_set_and_reset_use_same_saved_value_as_runtime(self):
        self.assertEqual(server_port.main(["--set", "8124"]), 0)
        self.assertEqual(server_port.resolve_server_port(), 8124)

        self.assertEqual(server_port.main(["--reset"]), 0)
        self.assertEqual(server_port.resolve_server_port(), 8000)

    def test_invalid_cli_value_returns_configuration_error(self):
        with mock.patch("sys.stderr") as stderr:
            exit_code = server_port.main(["--set", "8123; echo nope"])

        self.assertEqual(exit_code, 2)
        output = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("must be an integer from 1 to 65535", output)
