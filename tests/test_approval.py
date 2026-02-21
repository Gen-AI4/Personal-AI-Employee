"""Tests for the Human-in-the-Loop Approval workflow."""

import json
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from approval import ApprovalManager, ApprovalRequest, ALWAYS_REQUIRE_APPROVAL, AUTO_APPROVE


@pytest.fixture
def vault(tmp_path):
    """Create a temporary vault with required directories."""
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    return vault_path


@pytest.fixture
def manager(vault):
    """Create an ApprovalManager with a temporary vault."""
    return ApprovalManager(vault_path=str(vault))


# --- ApprovalRequest Tests ---


class TestApprovalRequest:
    """Test the ApprovalRequest data class."""

    def test_creates_request_id(self):
        req = ApprovalRequest(action="email_send", description="Test")
        assert "email_send" in req.request_id

    def test_sets_expiry(self):
        req = ApprovalRequest(action="test", description="Test", expires_hours=48)
        delta = req.expires - req.created
        assert abs(delta.total_seconds() - 48 * 3600) < 2

    def test_default_expiry_24h(self):
        req = ApprovalRequest(action="test", description="Test")
        delta = req.expires - req.created
        assert abs(delta.total_seconds() - 24 * 3600) < 2

    def test_to_markdown_has_frontmatter(self):
        req = ApprovalRequest(action="email_send", description="Send an email")
        md = req.to_markdown()
        assert md.startswith("---\n")
        assert "type: approval_request" in md
        assert "action: email_send" in md
        assert "status: pending" in md

    def test_to_markdown_has_instructions(self):
        req = ApprovalRequest(action="payment", description="Pay invoice")
        md = req.to_markdown()
        assert "To Approve" in md
        assert "/Approved" in md
        assert "To Reject" in md
        assert "/Rejected" in md

    def test_to_markdown_includes_details(self):
        req = ApprovalRequest(
            action="email_send",
            description="Send email",
            details={"to": "alice@example.com", "subject": "Hello"},
        )
        md = req.to_markdown()
        assert "alice@example.com" in md
        assert "Hello" in md

    def test_to_markdown_escapes_quotes_in_details(self):
        req = ApprovalRequest(
            action="test",
            description="Test",
            details={"note": 'He said "hello"'},
        )
        md = req.to_markdown()
        assert '\\"hello\\"' in md

    def test_priority_included(self):
        req = ApprovalRequest(action="test", description="Test", priority="high")
        md = req.to_markdown()
        assert "priority: high" in md


# --- Constants Tests ---


class TestApprovalConstants:
    """Test the approval action classification constants."""

    def test_payment_requires_approval(self):
        assert "payment" in ALWAYS_REQUIRE_APPROVAL

    def test_email_send_requires_approval(self):
        assert "email_send" in ALWAYS_REQUIRE_APPROVAL

    def test_linkedin_post_requires_approval(self):
        assert "linkedin_post" in ALWAYS_REQUIRE_APPROVAL

    def test_file_organize_is_auto_approved(self):
        assert "file_organize" in AUTO_APPROVE

    def test_dashboard_update_is_auto_approved(self):
        assert "dashboard_update" in AUTO_APPROVE

    def test_no_overlap_between_sets(self):
        overlap = ALWAYS_REQUIRE_APPROVAL & AUTO_APPROVE
        assert len(overlap) == 0


# --- ApprovalManager Tests ---


class TestApprovalManagerInit:
    """Test ApprovalManager initialization."""

    def test_creates_directories(self, vault):
        manager = ApprovalManager(vault_path=str(vault))
        assert (vault / "Pending_Approval").exists()
        assert (vault / "Approved").exists()
        assert (vault / "Rejected").exists()
        assert (vault / "Done").exists()
        assert (vault / "Logs").exists()

    def test_sets_vault_path(self, vault):
        manager = ApprovalManager(vault_path=str(vault))
        assert manager.vault_path == vault


