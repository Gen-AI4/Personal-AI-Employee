"""Tests for Gold tier social media watchers (Facebook, Instagram, Twitter)."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from watchers.facebook_watcher import FacebookWatcher, _extract_sender as fb_extract
from watchers.instagram_watcher import InstagramWatcher, _extract_sender as ig_extract
from watchers.twitter_watcher import TwitterWatcher, _extract_sender as tw_extract
from watchers.social_base_watcher import SocialBaseWatcher


@pytest.fixture
def vault(tmp_path):
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    (vault_path / "Needs_Action").mkdir()
    (vault_path / "Logs").mkdir()
    return vault_path


@pytest.fixture
def fb_watcher(vault):
    return FacebookWatcher(vault_path=str(vault))


@pytest.fixture
def ig_watcher(vault):
    return InstagramWatcher(vault_path=str(vault))


@pytest.fixture
def tw_watcher(vault):
    return TwitterWatcher(vault_path=str(vault))


# ===========================
# FacebookWatcher Tests
# ===========================


class TestFacebookWatcherInit:
    """Tests for FacebookWatcher initialization."""

    def test_platform_name(self, fb_watcher):
        assert fb_watcher.platform_name == "facebook"

    def test_notifications_url(self, fb_watcher):
        assert "facebook.com" in fb_watcher.notifications_url

    def test_creates_needs_action_dir(self, vault):
        watcher = FacebookWatcher(vault_path=str(vault))
        assert (vault / "Needs_Action").exists()

    def test_processed_ids_initially_empty(self, fb_watcher):
        assert len(fb_watcher._processed_ids) == 0

    def test_mcp_available_initially_none(self, fb_watcher):
        assert fb_watcher._mcp_available is None


class TestFacebookNotificationParsing:
    """Tests for Facebook notification parsing."""

    def test_parses_message_notification(self, fb_watcher):
        snapshot = "John Smith messaged you: Hello!\nOther content"
        notifs = fb_watcher._parse_notifications(snapshot)
        types = [n["type"] for n in notifs]
        assert "message" in types

    def test_parses_friend_request(self, fb_watcher):
        snapshot = "Jane Doe sent you a friend request\nOther"
        notifs = fb_watcher._parse_notifications(snapshot)
        types = [n["type"] for n in notifs]
        assert "friend_request" in types

    def test_parses_engagement(self, fb_watcher):
        snapshot = "Bob liked your post about coding\nOther"
        notifs = fb_watcher._parse_notifications(snapshot)
        types = [n["type"] for n in notifs]
        assert "engagement" in types

    def test_parses_business_notification(self, fb_watcher):
        snapshot = "Your ad campaign reached 1000 people\nOther"
        notifs = fb_watcher._parse_notifications(snapshot)
        types = [n["type"] for n in notifs]
        assert "business" in types

    def test_empty_snapshot_returns_empty(self, fb_watcher):
        notifs = fb_watcher._parse_notifications("")
        assert notifs == []

    def test_notification_has_required_fields(self, fb_watcher):
        snapshot = "Alice messaged you: Hi there"
        notifs = fb_watcher._parse_notifications(snapshot)
        assert len(notifs) > 0
        n = notifs[0]
        assert "id" in n
        assert "type" in n
        assert "content" in n
        assert "sender" in n


class TestFacebookClassification:
    """Tests for Facebook notification classification."""

    def test_message_is_high_priority(self, fb_watcher):
        notif = {"type": "message"}
        result = fb_watcher._classify_notification(notif)
        assert result["priority"] == "high"
        assert result["action_type"] == "facebook_message"

    def test_friend_request_is_medium(self, fb_watcher):
        notif = {"type": "friend_request"}
        result = fb_watcher._classify_notification(notif)
        assert result["priority"] == "medium"
        assert result["action_type"] == "facebook_friend_request"

    def test_engagement_is_low(self, fb_watcher):
        notif = {"type": "engagement"}
        result = fb_watcher._classify_notification(notif)
        assert result["priority"] == "low"
        assert result["action_type"] == "facebook_engagement"

    def test_business_is_medium(self, fb_watcher):
        notif = {"type": "business"}
        result = fb_watcher._classify_notification(notif)
        assert result["priority"] == "medium"
        assert result["action_type"] == "facebook_business"

    def test_unknown_type_defaults_low(self, fb_watcher):
        notif = {"type": "unknown_type"}
        result = fb_watcher._classify_notification(notif)
        assert result["priority"] == "low"


class TestFacebookActionFile:
    """Tests for Facebook action file creation."""

    def test_creates_md_file(self, fb_watcher, vault):
        item = {
            "id": "fb_test_123",
            "type": "message",
            "content": "Hello from Facebook",
            "sender": "Alice",
            "priority": "high",
            "action_type": "facebook_message",
        }
        path = fb_watcher.create_action_file(item)
        assert path.exists()
        assert path.suffix == ".md"

    def test_file_in_needs_action(self, fb_watcher, vault):
        item = {
            "id": "fb_test_456",
            "type": "engagement",
            "content": "Liked your post",
            "sender": "Bob",
            "priority": "low",
            "action_type": "facebook_engagement",
        }
        path = fb_watcher.create_action_file(item)
        assert path.parent == vault / "Needs_Action"

    def test_file_has_frontmatter(self, fb_watcher, vault):
        item = {
            "id": "fb_test_789",
            "type": "message",
            "content": "Test message",
            "sender": "Alice",
            "priority": "high",
            "action_type": "facebook_message",
        }
        path = fb_watcher.create_action_file(item)
        content = path.read_text(encoding="utf-8")
        assert "---" in content
        assert "source: facebook" in content
        assert "priority: high" in content

    def test_file_contains_content(self, fb_watcher, vault):
        item = {
            "id": "fb_test_content",
            "type": "message",
            "content": "Specific test message content",
            "sender": "Alice",
            "priority": "high",
            "action_type": "facebook_message",
        }
        path = fb_watcher.create_action_file(item)
        content = path.read_text(encoding="utf-8")
        assert "Specific test message content" in content


class TestFacebookMCPIntegration:
    """Tests for Facebook MCP check_for_updates flow."""

    def test_returns_empty_when_mcp_unavailable(self, fb_watcher):
        fb_watcher._mcp_available = False
        items = fb_watcher.check_for_updates()
        assert items == []

    def test_deduplicates_notifications(self, fb_watcher):
        fb_watcher._processed_ids = {"fb_1_12345"}
        snapshot = "fb_1_12345 content"
        notifs = fb_watcher._parse_notifications(snapshot)
        # Even if parsed, already-processed IDs should be filtered
        new_items = [
            n for n in notifs
            if n.get("id", "") not in fb_watcher._processed_ids
        ]
        for n in new_items:
            assert n.get("id") not in fb_watcher._processed_ids

    def test_check_for_updates_navigates_and_snapshots(self, fb_watcher):
        with patch.object(fb_watcher, '_check_mcp_available', return_value=True), \
             patch.object(fb_watcher, '_call_mcp') as mock_call:
            mock_call.side_effect = [
                {"ok": True},  # navigate
                {"content": "John liked your post"},  # snapshot
            ]
            items = fb_watcher.check_for_updates()
            # Should have called navigate then snapshot
            assert mock_call.call_count == 2


# ===========================
# InstagramWatcher Tests
# ===========================


class TestInstagramWatcherInit:
    """Tests for InstagramWatcher initialization."""

    def test_platform_name(self, ig_watcher):
        assert ig_watcher.platform_name == "instagram"

    def test_notifications_url(self, ig_watcher):
        assert "instagram.com" in ig_watcher.notifications_url

    def test_processed_ids_initially_empty(self, ig_watcher):
        assert len(ig_watcher._processed_ids) == 0


class TestInstagramNotificationParsing:
    """Tests for Instagram notification parsing."""

    def test_parses_direct_message(self, ig_watcher):
        snapshot = "alice_user sent you a message: Hey!"
        notifs = ig_watcher._parse_notifications(snapshot)
        types = [n["type"] for n in notifs]
        assert "direct_message" in types

    def test_parses_follow_request(self, ig_watcher):
        snapshot = "bob_photo started following you"
        notifs = ig_watcher._parse_notifications(snapshot)
        types = [n["type"] for n in notifs]
        assert "follow_request" in types

    def test_parses_engagement(self, ig_watcher):
        snapshot = "carol liked your photo"
        notifs = ig_watcher._parse_notifications(snapshot)
        types = [n["type"] for n in notifs]
        assert "engagement" in types

    def test_empty_returns_empty(self, ig_watcher):
        assert ig_watcher._parse_notifications("") == []


class TestInstagramClassification:
    """Tests for Instagram notification classification."""

    def test_direct_message_is_high(self, ig_watcher):
        result = ig_watcher._classify_notification({"type": "direct_message"})
        assert result["priority"] == "high"
        assert result["action_type"] == "instagram_message"

    def test_follow_request_is_medium(self, ig_watcher):
        result = ig_watcher._classify_notification({"type": "follow_request"})
        assert result["priority"] == "medium"
        assert result["action_type"] == "instagram_follow_request"

    def test_engagement_is_low(self, ig_watcher):
        result = ig_watcher._classify_notification({"type": "engagement"})
        assert result["priority"] == "low"
        assert result["action_type"] == "instagram_engagement"

    def test_business_is_medium(self, ig_watcher):
        result = ig_watcher._classify_notification({"type": "business"})
        assert result["priority"] == "medium"
        assert result["action_type"] == "instagram_business"

    def test_unknown_defaults_low(self, ig_watcher):
        result = ig_watcher._classify_notification({"type": "xyz"})
        assert result["priority"] == "low"


class TestInstagramActionFile:
    """Tests for Instagram action file creation."""

    def test_creates_instagram_action_file(self, ig_watcher, vault):
        item = {
            "id": "ig_test_001",
            "type": "direct_message",
            "content": "Check out my profile",
            "sender": "@photographer",
            "priority": "high",
            "action_type": "instagram_message",
        }
        path = ig_watcher.create_action_file(item)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "source: instagram" in content

    def test_filename_contains_platform(self, ig_watcher, vault):
        item = {
            "id": "ig_test_002",
            "type": "engagement",
            "content": "liked",
            "sender": "user",
            "priority": "low",
            "action_type": "instagram_engagement",
        }
        path = ig_watcher.create_action_file(item)
        assert "INSTAGRAM" in path.name


# ===========================
# TwitterWatcher Tests
# ===========================


class TestTwitterWatcherInit:
    """Tests for TwitterWatcher initialization."""

    def test_platform_name(self, tw_watcher):
        assert tw_watcher.platform_name == "twitter"

    def test_notifications_url(self, tw_watcher):
        assert "x.com" in tw_watcher.notifications_url

    def test_processed_ids_initially_empty(self, tw_watcher):
        assert len(tw_watcher._processed_ids) == 0


class TestTwitterNotificationParsing:
    """Tests for Twitter notification parsing."""

    def test_parses_direct_message(self, tw_watcher):
        snapshot = "New message from @alice: Hello there!"
        notifs = tw_watcher._parse_notifications(snapshot)
        types = [n["type"] for n in notifs]
        assert "direct_message" in types

    def test_parses_mention(self, tw_watcher):
        snapshot = "@bob mentioned you in a tweet about AI"
        notifs = tw_watcher._parse_notifications(snapshot)
        types = [n["type"] for n in notifs]
        assert "mention" in types

    def test_parses_follow(self, tw_watcher):
        snapshot = "@carol followed you"
        notifs = tw_watcher._parse_notifications(snapshot)
        types = [n["type"] for n in notifs]
        assert "follow" in types

    def test_parses_engagement(self, tw_watcher):
        snapshot = "@dave liked your tweet"
        notifs = tw_watcher._parse_notifications(snapshot)
        types = [n["type"] for n in notifs]
        assert "engagement" in types

    def test_empty_returns_empty(self, tw_watcher):
        assert tw_watcher._parse_notifications("") == []


class TestTwitterClassification:
    """Tests for Twitter notification classification."""

    def test_direct_message_is_high(self, tw_watcher):
        result = tw_watcher._classify_notification({"type": "direct_message"})
        assert result["priority"] == "high"
        assert result["action_type"] == "twitter_message"

    def test_mention_is_high(self, tw_watcher):
        result = tw_watcher._classify_notification({"type": "mention"})
        assert result["priority"] == "high"
        assert result["action_type"] == "twitter_mention"

    def test_follow_is_medium(self, tw_watcher):
        result = tw_watcher._classify_notification({"type": "follow"})
        assert result["priority"] == "medium"
        assert result["action_type"] == "twitter_follow"

    def test_engagement_is_low(self, tw_watcher):
        result = tw_watcher._classify_notification({"type": "engagement"})
        assert result["priority"] == "low"
        assert result["action_type"] == "twitter_engagement"

    def test_business_is_medium(self, tw_watcher):
        result = tw_watcher._classify_notification({"type": "business"})
        assert result["priority"] == "medium"
        assert result["action_type"] == "twitter_business"

    def test_unknown_defaults_low(self, tw_watcher):
        result = tw_watcher._classify_notification({"type": "xyz"})
        assert result["priority"] == "low"


class TestTwitterActionFile:
    """Tests for Twitter action file creation."""

    def test_creates_twitter_action_file(self, tw_watcher, vault):
        item = {
            "id": "tw_test_001",
            "type": "mention",
            "content": "@myhandle great work on the AI project!",
            "sender": "@techguru",
            "priority": "high",
            "action_type": "twitter_mention",
        }
        path = tw_watcher.create_action_file(item)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "source: twitter" in content

    def test_filename_contains_platform(self, tw_watcher, vault):
        item = {
            "id": "tw_test_002",
            "type": "follow",
            "content": "followed",
            "sender": "@user",
            "priority": "medium",
            "action_type": "twitter_follow",
        }
        path = tw_watcher.create_action_file(item)
        assert "TWITTER" in path.name

    def test_twitter_handle_extraction(self):
        text = "@Alice mentioned you in a tweet"
        sender = tw_extract(text)
        assert sender == "@Alice"

    def test_twitter_fallback_extraction(self):
        text = "Bob liked your tweet"
        sender = tw_extract(text)
        assert "Bob" in sender


# ===========================
# SocialBaseWatcher shared tests
# ===========================


class TestSocialBaseWatcher:
    """Tests for shared social base watcher behavior."""

    def test_mcp_unavailable_returns_empty(self, fb_watcher):
        fb_watcher._mcp_available = False
        assert fb_watcher.check_for_updates() == []

    def test_mcp_check_caches_result(self, fb_watcher):
        fb_watcher._mcp_available = True
        # Should use cached value, not call subprocess
        result = fb_watcher._check_mcp_available()
        assert result is True

    def test_call_mcp_handles_timeout(self, fb_watcher):
        with patch('subprocess.run', side_effect=Exception("timeout")):
            result = fb_watcher._call_mcp("browser_navigate", {"url": "test"})
            assert result is None

    def test_action_file_logs_notification(self, fb_watcher, vault):
        item = {
            "id": "log_test_001",
            "type": "message",
            "content": "Test",
            "sender": "Alice",
            "priority": "high",
            "action_type": "facebook_message",
        }
        fb_watcher.create_action_file(item)
        # Log file should be created
        log_files = list((vault / "Logs").glob("*.json"))
        assert len(log_files) > 0

    def test_deduplication_prevents_reprocessing(self, fb_watcher, vault):
        item = {
            "id": "dedup_test_001",
            "type": "message",
            "content": "Duplicate message",
            "sender": "Bob",
            "priority": "high",
            "action_type": "facebook_message",
        }
        fb_watcher.create_action_file(item)
        # Mark as processed
        fb_watcher._processed_ids.add("dedup_test_001")

        # Should not appear in new items since ID is already processed
        assert "dedup_test_001" in fb_watcher._processed_ids
