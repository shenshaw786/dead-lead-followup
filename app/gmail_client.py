"""
Gmail API Client
Sends emails via the Gmail API using OAuth 2.0 credentials.
Supports Google Workspace accounts.

Authentication Setup:
1. Go to Google Cloud Console (console.cloud.google.com)
2. Create a project and enable the Gmail API
3. Create OAuth 2.0 credentials (Desktop App type)
4. Download credentials.json and place it in the project root
5. On first run, the app will open a browser for authorization
6. The token will be saved to token.json for future use
"""
import base64
import logging
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# Gmail API scopes required
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

# Token storage path
TOKEN_PATH = Path("data/gmail_token.json")
CREDENTIALS_PATH = Path(os.getenv("GMAIL_CREDENTIALS_FILE", "credentials.json"))


def _get_gmail_service():
    """
    Authenticates with the Gmail API and returns a service object.
    Uses stored token if available, otherwise initiates OAuth flow.
    """
    creds = None

    # Load existing token if available
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    # Refresh or re-authenticate if needed
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing Gmail OAuth token...")
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    f"Gmail credentials file not found at: {CREDENTIALS_PATH}\n"
                    "Please download credentials.json from Google Cloud Console and place it in the project root."
                )
            logger.info("Initiating Gmail OAuth flow...")
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)

        # Save the token for future use
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(creds.to_json())
        logger.info(f"Gmail token saved to {TOKEN_PATH}")

    return build("gmail", "v1", credentials=creds)


def _create_message(
    sender: str,
    to_email: str,
    to_name: str,
    subject: str,
    body: str,
) -> dict:
    """
    Creates a Gmail API message object from email components.
    Sends as plain text with proper formatting.
    """
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = f"{to_name} <{to_email}>" if to_name else to_email

    # Plain text part
    text_part = MIMEText(body, "plain", "utf-8")
    message.attach(text_part)

    # HTML part (convert line breaks to <br> for better rendering)
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
    """
    Sends an email via the Gmail API.

    Args:
        to_email: Recipient email address
        to_name: Recipient display name
        subject: Email subject line
        body: Plain text email body
        sender_email: Override sender email (defaults to GMAIL_SENDER_EMAIL env var)

    Returns:
        Gmail API response dict with message ID
    """
    sender = sender_email or os.getenv("GMAIL_SENDER_EMAIL", "me")

    if not to_email:
        raise ValueError("Recipient email address is required.")

    logger.info(f"Sending email to {to_name} <{to_email}> — Subject: {subject}")

    try:
        service = _get_gmail_service()
        message = _create_message(sender, to_email, to_name, subject, body)

        result = service.users().messages().send(
            userId="me",
            body=message,
        ).execute()

        message_id = result.get("id")
        logger.info(f"Email sent successfully. Gmail Message ID: {message_id}")
        return result

    except HttpError as e:
        logger.error(f"Gmail API HttpError: {e.status_code} — {e.reason}")
        raise
    except FileNotFoundError as e:
        logger.error(str(e))
        raise
    except Exception as e:
        logger.error(f"Unexpected error sending email: {e}", exc_info=True)
        raise


async def verify_gmail_connection() -> bool:
    """
    Verifies that the Gmail API connection is working by fetching the user's profile.
    Returns True if successful, False otherwise.
    """
    try:
        service = _get_gmail_service()
        profile = service.users().getProfile(userId="me").execute()
        email = profile.get("emailAddress", "unknown")
        logger.info(f"Gmail connection verified. Sending as: {email}")
        return True
    except Exception as e:
        logger.error(f"Gmail connection verification failed: {e}")
        return False
