"""
Odoo Community Accounting Integration via JSON-RPC.

Connects to a self-hosted Odoo Community instance (19+) to manage
invoices, payments, journal entries, and generate financial summaries.
Supports the mcp-odoo-adv MCP server pattern for Claude integration.

Gold tier requirement: Odoo Community accounting system integration.
"""

import os
import json
import logging
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError

from log_utils import log_file_lock as _log_lock

logger = logging.getLogger(__name__)

# Odoo configuration from environment
ODOO_URL = os.getenv("ODOO_URL", "http://localhost:8069")
ODOO_DB = os.getenv("ODOO_DB", "odoo")
ODOO_USER = os.getenv("ODOO_USER", "admin")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD", "")
ODOO_MCP_URL = os.getenv("ODOO_MCP_URL", "")
DEV_MODE = os.getenv("DEV_MODE", "true").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

# Subscription patterns for audit analysis
SUBSCRIPTION_PATTERNS = {
    "netflix.com": "Netflix",
    "spotify.com": "Spotify",
    "adobe.com": "Adobe Creative Cloud",
    "notion.so": "Notion",
    "slack.com": "Slack",
    "github.com": "GitHub",
    "openai.com": "OpenAI",
    "anthropic.com": "Anthropic",
    "aws.amazon.com": "AWS",
    "cloud.google.com": "Google Cloud",
    "azure.microsoft.com": "Microsoft Azure",
    "heroku.com": "Heroku",
    "digitalocean.com": "DigitalOcean",
    "zoom.us": "Zoom",
}


