# shellcheck shell=bash
#
# Shared helpers for the Floppy guided installer.
#
# Sourced by scripts/install/main.sh and the per-method implementation files.
# The bootstrap (scripts/install.sh) deliberately does NOT source this: it runs
# before the repository exists and carries its own minimal prompt helper.

FLOPPY_REPO_URL=${FLOPPY_REPO_URL:-https://github.com/dannyvfilms/Floppy.git}
# TODO: point both back at "release" once a release cuts these forward onto
# that branch. Today only "latest" (and its :latest image) carries the
# installer and the commands it runs, e.g. promote_superuser - the :release
# image predates it and fails with "Unknown command".
FLOPPY_REPO_BRANCH=${FLOPPY_REPO_BRANCH:-latest}
FLOPPY_IMAGE=${FLOPPY_IMAGE:-ghcr.io/dannyvfilms/floppy:latest}

# Readiness bound shared by every method (five minutes, per the install spec).
FLOPPY_READY_TIMEOUT=${FLOPPY_READY_TIMEOUT:-300}

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    _c_bold=$(printf '\033[1m')
    _c_dim=$(printf '\033[2m')
    _c_red=$(printf '\033[31m')
    _c_yellow=$(printf '\033[33m')
    _c_off=$(printf '\033[0m')
else
    _c_bold=""; _c_dim=""; _c_red=""; _c_yellow=""; _c_off=""
fi

say() { printf '%s\n' "$*"; }
step() { printf '\n%s==> %s%s\n' "$_c_bold" "$*" "$_c_off"; }
note() { printf '%s    %s%s\n' "$_c_dim" "$*" "$_c_off"; }
warn() { printf '%sWarning: %s%s\n' "$_c_yellow" "$*" "$_c_off" >&2; }
fail() { printf '%sError: %s%s\n' "$_c_red" "$*" "$_c_off" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
# Prompting
#
# Read answers from the controlling terminal rather than stdin: the documented
# install command pipes the bootstrap through a file, but a user who pipes it
# straight into a shell would otherwise have every prompt consume script text.
# ---------------------------------------------------------------------------

FLOPPY_ASSUME_YES=${FLOPPY_ASSUME_YES:-0}

_tty_read() {
    # $1 = variable name, rest = prompt
    #
    # The local below must not be named the same as any caller's own local
    # (e.g. ask()'s "__reply") - printf -v resolves to the nearest local of
    # that name, so a same-named local here would silently shadow it and the
    # caller would keep reading an empty string forever.
    local __var=$1
    shift
    local __input=""
    printf '%s' "$*" >&2
    if [ "$FLOPPY_ASSUME_YES" = "1" ] || [ ! -r /dev/tty ]; then
        printf '\n' >&2
        printf -v "$__var" '%s' ""
        return 0
    fi
    IFS= read -r __input </dev/tty || __input=""
    printf -v "$__var" '%s' "$__input"
}

# ask VAR "Question" "default"
ask() {
    local __var=$1 __question=$2 __default=${3:-} __reply=""
    if [ -n "$__default" ]; then
        _tty_read __reply "$__question [$__default]: "
    else
        _tty_read __reply "$__question: "
    fi
    [ -n "$__reply" ] || __reply=$__default
    printf -v "$__var" '%s' "$__reply"
}

# ask_yes_no "Question" "yes|no"  -> returns 0 for yes
ask_yes_no() {
    local question=$1 default=${2:-yes} reply="" hint
    case $default in
        yes) hint="Y/n" ;;
        *) hint="y/N" ;;
    esac
    while :; do
        _tty_read reply "$question [$hint]: "
        [ -n "$reply" ] || reply=$default
        case $reply in
            y|Y|yes|Yes|YES) return 0 ;;
            n|N|no|No|NO) return 1 ;;
            *) say "Please answer yes or no." ;;
        esac
    done
}

