#!/usr/bin/env bash
# meeting-hive installer — idempotent setup for macOS.
#
# What it does:
#   1. Verifies prereqs (macOS, Python 3.11+, meeting-hive-autocommit on PATH)
#   2. Collects adapter choices + scope + internal domains (flags preferred,
#      TTY prompts as fallback, sensible defaults when non-interactive)
#   3. Calls `meeting-hive init` to generate config.yaml
#   4. Prompts for the summarizer's API key (unless --skip-secrets), writes to
#      ~/.config/meeting-hive/secrets.env (chmod 600)
#   5. Renders the launchd plist pointing at the autocommit binary (schedule
#      from --hour/--minute/--days) and loads it
#
# Prerequisite: install meeting-hive itself first with `pipx install meeting-hive`.
# This script does not install the Python package — it only handles the
# macOS-specific launchd registration.
#
# Interactive mode: run with `--summarizer NAME` (or no flags) and the
# installer prompts for the rest. Unattended mode (for AI agents / CI): pass
# every adapter flag plus --skip-secrets so the installer never blocks on
# input. See `install.sh --help`.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/meeting-hive"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/meeting-hive"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
PLIST_LABEL="com.${USER}.meeting-hive"
PLIST_PATH="${LAUNCH_DIR}/${PLIST_LABEL}.plist"

# Schedule defaults (overridable via flags). Midnight local time, Mon-Fri.
HOUR=0
MINUTE=0
DAYS="1-5"

# Summarizer — no default. Must be picked via flag or interactive prompt.
SUMMARIZER=""

# Adapter / scope choices. If blank, the installer prompts (TTY) or falls back
# to sensible defaults (non-TTY).
SOURCE=""
SOURCE_PATH=""
VOCAB=""
SCOPE=""
INTERNAL_DOMAINS=""

# Unattended mode. If set, the installer never prompts for API keys — it
# prints the command the user (or another agent) should run to add them.
SKIP_SECRETS=0

c_reset=$'\033[0m'
c_bold=$'\033[1m'
c_green=$'\033[32m'
c_yellow=$'\033[33m'
c_red=$'\033[31m'

log() { printf "%s[install]%s %s\n" "$c_bold" "$c_reset" "$*"; }
ok()  { printf "%s✓%s %s\n" "$c_green" "$c_reset" "$*"; }
warn(){ printf "%s⚠%s %s\n" "$c_yellow" "$c_reset" "$*"; }
err() { printf "%s✗%s %s\n" "$c_red" "$c_reset" "$*" >&2; }

prompt_and_write_secret() {
  local var_name="$1"
  local context="$2"
  local url="$3"

  if grep -q "^${var_name}=" "$CONFIG_DIR/secrets.env" 2>/dev/null; then
    ok "$CONFIG_DIR/secrets.env already has ${var_name} (untouched)"
    return
  fi

  # Unattended: either --skip-secrets was passed or stdin isn't a TTY (so we
  # can't prompt anyway). Print the exact command the user needs to run.
  if [ "$SKIP_SECRETS" = "1" ] || [ "$IS_TTY" != "1" ]; then
    warn "${var_name} not set — needed for ${context}."
    warn "Get one at ${url}, then run:"
    warn "  echo '${var_name}=...' >> $CONFIG_DIR/secrets.env && chmod 600 $CONFIG_DIR/secrets.env"
    return
  fi

  echo
  log "${var_name} needed for ${context}."
  log "Get one at ${url}"
  printf "Paste your %s (or press Enter to skip and set it later): " "$var_name"
  read -r -s secret
  echo
  if [ -n "$secret" ]; then
    umask 077
    if [ -f "$CONFIG_DIR/secrets.env" ]; then
      printf "%s=%s\n" "$var_name" "$secret" >> "$CONFIG_DIR/secrets.env"
    else
      printf "%s=%s\n" "$var_name" "$secret" > "$CONFIG_DIR/secrets.env"
    fi
    chmod 600 "$CONFIG_DIR/secrets.env"
    ok "Wrote ${var_name} to $CONFIG_DIR/secrets.env (chmod 600)"
  else
    warn "No ${var_name} provided. Add it before first run:"
    warn "  echo '${var_name}=...' >> $CONFIG_DIR/secrets.env && chmod 600 $CONFIG_DIR/secrets.env"
  fi
}

