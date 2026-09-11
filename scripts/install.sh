#!/usr/bin/env bash
#
# Floppy guided installer - bootstrap.
#
#   curl -fsSL https://raw.githubusercontent.com/dannyvfilms/Floppy/latest/scripts/install.sh -o /tmp/floppy-install.sh
#   bash /tmp/floppy-install.sh
#
# This file runs before the repository exists on the host, so it stays small
# and self-contained: it looks at the machine, asks where Floppy should live,
# makes sure git is available, clones the target branch, and hands over to
# scripts/install/main.sh from that clone. Everything else - the installation
# method, ports, services, owner setup - is decided by the cloned installer, so
# a fix there reaches a user who saved this bootstrap months ago.
#
# TODO: the raw-URL above and the --branch default below point at "latest"
# because "release" does not carry scripts/install/ yet. Repoint both at
# "release" once a release brings the installer forward onto that branch.

set -euo pipefail

REPO_URL=${FLOPPY_REPO_URL:-https://github.com/dannyvfilms/Floppy.git}
REPO_BRANCH=${FLOPPY_REPO_BRANCH:-latest}
INSTALL_ROOT=${FLOPPY_ROOT:-}
ASSUME_YES=0

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    c_bold=$(printf '\033[1m'); c_dim=$(printf '\033[2m'); c_red=$(printf '\033[31m'); c_off=$(printf '\033[0m')
else
    c_bold=""; c_dim=""; c_red=""; c_off=""
fi

say() { printf '%s\n' "$*"; }
step() { printf '\n%s==> %s%s\n' "$c_bold" "$*" "$c_off"; }
note() { printf '%s    %s%s\n' "$c_dim" "$*" "$c_off"; }
fail() { printf '%sError: %s%s\n' "$c_red" "$*" "$c_off" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

ask() {
    local __var=$1 __question=$2 __default=${3:-} __reply=""
    printf '%s [%s]: ' "$__question" "$__default" >&2
    if [ "$ASSUME_YES" = "1" ] || [ ! -r /dev/tty ]; then
        printf '\n' >&2
    else
        IFS= read -r __reply </dev/tty || __reply=""
    fi
    [ -n "$__reply" ] || __reply=$__default
    printf -v "$__var" '%s' "$__reply"
}

ask_yes_no() {
    local question=$1 default=${2:-yes} reply="" hint
    case $default in yes) hint="Y/n" ;; *) hint="y/N" ;; esac
    while :; do
        printf '%s [%s]: ' "$question" "$hint" >&2
        if [ "$ASSUME_YES" = "1" ] || [ ! -r /dev/tty ]; then
            printf '\n' >&2
            reply=$default
        else
            IFS= read -r reply </dev/tty || reply=$default
        fi
        [ -n "$reply" ] || reply=$default
        case $reply in
            y|Y|yes|Yes|YES) return 0 ;;
            n|N|no|No|NO) return 1 ;;
            *) say "Please answer yes or no." ;;
        esac
    done
}

usage() {
    cat <<'USAGE'
Floppy guided installer.

Usage: bash floppy-install.sh [options]

  --dir PATH     Installation root (default: ~/floppy)
  --branch NAME  Branch to install from (default: latest)
  --repo URL     Repository to clone (default: the Floppy repository)
  --yes          Accept every default without prompting
  --help         Show this message
USAGE
}

while [ $# -gt 0 ]; do
    case $1 in
        --dir) INSTALL_ROOT=${2:-}; shift 2 ;;
        --dir=*) INSTALL_ROOT=${1#*=}; shift ;;
        --branch) REPO_BRANCH=${2:-}; shift 2 ;;
        --branch=*) REPO_BRANCH=${1#*=}; shift ;;
        --repo) REPO_URL=${2:-}; shift 2 ;;
        --repo=*) REPO_URL=${1#*=}; shift ;;
        --yes|-y) ASSUME_YES=1; shift ;;
        --help|-h) usage; exit 0 ;;
        *) fail "Unknown option: $1 (try --help)" ;;
    esac
done

if [ "$(id -u)" = "0" ]; then
    say "Note: running as root. Floppy's own processes still run as a normal user where that applies."
fi

# ---------------------------------------------------------------------------
# 1. Look at the machine
# ---------------------------------------------------------------------------

step "Checking this computer"

OS=$(uname -s)
ARCH=$(uname -m)
DISTRO=""
PKG=""
case $OS in
    Darwin) DISTRO="macOS $(sw_vers -productVersion 2>/dev/null || echo '')" ;;
    Linux)
        if [ -r /etc/os-release ]; then
            DISTRO=$(. /etc/os-release; printf '%s' "${PRETTY_NAME:-${ID:-Linux}}")
        else
            DISTRO="Linux"
        fi
        have apt-get && PKG="apt"
        ;;
    *) fail "Floppy's installer supports macOS and Linux. This host reports '$OS'." ;;
esac

say "  System:       ${DISTRO:-$OS} ($ARCH)"
say "  Shell user:   $(id -un)"
if have docker; then
    if docker info >/dev/null 2>&1; then
        say "  Docker:       available"
    else
        say "  Docker:       installed but not running"
    fi
else
    say "  Docker:       not installed"
fi
have git && say "  Git:          $(git --version 2>/dev/null)" || say "  Git:          not installed"

# ---------------------------------------------------------------------------
# 2. Where it goes
# ---------------------------------------------------------------------------

step "Where should Floppy be installed?"
note "This directory holds the code, the database, backups, and logs."
note "Everything Floppy stores stays inside it, so it is the only thing to back up."

