"""Silver tier tests for the Orchestrator.

Tests Silver-specific features while ensuring backward compatibility
with Bronze tier functionality.
"""

import json
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

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


# --- Silver Tier Vault Structure ---


class TestSilverVaultStructure:
    """Test that Silver tier creates all required directories."""

    def test_creates_pending_approval(self, vault):
        orch = Orchestrator(vault_path=str(vault))
        assert (vault / "Pending_Approval").exists()

    def test_creates_approved(self, vault):
        orch = Orchestrator(vault_path=str(vault))
        assert (vault / "Approved").exists()

    def test_creates_rejected(self, vault):
        orch = Orchestrator(vault_path=str(vault))
        assert (vault / "Rejected").exists()

    def test_creates_plans(self, vault):
        orch = Orchestrator(vault_path=str(vault))
        assert (vault / "Plans").exists()

    def test_creates_briefings(self, vault):
        orch = Orchestrator(vault_path=str(vault))
        assert (vault / "Briefings").exists()

    def test_creates_accounting(self, vault):
        orch = Orchestrator(vault_path=str(vault))
        assert (vault / "Accounting").exists()


# --- Backward Compatibility ---


class TestBackwardCompatibility:
    """Test Bronze-tier backward compatibility properties."""

    def test_watcher_property_returns_none_initially(self, orch):
        # Before any watchers started, should return None
        assert orch._watcher is None

    def test_watcher_thread_returns_none_initially(self, orch):
        assert orch._watcher_thread is None

    def test_watcher_setter_is_noop(self, orch):
        orch._watcher = "something"
        assert orch._watcher is None

    def test_watcher_thread_setter_is_noop(self, orch):
        orch._watcher_thread = "something"
        assert orch._watcher_thread is None

    def test_get_pending_items_still_works(self, orch, vault):
        (vault / "Needs_Action" / "test.md").write_text("test", encoding="utf-8")
        items = orch.get_pending_items()
        assert len(items) == 1

    def test_get_approved_items_still_works(self, orch, vault):
        (vault / "Approved" / "test.md").write_text("test", encoding="utf-8")
        items = orch.get_approved_items()
        assert len(items) == 1

    def test_move_to_done_still_works(self, orch, vault):
        src = vault / "Needs_Action" / "item.md"
        src.write_text("content", encoding="utf-8")
        dest = orch.move_to_done(src)
        assert dest.exists()
        assert not src.exists()

    def test_log_action_still_works(self, orch, vault):
        orch.log_action("test_event", {"detail": "value"})
        log_files = list((vault / "Logs").glob("*.json"))
        assert len(log_files) >= 1

    def test_process_approved_items_still_works(self, orch, vault):
        (vault / "Approved" / "action.md").write_text("action", encoding="utf-8")
        count = orch.process_approved_items()
        assert count == 1


# --- Silver Tier Components ---


class TestSilverComponents:
    """Test Silver tier component initialization."""

    def test_approval_manager_initially_none(self, orch):
        assert orch._approval_manager is None

    def test_planner_initially_none(self, orch):
        assert orch._planner is None

    def test_scheduler_initially_none(self, orch):
        assert orch._scheduler is None

    def test_watchers_dict_initially_empty(self, orch):
        assert len(orch._watchers) == 0


# --- Dashboard Silver ---


class TestSilverDashboard:
    """Test Silver-tier dashboard features."""

    def test_dashboard_shows_tier(self, orch, vault):
        orch.update_dashboard()
        content = (vault / "Dashboard.md").read_text(encoding="utf-8")
        assert "tier: silver" in content

    def test_dashboard_shows_watchers_section(self, orch, vault):
        orch.update_dashboard()
        content = (vault / "Dashboard.md").read_text(encoding="utf-8")
        assert "Active Watchers" in content

    def test_dashboard_shows_no_watchers_when_empty(self, orch, vault):
        orch.update_dashboard()
        content = (vault / "Dashboard.md").read_text(encoding="utf-8")
        assert "No watchers configured" in content

    def test_dashboard_shows_pending_approvals(self, orch, vault):
        (vault / "Pending_Approval" / "APPROVAL_test.md").write_text(
            "pending", encoding="utf-8"
        )
        orch.update_dashboard()
        content = (vault / "Dashboard.md").read_text(encoding="utf-8")
        assert "Pending Approvals" in content

    def test_dashboard_shows_plans_count(self, orch, vault):
        (vault / "Plans" / "PLAN_test.md").write_text("plan", encoding="utf-8")
        orch.update_dashboard()
        content = (vault / "Dashboard.md").read_text(encoding="utf-8")
        assert "Active Plans" in content

    def test_dashboard_shows_scheduled_tasks(self, orch, vault):
        orch.update_dashboard()
        content = (vault / "Dashboard.md").read_text(encoding="utf-8")
        assert "Scheduled Tasks" in content

    def test_dashboard_shows_watcher_status(self, orch, vault):
        # Simulate a watcher entry
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        orch._watchers["TestWatcher"] = {
            "watcher": MagicMock(),
            "thread": mock_thread,
        }
        orch.update_dashboard()
        content = (vault / "Dashboard.md").read_text(encoding="utf-8")
        assert "TestWatcher" in content
        assert "Active" in content


# --- Run Cycle Silver ---


