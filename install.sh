#!/usr/bin/env bash
# install.sh — One-shot setup for Vantage Bot on Ubuntu 22.04+
#
# Quick install (curl one-liner):
#   curl -sSL https://raw.githubusercontent.com/BigPattyOG/VantageOverlook/main/install.sh | sudo bash
#
# Or clone and run manually:
#   chmod +x install.sh && sudo ./install.sh
#
# What this script does:
#   1. Installs Python 3.13, pip, venv, git, and other system tools
#   2. Creates a dedicated 'vantage' system user
#   3. Clones (or updates) the repository to /opt/vantage/VantageOverlook
#   4. Creates a Python virtual environment and installs all dependencies
#   5. Interactively configures the bot token, prefix, and owner IDs
#   6. Installs and enables the systemd service
#   7. Generates FILE_MAP.txt describing every file in the project

set -euo pipefail

# ── configuration ─────────────────────────────────────────────────────────────
INSTALL_DIR="/opt/vantage/VantageOverlook"
BOT_USER="vantage"
REPO_URL="${VANTAGE_REPO_URL:-https://github.com/BigPattyOG/VantageOverlook.git}"
SERVICE_FILE="vantage.service"
SYSTEMD_DEST="/etc/systemd/system/vantage.service"
PYTHON_VERSION="3.13"

