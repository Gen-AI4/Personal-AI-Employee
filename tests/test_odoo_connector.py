"""Tests for the Odoo accounting connector (Gold tier)."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from odoo_connector import OdooConnector, SUBSCRIPTION_PATTERNS


@pytest.fixture
def vault(tmp_path):
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    (vault_path / "Accounting").mkdir()
    (vault_path / "Logs").mkdir()
    return vault_path


@pytest.fixture(autouse=True)
def force_dev_mode(monkeypatch):
    """Ensure DEV_MODE=true for all odoo connector tests regardless of .env."""
    monkeypatch.setenv("DEV_MODE", "true")
    monkeypatch.setenv("DRY_RUN", "true")


@pytest.fixture
def connector(vault, force_dev_mode):
    oc = OdooConnector(
        vault_path=str(vault),
        url="http://localhost:8069",
        db="test_db",
        user="admin",
        password="test_pass",
    )
    return oc


# --- Initialization ---


class TestOdooConnectorInit:
    """Tests for OdooConnector initialization."""

    def test_creates_accounting_dir(self, vault):
        OdooConnector(vault_path=str(vault))
        assert (vault / "Accounting").exists()

    def test_creates_logs_dir(self, vault):
        OdooConnector(vault_path=str(vault))
        assert (vault / "Logs").exists()

    def test_uid_initially_none(self, connector):
        assert connector._uid is None

    def test_available_initially_none(self, connector):
        assert connector._available is None

    def test_url_stored(self, connector):
        assert connector.url == "http://localhost:8069"

    def test_db_stored(self, connector):
        assert connector.db == "test_db"


# --- DEV_MODE behavior ---


class TestDevModeBehavior:
    """Tests for DEV_MODE mock data behavior."""

    def test_get_invoices_in_dev_mode(self, connector):
        # DEV_MODE=true is the default in tests
        invoices = connector.get_invoices()
        assert isinstance(invoices, list)
        # Should return mock data
        assert len(invoices) > 0

    def test_mock_invoices_have_expected_fields(self, connector):
        invoices = connector.get_invoices()
        for inv in invoices:
            assert "id" in inv
            assert "name" in inv
            assert "amount_total" in inv

    def test_get_payments_in_dev_mode(self, connector):
        payments = connector.get_payments()
        assert isinstance(payments, list)
        assert len(payments) > 0

    def test_mock_payments_have_expected_fields(self, connector):
        payments = connector.get_payments()
        for pay in payments:
            assert "id" in pay
            assert "amount" in pay
            assert "payment_type" in pay

    def test_is_available_returns_false_in_dev_mode(self, connector):
        # DEV_MODE=true prevents connectivity check
        result = connector.is_available()
        assert result is False


# --- Financial Summary ---


class TestFinancialSummary:
    """Tests for financial summary generation."""

    def test_generates_summary_dict(self, connector):
        summary = connector.generate_financial_summary()
        assert isinstance(summary, dict)

    def test_summary_has_required_keys(self, connector):
        summary = connector.generate_financial_summary()
        assert "total_invoiced" in summary
        assert "total_received" in summary
        assert "total_outgoing" in summary
        assert "net_revenue" in summary
        assert "invoice_count" in summary
        assert "payment_count" in summary
        assert "subscriptions" in summary

    def test_net_revenue_calculation(self, connector):
        summary = connector.generate_financial_summary()
        expected_net = summary["total_received"] - summary["total_outgoing"]
        assert abs(summary["net_revenue"] - expected_net) < 0.01

    def test_invoice_count_matches(self, connector):
        invoices = connector.get_invoices()
        summary = connector.generate_financial_summary()
        assert summary["invoice_count"] == len(invoices)

    def test_payment_count_matches(self, connector):
        payments = connector.get_payments()
        summary = connector.generate_financial_summary()
        assert summary["payment_count"] == len(payments)

    def test_subscriptions_detected(self, connector):
        summary = connector.generate_financial_summary()
        # Mock data includes Netflix payment
        sub_names = [s["name"] for s in summary["subscriptions"]]
        assert "Netflix" in sub_names


# --- Subscription Analysis ---


class TestSubscriptionAnalysis:
    """Tests for transaction subscription detection."""

    def test_detects_netflix(self, connector):
        transaction = {
            "description": "Payment to netflix.com",
            "amount": 15.99,
            "date": "2026-02-01",
        }
        result = connector.analyze_transaction(transaction)
        assert result is not None
        assert result["name"] == "Netflix"
        assert result["type"] == "subscription"

    def test_detects_spotify(self, connector):
        transaction = {
            "description": "Monthly spotify.com subscription",
            "amount": 9.99,
            "date": "2026-02-01",
        }
        result = connector.analyze_transaction(transaction)
        assert result is not None
        assert result["name"] == "Spotify"

    def test_detects_github(self, connector):
        transaction = {
            "description": "github.com Teams plan",
            "amount": 4.00,
            "date": "2026-02-01",
        }
        result = connector.analyze_transaction(transaction)
        assert result is not None
        assert result["name"] == "GitHub"

    def test_returns_none_for_non_subscription(self, connector):
        transaction = {
            "description": "Office supplies purchase",
            "amount": 45.00,
            "date": "2026-02-01",
        }
        result = connector.analyze_transaction(transaction)
        assert result is None

    def test_subscription_includes_amount(self, connector):
        transaction = {
            "description": "notion.so business",
            "amount": 20.00,
            "date": "2026-02-01",
        }
        result = connector.analyze_transaction(transaction)
        assert result["amount"] == 20.00

    def test_subscription_patterns_not_empty(self):
        assert len(SUBSCRIPTION_PATTERNS) > 0


# --- Write Accounting Summary ---


class TestWriteAccountingSummary:
    """Tests for writing accounting summary to vault."""

    def test_creates_summary_file(self, connector, vault):
        path = connector.write_accounting_summary()
        assert path.exists()

    def test_summary_in_accounting_dir(self, connector, vault):
        path = connector.write_accounting_summary()
        assert path.parent == vault / "Accounting"

    def test_summary_has_md_extension(self, connector, vault):
        path = connector.write_accounting_summary()
        assert path.suffix == ".md"

    def test_summary_filename_pattern(self, connector, vault):
        path = connector.write_accounting_summary()
        assert "Summary_" in path.name

    def test_summary_contains_frontmatter(self, connector, vault):
        path = connector.write_accounting_summary()
        content = path.read_text(encoding="utf-8")
        assert "---" in content
        assert "type: accounting_summary" in content

    def test_summary_contains_financial_data(self, connector, vault):
        path = connector.write_accounting_summary()
        content = path.read_text(encoding="utf-8")
        assert "Total Invoiced" in content
        assert "Net Revenue" in content

    def test_summary_logs_action(self, connector, vault):
        connector.write_accounting_summary()
        log_files = list((vault / "Logs").glob("*.json"))
        assert len(log_files) > 0
        entries = json.loads(log_files[0].read_text(encoding="utf-8"))
        action_types = [e["action_type"] for e in entries]
        assert "accounting_summary_generated" in action_types


# --- JSON-RPC (non-DEV_MODE) ---


class TestJsonRpc:
    """Tests for JSON-RPC calls in non-DEV mode."""

    def test_json_rpc_logs_in_dev_mode(self, connector, capsys):
        # In DEV_MODE, _json_rpc returns None and logs
        result = connector._json_rpc("/jsonrpc", "call", {"test": "params"})
        assert result is None

    def test_authenticate_returns_none_in_dev_mode(self, connector):
        result = connector.authenticate()
        assert result is None

    def test_get_journal_entries_empty_in_dev_mode(self, connector):
        entries = connector.get_journal_entries()
        assert entries == []