class TestRequiresApproval:
    """Test the requires_approval method."""

    def test_sensitive_action_requires_approval(self, manager):
        assert manager.requires_approval("email_send") is True
        assert manager.requires_approval("payment") is True
        assert manager.requires_approval("linkedin_post") is True

    def test_safe_action_does_not_require_approval(self, manager):
        assert manager.requires_approval("file_organize") is False
        assert manager.requires_approval("log_create") is False

    def test_unknown_action_does_not_require_approval(self, manager):
        assert manager.requires_approval("unknown_action") is False

    def test_is_auto_approved(self, manager):
        assert manager.is_auto_approved("file_organize") is True
        assert manager.is_auto_approved("dashboard_update") is True
        assert manager.is_auto_approved("email_send") is False


class TestCreateRequest:
    """Test creating approval requests."""

    def test_creates_file_in_pending(self, manager, vault):
        path = manager.create_request(
            action="email_send",
            description="Send test email",
        )
        assert path.exists()
        assert path.parent == vault / "Pending_Approval"

    def test_file_has_approval_prefix(self, manager):
        path = manager.create_request(action="test", description="Test")
        assert path.name.startswith("APPROVAL_")

    def test_file_has_md_extension(self, manager):
        path = manager.create_request(action="test", description="Test")
        assert path.suffix == ".md"

    def test_file_contains_frontmatter(self, manager):
        path = manager.create_request(
            action="email_send",
            description="Send email to client",
            details={"to": "client@example.com"},
            priority="high",
        )
        content = path.read_text(encoding="utf-8")
        assert "type: approval_request" in content
        assert "action: email_send" in content
        assert "priority: high" in content

    def test_creates_log_entry(self, manager, vault):
        manager.create_request(action="payment", description="Pay invoice")
        log_files = list((vault / "Logs").glob("*.json"))
        assert len(log_files) >= 1
        entries = json.loads(log_files[0].read_text(encoding="utf-8"))
        assert any(e["action_type"] == "approval_request_created" for e in entries)

    def test_request_with_details(self, manager):
        path = manager.create_request(
            action="email_send",
            description="Send email",
            details={"to": "test@test.com", "subject": "Hello"},
        )
        content = path.read_text(encoding="utf-8")
        assert "test@test.com" in content


class TestGetPendingRequests:
    """Test listing pending requests."""

    def test_empty_pending(self, manager):
        assert manager.get_pending_requests() == []

    def test_returns_pending_files(self, manager, vault):
        (vault / "Pending_Approval" / "APPROVAL_test.md").write_text("test", encoding="utf-8")
        items = manager.get_pending_requests()
        assert len(items) == 1

    def test_ignores_non_md(self, manager, vault):
        (vault / "Pending_Approval" / "data.txt").write_text("test", encoding="utf-8")
        assert manager.get_pending_requests() == []

    def test_ignores_gitkeep(self, manager, vault):
        (vault / "Pending_Approval" / ".gitkeep").write_text("", encoding="utf-8")
        assert manager.get_pending_requests() == []


