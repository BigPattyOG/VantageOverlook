#!/usr/bin/env bash
# =============================================================================
#  install-vdev.sh — Development installer for vprod
#  Vantage Discord Bot Framework
# =============================================================================
#
#  Run from inside the repo directory (no sudo needed):
#      bash scripts/install-vdev.sh
#
#  What this does:
#    1. Checks Python 3.10+ and git are available
#    2. Creates a Python virtual environment in ./venv
#    3. Installs all requirements
#    4. Creates ./data/ with dev config and directory layout
#    5. Stores your Discord token in ./data/.env (gitignored, chmod 600)
#    6. Installs vmanage so it works from the dev checkout
#
#  Optional overrides:
#      DISCORD_TOKEN=...       skip the interactive token prompt
#      PREFIX=?                command prefix (default: !)
#      PYTHON=python3.12       Python binary to use
#      SKIP_VMANAGE_LOCAL=1    don't install to ~/.local/bin
#
# =============================================================================

set -Eeuo pipefail

PREFIX="${PREFIX:-!}"
PYTHON="${PYTHON:-python3}"
DISCORD_TOKEN="${DISCORD_TOKEN:-}"
SKIP_VMANAGE_LOCAL="${SKIP_VMANAGE_LOCAL:-0}"

# ── ANSI colours ──────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  _R="\033[0m" _B="\033[1m" _DIM="\033[2m"
  _TEAL="\033[36m" _GREEN="\033[32m" _YELLOW="\033[33m" _RED="\033[31m"
else
  _R="" _B="" _DIM="" _TEAL="" _GREEN="" _YELLOW="" _RED=""
fi

# ── pretty output ─────────────────────────────────────────────────────────────
STEP=0
TOTAL_STEPS=6

_line()    { printf '%*s\n' "${COLUMNS:-72}" '' | tr ' ' '═'; }
_subline() { printf '%*s\n' "${COLUMNS:-72}" '' | tr ' ' '─'; }

