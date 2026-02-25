"""Tests for the CEO Briefing generator (Gold tier)."""

import json
import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from briefing import BriefingGenerator, _extract_dollar, _generate_executive_summary


@pytest.fixture
def vault(tmp_path):
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    dirs = ["Briefings", "Done", "Logs", "Accounting", "Needs_Action"]
    for d in dirs:
        (vault_path / d).mkdir()
    return vault_path


@pytest.fixture
def generator(vault):
    return BriefingGenerator(vault_path=str(vault))


@pytest.fixture
def reference_date():
    return datetime(2026, 2, 24, 20, 0, 0, tzinfo=timezone.utc)


# --- Initialization ---


class TestBriefingGeneratorInit:
    """Tests for BriefingGenerator initialization."""

    def test_creates_briefings_dir(self, vault):
        BriefingGenerator(vault_path=str(vault))
        assert (vault / "Briefings").exists()

    def test_creates_logs_dir(self, vault):
        BriefingGenerator(vault_path=str(vault))
        assert (vault / "Logs").exists()

    def test_no_odoo_by_default(self, generator):
        assert generator.odoo is None


# --- Weekly Done Items ---


class TestWeeklyDoneItems:
    """Tests for getting weekly completed items."""

    def test_empty_done_folder(self, generator, reference_date):
        items = generator._get_weekly_done_items(reference_date)
        assert items == []

    def test_returns_items_within_week(self, vault, generator, reference_date):
        # Create a done file with recent timestamp
        recent = reference_date - timedelta(days=2)
        timestamp = recent.strftime("%Y%m%d_%H%M%S")
        (vault / "Done" / f"{timestamp}_EMAIL_test.md").write_text(
            "done", encoding="utf-8"
        )
        items = generator._get_weekly_done_items(reference_date)
        assert len(items) == 1

    def test_ignores_items_older_than_week(self, vault, generator, reference_date):
        # Create a done file with old timestamp
        old = reference_date - timedelta(days=10)
        timestamp = old.strftime("%Y%m%d_%H%M%S")
        (vault / "Done" / f"{timestamp}_OLD_item.md").write_text(
            "old", encoding="utf-8"
        )
        items = generator._get_weekly_done_items(reference_date)
        assert len(items) == 0

    def test_item_type_detection_email(self, vault, generator, reference_date):
        recent = reference_date - timedelta(days=1)
        timestamp = recent.strftime("%Y%m%d_%H%M%S")
        (vault / "Done" / f"{timestamp}_EMAIL_test_subject.md").write_text("", encoding="utf-8")
        items = generator._get_weekly_done_items(reference_date)
        assert any(item["type"] == "email" for item in items)

    def test_item_type_detection_file(self, vault, generator, reference_date):
        recent = reference_date - timedelta(days=1)
        timestamp = recent.strftime("%Y%m%d_%H%M%S")
        (vault / "Done" / f"{timestamp}_FILE_document.md").write_text("", encoding="utf-8")
        items = generator._get_weekly_done_items(reference_date)
        assert any(item["type"] == "file" for item in items)

    def test_item_type_detection_approval(self, vault, generator, reference_date):
        recent = reference_date - timedelta(days=1)
        timestamp = recent.strftime("%Y%m%d_%H%M%S")
        (vault / "Done" / f"{timestamp}_APPROVAL_payment.md").write_text("", encoding="utf-8")
        items = generator._get_weekly_done_items(reference_date)
        assert any(item["type"] == "approval" for item in items)

    def test_items_have_required_fields(self, vault, generator, reference_date):
        recent = reference_date - timedelta(days=1)
        timestamp = recent.strftime("%Y%m%d_%H%M%S")
        (vault / "Done" / f"{timestamp}_TASK_test.md").write_text("", encoding="utf-8")
        items = generator._get_weekly_done_items(reference_date)
        for item in items:
            assert "name" in item
            assert "completed_date" in item
            assert "type" in item


# --- Weekly Log Summary ---


