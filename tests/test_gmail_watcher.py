"""Tests for the Gmail Watcher."""

import json
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from watchers.gmail_watcher import GmailWatcher, DEFAULT_GMAIL_QUERY


@pytest.fixture
def vault(tmp_path):
    """Create a temporary vault with required directories."""
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    for d in ["Needs_Action", "Logs"]:
        (vault_path / d).mkdir()
    return vault_path


@pytest.fixture
def watcher(vault):
    """Create a GmailWatcher with a temporary vault."""
    return GmailWatcher(vault_path=str(vault), check_interval=10)


# --- Init Tests ---


class TestGmailWatcherInit:
    """Test GmailWatcher initialization."""

    def test_sets_vault_path(self, vault):
        w = GmailWatcher(vault_path=str(vault))
        assert w.vault_path == vault

    def test_default_query(self, vault):
        w = GmailWatcher(vault_path=str(vault))
        assert w.query == DEFAULT_GMAIL_QUERY

    def test_custom_query(self, vault):
        w = GmailWatcher(vault_path=str(vault), query="is:unread label:work")
        assert w.query == "is:unread label:work"

    def test_default_check_interval(self, vault):
        w = GmailWatcher(vault_path=str(vault))
        assert w.check_interval == 120

    def test_custom_check_interval(self, vault):
        w = GmailWatcher(vault_path=str(vault), check_interval=60)
        assert w.check_interval == 60

    def test_empty_processed_ids(self, vault):
        w = GmailWatcher(vault_path=str(vault))
        assert len(w._processed_ids) == 0

    def test_no_service_initially(self, vault):
        w = GmailWatcher(vault_path=str(vault))
        assert w._service is None


# --- Email Priority Classification Tests ---


class TestClassifyEmailPriority:
    """Test email priority classification."""

    def test_important_label_is_high(self, watcher):
        priority = watcher._classify_email_priority(
            {"Subject": "Normal email"}, ["IMPORTANT", "INBOX"]
        )
        assert priority == "high"

    def test_urgent_subject_is_high(self, watcher):
        priority = watcher._classify_email_priority(
            {"Subject": "URGENT: Please respond"}, ["INBOX"]
        )
        assert priority == "high"

    def test_asap_subject_is_high(self, watcher):
        priority = watcher._classify_email_priority(
            {"Subject": "Need this ASAP"}, ["INBOX"]
        )
        assert priority == "high"

    def test_critical_subject_is_high(self, watcher):
        priority = watcher._classify_email_priority(
            {"Subject": "Critical system alert"}, ["INBOX"]
        )
        assert priority == "high"

    def test_invoice_subject_is_medium(self, watcher):
        priority = watcher._classify_email_priority(
            {"Subject": "Invoice #1234"}, ["INBOX"]
        )
        assert priority == "medium"

    def test_payment_subject_is_medium(self, watcher):
        priority = watcher._classify_email_priority(
            {"Subject": "Payment confirmation"}, ["INBOX"]
        )
        assert priority == "medium"

    def test_normal_subject_is_low(self, watcher):
        priority = watcher._classify_email_priority(
            {"Subject": "Hello there"}, ["INBOX"]
        )
        assert priority == "low"

    def test_empty_subject_is_low(self, watcher):
        priority = watcher._classify_email_priority({}, [])
        assert priority == "low"


# --- Header Extraction Tests ---


class TestExtractHeaders:
    """Test Gmail header extraction."""

    def test_extracts_headers(self, watcher):
        headers_list = [
            {"name": "From", "value": "alice@example.com"},
            {"name": "Subject", "value": "Hello"},
            {"name": "Date", "value": "Mon, 20 Feb 2026 10:00:00 +0000"},
        ]
        result = watcher._extract_headers(headers_list)
        assert result["From"] == "alice@example.com"
        assert result["Subject"] == "Hello"

    def test_empty_headers(self, watcher):
        result = watcher._extract_headers([])
        assert result == {}


# --- Check For Updates Tests ---


