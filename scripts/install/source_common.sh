# shellcheck shell=bash
#
# Floppy guided installer - shared source-installation steps.
#
# The per-OS files (linux_source.sh, macos_source.sh) supply
# source_install_packages, source_locate_binaries, and source_register_service.
# Everything below is genuinely identical between the two.

RUN_DIR="$FLOPPY_ROOT/run"
VENV_DIR="$REPO_DIR/.venv"
SRC_DIR="$REPO_DIR/src"
STATIC_ROOT="$SRC_DIR/staticfiles"
UV_BIN_DIR="$FLOPPY_ROOT/bin"
UV="$UV_BIN_DIR/uv"

# Pinned to the version pyproject.toml requires, so the installer cannot pull a
# uv that refuses to run in this repository.
UV_VERSION=${FLOPPY_UV_VERSION:-0.12.3}

_source_ensure_uv() {
    if [ -x "$UV" ] && [ "$("$UV" --version 2>/dev/null | awk '{print $2}')" = "$UV_VERSION" ]; then
        return 0
    fi
    if have uv && [ "$(uv --version 2>/dev/null | awk '{print $2}')" = "$UV_VERSION" ]; then
        UV=$(command -v uv)
        return 0
    fi
    step "Installing uv $UV_VERSION"
    note "uv installs the Python version Floppy needs without touching the system Python."
    mkdir -p "$UV_BIN_DIR"
    curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" \
        | env UV_INSTALL_DIR="$UV_BIN_DIR" UV_UNMANAGED_INSTALL="$UV_BIN_DIR" INSTALLER_NO_MODIFY_PATH=1 sh \
        || fail "Could not install uv. Check the network connection and try again."
    [ -x "$UV" ] || fail "uv was not installed at $UV."
}

_source_build_environment() {
    step "Installing Python and Floppy's dependencies"
    note "This takes a few minutes on a first installation."
    ( cd "$REPO_DIR" && "$UV" python install ) || fail "Could not install the Python version Floppy needs."
    ( cd "$REPO_DIR" && "$UV" sync --locked --no-default-groups ) \
        || fail "Dependency installation failed. The output above says which package could not be built."
    [ -x "$VENV_DIR/bin/python" ] || fail "Expected a virtual environment at $VENV_DIR."
}

_source_generate_secret() {
    local secret_path="$DATA_DIR/secret_key"
    if [ -s "$secret_path" ]; then
        note "Keeping the existing secret key."
        return 0
    fi
    # Same generation the container uses, written where only the owner can read
    # it, and referenced from the configuration by path so it is never printed.
    ( umask 077; "$VENV_DIR/bin/python" -c \
        'import pathlib, secrets, sys; pathlib.Path(sys.argv[1]).write_text(secrets.token_urlsafe(50))' \
        "$secret_path" ) || fail "Could not create the secret key at $secret_path."
    chmod 600 "$secret_path"
}

_source_write_env() {
    if [ -f "$ENV_FILE" ]; then
        note "Keeping the existing configuration at $ENV_FILE."
        return 0
    fi
    # Sourced by the service wrapper with 'set -a', so every value is quoted:
    # installation paths may contain spaces.
    write_private "$ENV_FILE" <<EOF
# Floppy installation settings. Edit, then restart Floppy.
TZ='$FLOPPY_TZ'
DEBUG='False'
ADMIN_ENABLED='False'
DEMO_ACCOUNT_ENABLED='False'
REGISTRATION='True'
ALLOWED_HOSTS='*'
SECRET_FILE='$DATA_DIR/secret_key'
FLOPPY_DATA_DIR='$DATA_DIR'
BACKUP_DIR='$BACKUP_DIR'
LOG_DIR='$LOG_DIR'
REDIS_URL='redis://127.0.0.1:$REDIS_PORT'
PYTHONPATH='$SRC_DIR'
DJANGO_SETTINGS_MODULE='config.settings'
EOF
    say "  $ENV_FILE"
}