class TestSilverRunCycle:
    """Test Silver-tier run_cycle features."""

    def test_run_cycle_includes_scheduled_tasks(self, orch, vault):
        summary = orch.run_cycle()
        assert "scheduled_tasks_ran" in summary

    def test_run_cycle_with_scheduler(self, orch, vault):
        from scheduler import Scheduler, ScheduledTask

        orch._scheduler = Scheduler(vault_path=str(vault))
        cb = MagicMock()
        # interval_seconds must be > 0 (truthy); last_run=None triggers first run
        orch._scheduler.add_task(ScheduledTask(
            name="test_task", callback=cb, interval_seconds=1,
        ))

        summary = orch.run_cycle()
        assert "test_task" in summary["scheduled_tasks_ran"]
        cb.assert_called_once()

    def test_run_cycle_handles_errors(self, orch, vault):
        # Create a scheduler that raises
        orch._scheduler = MagicMock()
        orch._scheduler.check_and_run.side_effect = RuntimeError("boom")

        summary = orch.run_cycle()
        assert "error" in summary


# --- Watcher Management ---


class TestWatcherManagement:
    """Test watcher lifecycle management."""

    def test_start_watcher_adds_to_dict(self, orch):
        mock_watcher = MagicMock()
        mock_watcher.run = MagicMock()
        orch._start_watcher("TestWatcher", mock_watcher)
        assert "TestWatcher" in orch._watchers
        # Clean up
        time.sleep(0.1)

    def test_start_watcher_creates_thread(self, orch):
        mock_watcher = MagicMock()
        mock_watcher.run = MagicMock()
        orch._start_watcher("TestWatcher", mock_watcher)
        thread = orch._watchers["TestWatcher"]["thread"]
        assert thread is not None
        time.sleep(0.1)

    def test_stop_stops_all_watchers(self, orch):
        mock_watcher = MagicMock()
        orch._watchers["W1"] = {"watcher": mock_watcher, "thread": MagicMock()}
        orch._running = True
        orch.stop()
        mock_watcher.stop.assert_called_once()

    def test_stop_is_idempotent(self, orch):
        orch._running = True
        orch.stop()
        orch.stop()  # Should not raise
        assert not orch._running

    def test_stop_stops_scheduler(self, orch):
        mock_scheduler = MagicMock()
        orch._scheduler = mock_scheduler
        orch._running = True
        orch.stop()
        mock_scheduler.stop.assert_called_once()


# --- Start All Watchers ---


class TestStartAllWatchers:
    """Test starting all configured watchers."""

    @patch("orchestrator.ENABLE_GMAIL", False)
    @patch("orchestrator.ENABLE_LINKEDIN", False)
    def test_starts_filesystem_watcher_only(self, orch):
        orch._start_all_watchers()
        assert "FileSystemWatcher" in orch._watchers
        assert len(orch._watchers) == 1
        # Clean up: signal watchers to stop (don't join observer thread)
        for name, info in orch._watchers.items():
            watcher = info["watcher"]
            watcher._running = False
            watcher._stop_event.set()
        time.sleep(0.3)

    @patch("orchestrator.ENABLE_GMAIL", True)
    @patch("orchestrator.ENABLE_LINKEDIN", False)
    def test_starts_gmail_watcher_when_enabled(self, orch):
        orch._start_all_watchers()
        assert "FileSystemWatcher" in orch._watchers
        # Gmail watcher may or may not start depending on credentials
        # Just verify it doesn't crash
        for name, info in orch._watchers.items():
            watcher = info["watcher"]
            watcher._running = False
            watcher._stop_event.set()
        time.sleep(0.3)


# --- Init Silver Components ---


class TestInitSilverComponents:
    """Test Silver component initialization."""

    def test_init_creates_approval_manager(self, orch):
        orch._init_silver_components()
        assert orch._approval_manager is not None

    def test_init_creates_planner(self, orch):
        orch._init_silver_components()
        assert orch._planner is not None

    def test_init_creates_scheduler(self, orch):
        orch._init_silver_components()
        assert orch._scheduler is not None

    def test_scheduler_has_tasks(self, orch):
        orch._init_silver_components()
        tasks = orch._scheduler.get_tasks()
        assert len(tasks) >= 3
        assert "create_plans" in tasks
        assert "process_approvals" in tasks
        assert "check_expired_approvals" in tasks


# --- Integration Tests ---


class TestSilverIntegration:
    """Silver tier integration tests."""

    def test_full_silver_cycle(self, vault):
        """Test a complete Silver-tier processing cycle."""
        orch = Orchestrator(vault_path=str(vault))
        orch._init_silver_components()

        # Create an item in Needs_Action
        (vault / "Needs_Action" / "test_email.md").write_text("""---
type: email
priority: high
status: pending
source: gmail
from: "client@example.com"
subject: "Important Deal"
---

# Important Deal Email
Please review this deal.
""", encoding="utf-8")

        # Run a cycle
        summary = orch.run_cycle()
        assert "timestamp" in summary
        assert "pending_items" in summary

        # Plans should have been created (scheduler ran create_plans)
        plan_files = list((vault / "Plans").glob("PLAN_*.md"))
        assert len(plan_files) >= 1

        # Dashboard should be updated
        dashboard = (vault / "Dashboard.md").read_text(encoding="utf-8")
        assert "AI Employee Dashboard" in dashboard

    def test_approval_workflow_integration(self, vault):
        """Test approval workflow through orchestrator."""
        orch = Orchestrator(vault_path=str(vault))
        orch._init_silver_components()

        # Create an approval request
        path = orch._approval_manager.create_request(
            action="email_send",
            description="Send quarterly report",
            priority="high",
        )

        # Simulate approval
        import shutil
        shutil.move(str(path), str(vault / "Approved" / path.name))

        # Process approved items through orchestrator
        count = orch.process_approved_items()
        assert count >= 1

    def test_scheduler_integration(self, vault):
        """Test scheduler tasks execute during cycle."""
        orch = Orchestrator(vault_path=str(vault))
        orch._init_silver_components()

        # First cycle triggers all scheduled tasks (first run)
        summary = orch.run_cycle()
        assert isinstance(summary["scheduled_tasks_ran"], list)
        assert len(summary["scheduled_tasks_ran"]) > 0