show_help() {
  cat <<'EOF'
Usage: install.sh [OPTIONS]

Adapter choices (all required for a fully unattended install):
  --summarizer NAME       anthropic | openai | ollama (no default)
  --source NAME           granola | fathom | markdown (default: granola)
  --source-path PATH      required when --source=markdown
  --vocabulary NAME       sqlite | wispr (default: sqlite)
  --scope NAME            archive subfolder under ~/.meeting-notes/ (default: work)
  --internal-domains LIST comma-separated (default: empty)

Schedule (macOS launchd):
  --hour HOUR             0-23 local time (default: 0)
  --minute MINUTE         0-59 (default: 0)
  --days DAYS             range "1-5" or list "1,3,5"
                          launchd weekdays: 0/7=Sun, 1=Mon, ..., 6=Sat
                          (default: 1-5)

Secrets:
  --skip-secrets          Don't prompt for API keys. After install, the user
                          adds the appropriate KEY=value lines to
                          ~/.config/meeting-hive/secrets.env themselves.
                          Useful for AI-agent / CI / unattended flows.

  -h, --help              Show this help

Interactive mode (TTY): any missing --summarizer / --source / --vocabulary /
--scope / --internal-domains is prompted. Non-TTY: missing --summarizer is a
hard error; the rest fall back to defaults.

Re-running with different flags regenerates and reloads the launchd plist.
EOF
}

# -----------------------------------------------------------------------------
# Parse flags
# -----------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --summarizer)        SUMMARIZER="$2"; shift 2 ;;
    --source)            SOURCE="$2"; shift 2 ;;
    --source-path)       SOURCE_PATH="$2"; shift 2 ;;
    --vocabulary)        VOCAB="$2"; shift 2 ;;
    --scope)             SCOPE="$2"; shift 2 ;;
    --internal-domains)  INTERNAL_DOMAINS="$2"; shift 2 ;;
    --skip-secrets)      SKIP_SECRETS=1; shift ;;
    --hour)              HOUR="$2"; shift 2 ;;
    --minute)            MINUTE="$2"; shift 2 ;;
    --days)              DAYS="$2"; shift 2 ;;
    -h|--help)           show_help; exit 0 ;;
    *) err "Unknown flag: $1"; show_help; exit 1 ;;
  esac
done

IS_TTY=0
[ -t 0 ] && IS_TTY=1

if ! [[ "$HOUR" =~ ^[0-9]+$ ]] || (( HOUR > 23 )); then
  err "--hour must be 0-23, got: $HOUR"; exit 1
fi
if ! [[ "$MINUTE" =~ ^[0-9]+$ ]] || (( MINUTE > 59 )); then
  err "--minute must be 0-59, got: $MINUTE"; exit 1
fi
if ! [[ "$DAYS" =~ ^[0-9]+(-[0-9]+|(,[0-9]+)*)$ ]]; then
  err "--days must be a range like '1-5' or a list like '1,3,5', got: $DAYS"; exit 1
fi

# Summarizer: required. Prompt on TTY if missing; error on non-TTY.
if [ -z "$SUMMARIZER" ]; then
  if [ "$IS_TTY" = "1" ]; then
    echo
    log "Pick a summarizer backend:"
    log "  1) anthropic  — Claude models via Anthropic API (requires API key)"
    log "  2) openai     — GPT / o-series via OpenAI API (requires API key)"
    log "  3) ollama     — Local LLM via Ollama (no API key, requires Ollama running)"
    printf "Choice [1-3]: "
    read -r choice
    case "$choice" in
      1) SUMMARIZER=anthropic ;;
      2) SUMMARIZER=openai ;;
      3) SUMMARIZER=ollama ;;
      *) err "invalid choice: $choice"; exit 1 ;;
    esac
  else
    err "--summarizer is required in non-interactive mode. Pass --summarizer anthropic|openai|ollama."
    exit 1
  fi
fi

case "$SUMMARIZER" in
  anthropic|openai|ollama) ;;
  *) err "--summarizer must be one of: anthropic, openai, ollama. Got: $SUMMARIZER"; exit 1 ;;
esac
ok "Summarizer: $SUMMARIZER"

# -----------------------------------------------------------------------------
# 1. Prereqs
# -----------------------------------------------------------------------------
log "Checking prerequisites..."

if [ "$(uname)" != "Darwin" ]; then
  err "meeting-hive currently supports macOS only (found: $(uname))."
  exit 1
fi
ok "macOS detected"

PYTHON=""
for candidate in python3.13 python3.12 python3.11; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  err "Python 3.11+ not found. Install via Homebrew: brew install python@3.13"
  exit 1
fi
ok "Python: $($PYTHON --version) ($PYTHON)"

# meeting-hive is adapter-driven — source and vocabulary backends are chosen in
# config.yaml. Installed apps are discovered lazily at run time; the adapter
# raises a clear error if its backend isn't available. No per-app prechecks here.

