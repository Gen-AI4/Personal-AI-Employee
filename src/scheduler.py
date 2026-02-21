"""
Scheduler - Manages periodic and scheduled task execution.

Provides a lightweight cron-like scheduling system that:
1. Runs periodic tasks (dashboard refresh, inbox processing)
2. Supports daily scheduled tasks (morning briefing, LinkedIn posting)
3. Generates platform-specific scheduling configs (cron, Windows Task Scheduler)

Silver tier requirement: Basic scheduling via cron or Task Scheduler.
"""

import os
import json
import logging
import threading
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Callable

from log_utils import log_file_lock as _log_lock

logger = logging.getLogger(__name__)

VAULT_PATH = os.getenv("VAULT_PATH", "./vault")


class ScheduledTask:
    """Represents a single scheduled task with its configuration."""

    def __init__(
        self,
        name: str,
        callback: Callable,
        interval_seconds: int = None,
        run_at_hour: int = None,
        run_at_minute: int = 0,
        description: str = "",
    ):
        """
        Args:
            name: Unique task identifier
            callback: Function to call when task runs
            interval_seconds: Run every N seconds (periodic mode)
            run_at_hour: Run daily at this hour UTC (daily mode)
            run_at_minute: Run daily at this minute UTC (daily mode)
            description: Human-readable description
        """
        self.name = name
        self.callback = callback
        self.interval_seconds = interval_seconds
        self.run_at_hour = run_at_hour
        self.run_at_minute = run_at_minute
        self.description = description
        self.last_run: datetime | None = None
        self.run_count: int = 0
        self.error_count: int = 0

    def should_run(self, now: datetime) -> bool:
        """Determine if this task should run at the given time."""
        if self.interval_seconds:
            if self.last_run is None:
                return True
            elapsed = (now - self.last_run).total_seconds()
            return elapsed >= self.interval_seconds

        if self.run_at_hour is not None:
            if self.last_run and self.last_run.date() == now.date():
                return False  # Already ran today
            return (
                now.hour == self.run_at_hour
                and now.minute >= self.run_at_minute
            )

        return False

    def execute(self) -> bool:
        """Execute the task callback. Returns True on success."""
        try:
            self.callback()
            self.last_run = datetime.now(timezone.utc)
            self.run_count += 1
            logger.info(f"Scheduled task '{self.name}' completed (run #{self.run_count})")
            return True
        except Exception as e:
            self.error_count += 1
            logger.error(f"Scheduled task '{self.name}' failed: {e}")
            return False


class Scheduler:
    """Lightweight cron-like scheduler for the AI Employee.

    Manages a collection of ScheduledTasks and runs them
    based on their interval or daily schedule configuration.
    """

    def __init__(self, vault_path: str = VAULT_PATH):
        self.vault_path = Path(vault_path)
        self.logs_dir = self.vault_path / "Logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._tasks: dict[str, ScheduledTask] = {}
        self._running = False
        self._stop_event = threading.Event()

    def add_task(self, task: ScheduledTask) -> None:
        """Register a scheduled task."""
        self._tasks[task.name] = task
        logger.info(
            f"Registered task: '{task.name}' - {task.description}"
        )

    def remove_task(self, name: str) -> None:
        """Remove a scheduled task by name."""
        self._tasks.pop(name, None)

    def get_tasks(self) -> dict[str, ScheduledTask]:
        """Return all registered tasks."""
        return dict(self._tasks)

    def check_and_run(self) -> list[str]:
        """Check all tasks and run those that are due.

        Returns list of task names that were executed.
        """
        now = datetime.now(timezone.utc)
        executed = []

        for name, task in self._tasks.items():
            if task.should_run(now):
                success = task.execute()
                self._log(
                    "scheduled_task_executed" if success else "scheduled_task_failed",
                    {
                        "task_name": name,
                        "run_count": task.run_count,
                        "error_count": task.error_count,
                        "result": "success" if success else "failure",
                    },
                )
                executed.append(name)

        return executed

    def run(self, check_interval: int = 30) -> None:
        """Main scheduler loop. Checks tasks every check_interval seconds."""
        logger.info(f"Scheduler starting with {len(self._tasks)} tasks")
        self._running = True
        self._stop_event.clear()

        while self._running:
            self.check_and_run()
            if self._stop_event.wait(timeout=check_interval):
                break

    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        self._stop_event.set()
        logger.info("Scheduler stopped")

    def get_status(self) -> dict:
        """Return scheduler status for dashboard display."""
        return {
            "running": self._running,
            "task_count": len(self._tasks),
            "tasks": {
                name: {
                    "description": t.description,
                    "last_run": t.last_run.isoformat() if t.last_run else None,
                    "run_count": t.run_count,
                    "error_count": t.error_count,
                }
                for name, t in self._tasks.items()
            },
        }

    def _log(self, action_type: str, details: dict) -> None:
        """Write a structured log entry. Thread-safe via shared lock."""
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        log_file = self.logs_dir / f"{today}.json"

        entry = {
            "timestamp": now.isoformat(),
            "action_type": action_type,
            "actor": "scheduler",
            **details,
        }

        with _log_lock:
            entries = []
            if log_file.exists():
                try:
                    entries = json.loads(log_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    entries = []
            entries.append(entry)
            log_file.write_text(
                json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
            )


def generate_cron_entries(python_path: str = "python3", script_dir: str = ".") -> str:
    """Generate crontab entries for the AI Employee scheduled tasks.

    Returns a string of crontab lines ready to be added via `crontab -e`.
    """
    entries = [
        "# Personal AI Employee - Scheduled Tasks",
        "# Add these lines to your crontab (crontab -e)",
        "",
        f"# Run orchestrator every 5 minutes (process inbox, update dashboard)",
        f"*/5 * * * * cd {script_dir} && {python_path} src/orchestrator.py --cycle >> vault/Logs/cron.log 2>&1",
        "",
        f"# Daily morning briefing at 8:00 AM UTC",
        f"0 8 * * * cd {script_dir} && {python_path} -c \"from planner import Planner; Planner('{VAULT_PATH}').create_plans_for_pending()\" >> vault/Logs/cron.log 2>&1",
        "",
        f"# Check for expired approvals every hour",
        f"0 * * * * cd {script_dir} && {python_path} -c \"from approval import ApprovalManager; ApprovalManager('{VAULT_PATH}').check_expired_requests()\" >> vault/Logs/cron.log 2>&1",
        "",
    ]
    return "\n".join(entries)


def generate_windows_task_xml(
    python_path: str = "python",
    script_dir: str = ".",
    task_name: str = "PersonalAIEmployee",
) -> str:
    """Generate a Windows Task Scheduler XML for the orchestrator.

    Returns XML string that can be imported via:
        schtasks /create /xml <file> /tn "PersonalAIEmployee"
    """
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Personal AI Employee - Orchestrator</Description>
  </RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <Repetition>
        <Interval>PT5M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>2026-01-01T00:00:00</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
    <BootTrigger>
      <Delay>PT1M</Delay>
      <Enabled>true</Enabled>
    </BootTrigger>
  </Triggers>
  <Actions>
    <Exec>
      <Command>{python_path}</Command>
      <Arguments>src/orchestrator.py</Arguments>
      <WorkingDirectory>{script_dir}</WorkingDirectory>
    </Exec>
  </Actions>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
</Task>"""
