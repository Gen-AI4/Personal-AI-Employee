"""
Planner - Claude reasoning loop that creates Plan.md files.

Reads items from /Needs_Action, analyzes them against the Company_Handbook
and Business_Goals, and creates structured Plan.md files in /Plans with
step-by-step actions and checkboxes.

Silver tier requirement: Claude reasoning loop that creates Plan.md files.
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone

from log_utils import log_file_lock as _log_lock

logger = logging.getLogger(__name__)

# Action type to plan template mapping
PLAN_TEMPLATES = {
    "email": {
        "title": "Email Response Plan",
        "default_steps": [
            "Read and analyze email content",
            "Check Company_Handbook for response guidelines",
            "Draft response",
            "Submit for approval (if external)",
            "Send response",
            "Log action and move to Done",
        ],
    },
    "file_drop": {
        "title": "File Processing Plan",
        "default_steps": [
            "Review file contents and metadata",
            "Categorize file by type and priority",
            "Determine required actions",
            "Execute processing steps",
            "Update Dashboard",
            "Move to Done",
        ],
    },
    "linkedin_message": {
        "title": "LinkedIn Message Response Plan",
        "default_steps": [
            "Read message content",
            "Check if sender is known contact",
            "Draft appropriate response",
            "Submit for approval",
            "Send response via LinkedIn",
            "Log action",
        ],
    },
    "linkedin_connection": {
        "title": "LinkedIn Connection Plan",
        "default_steps": [
            "Review connection request profile",
            "Check against business goals for relevance",
            "Accept or decline connection",
            "Send welcome message if accepted",
            "Log decision",
        ],
    },
    "linkedin_engagement": {
        "title": "LinkedIn Engagement Plan",
        "default_steps": [
            "Review engagement notification",
            "Determine if response needed",
            "Draft response if applicable",
            "Execute engagement action",
            "Log action",
        ],
    },
    "default": {
        "title": "Action Plan",
        "default_steps": [
            "Analyze item details",
            "Determine required actions",
            "Check handbook for guidelines",
            "Execute actions",
            "Update Dashboard",
            "Move to Done",
        ],
    },
}


def _parse_frontmatter(content: str) -> dict:
    """Parse YAML-like frontmatter from a Markdown file.

    Simple parser that extracts key-value pairs from --- delimited frontmatter.
    Does not require PyYAML dependency.
    """
    metadata = {}
    if not content.startswith("---"):
        return metadata

    lines = content.split("\n")
    in_frontmatter = False
    for line in lines:
        if line.strip() == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if in_frontmatter and ":" in line:
            if line[0] in (" ", "\t"):
                continue  # Skip indented/nested keys
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip('"')
            if key:
                metadata[key] = value

    return metadata


class Planner:
    """Creates structured Plan.md files for items in /Needs_Action.

    Reads each pending item, determines the action type and priority,
    cross-references with Company_Handbook and Business_Goals, and
    generates a Plan.md with step-by-step actions.
    """

    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path)
        self.needs_action = self.vault_path / "Needs_Action"
        self.plans_dir = self.vault_path / "Plans"
        self.done_dir = self.vault_path / "Done"
        self.logs_dir = self.vault_path / "Logs"
        self.handbook_path = self.vault_path / "Company_Handbook.md"
        self.goals_path = self.vault_path / "Business_Goals.md"

        # Ensure directories
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def _read_handbook_rules(self) -> str:
        """Read the Company Handbook for processing rules."""
        if self.handbook_path.exists():
            return self.handbook_path.read_text(encoding="utf-8")
        return ""

    def _read_business_goals(self) -> str:
        """Read the Business Goals for context."""
        if self.goals_path.exists():
            return self.goals_path.read_text(encoding="utf-8")
        return ""

    def _get_template(self, action_type: str) -> dict:
        """Get the plan template for a given action type."""
        # Normalize type names
        normalized = action_type.lower().replace("-", "_").replace(" ", "_")
        if normalized.startswith("linkedin_"):
            # Map linkedin subtypes
            subtype = normalized.replace("linkedin_", "")
            template_key = f"linkedin_{subtype}"
            if template_key in PLAN_TEMPLATES:
                return PLAN_TEMPLATES[template_key]
        return PLAN_TEMPLATES.get(normalized, PLAN_TEMPLATES["default"])

    def _determine_approval_needed(self, action_type: str, priority: str) -> bool:
        """Determine if this plan requires human approval."""
        from approval import ALWAYS_REQUIRE_APPROVAL
        return action_type in ALWAYS_REQUIRE_APPROVAL or priority == "high"

    def create_plan(self, action_file: Path) -> Path | None:
        """Create a Plan.md for a single action item.

        Args:
            action_file: Path to an .md file in /Needs_Action

        Returns:
            Path to the created Plan.md, or None if plan already exists.
        """
        content = action_file.read_text(encoding="utf-8")
        metadata = _parse_frontmatter(content)

        action_type = metadata.get("type", "default")
        priority = metadata.get("priority", "medium")
        status = metadata.get("status", "pending")
        source = metadata.get("source", "unknown")

        # Skip already-planned items
        if status == "planned":
            return None

        template = self._get_template(action_type)
        needs_approval = self._determine_approval_needed(action_type, priority)
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%d_%H%M%S")

        plan_name = f"PLAN_{timestamp}_{action_file.stem}.md"
        plan_path = self.plans_dir / plan_name

        # Build step list with checkboxes
        steps = template["default_steps"].copy()
        if needs_approval and "Submit for approval" not in " ".join(steps):
            steps.insert(-1, "Submit for approval (REQUIRES HUMAN APPROVAL)")

        steps_md = "\n".join(f"- [ ] {step}" for step in steps)

        # Build contextual notes
        context_notes = []
        handbook = self._read_handbook_rules()
        if handbook and priority == "high":
            context_notes.append(
                "- **High priority**: Per handbook, respond within 1 hour"
            )
        if needs_approval:
            context_notes.append(
                "- **Approval required**: This plan includes actions that need human sign-off"
            )

        context_md = "\n".join(context_notes) if context_notes else "_No special notes._"

        # Extract key details from original item for the plan
        subject = metadata.get("subject", metadata.get("original_name", action_file.stem))
        sender = metadata.get("from", metadata.get("source", "system"))

        plan_content = f"""---
