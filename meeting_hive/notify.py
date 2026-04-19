"""Cross-platform desktop notifications.

Best-effort: if the underlying mechanism isn't available (missing binary,
broken DBus session, etc.) we log and return silently — notifications are
secondary UX, never a blocker for the pipeline.
"""

from __future__ import annotations

import logging
import subprocess
import sys

log = logging.getLogger(__name__)


def notify(title: str, message: str, sound: str = "Glass") -> None:
    """Fire a desktop banner notification. Silent on failure."""
    try:
        if sys.platform == "darwin":
            _notify_macos(title, message, sound)
        elif sys.platform.startswith("linux"):
            _notify_linux(title, message)
        elif sys.platform == "win32":
            _notify_windows(title, message)
        else:
            log.info("Notify [%s]: %s", title, message)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
        log.warning("Notification failed: %s", e)


def _notify_macos(title: str, message: str, sound: str) -> None:
    title_safe = title.replace('"', '\\"')
    msg_safe = message.replace('"', '\\"').replace("\n", " — ")
    script = f'display notification "{msg_safe}" with title "{title_safe}" sound name "{sound}"'
    subprocess.run(["osascript", "-e", script], check=True, capture_output=True)


def _notify_linux(title: str, message: str) -> None:
    # notify-send is libnotify's CLI, present on all major desktop distros.
    subprocess.run(
        ["notify-send", "--app-name=meeting-hive", title, message],
        check=True,
        capture_output=True,
    )


def _notify_windows(title: str, message: str) -> None:
    # Use Windows Runtime toast notifications via PowerShell. No extra deps.
    title_safe = title.replace("'", "''")
    msg_safe = message.replace("'", "''").replace("\n", " — ")
    ps = (
        "[void][Windows.UI.Notifications.ToastNotificationManager,"
        "Windows.UI.Notifications,ContentType=WindowsRuntime];"
        "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(1);"
        f"$t.GetElementsByTagName('text')[0].AppendChild($t.CreateTextNode('{title_safe}'))|Out-Null;"
        f"$t.GetElementsByTagName('text')[1].AppendChild($t.CreateTextNode('{msg_safe}'))|Out-Null;"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('meeting-hive')"
        ".Show([Windows.UI.Notifications.ToastNotification]::new($t))"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        check=True,
        capture_output=True,
    )
