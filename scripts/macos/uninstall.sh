#!/usr/bin/env bash
# meeting-hive uninstaller (macOS) — reverses what scripts/install.sh did.
#
# Default behavior: removes launchd agent and plist. Leaves every byte of
# user data intact. Does not uninstall the meeting-hive Python package —
# use `pipx uninstall meeting-hive` for that.
#
# Flags:
#   --purge            Also deletes config + vocabulary DB + logs.
#                      Never touches ~/.meeting-notes/.
#   --nuke-notes       Also deletes ~/.meeting-notes/ (the archive itself —
#                      data loss). Requires an extra confirmation step:
#                      typed archive path (TTY) or --i-really-mean-it (non-TTY).
#   --i-really-mean-it Extra signal required for --nuke-notes without a TTY.
#   -y, --yes          Skip confirmation prompts for --purge (safe cleanup).
#                      Does NOT bypass the --nuke-notes confirmation.
#   -h, --help         Show this help.
#

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/meeting-hive"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/meeting-hive"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/meeting-hive"
NOTES_DIR="$HOME/.meeting-notes"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
PLIST_LABEL="com.${USER}.meeting-hive"
PLIST_PATH="${LAUNCH_DIR}/${PLIST_LABEL}.plist"

PURGE=0
NUKE_NOTES=0
ASSUME_YES=0
I_REALLY_MEAN_IT=0

c_reset=$'\033[0m'
c_bold=$'\033[1m'
c_green=$'\033[32m'
c_yellow=$'\033[33m'
c_red=$'\033[31m'

log() { printf "%s[uninstall]%s %s\n" "$c_bold" "$c_reset" "$*"; }
ok()  { printf "%s✓%s %s\n" "$c_green" "$c_reset" "$*"; }
warn(){ printf "%s⚠%s %s\n" "$c_yellow" "$c_reset" "$*"; }
err() { printf "%s✗%s %s\n" "$c_red" "$c_reset" "$*" >&2; }

show_help() {
  cat <<'EOF'
Usage: uninstall.sh [OPTIONS]

Default behavior removes:
  - the launchd agent (bootout)
  - the launchd plist file

The meeting-hive Python package is not touched — uninstall it separately
with `pipx uninstall meeting-hive` if you want to remove it fully.

Options:
  --purge             Also delete config + vocabulary DB + logs
                      (~/.config/meeting-hive, ~/.local/share/meeting-hive,
                      ~/.local/state/meeting-hive). Never touches
                      ~/.meeting-notes/.
  --nuke-notes        Also delete ~/.meeting-notes/ (the archive itself —
                      user data). Requires an extra confirmation step:
                      typed archive path (TTY) or --i-really-mean-it (non-TTY).
  --i-really-mean-it  Extra signal required for --nuke-notes in non-TTY mode.
  -y, --yes           Skip --purge confirmation (for automation). Does NOT
                      bypass the --nuke-notes confirmation.
  -h, --help          Show this help.

Any invocation without --help is destructive by design (unloads the launchd
agent, removes the plist). There is no dry-run; back up first if unsure.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --purge)              PURGE=1; shift ;;
    --nuke-notes)         NUKE_NOTES=1; shift ;;
    --i-really-mean-it)   I_REALLY_MEAN_IT=1; shift ;;
    -y|--yes)             ASSUME_YES=1; shift ;;
    -h|--help)            show_help; exit 0 ;;
    *) err "Unknown flag: $1"; show_help; exit 1 ;;
  esac
done

IS_TTY=0
[ -t 0 ] && IS_TTY=1

confirm() {
  local prompt="$1"
  if [ "$ASSUME_YES" = "1" ]; then
    return 0
  fi
  if [ "$IS_TTY" != "1" ]; then
    err "Non-interactive mode requires --yes to confirm: $prompt"
    exit 1
  fi
  printf "%s [y/N]: " "$prompt"
  read -r ans
  case "$ans" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

# -----------------------------------------------------------------------------
# 1. launchd agent + plist
# -----------------------------------------------------------------------------
log "Unloading launchd agent..."
if launchctl print "gui/$(id -u)/${PLIST_LABEL}" >/dev/null 2>&1; then
  launchctl bootout "gui/$(id -u)/${PLIST_LABEL}" 2>/dev/null || true
  ok "Unloaded $PLIST_LABEL"
else
  ok "No launchd agent loaded (nothing to unload)"
fi

if [ -f "$PLIST_PATH" ]; then
  rm -f "$PLIST_PATH"
  ok "Removed $PLIST_PATH"
fi

# -----------------------------------------------------------------------------
# 2. --purge: config + data + state
# -----------------------------------------------------------------------------
if [ "$PURGE" = "1" ]; then
  echo
  warn "--purge will delete:"
  [ -d "$CONFIG_DIR" ] && warn "  $CONFIG_DIR  (config.yaml + secrets.env)"
  [ -d "$DATA_DIR" ]   && warn "  $DATA_DIR  (vocabulary.db)"
  [ -d "$STATE_DIR" ]  && warn "  $STATE_DIR  (logs)"
  if confirm "Proceed with --purge?"; then
    [ -d "$CONFIG_DIR" ] && rm -rf "$CONFIG_DIR" && ok "Removed $CONFIG_DIR"
    [ -d "$DATA_DIR" ]   && rm -rf "$DATA_DIR"   && ok "Removed $DATA_DIR"
    [ -d "$STATE_DIR" ]  && rm -rf "$STATE_DIR"  && ok "Removed $STATE_DIR"
  else
    warn "Skipped --purge"
  fi
fi

# -----------------------------------------------------------------------------
# 3. --nuke-notes: the archive itself (DATA LOSS — extra confirmation required)
# -----------------------------------------------------------------------------
if [ "$NUKE_NOTES" = "1" ]; then
  echo
  err "--nuke-notes will DELETE the meeting archive at $NOTES_DIR"
  err "This is user data. Make sure you have a backup."
  if [ "$IS_TTY" = "1" ]; then
    printf "Type the archive path to confirm (%s): " "$NOTES_DIR"
    read -r typed
    if [ "$typed" != "$NOTES_DIR" ]; then
      err "Path mismatch — aborting. Nothing deleted."
      exit 1
    fi
  else
    if [ "$I_REALLY_MEAN_IT" != "1" ]; then
      err "--nuke-notes in non-TTY mode requires --i-really-mean-it"
      exit 1
    fi
  fi

  if [ -d "$NOTES_DIR" ]; then
    rm -rf "$NOTES_DIR"
    ok "Removed $NOTES_DIR"
  else
    ok "No archive found at $NOTES_DIR"
  fi
fi

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------
echo
ok "meeting-hive uninstalled."

if [ "$PURGE" != "1" ]; then
  remaining=()
  [ -d "$CONFIG_DIR" ] && remaining+=("$CONFIG_DIR")
  [ -d "$DATA_DIR" ]   && remaining+=("$DATA_DIR")
  [ -d "$STATE_DIR" ]  && remaining+=("$STATE_DIR")
  if [ ${#remaining[@]} -gt 0 ]; then
    log "Kept (pass --purge to remove):"
    for d in "${remaining[@]}"; do log "  $d"; done
  fi
fi

if [ "$NUKE_NOTES" != "1" ] && [ -d "$NOTES_DIR" ]; then
  log "Meeting archive preserved at: $NOTES_DIR"
fi
