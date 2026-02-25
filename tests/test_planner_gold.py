"""Gold tier planner tests - verifies social media and Odoo templates."""

import pytest
from pathlib import Path
from unittest.mock import patch

from planner import Planner, PLAN_TEMPLATES, _parse_frontmatter


@pytest.fixture
def vault(tmp_path):
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    (vault_path / "Needs_Action").mkdir()
    (vault_path / "Plans").mkdir()
    (vault_path / "Logs").mkdir()
    (vault_path / "Done").mkdir()
    return vault_path


@pytest.fixture
def planner(vault):
    return Planner(vault_path=str(vault))


# --- Gold Tier Templates ---


class TestGoldPlanTemplates:
    """Test that Gold tier plan templates exist and have correct structure."""

    def test_facebook_message_template_exists(self):
        assert "facebook_message" in PLAN_TEMPLATES

    def test_facebook_friend_request_template_exists(self):
        assert "facebook_friend_request" in PLAN_TEMPLATES

    def test_facebook_engagement_template_exists(self):
        assert "facebook_engagement" in PLAN_TEMPLATES

    def test_facebook_business_template_exists(self):
        assert "facebook_business" in PLAN_TEMPLATES

    def test_instagram_message_template_exists(self):
        assert "instagram_message" in PLAN_TEMPLATES

    def test_instagram_follow_request_template_exists(self):
        assert "instagram_follow_request" in PLAN_TEMPLATES

    def test_instagram_engagement_template_exists(self):
        assert "instagram_engagement" in PLAN_TEMPLATES

    def test_instagram_business_template_exists(self):
        assert "instagram_business" in PLAN_TEMPLATES

    def test_twitter_message_template_exists(self):
        assert "twitter_message" in PLAN_TEMPLATES

    def test_twitter_mention_template_exists(self):
        assert "twitter_mention" in PLAN_TEMPLATES

    def test_twitter_engagement_template_exists(self):
        assert "twitter_engagement" in PLAN_TEMPLATES

    def test_twitter_business_template_exists(self):
        assert "twitter_business" in PLAN_TEMPLATES

    def test_odoo_invoice_template_exists(self):
        assert "odoo_invoice" in PLAN_TEMPLATES

    def test_odoo_payment_template_exists(self):
        assert "odoo_payment" in PLAN_TEMPLATES

    def test_all_templates_have_title(self):
        for key, template in PLAN_TEMPLATES.items():
            assert "title" in template, f"{key} missing title"

    def test_all_templates_have_steps(self):
        for key, template in PLAN_TEMPLATES.items():
            assert "default_steps" in template, f"{key} missing default_steps"
            assert len(template["default_steps"]) > 0, f"{key} has empty steps"


# --- Template Selection for Gold Tier ---


class TestGoldTemplateSelection:
    """Test that the planner selects correct Gold tier templates."""

    def test_gets_facebook_message_template(self, planner):
        template = planner._get_template("facebook_message")
        assert template == PLAN_TEMPLATES["facebook_message"]

    def test_gets_facebook_engagement_template(self, planner):
        template = planner._get_template("facebook_engagement")
        assert template == PLAN_TEMPLATES["facebook_engagement"]

    def test_gets_instagram_message_template(self, planner):
        template = planner._get_template("instagram_message")
        assert template == PLAN_TEMPLATES["instagram_message"]

    def test_gets_instagram_follow_request_template(self, planner):
        template = planner._get_template("instagram_follow_request")
        assert template == PLAN_TEMPLATES["instagram_follow_request"]

    def test_gets_twitter_mention_template(self, planner):
        template = planner._get_template("twitter_mention")
        assert template == PLAN_TEMPLATES["twitter_mention"]

    def test_gets_twitter_engagement_template(self, planner):
        template = planner._get_template("twitter_engagement")
        assert template == PLAN_TEMPLATES["twitter_engagement"]

    def test_gets_odoo_invoice_template(self, planner):
        template = planner._get_template("odoo_invoice")
        assert template == PLAN_TEMPLATES["odoo_invoice"]

    def test_gets_odoo_payment_template(self, planner):
        template = planner._get_template("odoo_payment")
        assert template == PLAN_TEMPLATES["odoo_payment"]

    def test_defaults_for_unknown_social(self, planner):
        template = planner._get_template("facebook_unknown_subtype")
        assert template == PLAN_TEMPLATES["default"]

    def test_case_insensitive_selection(self, planner):
        template = planner._get_template("FACEBOOK_MESSAGE")
        assert template == PLAN_TEMPLATES["facebook_message"]


