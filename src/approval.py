"""
Human-in-the-Loop Approval Workflow.

Manages the approval lifecycle for sensitive actions:
1. Create structured approval request files in /Pending_Approval
2. Monitor /Approved and /Rejected folders for human decisions
3. Execute approved actions (or log rejections)
4. Maintain full audit trail in /Logs

Silver tier requirement: HITL approval workflow for sensitive actions.
"""

import json
import logging
import shutil
from pathlib import Path
from datetime import datetime, timezone

from log_utils import log_file_lock as _log_lock

logger = logging.getLogger(__name__)

# Actions that always require human approval
ALWAYS_REQUIRE_APPROVAL = {
    "payment",
    "email_send",
    "linkedin_post",
    "social_post",
    "file_delete",
    "external_api_call",
    "new_contact_email",
}

# Actions that can be auto-approved
AUTO_APPROVE = {
    "file_organize",
    "log_create",
    "dashboard_update",
    "plan_create",
}


class ApprovalRequest:
    """Represents a single approval request with its metadata."""

    def __init__(
        self,
        action: str,
        description: str,
        details: dict = None,
        priority: str = "medium",
        expires_hours: int = 24,
    ):
        self.action = action
        self.description = description
        self.details = details or {}
        self.priority = priority
        self.expires_hours = expires_hours
        now = datetime.now(timezone.utc)
        self.created = now
        from datetime import timedelta
        self.expires = now + timedelta(hours=expires_hours)
        self.request_id = now.strftime("%Y%m%d_%H%M%S") + f"_{action}"

    def to_markdown(self) -> str:
        """Render this request as a Markdown file with YAML frontmatter."""
        details_yaml = ""
        for key, value in self.details.items():
            escaped = str(value).replace('"', '\\"')
            details_yaml += f'  {key}: "{escaped}"\n'

        details_section = ""
        if self.details:
            details_section = "\n### Details\n"
            for key, value in self.details.items():
                details_section += f"- **{key}**: {value}\n"

        return f"""---
type: approval_request
request_id: "{self.request_id}"
action: {self.action}
priority: {self.priority}
created: {self.created.isoformat()}
expires: {self.expires.isoformat()}
status: pending
details:
{details_yaml}---

# Approval Required: {self.action.replace('_', ' ').title()}

{self.description}
{details_section}
## How to Respond
- **To Approve**: Move this file to the `/Approved` folder
- **To Reject**: Move this file to the `/Rejected` folder

> **Expires**: {self.expires.strftime('%Y-%m-%d %H:%M UTC')}
> **Priority**: {self.priority}
"""


