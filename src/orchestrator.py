"""
Orchestrator - Master process that coordinates watchers, planner,
approval workflow, and scheduler.

The orchestrator is the "automation glue" that:
1. Starts and manages multiple watcher processes (Silver: filesystem + gmail + linkedin)
2. Monitors /Needs_Action for new items and creates plans
3. Manages the human-in-the-loop approval workflow
4. Runs scheduled tasks (dashboard refresh, briefings)
5. Updates the Dashboard after processing cycles

Bronze tier: FileSystem Watcher + vault read/write
Silver tier: Multiple watchers, planner, approval, scheduler integration
"""

import os
import sys
import json
import signal
import logging
import shutil
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from watchers.filesystem_watcher import FileSystemWatcher
from watchers.gmail_watcher import GmailWatcher
from watchers.linkedin_watcher import LinkedInWatcher
from approval import ApprovalManager
from planner import Planner
from scheduler import Scheduler, ScheduledTask
from log_utils import log_file_lock as _log_file_lock

load_dotenv()

# Configuration from environment with validation
VAULT_PATH = os.getenv("VAULT_PATH", "./vault")
WATCH_FOLDER = os.getenv("WATCH_FOLDER", None)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DEV_MODE = os.getenv("DEV_MODE", "true").lower() == "true"

# Feature flags for optional watchers
ENABLE_GMAIL = os.getenv("ENABLE_GMAIL", "false").lower() == "true"
ENABLE_LINKEDIN = os.getenv("ENABLE_LINKEDIN", "false").lower() == "true"

try:
    CHECK_INTERVAL = max(1, int(os.getenv("CHECK_INTERVAL", "10")))
except ValueError:
    CHECK_INTERVAL = 10

# Validate LOG_LEVEL
if not hasattr(logging, LOG_LEVEL):
    LOG_LEVEL = "INFO"

logger = logging.getLogger("Orchestrator")


def setup_logging(vault_path: str) -> None:
    """Configure logging with both console and file handlers."""
    log_dir = Path(vault_path) / "Logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                log_dir / "orchestrator.log",
                encoding="utf-8",
            ),
        ],
    )