# --- Plan Creation for Social Media Items ---


class TestGoldPlanCreation:
    """Test plan creation for Gold tier action types."""

    def _make_action_file(self, vault, action_type, priority="medium", extra=""):
        filename = f"{action_type.upper()}_test_001.md"
        filepath = vault / "Needs_Action" / filename
        content = f"""---
type: {action_type}
source: {action_type.split('_')[0]}
priority: {priority}
status: pending
---

## Test notification

Content here.
{extra}
"""
        filepath.write_text(content, encoding="utf-8")
        return filepath

    def test_creates_plan_for_facebook_message(self, planner, vault):
        action_file = self._make_action_file(vault, "facebook_message", "high")
        plan = planner.create_plan(action_file)
        assert plan is not None
        assert plan.exists()

    def test_facebook_message_plan_uses_correct_template(self, planner, vault):
        action_file = self._make_action_file(vault, "facebook_message", "high")
        plan = planner.create_plan(action_file)
        content = plan.read_text(encoding="utf-8")
        assert "Facebook Message Response Plan" in content

    def test_creates_plan_for_instagram_engagement(self, planner, vault):
        action_file = self._make_action_file(vault, "instagram_engagement", "low")
        plan = planner.create_plan(action_file)
        assert plan is not None

    def test_creates_plan_for_twitter_mention(self, planner, vault):
        action_file = self._make_action_file(vault, "twitter_mention", "high")
        plan = planner.create_plan(action_file)
        assert plan is not None
        content = plan.read_text(encoding="utf-8")
        assert "Twitter Mention Response Plan" in content

    def test_creates_plan_for_odoo_invoice(self, planner, vault):
        action_file = self._make_action_file(vault, "odoo_invoice", "high")
        plan = planner.create_plan(action_file)
        assert plan is not None
        content = plan.read_text(encoding="utf-8")
        assert "Invoice Processing Plan" in content

    def test_odoo_payment_requires_approval(self, planner, vault):
        action_file = self._make_action_file(vault, "odoo_payment", "high")
        plan = planner.create_plan(action_file)
        content = plan.read_text(encoding="utf-8")
        # Payment should require approval
        assert "requires_approval: true" in content or "REQUIRES HUMAN APPROVAL" in content

    def test_facebook_high_priority_includes_handbook_note(self, planner, vault):
        # Create handbook
        (vault / "Company_Handbook.md").write_text(
            "# Handbook\nHigh priority: respond fast", encoding="utf-8"
        )
        action_file = self._make_action_file(vault, "facebook_message", "high")
        plan = planner.create_plan(action_file)
        content = plan.read_text(encoding="utf-8")
        assert "High priority" in content

    def test_batch_creates_plans_for_social_items(self, planner, vault):
        for atype in ["facebook_message", "instagram_engagement", "twitter_follow"]:
            self._make_action_file(vault, atype)
        plans = planner.create_plans_for_pending()
        assert len(plans) == 3


# --- Approval Determination for Gold Tier ---


class TestGoldApprovalDetermination:
    """Test approval requirements for Gold tier action types."""

    def test_facebook_post_requires_approval(self, planner):
        with patch("approval.ALWAYS_REQUIRE_APPROVAL", {
            "facebook_post", "instagram_post", "twitter_post",
            "odoo_payment", "odoo_invoice_post",
        }):
            assert planner._determine_approval_needed("facebook_post", "medium") is True

    def test_twitter_post_requires_approval(self, planner):
        with patch("approval.ALWAYS_REQUIRE_APPROVAL", {
            "twitter_post", "facebook_post", "instagram_post",
        }):
            assert planner._determine_approval_needed("twitter_post", "medium") is True

    def test_social_summary_no_approval(self, planner):
        # Read-only summaries don't require approval
        assert planner._determine_approval_needed("social_summary", "low") is False

    def test_accounting_summary_no_approval(self, planner):
        assert planner._determine_approval_needed("accounting_summary", "low") is False