banner() {
  clear || true
  echo -e "${_TEAL}${_B}"
  _line
  printf '  %-68s\n' "vprod — Development Installer"
  printf '  %-68s\n' "Vantage Discord Bot Framework"
  _line
  echo -e "${_R}"
  echo -e "  ${_DIM}Repo dir  :${_R} ${_B}$(pwd)${_R}"
  echo -e "  ${_DIM}Data dir  :${_R} $(pwd)/data  ${_TEAL}(token stored here, gitignored)${_R}"
  echo -e "  ${_DIM}Prefix    :${_R} ${PREFIX}"
  echo -e "  ${_DIM}Python    :${_R} ${PYTHON}"
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

confirm() {
  local prompt="${1:-Continue?}"; local ans
  read -r -p "  ${prompt} [y/N]: " ans </dev/tty || true
  [[ "${ans:-}" =~ ^[Yy] ]]
}

on_error() {
  local code=$?
  echo
  echo -e "${_RED}${_B}Setup stopped at step ${STEP}/${TOTAL_STEPS}.  Exit code: ${code}${_R}"
  echo "Check the output above for the failing step."
  exit "${code}"
}
trap on_error ERR

# ── guard: must be run from the repo root ─────────────────────────────────────
[[ -f launcher.py && -f requirements.txt ]] || \
  die "Run this script from the vprod repo root (where launcher.py lives)."

REPO_ROOT="$(pwd)"

# ── token validation ──────────────────────────────────────────────────────────
validate_token_format() {
  # Discord bot tokens: three base64url segments separated by dots.
  # Duplicated in scripts/install-vprod.sh and vmanage.py (_TOKEN_RE) — keep in sync.
  [[ "$1" =~ ^[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}$ ]]
}

# ── step implementations ──────────────────────────────────────────────────────

check_python() {
  # Verify the requested Python binary exists and is new enough.
  command -v "${PYTHON}" >/dev/null 2>&1 || \
    die "'${PYTHON}' not found.  Install Python 3.10+ or set PYTHON=python3.x"

  local pyver
  pyver=$("${PYTHON}" -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>/dev/null || echo "0.0")
  local major minor
  IFS='.' read -r major minor <<< "${pyver}"
  info "Python ${pyver}"
  if [[ "${major}" -lt 3 || ( "${major}" -eq 3 && "${minor}" -lt 10 ) ]]; then
    die "Python 3.10 or newer is required (found ${pyver})."
  fi
  ok "Python ${pyver} ✓"

  command -v git >/dev/null 2>&1 || die "git not found — install it first."
  ok "git $(git --version | awk '{print $3}') ✓"
}

create_venv() {
  if [[ -d venv ]]; then
    ok "venv already exists — upgrading packages"
    venv/bin/pip install --quiet --upgrade pip
    venv/bin/pip install --quiet -r requirements.txt
    ok "Requirements up to date"
  else
    info "Creating virtual environment…"
    "${PYTHON}" -m venv venv
    ok "venv created"
    info "Installing requirements (may take a moment)…"
    venv/bin/pip install --quiet --upgrade pip
    venv/bin/pip install --quiet -r requirements.txt
    ok "Requirements installed"
  fi
}

prepare_data_dir() {
  mkdir -p data/ext_plugins data/logs data/guilds data/repos
  # .gitkeep keeps repos/ tracked so plugins that add repos don't break
  touch data/repos/.gitkeep
  ok "data/ directory layout ready"
}

write_token() {
  local env_file="data/.env"
  local token="${DISCORD_TOKEN:-}"

  if [[ -f "${env_file}" && -z "${token}" ]]; then
    echo
    warn "${env_file} already exists."
    confirm "Overwrite it with a new token?" || {
      ok "Keeping existing ${env_file}"
      chmod 600 "${env_file}"
      return 0
    }
  fi

  if [[ -z "${token}" ]]; then
    echo
    info "Your token will be stored in ${REPO_ROOT}/data/.env"
    info "This path is gitignored — it will NOT be committed."
    echo
    while true; do
      read -r -s -p "  Enter DISCORD_TOKEN: " token </dev/tty; echo
      [[ -z "${token}" ]] && { warn "Token cannot be empty.  Try again."; continue; }
      validate_token_format "${token}" && break
      warn "That doesn't look like a valid Discord bot token."
      warn "Expected format: <24+chars>.<6chars>.<27+chars> (three dot-separated segments)."
      info "Get your token: https://discord.com/developers/applications"
      confirm "Try again?" || break
    done
  fi

  if [[ -z "${token}" ]]; then
    warn "No token provided — writing placeholder."
    printf 'DISCORD_TOKEN=\n' > "${env_file}"
  else
    printf 'DISCORD_TOKEN=%s\n' "${token}" > "${env_file}"
  fi
  chmod 600 "${env_file}"
  ok "Token written to ${env_file} (permissions: 600)"
}

write_config() {
  local cfg="data/config.json"
  [[ -f "${cfg}" ]] && { ok "Keeping existing ${cfg}"; return; }

  cat > "${cfg}" << EOF
{
  "name": "vprod-dev",
  "service_name": "vprod",
  "prefix": "${PREFIX}",
  "owner_ids": [],
  "description": "vprod — Dev Instance",
  "status": "online",
  "activity": "${PREFIX}help for commands",
  "health_port": 8080,
  "health_host": "127.0.0.1",
  "maintenance": false,
  "maintenance_message": ""
}
EOF
  ok "config.json written to data/"
}

install_vmanage_local() {
  # vmanage.py auto-detects the dev layout (INSTALL_DIR = repo root) when run
  # from inside the checkout, so no path patching is needed — just make it
  # executable from convenient locations.

  # 1. venv/bin/vmanage — available whenever the venv is activated
  local venv_link="${REPO_ROOT}/venv/bin/vmanage"
  [[ -e "${venv_link}" || -L "${venv_link}" ]] && rm -f "${venv_link}"
  ln -s "${REPO_ROOT}/vmanage.py" "${venv_link}"
  chmod 755 "${REPO_ROOT}/vmanage.py"
  ok "vmanage → venv/bin/vmanage  (active when venv is activated)"

  # 2. ~/.local/bin/vmanage — available system-wide for the current user,
  #    no sudo required.  Ubuntu adds ~/.local/bin to PATH automatically.
  if [[ "${SKIP_VMANAGE_LOCAL}" == "1" ]]; then
    info "Skipping ~/.local/bin install (SKIP_VMANAGE_LOCAL=1)"
    return
  fi

  local local_bin="${HOME}/.local/bin"
  mkdir -p "${local_bin}"
  local local_link="${local_bin}/vmanage"
  [[ -e "${local_link}" || -L "${local_link}" ]] && rm -f "${local_link}"
  ln -s "${REPO_ROOT}/vmanage.py" "${local_link}"
  ok "vmanage → ~/.local/bin/vmanage  (available without activating venv)"

  # If ~/.local/bin is not yet on PATH (fresh shell), warn the user.
  if ! echo ":${PATH}:" | grep -q ":${local_bin}:"; then
    warn "~/.local/bin is not on your current PATH."
    warn "The vmanage command will be available after you start a new shell, or run:"
    warn "  export PATH=\"\$HOME/.local/bin:\$PATH\""
  fi
}

# ── post-install summary ──────────────────────────────────────────────────────
print_summary() {
  echo
  echo -e "${_TEAL}${_B}"
  _line
  printf '  %-68s\n' "✅  Dev setup complete!"
  _line
  echo -e "${_R}"

  echo -e "  ${_DIM}Start the bot:${_R}"
  echo -e "    ${_B}venv/bin/python launcher.py start${_R}"
  echo -e "    ${_B}venv/bin/python launcher.py --debug start${_R}  ${_DIM}(verbose logging)${_R}"
  echo
  echo -e "  ${_DIM}Manage via vmanage (works from the repo directory):${_R}"
  echo -e "    ${_B}vmanage${_R}                 ${_DIM}status dashboard${_R}"
  echo -e "    ${_B}vmanage --logs${_R}           ${_DIM}stream live logs${_R}"
  echo -e "    ${_B}vmanage --update${_R}         ${_DIM}git pull + pip upgrade${_R}"
  echo -e "    ${_B}vmanage --update-token${_R}   ${_DIM}rotate the Discord token${_R}"
  echo -e "    ${_B}vmanage --motd${_R}           ${_DIM}preview the MOTD panel${_R}"
  echo
  echo -e "  ${_DIM}Token file :${_R} data/.env  ${_TEAL}(gitignored, chmod 600)${_R}"
  echo -e "  ${_DIM}Config     :${_R} data/config.json"
  echo -e "  ${_DIM}Plugins    :${_R} data/ext_plugins/"
  echo -e "  ${_DIM}Logs       :${_R} data/logs/vprod.log"
  echo
  _line
  echo
}

# ── main ──────────────────────────────────────────────────────────────────────
# Step inventory (keep in sync with TOTAL_STEPS above):
#   1  Check Python + git prerequisites
#   2  Create Python virtual environment
#   3  Prepare data directory
#   4  Store Discord token
#   5  Write bot configuration
#   6  Install vmanage
main() {
  banner

  step "Check Python + git prerequisites"
  check_python

  step "Create Python virtual environment"
  create_venv

  step "Prepare data directory"
  prepare_data_dir

  step "Store Discord token"
  write_token

  step "Write bot configuration"
  write_config

  step "Install vmanage"
  install_vmanage_local

  print_summary
}

main "$@"