class Orchestrator:
    """Master process coordinating watchers, planner, approvals, and scheduler.

    Silver tier extends Bronze with:
    - Multiple watchers (filesystem, gmail, linkedin)
    - Planner that creates Plan.md files for pending items
    - Approval manager for HITL workflow
    - Scheduler for periodic tasks
    """

    def __init__(self, vault_path: str = VAULT_PATH):
        self.vault_path = Path(vault_path)
        self.needs_action = self.vault_path / "Needs_Action"
        self.done = self.vault_path / "Done"
        self.approved = self.vault_path / "Approved"
        self.logs_dir = self.vault_path / "Logs"
        self._running = False
        self._stopped = False

        # Watcher management
        self._watchers: dict[str, dict] = {}  # name -> {"watcher": ..., "thread": ...}

        # Silver tier components
        self._approval_manager = None
        self._planner = None
        self._scheduler = None

        # Ensure all vault directories exist
        self._ensure_vault_structure()

    def _ensure_vault_structure(self) -> None:
        """Create vault directories if they don't exist."""
        dirs = [
            "Inbox", "Needs_Action", "Done", "Plans", "Logs",
            "Pending_Approval", "Approved", "Rejected",
            "Briefings", "Accounting",
        ]
        for d in dirs:
            (self.vault_path / d).mkdir(parents=True, exist_ok=True)

    def log_action(self, action_type: str, details: dict) -> None:
        """Write a structured log entry. Thread-safe via lock."""
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        log_file = self.logs_dir / f"{today}.json"

        entry = {
            "timestamp": now.isoformat(),
            "action_type": action_type,
            "actor": "orchestrator",
            **details,
        }

        with _log_file_lock:
            entries = []
            if log_file.exists():
                try:
                    entries = json.loads(log_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    logger.warning(
                        f"Corrupted log file {log_file.name}, starting fresh"
                    )
                    entries = []

            entries.append(entry)
            log_file.write_text(
                json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
            )

    def get_pending_items(self) -> list[Path]:
        """Return list of .md files in /Needs_Action awaiting processing."""
        try:
            if not self.needs_action.exists():
                return []
            return sorted(
                f for f in self.needs_action.iterdir()
                if f.is_file() and f.suffix == ".md" and f.name != ".gitkeep"
            )
        except OSError as e:
            logger.warning(f"Error reading Needs_Action: {e}")
            return []

    def get_approved_items(self) -> list[Path]:
        """Return list of approved action files."""
        try:
            if not self.approved.exists():
                return []
            return sorted(
                f for f in self.approved.iterdir()
                if f.is_file() and f.suffix == ".md" and f.name != ".gitkeep"
            )
        except OSError as e:
            logger.warning(f"Error reading Approved: {e}")
            return []

    def move_to_done(self, filepath: Path) -> Path:
        """Move a processed file to /Done with a timestamp prefix."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = self.done / f"{timestamp}_{filepath.name}"
        shutil.move(str(filepath), str(dest))

        self.log_action(
            "file_moved_to_done",
            {"source": str(filepath.name), "destination": str(dest.name)},
        )
        logger.info(f"Moved to Done: {filepath.name}")
        return dest

    def update_dashboard(self) -> None:
        """Update Dashboard.md with current vault state including Silver tier metrics."""
        dashboard_path = self.vault_path / "Dashboard.md"
        now = datetime.now(timezone.utc)

        # Count items in each folder
        try:
            inbox_path = self.vault_path / "Inbox"
            inbox_count = sum(
                1 for f in inbox_path.iterdir()
                if f.is_file() and not f.name.startswith(".")
            ) if inbox_path.exists() else 0
        except OSError:
            inbox_count = 0

        needs_action_count = len(self.get_pending_items())

        # Count pending approvals
        pending_approval_count = 0
        try:
            pa_dir = self.vault_path / "Pending_Approval"
            if pa_dir.exists():
                pending_approval_count = sum(
                    1 for f in pa_dir.iterdir()
                    if f.is_file() and f.suffix == ".md" and f.name != ".gitkeep"
                )
        except OSError:
            pass

        # Count plans
        plans_count = 0
        try:
            plans_dir = self.vault_path / "Plans"
            if plans_dir.exists():
                plans_count = sum(
                    1 for f in plans_dir.iterdir()
                    if f.is_file() and f.suffix == ".md" and f.name != ".gitkeep"
                )
        except OSError:
            pass

        done_today = 0
        done_week = 0
        today_log = self.logs_dir / f"{now.strftime('%Y-%m-%d')}.json"
        if today_log.exists():
            try:
                entries = json.loads(today_log.read_text(encoding="utf-8"))
                done_today = sum(
                    1 for e in entries
                    if e.get("action_type") in ("file_moved_to_done", "item_processed")
                )
            except (json.JSONDecodeError, OSError):
                pass

        for i in range(7):
            day = now - timedelta(days=i)
            day_log = self.logs_dir / f"{day.strftime('%Y-%m-%d')}.json"
            if day_log.exists():
                try:
                    entries = json.loads(day_log.read_text(encoding="utf-8"))
                    done_week += sum(
                        1 for e in entries
                        if e.get("action_type") in ("file_moved_to_done", "item_processed")
                    )
                except (json.JSONDecodeError, OSError):
                    pass

        # Get recent activity from logs
        recent_activity = []
        if today_log.exists():
            try:
                entries = json.loads(today_log.read_text(encoding="utf-8"))
                for e in entries[-10:]:
                    ts = e.get("timestamp", "")[:19].replace("T", " ")
                    action = e.get("action_type", "unknown")
                    target = e.get("target", e.get("file", e.get("source", "")))
                    recent_activity.append(f"- [{ts}] {action}: {target}")
            except (json.JSONDecodeError, OSError):
                pass

        activity_text = "\n".join(recent_activity) if recent_activity else "_No recent activity._"

        # Pending actions
        pending_items = self.get_pending_items()
        if pending_items:
            pending_text = "\n".join(f"- {p.name}" for p in pending_items[:10])
        else:
            pending_text = "_No pending actions._"

        # Active watchers list
        watcher_lines = []
        for name, info in self._watchers.items():
            thread = info.get("thread")
            status = "Active" if (thread and thread.is_alive()) else "Inactive"
            watcher_lines.append(f"- **{name}**: {status}")
        if not watcher_lines:
            watcher_lines.append("- _No watchers configured_")
        watchers_text = "\n".join(watcher_lines)

        # Scheduler status
        scheduler_text = "_Scheduler not running_"
        if self._scheduler:
            sched_status = self._scheduler.get_status()
            if sched_status["tasks"]:
                task_lines = []
                for tname, tinfo in sched_status["tasks"].items():
                    last = tinfo["last_run"][:19] if tinfo["last_run"] else "Never"
                    task_lines.append(f"- **{tname}**: runs={tinfo['run_count']}, last={last}")
                scheduler_text = "\n".join(task_lines)

        # Write dashboard
        dashboard_content = f"""---
last_updated: {now.isoformat()}
auto_refresh: true
tier: silver
---

# AI Employee Dashboard

## Status
- **System Status**: {"Active" if self._running else "Stopped"}
- **Dev Mode**: {"Enabled" if DEV_MODE else "Disabled"}
- **Tier**: Silver
- **Last Check**: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}

