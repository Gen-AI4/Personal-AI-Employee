"""
Twitter (X) Watcher - Monitors Twitter/X for notifications and messages.

Uses Playwright browser automation (via the Playwright MCP server) to
check Twitter for new notifications, direct messages, and engagement.
Creates action files in /Needs_Action for items requiring attention.

Gold tier requirement: Twitter (X) integration with posting and summary generation.
"""

import os
import logging
from pathlib import Path

from .social_base_watcher import SocialBaseWatcher

logger = logging.getLogger(__name__)

# Keywords for notification classification
DM_KEYWORDS = ["sent you a direct message", "new message from", "dm from"]
MENTION_KEYWORDS = ["mentioned you", "replied to you", "quoted your", "tagged you in"]
ENGAGEMENT_KEYWORDS = ["liked your", "retweeted", "reposted", "bookmarked"]
FOLLOW_KEYWORDS = ["followed you", "follow request"]
BUSINESS_KEYWORDS = ["analytics", "impressions", "promote", "ad ", "campaign"]


class TwitterWatcher(SocialBaseWatcher):
    """Watches Twitter/X for new notifications and messages via Playwright MCP.

    Detects and classifies:
    - Direct messages (high priority)
    - Mentions and replies (high priority)
    - Follow notifications (medium priority)
    - Post engagement: likes, retweets (low priority)
    - Business/analytics notifications (medium priority)

    Configuration via environment variables:
        TWITTER_SESSION_PATH: Path to Playwright persistent browser session
        MCP_CLIENT_PATH: Path to mcp-client.py script
        MCP_SERVER_URL: URL of the Playwright MCP server
        ENABLE_TWITTER: Set to 'true' to enable this watcher
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
            session_path=session_path or os.getenv("TWITTER_SESSION_PATH", ""),
            mcp_client_path=mcp_client_path,
            mcp_url=mcp_url,
            check_interval=check_interval,
        )

    @property
    def platform_name(self) -> str:
        return "twitter"

    @property
    def notifications_url(self) -> str:
        return "https://x.com/notifications"

    def _parse_notifications(self, snapshot_text: str) -> list[dict]:
        """Parse Twitter notifications from an accessibility snapshot."""
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
                        ntype = "follow"
                        break
            if not is_notification:
                for kw in ENGAGEMENT_KEYWORDS:
                    if kw in line_lower:
                        is_notification = True
                        ntype = "engagement"
                        break
            if not is_notification:
                for kw in MENTION_KEYWORDS:
                    if kw in line_lower:
                        is_notification = True
                        ntype = "mention"
                        break
            if not is_notification:
                for kw in BUSINESS_KEYWORDS:
                    if kw in line_lower:
                        is_notification = True
                        ntype = "business"
                        break

            if is_notification:
                notifications.append({
                    "id": f"tw_{i}_{hash(line_lower) % 100000}",
                    "type": ntype,
                    "content": line.strip()[:500],
                    "sender": _extract_sender(line.strip()),
                })

        return notifications

    def _classify_notification(self, notification: dict) -> dict:
        """Classify Twitter notification priority and action type."""
        ntype = notification.get("type", "general")

        priority_map = {
            "direct_message": "high",
            "mention": "high",
            "follow": "medium",
            "business": "medium",
            "engagement": "low",
            "general": "low",
        }

        action_type_map = {
            "direct_message": "twitter_message",
            "mention": "twitter_mention",
            "follow": "twitter_follow",
            "business": "twitter_business",
            "engagement": "twitter_engagement",
            "general": "twitter_notification",
        }

        return {
            "priority": priority_map.get(ntype, "low"),
            "action_type": action_type_map.get(ntype, "twitter_notification"),
        }


def _extract_sender(text: str) -> str:
    """Extract the sender/actor name from a notification line.

    Twitter notifications often include @handles.
    """
    # Look for @handle pattern first
    words = text.split()
    for word in words:
        if word.startswith("@") and len(word) > 1:
            return word

    # Fallback: take words before action verbs
    action_verbs = [
        "sent", "replied", "mentioned", "liked", "retweeted", "reposted",
        "quoted", "followed", "bookmarked",
    ]
    sender_words = []
    for word in words:
        if word.lower().rstrip(".,!?:") in action_verbs:
            break
        sender_words.append(word)
        if len(sender_words) >= 4:
            break
    return " ".join(sender_words) if sender_words else "Unknown"
