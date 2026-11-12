import ipaddress
import os
from unittest.mock import patch

from django.test import SimpleTestCase

from app import discovery_advertiser


class DiscoveryAdvertiserTests(SimpleTestCase):
    def test_advertisement_uses_configured_lan_address_port_and_floppy_marker(self):
        with (
            patch.dict(
                os.environ,
                {
                    "FLOPPY_ADVERTISE_HOST": "192.168.10.22",
                    "FLOPPY_ADVERTISE_PORT": "9010",
                    "FLOPPY_ADVERTISE_NAME": "Floppy Upstairs",
                },
                clear=True,
            ),
            patch(
                "app.discovery_advertiser.socket.gethostname",
                return_value="floppy-sidecar",
            ),
        ):
            service = discovery_advertiser._service_info()

        self.assertEqual(service.type, "_http._tcp.local.")
        self.assertEqual(service.name, "Floppy Upstairs._http._tcp.local.")
        self.assertEqual(
            service.addresses, [ipaddress.ip_address("192.168.10.22").packed]
        )
        self.assertEqual(service.port, 9010)
        self.assertEqual(
            service.properties,
            {b"floppy": b"1", b"path": b"/accounts/auth-config/"},
        )
        self.assertEqual(service.server, "floppy-sidecar.local.")

    def test_default_advertiser_address_uses_route_selected_interface(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("app.discovery_advertiser.socket.socket") as socket_factory,
        ):
            socket_factory.return_value.__enter__.return_value.getsockname.return_value = (
                "192.168.10.22",
                5353,
            )
            self.assertEqual(discovery_advertiser._host_address(), "192.168.10.22")
            socket_factory.return_value.__enter__.return_value.connect.assert_called_once_with(
                ("224.0.0.251", 5353)
            )

    def test_advertiser_rejects_invalid_host_and_port(self):
        with patch.dict(os.environ, {"FLOPPY_ADVERTISE_HOST": "127.0.0.1"}, clear=True):
            with self.assertRaisesRegex(ValueError, "reachable IPv4"):
                discovery_advertiser._host_address()

        with patch.dict(
            os.environ,
            {
                "FLOPPY_ADVERTISE_HOST": "192.168.10.22",
                "FLOPPY_ADVERTISE_PORT": "70000",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "1 to 65535"):
                discovery_advertiser._service_info()
