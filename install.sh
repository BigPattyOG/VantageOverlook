#!/usr/bin/env bash
# install.sh — One-shot setup for Vantage Bot on Ubuntu 22.04+
# Run as root (or a user with sudo) on a fresh server.
#
# Usage:
#   chmod +x install.sh
#   sudo ./install.sh
#
# What this script does:
#   1. Installs Python 3.11 and Git
#   2. Creates a dedicated 'vantage' system user
#   3. Clones (or updates) the repository to /opt/vantage/VantageOverlook
#   4. Creates a Python virtual environment and installs dependencies
#   5. Installs and enables the systemd service
#
# After running this script, configure the bot:
#   sudo -u vantage bash
#   cd /opt/vantage/VantageOverlook
#   source venv/bin/activate
#   python launcher.py setup
#   exit
#
# Then start the service:
#   sudo systemctl start vantage
#   sudo journalctl -u vantage -f   # watch logs

set -euo pipefail

INSTALL_DIR="/opt/vantage/VantageOverlook"
BOT_USER="vantage"
# Set this to your own fork if you've moved the repository.
REPO_URL="${VANTAGE_REPO_URL:-https://github.com/BigPattyOG/VantageOverlook.git}"
SERVICE_FILE="vantage.service"
SYSTEMD_DEST="/etc/systemd/system/vantage.service"

# ── colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── root check ────────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && error "Please run as root: sudo ./install.sh"

# ── system packages ───────────────────────────────────────────────────────────
info "Updating package lists…"
apt-get update -qq

info "Installing Python 3.11, pip, venv, git…"
apt-get install -y -qq python3.11 python3.11-venv python3-pip git

# Make python3.11 the default python3 if it isn't already
update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 2>/dev/null || true

# ── bot user ──────────────────────────────────────────────────────────────────
if id "$BOT_USER" &>/dev/null; then
    warn "User '$BOT_USER' already exists — skipping creation."
else
    info "Creating system user '$BOT_USER'…"
    useradd --system --shell /bin/bash --create-home "$BOT_USER"
fi

# ── repository ────────────────────────────────────────────────────────────────
mkdir -p "$(dirname "$INSTALL_DIR")"

if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Repository already cloned — pulling latest changes…"
    sudo -u "$BOT_USER" git -C "$INSTALL_DIR" pull
else
    info "Cloning repository to $INSTALL_DIR…"
    sudo -u "$BOT_USER" git clone "$REPO_URL" "$INSTALL_DIR"
fi

chown -R "$BOT_USER:$BOT_USER" "$INSTALL_DIR"

# ── virtual environment ───────────────────────────────────────────────────────
info "Creating Python virtual environment…"
sudo -u "$BOT_USER" python3.11 -m venv "$INSTALL_DIR/venv"

info "Installing Python dependencies…"
sudo -u "$BOT_USER" "$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
sudo -u "$BOT_USER" "$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

# ── data directory ────────────────────────────────────────────────────────────
info "Ensuring data directories exist…"
sudo -u "$BOT_USER" mkdir -p "$INSTALL_DIR/data/repos"

# ── systemd service ───────────────────────────────────────────────────────────
info "Installing systemd service…"
cp "$INSTALL_DIR/$SERVICE_FILE" "$SYSTEMD_DEST"

# Patch WorkingDirectory and ExecStart paths in case they differ
sed -i "s|WorkingDirectory=.*|WorkingDirectory=$INSTALL_DIR|" "$SYSTEMD_DEST"
sed -i "s|ExecStart=.*|ExecStart=$INSTALL_DIR/venv/bin/python launcher.py start|" "$SYSTEMD_DEST"
sed -i "s|^User=.*|User=$BOT_USER|" "$SYSTEMD_DEST"

systemctl daemon-reload
systemctl enable vantage

# ── done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}✅  Installation complete!${NC}"
echo ""
echo "Next steps:"
echo "  1. Configure the bot (token, prefix, owner IDs):"
echo "       sudo -u $BOT_USER bash -c 'cd $INSTALL_DIR && source venv/bin/activate && python launcher.py setup'"
echo ""
echo "  2. Start the bot:"
echo "       sudo systemctl start vantage"
echo ""
echo "  3. Watch the logs:"
echo "       sudo journalctl -u vantage -f"
echo ""
echo "  4. Add a cog repo (example):"
echo "       sudo -u $BOT_USER bash -c 'cd $INSTALL_DIR && source venv/bin/activate && python launcher.py repos add https://github.com/example/my-cogs'"
