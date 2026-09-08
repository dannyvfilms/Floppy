# shellcheck shell=bash
#
# Floppy guided installer - Docker installation.
#
# Reuses the published stable image and the app-plus-Redis architecture the
# documented Compose stack already describes. Cloning the repository does not
# cause a local image build.

COMPOSE_FILE="$FLOPPY_ROOT/docker-compose.yml"

# Compose project name for this installation only. Derived from the
# installation directory and then pinned in the generated Compose file, so an
# existing Floppy stack on the same host is never adopted or replaced.
compose_project_name() {
    local name
    name=$(basename -- "$FLOPPY_ROOT" \
        | tr '[:upper:]' '[:lower:]' \
        | tr -c 'a-z0-9_-' '-' \
        | sed 's/-\{1,\}/-/g; s/^-//; s/-$//')
    printf 'floppy-%s' "${name:-install}"
}

compose() {
    docker compose --project-directory "$FLOPPY_ROOT" -f "$COMPOSE_FILE" "$@"
}

_docker_install_engine_apt() {
    step "Installing Docker"
    say "Docker is not installed. The installer would run, with administrator access:"
    say "  apt-get install ca-certificates curl"
    say "  install the official Docker package signing key into /etc/apt/keyrings"
    say "  add https://download.docker.com/linux/${FLOPPY_DISTRO} to /etc/apt/sources.list.d"
    say "  apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin"
    say "  usermod -aG docker $(id -un)"
    ask_yes_no "Install Docker from the official Docker package repository?" yes \
        || fail "Docker is required for this installation method. Install it yourself, then run the installer again."

    confirm_sudo
    run_root apt-get update
    run_root apt-get install -y ca-certificates curl
    run_root install -m 0755 -d /etc/apt/keyrings
    curl -fsSL "https://download.docker.com/linux/${FLOPPY_DISTRO}/gpg" \
        | run_root tee /etc/apt/keyrings/docker.asc >/dev/null \
        || fail "Could not download the Docker package signing key."
    run_root chmod a+r /etc/apt/keyrings/docker.asc
    printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/%s %s stable\n' \
        "$(dpkg --print-architecture)" \
        "$FLOPPY_DISTRO" \
        "$(. /etc/os-release && printf '%s' "${VERSION_CODENAME:-${UBUNTU_CODENAME:-}}")" \
        | run_root tee /etc/apt/sources.list.d/docker.list >/dev/null
    run_root apt-get update
    run_root apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    run_root systemctl enable --now docker

    if ! docker info >/dev/null 2>&1; then
        run_root usermod -aG docker "$(id -un)" || true
        say ""
        say "Docker is installed, but group membership only takes effect in a new login session."
        say "Log out and back in (or run 'newgrp docker'), then run the installer again to continue."
        say "Nothing else was changed; the installer will resume from here."
        exit 0
    fi
}

# An existing Compose file keeps whatever image tag it was generated with
# forever (see the "Keeping the existing" branch below - regenerating the
# whole file on every run would silently discard a hand customization, like
# an extra volume). That is right for a real customization, but it also means
# common.sh moving its FLOPPY_IMAGE default forward - as happened live, when
# :release turned out to predate promote_superuser - never reaches an
# installation that already exists: every future resume just keeps pulling
# the stale tag baked into that first run. Bring only this one line forward,
# leaving the rest of a possibly-customized file untouched.
_docker_update_image_tag() {
    local current wanted tmp
    current=$(grep -m1 '^    image: ghcr\.io/dannyvfilms/floppy:' "$COMPOSE_FILE" || true)
    [ -n "$current" ] || return 0
    wanted="    image: $FLOPPY_IMAGE"
    [ "$current" = "$wanted" ] && return 0
    tmp="${COMPOSE_FILE}.tmp.$$"
    sed "s|^    image: ghcr\.io/dannyvfilms/floppy:.*\$|$wanted|" "$COMPOSE_FILE" >"$tmp" \
        && mv "$tmp" "$COMPOSE_FILE"
    say "  Updated the image tag: ${current#*image: } -> $FLOPPY_IMAGE"
}

install_docker() {
    if [ "$(docker_state)" = "missing" ]; then
        _docker_install_engine_apt
    fi
    [ "$(docker_state)" = "ready" ] || fail "Docker is not usable yet ($(docker_state)). Fix that, then run the installer again."

    step "Writing the installation's configuration"

    if [ -f "$ENV_FILE" ]; then
        note "Keeping the existing configuration at $ENV_FILE."
    else
        # Compose reads env_file literally, so no quoting here - and no paths,
        # which live in the Compose file where they can be quoted.
        write_private "$ENV_FILE" <<EOF
# Floppy installation settings. Edit, then run:
#   docker compose -f "$COMPOSE_FILE" up -d
TZ=$FLOPPY_TZ
REDIS_URL=redis://redis:6379
DEBUG=False
ADMIN_ENABLED=False
DEMO_ACCOUNT_ENABLED=False
REGISTRATION=True
PUID=$(id -u)
PGID=$(id -g)
EOF
        say "  $ENV_FILE"
    fi

    if [ -f "$COMPOSE_FILE" ]; then
        note "Keeping the existing $COMPOSE_FILE."
        _docker_update_image_tag
    else
        render_template "$TEMPLATE_DIR/docker-compose.install.yml.tmpl" "$COMPOSE_FILE" \
            "ROOT=$FLOPPY_ROOT" \
            "IMAGE=$FLOPPY_IMAGE" \
            "ENV_FILE=$ENV_FILE" \
            "DATA_DIR=$DATA_DIR" \
            "BACKUP_DIR=$BACKUP_DIR" \
            "REDIS_DIR=$REDIS_DIR" \
            "BIND=$BIND_ADDRESS" \
            "PORT=$PORT" \
            "PROJECT=$(compose_project_name)"
        say "  $COMPOSE_FILE"
    fi

    compose config >/dev/null || fail "The generated Compose file is not valid. It is at $COMPOSE_FILE."

    step "Downloading Floppy's image"
    compose pull || fail "Could not download $FLOPPY_IMAGE. Check the network connection and try again."

    step "Starting Floppy"
    compose up -d || fail "Floppy could not be started. Run 'docker compose -f \"$COMPOSE_FILE\" logs' to see why."

    state_set COMPOSE_FILE "$COMPOSE_FILE"
}

# --- interface used by finish.sh -------------------------------------------

floppy_manage() {
    compose exec -T floppy python manage.py "$@"
}

floppy_restart_app() {
    compose up -d floppy >/dev/null
}

floppy_diagnostics() {
    say "Last 40 lines from Floppy:"
    compose logs --tail 40 floppy 2>&1 | tail -c 6000 || true
    say ""
    say "Container status:"
    compose ps 2>&1 | tail -c 2000 || true
}

floppy_commands_help() {
    cat <<EOF
  Start:   docker compose -f "$COMPOSE_FILE" up -d
  Stop:    docker compose -f "$COMPOSE_FILE" down
  Status:  docker compose -f "$COMPOSE_FILE" ps
  Logs:    docker compose -f "$COMPOSE_FILE" logs -f
  Resume:  bash "$REPO_DIR/scripts/install/main.sh"
  Upgrade: docker compose -f "$COMPOSE_FILE" pull && docker compose -f "$COMPOSE_FILE" up -d
EOF
}
