#!/usr/bin/env bash
set -Eeuo pipefail

# ============================================================
# vprod — one-command installer
# ============================================================
#
# Run as root (or via sudo):
#   sudo bash install.sh
#
# Optional environment overrides (set before calling the script):
#   REPO_URL=https://github.com/BigPattyOG/VantageOverlook.git
#   APP_DIR=/opt/vprod
#   DATA_DIR=/var/lib/vprod
#   BOT_USER=vprodbot
#   ADMIN_GROUP=vprodadmins
#   SERVICE_NAME=vprod
#   FORCE_RECLONE=1          # wipe APP_DIR and re-clone even if it exists
#   SKIP_START=1             # install without starting the service
#   DISCORD_TOKEN=...        # skip the interactive token prompt

REPO_URL="${REPO_URL:-https://github.com/BigPattyOG/VantageOverlook.git}"
APP_DIR="${APP_DIR:-/opt/vprod}"
DATA_DIR="${DATA_DIR:-/var/lib/vprod}"
BOT_USER="${BOT_USER:-vprodbot}"
ADMIN_GROUP="${ADMIN_GROUP:-vprodadmins}"
SERVICE_NAME="${SERVICE_NAME:-vprod}"
FORCE_RECLONE="${FORCE_RECLONE:-0}"
SKIP_START="${SKIP_START:-0}"

CONFIG_NAME="${CONFIG_NAME:-vprod}"
PREFIX="${PREFIX:-!}"
DESCRIPTION="${DESCRIPTION:-vprod - Vantage Discord Bot}"
STATUS_TEXT="${STATUS_TEXT:-online}"
ACTIVITY_TEXT="${ACTIVITY_TEXT:-{prefix}help for commands}"

# The non-root user who invoked sudo (used to add them to the dev group).
ADMIN_USER="${SUDO_USER:-}"

# ── pretty output ─────────────────────────────────────────────────────────────

STEP=0
TOTAL_STEPS=13

line()    { printf '%*s\n' "${COLUMNS:-72}" '' | tr ' ' '='; }
subline() { printf '%*s\n' "${COLUMNS:-72}" '' | tr ' ' '-'; }

title() {
    clear || true
    line
    echo "vprod setup"
    line
    echo "Repo        : $REPO_URL"
    echo "App dir     : $APP_DIR"
    echo "Data dir    : $DATA_DIR"
    echo "Bot user    : $BOT_USER"
    echo "Admin group : $ADMIN_GROUP"
    echo "Service     : $SERVICE_NAME"
    if [[ -n "$ADMIN_USER" && "$ADMIN_USER" != "root" ]]; then
        echo "Linux admin : $ADMIN_USER"
    fi
    line
}

step() {
    STEP=$((STEP + 1))
    echo
    printf '[%02d/%02d] %s\n' "$STEP" "$TOTAL_STEPS" "$1"
    subline
}

ok()   { printf '  [ok] %s\n' "$1"; }
info() { printf '  [..] %s\n' "$1"; }
warn() { printf '  [!!] %s\n' "$1" >&2; }
die()  { printf '  [xx] %s\n' "$1" >&2; exit 1; }

run_quiet() {
    local desc="$1"; shift
    if "$@" >"$_TMPOUT" 2>"$_TMPERR"; then
        ok "$desc"
    else
        warn "$desc failed"
        if [[ -s "$_TMPOUT" ]]; then
            echo; echo "----- stdout -----"; cat "$_TMPOUT"
        fi
        if [[ -s "$_TMPERR" ]]; then
            echo; echo "----- stderr -----"; cat "$_TMPERR"
        fi
        exit 1
    fi
}

confirm() {
    local prompt="${1:-Continue?}"
    local answer
    read -r -p "$prompt [y/N]: " answer || true
    case "${answer:-}" in
        y|Y|yes|YES) return 0 ;;
        *) return 1 ;;
    esac
}

cleanup_temp() {
    rm -f "$_TMPOUT" "$_TMPERR" 2>/dev/null || true
}

# Create secure temporary files for capturing command output.
_TMPOUT=$(mktemp)
_TMPERR=$(mktemp)
trap cleanup_temp EXIT

on_error() {
    local code=$?
    echo; line
    echo "Setup stopped.  Exit code: $code"
    echo "Look above for the failing step."
    line
    exit "$code"
}
trap on_error ERR

# ── guard checks ──────────────────────────────────────────────────────────────

require_root() {
    [[ "$EUID" -eq 0 ]] || die "Please run this script with sudo."
}

check_os() {
    if [[ -r /etc/os-release ]]; then
        # shellcheck source=/dev/null
        . /etc/os-release
        info "Detected ${PRETTY_NAME:-unknown}"
        [[ "${ID:-}" == "ubuntu" ]] || warn "This script was written for Ubuntu."
    fi
}

# ── step implementations ──────────────────────────────────────────────────────

install_packages() {
    run_quiet "apt update" apt update
    run_quiet "install required packages" env DEBIAN_FRONTEND=noninteractive \
        apt install -y git python3 python3-pip python3-venv build-essential ca-certificates
}

