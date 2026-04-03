"""
Gmail API Client
Sends emails via the Gmail API using OAuth 2.0 refresh token.
Uses environment variables for credentials (no file-based auth needed).
"""
import base64
import logging
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import requests

logger = logging.getLogger(__name__)

GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET")
GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN")
GMAIL_SENDER_EMAIL = os.getenv("GMAIL_SENDER_EMAIL", "simon@viralgrowth.io")


def _get_access_token() -> str:
    """Get a fresh Gmail access token using the refresh token."""
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": GMAIL_CLIENT_ID,
            "client_secret": GMAIL_CLIENT_SECRET,
            "refresh_token": GMAIL_REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _create_message(sender: str, to_email: str, to_name: str, subject: str, body: str) -> dict:
    """Creates a Gmail API message object from email components."""
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = f"{to_name} <{to_email}>" if to_name else to_email

    text_part = MIMEText(body, "plain", "utf-8")
    message.attach(text_part)

    html_body = body.replace("\n", "<br>")
    html_part = MIMEText(f"<html><body><p>{html_body}</p></body></html>", "html", "utf-8")
    message.attach(html_part)

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return {"raw": raw}


async def send_email(
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
    sender_email: Optional[str] = None,
) -> dict:
    """Sends an email via the Gmail API using refresh token auth."""
    sender = sender_email or GMAIL_SENDER_EMAIL

    if not to_email:
        raise ValueError("Recipient email address is required.")

    logger.info(f"Sending email to {to_name} <{to_email}> — Subject: {subject}")

    try:
        access_token = _get_access_token()
        message = _create_message(sender, to_email, to_name, subject, body)

        resp = requests.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json=message,
            timeout=20,
        )
        resp.raise_for_status()
        result = resp.json()
        logger.info(f"Email sent successfully. Gmail Message ID: {result.get('id')}")
        return result

    except Exception as e:
        logger.error(f"Error sending email to {to_email}: {e}", exc_info=True)
        raise


async def fetch_gmail_history(email: str, max_results: int = 5) -> dict:
    """Fetch recent email thread history with a contact."""
    try:
        access_token = _get_access_token()
        headers = {"Authorization": f"Bearer {access_token}"}

        resp = requests.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            headers=headers,
            params={"q": f"from:{email} OR to:{email}", "maxResults": max_results},
            timeout=15,
        )
        resp.raise_for_status()
        messages = resp.json().get("messages", [])

        if not messages:
            return {"message_count": 0, "history": []}

        history_parts = []
        for msg in messages[:3]:
            msg_resp = requests.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
                headers=headers,
                params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
                timeout=10,
            )
            if msg_resp.status_code == 200:
                msg_data = msg_resp.json()
                headers_list = msg_data.get("payload", {}).get("headers", [])
                h = {h["name"]: h["value"] for h in headers_list}
                history_parts.append(
                    f"- {h.get('Date', '')}: {h.get('Subject', '(no subject)')} (from {h.get('From', '')})"
                )

        return {"message_count": len(messages), "history": history_parts}

    except Exception as e:
        logger.error(f"Gmail history error for {email}: {e}")
        return {"message_count": 0, "history": []}


async def verify_gmail_connection() -> bool:
    """Verifies that the Gmail API connection is working."""
    try:
        access_token = _get_access_token()
        resp = requests.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        resp.raise_for_status()
        email = resp.json().get("emailAddress", "unknown")
        logger.info(f"Gmail connection verified. Sending as: {email}")
        return True
    except Exception as e:
        logger.error(f"Gmail connection verification failed: {e}")
        return False
