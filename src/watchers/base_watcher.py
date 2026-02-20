"""
Base Watcher - Abstract template for all watcher implementations.

All watchers follow the Perception layer pattern: continuously monitor a source
for new items and create actionable .md files in the vault's /Needs_Action folder.
"""

import logging
import json
import threading
from pathlib import Path
from abc import ABC, abstractmethod
from datetime import datetime, timezone


# Module-level lock for log file writes to prevent concurrent corruption
_log_file_lock = threading.Lock()


class BaseWatcher(ABC):
    """Abstract base class for all watcher implementations.

    Subclasses must implement:
        - check_for_updates(): Return list of new items to process
        - create_action_file(item): Create .md file in Needs_Action folder
    """

    def __init__(self, vault_path: str, check_interval: int = 60):
        self.vault_path = Path(vault_path)
        self.needs_action = self.vault_path / "Needs_Action"
        self.logs_dir = self.vault_path / "Logs"
        self.check_interval = check_interval
        self.logger = logging.getLogger(self.__class__.__name__)
        self._running = False
        self._stop_event = threading.Event()

        # Ensure required directories exist
        self.needs_action.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def check_for_updates(self) -> list:
        """Return list of new items to process."""
        pass

    @abstractmethod
    def create_action_file(self, item) -> Path:
        """Create .md file in Needs_Action folder for the given item."""
        pass

    def log_action(self, action_type: str, details: dict) -> None:
        """Append a structured log entry to today's log file.

        Thread-safe: uses a lock to prevent concurrent read-modify-write corruption.
        """
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        log_file = self.logs_dir / f"{today}.json"

        entry = {
            "timestamp": now.isoformat(),
            "watcher": self.__class__.__name__,
            "action_type": action_type,
            "actor": "watcher",
            **details,
        }

        with _log_file_lock:
            entries = []
            if log_file.exists():
                try:
                    entries = json.loads(log_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    self.logger.warning(
                        f"Corrupted log file {log_file.name}, starting fresh"
                    )
                    entries = []

            entries.append(entry)
            log_file.write_text(
                json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
            )

    def run(self) -> None:
        """Main loop: poll for updates and create action files."""
        self.logger.info(f"Starting {self.__class__.__name__}")
        self._running = True
        self._stop_event.clear()

        while self._running:
            try:
                items = self.check_for_updates()
                for item in items:
                    filepath = self.create_action_file(item)
                    self.logger.info(f"Created action file: {filepath}")
                    self.log_action(
                        "file_created",
                        {"file": str(filepath), "result": "success"},
                    )
            except Exception as e:
                self.logger.error(f"Error during check: {e}")
                self.log_action(
                    "error",
                    {"error": str(e), "result": "failure"},
                )
            # Use Event.wait() instead of time.sleep() for immediate shutdown
            if self._stop_event.wait(timeout=self.check_interval):
                break

    def stop(self) -> None:
        """Signal the watcher to stop its run loop."""
        self._running = False
        self._stop_event.set()
        self.logger.info(f"Stopping {self.__class__.__name__}")
