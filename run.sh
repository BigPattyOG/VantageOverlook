#!/usr/bin/env bash
# run.sh — Interactive management menu for Vantage Bot
#
# Usage:
#   ./run.sh            (shows the interactive menu)
#   sudo ./run.sh       (required for service control commands)
#
# You can also pass a command directly to skip the menu:
#   ./run.sh start | stop | restart | status | logs | update | setup

set -euo pipefail

# ── configuration ─────────────────────────────────────────────────────────────
INSTALL_DIR="/opt/vantage/VantageOverlook"
BOT_USER="vantage"
SERVICE_NAME="vantage"
VENV_PYTHON="$INSTALL_DIR/venv/bin/python"
VENV_PIP="$INSTALL_DIR/venv/bin/pip"

# ── colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

ok()    { echo -e "  ${GREEN}✔${NC}  $*"; }
warn()  { echo -e "  ${YELLOW}⚠${NC}  $*"; }
err()   { echo -e "  ${RED}✘${NC}  $*"; }
info()  { echo -e "  ${CYAN}›${NC}  $*"; }

# ── banner ────────────────────────────────────────────────────────────────────
print_banner() {
    clear
    echo -e "${CYAN}${BOLD}"
    echo "  ██╗   ██╗ █████╗ ███╗   ██╗████████╗ █████╗  ██████╗ ███████╗"
    echo "  ██║   ██║██╔══██╗████╗  ██║╚══██╔══╝██╔══██╗██╔════╝ ██╔════╝"
    echo "  ██║   ██║███████║██╔██╗ ██║   ██║   ███████║██║  ███╗█████╗  "
    echo "  ╚██╗ ██╔╝██╔══██║██║╚██╗██║   ██║   ██╔══██║██║   ██║██╔══╝  "
    echo "   ╚████╔╝ ██║  ██║██║ ╚████║   ██║   ██║  ██║╚██████╔╝███████╗"
    echo "    ╚═══╝  ╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝"
    echo -e "${NC}"
    echo -e "  ${BOLD}Vantage Bot Manager${NC}${DIM}  —  ${INSTALL_DIR}${NC}"
}

# ── status bar ────────────────────────────────────────────────────────────────
print_status() {
    echo ""
    echo -e "  ${DIM}──────────────────────────────────────────────────────────${NC}"

    # systemd status
    if command -v systemctl &>/dev/null && systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        echo -e "  Service status : ${GREEN}${BOLD}● running${NC}"
    elif systemctl list-unit-files "$SERVICE_NAME.service" &>/dev/null 2>&1; then
        echo -e "  Service status : ${RED}${BOLD}● stopped${NC}"
    else
        echo -e "  Service status : ${YELLOW}not installed${NC}"
    fi

    # config file
    CONFIG="$INSTALL_DIR/data/config.json"
    if [[ -f "$CONFIG" ]]; then
        # Extract prefix safely without python dependency
        PREFIX=$(grep -o '"prefix": *"[^"]*"' "$CONFIG" 2>/dev/null | grep -o '"[^"]*"$' | tr -d '"' || echo "?")
        echo -e "  Config         : ${GREEN}found${NC}  (prefix: ${BOLD}${PREFIX}${NC})"
    else
        echo -e "  Config         : ${RED}missing${NC} — run Setup first"
    fi

    # Python / venv
    if [[ -x "$VENV_PYTHON" ]]; then
        PY_VER=$("$VENV_PYTHON" --version 2>&1 | awk '{print $2}')
        echo -e "  Python         : ${GREEN}${PY_VER}${NC}  (venv active)"
    else
        echo -e "  Python         : ${RED}venv not found${NC} — run install.sh"
    fi

    echo -e "  ${DIM}──────────────────────────────────────────────────────────${NC}"
    echo ""
}

# ── helpers ───────────────────────────────────────────────────────────────────
need_root() {
    if [[ $EUID -ne 0 ]]; then
        err "This action requires root.  Re-run with: ${BOLD}sudo ./run.sh${NC}"
        return 1
    fi
}

run_as_bot() {
    # Run a command as the bot user inside the install directory
    sudo -u "$BOT_USER" bash -c "cd '$INSTALL_DIR' && $*"
}

pause() {
    echo ""
    echo -ne "  ${DIM}Press Enter to return to the menu…${NC}"
    read -r
}

# ── actions ───────────────────────────────────────────────────────────────────
do_start() {
    need_root || return
    info "Starting ${SERVICE_NAME} service…"
    systemctl start "$SERVICE_NAME"
    sleep 1
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        ok "Bot is ${GREEN}${BOLD}running${NC}."
    else
        err "Bot failed to start. Check logs with option [6]."
    fi
    pause
}

do_stop() {
    need_root || return
    info "Stopping ${SERVICE_NAME} service…"
    systemctl stop "$SERVICE_NAME"
    ok "Bot stopped."
    pause
}

do_restart() {
    need_root || return
    info "Restarting ${SERVICE_NAME} service…"
    systemctl restart "$SERVICE_NAME"
    sleep 1
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        ok "Bot restarted and is ${GREEN}${BOLD}running${NC}."
    else
        err "Bot failed to restart. Check logs with option [6]."
    fi
    pause
}

do_status() {
    echo ""
    if command -v systemctl &>/dev/null; then
        systemctl status "$SERVICE_NAME" --no-pager 2>/dev/null || true
    else
        err "systemd not found on this system."
    fi
    pause
}

