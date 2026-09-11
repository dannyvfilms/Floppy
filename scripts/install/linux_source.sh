# shellcheck shell=bash
#
# Floppy guided installer - source installation on Debian and Ubuntu.

SERVICE_UNIT="/etc/systemd/system/floppy.service"

source_install_packages() {
    local missing=()
    have curl || missing+=("curl")
    [ -x /usr/sbin/nginx ] || have nginx || missing+=("nginx")
    have redis-server || missing+=("redis-server")

    if [ ${#missing[@]} -eq 0 ]; then
        return 0
    fi

    step "Packages this installation needs"
    say "Missing: ${missing[*]}"
    say "The installer would run, with administrator access:"
    say "  sudo apt-get update && sudo apt-get install -y ${missing[*]}"
    note "Floppy runs its own Redis on a separate port. A Redis already running on this computer is not reconfigured or restarted."
    ask_yes_no "Install these packages?" yes \
        || fail "These packages are required. Install them yourself, then run the installer again."

    confirm_sudo
    run_root apt-get update
    run_root apt-get install -y "${missing[@]}"
}

source_locate_binaries() {
    if [ -x /usr/sbin/nginx ]; then
        NGINX_BIN=/usr/sbin/nginx
    else
        NGINX_BIN=$(command -v nginx || true)
    fi
    [ -n "$NGINX_BIN" ] || fail "Nginx was installed but could not be found."

    REDIS_SERVER=$(command -v redis-server || true)
    [ -n "$REDIS_SERVER" ] || fail "redis-server was installed but could not be found."

    NGINX_MIME_TYPES=/etc/nginx/mime.types
    [ -r "$NGINX_MIME_TYPES" ] || fail "$NGINX_MIME_TYPES is missing; the nginx package is incomplete."
}

source_register_service() {
    local unit_temp="$RUN_DIR/floppy.service"
    render_template "$TEMPLATE_DIR/floppy.service.tmpl" "$unit_temp" \
        "RUN_USER=$(id -un)" \
        "RUN_GROUP=$(id -gn)" \
        "SRC_DIR=$SRC_DIR" \
        "RUN_DIR=$RUN_DIR"

    say "Floppy will be registered as a systemd service so it survives a reboot."
    say "The installer would run, with administrator access:"
    say "  sudo install -m 0644 \"$unit_temp\" $SERVICE_UNIT"
    say "  sudo systemctl daemon-reload && sudo systemctl enable --now floppy"
    ask_yes_no "Register and start the Floppy service?" yes \
        || fail "Floppy is installed but not registered. Run the installer again to finish, or start it manually with \"$RUN_DIR/floppy-supervisord\"."

    confirm_sudo
    run_root install -m 0644 "$unit_temp" "$SERVICE_UNIT"
    run_root systemctl daemon-reload
    run_root systemctl enable --now floppy || fail "systemd could not start Floppy. Run 'sudo journalctl -u floppy -n 50' to see why."
}

floppy_commands_help() {
    cat <<EOF
  Start:   sudo systemctl start floppy
  Stop:    sudo systemctl stop floppy
  Status:  sudo systemctl status floppy
  Logs:    tail -f "$LOG_DIR/gunicorn.log"   (and the other files in that directory)
  Resume:  bash "$REPO_DIR/scripts/install/main.sh"
  Upgrade: git -C "$REPO_DIR" pull && "$UV" sync --locked --no-default-groups \\
             && sudo systemctl restart floppy
EOF
}
