"""macOS launchd agent generation (M11).

APScheduler only fires while the process is alive. On a laptop that is the weak link
in the whole automation story: close the lid over `RUN_HOUR`, reboot, or let the
terminal running `start-scheduler` get closed, and the day is silently skipped.

launchd fixes the durable half — it starts the agent at login and restarts it if it
dies. `scheduler.jobs.catch_up_if_missed` fixes the other half, running the pipeline
immediately when the machine was asleep at the scheduled hour.

`StartCalendarInterval` is deliberately *not* used: the pipeline needs a real desktop
session for the headed browser, and keeping the schedule inside the app means the
Settings page stays the single place that owns `RUN_HOUR`.
"""

from __future__ import annotations

import sys
from pathlib import Path

LABEL = "com.jobhunter.scheduler"


def agent_path() -> Path:
    """Where the per-user LaunchAgent plist belongs."""
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def build_plist(
    *,
    working_dir: Path | None = None,
    python: str | None = None,
    log_dir: Path | None = None,
) -> str:
    """Render the LaunchAgent plist that keeps the scheduler daemon alive."""
    working_dir = (working_dir or Path.cwd()).resolve()
    python = python or sys.executable
    log_dir = (log_dir or working_dir / "logs").resolve()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>-m</string>
        <string>app.main</string>
        <string>start-scheduler</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{working_dir}</string>
    <!-- Start at login and restart if the daemon ever exits. -->
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>60</integer>
    <key>StandardOutPath</key>
    <string>{log_dir}/scheduler.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/scheduler.error.log</string>
    <key>ProcessType</key>
    <string>Interactive</string>
</dict>
</plist>
"""


def install(
    *,
    working_dir: Path | None = None,
    python: str | None = None,
    log_dir: Path | None = None,
) -> Path:
    """Write the plist and return its path. Loading it is left to the caller."""
    working_dir = (working_dir or Path.cwd()).resolve()
    log_dir = (log_dir or working_dir / "logs").resolve()
    log_dir.mkdir(parents=True, exist_ok=True)

    path = agent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_plist(working_dir=working_dir, python=python, log_dir=log_dir))
    return path
