"""Gold tier tests for the Orchestrator.

Tests Gold-specific features while ensuring backward compatibility
with Bronze and Silver tier functionality.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

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


# --- Gold Tier Vault Structure ---


class TestGoldVaultStructure:
    """Test that Gold tier creates all required directories."""

    def test_creates_briefings_dir(self, vault):
        orch = Orchestrator(vault_path=str(vault))
        assert (vault / "Briefings").exists()

    def test_creates_accounting_dir(self, vault):
        orch = Orchestrator(vault_path=str(vault))
        assert (vault / "Accounting").exists()

    def test_creates_all_silver_dirs(self, vault):
        orch = Orchestrator(vault_path=str(vault))
        for d in ["Pending_Approval", "Approved", "Rejected", "Plans", "Logs"]:
            assert (vault / d).exists()

    def test_creates_all_bronze_dirs(self, vault):
        orch = Orchestrator(vault_path=str(vault))
        for d in ["Inbox", "Needs_Action", "Done"]:
            assert (vault / d).exists()


# --- Gold Tier Component Initialization ---


class TestGoldComponentInit:
    """Test Gold tier component initialization."""

    def test_error_tracker_initialized(self, orch):
        assert orch._error_tracker is not None

    def test_odoo_connector_none_by_default(self, orch):
        # Odoo disabled by default (ENABLE_ODOO=false)
        assert orch._odoo is None

    def test_briefing_generator_none_before_init(self, orch):
        # Before _init_gold_components() is called
        assert orch._briefing_generator is None

    def test_init_gold_components_creates_briefing_gen(self, vault):
        with patch("orchestrator.ENABLE_CEO_BRIEFING", True), \
             patch("orchestrator.ENABLE_ODOO", False):
            orch = Orchestrator(vault_path=str(vault))
            orch._init_silver_components()
            orch._init_gold_components()
            assert orch._briefing_generator is not None

    def test_init_gold_adds_briefing_task(self, vault):
        with patch("orchestrator.ENABLE_CEO_BRIEFING", True), \
             patch("orchestrator.ENABLE_ODOO", False):
            orch = Orchestrator(vault_path=str(vault))
            orch._init_silver_components()
            orch._init_gold_components()
            tasks = orch._scheduler.get_tasks()
            assert "generate_ceo_briefing" in tasks

    def test_init_gold_no_briefing_task_when_disabled(self, vault):
        with patch("orchestrator.ENABLE_CEO_BRIEFING", False):
            orch = Orchestrator(vault_path=str(vault))
            orch._init_silver_components()
            orch._init_gold_components()
            if orch._scheduler:
                tasks = orch._scheduler.get_tasks()
                assert "generate_ceo_briefing" not in tasks

    def test_init_gold_with_odoo_enabled(self, vault):
        with patch("orchestrator.ENABLE_CEO_BRIEFING", False), \
             patch("orchestrator.ENABLE_ODOO", True), \
             patch("orchestrator.DEV_MODE", True):
            orch = Orchestrator(vault_path=str(vault))
            orch._init_silver_components()
            orch._init_gold_components()
            assert orch._odoo is not None


# --- Gold Tier Dashboard ---


class TestGoldDashboard:
    """Test Gold tier dashboard features."""

    def test_dashboard_shows_gold_tier(self, orch, vault):
        orch.update_dashboard()
        content = (vault / "Dashboard.md").read_text(encoding="utf-8")
        assert "tier: gold" in content

    def test_dashboard_shows_gold_tier_label(self, orch, vault):
        orch.update_dashboard()
        content = (vault / "Dashboard.md").read_text(encoding="utf-8")
        assert "Gold" in content

    def test_dashboard_shows_briefings_count(self, orch, vault):
        orch.update_dashboard()
        content = (vault / "Dashboard.md").read_text(encoding="utf-8")
        assert "CEO Briefings" in content

    def test_dashboard_shows_accounting_count(self, orch, vault):
        orch.update_dashboard()
        content = (vault / "Dashboard.md").read_text(encoding="utf-8")
        assert "Accounting Summaries" in content

    def test_dashboard_shows_error_recovery(self, orch, vault):
        orch.update_dashboard()
        content = (vault / "Dashboard.md").read_text(encoding="utf-8")
        assert "Error Recovery" in content

    def test_dashboard_shows_circuit_breaker(self, orch, vault):
        orch.update_dashboard()
        content = (vault / "Dashboard.md").read_text(encoding="utf-8")
        assert "Circuit Breaker" in content

    def test_dashboard_shows_briefings_count_when_present(self, orch, vault):
        # Add a briefing file
        briefings_dir = vault / "Briefings"
        briefings_dir.mkdir(exist_ok=True)
        (briefings_dir / "2026-02-24_Monday_Briefing.md").write_text(
            "briefing", encoding="utf-8"
        )
        orch.update_dashboard()
        content = (vault / "Dashboard.md").read_text(encoding="utf-8")
        assert "| CEO Briefings | 1 |" in content


# --- Gold Tier Watchers ---


class TestGoldWatchers:
    """Test Gold tier watcher initialization."""

    def test_facebook_watcher_started_when_enabled(self, vault):
        with patch("orchestrator.ENABLE_FACEBOOK", True):
            orch = Orchestrator(vault_path=str(vault))
            with patch("orchestrator.FacebookWatcher") as MockFB, \
                 patch.object(orch, "_start_watcher") as mock_start:
                MockFB.return_value = MagicMock()
                orch._start_all_watchers()
                # Check that _start_watcher was called with FacebookWatcher
                names = [call.args[0] for call in mock_start.call_args_list]
                assert "FacebookWatcher" in names

    def test_instagram_watcher_started_when_enabled(self, vault):
        with patch("orchestrator.ENABLE_INSTAGRAM", True):
            orch = Orchestrator(vault_path=str(vault))
            with patch("orchestrator.InstagramWatcher") as MockIG, \
                 patch.object(orch, "_start_watcher") as mock_start:
                MockIG.return_value = MagicMock()
                orch._start_all_watchers()
                names = [call.args[0] for call in mock_start.call_args_list]
                assert "InstagramWatcher" in names

    def test_twitter_watcher_started_when_enabled(self, vault):
        with patch("orchestrator.ENABLE_TWITTER", True):
            orch = Orchestrator(vault_path=str(vault))
            with patch("orchestrator.TwitterWatcher") as MockTW, \
                 patch.object(orch, "_start_watcher") as mock_start:
                MockTW.return_value = MagicMock()
                orch._start_all_watchers()
                names = [call.args[0] for call in mock_start.call_args_list]
                assert "TwitterWatcher" in names

    def test_social_watchers_not_started_when_disabled(self, vault):
        with patch("orchestrator.ENABLE_FACEBOOK", False), \
             patch("orchestrator.ENABLE_INSTAGRAM", False), \
             patch("orchestrator.ENABLE_TWITTER", False):
            orch = Orchestrator(vault_path=str(vault))
            with patch.object(orch, "_start_watcher") as mock_start:
                with patch("orchestrator.FileSystemWatcher") as MockFS:
                    MockFS.return_value = MagicMock()
                    orch._start_all_watchers()
                    names = [call.args[0] for call in mock_start.call_args_list]
                    assert "FacebookWatcher" not in names
                    assert "InstagramWatcher" not in names
                    assert "TwitterWatcher" not in names

    def test_facebook_watcher_failure_does_not_crash(self, vault):
        with patch("orchestrator.ENABLE_FACEBOOK", True), \
             patch("orchestrator.FacebookWatcher", side_effect=Exception("mcp not found")):
            orch = Orchestrator(vault_path=str(vault))
            # Should not raise
            orch._start_all_watchers()


# --- Error Tracking ---


class TestErrorTracking:
    """Test error tracking in the orchestrator cycle."""

    def test_error_tracker_records_cycle_errors(self, orch):
        with patch.object(orch, "_scheduler") as mock_sched:
            mock_sched.check_and_run.side_effect = RuntimeError("scheduler crash")
            orch.run_cycle()
            assert orch._error_tracker.total_errors > 0

    def test_run_cycle_returns_error_in_summary_on_failure(self, orch):
        with patch.object(orch, "_scheduler") as mock_sched:
            mock_sched.check_and_run.side_effect = RuntimeError("crash")
            result = orch.run_cycle()
            assert "error" in result

    def test_run_cycle_includes_error_tracker_status(self, orch):
        orch._init_silver_components()
        result = orch.run_cycle()
        assert "error_tracker" in result

    def test_error_tracker_status_structure(self, orch):
        status = orch._error_tracker.get_status()
        assert "total_errors" in status
        assert "recent_errors" in status
        assert "circuit_breaker" in status


# --- Gold Tier Full Cycle ---


class TestGoldCycleIntegration:
    """Integration tests for the full Gold tier processing cycle."""

    def test_full_cycle_with_briefing_generator(self, vault):
        """Test that a complete Gold cycle runs including briefing generator."""
        with patch("orchestrator.ENABLE_CEO_BRIEFING", True), \
             patch("orchestrator.ENABLE_ODOO", False):
            orch = Orchestrator(vault_path=str(vault))
            orch._init_silver_components()
            orch._init_gold_components()
            result = orch.run_cycle()
            assert "error" not in result or result.get("error") is None

    def test_approved_items_processed_in_gold_cycle(self, vault):
        orch = Orchestrator(vault_path=str(vault))
        # Do NOT init silver components — that would add a scheduler task that
        # races with process_approved_items() by also consuming the Approved folder.

        # Create an approved item
        (vault / "Approved" / "APPROVAL_test.md").write_text(
            "approved action", encoding="utf-8"
        )
        result = orch.run_cycle()
        assert result["approved_processed"] == 1
        # Item should be in Done
        done_items = list((vault / "Done").iterdir())
        assert len(done_items) == 1

    def test_gold_orchestrator_log_contains_tier(self, vault):
        orch = Orchestrator(vault_path=str(vault))
        orch._running = True
        orch._init_silver_components()
        orch.log_action("orchestrator_started", {"tier": "gold"})
        log_files = list((vault / "Logs").glob("*.json"))
        assert len(log_files) > 0
        entries = json.loads(log_files[0].read_text(encoding="utf-8"))
        gold_entries = [e for e in entries if e.get("tier") == "gold"]
        assert len(gold_entries) > 0

    def test_stop_is_safe_after_gold_init(self, vault):
        with patch("orchestrator.ENABLE_CEO_BRIEFING", True), \
             patch("orchestrator.ENABLE_ODOO", False):
            orch = Orchestrator(vault_path=str(vault))
            orch._init_silver_components()
            orch._init_gold_components()
            # Should not raise
            orch.stop()


# --- Backward Compatibility ---


class TestGoldBackwardCompatibility:
    """Test that Bronze and Silver features still work with Gold tier."""

    def test_bronze_methods_still_work(self, orch, vault):
        pending = orch.get_pending_items()
        assert isinstance(pending, list)

    def test_silver_approval_flow_works(self, vault):
        orch = Orchestrator(vault_path=str(vault))
        orch._init_silver_components()
        # Create pending approval
        (vault / "Pending_Approval" / "APPROVAL_silver_test.md").write_text(
            "---\ntype: approval_request\n---\n", encoding="utf-8"
        )
        count = len(orch._approval_manager.get_pending_requests())
        assert count == 1

    def test_watcher_property_backward_compat(self, orch):
        # Bronze compatibility property still works
        assert orch._watcher is None  # No watcher started yet

    def test_move_to_done_works(self, orch, vault):
        test_file = vault / "Needs_Action" / "test_item.md"
        test_file.write_text("test", encoding="utf-8")
        dest = orch.move_to_done(test_file)
        assert dest.exists()
        assert dest.parent == vault / "Done"
        assert not test_file.exists()