class TestProcessDecisions:
    """Test processing approved and rejected items."""

    def test_processes_approved_items(self, manager, vault):
        (vault / "Approved" / "APPROVAL_test.md").write_text("approved", encoding="utf-8")
        result = manager.process_decisions()
        assert result["approved"] == 1
        assert result["rejected"] == 0
        # File should be in Done
        done_files = [f for f in (vault / "Done").iterdir() if f.name != ".gitkeep"]
        assert len(done_files) == 1

    def test_processes_rejected_items(self, manager, vault):
        (vault / "Rejected" / "APPROVAL_test.md").write_text("rejected", encoding="utf-8")
        result = manager.process_decisions()
        assert result["rejected"] == 1
        assert result["approved"] == 0

    def test_processes_both(self, manager, vault):
        (vault / "Approved" / "APPROVAL_a.md").write_text("a", encoding="utf-8")
        (vault / "Rejected" / "APPROVAL_r.md").write_text("r", encoding="utf-8")
        result = manager.process_decisions()
        assert result["approved"] == 1
        assert result["rejected"] == 1

    def test_no_items_returns_zeros(self, manager):
        result = manager.process_decisions()
        assert result == {"approved": 0, "rejected": 0}

    def test_approved_logged(self, manager, vault):
        (vault / "Approved" / "APPROVAL_test.md").write_text("a", encoding="utf-8")
        manager.process_decisions()
        log_files = list((vault / "Logs").glob("*.json"))
        entries = json.loads(log_files[0].read_text(encoding="utf-8"))
        assert any(e["action_type"] == "approval_granted" for e in entries)

    def test_rejected_logged(self, manager, vault):
        (vault / "Rejected" / "APPROVAL_test.md").write_text("r", encoding="utf-8")
        manager.process_decisions()
        log_files = list((vault / "Logs").glob("*.json"))
        entries = json.loads(log_files[0].read_text(encoding="utf-8"))
        assert any(e["action_type"] == "approval_rejected" for e in entries)


class TestCheckExpiredRequests:
    """Test expiry checking."""

    def test_no_expired_requests(self, manager, vault):
        # Create a request that expires in the future
        manager.create_request(
            action="test", description="Test", expires_hours=24
        )
        expired = manager.check_expired_requests()
        assert len(expired) == 0

    def test_detects_expired_request(self, manager, vault):
        # Create a file with an already-expired timestamp
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        content = f"""---
type: approval_request
request_id: "test_expired"
action: test
priority: medium
created: {(past - timedelta(hours=25)).isoformat()}
expires: {past.isoformat()}
status: pending
---

# Expired Request
"""
        (vault / "Pending_Approval" / "APPROVAL_expired.md").write_text(
            content, encoding="utf-8"
        )
        expired = manager.check_expired_requests()
        assert len(expired) == 1

    def test_expired_logged(self, manager, vault):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        content = f"""---
expires: {past.isoformat()}
---
Test
"""
        (vault / "Pending_Approval" / "APPROVAL_exp.md").write_text(
            content, encoding="utf-8"
        )
        manager.check_expired_requests()
        log_files = list((vault / "Logs").glob("*.json"))
        entries = json.loads(log_files[0].read_text(encoding="utf-8"))
        assert any(e["action_type"] == "approval_expired" for e in entries)


class TestApprovalIntegration:
    """Integration tests for the full approval workflow."""

    def test_full_lifecycle(self, vault):
        """End-to-end: create request → approve → process → done."""
        manager = ApprovalManager(vault_path=str(vault))

        # Step 1: Create request
        path = manager.create_request(
            action="email_send",
            description="Send quarterly report",
            details={"to": "boss@company.com"},
            priority="high",
        )
        assert path.exists()
        assert len(manager.get_pending_requests()) == 1

        # Step 2: Simulate human approval (move to Approved)
        import shutil
        approved_path = vault / "Approved" / path.name
        shutil.move(str(path), str(approved_path))
        assert len(manager.get_pending_requests()) == 0
        assert len(manager.get_approved_items()) == 1

        # Step 3: Process the decision
        result = manager.process_decisions()
        assert result["approved"] == 1
        assert len(manager.get_approved_items()) == 0

        # Step 4: Verify it's in Done
        done_files = [f for f in (vault / "Done").iterdir() if f.name != ".gitkeep"]
        assert len(done_files) == 1

    def test_rejection_lifecycle(self, vault):
        """End-to-end: create request → reject → process → done."""
        manager = ApprovalManager(vault_path=str(vault))

        path = manager.create_request(
            action="linkedin_post",
            description="Post quarterly update",
        )

        import shutil
        rejected_path = vault / "Rejected" / path.name
        shutil.move(str(path), str(rejected_path))

        result = manager.process_decisions()
        assert result["rejected"] == 1

        done_files = [f for f in (vault / "Done").iterdir() if f.name != ".gitkeep"]
        assert len(done_files) == 1
