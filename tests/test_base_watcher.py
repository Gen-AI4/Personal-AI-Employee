"""Tests for the BaseWatcher abstract class."""

import json
import time
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from watchers.base_watcher import BaseWatcher


class ConcreteWatcher(BaseWatcher):
    """Concrete implementation of BaseWatcher for testing."""

    def __init__(self, vault_path: str, items_to_return=None, **kwargs):
        super().__init__(vault_path, **kwargs)
        self.items_to_return = items_to_return or []
        self.created_files = []

    def check_for_updates(self) -> list:
        return self.items_to_return

    def create_action_file(self, item) -> Path:
        filepath = self.needs_action / f"TEST_{item}.md"
        filepath.write_text(f"Test action for {item}", encoding="utf-8")
        self.created_files.append(filepath)
        return filepath


class TestBaseWatcherInit:
    """Test BaseWatcher initialization."""

    def test_creates_needs_action_directory(self, tmp_path):
        vault = tmp_path / "vault"
        watcher = ConcreteWatcher(str(vault))
        assert (vault / "Needs_Action").exists()

    def test_creates_logs_directory(self, tmp_path):
        vault = tmp_path / "vault"
        watcher = ConcreteWatcher(str(vault))
        assert (vault / "Logs").exists()

    def test_sets_check_interval(self, tmp_path):
        watcher = ConcreteWatcher(str(tmp_path), check_interval=30)
        assert watcher.check_interval == 30

    def test_default_check_interval(self, tmp_path):
        watcher = ConcreteWatcher(str(tmp_path))
        assert watcher.check_interval == 60

    def test_sets_vault_path(self, tmp_path):
        watcher = ConcreteWatcher(str(tmp_path))
        assert watcher.vault_path == tmp_path


class TestBaseWatcherLogAction:
    """Test the log_action method."""

    def test_creates_log_file(self, tmp_path):
        watcher = ConcreteWatcher(str(tmp_path))
        watcher.log_action("test_action", {"detail": "value"})

        log_files = list((tmp_path / "Logs").glob("*.json"))
        assert len(log_files) == 1

    def test_log_entry_structure(self, tmp_path):
        watcher = ConcreteWatcher(str(tmp_path))
        watcher.log_action("test_action", {"target": "test.md"})

        log_files = list((tmp_path / "Logs").glob("*.json"))
        entries = json.loads(log_files[0].read_text(encoding="utf-8"))
        assert len(entries) == 1

        entry = entries[0]
        assert "timestamp" in entry
        assert entry["action_type"] == "test_action"
        assert entry["watcher"] == "ConcreteWatcher"
        assert entry["actor"] == "watcher"
        assert entry["target"] == "test.md"

    def test_appends_to_existing_log(self, tmp_path):
        watcher = ConcreteWatcher(str(tmp_path))
        watcher.log_action("action_1", {})
        watcher.log_action("action_2", {})

        log_files = list((tmp_path / "Logs").glob("*.json"))
        entries = json.loads(log_files[0].read_text(encoding="utf-8"))
        assert len(entries) == 2

    def test_handles_corrupted_log_file(self, tmp_path):
        watcher = ConcreteWatcher(str(tmp_path))
        # Create a corrupted log file
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = tmp_path / "Logs" / f"{today}.json"
        log_file.write_text("not valid json", encoding="utf-8")

        # Should not raise, should overwrite with fresh entry
        watcher.log_action("recovery_action", {})
        entries = json.loads(log_file.read_text(encoding="utf-8"))
        assert len(entries) == 1
        assert entries[0]["action_type"] == "recovery_action"


class TestBaseWatcherRun:
    """Test the run loop."""

    def test_run_processes_items(self, tmp_path):
        watcher = ConcreteWatcher(str(tmp_path), items_to_return=["item1", "item2"])
        watcher.check_interval = 0.1

        # Run in thread and stop after short time
        thread = threading.Thread(target=watcher.run, daemon=True)
        thread.start()
        time.sleep(0.3)
        watcher.stop()
        thread.join(timeout=2)

        assert len(watcher.created_files) >= 2

    def test_run_handles_errors_gracefully(self, tmp_path):
        """Watcher should continue running even if check_for_updates raises."""
        class ErrorWatcher(BaseWatcher):
            call_count = 0

            def check_for_updates(self):
                self.call_count += 1
                if self.call_count == 1:
                    raise RuntimeError("Simulated failure")
                return []

            def create_action_file(self, item):
                return self.needs_action / "test.md"

        watcher = ErrorWatcher(str(tmp_path), check_interval=0)
        watcher.check_interval = 0.1

        thread = threading.Thread(target=watcher.run, daemon=True)
        thread.start()
        time.sleep(0.5)
        watcher.stop()
        thread.join(timeout=2)

        # Should have been called multiple times despite the error
        assert watcher.call_count >= 2

    def test_stop_terminates_run(self, tmp_path):
        watcher = ConcreteWatcher(str(tmp_path))
        watcher.check_interval = 0.1

        thread = threading.Thread(target=watcher.run, daemon=True)
        thread.start()
        time.sleep(0.2)
        watcher.stop()
        thread.join(timeout=2)

        assert not thread.is_alive()
