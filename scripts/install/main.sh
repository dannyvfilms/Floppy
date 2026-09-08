#!/usr/bin/env bash
#
# Floppy guided installer - dispatcher.
#
# Invoked by scripts/install.sh from the cloned repository with FLOPPY_ROOT
# already set and pointing at a directory containing repo/.

set -euo pipefail

FLOPPY_ROOT=${FLOPPY_ROOT:?FLOPPY_ROOT must be set by the bootstrap}
INSTALL_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "$INSTALL_DIR/../.." && pwd)
TEMPLATE_DIR="$INSTALL_DIR/templates"

# shellcheck source=scripts/install/common.sh
. "$INSTALL_DIR/common.sh"

detect_platform

# Persistent layout. Runtime data lives beside the checkout, never inside it,
# so replacing the application can never touch the database.
DATA_DIR="$FLOPPY_ROOT/db"
BACKUP_DIR="$FLOPPY_ROOT/backups"
LOG_DIR="$FLOPPY_ROOT/logs"
REDIS_DIR="$FLOPPY_ROOT/redis"
ENV_FILE="$FLOPPY_ROOT/floppy.env"
mkdir -p "$DATA_DIR" "$BACKUP_DIR" "$LOG_DIR" "$REDIS_DIR"

# Loads the functions one method implements: install, manage, restart,
# diagnostics, and the maintenance commands printed at the end.
load_method() {
    case $1 in
        docker)
            # shellcheck source=scripts/install/docker.sh
            . "$INSTALL_DIR/docker.sh"
            ;;
        source)
            # shellcheck source=scripts/install/source_common.sh
            . "$INSTALL_DIR/source_common.sh"
            if [ "$FLOPPY_OS" = "Darwin" ]; then
                # shellcheck source=scripts/install/macos_source.sh
                . "$INSTALL_DIR/macos_source.sh"
            else
                # shellcheck source=scripts/install/linux_source.sh
                . "$INSTALL_DIR/linux_source.sh"
            fi
            ;;
        *) fail "Unknown installation method: $1" ;;
    esac
}

set_bind_address() {
    case $ACCESS in
        desktop) BIND_ADDRESS="127.0.0.1" ;;
        *) BIND_ADDRESS="0.0.0.0" ;;
    esac
}

# ---------------------------------------------------------------------------
# Resume an existing installation, or configure a new one
# ---------------------------------------------------------------------------

EXISTING_METHOD=$(state_get METHOD || true)
if [ -n "$EXISTING_METHOD" ]; then
    METHOD=$EXISTING_METHOD
    PORT=$(state_get PORT)
    ACCESS=$(state_get ACCESS)
    FLOPPY_TZ=$(state_get TZ)
    set_bind_address
    load_method "$METHOD"

    step "Existing installation"
    say "  Method:   $METHOD"
    say "  Port:     $PORT"
    say "  Access:   $ACCESS"
    note "The installation method of an existing installation is never changed."

    ask_choice RESUME_ACTION "What would you like to do?" start \
        "start|Start Floppy and finish setup|Uses the configuration already on disk." \
        "owner|Finish owner setup only|Promote an account you have already created." \
        "quit|Do nothing|Leave everything as it is."

    case $RESUME_ACTION in
        quit)
            say "Nothing was changed."
            exit 0
            ;;
        owner)
            # shellcheck source=scripts/install/finish.sh
            . "$INSTALL_DIR/finish.sh"
            finish_owner_setup
            finish_summary
            exit 0
            ;;
    esac
