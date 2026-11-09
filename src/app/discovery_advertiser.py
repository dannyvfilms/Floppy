"""Advertise this Floppy instance over local DNS-SD/mDNS."""

from __future__ import annotations

import ipaddress
import logging
import os
import re
import signal
import socket
import threading

from zeroconf import IPVersion, ServiceInfo, Zeroconf

LOGGER = logging.getLogger("floppy.discovery")
SERVICE_TYPE = "_http._tcp.local."
AUTH_CONFIG_PATH = "/accounts/auth-config/"
IPV4_VERSION = 4
MAX_PORT = 65535
MAX_DNS_LABEL_BYTES = 63
CONFIGURED_HOST_ERROR = "configured-host"
AUTOMATIC_HOST_ERROR = "automatic-host"
PORT_ERROR = "port"
NAME_ERROR = "name"


class DiscoveryConfigurationError(ValueError):
    """Raised when the local DNS-SD advertisement cannot be configured."""

    messages = {
        "configured-host": "FLOPPY_ADVERTISE_HOST must be a reachable IPv4 address.",
        "automatic-host": "Could not determine a reachable LAN IPv4 address.",
        "port": "FLOPPY_ADVERTISE_PORT must be an integer from 1 to 65535.",
        "name": "FLOPPY_ADVERTISE_NAME must be at most 63 UTF-8 bytes.",
    }

    def __init__(self, reason: str) -> None:
        """Create a configuration failure from its short reason code."""
        super().__init__(self.messages[reason])


def _host_address() -> str:
    configured = os.environ.get("FLOPPY_ADVERTISE_HOST", "").strip()
    if configured:
        address = ipaddress.ip_address(configured)
        if (
            address.version != IPV4_VERSION
            or address.is_loopback
            or address.is_link_local
        ):
            raise DiscoveryConfigurationError(CONFIGURED_HOST_ERROR)
        return str(address)

    # A UDP route lookup selects the host interface that would send mDNS traffic
    # without transmitting a packet. The host-networked Compose sidecar sees the
    # Linux host's interfaces here, including on Unraid.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect(("224.0.0.251", 5353))
        address = ipaddress.ip_address(probe.getsockname()[0])
    if address.is_loopback or address.is_link_local:
        raise DiscoveryConfigurationError(AUTOMATIC_HOST_ERROR)
    return str(address)


def _service_info() -> ServiceInfo:
    address = _host_address()
    raw_port = os.environ.get("FLOPPY_ADVERTISE_PORT", "8000").strip()
    try:
        port = int(raw_port)
    except ValueError as error:
        raise DiscoveryConfigurationError(PORT_ERROR) from error
    if not 1 <= port <= MAX_PORT:
        raise DiscoveryConfigurationError(PORT_ERROR)

    name = os.environ.get("FLOPPY_ADVERTISE_NAME", "Floppy").strip() or "Floppy"
    if len(name.encode("utf-8")) > MAX_DNS_LABEL_BYTES:
        raise DiscoveryConfigurationError(NAME_ERROR)
    host_label = (
        re.sub(r"[^a-zA-Z0-9-]", "-", socket.gethostname()).strip("-") or "floppy"
    )
    return ServiceInfo(
        type_=SERVICE_TYPE,
        name=f"{name}.{SERVICE_TYPE}",
        addresses=[ipaddress.ip_address(address).packed],
        port=port,
        properties={b"floppy": b"1", b"path": AUTH_CONFIG_PATH.encode("ascii")},
        server=f"{host_label}.local.",
    )


def run() -> None:
    """Advertise this Floppy instance until the container receives shutdown."""
    info = _service_info()
    address = str(ipaddress.ip_address(info.addresses[0]))
    zeroconf = Zeroconf(interfaces=[address], ip_version=IPVersion.V4Only)
    stopped = threading.Event()

    def stop(*_args: object) -> None:
        stopped.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        zeroconf.register_service(info, allow_name_change=True)
        LOGGER.info("Advertising %s on port %s", info.name, info.port)
        stopped.wait()
    finally:
        zeroconf.unregister_service(info)
        zeroconf.close()


def main() -> None:
    """Start the advertiser and print configuration failures to stderr."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        run()
    except (OSError, ValueError) as error:
        LOGGER.exception("Floppy DNS-SD advertiser failed")
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
