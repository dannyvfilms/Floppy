"""Control outbound metadata provider access."""

import functools
import os
import re
from collections.abc import Iterable

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

VALID_NETWORK_MODES = frozenset({"online", "offline", "restricted"})
_PROVIDER_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _configured_value(name, legacy_name, default=None):
    """Return a setting value, then an environment value, then the default."""
    value = getattr(settings, name, None)
    if value is not None:
        return value
    return os.environ.get(name, os.environ.get(legacy_name, default))


def _normalize_provider(provider):
    """Return one exact provider identifier or fail closed."""
    normalized = str(provider or "").strip().casefold()
    if not _PROVIDER_IDENTIFIER_PATTERN.fullmatch(normalized):
        msg = "Provider identifiers must use letters, numbers, hyphens, or underscores."
        raise ImproperlyConfigured(msg)
    return normalized


def get_network_mode():
    """Return the configured provider-network mode."""
    raw_mode = _configured_value(
        "FLOPPY_NETWORK_MODE",
        "YAMTRACK_NETWORK_MODE",
        default="online",
    )
    mode = str(raw_mode or "").strip().casefold()
    if mode not in VALID_NETWORK_MODES:
        valid_modes = ", ".join(sorted(VALID_NETWORK_MODES))
        msg = f"FLOPPY_NETWORK_MODE must be one of: {valid_modes}."
        raise ImproperlyConfigured(msg)
    return mode


def get_provider_allowlist():
    """Return exact provider identifiers allowed in restricted mode."""
    raw_allowlist = _configured_value(
        "FLOPPY_NETWORK_ALLOWLIST",
        "YAMTRACK_NETWORK_ALLOWLIST",
        default="",
    )
    if raw_allowlist in (None, ""):
        return frozenset()

    if isinstance(raw_allowlist, str):
        values = raw_allowlist.split(",")
    elif isinstance(raw_allowlist, Iterable):
        values = raw_allowlist
    else:
        msg = "FLOPPY_NETWORK_ALLOWLIST must be a comma-separated string or iterable."
        raise ImproperlyConfigured(msg)

    providers = set()
    for value in values:
        if str(value or "").strip():
            providers.add(_normalize_provider(value))
    return frozenset(providers)


def provider_access_allowed(provider, *, mode=None):
    """Return whether one provider may use the shared HTTP boundary."""
    active_mode = mode or get_network_mode()
    if active_mode == "online":
        return True
    if active_mode == "offline":
        return False
    return _normalize_provider(provider) in get_provider_allowlist()


def install_provider_network_guard():
    """Install one fail-closed guard around the shared provider request function."""
    from app.providers import services

    current_request = services.api_request
    if getattr(current_request, "_floppy_network_guard", False):
        return current_request

    class ProviderNetworkUnavailable(services.ProviderAPIError):
        """Report an intentional provider block without leaking request data."""

        def __init__(self, provider, mode):
            provider_id = _normalize_provider(provider)
            self.provider = provider_id
            self.response = None
            self.status_code = None
            self.mode = mode
            try:
                self.provider_label = services.Sources(provider_id).label
            except (TypeError, ValueError):
                self.provider_label = provider_id.replace("_", " ").title()

            message = (
                f"Network access to {self.provider_label} is disabled "
                f"by Floppy's {mode} mode."
            )
            Exception.__init__(self, message)

    @functools.wraps(current_request)
    def guarded_request(*args, **kwargs):
        provider = kwargs.get("provider")
        if provider is None and args:
            provider = args[0]

        mode = get_network_mode()
        if not provider_access_allowed(provider, mode=mode):
            raise ProviderNetworkUnavailable(provider, mode)
        return current_request(*args, **kwargs)

    guarded_request._floppy_network_guard = True
    guarded_request._floppy_network_guard_original = current_request
    services.ProviderNetworkUnavailable = ProviderNetworkUnavailable
    services.api_request = guarded_request
    return guarded_request