class TestCheckForUpdates:
    """Test Gmail polling for updates."""

    def test_returns_empty_when_no_service(self, watcher):
        watcher._service = None
        # _authenticate will fail without google libs
        with patch.object(watcher, '_get_service', return_value=None):
            result = watcher.check_for_updates()
            assert result == []

    def test_returns_messages_from_api(self, watcher):
        mock_service = MagicMock()
        # Mock the Gmail API chain
        mock_service.users().messages().list().execute.return_value = {
            "messages": [{"id": "msg_001"}]
        }
        mock_service.users().messages().get().execute.return_value = {
            "id": "msg_001",
            "snippet": "Hello world",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "test@example.com"},
                    {"name": "Subject", "value": "Test Email"},
                    {"name": "Date", "value": "Mon, 20 Feb 2026"},
                ]
            },
        }
        watcher._service = mock_service

        result = watcher.check_for_updates()
        assert len(result) == 1
        assert result[0]["id"] == "msg_001"
        assert result[0]["headers"]["From"] == "test@example.com"

    def test_skips_already_processed(self, watcher):
        watcher._processed_ids.add("msg_001")
        mock_service = MagicMock()
        mock_service.users().messages().list().execute.return_value = {
            "messages": [{"id": "msg_001"}]
        }
        watcher._service = mock_service

        result = watcher.check_for_updates()
        assert result == []

    def test_handles_api_error(self, watcher):
        mock_service = MagicMock()
        mock_service.users().messages().list().execute.side_effect = Exception("API Error")
        watcher._service = mock_service

        result = watcher.check_for_updates()
        assert result == []


# --- Create Action File Tests ---


class TestCreateActionFile:
    """Test action file creation for Gmail messages."""

    def test_creates_email_file(self, watcher, vault):
        item = {
            "id": "msg_123",
            "headers": {
                "From": "sender@example.com",
                "Subject": "Test Subject",
                "Date": "Mon, 20 Feb 2026",
            },
            "snippet": "Email preview text here",
            "label_ids": ["INBOX"],
        }
        path = watcher.create_action_file(item)
        assert path.exists()
        assert path.parent == vault / "Needs_Action"

    def test_filename_has_email_prefix(self, watcher, vault):
        item = {
            "id": "msg_123",
            "headers": {"From": "x@x.com", "Subject": "Test", "Date": ""},
            "snippet": "",
            "label_ids": [],
        }
        path = watcher.create_action_file(item)
        assert path.name.startswith("EMAIL_")

    def test_file_has_frontmatter(self, watcher, vault):
        item = {
            "id": "msg_456",
            "headers": {
                "From": "alice@test.com",
                "Subject": "Important Meeting",
                "Date": "Tue, 21 Feb 2026",
            },
            "snippet": "Please join the meeting",
            "label_ids": ["IMPORTANT"],
        }
        path = watcher.create_action_file(item)
        content = path.read_text(encoding="utf-8")
        assert "type: email" in content
        assert "priority: high" in content
        assert 'from: "alice@test.com"' in content

    def test_marks_as_processed(self, watcher, vault):
        item = {
            "id": "msg_789",
            "headers": {"From": "x@x.com", "Subject": "Test", "Date": ""},
            "snippet": "",
            "label_ids": [],
        }
        watcher.create_action_file(item)
        assert "msg_789" in watcher._processed_ids

    def test_creates_log_entry(self, watcher, vault):
        item = {
            "id": "msg_log",
            "headers": {"From": "x@x.com", "Subject": "Test", "Date": ""},
            "snippet": "",
            "label_ids": [],
        }
        watcher.create_action_file(item)
        log_files = list((vault / "Logs").glob("*.json"))
        assert len(log_files) >= 1
        entries = json.loads(log_files[0].read_text(encoding="utf-8"))
        assert any(e["action_type"] == "email_detected" for e in entries)

    def test_sanitizes_subject_in_filename(self, watcher, vault):
        item = {
            "id": "msg_special",
            "headers": {
                "From": "x@x.com",
                "Subject": "Re: Invoice <script>alert('xss')</script>",
                "Date": "",
            },
            "snippet": "",
            "label_ids": [],
        }
        path = watcher.create_action_file(item)
        # Filename should not contain < > ' ( ) characters
        assert "<" not in path.name
        assert ">" not in path.name

    def test_includes_snippet(self, watcher, vault):
        item = {
            "id": "msg_snip",
            "headers": {"From": "x@x.com", "Subject": "Hello", "Date": ""},
            "snippet": "This is the preview text",
            "label_ids": [],
        }
        path = watcher.create_action_file(item)
        content = path.read_text(encoding="utf-8")
        assert "This is the preview text" in content


# --- Run Tests ---


class TestGmailWatcherRun:
    """Test the run method."""

    def test_run_exits_without_service(self, watcher):
        with patch.object(watcher, '_get_service', return_value=None):
            # Should return without error (no infinite loop)
            watcher.run()

    def test_run_with_service_calls_super(self, watcher):
        mock_service = MagicMock()
        with patch.object(watcher, '_get_service', return_value=mock_service):
            with patch.object(watcher, '_stop_event') as mock_event:
                mock_event.wait.return_value = True  # Stop immediately
                watcher._running = False
                watcher.run()