else
    # -----------------------------------------------------------------------
    # 1. How to install
    # -----------------------------------------------------------------------
    step "How should Floppy run?"

    docker_status=$(docker_state)
    if platform_supports_source; then
        source_note="Installs Python, Redis, and Nginx on this computer directly."
    else
        source_note="Not automated on this system; the installer will say what is missing."
    fi

    ask_choice METHOD "There are two ways to run Floppy:" docker \
        "docker|Docker - recommended|Runs Floppy in containers, so nothing else on this computer changes. Docker here: ${docker_status}." \
        "source|Directly on this computer|${source_note}"

    if [ "$METHOD" = "source" ] && ! platform_supports_source; then
        say ""
        say "A direct installation is automated on macOS, and on Debian or Ubuntu with systemd."
        say "This host reports: ${FLOPPY_DISTRO:-$FLOPPY_OS} (package manager: ${FLOPPY_PKG:-none}, service manager: ${FLOPPY_SERVICE_MGR:-none})."
        say "Choose Docker instead, or follow the manual source instructions in README.md."
        exit 1
    fi

    if [ "$METHOD" = "docker" ]; then
        case $docker_status in
            missing)
                if [ "$FLOPPY_OS" = "Darwin" ]; then
                    fail "Docker is not installed. Install Docker Desktop from https://www.docker.com/products/docker-desktop/, start it, then run this installer again."
                fi
                case "$FLOPPY_DISTRO" in
                    ubuntu|debian) : ;;
                    *) fail "Docker is not installed, and automatic installation is only supported on Debian and Ubuntu (this host reports '${FLOPPY_DISTRO:-unknown}'). Install Docker Engine and the Compose plugin, then run this installer again." ;;
                esac
                ;;
            stopped)
                if [ "$FLOPPY_OS" = "Darwin" ]; then
                    fail "Docker is installed but not running. Start Docker Desktop, wait for it to report Running, then run this installer again."
                fi
                fail "Docker is installed but not responding. Start it (for example 'sudo systemctl start docker'), then run this installer again."
                ;;
            no-permission)
                fail "Docker is installed but $(id -un) may not talk to it. Run 'sudo usermod -aG docker $(id -un)', log out and back in, then run this installer again."
                ;;
            no-compose)
                fail "Docker is installed without the Compose plugin. Install docker-compose-plugin, then run this installer again."
                ;;
        esac
    fi

    # -----------------------------------------------------------------------
    # 2. Where it is reached
    # -----------------------------------------------------------------------
    step "Who should be able to open Floppy?"

    ask_choice ACCESS "Access:" lan \
        "lan|Other devices on this network|Phones, tablets, and TVs on the same network can open Floppy." \
        "desktop|Only this computer|Floppy answers on 127.0.0.1 and nowhere else."

    default_port=$(first_free_port 8000)
    while :; do
        ask PORT "Port to serve Floppy on" "$default_port"
        case $PORT in
            ''|*[!0-9]*) say "Enter a port number."; continue ;;
        esac
        if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
            say "Ports run from 1 to 65535."
            continue
        fi
        if port_in_use "$PORT"; then
            say "Port $PORT is already in use by something else on this computer."
            continue
        fi
        break
    done

    ask FLOPPY_TZ "Time zone" "$(detect_timezone)"

    set_bind_address

    # -----------------------------------------------------------------------
    # 3. Say what will happen before anything on this computer changes
    # -----------------------------------------------------------------------
    step "What will happen"
    if [ "$METHOD" = "docker" ]; then
        say "  Floppy runs in Docker containers, using the published stable image."
    else
        say "  Floppy runs directly on this computer, under ${FLOPPY_SERVICE_MGR}."
        say "  Python, Redis, and Nginx are installed for it."
    fi
    say "  Location:   $FLOPPY_ROOT"
    say "  Address:    http://${BIND_ADDRESS}:${PORT}"
    say "  Time zone:  $FLOPPY_TZ"
    say ""
    say "Every change to this computer - packages, services, administrator access -"
    say "is listed and confirmed before it happens. Nothing is installed silently."
    ask_yes_no "Continue?" yes || { say "Nothing was changed."; exit 0; }

    load_method "$METHOD"

    state_set ROOT "$FLOPPY_ROOT"
    state_set METHOD "$METHOD"
    state_set ACCESS "$ACCESS"
    state_set PORT "$PORT"
    state_set TZ "$FLOPPY_TZ"
    state_set BRANCH "${FLOPPY_REPO_BRANCH:-release}"
fi

# ---------------------------------------------------------------------------
# Install and start
# ---------------------------------------------------------------------------

case $METHOD in
    docker) install_docker ;;
    source) install_source ;;
esac

state_set INSTALLED 1

# shellcheck source=scripts/install/finish.sh
. "$INSTALL_DIR/finish.sh"
finish_startup
finish_owner_setup
finish_optional_configuration
finish_summary
