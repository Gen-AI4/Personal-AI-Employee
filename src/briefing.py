"""
CEO Briefing Generator - Weekly Business and Accounting Audit.

Generates the "Monday Morning CEO Briefing" that summarizes:
- Revenue and financial metrics from Odoo/accounting data
- Completed tasks from /Done for the week
- Bottlenecks (tasks that took longer than expected)
- Proactive suggestions (subscription optimization, deadline alerts)

Gold tier requirement: Weekly Business and Accounting Audit with CEO Briefing.
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

from log_utils import log_file_lock as _log_lock

logger = logging.getLogger(__name__)


class BriefingGenerator:
    """Generates weekly CEO briefings from vault data and accounting info.

    Reads Business_Goals.md, analyzes the week's /Done items,
    pulls financial data from accounting summaries, and produces
    a structured briefing in /Briefings.
    """

    def __init__(self, vault_path: str, odoo_connector=None):
        self.vault_path = Path(vault_path)
        self.briefings_dir = self.vault_path / "Briefings"
        self.done_dir = self.vault_path / "Done"
        self.logs_dir = self.vault_path / "Logs"
        self.accounting_dir = self.vault_path / "Accounting"
        self.goals_path = self.vault_path / "Business_Goals.md"
        self.odoo = odoo_connector

        # Ensure directories
        self.briefings_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def _read_business_goals(self) -> str:
        """Read the Business Goals markdown file."""
        if self.goals_path.exists():
            return self.goals_path.read_text(encoding="utf-8")
        return ""

    def _get_weekly_done_items(self, reference_date: datetime = None) -> list[dict]:
        """Get items completed in the past 7 days.

        Returns list of dicts with: name, completed_date, type
        """
        if reference_date is None:
            reference_date = datetime.now(timezone.utc)

        week_ago = reference_date - timedelta(days=7)
        items = []

        if not self.done_dir.exists():
            return items

        for f in sorted(self.done_dir.iterdir()):
            if not f.is_file() or not f.suffix == ".md":
                continue
            # Done files are prefixed with YYYYMMDD_HHMMSS_
            name = f.stem
            try:
                date_str = name[:15]  # YYYYMMDD_HHMMSS
                completed = datetime.strptime(date_str, "%Y%m%d_%H%M%S").replace(
                    tzinfo=timezone.utc
                )
                if completed >= week_ago:
                    # Try to determine type from the filename
                    remainder = name[16:] if len(name) > 16 else name
                    item_type = "general"
                    if remainder.startswith("EMAIL_"):
                        item_type = "email"
                    elif remainder.startswith("FILE_"):
                        item_type = "file"
                    elif remainder.startswith("APPROVAL_"):
                        item_type = "approval"
                    elif remainder.startswith("LINKEDIN_"):
                        item_type = "linkedin"
                    elif remainder.startswith("FACEBOOK_"):
                        item_type = "facebook"
                    elif remainder.startswith("INSTAGRAM_"):
                        item_type = "instagram"
                    elif remainder.startswith("TWITTER_"):
                        item_type = "twitter"

                    items.append({
                        "name": remainder,
                        "completed_date": completed.isoformat(),
                        "type": item_type,
                    })
            except (ValueError, IndexError):
                continue

        return items

    def _get_weekly_log_summary(self, reference_date: datetime = None) -> dict:
        """Summarize log entries for the past 7 days.

        Returns dict with action counts, error counts, and bottleneck info.
        """
        if reference_date is None:
            reference_date = datetime.now(timezone.utc)

        summary = {
            "total_actions": 0,
            "errors": 0,
            "action_types": {},
            "bottlenecks": [],
        }

        for i in range(7):
            day = reference_date - timedelta(days=i)
            log_file = self.logs_dir / f"{day.strftime('%Y-%m-%d')}.json"
            if not log_file.exists():
                continue

            try:
                entries = json.loads(log_file.read_text(encoding="utf-8"))
                for entry in entries:
                    summary["total_actions"] += 1
                    action = entry.get("action_type", "unknown")
                    summary["action_types"][action] = (
                        summary["action_types"].get(action, 0) + 1
                    )
                    if entry.get("result") == "failure" or "error" in action:
                        summary["errors"] += 1
            except (json.JSONDecodeError, OSError):
                continue

        return summary

    def _get_financial_summary(self) -> dict:
        """Get financial summary from Odoo connector or accounting files.

        Returns dict with revenue, expenses, subscriptions data.
        """
        # Try Odoo connector first
        if self.odoo:
            try:
                return self.odoo.generate_financial_summary()
            except Exception as e:
                logger.warning(f"Odoo financial summary failed: {e}")

        # Fallback: read the latest accounting summary from vault
        if self.accounting_dir.exists():
            summaries = sorted(
                f for f in self.accounting_dir.iterdir()
                if f.is_file() and f.name.startswith("Summary_")
            )
            if summaries:
                # Parse the most recent summary for numbers
                content = summaries[-1].read_text(encoding="utf-8")
                return self._parse_accounting_summary(content)

        return {
            "total_invoiced": 0,
            "total_received": 0,
            "total_outgoing": 0,
            "net_revenue": 0,
            "invoice_count": 0,
            "payment_count": 0,
            "subscriptions": [],
        }

    def _parse_accounting_summary(self, content: str) -> dict:
        """Parse financial figures from an accounting summary markdown file."""
        result = {
            "total_invoiced": 0,
            "total_received": 0,
            "total_outgoing": 0,
            "net_revenue": 0,
            "invoice_count": 0,
            "payment_count": 0,
            "subscriptions": [],
        }

        for line in content.split("\n"):
            line = line.strip()
            if "Total Invoiced" in line and "$" in line:
                result["total_invoiced"] = _extract_dollar(line)
            elif "Total Received" in line and "$" in line:
                result["total_received"] = _extract_dollar(line)
            elif "Total Outgoing" in line and "$" in line:
                result["total_outgoing"] = _extract_dollar(line)
            elif "Net Revenue" in line and "$" in line:
                result["net_revenue"] = _extract_dollar(line)

        return result

    def generate_briefing(self, reference_date: datetime = None) -> Path:
        """Generate a CEO briefing for the week ending on reference_date.

        Args:
            reference_date: End date for the report period. Defaults to now.

        Returns:
            Path to the generated briefing file.
        """
        if reference_date is None:
            reference_date = datetime.now(timezone.utc)

        period_start = reference_date - timedelta(days=7)

        # Gather data
        done_items = self._get_weekly_done_items(reference_date)
        log_summary = self._get_weekly_log_summary(reference_date)
        financial = self._get_financial_summary()
        goals = self._read_business_goals()

        # Build completed tasks section
        if done_items:
            completed_lines = "\n".join(
                f"- [x] {item['name']} ({item['type']})"
                for item in done_items
            )
        else:
            completed_lines = "- _No items completed this week_"

        # Build revenue section
        revenue_trend = "On track"
        if financial["net_revenue"] < 0:
            revenue_trend = "Below target - expenses exceed revenue"
        elif financial["total_received"] == 0:
            revenue_trend = "No revenue data available"

        # Build bottleneck section
        bottleneck_lines = ""
        error_count = log_summary["errors"]
        if error_count > 0:
            bottleneck_lines = f"""| System Errors | 0 | {error_count} | {error_count} errors this week |
