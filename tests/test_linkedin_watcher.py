"""Tests for the LinkedIn Watcher."""

import json
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from watchers.linkedin_watcher import LinkedInWatcher, DEFAULT_MCP_CLIENT, DEFAULT_MCP_URL


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
    """Create a LinkedInWatcher with a temporary vault."""
    return LinkedInWatcher(vault_path=str(vault), check_interval=300)


# --- Init Tests ---


class TestLinkedInWatcherInit:
    """Test LinkedInWatcher initialization."""

    def test_sets_vault_path(self, vault):
        w = LinkedInWatcher(vault_path=str(vault))
        assert w.vault_path == vault

    def test_default_check_interval(self, vault):
        w = LinkedInWatcher(vault_path=str(vault))
        assert w.check_interval == 300

    def test_custom_check_interval(self, vault):
        w = LinkedInWatcher(vault_path=str(vault), check_interval=60)
        assert w.check_interval == 60

    def test_default_mcp_url(self, vault):
        w = LinkedInWatcher(vault_path=str(vault))
        assert w.mcp_url == DEFAULT_MCP_URL

    def test_custom_mcp_url(self, vault):
        w = LinkedInWatcher(vault_path=str(vault), mcp_url="http://localhost:9999")
        assert w.mcp_url == "http://localhost:9999"

    def test_empty_processed_ids(self, vault):
        w = LinkedInWatcher(vault_path=str(vault))
        assert len(w._processed_ids) == 0

    def test_mcp_available_none_initially(self, vault):
        w = LinkedInWatcher(vault_path=str(vault))
        assert w._mcp_available is None


# --- Notification Classification Tests ---


class TestClassifyNotification:
    """Test notification type classification."""

    def test_message_type(self, watcher):
        assert watcher._classify_notification("messaged you") == "message"
        assert watcher._classify_notification("sent you") == "message"
        assert watcher._classify_notification("invited you") == "message"

    def test_connection_type(self, watcher):
        assert watcher._classify_notification("connection request") == "connection"

    def test_engagement_type(self, watcher):
        assert watcher._classify_notification("commented on") == "engagement"
        assert watcher._classify_notification("liked your") == "engagement"
        assert watcher._classify_notification("mentioned you") == "engagement"
        assert watcher._classify_notification("endorsed you") == "engagement"

    def test_unknown_type(self, watcher):
        assert watcher._classify_notification("viewed your profile") == "notification"


class TestNotificationPriority:
    """Test notification priority assignment."""

    def test_message_is_high(self, watcher):
        assert watcher._get_notification_priority("message") == "high"

    def test_connection_is_medium(self, watcher):
        assert watcher._get_notification_priority("connection") == "medium"

    def test_engagement_is_low(self, watcher):
        assert watcher._get_notification_priority("engagement") == "low"

    def test_notification_is_low(self, watcher):
        assert watcher._get_notification_priority("notification") == "low"

    def test_unknown_is_low(self, watcher):
        assert watcher._get_notification_priority("unknown") == "low"


# --- Parse Notifications Tests ---


class TestParseNotifications:
    """Test notification parsing from page snapshots."""

    def test_empty_snapshot(self, watcher):
        result = watcher._parse_notifications("")
        assert result == []

    def test_none_snapshot(self, watcher):
        result = watcher._parse_notifications(None)
        assert result == []

    def test_detects_message_notification(self, watcher):
        snapshot = "John Doe messaged you about a new opportunity"
        result = watcher._parse_notifications(snapshot)
        assert len(result) == 1
        assert result[0]["type"] == "message"

    def test_detects_connection_request(self, watcher):
        snapshot = "Jane Smith sent you a connection request"
        result = watcher._parse_notifications(snapshot)
        assert len(result) == 1
        assert result[0]["type"] == "connection"

    def test_detects_engagement(self, watcher):
        snapshot = "Bob commented on your post about AI"
        result = watcher._parse_notifications(snapshot)
        assert len(result) == 1
        assert result[0]["type"] == "engagement"

    def test_multiple_notifications(self, watcher):
        snapshot = """John messaged you about a deal
Alice liked your post
Bob sent you a connection request"""
        result = watcher._parse_notifications(snapshot)
        assert len(result) == 3

    def test_skips_processed_ids(self, watcher):
        snapshot = "John messaged you"
        # First parse
        result1 = watcher._parse_notifications(snapshot)
        assert len(result1) == 1
        # Mark as processed
        watcher._processed_ids.add(result1[0]["id"])
        # Second parse should skip it
        result2 = watcher._parse_notifications(snapshot)
        assert len(result2) == 0

    def test_notification_has_id(self, watcher):
        snapshot = "Alice liked your post"
        result = watcher._parse_notifications(snapshot)
        assert result[0]["id"].startswith("li_")

    def test_content_truncated_at_300(self, watcher):
        long_text = "Alice liked your " + "x" * 400
        result = watcher._parse_notifications(long_text)
        assert len(result[0]["content"]) <= 300


# --- MCP Call Tests ---


