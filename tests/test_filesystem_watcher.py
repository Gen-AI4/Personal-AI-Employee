"""Tests for the FileSystem Watcher."""

import json
import time
import threading
from pathlib import Path

import pytest

from watchers.filesystem_watcher import (
    FileSystemWatcher,
    DropFolderHandler,
    classify_priority,
)


class TestClassifyPriority:
    """Test priority classification from filenames."""

    def test_high_priority_urgent(self):
        assert classify_priority("URGENT_report.pdf") == "high"

    def test_high_priority_asap(self):
        assert classify_priority("need_this_ASAP.doc") == "high"

    def test_high_priority_critical(self):
        assert classify_priority("critical_update.txt") == "high"

    def test_medium_priority_invoice(self):
        assert classify_priority("invoice_january.pdf") == "medium"

    def test_medium_priority_payment(self):
        assert classify_priority("payment_receipt.pdf") == "medium"

    def test_low_priority_default(self):
        assert classify_priority("notes.txt") == "low"

    def test_case_insensitive(self):
        assert classify_priority("URGENT_FILE.PDF") == "high"
        assert classify_priority("Invoice_2026.pdf") == "medium"


class TestFileSystemWatcherInit:
    """Test FileSystemWatcher initialization."""

    def test_creates_watch_folder(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = FileSystemWatcher(str(vault))
        assert (vault / "Inbox").exists()

    def test_custom_watch_folder(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        custom_folder = tmp_path / "custom_inbox"
        watcher = FileSystemWatcher(str(vault), watch_folder=str(custom_folder))
        assert custom_folder.exists()
        assert watcher.watch_folder == custom_folder

    def test_default_watch_folder_is_inbox(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = FileSystemWatcher(str(vault))
        assert watcher.watch_folder == vault / "Inbox"

    def test_empty_pending_items(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = FileSystemWatcher(str(vault))
        assert watcher.pending_items == []

    def test_empty_processed_files(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = FileSystemWatcher(str(vault))
        assert watcher._processed_files == set()


class TestFileSystemWatcherCheckForUpdates:
    """Test the check_for_updates method."""

    def test_detects_new_files(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = FileSystemWatcher(str(vault))

        # Drop a file into inbox
        test_file = watcher.watch_folder / "test_document.txt"
        test_file.write_text("Hello world", encoding="utf-8")

        items = watcher.check_for_updates()
        assert len(items) == 1
        assert items[0].name == "test_document.txt"

    def test_ignores_hidden_files(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = FileSystemWatcher(str(vault))

        # Drop hidden file and .gitkeep
        (watcher.watch_folder / ".gitkeep").write_text("", encoding="utf-8")
        (watcher.watch_folder / ".hidden").write_text("", encoding="utf-8")

        items = watcher.check_for_updates()
        assert len(items) == 0

    def test_does_not_return_already_processed(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = FileSystemWatcher(str(vault))

        test_file = watcher.watch_folder / "document.txt"
        test_file.write_text("content", encoding="utf-8")

        # Process it once
        items = watcher.check_for_updates()
        assert len(items) == 1
        watcher.create_action_file(items[0])

        # Should not return it again
        items = watcher.check_for_updates()
        assert len(items) == 0

    def test_detects_multiple_files(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = FileSystemWatcher(str(vault))

        for i in range(3):
            (watcher.watch_folder / f"file_{i}.txt").write_text(f"content {i}", encoding="utf-8")

        items = watcher.check_for_updates()
        assert len(items) == 3

    def test_includes_watchdog_pending_items(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = FileSystemWatcher(str(vault))

        # Simulate watchdog event by adding to pending_items
        test_file = watcher.watch_folder / "event_file.txt"
        test_file.write_text("content", encoding="utf-8")
        watcher.pending_items.append(test_file)

        items = watcher.check_for_updates()
        assert len(items) == 1
        assert items[0].name == "event_file.txt"


class TestFileSystemWatcherCreateActionFile:
    """Test the create_action_file method."""

    def test_creates_metadata_md_file(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = FileSystemWatcher(str(vault))

        test_file = watcher.watch_folder / "report.pdf"
        test_file.write_text("pdf content", encoding="utf-8")

        meta_path = watcher.create_action_file(test_file)
        assert meta_path.exists()
        assert meta_path.suffix == ".md"

    def test_copies_original_file_to_needs_action(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = FileSystemWatcher(str(vault))

        test_file = watcher.watch_folder / "data.csv"
        test_file.write_text("col1,col2\n1,2", encoding="utf-8")

        watcher.create_action_file(test_file)

        # Check that a copy exists in Needs_Action
        needs_action_files = list(watcher.needs_action.iterdir())
        # Should have both the copy and the .md metadata
        non_gitkeep = [f for f in needs_action_files if f.name != ".gitkeep"]
        assert len(non_gitkeep) == 2  # data.csv copy + metadata .md

    def test_metadata_contains_frontmatter(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = FileSystemWatcher(str(vault))

        test_file = watcher.watch_folder / "invoice_jan.pdf"
        test_file.write_text("invoice content", encoding="utf-8")

        meta_path = watcher.create_action_file(test_file)
        content = meta_path.read_text(encoding="utf-8")

        assert "---" in content
        assert "type: file_drop" in content
        assert 'original_name: "invoice_jan.pdf"' in content
        assert "priority: medium" in content  # "invoice" is medium priority
        assert "status: pending" in content

    def test_high_priority_file(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = FileSystemWatcher(str(vault))

        test_file = watcher.watch_folder / "URGENT_fix_needed.txt"
        test_file.write_text("urgent stuff", encoding="utf-8")

        meta_path = watcher.create_action_file(test_file)
        content = meta_path.read_text(encoding="utf-8")
        assert "priority: high" in content

    def test_marks_file_as_processed(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = FileSystemWatcher(str(vault))

        test_file = watcher.watch_folder / "doc.txt"
        test_file.write_text("content", encoding="utf-8")

        watcher.create_action_file(test_file)
        assert "doc.txt" in watcher._processed_files

    def test_creates_log_entry(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = FileSystemWatcher(str(vault))

        test_file = watcher.watch_folder / "logged_file.txt"
        test_file.write_text("content", encoding="utf-8")

        watcher.create_action_file(test_file)

        log_files = list((vault / "Logs").glob("*.json"))
        assert len(log_files) == 1
        entries = json.loads(log_files[0].read_text(encoding="utf-8"))
        assert any(e["action_type"] == "file_drop_processed" for e in entries)

    def test_handles_spaces_in_filename(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = FileSystemWatcher(str(vault))

        test_file = watcher.watch_folder / "my important document.txt"
        test_file.write_text("content", encoding="utf-8")

        meta_path = watcher.create_action_file(test_file)
        assert meta_path.exists()
        # Spaces should be replaced with underscores in the destination
        assert " " not in meta_path.stem or "_" in meta_path.stem


class TestFileSystemWatcherIntegration:
    """Integration tests for the full file drop → action file workflow."""

    def test_full_workflow_drop_to_action(self, tmp_path):
        """End-to-end: drop file → detect → create action file."""
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = FileSystemWatcher(str(vault), check_interval=1)

        # Step 1: Drop a file
        test_file = watcher.watch_folder / "client_invoice.pdf"
        test_file.write_text("invoice data", encoding="utf-8")

        # Step 2: Check for updates
        items = watcher.check_for_updates()
        assert len(items) == 1

        # Step 3: Create action file
        meta_path = watcher.create_action_file(items[0])
        assert meta_path.exists()

        # Step 4: Verify metadata
        content = meta_path.read_text(encoding="utf-8")
        assert "client_invoice.pdf" in content
        assert "priority: medium" in content  # "invoice" keyword

        # Step 5: Verify file was copied
        copied_files = [
            f for f in watcher.needs_action.iterdir()
            if f.suffix == ".pdf"
        ]
        assert len(copied_files) == 1

        # Step 6: Verify logging
        log_files = list((vault / "Logs").glob("*.json"))
        assert len(log_files) >= 1

    def test_multiple_files_workflow(self, tmp_path):
        """Process multiple files in sequence."""
        vault = tmp_path / "vault"
        vault.mkdir()
        watcher = FileSystemWatcher(str(vault))

        # Drop multiple files
        files = ["urgent_report.txt", "invoice_feb.pdf", "notes.md"]
        for fname in files:
            (watcher.watch_folder / fname).write_text(f"content of {fname}", encoding="utf-8")

        # Process all
        items = watcher.check_for_updates()
        assert len(items) == 3

        for item in items:
            watcher.create_action_file(item)

        # All should be processed
        assert len(watcher._processed_files) == 3

        # Check priorities are correct
        md_files = [
            f for f in watcher.needs_action.iterdir()
            if f.suffix == ".md" and f.name != ".gitkeep"
        ]
        contents = {f.name: f.read_text(encoding="utf-8") for f in md_files}

        has_high = any("priority: high" in c for c in contents.values())
        has_medium = any("priority: medium" in c for c in contents.values())
        has_low = any("priority: low" in c for c in contents.values())

        assert has_high  # "urgent" keyword
        assert has_medium  # "invoice" keyword
        assert has_low  # "notes" has no keywords
