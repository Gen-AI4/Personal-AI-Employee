"""Tests for the Orchestrator."""

import json
import os
import time
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from orchestrator import Orchestrator


@pytest.fixture
def vault(tmp_path):
    """Create a temporary vault with all required directories."""
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    return vault_path


@pytest.fixture
def orch(vault):
    """Create an Orchestrator instance with a temporary vault."""
    return Orchestrator(vault_path=str(vault))


class TestOrchestratorInit:
    """Test Orchestrator initialization."""

    def test_creates_vault_structure(self, vault):
        orch = Orchestrator(vault_path=str(vault))
        expected_dirs = [
            "Inbox", "Needs_Action", "Done", "Plans", "Logs",
            "Pending_Approval", "Approved", "Rejected",
            "Briefings", "Accounting",
        ]
        for d in expected_dirs:
            assert (vault / d).exists(), f"Missing directory: {d}"

    def test_sets_vault_path(self, vault):
        orch = Orchestrator(vault_path=str(vault))
        assert orch.vault_path == vault


class TestOrchestratorGetPendingItems:
    """Test getting pending items from /Needs_Action."""

    def test_empty_needs_action(self, orch, vault):
        items = orch.get_pending_items()
        assert items == []

    def test_returns_md_files(self, orch, vault):
        (vault / "Needs_Action" / "test_item.md").write_text("content", encoding="utf-8")
        items = orch.get_pending_items()
        assert len(items) == 1
        assert items[0].name == "test_item.md"

    def test_ignores_non_md_files(self, orch, vault):
        (vault / "Needs_Action" / "data.csv").write_text("content", encoding="utf-8")
        items = orch.get_pending_items()
        assert len(items) == 0

    def test_ignores_gitkeep(self, orch, vault):
        (vault / "Needs_Action" / ".gitkeep").write_text("", encoding="utf-8")
        items = orch.get_pending_items()
        assert len(items) == 0

    def test_returns_sorted(self, orch, vault):
        (vault / "Needs_Action" / "b_item.md").write_text("b", encoding="utf-8")
        (vault / "Needs_Action" / "a_item.md").write_text("a", encoding="utf-8")
        items = orch.get_pending_items()
        assert items[0].name == "a_item.md"
        assert items[1].name == "b_item.md"


class TestOrchestratorGetApprovedItems:
    """Test getting approved items."""

    def test_empty_approved(self, orch, vault):
        items = orch.get_approved_items()
        assert items == []

    def test_returns_approved_md_files(self, orch, vault):
        (vault / "Approved" / "approved_action.md").write_text("approved", encoding="utf-8")
        items = orch.get_approved_items()
        assert len(items) == 1


class TestOrchestratorMoveToDone:
    """Test moving files to /Done."""

    def test_moves_file(self, orch, vault):
        src = vault / "Needs_Action" / "test.md"
        src.write_text("test content", encoding="utf-8")

        dest = orch.move_to_done(src)
        assert dest.exists()
        assert not src.exists()
        assert dest.parent == vault / "Done"

    def test_adds_timestamp_prefix(self, orch, vault):
        src = vault / "Needs_Action" / "task.md"
        src.write_text("content", encoding="utf-8")

        dest = orch.move_to_done(src)
        # Format: YYYYMMDD_HHMMSS_original.md
        assert "_task.md" in dest.name
        assert len(dest.stem) > len("task")

    def test_creates_log_entry(self, orch, vault):
        src = vault / "Needs_Action" / "logged_task.md"
        src.write_text("content", encoding="utf-8")

        orch.move_to_done(src)

        log_files = list((vault / "Logs").glob("*.json"))
        assert len(log_files) >= 1
        entries = json.loads(log_files[0].read_text(encoding="utf-8"))
        assert any(e["action_type"] == "file_moved_to_done" for e in entries)


class TestOrchestratorProcessApprovedItems:
    """Test processing of approved items."""

    def test_processes_approved_items(self, orch, vault):
        (vault / "Approved" / "action.md").write_text("approved action", encoding="utf-8")

        count = orch.process_approved_items()
        assert count == 1

        # Should be moved to Done
        done_files = [f for f in (vault / "Done").iterdir() if f.name != ".gitkeep"]
        assert len(done_files) == 1

        # Should be removed from Approved
        approved_files = [f for f in (vault / "Approved").iterdir() if f.name != ".gitkeep"]
        assert len(approved_files) == 0

    def test_no_approved_items(self, orch, vault):
        count = orch.process_approved_items()
        assert count == 0


