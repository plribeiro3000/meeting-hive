# meeting-hive installer — Windows (Task Scheduler).
#
# STATUS: not implemented yet. Follow the manual steps in
# docs/scheduling.md → "Task Scheduler" until this lands.
#
# Tracking issue: https://github.com/plribeiro3000/meeting-hive/issues

Write-Host @"
meeting-hive: Windows installer is not implemented yet.

Until a dedicated installer lands, follow the manual steps:

  1. Install the package:
       python -m venv .venv
       .venv\Scripts\pip install -e .
       # Add <repo>\bin to PATH so bin\meeting-hive.cmd is reachable.

  2. Generate config:
       meeting-hive init

  3. Schedule via Task Scheduler:
       see docs\scheduling.md

If you'd like to contribute a proper installer, PRs are welcome. See
CONTRIBUTING.md for guidance.
"@
exit 1
