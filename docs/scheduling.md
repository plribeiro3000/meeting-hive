# Scheduling

meeting-hive is a batch job: you schedule `meeting-hive sync` to run on a cadence (nightly is typical) and let it work while you're away. The scheduling mechanism is OS-specific; the macOS installer handles launchd for you, Linux and Windows users pick their own.

All examples assume `meeting-hive` is on `PATH`. If you installed via the steps in the README, that means `~/.local/bin/meeting-hive` (Linux) or the equivalent on Windows.

## Local git history (optional, recommended)

The macOS installer schedules a wrapper (`meeting-hive-autocommit`) that runs `meeting-hive sync` and then commits any archive changes to a local-only git repo under `~/.meeting-notes/.git/`. This gives you daily diffs and one-command rollback. See [the README](../README.md#local-history-git) for the rationale and the explicit reminder that git history is not a backup.

Linux and Windows users can replicate the behavior with a tiny wrapper and point their scheduler at it instead of `meeting-hive sync`:

**Linux/macOS shell** — save as `~/.local/bin/meeting-hive-autocommit` and `chmod +x`:

```bash
#!/usr/bin/env bash
set -euo pipefail
NOTES_DIR="$HOME/.meeting-notes"
meeting-hive sync "$@"
for arg in "$@"; do [ "$arg" = "--dry-run" ] && exit 0; done
mkdir -p "$NOTES_DIR" && cd "$NOTES_DIR"
[ -d .git ] || git init --quiet --initial-branch=main
git config user.email >/dev/null 2>&1 || git config user.email "meeting-hive@localhost"
git config user.name  >/dev/null 2>&1 || git config user.name  "meeting-hive"
git add -A
git diff --cached --quiet || git commit --quiet -m "sync $(date +%Y-%m-%d)"
```

**Windows PowerShell** — save as `meeting-hive-autocommit.ps1`:

```powershell
param([Parameter(ValueFromRemainingArguments=$true)]$args)
$NotesDir = Join-Path $env:USERPROFILE ".meeting-notes"
& meeting-hive sync @args
if ($args -contains "--dry-run") { exit 0 }
New-Item -ItemType Directory -Force -Path $NotesDir | Out-Null
Push-Location $NotesDir
if (-not (Test-Path ".git")) { git init --quiet --initial-branch=main }
if (-not (git config user.email)) { git config user.email "meeting-hive@localhost" }
if (-not (git config user.name))  { git config user.name  "meeting-hive" }
git add -A
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) { git commit --quiet -m "sync $(Get-Date -Format yyyy-MM-dd)" }
Pop-Location
```

In the examples below, swap `meeting-hive sync` for the wrapper if you want the auto-commit behavior.

## macOS — launchd (handled by the installer)

`./scripts/install.sh` renders a launchd plist and loads it. Default is Mon-Fri midnight local time. To change the schedule:

```bash
./scripts/install.sh --hour 4 --minute 30 --days 1-5
```

See the [README](../README.md#schedule) for the full flag reference.

## Linux — systemd user timer (recommended on modern distros)

Systemd timers support wall-clock scheduling with timezone awareness via `OnCalendar=`. This is the cleaner option if your distro ships systemd (Ubuntu, Fedora, Arch, Debian, etc.).

Create the service unit at `~/.config/systemd/user/meeting-hive.service`:

```ini
[Unit]
Description=meeting-hive sync
After=network-online.target

[Service]
Type=oneshot
ExecStart=%h/.local/bin/meeting-hive sync
# Optional: increase if your runs need more than the default 90s.
TimeoutStartSec=10min
```

Create the timer unit at `~/.config/systemd/user/meeting-hive.timer`:

```ini
[Unit]
Description=meeting-hive nightly sync

[Timer]
# Mon-Fri at 00:00 local time.
OnCalendar=Mon..Fri *-*-* 00:00:00
Persistent=true                # if the machine was off, run on next boot

[Install]
WantedBy=timers.target
```

Enable and start:

```bash
systemctl --user daemon-reload
systemctl --user enable --now meeting-hive.timer
systemctl --user list-timers meeting-hive.timer   # verify next fire
```

Logs: `journalctl --user -u meeting-hive.service`.

To change the schedule, edit the `OnCalendar=` line and `systemctl --user daemon-reload && systemctl --user restart meeting-hive.timer`.

See `man systemd.time(7)` for `OnCalendar` format details.

## Linux — cron (fallback)

For systems without systemd user sessions (minimal servers, WSL, etc.):

```bash
crontab -e
```

Add:

```
# Mon-Fri at 00:00 local time.
0 0 * * 1-5   $HOME/.local/bin/meeting-hive sync >> $HOME/.local/state/meeting-hive/cron.log 2>&1
```

Notes:
- cron uses the system's local timezone (set by `/etc/timezone` or `TZ=`).
- Expand `$HOME` or hardcode the absolute path — cron's `$HOME` isn't always populated.
- Redirect output to a log file you can tail; cron emails on stderr by default, which is rarely useful.

## Windows — Task Scheduler

Create the task via PowerShell (run as your user; no admin rights needed):

```powershell
$action = New-ScheduledTaskAction `
    -Execute "meeting-hive.exe" `
    -Argument "sync"

# Mon-Fri at 00:00 local time.
$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At 00:00

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries

Register-ScheduledTask `
    -TaskName "meeting-hive sync" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings
```

Adjust the `meeting-hive.exe` path if it's not on your PATH (use the full venv shim path).

Verify:

```powershell
Get-ScheduledTask -TaskName "meeting-hive sync" | Get-ScheduledTaskInfo
```

Task Scheduler interprets `-At 00:00` in the local time zone. Logs go to Event Viewer → Applications and Services Logs → Microsoft → Windows → TaskScheduler.

To change the schedule, re-register with different `-DaysOfWeek` / `-At`, or unregister and repeat:

```powershell
Unregister-ScheduledTask -TaskName "meeting-hive sync" -Confirm:$false
```

## Timezone sanity

All three schedulers above interpret times in the **machine's local timezone**. meeting-hive itself also renders meeting timestamps in local time (see `docs/architecture.md`). Moving the machine to another timezone just works — no reconfiguration needed.
