# shellcheck shell=bash
#
# Floppy guided installer - completion, owner setup, and maintenance summary.
#
# Every method file supplies floppy_manage, floppy_restart_app,
# floppy_diagnostics, and floppy_commands_help, so nothing below needs to know
# whether Floppy is running in containers or as host services.

FLOPPY_READY=0

_lan_address() {
    case $FLOPPY_OS in
        Darwin)
            ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true
            ;;
        Linux)
            hostname -I 2>/dev/null | awk '{print $1}'
            ;;
    esac
}

floppy_url() {
    local host="127.0.0.1"
    if [ "$ACCESS" != "desktop" ]; then
        local lan
        lan=$(_lan_address)
        [ -n "$lan" ] && host=$lan
    fi
    printf 'http://%s:%s' "$host" "$PORT"
}

# Rewrite one setting in the installation's configuration, keeping the quoting
# each method's file format needs and the file's owner-only permissions.
set_env_value() {
    local key=$1 value=$2 rendered tmp
    if [ "$METHOD" = "source" ]; then
        rendered="${key}='${value}'"
    else
        rendered="${key}=${value}"
    fi
    tmp="${ENV_FILE}.tmp.$$"
    ( umask 077; { grep -v "^${key}=" "$ENV_FILE" 2>/dev/null || true; printf '%s\n' "$rendered"; } >"$tmp" )
    chmod 600 "$tmp"
    mv "$tmp" "$ENV_FILE"
}

# ---------------------------------------------------------------------------

finish_startup() {
    step "Waiting for Floppy to be ready"
    note "First startup applies database migrations, so it can take a couple of minutes."

    if wait_for_http "http://127.0.0.1:${PORT}/health/" "$FLOPPY_READY_TIMEOUT"; then
        FLOPPY_READY=1
        say "Floppy is answering on port $PORT."
    else
        FLOPPY_READY=0
        say ""
        warn "Floppy did not answer within $((FLOPPY_READY_TIMEOUT / 60)) minutes."
        say "Nothing was stopped or removed: the services are still running and your data is untouched."
        say "Startup may still be progressing. The diagnostics below say where it is."
        say ""
        floppy_diagnostics
        return 0
    fi

    step "Checking the installation"
    if floppy_manage floppy_preflight 2>&1 | tail -c 4000; then
        :
    else
        warn "floppy_preflight reported problems. The output above says which."
    fi
}

finish_owner_setup() {
    local url username reply
    url=$(floppy_url)

    if [ "$(state_get OWNER || echo 0)" = "1" ]; then
        note "Owner setup was already completed for this installation."
        return 0
    fi
    if [ "$FLOPPY_READY" = "0" ] && [ "$(state_get INSTALLED || echo 0)" = "1" ] && ! curl -fsS --max-time 5 "http://127.0.0.1:${PORT}/health/" >/dev/null 2>&1; then
        note "Owner setup needs Floppy to be answering. Run the installer again once it is up."
        return 0
    fi

    step "Create your account"
    say "Open Floppy and create the first account (copy and paste the address below - most terminals won't let you click it):"
    say ""
    say "    $url"
    say ""
    say "The installer never asks for a password. Create the account in the browser."
    if open_url "$url"; then
        note "Opened it in your browser."
    fi

    if ! ask_yes_no "Have you created your account?" yes; then
        say "No problem. When you have, run this to finish owner setup:"
        say "    bash \"$REPO_DIR/scripts/install/main.sh\""
        return 0
    fi

    say ""
    say "Signing in for the first time drops you into Floppy's own setup wizard"
    say "(media types, services, and so on) in the browser. That wizard is"
    say "separate from what's left here and saves as you go, so answer the next"
    say "prompt now - come back and finish or skip the wizard whenever you like."

    step "Making that account the owner"
    note "The owner can change instance-wide settings, such as metadata API keys."
    while :; do
        ask username "Username of the account you just created" ""
        if [ -z "$username" ]; then
            if ask_yes_no "No username given. Skip owner setup for now?" no; then
                say "Run 'bash \"$REPO_DIR/scripts/install/main.sh\"' later to finish it."
                return 0
            fi
            continue
        fi
        if floppy_manage promote_superuser "$username"; then
            state_set OWNER 1
            return 0
        fi
        say ""
        say "Accounts on this installation:"
        floppy_manage promote_superuser --list 2>&1 | tail -c 2000 || true
        say ""
        if ! ask_yes_no "Try a different username?" yes; then
            say "Run 'bash \"$REPO_DIR/scripts/install/main.sh\"' later to finish owner setup."
            return 0
        fi
    done
}

finish_optional_configuration() {
    local url
    url=$(floppy_url)

    [ "$FLOPPY_READY" = "1" ] || return 0

    step "Optional next steps"
    say "Metadata API keys are entered in Floppy itself, not here:"
    say ""
    say "    ${url}/settings/metadata"
    say ""
    say "Floppy works without them; add them whenever you like."

    if [ "$(state_get OWNER || echo 0)" = "1" ]; then
        say ""
        if ask_yes_no "Now that your account exists, close registration to new accounts?" no; then
            set_env_value REGISTRATION False
            floppy_restart_app
            state_set REGISTRATION False
            say "Registration is closed. To reopen it, set REGISTRATION to True in $ENV_FILE and restart Floppy."
        fi
    fi
}

finish_summary() {
    local url
    url=$(floppy_url)

    step "Floppy is installed"
    say ""
    say "  Address:        $url"
    say "  Your data:      $FLOPPY_ROOT"
    say "                    db/       the database and the generated secret key"
    say "                    backups/  automatic database backups"
    say "                    logs/     log files"
    say "  Configuration:  $ENV_FILE"
    say ""
    say "Commands:"
    floppy_commands_help
    say ""
    say "Back up $FLOPPY_ROOT and you have backed up Floppy."
}