class TestWeeklyLogSummary:
    """Tests for weekly log activity summary."""

    def test_empty_logs(self, generator, reference_date):
        summary = generator._get_weekly_log_summary(reference_date)
        assert summary["total_actions"] == 0
        assert summary["errors"] == 0

    def test_counts_actions_from_logs(self, vault, generator, reference_date):
        # Write a log file for today
        today = reference_date.strftime("%Y-%m-%d")
        log_data = [
            {"action_type": "file_moved_to_done", "result": "success"},
            {"action_type": "plan_created", "result": "success"},
            {"action_type": "approval_granted", "result": "success"},
        ]
        (vault / "Logs" / f"{today}.json").write_text(
            json.dumps(log_data), encoding="utf-8"
        )
        summary = generator._get_weekly_log_summary(reference_date)
        assert summary["total_actions"] == 3

    def test_counts_error_actions(self, vault, generator, reference_date):
        today = reference_date.strftime("%Y-%m-%d")
        log_data = [
            {"action_type": "cycle_error", "result": "failure"},
            {"action_type": "scheduled_task_failed", "result": "failure"},
        ]
        (vault / "Logs" / f"{today}.json").write_text(
            json.dumps(log_data), encoding="utf-8"
        )
        summary = generator._get_weekly_log_summary(reference_date)
        assert summary["errors"] > 0

    def test_handles_corrupted_log_file(self, vault, generator, reference_date):
        today = reference_date.strftime("%Y-%m-%d")
        (vault / "Logs" / f"{today}.json").write_text(
            "not valid json", encoding="utf-8"
        )
        # Should not raise
        summary = generator._get_weekly_log_summary(reference_date)
        assert summary["total_actions"] == 0


# --- Financial Summary ---


class TestFinancialSummaryFromAccounting:
    """Tests for reading financial data from accounting files."""

    def test_no_odoo_no_accounting_files_returns_zeros(self, generator):
        summary = generator._get_financial_summary()
        assert summary["total_invoiced"] == 0
        assert summary["net_revenue"] == 0

    def test_reads_from_accounting_file(self, vault, generator):
        accounting_content = """---
type: accounting_summary
---

## Financial Overview
| Metric | Amount |
|--------|--------|
| Total Invoiced | $4300.00 |
| Total Received | $2500.00 |
| Total Outgoing | $500.00 |
| Net Revenue | $2000.00 |
"""
        (vault / "Accounting" / "Summary_2026_02.md").write_text(
            accounting_content, encoding="utf-8"
        )
        summary = generator._get_financial_summary()
        assert summary["total_invoiced"] == 4300.00
        assert summary["total_received"] == 2500.00

    def test_odoo_connector_used_when_available(self, vault, generator):
        mock_odoo = MagicMock()
        mock_odoo.generate_financial_summary.return_value = {
            "total_invoiced": 5000.0,
            "total_received": 3000.0,
            "total_outgoing": 500.0,
            "net_revenue": 2500.0,
            "invoice_count": 5,
            "payment_count": 8,
            "subscriptions": [],
        }
        generator.odoo = mock_odoo
        summary = generator._get_financial_summary()
        assert summary["total_invoiced"] == 5000.0
        mock_odoo.generate_financial_summary.assert_called_once()

    def test_falls_back_on_odoo_failure(self, vault, generator):
        mock_odoo = MagicMock()
        mock_odoo.generate_financial_summary.side_effect = Exception("Odoo down")
        generator.odoo = mock_odoo
        # Should not raise, should fall back to accounting files
        summary = generator._get_financial_summary()
        assert isinstance(summary, dict)


# --- Briefing Generation ---


