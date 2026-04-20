#!/usr/bin/env bash
# meeting-hive installer — Linux (systemd user timer).
#
# STATUS: not implemented yet. Follow the manual steps in
# docs/scheduling.md → "systemd user timer" until this lands.
#
# Tracking issue: https://github.com/plribeiro3000/meeting-hive/issues

set -euo pipefail

cat <<'EOF'
meeting-hive: Linux installer is not implemented yet.

Until a dedicated installer lands, follow the manual steps:

  1. Install the package:
       pipx install meeting-hive

  2. Generate config:
       meeting-hive init

  3. Schedule via systemd user timer:
       see docs/scheduling.md

If you'd like to contribute a proper installer, PRs are welcome. See
CONTRIBUTING.md for guidance.
EOF
exit 1
