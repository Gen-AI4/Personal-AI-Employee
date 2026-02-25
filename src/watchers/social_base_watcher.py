"""
Social Media Base Watcher - Shared foundation for Facebook, Instagram, and Twitter watchers.

Provides common Playwright MCP integration patterns, notification parsing,
and action file creation for social media platforms.

Gold tier requirement: Facebook, Instagram, and Twitter integration.
"""

import os
import json
import logging
import subprocess
from pathlib import Path
from datetime import datetime, timezone

from .base_watcher import BaseWatcher

logger = logging.getLogger(__name__)

# Shared MCP defaults
DEFAULT_MCP_CLIENT = ".claude/skills/browsing-with-playwright/scripts/mcp-client.py"
DEFAULT_MCP_URL = "http://localhost:8808"


class SocialBaseWatcher(BaseWatcher):
    """Abstract base for social media platform watchers using Playwright MCP.

    Subclasses must implement:
        - platform_name: str property returning the platform name
        - notifications_url: str property returning the notifications page URL
        - _parse_notifications(snapshot_text): Parse platform-specific notifications
        - _classify_notification(notification): Classify priority and type
    """

    def __init__(
        self,
        vault_path: str,
        session_path: str = None,
        mcp_client_path: str = None,
        mcp_url: str = None,
        check_interval: int = 300,
    ):
        super().__init__(vault_path, check_interval)
        self.session_path = session_path or os.getenv(
            f"{self.platform_name.upper()}_SESSION_PATH", ""
        )
        self.mcp_client = mcp_client_path or os.getenv(
            "MCP_CLIENT_PATH", DEFAULT_MCP_CLIENT
        )
        self.mcp_url = mcp_url or os.getenv("MCP_SERVER_URL", DEFAULT_MCP_URL)
        self._processed_ids: set[str] = set()
        self._mcp_available: bool | None = None

    @property
    def platform_name(self) -> str:
        """Return the lowercase platform name (e.g., 'facebook')."""
        raise NotImplementedError

    @property
    def notifications_url(self) -> str:
        """Return the URL of the platform's notifications page."""
        raise NotImplementedError

    def _call_mcp(self, tool: str, params: dict) -> dict | None:
        """Call a Playwright MCP tool via the mcp-client script.

        Returns parsed JSON result or None on failure.
        """
        try:
            params_json = json.dumps(params)
            result = subprocess.run(
                [
                    "python3", self.mcp_client,
                    "call",
                    "-u", self.mcp_url,
                    "-t", tool,
                    "-p", params_json,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                return json.loads(result.stdout)
            return None
        except Exception as e:
            self.logger.warning(f"MCP call failed ({tool}): {e}")
            return None

    def _check_mcp_available(self) -> bool:
        """Check if the Playwright MCP server is reachable."""
        if self._mcp_available is not None:
            return self._mcp_available
        try:
            result = subprocess.run(
                ["python3", self.mcp_client, "list", "-u", self.mcp_url],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self._mcp_available = result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            self._mcp_available = False
        return self._mcp_available

    def _parse_notifications(self, snapshot_text: str) -> list[dict]:
        """Parse platform-specific notifications from an accessibility snapshot.

        Must be implemented by subclasses.
        Returns list of dicts with keys: id, type, content, sender (optional).
        """
        raise NotImplementedError

    def _classify_notification(self, notification: dict) -> dict:
        """Classify a notification's priority and action type.

        Must be implemented by subclasses.
        Returns dict with: priority, action_type, type (notification subtype).
        """
        raise NotImplementedError

    def check_for_updates(self) -> list:
        """Check the social media platform for new notifications via Playwright MCP."""
        if not self._check_mcp_available():
            self.logger.debug(f"{self.platform_name} MCP not available, skipping")
            return []

        # Navigate to notifications
        nav_result = self._call_mcp(
            "browser_navigate", {"url": self.notifications_url}
        )
        if not nav_result:
            return []

        # Take accessibility snapshot
        snapshot = self._call_mcp("browser_snapshot", {})
        if not snapshot:
            return []

        snapshot_text = str(snapshot)
        notifications = self._parse_notifications(snapshot_text)

        # Filter already-processed
        new_items = []
        for notif in notifications:
            nid = notif.get("id", "")
            if nid and nid not in self._processed_ids:
                self._processed_ids.add(nid)
                classified = self._classify_notification(notif)
                notif.update(classified)
                new_items.append(notif)

        return new_items

    def create_action_file(self, item: dict) -> Path:
        """Create a structured .md action file in /Needs_Action."""
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        platform = self.platform_name.upper()
        ntype = item.get("type", "notification")
        nid = item.get("id", timestamp)

        safe_id = "".join(c for c in str(nid) if c.isalnum() or c in "-_")[:50]
        filename = f"{platform}_{timestamp}_{ntype}_{safe_id}.md"
        filepath = self.needs_action / filename

        content = item.get("content", "No content available")
        sender = item.get("sender", "Unknown")
        priority = item.get("priority", "low")
        action_type = item.get("action_type", f"{self.platform_name}_notification")

        escaped_content = str(content).replace('"', '\\"')
        escaped_sender = str(sender).replace('"', '\\"')

        md_content = f"""---
type: {action_type}
source: {self.platform_name}
priority: {priority}
status: pending
notification_type: {ntype}
sender: "{escaped_sender}"
detected: {now.isoformat()}
notification_id: "{safe_id}"
---

## {platform} Notification: {ntype.replace('_', ' ').title()}

**From**: {sender}
**Detected**: {now.strftime('%Y-%m-%d %H:%M UTC')}
**Priority**: {priority}

### Content
{content}

### Suggested Actions
- [ ] Review notification content
- [ ] Determine appropriate response
- [ ] Execute response (if needed)
- [ ] Log action and move to Done
"""
        filepath.write_text(md_content, encoding="utf-8")
        self.log_action(
            f"{self.platform_name}_notification_detected",
            {
                "file": filename,
                "notification_type": ntype,
                "priority": priority,
                "result": "success",
            },
        )
        return filepath