ensure_group() {
    if getent group "$ADMIN_GROUP" >/dev/null; then
        ok "group $ADMIN_GROUP already exists"
    else
        run_quiet "create group $ADMIN_GROUP" groupadd "$ADMIN_GROUP"
    fi
}

ensure_user() {
    if id "$BOT_USER" >/dev/null 2>&1; then
        ok "user $BOT_USER already exists"
    else
        run_quiet "create system user $BOT_USER" \
            useradd --system --create-home --shell /usr/sbin/nologin "$BOT_USER"
    fi
}

add_admin_user_to_group() {
    if [[ -z "$ADMIN_USER" || "$ADMIN_USER" == "root" ]]; then
        warn "Could not determine a non-root Linux user to add to $ADMIN_GROUP"
        return 0
    fi

    if id -nG "$ADMIN_USER" | tr ' ' '\n' | grep -qx "$ADMIN_GROUP"; then
        ok "$ADMIN_USER is already in $ADMIN_GROUP"
    else
        run_quiet "add $ADMIN_USER to $ADMIN_GROUP" usermod -aG "$ADMIN_GROUP" "$ADMIN_USER"
        warn "You will need to log out and back in for the new group to apply."
    fi
}

prepare_repo() {
    mkdir -p /opt

    if [[ -e "$APP_DIR" && "$FORCE_RECLONE" == "1" ]]; then
        run_quiet "remove existing $APP_DIR" rm -rf "$APP_DIR"
    fi

    if [[ -d "$APP_DIR/.git" ]]; then
        ok "existing git checkout found at $APP_DIR"
        run_quiet "mark git directory as safe" \
            git config --global --add safe.directory "$APP_DIR"
        run_quiet "fix ownership on existing checkout" \
            chown -R "$BOT_USER:$ADMIN_GROUP" "$APP_DIR"
        run_quiet "fetch latest refs as $BOT_USER" \
            sudo -u "$BOT_USER" git -C "$APP_DIR" fetch --all --prune
        return 0
    fi

    if [[ -e "$APP_DIR" ]]; then
        warn "$APP_DIR already exists but is not a git checkout."
        warn "Use FORCE_RECLONE=1 to wipe it and re-clone."
        ls -la "$APP_DIR" || true
        exit 1
    fi

    run_quiet "clone repository into $APP_DIR" git clone "$REPO_URL" "$APP_DIR"
}

set_code_permissions() {
    run_quiet "set ownership on $APP_DIR" chown -R "$BOT_USER:$ADMIN_GROUP" "$APP_DIR"

    info "setting directory permissions"
    find "$APP_DIR" -type d -exec chmod 2775 {} \;
    ok "directories set to 2775"

    info "setting file permissions"
    find "$APP_DIR" -type f -exec chmod 664 {} \;
    ok "files set to 664"

    [[ -f "$APP_DIR/launcher.py" ]] && chmod 775 "$APP_DIR/launcher.py" \
        && ok "launcher.py set executable"
    [[ -f "$APP_DIR/vmanage.py" ]] && chmod 775 "$APP_DIR/vmanage.py" \
        && ok "vmanage.py set executable"
    [[ -f "$APP_DIR/install.sh" ]] && chmod 775 "$APP_DIR/install.sh" \
        && ok "install.sh set executable"
}

prepare_data_dir() {
    run_quiet "create $DATA_DIR" mkdir -p "$DATA_DIR"
    run_quiet "set ownership on $DATA_DIR" chown -R "$BOT_USER:$ADMIN_GROUP" "$DATA_DIR"
    find "$DATA_DIR" -type d -exec chmod 2775 {} \;
    find "$DATA_DIR" -type f -exec chmod 664 {} \;
    ok "data directory permissions set"
}

ensure_umask() {
    local profile="/home/$BOT_USER/.profile"
    touch "$profile"
    chown "$BOT_USER:$BOT_USER" "$profile"
    if grep -qx 'umask 002' "$profile" 2>/dev/null; then
        ok "umask 002 already present for $BOT_USER"
    else
        printf '\numask 002\n' >> "$profile"
        ok "added umask 002 for $BOT_USER"
    fi
}

create_venv() {
    info "this may take a minute"
    local pip_out pip_err
    pip_out=$(mktemp)
    pip_err=$(mktemp)
    chown "$BOT_USER" "$pip_out" "$pip_err"
    sudo -u "$BOT_USER" bash -lc "
        set -Eeuo pipefail
        cd '$APP_DIR'
        python3 -m venv venv >/dev/null 2>&1
        venv/bin/pip install --upgrade pip >/dev/null 2>&1
        venv/bin/pip install -r requirements.txt >'$pip_out' 2>'$pip_err'
    " || {
        warn "venv or dependency install failed"
        [[ -s "$pip_out" ]] && { echo; echo "----- pip stdout -----"; cat "$pip_out"; }
        [[ -s "$pip_err" ]] && { echo; echo "----- pip stderr -----"; cat "$pip_err"; }
        rm -f "$pip_out" "$pip_err"
        exit 1
    }
    rm -f "$pip_out" "$pip_err"
    ok "virtual environment created and requirements installed"

    find "$APP_DIR/venv" -type d -exec chmod 2775 {} \;
    find "$APP_DIR/venv" -type f -exec chmod 664 {} \;
    find "$APP_DIR/venv/bin" -type f -exec chmod 775 {} \;
    ok "venv permissions fixed"
}