class TestBriefingGeneration:
    """Tests for the full briefing generation."""

    def test_generates_briefing_file(self, generator, vault, reference_date):
        path = generator.generate_briefing(reference_date)
        assert path.exists()
        assert path.suffix == ".md"

    def test_briefing_in_briefings_dir(self, generator, vault, reference_date):
        path = generator.generate_briefing(reference_date)
        assert path.parent == vault / "Briefings"

    def test_briefing_filename_contains_date(self, generator, vault, reference_date):
        path = generator.generate_briefing(reference_date)
        assert reference_date.strftime("%Y-%m-%d") in path.name

    def test_briefing_has_frontmatter(self, generator, vault, reference_date):
        path = generator.generate_briefing(reference_date)
        content = path.read_text(encoding="utf-8")
        assert "type: ceo_briefing" in content
        assert "generated:" in content

    def test_briefing_has_required_sections(self, generator, vault, reference_date):
        path = generator.generate_briefing(reference_date)
        content = path.read_text(encoding="utf-8")
        assert "# Monday Morning CEO Briefing" in content
        assert "## Executive Summary" in content
        assert "## Revenue" in content
        assert "## Completed Tasks" in content
        assert "## Bottlenecks" in content
        assert "## Proactive Suggestions" in content

    def test_briefing_reflects_done_items(self, vault, generator, reference_date):
        # Add some done items
        recent = reference_date - timedelta(days=1)
        timestamp = recent.strftime("%Y%m%d_%H%M%S")
        (vault / "Done" / f"{timestamp}_EMAIL_client_reply.md").write_text(
            "", encoding="utf-8"
        )
        path = generator.generate_briefing(reference_date)
        content = path.read_text(encoding="utf-8")
        assert "1 tasks completed" in content or "Completed Tasks (1" in content

    def test_briefing_logs_action(self, generator, vault, reference_date):
        generator.generate_briefing(reference_date)
        log_files = list((vault / "Logs").glob("*.json"))
        assert len(log_files) > 0
        entries = json.loads(log_files[0].read_text(encoding="utf-8"))
        action_types = [e["action_type"] for e in entries]
        assert "briefing_generated" in action_types

    def test_briefing_log_has_file_info(self, generator, vault, reference_date):
        generator.generate_briefing(reference_date)
        log_files = list((vault / "Logs").glob("*.json"))
        entries = json.loads(log_files[0].read_text(encoding="utf-8"))
        briefing_entry = next(
            (e for e in entries if e["action_type"] == "briefing_generated"),
            None
        )
        assert briefing_entry is not None
        assert "file" in briefing_entry
        assert "period_start" in briefing_entry
        assert "period_end" in briefing_entry

    def test_generates_default_date_when_none(self, generator, vault):
        # Should not raise and should use current date
        path = generator.generate_briefing()
        assert path.exists()

    def test_subscription_suggestions_present(self, vault, generator, reference_date):
        # Create accounting file with subscription data
        accounting_content = """---
type: accounting_summary
---

## Subscriptions Detected
| Service | Amount | Date |
|---------|--------|------|
| Netflix | $15.99 | 2026-02-01 |
"""
        (vault / "Accounting" / "Summary_2026_02.md").write_text(
            accounting_content, encoding="utf-8"
        )
        path = generator.generate_briefing(reference_date)
        content = path.read_text(encoding="utf-8")
        assert "Cost Optimization" in content


# --- Helper Functions ---


class TestHelperFunctions:
    """Tests for briefing helper functions."""

    def test_extract_dollar_basic(self):
        assert _extract_dollar("Total: $2,500.00") == 2500.0

    def test_extract_dollar_small(self):
        assert _extract_dollar("Amount $15.99 monthly") == 15.99

    def test_extract_dollar_no_dollar(self):
        assert _extract_dollar("No amount here") == 0.0

    def test_extract_dollar_with_comma(self):
        assert _extract_dollar("Revenue: $1,234.56") == 1234.56

    def test_exec_summary_with_done_items(self):
        items = [{"type": "email"}, {"type": "file"}]
        financial = {"net_revenue": 500.0, "total_received": 500.0}
        summary = _generate_executive_summary(items, 0, financial)
        assert "2 tasks completed" in summary

    def test_exec_summary_with_errors(self):
        items = []
        financial = {"net_revenue": 0.0, "total_received": 0.0}
        summary = _generate_executive_summary(items, 3, financial)
        assert "3 errors" in summary

    def test_exec_summary_with_negative_revenue(self):
        items = [{"type": "file"}]
        financial = {"net_revenue": -200.0, "total_received": 100.0}
        summary = _generate_executive_summary(items, 0, financial)
        assert "loss" in summary or "expenses" in summary

    def test_exec_summary_empty(self):
        summary = _generate_executive_summary([], 0, {"net_revenue": 0, "total_received": 0})
        assert isinstance(summary, str)
        assert len(summary) > 0
