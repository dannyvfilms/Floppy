# shellcheck shell=bash
#
# Floppy guided installer - source installation on macOS.

LAUNCH_DAEMON="/Library/LaunchDaemons/com.floppy.app.plist"

_brew() {
    if have brew; then
        command -v brew
    elif [ -x /opt/homebrew/bin/brew ]; then
        printf '%s' /opt/homebrew/bin/brew
    elif [ -x /usr/local/bin/brew ]; then
        printf '%s' /usr/local/bin/brew
    fi
}

source_install_packages() {
    BREW=$(_brew)
    if [ -z "$BREW" ]; then
        step "Homebrew is needed"
        say "A direct installation on macOS uses Homebrew to install Redis and Nginx."
        say "Install it with the official command from https://brew.sh, then run this installer again:"
        say ""
        say '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
        say ""
        fail "Homebrew is not installed."
    fi

    BREW_PREFIX=$("$BREW" --prefix)
    local missing=()
    [ -x "$BREW_PREFIX/bin/redis-server" ] || missing+=("redis")
    [ -x "$BREW_PREFIX/bin/nginx" ] || missing+=("nginx")

    if [ ${#missing[@]} -eq 0 ]; then
        return 0
    fi

    step "Packages this installation needs"
    say "Missing: ${missing[*]}"
    say "The installer would run:"
    say "  $BREW install ${missing[*]}"
    note "Floppy runs its own Redis on a separate port. A Redis already running on this Mac is not reconfigured or restarted."
    ask_yes_no "Install these packages?" yes \
        || fail "These packages are required. Install them yourself, then run the installer again."

    "$BREW" install "${missing[@]}" || fail "Homebrew could not install ${missing[*]}."
}

source_locate_binaries() {
    BREW=${BREW:-$(_brew)}
    BREW_PREFIX=${BREW_PREFIX:-$("$BREW" --prefix)}
    NGINX_BIN="$BREW_PREFIX/bin/nginx"
    REDIS_SERVER="$BREW_PREFIX/bin/redis-server"
    NGINX_MIME_TYPES="$BREW_PREFIX/etc/nginx/mime.types"
    [ -x "$NGINX_BIN" ] || fail "Nginx was not found at $NGINX_BIN."
    [ -x "$REDIS_SERVER" ] || fail "redis-server was not found at $REDIS_SERVER."
    [ -r "$NGINX_MIME_TYPES" ] || fail "$NGINX_MIME_TYPES is missing; the nginx formula is incomplete."
}

source_register_service() {
    local plist_temp="$RUN_DIR/com.floppy.app.plist"
    render_template "$TEMPLATE_DIR/com.floppy.app.plist.tmpl" "$plist_temp" \
        "RUN_USER=$(id -un)" \
        "RUN_GROUP=$(id -gn)" \
        "SRC_DIR=$SRC_DIR" \
        "RUN_DIR=$RUN_DIR" \
        "LOG_DIR=$LOG_DIR" \
        "VENV_DIR=$VENV_DIR" \
        "EXTRA_PATH=$BREW_PREFIX/bin"

    say "Floppy will be registered as a launchd daemon so it survives a reboot."
    say "The installer would run, with administrator access:"
    say "  sudo install -m 0644 -o root -g wheel \"$plist_temp\" $LAUNCH_DAEMON"
    say "  sudo launchctl bootstrap system $LAUNCH_DAEMON"
    ask_yes_no "Register and start the Floppy service?" yes \
        || fail "Floppy is installed but not registered. Run the installer again to finish, or start it manually with \"$RUN_DIR/floppy-supervisord\"."

    confirm_sudo
    run_root install -m 0644 -o root -g wheel "$plist_temp" "$LAUNCH_DAEMON"
    # bootout first so a rerun re-reads a changed plist instead of failing.
    run_root launchctl bootout system "$LAUNCH_DAEMON" >/dev/null 2>&1 || true
    run_root launchctl bootstrap system "$LAUNCH_DAEMON" \
        || fail "launchd could not start Floppy. Check $LOG_DIR/launchd.err.log."
}

floppy_commands_help() {
    cat <<EOF
  Start:   sudo launchctl bootstrap system $LAUNCH_DAEMON
  Stop:    sudo launchctl bootout system $LAUNCH_DAEMON
  Status:  sudo launchctl print system/com.floppy.app | head -n 20
  Logs:    tail -f "$LOG_DIR/gunicorn.log"   (and the other files in that directory)
  Resume:  bash "$REPO_DIR/scripts/install/main.sh"
  Upgrade: git -C "$REPO_DIR" pull && "$UV" sync --locked --no-default-groups \\
             && sudo launchctl kickstart -k system/com.floppy.app
EOF
}
