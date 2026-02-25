"""
Instagram Watcher - Monitors Instagram for notifications and messages.

Uses Playwright browser automation (via the Playwright MCP server) to
check Instagram for new notifications, direct messages, and engagement.
Creates action files in /Needs_Action for items requiring attention.

Gold tier requirement: Instagram integration with posting and summary generation.
"""

import os
import logging
from pathlib import Path

from .social_base_watcher import SocialBaseWatcher

logger = logging.getLogger(__name__)

# Keywords for notification classification
DM_KEYWORDS = ["sent you a message", "replied to your story", "mentioned you"]
FOLLOW_KEYWORDS = ["started following", "follow request", "wants to follow"]
ENGAGEMENT_KEYWORDS = ["liked your", "commented on", "shared your", "tagged you in"]
BUSINESS_KEYWORDS = ["insights", "promotion", "boost", "ad ", "reach"]


class InstagramWatcher(SocialBaseWatcher):
    """Watches Instagram for new notifications and messages via Playwright MCP.

    Detects and classifies:
    - Direct messages (high priority)
    - Follow requests (medium priority)
    - Business/promotion notifications (medium priority)
    - Post engagement: likes, comments (low priority)

    Configuration via environment variables:
        INSTAGRAM_SESSION_PATH: Path to Playwright persistent browser session
        MCP_CLIENT_PATH: Path to mcp-client.py script
        MCP_SERVER_URL: URL of the Playwright MCP server
        ENABLE_INSTAGRAM: Set to 'true' to enable this watcher
    """

    def __init__(
        self,
        vault_path: str,
        session_path: str = None,
        mcp_client_path: str = None,
        mcp_url: str = None,
        check_interval: int = 300,
    ):
        super().__init__(
            vault_path=vault_path,
            session_path=session_path or os.getenv("INSTAGRAM_SESSION_PATH", ""),
            mcp_client_path=mcp_client_path,
            mcp_url=mcp_url,
            check_interval=check_interval,
        )

    @property
    def platform_name(self) -> str:
        return "instagram"

    @property
    def notifications_url(self) -> str:
        return "https://www.instagram.com/accounts/activity/"

    def _parse_notifications(self, snapshot_text: str) -> list[dict]:
        """Parse Instagram notifications from an accessibility snapshot."""
        notifications = []
        lines = snapshot_text.split("\n")

        for i, line in enumerate(lines):
            line_lower = line.lower().strip()
            if not line_lower:
                continue

            is_notification = False
            ntype = "general"

            for kw in DM_KEYWORDS:
                if kw in line_lower:
                    is_notification = True
                    ntype = "direct_message"
                    break
            if not is_notification:
                for kw in FOLLOW_KEYWORDS:
                    if kw in line_lower:
                        is_notification = True
                        ntype = "follow_request"
                        break
            if not is_notification:
                for kw in ENGAGEMENT_KEYWORDS:
                    if kw in line_lower:
                        is_notification = True
                        ntype = "engagement"
                        break
            if not is_notification:
                for kw in BUSINESS_KEYWORDS:
                    if kw in line_lower:
                        is_notification = True
                        ntype = "business"
                        break

            if is_notification:
                notifications.append({
                    "id": f"ig_{i}_{hash(line_lower) % 100000}",
                    "type": ntype,
                    "content": line.strip()[:500],
                    "sender": _extract_sender(line.strip()),
                })

        return notifications

    def _classify_notification(self, notification: dict) -> dict:
        """Classify Instagram notification priority and action type."""
        ntype = notification.get("type", "general")

        priority_map = {
            "direct_message": "high",
            "follow_request": "medium",
            "business": "medium",
            "engagement": "low",
            "general": "low",
        }

        action_type_map = {
            "direct_message": "instagram_message",
            "follow_request": "instagram_follow_request",
            "business": "instagram_business",
            "engagement": "instagram_engagement",
            "general": "instagram_notification",
        }

        return {
            "priority": priority_map.get(ntype, "low"),
            "action_type": action_type_map.get(ntype, "instagram_notification"),
        }


def _extract_sender(text: str) -> str:
    """Extract the sender/actor name from a notification line."""
    action_verbs = [
        "sent", "replied", "mentioned", "liked", "commented", "shared",
        "tagged", "started", "wants", "followed",
    ]
    words = text.split()
    sender_words = []
    for word in words:
        if word.lower().rstrip(".,!?:") in action_verbs:
            break
        sender_words.append(word)
        if len(sender_words) >= 4:
            break
    return " ".join(sender_words) if sender_words else "Unknown"
