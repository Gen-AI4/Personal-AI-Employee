"""
Gmail Watcher - Monitors Gmail for unread important emails.

Polls the Gmail API for unread messages matching a configurable query,
creates action files in /Needs_Action for each new message detected.
Supports dry-run/dev-mode and deduplication via processed ID tracking.

Requirements:
    - Google Gmail API credentials (OAuth2 or service account)
    - google-auth, google-auth-oauthlib, google-api-python-client packages

This is a Silver tier watcher (requirement: two or more watchers).
"""

import os
import logging
from pathlib import Path
from datetime import datetime, timezone

from .base_watcher import BaseWatcher

logger = logging.getLogger(__name__)

# Default Gmail query for important unread messages
DEFAULT_GMAIL_QUERY = "is:unread is:important"


class GmailWatcher(BaseWatcher):
    """Watches Gmail for unread important emails and creates vault action files.

    Uses the Gmail API to poll for new messages. Each detected email
    is written as a structured .md file in /Needs_Action with YAML
    frontmatter containing sender, subject, priority, and content.

    Configuration via environment variables:
        GMAIL_CREDENTIALS: Path to OAuth2 credentials JSON file
        GMAIL_TOKEN: Path to saved token file (auto-created on first auth)
        GMAIL_QUERY: Gmail search query (default: "is:unread is:important")
    """

    # Gmail API scopes needed for read access
    SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

    def __init__(
        self,
        vault_path: str,
        credentials_path: str = None,
        token_path: str = None,
        query: str = None,
        check_interval: int = 120,
    ):
        super().__init__(vault_path, check_interval)
        self.credentials_path = credentials_path or os.getenv(
            "GMAIL_CREDENTIALS", "credentials.json"
        )
        self.token_path = token_path or os.getenv("GMAIL_TOKEN", "token.json")
        self.query = query or os.getenv("GMAIL_QUERY", DEFAULT_GMAIL_QUERY)
        self._processed_ids: set[str] = set()
        self._service = None

    def _authenticate(self):
        """Authenticate with Gmail API and build the service client.

        Uses stored token if available, otherwise initiates OAuth2 flow.
        Returns None if authentication libraries are not installed.
        """
        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
        except ImportError:
            self.logger.warning(
                "Gmail API libraries not installed. "
                "Install with: pip install google-auth google-auth-oauthlib google-api-python-client"
            )
            return None

        creds = None
        token_path = Path(self.token_path)

        # Load existing token
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), self.SCOPES)

        # Refresh or create new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                creds_path = Path(self.credentials_path)
                if not creds_path.exists():
                    self.logger.error(
                        f"Gmail credentials file not found: {self.credentials_path}"
                    )
                    return None
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(creds_path), self.SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save token for future use
            token_path.write_text(creds.to_json(), encoding="utf-8")

        self._service = build("gmail", "v1", credentials=creds)
        self.logger.info("Gmail API authenticated successfully")
        return self._service

    def _get_service(self):
        """Get or create the Gmail API service."""
        if self._service is None:
            self._authenticate()
        return self._service

    def _extract_headers(self, headers_list: list) -> dict:
        """Extract a header dict from Gmail's header list format."""
        return {h["name"]: h["value"] for h in headers_list}

    def _classify_email_priority(self, headers: dict, label_ids: list) -> str:
        """Classify email priority based on Gmail labels and content."""
        if "IMPORTANT" in label_ids:
            return "high"
        subject = headers.get("Subject", "").lower()
        high_keywords = ["urgent", "asap", "critical", "important", "action required"]
        if any(kw in subject for kw in high_keywords):
            return "high"
        medium_keywords = ["invoice", "payment", "review", "request", "meeting"]
        if any(kw in subject for kw in medium_keywords):
            return "medium"
        return "low"

    def check_for_updates(self) -> list:
        """Poll Gmail for unread messages matching the configured query.

        Returns a list of message dicts with id, headers, snippet, and labels.
        Skips messages that have already been processed.
        """
        service = self._get_service()
        if not service:
            return []

        try:
            results = (
                service.users()
                .messages()
                .list(userId="me", q=self.query, maxResults=20)
                .execute()
            )
            messages = results.get("messages", [])
        except Exception as e:
            self.logger.error(f"Error fetching Gmail messages: {e}")
            return []

        new_messages = []
        for msg_ref in messages:
            msg_id = msg_ref["id"]
            if msg_id in self._processed_ids:
                continue

            try:
                msg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=msg_id, format="metadata")
                    .execute()
                )
                headers = self._extract_headers(
                    msg.get("payload", {}).get("headers", [])
                )
                new_messages.append(
                    {
                        "id": msg_id,
                        "headers": headers,
                        "snippet": msg.get("snippet", ""),
                        "label_ids": msg.get("labelIds", []),
                    }
                )
            except Exception as e:
                self.logger.error(f"Error fetching message {msg_id}: {e}")

        return new_messages

    def create_action_file(self, item: dict) -> Path:
        """Create a .md action file for a Gmail message.

        Args:
            item: Dict with id, headers, snippet, label_ids from check_for_updates.

        Returns:
            Path to the created .md file in /Needs_Action.
        """
        msg_id = item["id"]
        headers = item["headers"]
        snippet = item["snippet"]
        label_ids = item["label_ids"]

        sender = headers.get("From", "Unknown")
        subject = headers.get("Subject", "No Subject")
        date = headers.get("Date", "Unknown")
        priority = self._classify_email_priority(headers, label_ids)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_subject = "".join(
            c if c.isalnum() or c in " _-" else "_" for c in subject
        )[:60].strip()

        filename = f"EMAIL_{timestamp}_{safe_subject}.md"
        filepath = self.needs_action / filename

        # Escape for YAML safety
        escaped_sender = sender.replace('"', '\\"')
        escaped_subject = subject.replace('"', '\\"')

        content = f"""---
type: email
message_id: "{msg_id}"
from: "{escaped_sender}"
subject: "{escaped_subject}"
date: "{date}"
received: {datetime.now(timezone.utc).isoformat()}
priority: {priority}
status: pending
source: gmail
---

## Email: {subject}

**From**: {sender}
**Date**: {date}
**Priority**: {priority}

### Preview
{snippet}

### Suggested Actions
- [ ] Read full email
- [ ] Reply to sender
- [ ] Forward to relevant party
- [ ] Archive after processing
"""
        filepath.write_text(content, encoding="utf-8")
        self._processed_ids.add(msg_id)

        self.log_action(
            "email_detected",
            {
                "message_id": msg_id,
                "from": sender,
                "subject": subject,
                "priority": priority,
                "action_file": filename,
                "result": "success",
            },
        )

        return filepath

    def run(self) -> None:
        """Start the Gmail watcher with authentication check."""
        service = self._get_service()
        if not service:
            self.logger.error(
                "Gmail watcher cannot start - authentication failed. "
                "Ensure GMAIL_CREDENTIALS is set and valid."
            )
            return
        self.logger.info(f"Starting GmailWatcher (query: {self.query})")
        super().run()