class TestCallMcp:
    """Test MCP tool calling."""

    def test_handles_missing_client(self, watcher):
        watcher.mcp_client = "/nonexistent/path/mcp-client.py"
        result = watcher._call_mcp("browser_navigate", {"url": "about:blank"})
        assert result is None

    @patch("watchers.linkedin_watcher.subprocess.run")
    def test_handles_timeout(self, mock_run, watcher):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=30)
        result = watcher._call_mcp("browser_navigate", {"url": "test"})
        assert result is None

    @patch("watchers.linkedin_watcher.subprocess.run")
    def test_parses_json_output(self, mock_run, watcher):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"status": "ok"}',
            stderr="",
        )
        result = watcher._call_mcp("browser_snapshot", {})
        assert result == {"status": "ok"}

    @patch("watchers.linkedin_watcher.subprocess.run")
    def test_returns_raw_on_invalid_json(self, mock_run, watcher):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="not json",
            stderr="",
        )
        result = watcher._call_mcp("browser_snapshot", {})
        assert result == {"raw": "not json"}

    @patch("watchers.linkedin_watcher.subprocess.run")
    def test_returns_none_on_error(self, mock_run, watcher):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error occurred",
        )
        result = watcher._call_mcp("browser_navigate", {"url": "test"})
        assert result is None


# --- Check MCP Available Tests ---


class TestCheckMcpAvailable:
    """Test MCP availability checking."""

    def test_caches_result(self, watcher):
        with patch.object(watcher, '_call_mcp', return_value={"status": "ok"}):
            watcher._check_mcp_available()
            assert watcher._mcp_available is True
            # Second call should use cache
            watcher._check_mcp_available()

    def test_unavailable_when_call_fails(self, watcher):
        with patch.object(watcher, '_call_mcp', return_value=None):
            result = watcher._check_mcp_available()
            assert result is False


# --- Check For Updates Tests ---


class TestCheckForUpdates:
    """Test LinkedIn notification checking."""

    def test_returns_empty_when_mcp_unavailable(self, watcher):
        watcher._mcp_available = False
        result = watcher.check_for_updates()
        assert result == []

    def test_returns_empty_when_navigation_fails(self, watcher):
        watcher._mcp_available = True
        with patch.object(watcher, '_navigate_to_linkedin', return_value=False):
            result = watcher.check_for_updates()
            assert result == []

    def test_returns_empty_when_snapshot_fails(self, watcher):
        watcher._mcp_available = True
        with patch.object(watcher, '_navigate_to_linkedin', return_value=True):
            with patch.object(watcher, '_get_page_snapshot', return_value=None):
                result = watcher.check_for_updates()
                assert result == []

    def test_returns_notifications_on_success(self, watcher):
        watcher._mcp_available = True
        snapshot = "John messaged you about a project"
        with patch.object(watcher, '_navigate_to_linkedin', return_value=True):
            with patch.object(watcher, '_get_page_snapshot', return_value=snapshot):
                result = watcher.check_for_updates()
                assert len(result) == 1


# --- Create Action File Tests ---


class TestCreateActionFile:
    """Test action file creation for LinkedIn notifications."""

    def test_creates_file(self, watcher, vault):
        item = {
            "id": "li_12345678",
            "type": "message",
            "content": "John Doe messaged you about AI consulting",
            "keyword": "messaged you",
        }
        path = watcher.create_action_file(item)
        assert path.exists()
        assert path.parent == vault / "Needs_Action"

    def test_filename_has_linkedin_prefix(self, watcher, vault):
        item = {
            "id": "li_abc",
            "type": "connection",
            "content": "Connection request",
            "keyword": "connection request",
        }
        path = watcher.create_action_file(item)
        assert path.name.startswith("LINKEDIN_")

    def test_file_has_frontmatter(self, watcher, vault):
        item = {
            "id": "li_front",
            "type": "message",
            "content": "Test message",
            "keyword": "messaged you",
        }
        path = watcher.create_action_file(item)
        content = path.read_text(encoding="utf-8")
        assert "type: linkedin_message" in content
        assert "priority: high" in content
        assert "source: linkedin" in content

    def test_marks_as_processed(self, watcher, vault):
        item = {
            "id": "li_proc",
            "type": "engagement",
            "content": "Someone liked your post",
            "keyword": "liked your",
        }
        watcher.create_action_file(item)
        assert "li_proc" in watcher._processed_ids

    def test_creates_log_entry(self, watcher, vault):
        item = {
            "id": "li_logged",
            "type": "connection",
            "content": "Connection request",
            "keyword": "connection request",
        }
        watcher.create_action_file(item)
        log_files = list((vault / "Logs").glob("*.json"))
        assert len(log_files) >= 1
        entries = json.loads(log_files[0].read_text(encoding="utf-8"))
        assert any(
            e["action_type"] == "linkedin_notification_detected" for e in entries
        )

    def test_escapes_quotes_in_content(self, watcher, vault):
        item = {
            "id": "li_quote",
            "type": "message",
            "content": 'He said "check this out" today',
            "keyword": "messaged you",
        }
        path = watcher.create_action_file(item)
        content = path.read_text(encoding="utf-8")
        # YAML frontmatter should have escaped quotes
        assert '\\"' in content


# --- Run Tests ---


class TestLinkedInWatcherRun:
    """Test the run method."""

    def test_run_exits_without_mcp(self, watcher):
        watcher._mcp_available = False
        # Should return without error (no infinite loop)
        watcher.run()

    def test_run_starts_with_mcp(self, watcher):
        watcher._mcp_available = True
        with patch.object(watcher, '_stop_event') as mock_event:
            mock_event.wait.return_value = True  # Stop immediately
            watcher._running = False
            watcher.run()