# ask_choice VAR "Question" "default_value" "value|Label|One line of help" ...
ask_choice() {
    local __var=$1 __question=$2 __default=$3
    shift 3
    local __entries=("$@")
    local __index=1 __entry __value __label __help __reply="" __chosen=""

    say ""
    say "$__question"
    for __entry in "${__entries[@]}"; do
        __value=${__entry%%|*}
        __label=${__entry#*|}
        __help=${__label#*|}
        __label=${__label%%|*}
        [ "$__help" = "$__label" ] && __help=""
        if [ "$__value" = "$__default" ]; then
            say "  $__index) $__label (default)"
        else
            say "  $__index) $__label"
        fi
        [ -n "$__help" ] && note "$__help"
        __index=$((__index + 1))
    done

    while :; do
        _tty_read __reply "Choose 1-${#__entries[@]} [$__default]: "
        if [ -z "$__reply" ]; then
            __chosen=$__default
            break
        fi
        case $__reply in
            ''|*[!0-9]*) ;;
            *)
                if [ "$__reply" -ge 1 ] && [ "$__reply" -le "${#__entries[@]}" ]; then
                    __entry=${__entries[$((__reply - 1))]}
                    __chosen=${__entry%%|*}
                    break
                fi
                ;;
        esac
        # Accept the value itself too, so a documented answer keeps working.
        for __entry in "${__entries[@]}"; do
            if [ "${__entry%%|*}" = "$__reply" ]; then
                __chosen=$__reply
                break 2
            fi
        done
        say "Pick a number between 1 and ${#__entries[@]}."
    done
    printf -v "$__var" '%s' "$__chosen"
}

# ---------------------------------------------------------------------------
# Host detection
# ---------------------------------------------------------------------------

detect_platform() {
    FLOPPY_OS=$(uname -s)
    FLOPPY_ARCH=$(uname -m)
    FLOPPY_DISTRO=""
    FLOPPY_DISTRO_LIKE=""
    FLOPPY_PKG=""
    FLOPPY_SERVICE_MGR=""
    FLOPPY_IS_WSL=0

    case $FLOPPY_OS in
        Darwin)
            FLOPPY_DISTRO="macos"
            FLOPPY_PKG="brew"
            FLOPPY_SERVICE_MGR="launchd"
            ;;
        Linux)
            if [ -r /etc/os-release ]; then
                # shellcheck disable=SC1091
                FLOPPY_DISTRO=$(. /etc/os-release; printf '%s' "${ID:-}")
                FLOPPY_DISTRO_LIKE=$(. /etc/os-release; printf '%s' "${ID_LIKE:-}")
            fi
            if have apt-get; then
                FLOPPY_PKG="apt"
            elif have dnf; then
                FLOPPY_PKG="dnf"
            elif have pacman; then
                FLOPPY_PKG="pacman"
            fi
            if have systemctl && [ -d /run/systemd/system ]; then
                FLOPPY_SERVICE_MGR="systemd"
            fi
            case $(uname -r) in
                *icrosoft*|*WSL*) FLOPPY_IS_WSL=1 ;;
            esac
            ;;
    esac
}

# True when this host is one the source installer automates end to end.
platform_supports_source() {
    case $FLOPPY_OS in
        Darwin) return 0 ;;
        Linux)
            [ "$FLOPPY_PKG" = "apt" ] && [ "$FLOPPY_SERVICE_MGR" = "systemd" ] && return 0
            return 1
            ;;
    esac
    return 1
}

docker_state() {
    # Prints one of: ready, stopped, missing, no-compose, no-permission
    if ! have docker; then
        printf 'missing'
        return
    fi
    if ! docker info >/dev/null 2>&1; then
        if docker info 2>&1 | grep -qi 'permission denied'; then
            printf 'no-permission'
        else
            printf 'stopped'
        fi
        return
    fi
    if ! docker compose version >/dev/null 2>&1; then
        printf 'no-compose'
        return
    fi
    printf 'ready'
}

detect_timezone() {
    local tz=""
    if [ -n "${TZ:-}" ]; then
        tz=$TZ
    elif have timedatectl; then
        tz=$(timedatectl show --property=Timezone --value 2>/dev/null || true)
    fi
    if [ -z "$tz" ] && [ -L /etc/localtime ]; then
        tz=$(readlink /etc/localtime 2>/dev/null | sed -n 's#.*/zoneinfo/##p')
    fi
    if [ -z "$tz" ] && [ -r /etc/timezone ]; then
        tz=$(cat /etc/timezone)
    fi
    printf '%s' "${tz:-UTC}"
}

# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------

port_in_use() {
    local port=$1
    if have lsof; then
        lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 && return 0
        return 1
    fi
    if have ss; then
        ss -lnt 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}\$" && return 0
        return 1
    fi
    if have nc; then
        nc -z 127.0.0.1 "$port" >/dev/null 2>&1 && return 0
        return 1
    fi
    return 1
}

first_free_port() {
    local port=$1 limit=$((${1} + 50))
    while [ "$port" -lt "$limit" ]; do
        port_in_use "$port" || { printf '%s' "$port"; return 0; }
        port=$((port + 1))
    done
    printf '%s' "$1"
}

# ---------------------------------------------------------------------------
# Privilege
# ---------------------------------------------------------------------------

run_root() {
    if [ "$(id -u)" = "0" ]; then
        "$@"
    elif have sudo; then
        sudo "$@"
    else
        fail "This step needs administrator access, but sudo is not available. Run the installer as root, or install sudo."
    fi
}

confirm_sudo() {
    [ "$(id -u)" = "0" ] && return 0
    have sudo || fail "This installation needs administrator access, but sudo is not available."
    say "Administrator access is needed for the steps listed above."
    sudo -v || fail "Administrator access was not granted."
}

# ---------------------------------------------------------------------------
# Files and templates
# ---------------------------------------------------------------------------

# render_template TEMPLATE OUTPUT KEY=VALUE...
# Placeholders are written @@KEY@@ so nothing collides with shell, YAML, or
# nginx syntax inside the templates themselves.
render_template() {
    local template=$1 output=$2
    shift 2
    local content pair key value
    content=$(cat "$template")
    for pair in "$@"; do
        key=${pair%%=*}
        value=${pair#*=}
        content=${content//@@${key}@@/${value}}
    done
    printf '%s\n' "$content" >"$output"
}

# Write stdin to a file only the owner can read. Configuration holds the
# generated secret in the Docker case, so it never becomes world readable.
write_private() {
    local output=$1
    local previous_umask
    previous_umask=$(umask)
    umask 077
    cat >"$output"
    umask "$previous_umask"
}

# ---------------------------------------------------------------------------
# Installation state
#
# One flat KEY='value' file under the installation root. Sourceable, and small
# enough to read by eye. Only the answers needed to resume are persisted.
# ---------------------------------------------------------------------------

state_file() { printf '%s/install.conf' "$FLOPPY_ROOT"; }

state_get() {
    local key=$1 file
    file=$(state_file)
    [ -f "$file" ] || return 1
    sed -n "s/^${key}='\(.*\)'\$/\1/p" "$file" | tail -n 1 | sed "s/'\\\\''/'/g"
}

state_set() {
    local key=$1 value=$2 file escaped tmp
    file=$(state_file)
    escaped=${value//\'/\'\\\'\'}
    tmp="${file}.tmp.$$"
    if [ -f "$file" ]; then
        grep -v "^${key}=" "$file" >"$tmp" 2>/dev/null || : >"$tmp"
    else
        : >"$tmp"
    fi
    printf "%s='%s'\n" "$key" "$escaped" >>"$tmp"
    LC_ALL=C sort -o "$tmp" "$tmp"
    chmod 600 "$tmp"
    mv "$tmp" "$file"
}

# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------

wait_for_http() {
    local url=$1 timeout=${2:-$FLOPPY_READY_TIMEOUT} waited=0
    while [ "$waited" -lt "$timeout" ]; do
        if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 3
        waited=$((waited + 3))
        if [ $((waited % 30)) -eq 0 ]; then
            note "Still waiting for Floppy to answer (${waited}s of ${timeout}s)."
        fi
    done
    return 1
}

open_url() {
    local url=$1
    case $FLOPPY_OS in
        Darwin) have open && open "$url" >/dev/null 2>&1 && return 0 ;;
        Linux)
            [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] || return 1
            have xdg-open && xdg-open "$url" >/dev/null 2>&1 && return 0
            ;;
    esac
    return 1
}
