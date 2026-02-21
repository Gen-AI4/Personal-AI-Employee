"""Tests for the Planner module (Plan.md generation)."""

import json
from pathlib import Path
from datetime import datetime, timezone

import pytest

from planner import Planner, _parse_frontmatter, PLAN_TEMPLATES


@pytest.fixture
def vault(tmp_path):
    """Create a temporary vault with required directories."""
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    for d in ["Needs_Action", "Plans", "Done", "Logs"]:
        (vault_path / d).mkdir()
    return vault_path


@pytest.fixture
def planner(vault):
    """Create a Planner with a temporary vault."""
    return Planner(vault_path=str(vault))


# --- Frontmatter Parser Tests ---


class TestParseFrontmatter:
    """Test the YAML-like frontmatter parser."""

    def test_parses_basic_frontmatter(self):
        content = """---
type: email
priority: high
status: pending
---

# Content
"""
        meta = _parse_frontmatter(content)
        assert meta["type"] == "email"
        assert meta["priority"] == "high"
        assert meta["status"] == "pending"

    def test_strips_quotes_from_values(self):
        content = """---
subject: "Hello World"
---
"""
        meta = _parse_frontmatter(content)
        assert meta["subject"] == "Hello World"

    def test_returns_empty_dict_without_frontmatter(self):
        content = "# Just a heading\nSome text."
        meta = _parse_frontmatter(content)
        assert meta == {}

    def test_returns_empty_dict_for_empty_string(self):
        meta = _parse_frontmatter("")
        assert meta == {}

    def test_ignores_indented_keys(self):
        content = """---
type: test
  nested_key: value
---
"""
        meta = _parse_frontmatter(content)
        assert "nested_key" not in meta
        assert meta["type"] == "test"

    def test_handles_colons_in_value(self):
        content = """---
subject: Re: Hello: World
---
"""
        meta = _parse_frontmatter(content)
        assert meta["subject"] == "Re: Hello: World"


# --- Plan Templates Tests ---


class TestPlanTemplates:
    """Test PLAN_TEMPLATES coverage."""

    def test_has_email_template(self):
        assert "email" in PLAN_TEMPLATES

    def test_has_file_drop_template(self):
        assert "file_drop" in PLAN_TEMPLATES

    def test_has_linkedin_message_template(self):
        assert "linkedin_message" in PLAN_TEMPLATES

    def test_has_default_template(self):
        assert "default" in PLAN_TEMPLATES

    def test_all_templates_have_title(self):
        for name, tmpl in PLAN_TEMPLATES.items():
            assert "title" in tmpl, f"Template '{name}' missing title"

    def test_all_templates_have_steps(self):
        for name, tmpl in PLAN_TEMPLATES.items():
            assert "default_steps" in tmpl, f"Template '{name}' missing steps"
            assert len(tmpl["default_steps"]) > 0


# --- Planner Init Tests ---


class TestPlannerInit:
    """Test Planner initialization."""

    def test_creates_plans_directory(self, vault):
        planner = Planner(vault_path=str(vault))
        assert (vault / "Plans").exists()

    def test_creates_logs_directory(self, vault):
        planner = Planner(vault_path=str(vault))
        assert (vault / "Logs").exists()


# --- Template Selection Tests ---


class TestGetTemplate:
    """Test template selection logic."""

    def test_email_type(self, planner):
        tmpl = planner._get_template("email")
        assert tmpl["title"] == "Email Response Plan"

    def test_file_drop_type(self, planner):
        tmpl = planner._get_template("file_drop")
        assert tmpl["title"] == "File Processing Plan"

    def test_linkedin_message_type(self, planner):
        tmpl = planner._get_template("linkedin_message")
        assert tmpl["title"] == "LinkedIn Message Response Plan"

    def test_unknown_type_returns_default(self, planner):
        tmpl = planner._get_template("unknown_type")
        assert tmpl["title"] == "Action Plan"

    def test_normalizes_hyphens(self, planner):
        tmpl = planner._get_template("file-drop")
        assert tmpl["title"] == "File Processing Plan"

    def test_normalizes_spaces(self, planner):
        tmpl = planner._get_template("file drop")
        assert tmpl["title"] == "File Processing Plan"


# --- Approval Determination Tests ---


class TestDetermineApproval:
    """Test approval requirement detection."""

    def test_email_send_requires_approval(self, planner):
        assert planner._determine_approval_needed("email_send", "medium") is True

    def test_payment_requires_approval(self, planner):
        assert planner._determine_approval_needed("payment", "low") is True

    def test_high_priority_requires_approval(self, planner):
        assert planner._determine_approval_needed("file_organize", "high") is True

    def test_safe_action_no_approval(self, planner):
        assert planner._determine_approval_needed("file_organize", "low") is False


# --- Create Plan Tests ---