if [ -z "$INSTALL_ROOT" ]; then
    ask INSTALL_ROOT "Installation directory" "$HOME/floppy"
fi
case $INSTALL_ROOT in
    "~") INSTALL_ROOT=$HOME ;;
    "~/"*) INSTALL_ROOT="$HOME/${INSTALL_ROOT#\~/}" ;;
esac
[ -n "$INSTALL_ROOT" ] || fail "An installation directory is required."

mkdir -p -- "$INSTALL_ROOT" || fail "Cannot create $INSTALL_ROOT"
INSTALL_ROOT=$(cd -- "$INSTALL_ROOT" && pwd)
[ -w "$INSTALL_ROOT" ] || fail "$INSTALL_ROOT is not writable by $(id -un)."

REPO_DIR="$INSTALL_ROOT/repo"

# Never adopt something that is already there and is not ours, and never reset
# a checkout the user may have changed. Both are silent ways to lose work.
if [ -e "$REPO_DIR" ]; then
    if [ ! -d "$REPO_DIR/.git" ]; then
        fail "$REPO_DIR already exists and is not a git checkout. Choose another installation directory, or move that directory aside."
    fi
    existing_remote=$(git -C "$REPO_DIR" remote get-url origin 2>/dev/null || true)
    if [ -z "$existing_remote" ]; then
        fail "$REPO_DIR is a git checkout with no 'origin' remote, so it is not a Floppy installation this installer created. Choose another installation directory."
    fi
    case $existing_remote in
        *[Ff]loppy*) : ;;
        *) fail "$REPO_DIR is a checkout of $existing_remote, not Floppy. Choose another installation directory." ;;
    esac
    say ""
    say "An existing Floppy installation was found at $INSTALL_ROOT."
    note "Your data and configuration are left exactly as they are; the checkout is fast-forwarded to pick up installer fixes."
    ask_yes_no "Resume that installation?" yes || fail "Nothing was changed."
    RESUME=1
else
    RESUME=0
fi

# ---------------------------------------------------------------------------
# 3. Prerequisites for the clone itself
# ---------------------------------------------------------------------------

if ! have git; then
    step "Git is needed to download Floppy"
    case "$OS:$PKG" in
        Linux:apt)
            say "The installer would run:"
            say "  sudo apt-get update && sudo apt-get install -y git ca-certificates curl"
            ask_yes_no "Install git now?" yes || fail "Git is required. Install it, then run this installer again."
            if [ "$(id -u)" = "0" ]; then
                apt-get update && apt-get install -y git ca-certificates curl
            else
                have sudo || fail "sudo is not available. Install git as root, then run this installer again."
                sudo apt-get update && sudo apt-get install -y git ca-certificates curl
            fi
            ;;
        Darwin:*)
            fail "Git is not installed. Run 'xcode-select --install', complete the Command Line Tools installation, then run this installer again."
            ;;
        *)
            fail "Git is not installed and this host's package manager is not one the installer automates. Install git with your package manager, then run this installer again."
            ;;
    esac
fi
have git || fail "Git is still not available after installation."

# ---------------------------------------------------------------------------
# 4. Get the code
# ---------------------------------------------------------------------------

if [ "$RESUME" = "0" ]; then
    step "Downloading Floppy ($REPO_BRANCH)"
    # HTTPS, no credentials: a GitHub account is not needed to install Floppy.
    git clone --branch "$REPO_BRANCH" --depth 1 --single-branch "$REPO_URL" "$REPO_DIR" \
        || fail "Could not download Floppy from $REPO_URL. Check the network connection and try again; nothing was installed."
    say "  Downloaded to $REPO_DIR"
else
    # The bootstrap re-downloads itself on every run, but a resumed
    # installation was otherwise stuck on whatever commit its first run
    # cloned - installer fixes never reached it, only ever refetching the
    # bootstrap ahead of the scripts it hands off to. Bring the checkout
    # forward the same way the documented "Upgrade" command already does
    # (fetch + fast-forward), so a fix here reaches an existing install on
    # its next run. Never a forced reset: if it can't fast-forward cleanly,
    # skip it and continue with what's on disk rather than discard anything.
    step "Checking for installer updates"
    # No --depth here: a second --depth-1 fetch against an already-shallow
    # clone produces a shallow boundary with no visible ancestry to the first,
    # so git refuses the fast-forward with "unrelated histories" even though
    # the branch is a clean, linear advance. An unbounded fetch lets git
    # deepen the existing shallow history instead of re-truncating it, which
    # is also what a plain "git pull" (the documented manual upgrade command)
    # already relies on.
    if git -C "$REPO_DIR" fetch --quiet origin "$REPO_BRANCH" 2>/dev/null \
        && git -C "$REPO_DIR" merge --quiet --ff-only FETCH_HEAD 2>/dev/null; then
        say "  Up to date."
    else
        warn "Could not update the installer checkout (offline, or local changes present); continuing with what's on disk."
    fi
fi

MAIN="$REPO_DIR/scripts/install/main.sh"
[ -f "$MAIN" ] || fail "$MAIN is missing. The checkout at $REPO_DIR predates the guided installer; update it with 'git -C $REPO_DIR pull' and try again."

export FLOPPY_ROOT="$INSTALL_ROOT"
export FLOPPY_REPO_URL="$REPO_URL"
export FLOPPY_REPO_BRANCH="$REPO_BRANCH"
export FLOPPY_ASSUME_YES="$ASSUME_YES"

exec bash "$MAIN"
