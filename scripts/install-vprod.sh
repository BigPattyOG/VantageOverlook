#!/usr/bin/env bash
# =============================================================================
#  install-vprod.sh — Production installer for vprod
#  Vantage Discord Bot Framework
# =============================================================================
#
#  Run as root (or via sudo):
#      sudo bash scripts/install-vprod.sh
#
#  Optional environment overrides:
#      REPO_URL=https://github.com/BigPattyOG/VantageOverlook.git
#      APP_DIR=/opt/vprod
#      DATA_DIR=/var/lib/vprod
#      BOT_USER=vprodbot
#      ADMIN_GROUP=vprodadmins
#      SERVICE_NAME=vprod
#      DISCORD_TOKEN=...   (skip interactive prompt)
#      FORCE_RECLONE=1     (wipe APP_DIR and re-clone)
#      SKIP_START=1        (install without starting the service)
#
# =============================================================================

set -Eeuo pipefail

# ── defaults ──────────────────────────────────────────────────────────────────
REPO_URL="${REPO_URL:-https://github.com/BigPattyOG/VantageOverlook.git}"
APP_DIR="${APP_DIR:-/opt/vprod}"
DATA_DIR="${DATA_DIR:-/var/lib/vprod}"
BOT_USER="${BOT_USER:-vprodbot}"
ADMIN_GROUP="${ADMIN_GROUP:-vprodadmins}"
SERVICE_NAME="${SERVICE_NAME:-vprod}"
FORCE_RECLONE="${FORCE_RECLONE:-0}"
SKIP_START="${SKIP_START:-0}"
PREFIX="${PREFIX:-!}"
DESCRIPTION="${DESCRIPTION:-vprod — Vantage Discord Bot}"
ADMIN_USER="${SUDO_USER:-}"

# ── ANSI colours ──────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  _R="\033[0m" _B="\033[1m" _DIM="\033[2m"
  _TEAL="\033[36m" _GREEN="\033[32m" _YELLOW="\033[33m" _RED="\033[31m"
else
  _R="" _B="" _DIM="" _TEAL="" _GREEN="" _YELLOW="" _RED=""
fi

# ── pretty output ─────────────────────────────────────────────────────────────
STEP=0
TOTAL_STEPS=12

_line() { printf '%*s\n' "${COLUMNS:-72}" '' | tr ' ' '═'; }
_subline() { printf '%*s\n' "${COLUMNS:-72}" '' | tr ' ' '─'; }

banner() {
  clear || true
  echo -e "${_TEAL}${_B}"
  _line
  printf '  %-68s\n' "vprod — Production Installer"
  printf '  %-68s\n' "Vantage Discord Bot Framework"
  _line
  echo -e "${_R}"
  echo -e "  ${_DIM}Repo        :${_R} ${_B}${REPO_URL}${_R}"
  echo -e "  ${_DIM}App dir     :${_R} ${APP_DIR}"
  echo -e "  ${_DIM}Data dir    :${_R} ${DATA_DIR}  ${_TEAL}← token stored here (outside git)${_R}"
  echo -e "  ${_DIM}Bot user    :${_R} ${BOT_USER}"
  echo -e "  ${_DIM}Admin group :${_R} ${ADMIN_GROUP}"
  echo -e "  ${_DIM}Service     :${_R} ${SERVICE_NAME}"
  [[ -n "${ADMIN_USER}" && "${ADMIN_USER}" != "root" ]] && \
    echo -e "  ${_DIM}Linux admin :${_R} ${ADMIN_USER}"
  echo
  _line
  echo
}

step() {
  STEP=$((STEP+1))
  echo
  echo -e "${_TEAL}${_B}[${STEP}/${TOTAL_STEPS}]${_R} ${_B}${1}${_R}"
  _subline
}

ok()   { echo -e "  ${_GREEN}✔${_R}  ${1}"; }
info() { echo -e "  ${_DIM}→${_R}  ${1}"; }
warn() { echo -e "  ${_YELLOW}⚠${_R}  ${1}" >&2; }
die()  { echo -e "  ${_RED}✖${_R}  ${1}" >&2; exit 1; }

run_quiet() {
  local desc="$1"; shift
  local out; out=$(mktemp); local err; err=$(mktemp)
  if "$@" >"${out}" 2>"${err}"; then
    ok "${desc}"
  else
    warn "${desc} failed"
    [[ -s "${out}" ]] && { echo; cat "${out}"; }
    [[ -s "${err}" ]] && { echo; cat "${err}"; }
    rm -f "${out}" "${err}"; exit 1
  fi
  rm -f "${out}" "${err}"
}