_source_render_runtime() {
    step "Writing the service configuration"
    mkdir -p "$RUN_DIR"
    chmod 700 "$RUN_DIR"

    render_template "$TEMPLATE_DIR/redis.conf.tmpl" "$RUN_DIR/redis.conf" \
        "REDIS_PORT=$REDIS_PORT" \
        "REDIS_DIR=$REDIS_DIR"

    render_template "$TEMPLATE_DIR/nginx.install.conf.tmpl" "$RUN_DIR/nginx.conf" \
        "RUN_DIR=$RUN_DIR" \
        "LOG_DIR=$LOG_DIR" \
        "MIME_TYPES=$NGINX_MIME_TYPES" \
        "STATIC_ROOT=$STATIC_ROOT" \
        "BIND=$BIND_ADDRESS" \
        "PORT=$PORT"

    render_template "$TEMPLATE_DIR/supervisord.install.conf.tmpl" "$RUN_DIR/supervisord.conf" \
        "RUN_DIR=$RUN_DIR" \
        "LOG_DIR=$LOG_DIR" \
        "REDIS_DIR=$REDIS_DIR" \
        "REDIS_SERVER=$REDIS_SERVER" \
        "NGINX=$NGINX_BIN" \
        "SRC_DIR=$SRC_DIR" \
        "VENV_DIR=$VENV_DIR"

    render_template "$TEMPLATE_DIR/floppy-supervisord.tmpl" "$RUN_DIR/floppy-supervisord" \
        "ENV_FILE=$ENV_FILE" \
        "VENV_DIR=$VENV_DIR" \
        "SRC_DIR=$SRC_DIR" \
        "RUN_DIR=$RUN_DIR" \
        "LOG_DIR=$LOG_DIR"
    chmod 755 "$RUN_DIR/floppy-supervisord"

    say "  $RUN_DIR"

    "$NGINX_BIN" -t -c "$RUN_DIR/nginx.conf" -p "$RUN_DIR" >/dev/null 2>&1 \
        || warn "Nginx reported a problem with $RUN_DIR/nginx.conf. Run: $NGINX_BIN -t -c \"$RUN_DIR/nginx.conf\" -p \"$RUN_DIR\""
}

_source_prepare_django() {
    step "Preparing the database and static files"
    floppy_manage collectstatic --noinput >/dev/null || fail "Collecting static files failed."
    floppy_manage migrate --noinput || fail "Database migrations failed."
}

install_source() {
    # A dedicated loopback Redis, so a Redis already on this computer is never
    # reconfigured, restarted, or shared.
    REDIS_PORT=$(state_get REDIS_PORT || true)
    [ -n "$REDIS_PORT" ] || REDIS_PORT=$(first_free_port 6479)
    state_set REDIS_PORT "$REDIS_PORT"

    source_install_packages
    source_locate_binaries
    _source_ensure_uv
    _source_build_environment
    _source_generate_secret
    _source_write_env
    _source_render_runtime
    _source_prepare_django

    step "Registering Floppy with this computer's service manager"
    source_register_service
}

# --- interface used by finish.sh -------------------------------------------

floppy_manage() {
    (
        set -a
        # shellcheck disable=SC1090
        . "$ENV_FILE"
        set +a
        cd "$SRC_DIR" || exit 1
        "$VENV_DIR/bin/python" manage.py "$@"
    )
}

supervisorctl_() {
    "$VENV_DIR/bin/supervisorctl" -c "$RUN_DIR/supervisord.conf" "$@"
}

floppy_restart_app() {
    supervisorctl_ restart gunicorn celery celery-interactive celery-discover >/dev/null 2>&1 || true
}

floppy_diagnostics() {
    say "Process status:"
    supervisorctl_ status 2>&1 | tail -c 2000 || true
    say ""
    say "Last 40 lines from Gunicorn:"
    tail -n 40 "$LOG_DIR/gunicorn.log" 2>/dev/null | tail -c 6000 || true
    say ""
    say "Last 20 lines from Nginx:"
    tail -n 20 "$LOG_DIR/nginx-error.log" 2>/dev/null | tail -c 2000 || true
}