# -----------------------------------------------------------------------------
# 2. Locate meeting-hive-autocommit
# -----------------------------------------------------------------------------
# Requires meeting-hive installed on PATH (via pipx or pip). Installing the
# Python package is the user's job — this script owns only the macOS
# launchd registration.
log "Locating meeting-hive-autocommit..."
if ! AUTOCOMMIT_BIN=$(command -v meeting-hive-autocommit 2>/dev/null); then
  err "meeting-hive-autocommit not on PATH. Install it first:"
  err "  pipx install meeting-hive"
  exit 1
fi
ok "Found $AUTOCOMMIT_BIN"

# -----------------------------------------------------------------------------
# 3. Config + secrets
# -----------------------------------------------------------------------------
log "Setting up config directory..."
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"

if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
  # For each choice: flag wins; else TTY prompt; else sensible default.

  if [ -z "$SOURCE" ]; then
    if [ "$IS_TTY" = "1" ]; then
      echo
      log "Pick a meeting source:"
      log "  1) granola   — Granola desktop app (local cache + REST)"
      log "  2) fathom    — Fathom via its public REST API (requires API key)"
      log "  3) markdown  — directory of YAML-frontmatter .md files"
      printf "Choice [1-3, default 1]: "
      read -r choice
      case "${choice:-1}" in
        1) SOURCE=granola ;;
        2) SOURCE=fathom ;;
        3) SOURCE=markdown ;;
        *) err "invalid choice: $choice"; exit 1 ;;
      esac
    else
      SOURCE=granola
    fi
  fi
  case "$SOURCE" in
    granola|fathom|markdown) ;;
    *) err "--source must be one of: granola, fathom, markdown. Got: $SOURCE"; exit 1 ;;
  esac

  if [ "$SOURCE" = "markdown" ] && [ -z "$SOURCE_PATH" ]; then
    if [ "$IS_TTY" = "1" ]; then
      printf "Path to meetings directory: "
      read -r SOURCE_PATH
    else
      err "--source-path is required when --source=markdown in non-interactive mode"
      exit 1
    fi
  fi

  if [ -z "$VOCAB" ]; then
    if [ "$IS_TTY" = "1" ]; then
      echo
      log "Pick a vocabulary source:"
      log "  1) sqlite    — local DB managed by meeting-hive (recommended)"
      log "  2) wispr     — Wispr Flow's dictionary (only if you already use it)"
      printf "Choice [1-2, default 1]: "
      read -r choice
      case "${choice:-1}" in
        1) VOCAB=sqlite ;;
        2) VOCAB=wispr ;;
        *) err "invalid choice: $choice"; exit 1 ;;
      esac
    else
      VOCAB=sqlite
    fi
  fi
  case "$VOCAB" in
    sqlite|wispr) ;;
    *) err "--vocabulary must be one of: sqlite, wispr. Got: $VOCAB"; exit 1 ;;
  esac

  if [ -z "$SCOPE" ]; then
    if [ "$IS_TTY" = "1" ]; then
      echo
      printf "Archive scope (subfolder under ~/.meeting-notes/) [work]: "
      read -r SCOPE
    fi
    SCOPE="${SCOPE:-work}"
  fi

  # internal_domains is optional — only prompt on TTY.
  if [ -z "$INTERNAL_DOMAINS" ] && [ "$IS_TTY" = "1" ]; then
    printf "Internal email domains (comma-separated, empty to skip — e.g. 'mycompany.com,myco.co.uk'): "
    read -r INTERNAL_DOMAINS
  fi

  INIT_ARGS=(--summarizer "$SUMMARIZER" --source "$SOURCE" --vocabulary "$VOCAB" --scope "$SCOPE")
  [ -n "$SOURCE_PATH" ] && INIT_ARGS+=(--source-path "$SOURCE_PATH")
  [ -n "$INTERNAL_DOMAINS" ] && INIT_ARGS+=(--internal-domains "$INTERNAL_DOMAINS")

  meeting-hive init "${INIT_ARGS[@]}"
  ok "Generated $CONFIG_DIR/config.yaml"
else
  ok "$CONFIG_DIR/config.yaml already exists (untouched). Re-run with \`meeting-hive init --force\` to regenerate."
fi

# Per-summarizer secret setup
case "$SUMMARIZER" in
  anthropic)
    prompt_and_write_secret ANTHROPIC_API_KEY \
      "the ${SUMMARIZER} summarizer" \
      "https://console.anthropic.com/settings/keys"
    ;;
  openai)
    prompt_and_write_secret OPENAI_API_KEY \
      "the ${SUMMARIZER} summarizer" \
      "https://platform.openai.com/api-keys"
    ;;
  ollama)
    ok "ollama: no API key needed. Make sure the Ollama server is running at run time."
    ;;