confirm() {
  local prompt="${1:-Continue?}"; local ans
  read -r -p "  ${prompt} [y/N]: " ans </dev/tty || true
  [[ "${ans:-}" =~ ^[Yy] ]]
}

on_error() {
  local code=$?
  echo; echo -e "${_RED}${_B}Setup stopped at step ${STEP}/${TOTAL_STEPS}.  Exit code: ${code}${_R}"
  echo "Check the output above for the failing step."
  exit "${code}"
}
trap on_error ERR

# ── guard ─────────────────────────────────────────────────────────────────────
[[ "${EUID}" -eq 0 ]] || die "Please run with sudo: sudo bash ${BASH_SOURCE[0]}"

# ── step implementations ──────────────────────────────────────────────────────

check_os() {
  if [[ -r /etc/os-release ]]; then
    # shellcheck source=/dev/null
    . /etc/os-release
    info "Detected ${PRETTY_NAME:-unknown}"
    [[ "${ID:-}" == "ubuntu" ]] || warn "This script was written for Ubuntu — proceed with care."
  fi
  local pyver
  pyver=$(python3 -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>/dev/null || echo "0.0")
  info "Python ${pyver}"
  [[ "${pyver}" != "0.0" ]] || die "python3 not found — install it first."
}

install_packages() {
  run_quiet "apt update" apt update
  run_quiet "install required packages" env DEBIAN_FRONTEND=noninteractive \
    apt install -y git python3 python3-pip python3-venv build-essential ca-certificates
}

ensure_group() {
  if getent group "${ADMIN_GROUP}" >/dev/null; then
    ok "Group '${ADMIN_GROUP}' already exists"
  else
    run_quiet "Create group '${ADMIN_GROUP}'" groupadd "${ADMIN_GROUP}"
  fi
}

ensure_user() {
  if id "${BOT_USER}" >/dev/null 2>&1; then
    ok "User '${BOT_USER}' already exists"
  else
    run_quiet "Create system user '${BOT_USER}'" \
      useradd --system --create-home --shell /usr/sbin/nologin "${BOT_USER}"
  fi
}

add_admin_to_group() {
  [[ -z "${ADMIN_USER}" || "${ADMIN_USER}" == "root" ]] && {
    warn "Could not determine non-root user to add to ${ADMIN_GROUP}"
    return 0
  }
  if id -nG "${ADMIN_USER}" | tr ' ' '\n' | grep -qx "${ADMIN_GROUP}"; then
    ok "${ADMIN_USER} is already in ${ADMIN_GROUP}"
  else
    run_quiet "Add ${ADMIN_USER} to ${ADMIN_GROUP}" usermod -aG "${ADMIN_GROUP}" "${ADMIN_USER}"
    warn "Log out and back in for the new group to take effect."
  fi
}

prepare_repo() {
  mkdir -p /opt
  if [[ -e "${APP_DIR}" && "${FORCE_RECLONE}" == "1" ]]; then
    run_quiet "Remove existing ${APP_DIR}" rm -rf "${APP_DIR}"
  fi

  if [[ -d "${APP_DIR}/.git" ]]; then
    ok "Git checkout found at ${APP_DIR}"
    run_quiet "Mark git dir as safe" git config --global --add safe.directory "${APP_DIR}"
    run_quiet "Fix ownership" chown -R "${BOT_USER}:${ADMIN_GROUP}" "${APP_DIR}"
    run_quiet "Fetch latest refs" sudo -u "${BOT_USER}" git -C "${APP_DIR}" fetch --all --prune
    return 0
  fi

  [[ -e "${APP_DIR}" ]] && die "${APP_DIR} exists but is not a git repo. Use FORCE_RECLONE=1."
  run_quiet "Clone repository to ${APP_DIR}" git clone "${REPO_URL}" "${APP_DIR}"
}

set_permissions() {
  run_quiet "Set ownership on ${APP_DIR}" chown -R "${BOT_USER}:${ADMIN_GROUP}" "${APP_DIR}"
  find "${APP_DIR}" -type d -exec chmod 2775 {} \;
  find "${APP_DIR}" -type f -exec chmod 664 {} \;
  for f in launcher.py vmanage.py scripts/install-vprod.sh scripts/install-vdev.sh scripts/install.sh; do
    [[ -f "${APP_DIR}/${f}" ]] && chmod 775 "${APP_DIR}/${f}"
  done
  ok "Code directory permissions set (2775 dirs, 664 files, 775 executables)"
}

