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
#   1. Asks for a bot name, token, prefix, and optionally owner IDs
#      (owner IDs are pulled from the Discord API automatically)
#   2. Installs Python 3.13, pip, venv, git, and other system tools
#   3. Creates a dedicated 'vantage' system user
#   4. Clones (or updates) the repository to /opt/vantage/<BotName>
#   5. Creates a Python virtual environment and installs all dependencies
#   6. Writes data/config.json (with override/update/keep prompt if it exists)
#   7. Installs and enables the systemd service, then starts the bot

set -euo pipefail

# ── fixed settings ─────────────────────────────────────────────────────────────
BOT_USER="vantage"
REPO_URL="${VANTAGE_REPO_URL:-https://github.com/BigPattyOG/VantageOverlook.git}"
PYTHON_VERSION="3.13"

# ── colours & helpers ─────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
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
# PRE-STEP — Bot identity (name, token, prefix)
# ═════════════════════════════════════════════════════════════════════════════
step "Pre-setup — Bot Identity"

echo ""
echo -e "  ${BOLD}Choose a name for this bot instance.${NC}"
echo -e "  ${DIM}Used for the install directory, service name, and in-Discord management.${NC}"
echo ""
prompt "Bot name [Vantage]"
read -r BOT_NAME_RAW
BOT_NAME_RAW="${BOT_NAME_RAW:-Vantage}"

# Sanitize: keep alphanumerics and hyphens only
BOT_NAME=$(echo "$BOT_NAME_RAW" | tr -s ' ' '-' | tr -cd '[:alnum:]-' | sed 's/^-//;s/-$//')
[[ -z "$BOT_NAME" ]] && BOT_NAME="Vantage"

# Derive paths from bot name
INSTALL_DIR="/opt/vantage/${BOT_NAME}"
SERVICE_NAME="vantage-$(echo "$BOT_NAME" | tr '[:upper:]' '[:lower:]')"
SYSTEMD_DEST="/etc/systemd/system/${SERVICE_NAME}.service"

echo ""
info "Bot name     : ${BOLD}${BOT_NAME}${NC}"
info "Install dir  : ${INSTALL_DIR}"
info "Service name : ${SERVICE_NAME}"

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
        --home-dir "/opt/vantage" \
        --create-home "$BOT_USER"
    info "User '${BOT_USER}' created  (home: /opt/vantage)"
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

if [[ ! -d "$INSTALL_DIR/venv" ]]; then
    info "Creating virtual environment (Python ${PYTHON_VERSION})…"
    sudo -u "$BOT_USER" "$PYTHON_BIN" -m venv "$INSTALL_DIR/venv"
else
    info "Virtual environment already exists — reusing."
fi

VENV_PIP="$INSTALL_DIR/venv/bin/pip"

info "Upgrading pip…"
sudo -u "$BOT_USER" "$VENV_PIP" install --quiet --upgrade pip

info "Installing discord.py and all project dependencies…"
sudo -u "$BOT_USER" "$VENV_PIP" install --quiet -r "$INSTALL_DIR/requirements.txt"

info "Ensuring runtime data directories exist…"
sudo -u "$BOT_USER" mkdir -p "$INSTALL_DIR/data/repos"
sudo -u "$BOT_USER" mkdir -p "$INSTALL_DIR/data/guilds"

# ── install vmanage as a system-wide command ──────────────────────────────────
info "Installing vmanage CLI to /usr/local/bin/vmanage…"
chmod +x "$INSTALL_DIR/vmanage.py"
ln -sf "$INSTALL_DIR/vmanage.py" /usr/local/bin/vmanage
info "vmanage installed — try: vmanage ${BOT_NAME}"

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

# ── detect existing config ────────────────────────────────────────────────────
RECONFIGURE=true
KEEP_EXISTING=false

if [[ -f "$CONFIG_FILE" ]]; then
    echo ""
    warn "A configuration file already exists at ${CONFIG_FILE}"
    echo ""
    echo -e "  ${BOLD}What would you like to do?${NC}"
    echo ""
    echo -e "    ${BOLD}[1]${NC} Override — replace all settings with new values  ${DIM}(fresh start)${NC}"
    echo -e "    ${BOLD}[2]${NC} Update  — keep existing values, only change specified fields"
    echo -e "    ${BOLD}[3]${NC} Keep    — leave config as-is, skip this step"
    echo ""
    prompt "Your choice [1/2/3]"
    read -r CONFIG_CHOICE
    case "${CONFIG_CHOICE:-1}" in
        2) RECONFIGURE=true;  KEEP_EXISTING=true  ;;
        3) RECONFIGURE=false; KEEP_EXISTING=true  ;;
        *) RECONFIGURE=true;  KEEP_EXISTING=false ;;
    esac
