"""Resolve and persist Floppy's public HTTP port without Django dependencies."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from collections.abc import Mapping

DEFAULT_SERVER_PORT = 8000
MIN_SERVER_PORT = 1
MAX_SERVER_PORT = 65535
SERVER_PORT_ENV = "FLOPPY_PORT"
SERVER_PORT_FILENAME = "server-port.json"
NGINX_DEFAULT_LISTEN = "listen 8000;"


class ServerPortError(ValueError):
    """Raised when the server port configuration cannot be used."""


@dataclass(frozen=True, slots=True)
class ServerPortStatus:
    """Describe the effective server port and where it came from."""

    effective_port: int
    source: str
    saved_port: int | None
    environment_port: int | None
    config_path: str
    saved_error: str | None = None


def _default_data_dir(environ: Mapping[str, str]) -> Path:
    configured = environ.get("FLOPPY_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(__file__).resolve().parent.parent / "db").resolve()


def config_path(
    *,
    environ: Mapping[str, str] | None = None,
    data_dir: str | os.PathLike[str] | None = None,
) -> Path:
    """Return the persisted server-port configuration path."""
    env = os.environ if environ is None else environ
    base = (
        Path(data_dir).expanduser().resolve()
        if data_dir is not None
        else _default_data_dir(env)
    )
    return base / SERVER_PORT_FILENAME


def _invalid_port_message(source: str) -> str:
    return (
        f"{source} must be an integer from {MIN_SERVER_PORT} "
        f"to {MAX_SERVER_PORT}."
    )


def validate_port(value: object, *, source: str = "server port") -> int:
    """Return a validated TCP port."""
    if isinstance(value, bool):
        message = _invalid_port_message(source)
        raise ServerPortError(message)

    text = str(value).strip()
    if not text or not text.isascii() or not text.isdecimal():
        message = _invalid_port_message(source)
        raise ServerPortError(message)

    port = int(text, 10)
    if not MIN_SERVER_PORT <= port <= MAX_SERVER_PORT:
        message = _invalid_port_message(source)
        raise ServerPortError(message)
    return port


def _read_saved_payload(path: Path) -> object:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK

    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError as exc:
        message = f"Cannot read saved server port from {path}: {exc}"
        raise ServerPortError(message) from exc

    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            message = f"Saved server-port configuration is not a regular file: {path}"
            raise ServerPortError(message)
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            try:
                return json.load(handle)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                message = f"Saved server-port configuration is invalid JSON: {path}"
                raise ServerPortError(message) from exc
    finally:
        if fd >= 0:
            os.close(fd)


def load_saved_port(
    *,
    environ: Mapping[str, str] | None = None,
    data_dir: str | os.PathLike[str] | None = None,
) -> int | None:
    """Return the saved port, or None when no saved value exists."""
    path = config_path(environ=environ, data_dir=data_dir)
    payload = _read_saved_payload(path)
    if payload is None:
        return None
    if not isinstance(payload, dict) or "port" not in payload:
        message = f"Saved server-port configuration must contain a 'port' value: {path}"
        raise ServerPortError(message)
    return validate_port(payload["port"], source=f"saved server port in {path}")


def resolve_server_port(
    *,
    environ: Mapping[str, str] | None = None,
    data_dir: str | os.PathLike[str] | None = None,
) -> int:
    """Resolve the effective public port using environment, saved value, then default."""
    env = os.environ if environ is None else environ
    if SERVER_PORT_ENV in env:
        return validate_port(env[SERVER_PORT_ENV], source=SERVER_PORT_ENV)

    saved = load_saved_port(environ=env, data_dir=data_dir)
    return DEFAULT_SERVER_PORT if saved is None else saved


def get_server_port_status(
    *,
    environ: Mapping[str, str] | None = None,
    data_dir: str | os.PathLike[str] | None = None,
) -> ServerPortStatus:
    """Return effective, saved, and environment state for UI and CLI surfaces."""
    env = os.environ if environ is None else environ
    path = config_path(environ=env, data_dir=data_dir)

    environment_port: int | None = None
    if SERVER_PORT_ENV in env:
        environment_port = validate_port(env[SERVER_PORT_ENV], source=SERVER_PORT_ENV)

    saved_port: int | None = None
    saved_error: str | None = None
    try:
        saved_port = load_saved_port(environ=env, data_dir=data_dir)
    except ServerPortError as exc:
        saved_error = str(exc)
        if environment_port is None:
            raise

    if environment_port is not None:
        effective_port = environment_port
        source = "environment"
    elif saved_port is not None:
        effective_port = saved_port
        source = "saved"
    else:
        effective_port = DEFAULT_SERVER_PORT
        source = "default"

    return ServerPortStatus(
        effective_port=effective_port,
        source=source,
        saved_port=saved_port,
        environment_port=environment_port,
        config_path=str(path),
        saved_error=saved_error,
    )


def _write_json_atomically(path: Path, payload: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    fd = -1
    temp_path: str | None = None
    try:
        fd, temp_path = tempfile.mkstemp(
            prefix=f".{path.name}.",
            dir=path.parent,
            text=True,
        )
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)

        # A root-run docker exec should not leave a root-owned file that the
        # app user cannot update later. Match the owning directory where allowed.
        try:
            parent_stat = path.parent.stat()
            os.fchown(fd, parent_stat.st_uid, parent_stat.st_gid)
        except (AttributeError, PermissionError, OSError):
            pass

        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        Path(temp_path).replace(path)
        temp_path = None
    except OSError as exc:
        message = f"Cannot save server port to {path}: {exc}"
        raise ServerPortError(message) from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if temp_path is not None:
            with suppress(FileNotFoundError):
                Path(temp_path).unlink()


def save_server_port(
    value: object,
    *,
    environ: Mapping[str, str] | None = None,
    data_dir: str | os.PathLike[str] | None = None,
) -> int:
    """Persist one validated fallback port."""
    port = validate_port(value)
    _write_json_atomically(
        config_path(environ=environ, data_dir=data_dir),
        {"port": port},
    )
    return port


def clear_saved_port(
    *,
    environ: Mapping[str, str] | None = None,
    data_dir: str | os.PathLike[str] | None = None,
) -> bool:
    """Remove the saved fallback port. Return whether a file was removed."""
    path = config_path(environ=environ, data_dir=data_dir)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        message = f"Cannot remove saved server port at {path}: {exc}"
        raise ServerPortError(message) from exc
    return True


def render_nginx_configs(
    template_path: str | os.PathLike[str],
    ipv4_output_path: str | os.PathLike[str],
    ipv6_output_path: str | os.PathLike[str],
    port: int,
) -> None:
    """Render validated IPv4/IPv6 Nginx configs from the checked-in default."""
    validated = validate_port(port)
    template = Path(template_path)
    try:
        source = template.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        message = f"Cannot read Nginx template {template}: {exc}"
        raise ServerPortError(message) from exc

    if source.count(NGINX_DEFAULT_LISTEN) != 1:
        message = (
            f"Nginx template {template} must contain exactly one "
            f"'{NGINX_DEFAULT_LISTEN}' line."
        )
        raise ServerPortError(message)

    ipv4 = source.replace(NGINX_DEFAULT_LISTEN, f"listen {validated};")
    ipv6 = source.replace(
        NGINX_DEFAULT_LISTEN,
        f"listen {validated};\n    listen [::]:{validated};",
    )

    for output, content in (
        (Path(ipv4_output_path), ipv4),
        (Path(ipv6_output_path), ipv6),
    ):
        try:
            output.write_text(content, encoding="utf-8")
        except OSError as exc:
            message = f"Cannot write Nginx config {output}: {exc}"
            raise ServerPortError(message) from exc


def prepare_runtime(
    template_path: str | os.PathLike[str],
    ipv4_output_path: str | os.PathLike[str],
    ipv6_output_path: str | os.PathLike[str],
    runtime_port_path: str | os.PathLike[str],
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Resolve the port once, render Nginx, and publish the health-check value."""
    port = resolve_server_port(environ=environ)
    render_nginx_configs(template_path, ipv4_output_path, ipv6_output_path, port)

    runtime_path = Path(runtime_port_path)
    try:
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text(f"{port}\n", encoding="ascii")
    except OSError as exc:
        message = f"Cannot write resolved server port to {runtime_path}: {exc}"
        raise ServerPortError(message) from exc
    return port


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read or change Floppy's public HTTP port. "
            f"Precedence is {SERVER_PORT_ENV}, saved value, then {DEFAULT_SERVER_PORT}."
        )
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--set", metavar="PORT", dest="set_port")
    actions.add_argument("--reset", action="store_true")
    actions.add_argument("--value", action="store_true")
    actions.add_argument(
        "--prepare-runtime",
        nargs=4,
        metavar=("NGINX_TEMPLATE", "IPV4_CONFIG", "IPV6_CONFIG", "PORT_FILE"),
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _write_line(stream: TextIO, value: object) -> None:
    stream.write(f"{value}\n")


def _print_status(status: ServerPortStatus, *, stream: TextIO) -> None:
    _write_line(stream, f"Effective port: {status.effective_port}")
    _write_line(stream, f"Source: {status.source}")
    saved = status.saved_port if status.saved_port is not None else "not set"
    _write_line(stream, f"Saved port: {saved}")
    _write_line(stream, f"Config file: {status.config_path}")
    if status.source == "environment":
        _write_line(
            stream,
            f"{SERVER_PORT_ENV} is active and overrides the saved value.",
        )
    if status.saved_error:
        _write_line(stream, f"Saved configuration warning: {status.saved_error}")


def _execute(args: argparse.Namespace) -> int:
    if args.set_port is not None:
        saved = save_server_port(args.set_port)
        status = get_server_port_status()
        if args.as_json:
            _write_line(sys.stdout, json.dumps(asdict(status), sort_keys=True))
        else:
            _write_line(sys.stdout, f"Saved server port: {saved}")
            _print_status(status, stream=sys.stdout)
            if status.source == "environment":
                _write_line(
                    sys.stdout,
                    "The saved value will take effect only after FLOPPY_PORT is removed.",
                )
            else:
                _write_line(sys.stdout, "Restart Floppy to use the saved port.")
        return 0

    if args.reset:
        removed = clear_saved_port()
        status = get_server_port_status()
        if args.as_json:
            output = asdict(status)
            output["saved_value_removed"] = removed
            _write_line(sys.stdout, json.dumps(output, sort_keys=True))
        else:
            message = "Saved server port removed." if removed else "No saved server port."
            _write_line(sys.stdout, message)
            _print_status(status, stream=sys.stdout)
            _write_line(sys.stdout, "Restart Floppy if the effective port changed.")
        return 0

    if args.prepare_runtime:
        port = prepare_runtime(*args.prepare_runtime)
        _write_line(sys.stdout, port)
        return 0

    if args.value:
        _write_line(sys.stdout, resolve_server_port())
        return 0

    status = get_server_port_status()
    if args.as_json:
        _write_line(sys.stdout, json.dumps(asdict(status), sort_keys=True))
    else:
        _print_status(status, stream=sys.stdout)
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point used by operators and the container wrapper."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        exit_code = _execute(args)
    except ServerPortError as exc:
        _write_line(sys.stderr, f"server-port: {exc}")
        return 2
    else:
        return exit_code


if __name__ == "__main__":  # pragma: no cover - exercised through CLI tests
    raise SystemExit(main())
