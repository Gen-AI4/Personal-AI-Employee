"""
LinkedIn Watcher - Monitors LinkedIn for notifications and messages.

Uses Playwright browser automation (via the Playwright MCP server) to
check LinkedIn for new notifications, messages, and connection requests.
Creates action files in /Needs_Action for items requiring attention.

This is a Silver tier watcher (requirement: two or more watchers).
Requires the Playwright MCP server to be running.
"""

import os
import json
import logging
import subprocess
from pathlib import Path
from datetime import datetime, timezone

from .base_watcher import BaseWatcher

logger = logging.getLogger(__name__)

# Path to the MCP client script (relative to project root)
DEFAULT_MCP_CLIENT = ".claude/skills/browsing-with-playwright/scripts/mcp-client.py"
DEFAULT_MCP_URL = "http://localhost:8808"


class LinkedInWatcher(BaseWatcher):
    """Watches LinkedIn for new notifications and messages via Playwright.

    Uses browser automation to log into LinkedIn and check for:
    - New messages/InMail
    - Connection requests
    - Post engagement (comments, likes)
    - Mentions and tags

    Each detected item creates a structured .md file in /Needs_Action.

    Configuration via environment variables:
        LINKEDIN_SESSION_PATH: Path to Playwright persistent browser session
        MCP_CLIENT_PATH: Path to mcp-client.py script
        MCP_SERVER_URL: URL of the Playwright MCP server
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
        self.session_path = session_path or os.getenv("LINKEDIN_SESSION_PATH", "")
        self.mcp_client = mcp_client_path or os.getenv(
            "MCP_CLIENT_PATH", DEFAULT_MCP_CLIENT
        )
        self.mcp_url = mcp_url or os.getenv("MCP_SERVER_URL", DEFAULT_MCP_URL)
        self._processed_ids: set[str] = set()
        self._mcp_available = None

    def _call_mcp(self, tool: str, params: dict) -> dict | None:
        """Call a Playwright MCP tool and return the parsed result.

        Args:
            tool: MCP tool name (e.g., 'browser_navigate')
            params: Tool parameters as a dict

        Returns:
            Parsed JSON result dict, or None on failure.
        """
        try:
            result = subprocess.run(
                [
                    "python3" if os.name != "nt" else "python",
                    self.mcp_client,
                    "call",
                    "-u", self.mcp_url,
                    "-t", tool,
                    "-p", json.dumps(params),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError:
                    return {"raw": result.stdout}
            else:
                self.logger.error(f"MCP call failed: {result.stderr}")
                return None
        except subprocess.TimeoutExpired:
            self.logger.error(f"MCP call timed out: {tool}")
            return None
        except FileNotFoundError:
            self.logger.error(f"MCP client not found: {self.mcp_client}")
            return None

    def _check_mcp_available(self) -> bool:
        """Check if the Playwright MCP server is running and accessible."""
        if self._mcp_available is not None:
            return self._mcp_available

        result = self._call_mcp("browser_navigate", {"url": "about:blank"})
        self._mcp_available = result is not None
        if not self._mcp_available:
            self.logger.warning(
                "Playwright MCP server not available. "
                "Start it with: bash .claude/skills/browsing-with-playwright/scripts/start-server.sh"
            )
        return self._mcp_available

    def _navigate_to_linkedin(self) -> bool:
        """Navigate the browser to LinkedIn notifications page."""
        result = self._call_mcp(
            "browser_navigate",
            {"url": "https://www.linkedin.com/notifications/"},
        )
        return result is not None

    def _get_page_snapshot(self) -> str | None:
        """Get an accessibility snapshot of the current page."""
        result = self._call_mcp("browser_snapshot", {})
        if result and "raw" in result:
            return result["raw"]
        if result:
            return json.dumps(result)
        return None

    def _parse_notifications(self, snapshot: str) -> list[dict]:
        """Parse LinkedIn notifications from a page snapshot.

        Extracts notification items with their type, content, and timestamp.
        Returns a list of notification dicts.
        """
        notifications = []
        if not snapshot:
            return notifications

        # Parse the snapshot text to identify notification items
        lines = snapshot.split("\n")
        current_notification = None

        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue

            # Look for notification patterns in the accessibility tree
            # LinkedIn notifications typically contain action verbs
            # More specific keywords first to avoid premature matching
            notification_keywords = [
                "connection request",
                "messaged you",
                "sent you",
                "commented on",
                "liked your",
                "mentioned you",
                "endorsed you",
                "viewed your profile",
                "invited you",
                "posted",
                "shared",
            ]

            for keyword in notification_keywords:
                if keyword in line_stripped.lower():
                    notif_id = f"li_{hash(line_stripped) & 0xFFFFFFFF:08x}"
                    if notif_id not in self._processed_ids:
                        notif_type = self._classify_notification(keyword)
                        notifications.append(
                            {
                                "id": notif_id,
                                "type": notif_type,
                                "content": line_stripped[:300],
                                "keyword": keyword,
                            }
                        )
                    break

        return notifications

    def _classify_notification(self, keyword: str) -> str:
        """Classify a notification type based on its keyword."""
        message_keywords = ["messaged you", "sent you", "invited you"]
        connection_keywords = ["connection request"]
        engagement_keywords = [
            "commented on", "liked your", "mentioned you",
            "endorsed you", "shared",
        ]

        if any(kw in keyword for kw in message_keywords):
            return "message"
        if any(kw in keyword for kw in connection_keywords):
            return "connection"
        if any(kw in keyword for kw in engagement_keywords):
            return "engagement"
        return "notification"

    def _get_notification_priority(self, notif_type: str) -> str:
        """Assign priority based on notification type."""
        priorities = {
            "message": "high",
            "connection": "medium",
            "engagement": "low",
            "notification": "low",
        }
        return priorities.get(notif_type, "low")

    def check_for_updates(self) -> list:
        """Check LinkedIn for new notifications via browser automation.

        Navigates to LinkedIn notifications page, takes a snapshot,
        and parses for new items.
        """
        if not self._check_mcp_available():
            return []

        if not self._navigate_to_linkedin():
            self.logger.error("Failed to navigate to LinkedIn")
            return []

        snapshot = self._get_page_snapshot()
        if not snapshot:
            self.logger.warning("Failed to get LinkedIn page snapshot")
            return []

        notifications = self._parse_notifications(snapshot)
        self.logger.info(f"Found {len(notifications)} new LinkedIn notifications")
        return notifications

    def create_action_file(self, item: dict) -> Path:
        """Create a .md action file for a LinkedIn notification.

        Args:
            item: Dict with id, type, content, keyword from check_for_updates.

        Returns:
            Path to the created .md file in /Needs_Action.
        """
        notif_id = item["id"]
        notif_type = item["type"]
        content = item["content"]
        priority = self._get_notification_priority(notif_type)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"LINKEDIN_{timestamp}_{notif_type}_{notif_id[:8]}.md"
        filepath = self.needs_action / filename

        # Escape for YAML safety
        escaped_content = content.replace('"', '\\"').replace("\n", "\\n")

        file_content = f"""---
type: linkedin_{notif_type}
notification_id: "{notif_id}"
content_preview: "{escaped_content[:200]}"
received: {datetime.now(timezone.utc).isoformat()}
priority: {priority}
status: pending
source: linkedin
---

## LinkedIn {notif_type.title()}: {content[:100]}

**Type**: {notif_type}
**Priority**: {priority}
**Detected**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

### Content
{content}

### Suggested Actions
- [ ] Review notification
- [ ] Respond if needed
- [ ] Archive after processing
"""
        filepath.write_text(file_content, encoding="utf-8")
        self._processed_ids.add(notif_id)

        self.log_action(
            "linkedin_notification_detected",
            {
                "notification_id": notif_id,
                "type": notif_type,
                "priority": priority,
                "action_file": filename,
                "result": "success",
            },
        )

        return filepath

    def run(self) -> None:
        """Start the LinkedIn watcher with MCP availability check."""
        if not self._check_mcp_available():
            self.logger.error(
                "LinkedIn watcher cannot start - Playwright MCP not available."
            )
            return
        self.logger.info("Starting LinkedInWatcher")
        super().run()