## Active Watchers
{watchers_text}

## Pending Actions
{pending_text}

## Recent Activity
{activity_text}

## Scheduled Tasks
{scheduler_text}

## Quick Stats
| Metric | Value |
|--------|-------|
| Items in Inbox | {inbox_count} |
| Items Needs Action | {needs_action_count} |
| Pending Approvals | {pending_approval_count} |
| Active Plans | {plans_count} |
| Items Done (Today) | {done_today} |
| Items Done (This Week) | {done_week} |
"""
        dashboard_path.write_text(dashboard_content, encoding="utf-8")
        logger.debug("Dashboard updated")

    def _start_watcher(self, name: str, watcher) -> None:
        """Start a watcher in a background thread."""
        thread = threading.Thread(
            target=watcher.run, daemon=True, name=name
        )
        self._watchers[name] = {"watcher": watcher, "thread": thread}
        thread.start()
        logger.info(f"Watcher started: {name}")

    def _start_all_watchers(self) -> None:
        """Start all configured watchers."""
        # Always start the filesystem watcher (Bronze tier)
        watch_folder = WATCH_FOLDER if WATCH_FOLDER else None
        fs_watcher = FileSystemWatcher(
            vault_path=str(self.vault_path),
            watch_folder=watch_folder,
            check_interval=CHECK_INTERVAL,
        )
        self._start_watcher("FileSystemWatcher", fs_watcher)

        # Optional Gmail watcher (Silver tier)
        if ENABLE_GMAIL:
            try:
                gmail_watcher = GmailWatcher(
                    vault_path=str(self.vault_path),
                    check_interval=120,
                )
                self._start_watcher("GmailWatcher", gmail_watcher)
            except Exception as e:
                logger.warning(f"Gmail watcher failed to start: {e}")

        # Optional LinkedIn watcher (Silver tier)
        if ENABLE_LINKEDIN:
            try:
                linkedin_watcher = LinkedInWatcher(
                    vault_path=str(self.vault_path),
                    check_interval=300,
                )
                self._start_watcher("LinkedInWatcher", linkedin_watcher)
            except Exception as e:
                logger.warning(f"LinkedIn watcher failed to start: {e}")

    def _init_silver_components(self) -> None:
        """Initialize Silver tier components: planner, approval manager, scheduler."""
        vault_str = str(self.vault_path)

        # Approval manager
        self._approval_manager = ApprovalManager(vault_str)
        logger.info("Approval manager initialized")

        # Planner
        self._planner = Planner(vault_str)
        logger.info("Planner initialized")

        # Scheduler with default tasks
        self._scheduler = Scheduler(vault_str)
        self._scheduler.add_task(ScheduledTask(
            name="create_plans",
            callback=self._planner.create_plans_for_pending,
            interval_seconds=CHECK_INTERVAL * 3,
            description="Create plans for new items in /Needs_Action",
        ))
        self._scheduler.add_task(ScheduledTask(
            name="process_approvals",
            callback=self._approval_manager.process_decisions,
            interval_seconds=CHECK_INTERVAL * 2,
            description="Process approved and rejected items",
        ))
        self._scheduler.add_task(ScheduledTask(
            name="check_expired_approvals",
            callback=self._approval_manager.check_expired_requests,
            interval_seconds=3600,
            description="Check for expired approval requests",
        ))
        logger.info(f"Scheduler initialized with {len(self._scheduler.get_tasks())} tasks")

    # --- Keep Bronze-compatible methods ---

    @property
    def _watcher(self):
        """Backwards-compatible property for Bronze tests."""
        fs = self._watchers.get("FileSystemWatcher")
        return fs["watcher"] if fs else None

    @_watcher.setter
    def _watcher(self, value):
        """Backwards-compatible setter - no-op for Silver tier."""
        pass

    @property
    def _watcher_thread(self):
        """Backwards-compatible property for Bronze tests."""
        fs = self._watchers.get("FileSystemWatcher")
        return fs["thread"] if fs else None

    @_watcher_thread.setter
    def _watcher_thread(self, value):
        """Backwards-compatible setter - no-op for Silver tier."""
        pass

    def process_approved_items(self) -> int:
        """Process items that have been human-approved.

        Returns the number of items processed.
        """
        approved = self.get_approved_items()
        count = 0
        for item in approved:
            logger.info(f"Processing approved item: {item.name}")
            if DEV_MODE:
                logger.info(f"[DEV MODE] Would execute action for: {item.name}")
            self.move_to_done(item)
            count += 1
        return count

    def run_cycle(self) -> dict:
        """Run a single processing cycle. Returns a summary dict.

        Silver tier extends Bronze cycle with:
        - Scheduler check_and_run
        - Plan creation for new items
        - Approval workflow processing
        """
        try:
            # Run scheduled tasks
            scheduled_ran = []
            if self._scheduler:
                scheduled_ran = self._scheduler.check_and_run()

            summary = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pending_items": len(self.get_pending_items()),
                "approved_processed": self.process_approved_items(),
                "scheduled_tasks_ran": scheduled_ran,
            }

            self.update_dashboard()
            self.log_action("cycle_complete", summary)
            return summary
        except Exception as e:
            logger.error(f"Error during processing cycle: {e}")
            self.log_action("cycle_error", {"error": str(e)})
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
            }

    def run(self) -> None:
        """Main orchestrator loop.

        Starts all watchers and Silver tier components, then periodically
        runs processing cycles.
        """
        logger.info("=" * 60)
        logger.info("Personal AI Employee - Orchestrator Starting (Silver Tier)")
        logger.info(f"  Vault: {self.vault_path.resolve()}")
        logger.info(f"  Dev Mode: {DEV_MODE}")
        logger.info(f"  Check Interval: {CHECK_INTERVAL}s")
        logger.info(f"  Gmail Watcher: {'Enabled' if ENABLE_GMAIL else 'Disabled'}")
        logger.info(f"  LinkedIn Watcher: {'Enabled' if ENABLE_LINKEDIN else 'Disabled'}")
        logger.info("=" * 60)

        self._running = True
        self._stopped = False

        # Start all watchers
        self._start_all_watchers()

        # Initialize Silver tier components
        self._init_silver_components()

        self.update_dashboard()

        self.log_action("orchestrator_started", {
            "vault_path": str(self.vault_path.resolve()),
            "dev_mode": DEV_MODE,
            "tier": "silver",
            "watchers": list(self._watchers.keys()),
        })

        try:
            while self._running:
                self.run_cycle()
                time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Shutdown requested (Ctrl+C)")
        finally:
            self.stop()

    def stop(self) -> None:
        """Gracefully shut down the orchestrator and all components.

        Idempotent: safe to call multiple times.
        """
        if self._stopped:
            return
        self._stopped = True

        logger.info("Shutting down orchestrator...")
        self._running = False

        # Stop all watchers
        for name, info in self._watchers.items():
            watcher = info.get("watcher")
            if watcher:
                watcher.stop()
                logger.info(f"Watcher stopped: {name}")

        # Stop scheduler
        if self._scheduler:
            self._scheduler.stop()

        self.update_dashboard()
        self.log_action("orchestrator_stopped", {})
        logger.info("Orchestrator stopped")


def main():
    """Entry point for the orchestrator."""
    setup_logging(VAULT_PATH)
    orchestrator = Orchestrator(vault_path=VAULT_PATH)

    # Handle graceful shutdown via signal
    def signal_handler(sig, frame):
        orchestrator.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    orchestrator.run()


if __name__ == "__main__":
    main()