type: plan
plan_id: "{plan_name}"
source_file: "{action_file.name}"
action_type: {action_type}
priority: {priority}
created: {now.isoformat()}
status: pending
requires_approval: {str(needs_approval).lower()}
---

# {template['title']}

**Source**: {action_file.name}
**Type**: {action_type}
**Priority**: {priority}
**From**: {sender}
**Subject**: {subject}
**Created**: {now.strftime('%Y-%m-%d %H:%M UTC')}

## Objective
Process the {action_type} item: {subject}

## Steps
{steps_md}

## Context Notes
{context_md}

## Approval Status
{"**PENDING APPROVAL** - Move approval request from /Pending_Approval to /Approved to proceed." if needs_approval else "Auto-approved - no human approval needed for this action type."}

---
*Generated by AI Employee Planner v0.2*
"""
        plan_path.write_text(plan_content, encoding="utf-8")

        self._log("plan_created", {
            "plan_file": plan_name,
            "source_file": action_file.name,
            "source_action_type": action_type,
            "priority": priority,
            "requires_approval": needs_approval,
        })

        logger.info(f"Plan created: {plan_name} (approval: {needs_approval})")
        return plan_path

    def create_plans_for_pending(self) -> list[Path]:
        """Create plans for all pending items in /Needs_Action.

        Returns list of created plan file paths.
        """
        created_plans = []

        if not self.needs_action.exists():
            return created_plans

        pending = sorted(
            f for f in self.needs_action.iterdir()
            if f.is_file() and f.suffix == ".md" and f.name != ".gitkeep"
        )

        for item in pending:
            try:
                plan = self.create_plan(item)
                if plan:
                    created_plans.append(plan)
            except Exception as e:
                logger.error(f"Error creating plan for {item.name}: {e}")
                self._log("plan_error", {
                    "source_file": item.name,
                    "error": str(e),
                })

        return created_plans

    def get_pending_plans(self) -> list[Path]:
        """Return list of plan files with status 'pending'."""
        try:
            return sorted(
                f for f in self.plans_dir.iterdir()
                if f.is_file() and f.suffix == ".md" and f.name != ".gitkeep"
            )
        except OSError:
            return []

    def _log(self, action_type: str, details: dict) -> None:
        """Write a structured log entry. Thread-safe."""
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        log_file = self.logs_dir / f"{today}.json"

        entry = {
            "timestamp": now.isoformat(),
            "action_type": action_type,
            "actor": "planner",
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
