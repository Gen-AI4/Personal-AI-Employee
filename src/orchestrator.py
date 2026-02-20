"""
Orchestrator - Master process that coordinates watchers and Claude Code.

The orchestrator is the "automation glue" that:
1. Starts and manages watcher processes
2. Monitors /Needs_Action for new items
3. Triggers Claude Code to process pending items
4. Watches /Approved folder for human-approved actions
5. Updates the Dashboard after processing cycles

For Bronze tier, this runs the FileSystem Watcher and provides
the interface for Claude Code to read from and write to the vault.
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

load_dotenv()

# Configuration from environment with validation
VAULT_PATH = os.getenv("VAULT_PATH", "./vault")
WATCH_FOLDER = os.getenv("WATCH_FOLDER", None)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DEV_MODE = os.getenv("DEV_MODE", "true").lower() == "true"

try:
    CHECK_INTERVAL = max(1, int(os.getenv("CHECK_INTERVAL", "10")))
except ValueError:
    CHECK_INTERVAL = 10

# Validate LOG_LEVEL
if not hasattr(logging, LOG_LEVEL):
    LOG_LEVEL = "INFO"

logger = logging.getLogger("Orchestrator")

# Thread lock for log file writes (shared with watchers via base_watcher._log_file_lock)
_log_file_lock = threading.Lock()


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
    """Master process coordinating watchers and vault workflow.

    The orchestrator manages the lifecycle of watcher processes and
    provides the trigger mechanism for Claude Code to process items.
    """

    def __init__(self, vault_path: str = VAULT_PATH):
        self.vault_path = Path(vault_path)
        self.needs_action = self.vault_path / "Needs_Action"
        self.done = self.vault_path / "Done"
        self.approved = self.vault_path / "Approved"
        self.logs_dir = self.vault_path / "Logs"
        self._running = False
        self._stopped = False
        self._watcher = None
        self._watcher_thread = None

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
        """Update Dashboard.md with current vault state."""
        dashboard_path = self.vault_path / "Dashboard.md"
        now = datetime.now(timezone.utc)

        # Count items in each folder (with error handling for race conditions)
        try:
            inbox_path = self.vault_path / "Inbox"
            inbox_count = sum(
                1 for f in inbox_path.iterdir()
                if f.is_file() and not f.name.startswith(".")
            ) if inbox_path.exists() else 0
        except OSError:
            inbox_count = 0

        needs_action_count = len(self.get_pending_items())

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

        # Count done items from this week's logs
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

        # Write dashboard
        dashboard_content = f"""---
last_updated: {now.isoformat()}
auto_refresh: true
---

# AI Employee Dashboard

## Status
- **System Status**: {"Active" if self._running else "Stopped"}
- **Watcher**: File System Watcher - {"Active" if self._watcher else "Inactive"}
- **Dev Mode**: {"Enabled" if DEV_MODE else "Disabled"}
- **Last Check**: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}

## Pending Actions
{pending_text}

## Recent Activity
{activity_text}

## Quick Stats
| Metric | Value |
|--------|-------|
| Items in Inbox | {inbox_count} |
| Items Needs Action | {needs_action_count} |
| Items Done (Today) | {done_today} |
| Items Done (This Week) | {done_week} |
"""
        dashboard_path.write_text(dashboard_content, encoding="utf-8")
        logger.debug("Dashboard updated")

    def _start_watcher(self) -> None:
        """Start the filesystem watcher in a background thread."""
        watch_folder = WATCH_FOLDER if WATCH_FOLDER else None
        self._watcher = FileSystemWatcher(
            vault_path=str(self.vault_path),
            watch_folder=watch_folder,
            check_interval=CHECK_INTERVAL,
        )
        self._watcher_thread = threading.Thread(
            target=self._watcher.run, daemon=True, name="FileSystemWatcher"
        )
        self._watcher_thread.start()
        logger.info("FileSystem Watcher started")

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

        This is useful for testing and for manual triggering.
        Catches exceptions to prevent a single bad file from crashing the loop.
        """
        try:
            summary = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pending_items": len(self.get_pending_items()),
                "approved_processed": self.process_approved_items(),
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

        Starts the watcher, then periodically:
        1. Checks for approved items and processes them
        2. Updates the dashboard
        3. Logs cycle summary
        """
        logger.info("=" * 60)
        logger.info("Personal AI Employee - Orchestrator Starting")
        logger.info(f"  Vault: {self.vault_path.resolve()}")
        logger.info(f"  Dev Mode: {DEV_MODE}")
        logger.info(f"  Check Interval: {CHECK_INTERVAL}s")
        logger.info("=" * 60)

        self._running = True
        self._stopped = False
        self._start_watcher()
        self.update_dashboard()

        self.log_action("orchestrator_started", {
            "vault_path": str(self.vault_path.resolve()),
            "dev_mode": DEV_MODE,
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
        """Gracefully shut down the orchestrator and all watchers.

        Idempotent: safe to call multiple times.
        """
        if self._stopped:
            return
        self._stopped = True

        logger.info("Shutting down orchestrator...")
        self._running = False

        if self._watcher:
            self._watcher.stop()

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