class OdooConnector:
    """Connects to Odoo Community via JSON-RPC for accounting operations.

    Supports both direct JSON-RPC calls to Odoo and indirect calls
    through an MCP server (mcp-odoo-adv).

    In DEV_MODE/DRY_RUN, operations are logged but not executed.
    """

    def __init__(
        self,
        vault_path: str,
        url: str = ODOO_URL,
        db: str = ODOO_DB,
        user: str = ODOO_USER,
        password: str = ODOO_PASSWORD,
        mcp_url: str = ODOO_MCP_URL,
    ):
        self.vault_path = Path(vault_path)
        self.accounting_dir = self.vault_path / "Accounting"
        self.logs_dir = self.vault_path / "Logs"
        self.url = url
        self.db = db
        self.user = user
        self.password = password
        self.mcp_url = mcp_url
        self._uid = None
        self._available: bool | None = None
        self.dev_mode = os.getenv("DEV_MODE", "true").lower() == "true"
        self.dry_run = os.getenv("DRY_RUN", "true").lower() == "true"

        # Ensure directories
        self.accounting_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def _json_rpc(self, endpoint: str, method: str, params: dict) -> dict | None:
        """Make a JSON-RPC call to Odoo.

        Args:
            endpoint: URL path (e.g., '/jsonrpc')
            method: JSON-RPC method (e.g., 'call')
            params: Parameters dict

        Returns:
            Result dict or None on failure.
        """
        if self.dev_mode or self.dry_run:
            logger.info(f"[DRY RUN] Odoo RPC: {endpoint} {method} {params}")
            return None

        payload = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1,
        }).encode("utf-8")

        try:
            req = Request(
                f"{self.url}{endpoint}",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if "error" in result:
                    logger.error(f"Odoo RPC error: {result['error']}")
                    return None
                return result.get("result")
        except (URLError, TimeoutError, json.JSONDecodeError) as e:
            logger.warning(f"Odoo RPC call failed: {e}")
            return None

    def authenticate(self) -> int | None:
        """Authenticate with Odoo and return the user ID.

        Returns:
            User ID (int) on success, None on failure.
        """
        result = self._json_rpc(
            "/jsonrpc",
            "call",
            {
                "service": "common",
                "method": "authenticate",
                "args": [self.db, self.user, self.password, {}],
            },
        )
        if result:
            self._uid = result
            logger.info(f"Authenticated with Odoo as uid={result}")
        return result

    def is_available(self) -> bool:
        """Check if Odoo is reachable."""
        if self._available is not None:
            return self._available

        if self.dev_mode:
            self._available = False
            return False

        try:
            result = self._json_rpc(
                "/jsonrpc",
                "call",
                {
                    "service": "common",
                    "method": "version",
                    "args": [],
                },
            )
            self._available = result is not None
        except Exception:
            self._available = False
        return self._available

    def get_invoices(self, state: str = "posted", limit: int = 50) -> list[dict]:
        """Fetch invoices from Odoo.

        Args:
            state: Invoice state filter ('draft', 'posted', 'cancel')
            limit: Maximum number of invoices to return

        Returns:
            List of invoice dicts with keys: id, name, partner, amount, date, state
        """
        if self.dev_mode or not self._uid:
            return self._get_mock_invoices() if self.dev_mode else []

        result = self._json_rpc(
            "/jsonrpc",
            "call",
            {
                "service": "object",
                "method": "execute_kw",
                "args": [
                    self.db, self._uid, self.password,
                    "account.move", "search_read",
                    [[["move_type", "=", "out_invoice"], ["state", "=", state]]],
                    {
                        "fields": ["name", "partner_id", "amount_total",
                                   "invoice_date", "state", "payment_state"],
                        "limit": limit,
                        "order": "invoice_date desc",
                    },
                ],
            },
        )
        return result or []

    def get_payments(self, limit: int = 50) -> list[dict]:
        """Fetch recent payments from Odoo.

        Returns:
            List of payment dicts with keys: id, name, partner, amount, date, state
        """
        if self.dev_mode or not self._uid:
            return self._get_mock_payments() if self.dev_mode else []

        result = self._json_rpc(
            "/jsonrpc",
            "call",
            {
                "service": "object",
                "method": "execute_kw",
                "args": [
                    self.db, self._uid, self.password,
                    "account.payment", "search_read",
                    [[]],
                    {
                        "fields": ["name", "partner_id", "amount",
                                   "date", "state", "payment_type"],
                        "limit": limit,
                        "order": "date desc",
                    },
                ],
            },
        )
        return result or []

    def get_journal_entries(self, limit: int = 50) -> list[dict]:
        """Fetch recent journal entries from Odoo.

        Returns:
            List of journal entry dicts.
        """
        if self.dev_mode or not self._uid:
            return []

        result = self._json_rpc(
            "/jsonrpc",
            "call",
            {
                "service": "object",
                "method": "execute_kw",
                "args": [
                    self.db, self._uid, self.password,
                    "account.move", "search_read",
                    [[["move_type", "=", "entry"]]],
                    {
                        "fields": ["name", "date", "amount_total", "state", "ref"],
                        "limit": limit,
                        "order": "date desc",
                    },
                ],
            },
        )
        return result or []

    def analyze_transaction(self, transaction: dict) -> dict | None:
        """Analyze a transaction for subscription patterns.

        Args:
            transaction: Dict with 'description' and 'amount' keys.

        Returns:
            Dict with subscription info, or None if not a subscription.
        """
        description = transaction.get("description", "").lower()
        for pattern, name in SUBSCRIPTION_PATTERNS.items():
            if pattern in description:
                return {
                    "type": "subscription",
                    "name": name,
                    "amount": transaction.get("amount", 0),
                    "date": transaction.get("date", ""),
                }
        return None

    def generate_financial_summary(self) -> dict:
        """Generate a financial summary for the current period.

        Returns:
            Summary dict with revenue, expenses, subscriptions, etc.
        """
        invoices = self.get_invoices()
        payments = self.get_payments()

        total_invoiced = sum(
            inv.get("amount_total", 0) for inv in invoices
        )
        total_paid = sum(
            pay.get("amount", 0) for pay in payments
            if pay.get("payment_type") == "inbound"
        )
        total_outgoing = sum(
            pay.get("amount", 0) for pay in payments
            if pay.get("payment_type") == "outbound"
        )

        # Identify subscriptions from payments
        subscriptions = []
        for pay in payments:
            result = self.analyze_transaction({
                "description": str(pay.get("name", "")),
                "amount": pay.get("amount", 0),
                "date": str(pay.get("date", "")),
            })
            if result:
                subscriptions.append(result)

        return {
            "total_invoiced": total_invoiced,
            "total_received": total_paid,
            "total_outgoing": total_outgoing,
            "net_revenue": total_paid - total_outgoing,
            "invoice_count": len(invoices),
            "payment_count": len(payments),
            "subscriptions": subscriptions,
            "generated": datetime.now(timezone.utc).isoformat(),
        }

    def write_accounting_summary(self) -> Path:
        """Write the current financial summary to vault/Accounting/.

        Returns:
            Path to the generated summary file.
        """
        now = datetime.now(timezone.utc)
        summary = self.generate_financial_summary()

        filename = f"Summary_{now.strftime('%Y_%m')}.md"
        filepath = self.accounting_dir / filename

        subs_lines = ""
        if summary["subscriptions"]:
            for sub in summary["subscriptions"]:
                subs_lines += f"| {sub['name']} | ${sub['amount']:.2f} | {sub['date']} |\n"
        else:
            subs_lines = "| _No subscriptions detected_ | - | - |\n"

        content = f"""---
type: accounting_summary
period: {now.strftime('%Y-%m')}
generated: {now.isoformat()}
---

# Accounting Summary - {now.strftime('%B %Y')}

## Financial Overview
| Metric | Amount |
|--------|--------|
| Total Invoiced | ${summary['total_invoiced']:.2f} |
| Total Received | ${summary['total_received']:.2f} |
| Total Outgoing | ${summary['total_outgoing']:.2f} |
| Net Revenue | ${summary['net_revenue']:.2f} |

## Activity
- **Invoices**: {summary['invoice_count']}
- **Payments**: {summary['payment_count']}

## Subscriptions Detected
| Service | Amount | Date |
|---------|--------|------|
{subs_lines}
---
*Generated by AI Employee Accounting v0.3*
"""
        filepath.write_text(content, encoding="utf-8")

        self._log("accounting_summary_generated", {
            "file": filename,
            "total_invoiced": summary["total_invoiced"],
            "total_received": summary["total_received"],
            "net_revenue": summary["net_revenue"],
        })

        logger.info(f"Accounting summary written: {filename}")
        return filepath

    def _get_mock_invoices(self) -> list[dict]:
        """Return mock invoice data for DEV_MODE testing."""
        return [
            {
                "id": 1, "name": "INV/2026/0001",
                "partner_id": [1, "Client A"],
                "amount_total": 2500.00,
                "invoice_date": "2026-02-15",
                "state": "posted",
                "payment_state": "paid",
            },
            {
                "id": 2, "name": "INV/2026/0002",
                "partner_id": [2, "Client B"],
                "amount_total": 1800.00,
                "invoice_date": "2026-02-18",
                "state": "posted",
                "payment_state": "not_paid",
            },
        ]

    def _get_mock_payments(self) -> list[dict]:
        """Return mock payment data for DEV_MODE testing."""
        return [
            {
                "id": 1, "name": "PAY/2026/0001",
                "partner_id": [1, "Client A"],
                "amount": 2500.00,
                "date": "2026-02-16",
                "state": "posted",
                "payment_type": "inbound",
            },
            {
                "id": 2, "name": "netflix.com subscription",
                "partner_id": [3, "Netflix"],
                "amount": 15.99,
                "date": "2026-02-01",
                "state": "posted",
                "payment_type": "outbound",
            },
        ]

    def _log(self, action_type: str, details: dict) -> None:
        """Write a structured log entry. Thread-safe."""
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        log_file = self.logs_dir / f"{today}.json"

        entry = {
            "timestamp": now.isoformat(),
            "action_type": action_type,
            "actor": "odoo_connector",
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
