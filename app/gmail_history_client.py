"""
Gmail History Client
Fetches email correspondence history for a given contact.
Delegates to gmail_client for actual API calls.
"""
import logging
from app.gmail_client import fetch_gmail_history as _fetch_gmail_history

logger = logging.getLogger(__name__)


async def fetch_gmail_history(email: str) -> dict:
    """
    Fetch recent email thread history with a contact.
    Returns a dict with message_count and history list.
    """
    result = await _fetch_gmail_history(email)
    history_text = "\n".join(result.get("history", []))
    return {
        "message_count": result.get("message_count", 0),
        "history_text": history_text,
        "has_history": result.get("message_count", 0) > 0,
    }