do_logs() {
    echo ""
    info "Streaming live logs (Ctrl+C to stop)…"
    echo ""
    journalctl -u "$SERVICE_NAME" -f --no-pager 2>/dev/null || \
        err "Could not read journal — try: sudo journalctl -u $SERVICE_NAME -f"
}

do_logs_tail() {
    echo ""
    info "Last 50 log lines:"
    echo ""
    journalctl -u "$SERVICE_NAME" -n 50 --no-pager 2>/dev/null || \
        err "Could not read journal — try: sudo journalctl -u $SERVICE_NAME -n 50"
    pause
}

do_setup() {
    echo ""
    info "Launching interactive setup wizard…"
    echo ""
    if [[ -x "$VENV_PYTHON" ]]; then
        run_as_bot "$VENV_PYTHON launcher.py setup"
    else
        err "Virtual environment not found at $INSTALL_DIR/venv"
        err "Run install.sh first."
    fi
    pause
}

do_update() {
    need_root || return
    echo ""
    info "Pulling latest code from GitHub…"
    sudo -u "$BOT_USER" git -C "$INSTALL_DIR" pull --ff-only
    echo ""
    info "Upgrading Python dependencies…"
    sudo -u "$BOT_USER" "$VENV_PIP" install --quiet --upgrade pip
    sudo -u "$BOT_USER" "$VENV_PIP" install --quiet -r "$INSTALL_DIR/requirements.txt"
    ok "Update complete."
    echo ""
    warn "Restart the bot to apply changes:  option [3] Restart"
    pause
}

do_repos() {
    echo ""
    info "Cog repository list:"
    echo ""
    if [[ -x "$VENV_PYTHON" ]]; then
        run_as_bot "$VENV_PYTHON launcher.py repos list" || true
    else
        err "Virtual environment not found."
    fi
    pause
}

do_cogs() {
    echo ""
    info "Installed cogs:"
    echo ""
    if [[ -x "$VENV_PYTHON" ]]; then
        run_as_bot "$VENV_PYTHON launcher.py cogs list" || true
    else
        err "Virtual environment not found."
    fi
    pause
}

do_filemap() {
    FILE_MAP="$INSTALL_DIR/FILE_MAP.txt"
    if [[ -f "$FILE_MAP" ]]; then
        echo ""
        cat "$FILE_MAP"
    else
        warn "FILE_MAP.txt not found — run install.sh to generate it."
    fi
    pause
}

do_system_check() {
    echo ""
    info "Running system status check…"
    echo ""
    if [[ -x "$VENV_PYTHON" ]]; then
        run_as_bot "$VENV_PYTHON launcher.py system status" || true
    else
        err "Virtual environment not found — run install.sh first."
    fi
    pause
}

# ── direct command mode (non-interactive) ─────────────────────────────────────
if [[ $# -gt 0 ]]; then
    case "$1" in
        start)   do_start ;;
        stop)    do_stop ;;
        restart) do_restart ;;
        status)  do_status ;;
        logs)    do_logs ;;
        update)  do_update ;;
        setup)   do_setup ;;
        *)
            echo "Usage: $0 [start|stop|restart|status|logs|update|setup]"
            exit 1
            ;;
    esac
    exit 0
fi

# ── interactive menu loop ─────────────────────────────────────────────────────
while true; do
    print_banner
    print_status

    echo -e "  ${BOLD}What would you like to do?${NC}"
    echo ""
    echo -e "  ${GREEN}${BOLD}Bot Control${NC}"
    echo -e "    ${BOLD}[1]${NC} Start bot"
    echo -e "    ${BOLD}[2]${NC} Stop bot"
    echo -e "    ${BOLD}[3]${NC} Restart bot"
    echo -e "    ${BOLD}[4]${NC} Show service status"
    echo ""
    echo -e "  ${CYAN}${BOLD}Logs${NC}"
    echo -e "    ${BOLD}[5]${NC} Stream live logs  (Ctrl+C to exit)"
    echo -e "    ${BOLD}[6]${NC} Show last 50 log lines"
    echo ""
    echo -e "  ${YELLOW}${BOLD}Configuration & Updates${NC}"
    echo -e "    ${BOLD}[7]${NC} Re-run setup wizard  (token / prefix / owners)"
    echo -e "    ${BOLD}[8]${NC} Update bot  (git pull + pip upgrade)"
    echo ""
    echo -e "  ${BLUE}${BOLD}Cogs & Repos${NC}"
    echo -e "    ${BOLD}[9]${NC} List cog repositories"
    echo -e "    ${BOLD}[10]${NC} List installed cogs"
    echo ""
    echo -e "  ${MAGENTA}${BOLD}Info${NC}"
    echo -e "    ${BOLD}[11]${NC} Show system health check"
    echo -e "    ${BOLD}[12]${NC} Show file map  (FILE_MAP.txt)"
    echo ""
    echo -e "    ${BOLD}[0]${NC} Exit"
    echo ""
    echo -ne "  ${BOLD}Enter choice:${NC} "
    read -r CHOICE

    case "$CHOICE" in
        1)  do_start ;;
        2)  do_stop ;;
        3)  do_restart ;;
        4)  do_status ;;
        5)  do_logs ;;
        6)  do_logs_tail ;;
        7)  do_setup ;;
        8)  do_update ;;
        9)  do_repos ;;
        10) do_cogs ;;
        11) do_system_check ;;
        12) do_filemap ;;
        0)
            echo ""
            ok "Goodbye!"
            echo ""
            exit 0
            ;;
        *)
            warn "Unknown option '${CHOICE}' — please enter a number from the menu."
            sleep 1
            ;;
    esac
done