prepare_data_dir() {
  run_quiet "Create ${DATA_DIR}" mkdir -p "${DATA_DIR}"
  run_quiet "Create ${DATA_DIR}/ext_plugins" mkdir -p "${DATA_DIR}/ext_plugins"
  run_quiet "Create ${DATA_DIR}/logs" mkdir -p "${DATA_DIR}/logs"
  run_quiet "Set ownership on ${DATA_DIR}" chown -R "${BOT_USER}:${ADMIN_GROUP}" "${DATA_DIR}"
  find "${DATA_DIR}" -type d -exec chmod 2775 {} \;
  find "${DATA_DIR}" -type f -exec chmod 664 {} \;
  ok "Data directory ready"
}

ensure_umask() {
  local profile="/home/${BOT_USER}/.profile"
  touch "${profile}"; chown "${BOT_USER}:${BOT_USER}" "${profile}"
  grep -qx 'umask 002' "${profile}" 2>/dev/null && { ok "umask 002 already set"; return; }
  printf '\numask 002\n' >> "${profile}"
  ok "Set umask 002 for ${BOT_USER}"
}

create_venv() {
  info "Creating virtual environment (may take a minute)…"
  local pip_out pip_err
  pip_out=$(mktemp); pip_err=$(mktemp)
  chown "${BOT_USER}" "${pip_out}" "${pip_err}"

  # Restore execute bits on existing venv/bin if a previous run stripped them.
  [[ -d "${APP_DIR}/venv/bin" ]] && find "${APP_DIR}/venv/bin" -type f -exec chmod 775 {} \;

  sudo -u "${BOT_USER}" bash -c "
    set -Eeuo pipefail
    cd '${APP_DIR}'
    python3 -m venv venv >'${pip_out}' 2>'${pip_err}'
    venv/bin/pip install --upgrade pip >>'${pip_out}' 2>'${pip_err}'
    venv/bin/pip install -r requirements.txt >>'${pip_out}' 2>'${pip_err}'
  " || {
    warn "venv / pip install failed"
    [[ -s "${pip_out}" ]] && cat "${pip_out}"
    [[ -s "${pip_err}" ]] && cat "${pip_err}"
    rm -f "${pip_out}" "${pip_err}"; exit 1
  }
  rm -f "${pip_out}" "${pip_err}"
  find "${APP_DIR}/venv" -type d -exec chmod 2775 {} \;
  find "${APP_DIR}/venv" -type f -exec chmod 664 {} \;
  find "${APP_DIR}/venv/bin" -type f -exec chmod 775 {} \;
  ok "Virtual environment ready"
}

# ── token handling ─────────────────────────────────────────────────────────────
#
# The token is stored in DATA_DIR/.env — OUTSIDE the git checkout.
# This means:
#   • git pull can never overwrite it
#   • Discord's token scanner never sees it in the repo
#   • systemd reads it via EnvironmentFile= and injects DISCORD_TOKEN
#
validate_token_format() {
  local tok="$1"
  # Discord bot tokens are three base64url segments joined by dots
  if [[ "${tok}" =~ ^[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}$ ]]; then
    return 0
  fi
  return 1
}

write_token() {
  local env_file="${DATA_DIR}/.env"
  local token="${DISCORD_TOKEN:-}"

  if [[ -f "${env_file}" && -z "${token}" ]]; then
    echo
    warn "${env_file} already exists."
    confirm "Overwrite it with a new token?" || {
      ok "Keeping existing ${env_file}"
      chown "${BOT_USER}:${BOT_USER}" "${env_file}"; chmod 600 "${env_file}"
      return 0
    }
  fi

  if [[ -z "${token}" ]]; then
    echo
    info "The token will be stored in ${env_file}"
    info "It will NOT be inside the git directory — git pull can never reset it."
    echo
    while true; do
      read -r -s -p "  Enter DISCORD_TOKEN: " token </dev/tty; echo
      [[ -z "${token}" ]] && { warn "Token cannot be empty. Try again."; continue; }
      validate_token_format "${token}" && break
      warn "That doesn't look like a valid Discord bot token."
      warn "Expected format: <24+chars>.<6chars>.<27+chars> (separated by dots)."
      info "Get your token from: https://discord.com/developers/applications"
      confirm "Try again?" || break
    done
  fi

  if [[ -z "${token}" ]]; then
    warn "No token provided. Creating placeholder ${env_file}."
    printf 'DISCORD_TOKEN=\n' > "${env_file}"
  else
    printf 'DISCORD_TOKEN=%s\n' "${token}" > "${env_file}"
  fi

  chown "${BOT_USER}:${BOT_USER}" "${env_file}"
  chmod 600 "${env_file}"
  ok "Token written to ${env_file} (permissions: 600, owner: ${BOT_USER} only)"
}

