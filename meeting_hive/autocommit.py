"""meeting-hive-autocommit — wrap sync with a local git commit of the archive.

Runs ``meeting-hive sync`` and then commits any changes under
``~/.meeting-notes/`` to a local-only git repository. Empty syncs produce
no commit. Nothing is pushed anywhere. Git history here is a
versioning / diff / rollback tool — not a backup; see the README.

First run initializes the repo. Subsequent runs commit only when the sync
produced changes. ``--dry-run`` skips the commit step.
"""

from __future__ import annotations

import datetime
import subprocess
import sys
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]

    # Resolve the sibling meeting-hive entry point by absolute path. launchd
    # runs this wrapper with a minimal PATH that does not include the pipx
    # venv's bin dir, so relying on name-only lookup breaks the scheduled run.
    meeting_hive_bin = str(Path(sys.executable).parent / "meeting-hive")

    sync_rc = subprocess.run([meeting_hive_bin, "sync", *args], check=False).returncode
    if sync_rc != 0:
        return sync_rc

    if "--dry-run" in args:
        return 0

    notes_dir = Path.home() / ".meeting-notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    if not (notes_dir / ".git").is_dir():
        subprocess.run(
            ["git", "init", "--quiet", "--initial-branch=main"],
            cwd=notes_dir,
            check=True,
        )

    for key, fallback in (
        ("user.email", "meeting-hive@localhost"),
        ("user.name", "meeting-hive"),
    ):
        current = subprocess.run(
            ["git", "config", key], cwd=notes_dir, capture_output=True, check=False
        )
        if current.returncode != 0 or not current.stdout.strip():
            subprocess.run(["git", "config", key, fallback], cwd=notes_dir, check=True)

    subprocess.run(["git", "add", "-A"], cwd=notes_dir, check=True)

    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=notes_dir, check=False)
    if diff.returncode == 0:
        return 0

    today = datetime.date.today().isoformat()
    subprocess.run(
        ["git", "commit", "--quiet", "-m", f"sync {today}"],
        cwd=notes_dir,
        check=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