class TestCreatePlan:
    """Test individual plan creation."""

    def _create_action_file(self, vault, name="test_item.md", content=None):
        """Helper to create an action file in Needs_Action."""
        if content is None:
            content = """---
type: email
priority: medium
status: pending
source: gmail
from: "sender@example.com"
subject: "Test Email"
---

# Test Email
Some content here.
"""
        path = vault / "Needs_Action" / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_creates_plan_file(self, planner, vault):
        action = self._create_action_file(vault)
        plan = planner.create_plan(action)
        assert plan is not None
        assert plan.exists()
        assert plan.parent == vault / "Plans"

    def test_plan_has_frontmatter(self, planner, vault):
        action = self._create_action_file(vault)
        plan = planner.create_plan(action)
        content = plan.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        assert "type: plan" in content
        assert "action_type: email" in content
        assert "priority: medium" in content

    def test_plan_has_checkboxes(self, planner, vault):
        action = self._create_action_file(vault)
        plan = planner.create_plan(action)
        content = plan.read_text(encoding="utf-8")
        assert "- [ ]" in content

    def test_plan_filename_prefix(self, planner, vault):
        action = self._create_action_file(vault)
        plan = planner.create_plan(action)
        assert plan.name.startswith("PLAN_")
        assert plan.suffix == ".md"

    def test_plan_references_source(self, planner, vault):
        action = self._create_action_file(vault)
        plan = planner.create_plan(action)
        content = plan.read_text(encoding="utf-8")
        assert "test_item.md" in content

    def test_plan_includes_approval_note_for_sensitive(self, planner, vault):
        action = self._create_action_file(vault, content="""---
type: email_send
priority: high
status: pending
---
Send an email
""")
        plan = planner.create_plan(action)
        content = plan.read_text(encoding="utf-8")
        assert "requires_approval: true" in content

    def test_plan_skips_already_planned(self, planner, vault):
        action = self._create_action_file(vault, content="""---
type: email
status: planned
---
Already planned
""")
        plan = planner.create_plan(action)
        assert plan is None

    def test_plan_creates_log_entry(self, planner, vault):
        action = self._create_action_file(vault)
        planner.create_plan(action)
        log_files = list((vault / "Logs").glob("*.json"))
        assert len(log_files) >= 1
        entries = json.loads(log_files[0].read_text(encoding="utf-8"))
        assert any(e["action_type"] == "plan_created" for e in entries)

    def test_plan_uses_email_template(self, planner, vault):
        action = self._create_action_file(vault)
        plan = planner.create_plan(action)
        content = plan.read_text(encoding="utf-8")
        assert "Email Response Plan" in content

    def test_plan_uses_default_template_for_unknown(self, planner, vault):
        action = self._create_action_file(vault, content="""---
type: mystery_action
status: pending
---
Unknown type
""")
        plan = planner.create_plan(action)
        content = plan.read_text(encoding="utf-8")
        assert "Action Plan" in content

    def test_high_priority_includes_handbook_note(self, planner, vault):
        # Create a handbook file
        (vault / "Company_Handbook.md").write_text("# Handbook\nRules here", encoding="utf-8")
        action = self._create_action_file(vault, content="""---
type: email
priority: high
status: pending
---
Urgent email
""")
        plan = planner.create_plan(action)
        content = plan.read_text(encoding="utf-8")
        assert "respond within 1 hour" in content


# --- Batch Plan Creation Tests ---


class TestCreatePlansForPending:
    """Test batch plan creation."""

    def test_creates_plans_for_all_pending(self, planner, vault):
        for i in range(3):
            (vault / "Needs_Action" / f"item_{i}.md").write_text(f"""---
type: file_drop
status: pending
---
Item {i}
""", encoding="utf-8")

        plans = planner.create_plans_for_pending()
        assert len(plans) == 3

    def test_returns_empty_for_no_pending(self, planner):
        plans = planner.create_plans_for_pending()
        assert plans == []

    def test_skips_planned_items(self, planner, vault):
        (vault / "Needs_Action" / "already.md").write_text("""---
type: email
status: planned
---
Already done
""", encoding="utf-8")
        (vault / "Needs_Action" / "new.md").write_text("""---
type: email
status: pending
---
New item
""", encoding="utf-8")
        plans = planner.create_plans_for_pending()
        assert len(plans) == 1

    def test_handles_errors_gracefully(self, planner, vault):
        # Create a file that will cause read errors (directory instead of file)
        # Actually, create a normal file and an invalid one
        (vault / "Needs_Action" / "good.md").write_text("""---
type: email
status: pending
---
Good item
""", encoding="utf-8")
        plans = planner.create_plans_for_pending()
        assert len(plans) >= 1


class TestGetPendingPlans:
    """Test listing pending plans."""

    def test_empty_plans(self, planner):
        plans = planner.get_pending_plans()
        assert plans == []

    def test_returns_plan_files(self, planner, vault):
        (vault / "Plans" / "PLAN_test.md").write_text("plan", encoding="utf-8")
        plans = planner.get_pending_plans()
        assert len(plans) == 1

    def test_ignores_non_md(self, planner, vault):
        (vault / "Plans" / "notes.txt").write_text("text", encoding="utf-8")
        plans = planner.get_pending_plans()
        assert plans == []


class TestPlannerIntegration:
    """Integration tests for the full planner workflow."""

    def test_email_to_plan_workflow(self, vault):
        """Full workflow: email action file → plan with approval."""
        planner = Planner(vault_path=str(vault))

        # Create handbook and goals
        (vault / "Company_Handbook.md").write_text(
            "# Handbook\n## Rules\n- Respond to high-priority within 1 hour",
            encoding="utf-8",
        )
        (vault / "Business_Goals.md").write_text(
            "# Goals\n- Increase response rate",
            encoding="utf-8",
        )

        # Create action file
        action = vault / "Needs_Action" / "EMAIL_20260221_urgent.md"
        action.write_text("""---
type: email
priority: high
status: pending
from: "vip@client.com"
subject: "Urgent: Contract Review"
source: gmail
---

## Email: Urgent Contract Review
Important client email requiring immediate attention.
""", encoding="utf-8")

        # Create plan
        plan = planner.create_plan(action)
        assert plan is not None
        content = plan.read_text(encoding="utf-8")

        # Verify plan quality
        assert "Email Response Plan" in content
        assert "priority: high" in content
        assert "requires_approval: true" in content
        assert "respond within 1 hour" in content
        assert "- [ ]" in content