read_token() {
    local _tok
    read -r -s -p "Enter DISCORD_TOKEN: " _tok
    echo
    printf '%s' "$_tok"
}

write_env_file() {
    local env_file="$APP_DIR/.env"
    local token="${DISCORD_TOKEN:-}"

    if [[ -f "$env_file" && -z "$token" ]]; then
        echo
        warn "$env_file already exists."
        if confirm "Overwrite it with a new Discord token"; then
            token=$(read_token)
        else
            ok "keeping existing .env"
            chown "$BOT_USER:$BOT_USER" "$env_file"
            chmod 600 "$env_file"
            return 0
        fi
    fi

    if [[ ! -f "$env_file" && -z "$token" ]]; then
        echo
        token=$(read_token)
    fi

    if [[ -z "$token" ]]; then
        warn "No token entered. Creating placeholder .env."
        printf 'DISCORD_TOKEN=\n' > "$env_file"
    else
        printf 'DISCORD_TOKEN=%s\n' "$token" > "$env_file"
    fi

    chown "$BOT_USER:$BOT_USER" "$env_file"
    chmod 600 "$env_file"
    ok ".env written and locked down"
}

write_config() {
    local cfg="$DATA_DIR/config.json"

    if [[ -f "$cfg" ]]; then
        ok "keeping existing config.json"
        return 0
    fi

    cat > "$cfg" << EOF
{
  "name": "$CONFIG_NAME",
  "service_name": "$SERVICE_NAME",
  "prefix": "$PREFIX",
  "owner_ids": [],
  "description": "$DESCRIPTION",
  "status": "$STATUS_TEXT",
  "activity": "$ACTIVITY_TEXT"
}
EOF

    chown "$BOT_USER:$ADMIN_GROUP" "$cfg"
    chmod 660 "$cfg"
    ok "config.json written"
}

install_service() {
    local svc_src="$APP_DIR/vprod.service"
    local svc_dest="/etc/systemd/system/${SERVICE_NAME}.service"

    if [[ ! -f "$svc_src" ]]; then
        warn "vprod.service not found in $APP_DIR — skipping service install"
        return 0
    fi

    # Patch User=, WorkingDirectory=, EnvironmentFile=, ExecStart=, and
    # VPROD_DATA_DIR to match this install's actual paths and user.
    # Only lines that start with a key= directive are modified (not comments).
    sed \
        -e "s|^User=.*|User=$BOT_USER|" \
        -e "s|^\(WorkingDirectory=\)/opt/vprod|\1$APP_DIR|" \
        -e "s|^\(EnvironmentFile=-\)/opt/vprod|\1$APP_DIR|" \
        -e "s|^\(ExecStart=\)/opt/vprod|\1$APP_DIR|" \
        -e "s|^\(Environment=VPROD_DATA_DIR=\)/var/lib/vprod|\1$DATA_DIR|" \
        "$svc_src" > "$svc_dest"

    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
    ok "systemd service '$SERVICE_NAME' installed and enabled"
}

# ── main ─────────────────────────────────────────────────────────────────────

main() {
    require_root
    title

    step "Check operating system"
    check_os

    step "Install system packages"
    install_packages

    step "Ensure admin group ($ADMIN_GROUP)"
    ensure_group

    step "Ensure bot user ($BOT_USER)"
    ensure_user

    step "Add Linux admin to dev group"
    add_admin_user_to_group

    step "Clone / update repository"
    prepare_repo

    step "Set code directory permissions"
    set_code_permissions

    step "Prepare data directory"
    prepare_data_dir

    step "Set bot-user umask"
    ensure_umask

    step "Create Python virtual environment"
    create_venv

    step "Write bot token (.env)"
    write_env_file

    step "Write bot config (config.json)"
    write_config

    step "Install systemd service"
    install_service

    echo
    line
    echo "Setup complete!"
    echo

    if [[ "$SKIP_START" != "1" ]]; then
        info "Starting the service..."
        if systemctl start "$SERVICE_NAME"; then
            ok "$SERVICE_NAME started"
        else
            warn "Failed to start $SERVICE_NAME"
            warn "Check logs: sudo journalctl -u $SERVICE_NAME -n 50"
        fi
        echo
    fi

    echo "View logs   : sudo journalctl -u $SERVICE_NAME -f"
    echo "Check status: sudo systemctl status $SERVICE_NAME"
    if [[ -n "$ADMIN_USER" && "$ADMIN_USER" != "root" ]]; then
        echo
        warn "Remember: log out and back in as '$ADMIN_USER' so the"
        warn "new $ADMIN_GROUP group membership takes effect."
    fi
    line
}

main "$@"
