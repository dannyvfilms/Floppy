"""Instance-level server-port helpers for Advanced settings."""

from __future__ import annotations

import os
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
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

RUNTIME_PORT_PATH = Path("/tmp/floppy-runtime/server-port")  # noqa: S108 - container-private runtime directory


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


def _wants_json(request) -> bool:
    """Return whether the browser adapter asked for an in-place result."""
    accept = request.headers.get("Accept", "")
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in accept
    )


def _json_port_result(request, message: str, *, ok: bool = True):
    """Return a fresh server-port payload for an async browser write."""
    from users.advanced_props import server_port_props

    return JsonResponse(
        {
            "ok": ok,
            "message": message,
            "serverPort": server_port_props(request),
        },
        status=200 if ok else 400,
    )


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
            message = str(exc)
            messages.error(request, message)
            if _wants_json(request):
                return _json_port_result(request, message, ok=False)
        else:
            if removed:
                message = (
                    "Saved server port removed. Restart Floppy to apply the current "
                    "environment or default value."
                )
                messages.success(request, message)
            else:
                message = "No saved server port was set."
                messages.info(request, message)
            if _wants_json(request):
                return _json_port_result(request, message)
        return redirect("advanced")

    if action == "save":
        if _environment_override_active():
            message = (
                f"{SERVER_PORT_ENV} controls the server port for this instance. "
                "Change or remove that environment variable, then restart Floppy."
            )
            messages.error(request, message)
            if _wants_json(request):
                return _json_port_result(request, message, ok=False)
            return redirect("advanced")

        try:
            saved_port = save_server_port(request.POST.get("port", ""))
        except ServerPortError as exc:
            message = str(exc)
            messages.error(request, message)
            if _wants_json(request):
                return _json_port_result(request, message, ok=False)
        else:
            running_port = _runtime_port()
            if running_port == saved_port:
                message = (
                    f"Server port {saved_port} saved. The current listener already "
                    "uses this port."
                )
            else:
                message = (
                    f"Server port {saved_port} saved. If your container publishes "
                    f"Floppy's port, update its target to {saved_port} before you "
                    "restart Floppy."
                )
            messages.success(request, message)
            if _wants_json(request):
                return _json_port_result(request, message)
        return redirect("advanced")

    message = "Unknown server port action."
    messages.error(request, message)
    if _wants_json(request):
        return _json_port_result(request, message, ok=False)
    return redirect("advanced")