# ── colours & helpers ─────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "  ${GREEN}✔${NC}  $*"; }
warn()    { echo -e "  ${YELLOW}⚠${NC}  $*"; }
error()   { echo -e "\n  ${RED}✘  ERROR:${NC} $*\n"; exit 1; }
step()    { echo -e "\n${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; \
            echo -e "${CYAN}${BOLD}  $*${NC}"; \
            echo -e "${CYAN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }
prompt()  { echo -ne "  ${BOLD}$*${NC} > "; }

# ── banner ────────────────────────────────────────────────────────────────────
clear
echo -e "${CYAN}${BOLD}"
echo "  ██╗   ██╗ █████╗ ███╗   ██╗████████╗ █████╗  ██████╗ ███████╗"
echo "  ██║   ██║██╔══██╗████╗  ██║╚══██╔══╝██╔══██╗██╔════╝ ██╔════╝"
echo "  ██║   ██║███████║██╔██╗ ██║   ██║   ███████║██║  ███╗█████╗  "
echo "  ╚██╗ ██╔╝██╔══██║██║╚██╗██║   ██║   ██╔══██║██║   ██║██╔══╝  "
echo "   ╚████╔╝ ██║  ██║██║ ╚████║   ██║   ██║  ██║╚██████╔╝███████╗"
echo "    ╚═══╝  ╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝"
echo -e "${NC}"
echo -e "  ${BOLD}Vantage Discord Bot — Automated Installer${NC}"
echo -e "  Python ${PYTHON_VERSION} · discord.py · Ubuntu 22.04+"
echo ""

# ── root check ────────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && error "Please run as root:  sudo ./install.sh"

# ── detect OS ─────────────────────────────────────────────────────────────────
if ! command -v apt-get &>/dev/null; then
    error "This installer requires an apt-based Linux distribution (Ubuntu/Debian)."
fi

# ═════════════════════════════════════════════════════════════════════════════
# STEP 1 — System packages
# ═════════════════════════════════════════════════════════════════════════════
step "Step 1/6 — System packages"

info "Updating package lists…"
apt-get update -qq

info "Installing prerequisites (software-properties-common, curl, git)…"
apt-get install -y -qq software-properties-common curl git build-essential

info "Adding deadsnakes PPA for Python ${PYTHON_VERSION}…"
add-apt-repository -y ppa:deadsnakes/ppa &>/dev/null
apt-get update -qq

info "Installing Python ${PYTHON_VERSION} and venv support…"
apt-get install -y -qq \
    "python${PYTHON_VERSION}" \
    "python${PYTHON_VERSION}-venv" \
    "python${PYTHON_VERSION}-dev" \
    python3-pip

# Register python3.13 as the default python3
update-alternatives --install /usr/bin/python3 python3 \
    "/usr/bin/python${PYTHON_VERSION}" 10 2>/dev/null || true

PYTHON_BIN="python${PYTHON_VERSION}"
info "Python version: $($PYTHON_BIN --version 2>&1)"

# ═════════════════════════════════════════════════════════════════════════════
# STEP 2 — Linux system user
# ═════════════════════════════════════════════════════════════════════════════
step "Step 2/6 — Linux system user"

if id "$BOT_USER" &>/dev/null; then
    warn "User '${BOT_USER}' already exists — skipping creation."
    info "Home: $(getent passwd "$BOT_USER" | cut -d: -f6)"
else
    info "Creating system user '${BOT_USER}'…"
    useradd --system --shell /bin/bash \
        --home-dir "$(dirname "$INSTALL_DIR")" \
        --create-home "$BOT_USER"
    info "User '${BOT_USER}' created  (home: $(dirname "$INSTALL_DIR"))"
fi

# ═════════════════════════════════════════════════════════════════════════════
# STEP 3 — Repository
# ═════════════════════════════════════════════════════════════════════════════
step "Step 3/6 — Repository"

mkdir -p "$(dirname "$INSTALL_DIR")"

if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Repository already cloned — pulling latest changes…"
    sudo -u "$BOT_USER" git -C "$INSTALL_DIR" pull --ff-only
else
    info "Cloning repository to ${INSTALL_DIR}…"
    sudo -u "$BOT_USER" git clone "$REPO_URL" "$INSTALL_DIR"
fi

chown -R "$BOT_USER:$BOT_USER" "$INSTALL_DIR"
info "Repository ready at ${INSTALL_DIR}"

# ═════════════════════════════════════════════════════════════════════════════
# STEP 4 — Python virtual environment & dependencies
# ═════════════════════════════════════════════════════════════════════════════
step "Step 4/6 — Python environment & dependencies"

info "Creating virtual environment (Python ${PYTHON_VERSION})…"
sudo -u "$BOT_USER" "$PYTHON_BIN" -m venv "$INSTALL_DIR/venv"

VENV_PIP="$INSTALL_DIR/venv/bin/pip"

info "Upgrading pip…"
sudo -u "$BOT_USER" "$VENV_PIP" install --quiet --upgrade pip

info "Installing discord.py and all project dependencies…"
sudo -u "$BOT_USER" "$VENV_PIP" install --quiet -r "$INSTALL_DIR/requirements.txt"

info "Ensuring runtime data directories exist…"
sudo -u "$BOT_USER" mkdir -p "$INSTALL_DIR/data/repos"

# Show installed packages summary
echo ""
echo -e "  ${BOLD}Installed packages:${NC}"
sudo -u "$BOT_USER" "$VENV_PIP" list --format=columns 2>/dev/null \
    | grep -E "discord|aiohttp|click|python-dotenv|gitpython" \
    | sed 's/^/    /'

# ═════════════════════════════════════════════════════════════════════════════
# STEP 5 — Bot configuration (token, prefix, owner IDs)
# ═════════════════════════════════════════════════════════════════════════════
step "Step 5/6 — Bot configuration"

CONFIG_FILE="$INSTALL_DIR/data/config.json"

echo ""
echo -e "  ${BOLD}Let's configure your bot now so it's ready to start immediately.${NC}"
echo ""

# ── bot token ─────────────────────────────────────────────────────────────────
echo -e "  ${YELLOW}Bot Token${NC}"
echo "  Get your token at: https://discord.com/developers/applications"
echo "  (Your input will not be echoed to the terminal)"
echo ""
prompt "Bot token"
read -rs BOT_TOKEN
echo ""

# Basic validation: Discord tokens are at least 50 characters long
while [[ -z "$BOT_TOKEN" ]] || [[ ${#BOT_TOKEN} -lt 50 ]]; do
    if [[ -z "$BOT_TOKEN" ]]; then
        warn "Token cannot be empty."
    else
        warn "That doesn't look like a valid Discord token (too short). Please try again."
    fi
    prompt "Bot token"
    read -rs BOT_TOKEN
    echo ""
done

# ── command prefix ────────────────────────────────────────────────────────────
echo ""
echo -e "  ${YELLOW}Command Prefix${NC}"
prompt "Command prefix [!]"
read -r BOT_PREFIX
BOT_PREFIX="${BOT_PREFIX:-!}"

# ── owner IDs ─────────────────────────────────────────────────────────────────
echo ""
echo -e "  ${YELLOW}Owner Discord ID(s)${NC}"
echo "  Enable Developer Mode in Discord → right-click your name → Copy ID."
echo "  Separate multiple IDs with commas."
prompt "Owner ID(s)"
read -r OWNER_IDS_RAW

# ── description ───────────────────────────────────────────────────────────────
echo ""
echo -e "  ${YELLOW}Bot Description${NC}"
DEFAULT_DESC="Vantage — a custom Discord bot framework"
prompt "Description [${DEFAULT_DESC}]"
read -r BOT_DESC
BOT_DESC="${BOT_DESC:-$DEFAULT_DESC}"

# ── write config.json — use Python for proper JSON escaping ───────────────────
# Values are passed via environment variables to avoid exposure in ps output.
BOT_TOKEN="$BOT_TOKEN" \
BOT_PREFIX="$BOT_PREFIX" \
OWNER_IDS_RAW="$OWNER_IDS_RAW" \
BOT_DESC="$BOT_DESC" \
"$PYTHON_BIN" - "$CONFIG_FILE" <<'PYEOF'
import json, os, sys

owner_ids = [
    int(x.strip())
    for x in os.environ.get("OWNER_IDS_RAW", "").split(",")
    if x.strip().isdigit()
]
prefix = os.environ["BOT_PREFIX"]
config = {
    "token": os.environ["BOT_TOKEN"],
    "prefix": prefix,
    "owner_ids": owner_ids,
    "description": os.environ["BOT_DESC"],
    "status": "online",
    "activity": f"{prefix}help for commands",
}
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump(config, fh, indent=2)
PYEOF

chown "$BOT_USER:$BOT_USER" "$CONFIG_FILE"
chmod 600 "$CONFIG_FILE"

info "Configuration saved to ${CONFIG_FILE}"

# ═════════════════════════════════════════════════════════════════════════════
# STEP 6 — systemd service
# ═════════════════════════════════════════════════════════════════════════════
step "Step 6/6 — systemd service"

info "Installing systemd unit file…"
cp "$INSTALL_DIR/$SERVICE_FILE" "$SYSTEMD_DEST"

sed -i "s|WorkingDirectory=.*|WorkingDirectory=$INSTALL_DIR|" "$SYSTEMD_DEST"
sed -i "s|ExecStart=.*|ExecStart=$INSTALL_DIR/venv/bin/python launcher.py start|" "$SYSTEMD_DEST"
sed -i "s|^User=.*|User=$BOT_USER|" "$SYSTEMD_DEST"

systemctl daemon-reload
systemctl enable vantage
info "Service 'vantage' installed and enabled (auto-starts on boot)"

# ═════════════════════════════════════════════════════════════════════════════
# FILE MAP — generate FILE_MAP.txt
# ═════════════════════════════════════════════════════════════════════════════
FILE_MAP="$INSTALL_DIR/FILE_MAP.txt"
cat > "$FILE_MAP" <<FILEMAP
╔══════════════════════════════════════════════════════════════════════════════╗
║              VantageOverlook — Project File Map                            ║
╚══════════════════════════════════════════════════════════════════════════════╝

This file is auto-generated by install.sh.  It describes every file and
directory in the VantageOverlook project and what it is used for.

──────────────────────────────────────────────────────────────────────────────
ROOT
──────────────────────────────────────────────────────────────────────────────
launcher.py
    Main CLI entry-point.  Start the bot, run interactive setup, manage cog
    repos, and control the systemd service.  Commands:
      python launcher.py start          — launch the bot
      python launcher.py setup          — interactive config wizard
      python launcher.py repos <cmd>    — manage cog repositories
      python launcher.py cogs  <cmd>    — manage individual cogs
      python launcher.py system <cmd>   — system / service management

install.sh
    One-shot Bash installer for Ubuntu 22.04+.  Installs Python ${PYTHON_VERSION},
    discord.py, all dependencies, creates the 'vantage' system user, clones
    the repository, configures the bot token, and enables the systemd service.
    Run with:  sudo ./install.sh
    Or via curl (one-liner):
      curl -sSL https://raw.githubusercontent.com/BigPattyOG/VantageOverlook/main/install.sh | sudo bash

run.sh
    Interactive management menu for the running bot.  Provides a friendly
    terminal UI to start / stop / restart the bot, view live logs, trigger
    updates, and re-run setup without memorising systemd commands.
    Run with:  ./run.sh   (or  sudo ./run.sh  for service control)

requirements.txt
    Python package dependencies installed into the virtual environment:
      • discord.py    — Discord API client library
      • aiohttp       — async HTTP client (used internally by discord.py)
      • gitpython     — programmatic Git operations for cog repo management
      • click         — CLI framework used by launcher.py
      • python-dotenv — optional .env file support

vantage.service
    systemd unit file.  Defines how the OS starts, stops, and restarts the
    bot as a background service.  Installed to /etc/systemd/system/ by
    install.sh.  Key settings: User, WorkingDirectory, ExecStart, Restart.

.env.example
    Template showing the BOT_TOKEN environment variable.  Copy to .env and
    fill in your token if you prefer environment-variable based config over
    the JSON config file.

FILE_MAP.txt  (this file)
    Human-readable map of every file in the project and what it does.
    Auto-generated / updated by install.sh.

README.md
    Full documentation: features, quick-start guide, CLI reference, cog
    authoring guide, and service management commands.

──────────────────────────────────────────────────────────────────────────────
core/
──────────────────────────────────────────────────────────────────────────────
core/__init__.py
    Package marker; makes 'core' importable as a Python package.

core/bot.py
    VantageBot class — subclasses discord.ext.commands.Bot.  Handles startup,
    config loading, extension (cog) autoloading, and graceful shutdown.

core/config.py
    Configuration helpers.  Reads and writes data/config.json.  Defines
    DEFAULT_CONFIG values (token, prefix, owner_ids, description, etc.).

core/cog_manager.py
    CogManager class.  Manages the registry of cog repositories (local
    directories and GitHub clones) and individual cog installations.
    Persists state to data/cog_data.json.

core/help_command.py
    Custom paginated help command.  Renders embeds with navigation buttons
    and a live keyword-search mode.  Replaces the default discord.py help.

──────────────────────────────────────────────────────────────────────────────
cogs/
──────────────────────────────────────────────────────────────────────────────
cogs/__init__.py
    Package marker for the built-in cogs directory.

cogs/admin.py
    Built-in admin cog — always loaded at startup.  Provides owner-only
    Discord commands: !ping, !load, !unload, !reload, !cogs, !prefix,
    !shutdown.

──────────────────────────────────────────────────────────────────────────────
data/  (runtime data — gitignored)
──────────────────────────────────────────────────────────────────────────────
data/config.json
    Bot configuration: token, command prefix, owner Discord IDs, description,
    status, and activity text.  Written by  launcher.py setup  or install.sh.
    Permissions: 600 (owner read/write only) to protect the bot token.

data/cog_data.json
    Registry of installed cog repositories and individual cogs.  Managed
    automatically by CogManager / launcher.py repos and cogs commands.

data/repos/
    Directory where GitHub-sourced cog repositories are cloned.  Each
    sub-directory is one repository, named by its identifier.

──────────────────────────────────────────────────────────────────────────────
venv/  (generated — not in git)
──────────────────────────────────────────────────────────────────────────────
venv/
    Python ${PYTHON_VERSION} virtual environment created by install.sh.  Contains all
    installed packages.  Use  source venv/bin/activate  to activate manually.

venv/bin/python
    The Python ${PYTHON_VERSION} interpreter used to run the bot.

venv/bin/pip
    Package installer for the virtual environment.

──────────────────────────────────────────────────────────────────────────────
systemd (installed to /etc/systemd/system/)
──────────────────────────────────────────────────────────────────────────────
/etc/systemd/system/vantage.service
    Installed copy of vantage.service with paths patched to match INSTALL_DIR.
    Manage with:
      sudo systemctl start|stop|restart|status vantage
      sudo journalctl -u vantage -f
FILEMAP

chown "$BOT_USER:$BOT_USER" "$FILE_MAP"
info "File map written to ${FILE_MAP}"

# ═════════════════════════════════════════════════════════════════════════════
# DONE
# ═════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}  ✅  Installation complete!                             ${NC}"
echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${BOLD}Install directory :${NC} $INSTALL_DIR"
echo -e "  ${BOLD}Linux user        :${NC} $BOT_USER"
echo -e "  ${BOLD}Python            :${NC} $($PYTHON_BIN --version 2>&1)"
echo -e "  ${BOLD}Config file       :${NC} $CONFIG_FILE"
echo -e "  ${BOLD}File map          :${NC} $FILE_MAP"
echo ""
echo -e "  ${BOLD}Next steps:${NC}"
echo ""
echo -e "  ${CYAN}▶  Start the bot${NC}"
echo "       sudo systemctl start vantage"
echo ""
echo -e "  ${CYAN}▶  Watch live logs${NC}"
echo "       sudo journalctl -u vantage -f"
echo ""
echo -e "  ${CYAN}▶  Use the interactive manager${NC}"
echo "       sudo $INSTALL_DIR/run.sh"
echo ""
echo -e "  ${CYAN}▶  Read the file map${NC}"
echo "       cat $FILE_MAP"
echo ""
