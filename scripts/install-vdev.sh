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
#    1. Creates a Python virtual environment in ./venv
#    2. Installs all requirements
#    3. Creates ./data/ with dev config and ext_plugins folder
#    4. Stores your Discord token in ./data/.env (gitignored)
#    5. Prints the command to start the bot
#
#  Optional overrides:
#    DISCORD_TOKEN=...   skip the interactive token prompt
#    PREFIX=?            command prefix (default: !)
#    PYTHON=python3.12   Python binary to use
#
# =============================================================================

set -Eeuo pipefail

PREFIX="${PREFIX:-!}"
PYTHON="${PYTHON:-python3}"
DISCORD_TOKEN="${DISCORD_TOKEN:-}"

# ── ANSI colours ──────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  _R="\033[0m" _B="\033[1m" _DIM="\033[2m"
  _TEAL="\033[36m" _GREEN="\033[32m" _YELLOW="\033[33m" _RED="\033[31m"
else
  _R="" _B="" _DIM="" _TEAL="" _GREEN="" _YELLOW="" _RED=""
fi

_line()    { printf '%*s\n' "${COLUMNS:-66}" '' | tr ' ' '═'; }
_subline() { printf '%*s\n' "${COLUMNS:-66}" '' | tr ' ' '─'; }
STEP=0; TOTAL_STEPS=5

banner() {
  clear || true
  echo -e "${_TEAL}${_B}"
  _line
  printf '  %-62s\n' "vprod — Development Installer"
  printf '  %-62s\n' "Vantage Discord Bot Framework"
  _line
  echo -e "${_R}"
  echo -e "  ${_DIM}Repo dir  :${_R} ${_B}$(pwd)${_R}"
  echo -e "  ${_DIM}Data dir  :${_R} $(pwd)/data  ${_TEAL}(token stored here, gitignored)${_R}"
  echo -e "  ${_DIM}Prefix    :${_R} ${PREFIX}"
  echo
  _line
  echo
}

step() { STEP=$((STEP+1)); echo; echo -e "${_TEAL}${_B}[${STEP}/${TOTAL_STEPS}]${_R} ${_B}${1}${_R}"; _subline; }
ok()   { echo -e "  ${_GREEN}✔${_R}  ${1}"; }
info() { echo -e "  ${_DIM}→${_R}  ${1}"; }
warn() { echo -e "  ${_YELLOW}⚠${_R}  ${1}" >&2; }
die()  { echo -e "  ${_RED}✖${_R}  ${1}" >&2; exit 1; }

on_error() {
  local code=$?
  echo; echo -e "${_RED}${_B}Setup stopped at step ${STEP}/${TOTAL_STEPS}. Exit code: ${code}${_R}"
  exit "${code}"
}
trap on_error ERR

# ── verify we're in the repo root ─────────────────────────────────────────────
[[ -f launcher.py && -f requirements.txt ]] || \
  die "Run this script from the vprod repo root (where launcher.py lives)."

REPO_ROOT="$(pwd)"

validate_token_format() {
  [[ "$1" =~ ^[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}$ ]]
}

# ── steps ─────────────────────────────────────────────────────────────────────

create_venv() {
  if [[ -d venv ]]; then
    ok "venv already exists — upgrading packages"
    venv/bin/pip install --quiet --upgrade pip
    venv/bin/pip install --quiet -r requirements.txt
  else
    info "Creating virtual environment…"
    "${PYTHON}" -m venv venv
    ok "venv created"
    info "Installing requirements…"
    venv/bin/pip install --quiet --upgrade pip
    venv/bin/pip install --quiet -r requirements.txt
    ok "Requirements installed"
  fi
}

prepare_data_dir() {
  mkdir -p data/ext_plugins data/logs data/guilds data/repos
  # Touch a .gitkeep so repos/ is tracked
  touch data/repos/.gitkeep
  ok "data/ directory ready"
}

write_token() {
  local env_file="data/.env"
  local token="${DISCORD_TOKEN:-}"

  if [[ -f "${env_file}" && -z "${token}" ]]; then
    ok "${env_file} already exists — skipping token prompt"
    info "Edit ${env_file} manually to change the token."
    return 0
  fi

  if [[ -z "${token}" ]]; then
    echo
    info "Your token will be stored in ${REPO_ROOT}/data/.env"
    info "This path is gitignored — it will NOT be committed."
    echo
    while true; do
      read -r -s -p "  Enter DISCORD_TOKEN: " token </dev/tty; echo
      [[ -z "${token}" ]] && { warn "Token cannot be empty. Try again."; continue; }
      validate_token_format "${token}" && break
      warn "That doesn't look like a valid Discord bot token."
      warn "Expected: <24+chars>.<6chars>.<27+chars> (three dot-separated segments)."
      info "Get your token: https://discord.com/developers/applications"
      read -r -p "  Try again? [Y/n]: " ans </dev/tty || true
      [[ "${ans:-y}" =~ ^[Nn] ]] && break
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

print_summary() {
  echo
  echo -e "${_TEAL}${_B}"
  _line
  printf '  %-62s\n' "✅  Dev setup complete!"
  _line
  echo -e "${_R}"
  echo -e "  ${_DIM}Start the bot :${_R}"
  echo -e "    ${_B}venv/bin/python launcher.py start${_R}"
  echo
  echo -e "  ${_DIM}Or in debug mode :${_R}"
  echo -e "    ${_B}venv/bin/python launcher.py --debug start${_R}"
  echo
  echo -e "  ${_DIM}Token file   :${_R} data/.env  ${_TEAL}(gitignored, 600)${_R}"
  echo -e "  ${_DIM}Config file  :${_R} data/config.json"
  echo -e "  ${_DIM}Ext plugins  :${_R} data/ext_plugins/"
  echo -e "  ${_DIM}Log files    :${_R} data/logs/vprod.log"
  echo
  echo -e "  ${_DIM}Manage plugins via Discord (once running):${_R}"
  echo -e "    ${_B}${PREFIX}plugin install data/ext_plugins/<plugin>${_R}"
  echo
  _line
  echo
}

# ── main ──────────────────────────────────────────────────────────────────────
main() {
  banner

  step "Create Python virtual environment"
  create_venv

  step "Prepare data directory"
  prepare_data_dir

  step "Store Discord token"
  write_token

  step "Write bot configuration"
  write_config

  step "Summary"
  print_summary
}

main "$@"
