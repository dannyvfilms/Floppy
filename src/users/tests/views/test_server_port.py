import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from config.server_port import config_path, load_saved_port, save_server_port
from users import server_port_views


class AdvancedServerPortTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.runtime_port = self.data_dir / "runtime-port"
        self.runtime_port.write_text("8000\n", encoding="ascii")

        self.superuser = get_user_model().objects.create_superuser(
            username="admin",
            password="testpass123",
            email="admin@example.test",
        )
        self.user = get_user_model().objects.create_user(
            username="normal-user",
            password="testpass123",
        )

        self.environment = mock.patch.dict(
            "os.environ",
            {"FLOPPY_DATA_DIR": str(self.data_dir)},
            clear=True,
        )
        self.runtime_path = mock.patch.object(
            server_port_views,
            "RUNTIME_PORT_PATH",
            self.runtime_port,
        )
        self.environment.start()
        self.runtime_path.start()

    def tearDown(self):
        self.runtime_path.stop()
        self.environment.stop()
        self.temp_dir.cleanup()
        super().tearDown()

    def test_standalone_server_settings_route_does_not_exist(self):
        with self.assertRaises(NoReverseMatch):
            reverse("server_settings")

    def test_normal_user_can_open_advanced_without_instance_port_controls(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("advanced"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="server-port"')
        self.assertNotContains(response, "Running listener")

    def test_normal_user_cannot_mutate_server_port(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("update_server_port"),
            {"action": "save", "port": "9123"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertIsNone(load_saved_port())

    def test_superuser_advanced_shows_default_and_running_listener(self):
        self.client.force_login(self.superuser)

        response = self.client.get(reverse("advanced"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/advanced.html")
        self.assertContains(response, "Server port")
        self.assertContains(response, "Running listener")
        self.assertContains(response, "Configured port")
        self.assertContains(response, "Source: default")
        self.assertContains(response, "8000")
        self.assertContains(response, reverse("update_server_port"))
        self.assertContains(
            response,
            'aria-describedby="server-port-help server-port-source"',
        )

    def test_superuser_can_save_port_from_advanced(self):
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse("update_server_port"),
            {"action": "save", "port": "9123"},
            follow=True,
        )

        self.assertEqual(load_saved_port(), 9123)
        self.assertRedirects(response, reverse("advanced"))
        self.assertContains(response, "Server port 9123 saved")
        self.assertContains(response, "target to 9123")
        self.assertContains(response, "restart Floppy")

    def test_invalid_port_is_rejected_without_changing_saved_value(self):
        self.client.force_login(self.superuser)
        save_server_port(9123)

        response = self.client.post(
            reverse("update_server_port"),
            {"action": "save", "port": "70000"},
            follow=True,
        )

        self.assertEqual(load_saved_port(), 9123)
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(
            any("integer from 1 to 65535" in message for message in messages)
        )

    def test_environment_override_is_visible_and_blocks_web_save(self):
        self.client.force_login(self.superuser)
        save_server_port(9123)

        with mock.patch.dict("os.environ", {"FLOPPY_PORT": "8443"}, clear=False):
            response = self.client.get(reverse("advanced"))
            self.assertContains(response, "Environment override is active")
            self.assertContains(response, "8443")
            self.assertContains(response, 'id="server-port"')
            self.assertContains(response, "disabled")

            response = self.client.post(
                reverse("update_server_port"),
                {"action": "save", "port": "9000"},
                follow=True,
            )

        self.assertEqual(load_saved_port(), 9123)
        self.assertRedirects(response, reverse("advanced"))
        self.assertContains(response, "FLOPPY_PORT controls the server port")

    def test_invalid_environment_value_is_not_presented_as_saved_state(self):
        self.client.force_login(self.superuser)

        with mock.patch.dict(
            "os.environ",
            {"FLOPPY_PORT": "not-a-port"},
            clear=False,
        ):
            response = self.client.get(reverse("advanced"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Environment server port is invalid")
        self.assertContains(response, "Not evaluated")
        self.assertNotContains(response, "Reset saved value")

    def test_malformed_saved_configuration_can_be_reset_from_advanced(self):
        self.client.force_login(self.superuser)
        path = config_path()
        path.write_text("{not json", encoding="utf-8")

        response = self.client.get(reverse("advanced"))
        self.assertContains(response, "Saved server port cannot be read")
        self.assertContains(response, "Unreadable")
        self.assertContains(response, "Reset saved value")

        response = self.client.post(
            reverse("update_server_port"),
            {"action": "reset"},
            follow=True,
        )

        self.assertFalse(path.exists())
        self.assertRedirects(response, reverse("advanced"))
        self.assertContains(response, "Saved server port removed")

    def test_malformed_saved_fallback_is_reported_under_environment_override(self):
        self.client.force_login(self.superuser)
        path = config_path()
        path.write_text("{not json", encoding="utf-8")

        with mock.patch.dict("os.environ", {"FLOPPY_PORT": "8443"}, clear=False):
            response = self.client.get(reverse("advanced"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Environment override is active")
        self.assertContains(response, "Saved server port cannot be read")
        self.assertContains(response, "Unreadable")
        self.assertContains(response, "8443")

    def test_missing_or_malformed_runtime_port_is_not_presented_as_active(self):
        self.client.force_login(self.superuser)
        self.runtime_port.write_text("8000; invalid\n", encoding="ascii")

        response = self.client.get(reverse("advanced"))

        self.assertContains(response, "Not reported")
        self.assertNotContains(response, "8000; invalid")

    def test_unknown_action_does_not_mutate_configuration(self):
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse("update_server_port"),
            {"action": "unknown", "port": "9123"},
            follow=True,
        )

        self.assertIsNone(load_saved_port())
        self.assertRedirects(response, reverse("advanced"))
        self.assertContains(response, "Unknown server port action")