write_config() {
  local cfg="${DATA_DIR}/config.json"
  [[ -f "${cfg}" ]] && { ok "Keeping existing config.json"; return; }

  cat > "${cfg}" << EOF
{
  "name": "${SERVICE_NAME}",
  "service_name": "${SERVICE_NAME}",
  "prefix": "${PREFIX}",
  "owner_ids": [],
  "description": "${DESCRIPTION}",
  "status": "online",
  "activity": "${PREFIX}help for commands",
  "health_port": 8080,
  "health_host": "0.0.0.0",
  "maintenance": false,
  "maintenance_message": ""
}
EOF
  chown "${BOT_USER}:${ADMIN_GROUP}" "${cfg}"; chmod 660 "${cfg}"
  ok "config.json written to ${DATA_DIR}"
}

install_service() {
  local svc_src="${APP_DIR}/vprod.service"
  local svc_dest="/etc/systemd/system/${SERVICE_NAME}.service"
  [[ -f "${svc_src}" ]] || { warn "vprod.service not found — skipping service install"; return; }

  sed \
    -e "s|^User=.*|User=${BOT_USER}|" \
    -e "s|^\(WorkingDirectory=\)/opt/vprod|\1${APP_DIR}|" \
    -e "s|^\(EnvironmentFile=-\)/var/lib/vprod|\1${DATA_DIR}|" \
    -e "s|^\(ExecStart=\)/opt/vprod|\1${APP_DIR}|" \
    -e "s|^\(Environment=VPROD_DATA_DIR=\)/var/lib/vprod|\1${DATA_DIR}|" \
    "${svc_src}" > "${svc_dest}"

  systemctl daemon-reload
  systemctl enable "${SERVICE_NAME}"
  ok "Systemd service '${SERVICE_NAME}' installed and enabled"
}

# ── main ──────────────────────────────────────────────────────────────────────
main() {
  banner

  step "Check operating system"
  check_os

  step "Install system packages"
  install_packages

  step "Ensure admin group (${ADMIN_GROUP})"
  ensure_group

  step "Ensure bot user (${BOT_USER})"
  ensure_user

  step "Add Linux admin to dev group"
  add_admin_to_group

  step "Clone / update repository"
  prepare_repo

  step "Set code directory permissions"
  set_permissions

  step "Prepare data directory"
  prepare_data_dir

  step "Set bot-user umask"
  ensure_umask

  step "Create Python virtual environment"
  create_venv

  step "Write Discord token (stored in ${DATA_DIR}/.env)"
  write_token

  step "Write bot config (${DATA_DIR}/config.json)"
  write_config

  step "Install systemd service"
  install_service

  echo
  echo -e "${_TEAL}${_B}"
  _line
  printf '  %-68s\n' "✅  Setup complete!"
  _line
  echo -e "${_R}"

  if [[ "${SKIP_START}" != "1" ]]; then
    info "Starting ${SERVICE_NAME}…"
    if systemctl start "${SERVICE_NAME}"; then
      ok "${SERVICE_NAME} started"
    else
      warn "Service failed to start — check logs:"
      echo "    sudo journalctl -u ${SERVICE_NAME} -n 50"
    fi
    echo
  fi

  echo -e "  ${_DIM}View logs   :${_R} sudo journalctl -u ${SERVICE_NAME} -f"
  echo -e "  ${_DIM}Check status:${_R} sudo systemctl status ${SERVICE_NAME}"
  echo -e "  ${_DIM}Token file  :${_R} ${DATA_DIR}/.env  ${_TEAL}(600, ${BOT_USER} only)${_R}"
  echo -e "  ${_DIM}Config      :${_R} ${DATA_DIR}/config.json"
  echo -e "  ${_DIM}External plugins:${_R} ${DATA_DIR}/ext_plugins/"
  echo

  if [[ -n "${ADMIN_USER}" && "${ADMIN_USER}" != "root" ]]; then
    echo
    warn "Remember: log out and back in as '${ADMIN_USER}' so the"
    warn "'${ADMIN_GROUP}' group membership takes effect."
  fi
  _line
  echo
}

main "$@"