esac

# Per-source secret setup
case "$SOURCE" in
  fathom)
    prompt_and_write_secret FATHOM_API_KEY \
      "the ${SOURCE} source" \
      "https://developers.fathom.ai/"
    ;;
esac

# -----------------------------------------------------------------------------
# 4. launchd agent
# -----------------------------------------------------------------------------
log "Configuring launchd agent..."
mkdir -p "$LAUNCH_DIR"
mkdir -p "$STATE_DIR"

TEMPLATE="$REPO/launchd/com.USER.meeting-hive.plist"
if [ ! -f "$TEMPLATE" ]; then
  err "launchd template not found at $TEMPLATE"
  exit 1
fi

# If the plist is already loaded, unload first so we can replace it.
if launchctl print "gui/$(id -u)/${PLIST_LABEL}" >/dev/null 2>&1; then
  launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
  ok "Unloaded previous $PLIST_LABEL"
fi

MH_USER="$USER" \
MH_HOME="$HOME" \
MH_BIN="$AUTOCOMMIT_BIN" \
MH_HOUR="$HOUR" \
MH_MINUTE="$MINUTE" \
MH_DAYS="$DAYS" \
MH_TEMPLATE="$TEMPLATE" \
MH_OUTPUT="$PLIST_PATH" \
"$PYTHON" - <<'PYEOF'
import os, re, sys

hour = int(os.environ["MH_HOUR"])
minute = int(os.environ["MH_MINUTE"])
days_spec = os.environ["MH_DAYS"]

if re.fullmatch(r"\d+-\d+", days_spec):
    a, b = days_spec.split("-")
    days = list(range(int(a), int(b) + 1))
else:
    days = [int(d) for d in days_spec.split(",")]

for d in days:
    if not (0 <= d <= 7):
        sys.exit(f"Invalid weekday {d} in --days (expected 0-7)")

# Dedupe while preserving order.
seen = set()
days = [d for d in days if not (d in seen or seen.add(d))]

entries = "\n".join(
    f"""        <dict>
            <key>Weekday</key>
            <integer>{d}</integer>
            <key>Hour</key>
            <integer>{hour}</integer>
            <key>Minute</key>
            <integer>{minute}</integer>
        </dict>"""
    for d in days
)

with open(os.environ["MH_TEMPLATE"]) as f:
    content = f.read()
content = content.replace("__USER__", os.environ["MH_USER"])
content = content.replace("__HOME__", os.environ["MH_HOME"])
content = content.replace("__BIN__", os.environ["MH_BIN"])
content = content.replace("__SCHEDULE_ENTRIES__", entries)

with open(os.environ["MH_OUTPUT"], "w") as f:
    f.write(content)
PYEOF
chmod 644 "$PLIST_PATH"
ok "Rendered $PLIST_PATH (hour=$HOUR, minute=$MINUTE, days=$DAYS)"

launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
ok "Loaded $PLIST_LABEL"

NEXT_FIRE=$(launchctl print "gui/$(id -u)/${PLIST_LABEL}" 2>/dev/null | grep -E "next fire" | head -1 || true)
if [ -n "$NEXT_FIRE" ]; then
  ok "$NEXT_FIRE"
fi

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------
echo
ok "meeting-hive installed."
echo
log "Next steps:"
printf "  1. Edit %s to pick source + vocabulary adapters and add your entities.\n" "$CONFIG_DIR/config.yaml"
printf "     Summarizer is already set to %s%s%s.\n" "$c_bold" "$SUMMARIZER" "$c_reset"
printf "  2. (Optional, if vocabulary.adapter=sqlite) seed your dictionary:\n"
printf "       %smeeting-hive vocab import wispr%s            # from Wispr Flow\n" "$c_bold" "$c_reset"
printf "       %smeeting-hive vocab import yaml file.yaml%s   # from a YAML file\n" "$c_bold" "$c_reset"
printf "       %smeeting-hive vocab add \"Post Grass\" \"Postgres\"%s   # one at a time\n" "$c_bold" "$c_reset"
printf "  3. Dry-run to validate: %smeeting-hive sync --since 7 --dry-run --verbose%s\n" "$c_bold" "$c_reset"
printf "  4. Run for real once: %smeeting-hive sync --since 7%s\n" "$c_bold" "$c_reset"
printf "  5. From then on, launchd runs it automatically on schedule (days=%s, %02d:%02d).\n" "$DAYS" "$HOUR" "$MINUTE"
printf "     To change the schedule: re-run install.sh with --hour / --minute / --days.\n"
printf "     To switch summarizer: re-run install.sh with --summarizer NAME (and edit config.yaml).\n"