fi

if $RECONFIGURE; then
    echo ""
    echo -e "  ${BOLD}Let's configure your bot.${NC}"
    echo ""

    # ── load existing values for "update" mode ────────────────────────────────
    EXISTING_TOKEN=""
    EXISTING_PREFIX="!"
    EXISTING_DESC="Vantage — a custom Discord bot framework"
    if $KEEP_EXISTING && [[ -f "$CONFIG_FILE" ]]; then
        EXISTING_TOKEN=$("$PYTHON_BIN" -c "import json; d=json.load(open('$CONFIG_FILE')); print(d.get('token',''))" 2>/dev/null || echo "")
        EXISTING_PREFIX=$("$PYTHON_BIN" -c "import json; d=json.load(open('$CONFIG_FILE')); print(d.get('prefix','!'))" 2>/dev/null || echo "!")
        EXISTING_DESC=$("$PYTHON_BIN" -c "import json; d=json.load(open('$CONFIG_FILE')); print(d.get('description','Vantage — a custom Discord bot framework'))" 2>/dev/null || echo "Vantage — a custom Discord bot framework")
    fi

    # ── bot token ─────────────────────────────────────────────────────────────
    echo -e "  ${YELLOW}Bot Token${NC}"
    echo "  Get your token at: https://discord.com/developers/applications"
    echo "  (Your input will not be echoed to the terminal)"
    if $KEEP_EXISTING && [[ -n "$EXISTING_TOKEN" ]]; then
        echo "  Leave blank to keep the existing token."
    fi
    echo ""
    prompt "Bot token"
    read -rs BOT_TOKEN
    echo ""

    # Use existing if left blank in update mode
    if [[ -z "$BOT_TOKEN" ]] && $KEEP_EXISTING && [[ -n "$EXISTING_TOKEN" ]]; then
        BOT_TOKEN="$EXISTING_TOKEN"
        info "Keeping existing token."
    fi

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

    # ── auto-fetch owner from Discord API ─────────────────────────────────────
    echo ""
    echo -e "  ${YELLOW}Bot Owner(s)${NC}"
    echo -e "  ${DIM}Fetching application owner from Discord API…${NC}"

    # Use Python (already installed) to make the request so the token is never
    # exposed on the process command line.
    DISCORD_API_RESPONSE=$(BOT_TOKEN="$BOT_TOKEN" "$PYTHON_BIN" - <<'PYEOF'
import os, sys
try:
    import urllib.request
    token = os.environ["BOT_TOKEN"]
    req = urllib.request.Request(
        "https://discord.com/api/v10/oauth2/applications/@me",
        headers={"Authorization": f"Bot {token}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        print(resp.read().decode("utf-8"))
except Exception:
    print("")
PYEOF
)

    AUTO_OWNER_IDS=""
    AUTO_OWNER_NAMES=""

    if [[ -n "$DISCORD_API_RESPONSE" ]] && ! echo "$DISCORD_API_RESPONSE" | grep -q '"code"'; then
        # Parse owner/team with Python — API response is passed via stdin to avoid
        # embedding untrusted JSON in the script source.
        PARSED=$(echo "$DISCORD_API_RESPONSE" | "$PYTHON_BIN" - <<'PYEOF'
import json, sys
try:
    d = json.load(sys.stdin)
    team = d.get("team")
    if team:
        members = [
            m["user"] for m in team.get("members", [])
            if m.get("membership_state") == 2
        ]
        ids   = ",".join(m["id"] for m in members)
        names = ", ".join(f"{m.get('username','?')} ({m['id']})" for m in members)
    else:
        owner = d.get("owner", {})
        ids   = owner.get("id", "")
        names = f"{owner.get('username','?')} ({owner.get('id','?')})"
    print(ids)
    print(names)
except Exception as e:
    print("")
    print(f"(error: {e})")
PYEOF
)
        AUTO_OWNER_IDS=$(echo "$PARSED" | head -1)
        AUTO_OWNER_NAMES=$(echo "$PARSED" | tail -1)
    fi

    if [[ -n "$AUTO_OWNER_IDS" ]]; then
        echo ""
        info "Detected owner(s) from Discord:"
        echo -e "    ${BOLD}${AUTO_OWNER_NAMES}${NC}"
        echo ""
        echo -e "  ${DIM}Press Enter to accept, or type different owner ID(s) (comma-separated).${NC}"
        prompt "Owner ID(s) [${AUTO_OWNER_IDS}]"
        read -r OWNER_IDS_RAW
        OWNER_IDS_RAW="${OWNER_IDS_RAW:-${AUTO_OWNER_IDS}}"
    else
        warn "Could not fetch owner from Discord API — please enter manually."
        echo "  Enable Developer Mode in Discord → right-click your name → Copy ID."
        echo "  Separate multiple IDs with commas."
        prompt "Owner ID(s)"
        read -r OWNER_IDS_RAW
    fi

    # ── command prefix ────────────────────────────────────────────────────────
    echo ""
    echo -e "  ${YELLOW}Command Prefix${NC}"
    prompt "Command prefix [${EXISTING_PREFIX}]"
    read -r BOT_PREFIX
    BOT_PREFIX="${BOT_PREFIX:-${EXISTING_PREFIX}}"

    # ── description ───────────────────────────────────────────────────────────
    echo ""
    echo -e "  ${YELLOW}Bot Description${NC}"
    prompt "Description [${EXISTING_DESC}]"
    read -r BOT_DESC
    BOT_DESC="${BOT_DESC:-${EXISTING_DESC}}"

    # ── write config.json — use Python for proper JSON escaping ───────────────
    # Values are passed via environment variables to avoid exposure in ps output.
    BOT_TOKEN="$BOT_TOKEN" \
    BOT_PREFIX="$BOT_PREFIX" \
    BOT_NAME="$BOT_NAME" \
    SERVICE_NAME="$SERVICE_NAME" \
    OWNER_IDS_RAW="$OWNER_IDS_RAW" \
    BOT_DESC="$BOT_DESC" \
    KEEP_EXISTING="$KEEP_EXISTING" \
    CONFIG_FILE="$CONFIG_FILE" \
    "$PYTHON_BIN" - <<'PYEOF'
import json, os, sys

config_file = os.environ["CONFIG_FILE"]
keep = os.environ.get("KEEP_EXISTING", "false").lower() == "true"

# Load existing if updating
existing = {}
if keep and os.path.isfile(config_file):
    try:
        with open(config_file, encoding="utf-8") as fh:
            existing = json.load(fh)
    except Exception:
        pass

owner_ids = [
    int(x.strip())
    for x in os.environ.get("OWNER_IDS_RAW", "").split(",")
    if x.strip().isdigit()
]
prefix = os.environ["BOT_PREFIX"]

config = {
    **existing,
    "name":         os.environ["BOT_NAME"],
    "service_name": os.environ["SERVICE_NAME"],
    "token":        os.environ["BOT_TOKEN"],
    "prefix":       prefix,
    "owner_ids":    owner_ids if owner_ids else existing.get("owner_ids", []),
    "description":  os.environ["BOT_DESC"],
    "status":       existing.get("status", "online"),
    "activity":     existing.get("activity", f"{prefix}help for commands"),
}
with open(config_file, "w", encoding="utf-8") as fh:
    json.dump(config, fh, indent=2)
print("ok")
PYEOF

    chown "$BOT_USER:$BOT_USER" "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE"
    info "Configuration saved to ${CONFIG_FILE}"
else
    info "Keeping existing configuration at ${CONFIG_FILE}"
fi

# ═════════════════════════════════════════════════════════════════════════════
# STEP 6 — systemd service
# ═════════════════════════════════════════════════════════════════════════════
step "Step 6/6 — systemd service"

# Validate SERVICE_NAME before using it in system files (sudoers, service path).
if ! [[ "$SERVICE_NAME" =~ ^[a-z][a-z0-9-]*$ ]]; then
    error "Invalid service name '${SERVICE_NAME}'. Must be lowercase alphanumeric and hyphens."
fi

SERVICE_FILE="$INSTALL_DIR/vantage.service"

info "Installing systemd unit file as ${SERVICE_NAME}.service…"
cp "$SERVICE_FILE" "$SYSTEMD_DEST"

# Patch the service file using Python for safe replacement (avoids issues with
# special characters in BOT_NAME or INSTALL_DIR that would break sed patterns).
BOT_NAME="$BOT_NAME" \
SERVICE_NAME="$SERVICE_NAME" \
BOT_USER="$BOT_USER" \
INSTALL_DIR="$INSTALL_DIR" \
SYSTEMD_DEST="$SYSTEMD_DEST" \
"$PYTHON_BIN" - <<'PYEOF'
import os, re
dst  = os.environ["SYSTEMD_DEST"]
name = os.environ["BOT_NAME"]
svc  = os.environ["SERVICE_NAME"]
user = os.environ["BOT_USER"]
idir = os.environ["INSTALL_DIR"]
python_bin = f"{idir}/venv/bin/python"

replacements = {
    r"^Description=.*":         f"Description=Vantage Discord Bot — {name}",
    r"^WorkingDirectory=.*":    f"WorkingDirectory={idir}",
    r"^ExecStart=.*":           f"ExecStart={python_bin} launcher.py start",
    r"^User=.*":                f"User={user}",
    r"^SyslogIdentifier=.*":   f"SyslogIdentifier={svc}",
}
lines = open(dst, encoding="utf-8").read().splitlines()
out   = []
for line in lines:
    for pattern, replacement in replacements.items():
        if re.match(pattern, line):
            line = replacement
            break
    out.append(line)
with open(dst, "w", encoding="utf-8") as fh:
    fh.write("\n".join(out) + "\n")
PYEOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
info "Service '${SERVICE_NAME}' installed and enabled (auto-starts on boot)"

# ── sudoers entry: let the bot user control its own service ────────────────────
# SERVICE_NAME is validated above (^[a-z][a-z0-9-]*$) so it is safe to embed here.
SUDOERS_FILE="/etc/sudoers.d/${SERVICE_NAME}"
printf '# Allow %s to control the %s service (for vmanage Discord command)\n' \
    "$BOT_USER" "$SERVICE_NAME" > "$SUDOERS_FILE"
printf '%s ALL=(root) NOPASSWD: /usr/bin/systemctl start %s, /usr/bin/systemctl stop %s, /usr/bin/systemctl restart %s\n' \
    "$BOT_USER" "$SERVICE_NAME" "$SERVICE_NAME" "$SERVICE_NAME" >> "$SUDOERS_FILE"
chmod 0440 "$SUDOERS_FILE"
# Validate the sudoers file to ensure it is syntactically correct
if command -v visudo &>/dev/null; then
    visudo -c -f "$SUDOERS_FILE" &>/dev/null || {
        warn "Sudoers file validation failed — removing to avoid lockout."
        rm -f "$SUDOERS_FILE"
    }
fi
info "Sudoers rule written to ${SUDOERS_FILE}"

# ── start the bot now ─────────────────────────────────────────────────────────
echo ""
info "Starting '${SERVICE_NAME}' now…"
if systemctl start "$SERVICE_NAME"; then
    sleep 2
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        info "${GREEN}${BOLD}Bot is running!${NC}"
    else
        warn "Service started but may not be active yet — check logs below."
    fi
else
    warn "Could not start the service immediately — check token/config and try manually."
fi

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

Bot name     : ${BOT_NAME}
Service name : ${SERVICE_NAME}
Install dir  : ${INSTALL_DIR}

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

vmanage.py
    Standalone CLI management tool — installed to /usr/local/bin/vmanage.
    Uses only the Python standard library (no venv needed).  Usage:
      vmanage                         list all installed bots
      vmanage ${BOT_NAME}               show status dashboard
      vmanage ${BOT_NAME} --start       start the bot
      vmanage ${BOT_NAME} --stop        stop the bot
      vmanage ${BOT_NAME} --restart     restart the bot
      vmanage ${BOT_NAME} --logs        stream live logs
      vmanage ${BOT_NAME} --logs --lines 50  last 50 log lines
      vmanage ${BOT_NAME} --update      git pull + pip upgrade + restart
      vmanage ${BOT_NAME} --setup       re-run setup wizard
      vmanage ${BOT_NAME} --cogs        list installed cogs
      vmanage ${BOT_NAME} --repos       list cog repos

requirements.txt
    Python package dependencies installed into the virtual environment:
      • discord.py    — Discord API client library
      • aiohttp       — async HTTP client (used internally by discord.py)
      • gitpython     — programmatic Git operations for cog repo management
      • click         — CLI framework used by launcher.py
      • python-dotenv — optional .env file support

vantage.service
    systemd unit file template.  Installed to /etc/systemd/system/ by
    install.sh as ${SERVICE_NAME}.service.

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
    DEFAULT_CONFIG values (name, service_name, token, prefix, owner_ids, etc.).

core/guild_data.py
    Per-guild JSON data storage.  Each guild gets data/guilds/{id}.json.
    Use load_guild() / save_guild() for guild-specific settings.

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
    Discord commands: ping, load, unload, reload, cogs, prefix, shutdown,
    vmanage (interactive management panel), servers, stats, announce,
    setactivity, botinfo.

──────────────────────────────────────────────────────────────────────────────
data/  (runtime data — gitignored)
──────────────────────────────────────────────────────────────────────────────
data/config.json
    Bot configuration: name, service_name, token, command prefix, owner
    Discord IDs, description, status, and activity text.
    Written by install.sh or 'launcher.py setup'.
    Permissions: 600 (owner read/write only) to protect the bot token.

data/cog_data.json
    Registry of installed cog repositories and individual cogs.  Managed
    automatically by CogManager / launcher.py repos and cogs commands.

data/repos/
    Directory where GitHub-sourced cog repositories are cloned.  Each
    sub-directory is one repository, named by its identifier.

data/guilds/
    Per-guild JSON files: data/guilds/{guild_id}.json.  Stores guild-specific
    settings managed by the bot at runtime.

──────────────────────────────────────────────────────────────────────────────
venv/  (generated — not in git)
──────────────────────────────────────────────────────────────────────────────
venv/
    Python ${PYTHON_VERSION} virtual environment created by install.sh.
    Use  source venv/bin/activate  to activate manually.

──────────────────────────────────────────────────────────────────────────────
systemd (installed to /etc/systemd/system/)
──────────────────────────────────────────────────────────────────────────────
/etc/systemd/system/${SERVICE_NAME}.service
    Installed copy of vantage.service with paths patched to match INSTALL_DIR.
    Manage with:
      sudo systemctl start|stop|restart|status ${SERVICE_NAME}
      sudo journalctl -u ${SERVICE_NAME} -f

/etc/sudoers.d/${SERVICE_NAME}
    Allows the '${BOT_USER}' user to start/stop/restart the ${SERVICE_NAME}
    service without a password — used by the vmanage Discord command.
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
echo -e "  ${BOLD}Bot name          :${NC} ${BOT_NAME}"
echo -e "  ${BOLD}Install directory :${NC} $INSTALL_DIR"
echo -e "  ${BOLD}Linux user        :${NC} $BOT_USER"
echo -e "  ${BOLD}Python            :${NC} $($PYTHON_BIN --version 2>&1)"
echo -e "  ${BOLD}Service           :${NC} ${SERVICE_NAME}.service"
echo -e "  ${BOLD}Config file       :${NC} $CONFIG_FILE"
echo ""
echo -e "  ${BOLD}Next steps:${NC}"
echo ""
echo -e "  ${CYAN}▶  Status dashboard (new!)${NC}"
echo "       vmanage ${BOT_NAME}"
echo ""
echo -e "  ${CYAN}▶  Stream live logs${NC}"
echo "       vmanage ${BOT_NAME} --logs"
echo ""
echo -e "  ${CYAN}▶  Common service commands${NC}"
echo "       vmanage ${BOT_NAME} --restart"
echo "       vmanage ${BOT_NAME} --stop"
echo "       vmanage ${BOT_NAME} --update"
echo ""
echo -e "  ${CYAN}▶  In Discord (owner only)${NC}"
echo "       ${BOT_PREFIX:-!}vmanage          — management panel with buttons"
echo "       ${BOT_PREFIX:-!}stats            — bot statistics"
echo "       ${BOT_PREFIX:-!}servers          — list all guilds"
echo ""
