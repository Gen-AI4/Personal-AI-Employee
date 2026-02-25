"""
Facebook Watcher - Monitors Facebook for notifications and messages.

Uses Playwright browser automation (via the Playwright MCP server) to
check Facebook for new notifications, messages, and friend requests.
Creates action files in /Needs_Action for items requiring attention.

Gold tier requirement: Facebook integration with posting and summary generation.
"""

import os
import logging
from pathlib import Path

from .social_base_watcher import SocialBaseWatcher

logger = logging.getLogger(__name__)

# Keywords for notification classification
MESSAGE_KEYWORDS = ["messaged", "sent you a message", "sent you a video", "replied to your", "mentioned you in"]
FRIEND_KEYWORDS = ["friend request", "accepted your friend", "wants to be friends"]
ENGAGEMENT_KEYWORDS = ["liked", "reacted", "commented", "shared your", "tagged you"]
BUSINESS_KEYWORDS = ["page", "ad ", "boost", "insight", "follower"]


class FacebookWatcher(SocialBaseWatcher):
    """Watches Facebook for new notifications and messages via Playwright MCP.

    Detects and classifies:
    - Direct messages (high priority)
    - Friend requests (medium priority)
    - Page/business notifications (medium priority)
    - Post engagement: likes, comments, shares (low priority)

    Configuration via environment variables:
        FACEBOOK_SESSION_PATH: Path to Playwright persistent browser session
        MCP_CLIENT_PATH: Path to mcp-client.py script
        MCP_SERVER_URL: URL of the Playwright MCP server
        ENABLE_FACEBOOK: Set to 'true' to enable this watcher
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
            session_path=session_path or os.getenv("FACEBOOK_SESSION_PATH", ""),
            mcp_client_path=mcp_client_path,
            mcp_url=mcp_url,
            check_interval=check_interval,
        )

    @property
    def platform_name(self) -> str:
        return "facebook"

    @property
    def notifications_url(self) -> str:
        return "https://www.facebook.com/notifications"

    def _parse_notifications(self, snapshot_text: str) -> list[dict]:
        """Parse Facebook notifications from an accessibility snapshot.

        Extracts notification entries from the snapshot text by looking for
        common Facebook notification patterns.
        """
        notifications = []
        lines = snapshot_text.split("\n")

        for i, line in enumerate(lines):
            line_lower = line.lower().strip()
            if not line_lower:
                continue

            # Check for notification-like content
            is_notification = False
            ntype = "general"
            for kw in MESSAGE_KEYWORDS:
                if kw in line_lower:
                    is_notification = True
                    ntype = "message"
                    break
            if not is_notification:
                for kw in FRIEND_KEYWORDS:
                    if kw in line_lower:
                        is_notification = True
                        ntype = "friend_request"
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
                    "id": f"fb_{i}_{hash(line_lower) % 100000}",
                    "type": ntype,
                    "content": line.strip()[:500],
                    "sender": _extract_sender(line.strip()),
                })

        return notifications

    def _classify_notification(self, notification: dict) -> dict:
        """Classify Facebook notification priority and action type."""
        ntype = notification.get("type", "general")

        priority_map = {
            "message": "high",
            "friend_request": "medium",
            "business": "medium",
            "engagement": "low",
            "general": "low",
        }

        action_type_map = {
            "message": "facebook_message",
            "friend_request": "facebook_friend_request",
            "business": "facebook_business",
            "engagement": "facebook_engagement",
            "general": "facebook_notification",
        }

        return {
            "priority": priority_map.get(ntype, "low"),
            "action_type": action_type_map.get(ntype, "facebook_notification"),
        }


def _extract_sender(text: str) -> str:
    """Extract the sender/actor name from a notification line.

    Facebook notifications typically start with the person's name.
    """
    # Take the first few words before common action verbs
    action_verbs = [
        "messaged", "sent", "replied", "mentioned", "liked", "reacted",
        "commented", "shared", "tagged", "accepted", "wants", "posted",
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
