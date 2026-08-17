"""Instance-level server-port helpers for Advanced settings."""

from __future__ import annotations

import os
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from config.server_port import (
    DEFAULT_SERVER_PORT,
    SERVER_PORT_ENV,
    ServerPortError,
    clear_saved_port,
    get_server_port_status,
    save_server_port,
    validate_port,
)

RUNTIME_PORT_PATH = Path("/run/floppy/server-port")


def _runtime_port() -> int | None:
    """Return the listener recorded by the current launcher, when available."""
    try:
        return validate_port(
            RUNTIME_PORT_PATH.read_text(encoding="ascii"),
            source="runtime server port",
        )
    except (FileNotFoundError, OSError, UnicodeDecodeError, ServerPortError):
        return None


def _environment_override_active() -> bool:
    """Return whether the environment owns the server-port value."""
    return SERVER_PORT_ENV in os.environ


def server_port_context() -> dict[str, object]:
    """Build the Advanced-panel state without a database or network lookup."""
    environment_override = _environment_override_active()
    try:
        status = get_server_port_status()
        config_error = status.saved_error or ""
        config_error_source = "saved" if status.saved_error else ""
    except ServerPortError as exc:
        status = None
        config_error = str(exc)
        config_error_source = "environment" if environment_override else "saved"

    return {
        "server_port_status": status,
        "server_port_config_error": config_error,
        "server_port_config_error_source": config_error_source,
        "runtime_port": _runtime_port(),
        "default_port": DEFAULT_SERVER_PORT,
        "environment_name": SERVER_PORT_ENV,
        "environment_override": environment_override,
        "show_reset": bool(
            config_error_source == "saved"
            or (status is not None and status.saved_port is not None)
        ),
    }


@login_required
@require_POST
def update_server_port(request):
    """Update the Advanced server-port setting for a superuser."""
    if not request.user.is_superuser:
        raise PermissionDenied

    action = request.POST.get("action", "")

    if action == "reset":
        try:
            removed = clear_saved_port()
        except ServerPortError as exc:
            messages.error(request, str(exc))
        else:
            if removed:
                messages.success(
                    request,
                    "Saved server port removed. Restart Floppy to apply the current "
                    "environment or default value.",
                )
            else:
                messages.info(request, "No saved server port was set.")
        return redirect("advanced")

    if action == "save":
        if _environment_override_active():
            messages.error(
                request,
                f"{SERVER_PORT_ENV} controls the server port for this instance. "
                "Change or remove that environment variable, then restart Floppy.",
            )
            return redirect("advanced")

        try:
            saved_port = save_server_port(request.POST.get("port", ""))
        except ServerPortError as exc:
            messages.error(request, str(exc))
        else:
            running_port = _runtime_port()
            if running_port == saved_port:
                messages.success(
                    request,
                    f"Server port {saved_port} saved. The current listener already "
                    "uses this port.",
                )
            else:
                messages.success(
                    request,
                    f"Server port {saved_port} saved. If your container publishes "
                    f"Floppy's port, update its target to {saved_port} before you "
                    "restart Floppy.",
                )
        return redirect("advanced")

    messages.error(request, "Unknown server port action.")
    return redirect("advanced")