class ApprovalManager:
    """Manages the approval workflow for sensitive actions.

    Creates approval requests, monitors for human decisions,
    and processes approved/rejected items.
    """

    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path)
        self.pending_dir = self.vault_path / "Pending_Approval"
        self.approved_dir = self.vault_path / "Approved"
        self.rejected_dir = self.vault_path / "Rejected"
        self.done_dir = self.vault_path / "Done"
        self.logs_dir = self.vault_path / "Logs"

        # Ensure directories exist
        for d in (self.pending_dir, self.approved_dir, self.rejected_dir,
                  self.done_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)

    def requires_approval(self, action: str) -> bool:
        """Check if an action requires human approval."""
        return action in ALWAYS_REQUIRE_APPROVAL

    def is_auto_approved(self, action: str) -> bool:
        """Check if an action can be auto-approved."""
        return action in AUTO_APPROVE

    def create_request(
        self,
        action: str,
        description: str,
        details: dict = None,
        priority: str = "medium",
        expires_hours: int = 24,
    ) -> Path:
        """Create an approval request file in /Pending_Approval.

        Args:
            action: The action type (e.g., 'email_send', 'payment')
            description: Human-readable description of what will happen
            details: Additional details dict (recipient, amount, etc.)
            priority: Priority level (high, medium, low)
            expires_hours: Hours until the request expires

        Returns:
            Path to the created approval request file.
        """
        request = ApprovalRequest(
            action=action,
            description=description,
            details=details,
            priority=priority,
            expires_hours=expires_hours,
        )

        filename = f"APPROVAL_{request.request_id}.md"
        filepath = self.pending_dir / filename
        filepath.write_text(request.to_markdown(), encoding="utf-8")

        self._log("approval_request_created", {
            "request_id": request.request_id,
            "action": action,
            "priority": priority,
            "file": filename,
        })

        logger.info(f"Approval request created: {filename}")
        return filepath

    def get_pending_requests(self) -> list[Path]:
        """Return list of pending approval request files."""
        try:
            return sorted(
                f for f in self.pending_dir.iterdir()
                if f.is_file() and f.suffix == ".md" and f.name != ".gitkeep"
            )
        except OSError:
            return []

    def get_approved_items(self) -> list[Path]:
        """Return list of approved items waiting to be executed."""
        try:
            return sorted(
                f for f in self.approved_dir.iterdir()
                if f.is_file() and f.suffix == ".md" and f.name != ".gitkeep"
            )
        except OSError:
            return []

    def get_rejected_items(self) -> list[Path]:
        """Return list of rejected items waiting to be archived."""
        try:
            return sorted(
                f for f in self.rejected_dir.iterdir()
                if f.is_file() and f.suffix == ".md" and f.name != ".gitkeep"
            )
        except OSError:
            return []

    def process_decisions(self) -> dict:
        """Process all approved and rejected items.

        Moves approved items to /Done and logs the decision.
        Moves rejected items to /Done and logs the rejection.

        Returns:
            Summary dict with counts of approved and rejected items.
        """
        approved_count = 0
        rejected_count = 0

        # Process approved items
        for item in self.get_approved_items():
            logger.info(f"Processing approved item: {item.name}")
            self._log("approval_granted", {
                "file": item.name,
                "approved_by": "human",
            })
            self._move_to_done(item)
            approved_count += 1

        # Process rejected items
        for item in self.get_rejected_items():
            logger.info(f"Processing rejected item: {item.name}")
            self._log("approval_rejected", {
                "file": item.name,
                "rejected_by": "human",
            })
            self._move_to_done(item)
            rejected_count += 1

        return {"approved": approved_count, "rejected": rejected_count}

    def check_expired_requests(self) -> list[Path]:
        """Find and flag expired approval requests.

        Returns list of expired request file paths.
        """
        now = datetime.now(timezone.utc)
        expired = []

        for item in self.get_pending_requests():
            try:
                content = item.read_text(encoding="utf-8")
                # Parse expiry from frontmatter
                for line in content.split("\n"):
                    if line.startswith("expires:"):
                        expires_str = line.split(":", 1)[1].strip()
                        expires_dt = datetime.fromisoformat(expires_str)
                        if now > expires_dt:
                            expired.append(item)
                            self._log("approval_expired", {
                                "file": item.name,
                            })
                        break
            except (OSError, ValueError) as e:
                logger.warning(f"Error checking expiry for {item.name}: {e}")

        return expired

    def _move_to_done(self, filepath: Path) -> Path:
        """Move a processed file to /Done with timestamp prefix."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = self.done_dir / f"{timestamp}_{filepath.name}"
        shutil.move(str(filepath), str(dest))
        return dest

    def _log(self, action_type: str, details: dict) -> None:
        """Write a structured log entry. Thread-safe."""
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        log_file = self.logs_dir / f"{today}.json"

        entry = {
            "timestamp": now.isoformat(),
            "action_type": action_type,
            "actor": "approval_manager",
            **details,
        }

        with _log_lock:
            entries = []
            if log_file.exists():
                try:
                    entries = json.loads(log_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    entries = []
            entries.append(entry)
            log_file.write_text(
                json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
            )
