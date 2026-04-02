"""
Gmail History Client
Fetches past email correspondence with a lead to provide context for AI email generation.
Uses the Gmail API to search for threads with the lead's email address.
"""
import base64
import logging
import os
import json
from typing import Dict, Any, List, Optional
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def _get_gmail_service():
    """Returns an authenticated Gmail API service instance."""
    token_path = os.getenv("GMAIL_TOKEN_JSON", "token.json")
    credentials_path = os.getenv("GMAIL_CREDENTIALS_JSON", "credentials.json")

    creds = None

    # Load token from env var (for Railway deployment) or file
    token_json_str = os.getenv("GMAIL_TOKEN_JSON_CONTENT")
    if token_json_str:
        try:
            token_data = json.loads(token_json_str)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        except Exception as e:
            logger.error(f"Failed to load Gmail token from env: {e}")

    if not creds and os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Save refreshed token
            if os.path.exists(token_path):
                with open(token_path, "w") as f:
                    f.write(creds.to_json())
        else:
            logger.warning("Gmail credentials not available or invalid.")
            return None

    return build("gmail", "v1", credentials=creds)


def _extract_message_snippet(msg: Dict) -> str:
    """Extracts subject and snippet from a Gmail message."""
    headers = msg.get("payload", {}).get("headers", [])
    subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "(No Subject)")
    snippet = msg.get("snippet", "")
    date = next((h["value"] for h in headers if h["name"].lower() == "date"), "")
    direction = "→ Sent" if "SENT" in msg.get("labelIds", []) else "← Received"
    return f"{direction} [{date[:16]}] Subject: {subject}\nPreview: {snippet}"


async def fetch_gmail_history(email: str, max_messages: int = 5) -> Dict[str, Any]:
    """
    Fetches recent email correspondence with a lead.

    Args:
        email: Lead's email address
        max_messages: Maximum number of messages to retrieve

    Returns:
        Dict with keys:
        - has_history: bool
        - message_count: int
        - messages: List[str] - formatted message summaries
        - summary: str - human-readable summary for AI context
    """
    try:
        service = _get_gmail_service()
        if not service:
            return {
                "has_history": False,
                "message_count": 0,
                "messages": [],
                "summary": "Gmail not configured — no email history available.",
            }

        # Search for all emails to/from this address
        query = f"from:{email} OR to:{email}"
        result = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_messages,
        ).execute()

        messages_list = result.get("messages", [])

        if not messages_list:
            return {
                "has_history": False,
                "message_count": 0,
                "messages": [],
                "summary": f"No previous email correspondence found with {email}.",
            }

        # Fetch each message's details
        formatted_messages = []
        for msg_ref in messages_list:
            try:
                msg = service.users().messages().get(
                    userId="me",
                    id=msg_ref["id"],
                    format="metadata",
                    metadataHeaders=["Subject", "From", "To", "Date"],
                ).execute()
                formatted_messages.append(_extract_message_snippet(msg))
            except Exception as e:
                logger.warning(f"Could not fetch message {msg_ref['id']}: {e}")

        summary = (
            f"PREVIOUS EMAIL CORRESPONDENCE ({len(formatted_messages)} emails found):\n"
            + "\n\n".join(formatted_messages)
        )

        return {
            "has_history": True,
            "message_count": len(formatted_messages),
            "messages": formatted_messages,
            "summary": summary,
        }

    except Exception as e:
        logger.error(f"Gmail history error for {email}: {e}", exc_info=True)
        return {
            "has_history": False,
            "message_count": 0,
            "messages": [],
            "summary": f"Error fetching Gmail history: {str(e)}",
        }