"""
        else:
            bottleneck_lines = "| _No bottlenecks detected_ | - | - | - |\n"

        # Build subscription section
        sub_suggestions = ""
        if financial.get("subscriptions"):
            for sub in financial["subscriptions"]:
                sub_suggestions += (
                    f"- **{sub['name']}**: ${sub['amount']:.2f}/month. "
                    "Review usage and consider cancellation if unused.\n"
                )
        else:
            sub_suggestions = "- _No subscription optimization opportunities detected_\n"

        # Upcoming deadlines from goals
        deadline_lines = ""
        if "Due" in goals or "due" in goals:
            deadline_lines = "- Review Business_Goals.md for upcoming project deadlines\n"
        else:
            deadline_lines = "- _No upcoming deadlines found in Business_Goals.md_\n"

        # Executive summary
        exec_summary = _generate_executive_summary(
            done_items, error_count, financial
        )

        # Build briefing
        filename = f"{reference_date.strftime('%Y-%m-%d')}_Monday_Briefing.md"
        filepath = self.briefings_dir / filename

        content = f"""---
type: ceo_briefing
generated: {reference_date.isoformat()}
period: {period_start.strftime('%Y-%m-%d')} to {reference_date.strftime('%Y-%m-%d')}
---

# Monday Morning CEO Briefing

## Executive Summary
{exec_summary}

## Revenue
- **This Week**: ${financial['total_received']:.2f}
- **Total Invoiced**: ${financial['total_invoiced']:.2f}
- **Total Outgoing**: ${financial['total_outgoing']:.2f}
- **Net Revenue**: ${financial['net_revenue']:.2f}
- **Trend**: {revenue_trend}

## Completed Tasks ({len(done_items)} items)
{completed_lines}

## Activity Summary
- **Total Actions**: {log_summary['total_actions']}
- **Errors**: {log_summary['errors']}
- **Action Types**: {len(log_summary['action_types'])} different actions

## Bottlenecks
| Task | Expected | Actual | Notes |
|------|----------|--------|-------|
{bottleneck_lines}
## Proactive Suggestions

### Cost Optimization
{sub_suggestions}
### Upcoming Deadlines
{deadline_lines}
---
*Generated by AI Employee v0.3 - Gold Tier*
"""
        filepath.write_text(content, encoding="utf-8")

        self._log("briefing_generated", {
            "file": filename,
            "period_start": period_start.isoformat(),
            "period_end": reference_date.isoformat(),
            "done_count": len(done_items),
            "error_count": error_count,
            "net_revenue": financial["net_revenue"],
        })

        logger.info(f"CEO Briefing generated: {filename}")
        return filepath

    def _log(self, action_type: str, details: dict) -> None:
        """Write a structured log entry. Thread-safe."""
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        log_file = self.logs_dir / f"{today}.json"

        entry = {
            "timestamp": now.isoformat(),
            "action_type": action_type,
            "actor": "briefing_generator",
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


def _extract_dollar(line: str) -> float:
    """Extract a dollar amount from a line of text."""
    try:
        # Find $X.XX pattern
        idx = line.index("$")
        amount_str = ""
        for ch in line[idx + 1:]:
            if ch.isdigit() or ch == "." or ch == ",":
                amount_str += ch
            else:
                break
        return float(amount_str.replace(",", ""))
    except (ValueError, IndexError):
        return 0.0


def _generate_executive_summary(
    done_items: list[dict], error_count: int, financial: dict
) -> str:
    """Generate a one-line executive summary based on the week's data."""
    done_count = len(done_items)

    parts = []
    if done_count > 0:
        parts.append(f"{done_count} tasks completed")
    else:
        parts.append("No tasks completed")

    if financial["net_revenue"] > 0:
        parts.append(f"net revenue of ${financial['net_revenue']:.2f}")
    elif financial["net_revenue"] < 0:
        parts.append(
            f"net loss of ${abs(financial['net_revenue']):.2f} - review expenses"
        )

    if error_count > 0:
        parts.append(f"{error_count} errors requiring attention")

    if not parts:
        return "Quiet week with minimal activity."

    return ". ".join(parts) + "."