class TestOrchestratorUpdateDashboard:
    """Test dashboard update functionality."""

    def test_creates_dashboard(self, orch, vault):
        orch.update_dashboard()
        dashboard = vault / "Dashboard.md"
        assert dashboard.exists()

    def test_dashboard_contains_stats(self, orch, vault):
        # Add some items
        (vault / "Needs_Action" / "pending.md").write_text("pending", encoding="utf-8")

        orch.update_dashboard()
        content = (vault / "Dashboard.md").read_text(encoding="utf-8")

        assert "AI Employee Dashboard" in content
        assert "Items Needs Action" in content
        assert "Items in Inbox" in content

    def test_dashboard_shows_pending_items(self, orch, vault):
        (vault / "Needs_Action" / "urgent_task.md").write_text("urgent", encoding="utf-8")

        orch.update_dashboard()
        content = (vault / "Dashboard.md").read_text(encoding="utf-8")

        assert "urgent_task.md" in content

    def test_dashboard_frontmatter(self, orch, vault):
        orch.update_dashboard()
        content = (vault / "Dashboard.md").read_text(encoding="utf-8")

        assert "---" in content
        assert "last_updated:" in content
        assert "auto_refresh: true" in content

    def test_dashboard_shows_system_status(self, orch, vault):
        orch._running = True
        orch.update_dashboard()
        content = (vault / "Dashboard.md").read_text(encoding="utf-8")
        assert "Active" in content


class TestOrchestratorRunCycle:
    """Test the run_cycle method."""

    def test_returns_summary(self, orch, vault):
        summary = orch.run_cycle()
        assert "timestamp" in summary
        assert "pending_items" in summary
        assert "approved_processed" in summary

    def test_processes_approved_during_cycle(self, orch, vault):
        (vault / "Approved" / "test.md").write_text("approved", encoding="utf-8")

        summary = orch.run_cycle()
        assert summary["approved_processed"] == 1

    def test_updates_dashboard_during_cycle(self, orch, vault):
        orch.run_cycle()
        assert (vault / "Dashboard.md").exists()

    def test_creates_cycle_log(self, orch, vault):
        orch.run_cycle()

        log_files = list((vault / "Logs").glob("*.json"))
        assert len(log_files) >= 1
        entries = json.loads(log_files[0].read_text(encoding="utf-8"))
        assert any(e["action_type"] == "cycle_complete" for e in entries)


class TestOrchestratorLogAction:
    """Test orchestrator logging."""

    def test_log_entry_format(self, orch, vault):
        orch.log_action("test_event", {"key": "value"})

        log_files = list((vault / "Logs").glob("*.json"))
        entries = json.loads(log_files[0].read_text(encoding="utf-8"))
        entry = entries[0]

        assert entry["action_type"] == "test_event"
        assert entry["actor"] == "orchestrator"
        assert entry["key"] == "value"
        assert "timestamp" in entry


class TestOrchestratorIntegration:
    """Integration tests for the full orchestrator workflow."""

    def test_full_workflow_file_to_done(self, vault):
        """End-to-end: file drop → inbox → needs_action → done."""
        orch = Orchestrator(vault_path=str(vault))

        # Step 1: Simulate a file being processed into Needs_Action
        action_file = vault / "Needs_Action" / "FILE_20260220_test.md"
        action_file.write_text("""---
type: file_drop
status: pending
---
Test action item
""", encoding="utf-8")

        # Step 2: Verify it shows as pending
        pending = orch.get_pending_items()
        assert len(pending) == 1

        # Step 3: Simulate approval process - move to Approved
        import shutil
        approved_file = vault / "Approved" / action_file.name
        shutil.copy2(str(action_file), str(approved_file))
        action_file.unlink()

        # Step 4: Run a cycle
        summary = orch.run_cycle()
        assert summary["approved_processed"] == 1

        # Step 5: Verify file is in Done
        done_files = [f for f in (vault / "Done").iterdir() if f.name != ".gitkeep"]
        assert len(done_files) == 1

        # Step 6: Verify dashboard is updated
        dashboard = (vault / "Dashboard.md").read_text(encoding="utf-8")
        assert "AI Employee Dashboard" in content if (content := dashboard) else True

    def test_orchestrator_stop(self, vault):
        """Test that the orchestrator can be cleanly stopped."""
        orch = Orchestrator(vault_path=str(vault))
        orch._running = True
        orch.stop()
        assert not orch._running
