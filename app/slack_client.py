"""
Slack Client
Posts email drafts to a Slack channel for approval using Block Kit interactive messages.
Handles the three-button approval flow: Approve, Edit, Reject.
"""
import json
import logging
import os
from typing import Any, Dict

from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.errors import SlackApiError

from app.state import pending_approvals

logger = logging.getLogger(__name__)


def _get_slack_client() -> AsyncWebClient:
    return AsyncWebClient(token=os.getenv("SLACK_BOT_TOKEN"))


async def post_draft_for_approval(lead: Dict[str, Any], draft: Dict[str, str], calendly_context: Dict[str, Any] = None) -> str:
    """
    Posts an email draft to the configured Slack channel with interactive buttons.

    Returns the Slack message timestamp (ts) which is used as the approval key.
    """
    client = _get_slack_client()
    channel = os.getenv("SLACK_CHANNEL_ID")

    lead_name = lead.get("name", "Unknown Lead")
    lead_email = lead.get("email", "")
    lead_type = lead.get("lead_type", "other")
    stage = lead.get("pipeline_stage", "")
    company = lead.get("company", "")
    has_transcript = lead.get("_has_transcript", False)

    # Lead type badge
    type_labels = {
        "call_no_show": "📞 Booked Call — No Show",
        "applied_no_book": "📋 Applied — Didn't Book",
        "closed_lost": "❌ Closed Lost",
        "other": "🔄 Dead Lead",
    }
    type_label = type_labels.get(lead_type, "🔄 Dead Lead")
    transcript_badge = "🎙️ Fireflies transcript used" if has_transcript else "📝 No transcript found"

    # Calendly call status badge
    call_status = (calendly_context or {}).get("call_status", "unknown")
    calendly_badges = {
        "completed": "✅ Call completed",
        "booked_but_cancelled": "⚠️ Booked but cancelled",
        "never_booked": "🚫 Never booked a call",
        "unknown": "❓ Calendly unknown",
        "error": "❓ Calendly error",
    }
    calendly_badge = calendly_badges.get(call_status, "❓ No Calendly data")

    subject = draft.get("subject", "")
    body = draft.get("body", "")

    # Truncate body for Slack display (Slack has a 3000 char limit per block)
    display_body = body[:2800] + "..." if len(body) > 2800 else body

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📧 New Follow-Up Draft: {lead_name}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Lead:*\n{lead_name}"},
                {"type": "mrkdwn", "text": f"*Email:*\n{lead_email}"},
                {"type": "mrkdwn", "text": f"*Type:*\n{type_label}"},
                {"type": "mrkdwn", "text": f"*Stage:*\n{stage}"},
                {"type": "mrkdwn", "text": f"*Company:*\n{company if company else 'N/A'}"},
                {"type": "mrkdwn", "text": f"*Call Status:*\n{calendly_badge}"},
                {"type": "mrkdwn", "text": f"*Transcript:*\n{transcript_badge}"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Subject:* {subject}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Email Body:*\n```{display_body}```",
            },
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Approve & Send", "emoji": True},
                    "style": "primary",
                    "action_id": "approve_email",
                    "confirm": {
                        "title": {"type": "plain_text", "text": "Send this email?"},
                        "text": {"type": "mrkdwn", "text": f"This will send the email to *{lead_name}* at `{lead_email}`."},
                        "confirm": {"type": "plain_text", "text": "Yes, Send It"},
                        "deny": {"type": "plain_text", "text": "Cancel"},
                    },
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✏️ Edit Instructions", "emoji": True},
                    "action_id": "edit_email",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❌ Reject", "emoji": True},
                    "style": "danger",
                    "action_id": "reject_email",
                    "confirm": {
                        "title": {"type": "plain_text", "text": "Reject this draft?"},
                        "text": {"type": "mrkdwn", "text": "This lead will be skipped this cycle."},
                        "confirm": {"type": "plain_text", "text": "Yes, Reject"},
                        "deny": {"type": "plain_text", "text": "Cancel"},
                    },
                },
            ],
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "To edit: click *✏️ Edit Instructions* and reply in the thread with your changes.",
                }
            ],
        },
    ]

    try:
        response = await client.chat_postMessage(
            channel=channel,
            blocks=blocks,
            text=f"New follow-up draft for {lead_name} ({lead_email}) — awaiting approval.",
        )

        ts = response["ts"]

        # Store in pending approvals state
        pending_approvals[ts] = {
            "lead": lead,
            "draft": draft,
            "channel": channel,
            "ts": ts,
        }

        logger.info(f"Draft posted to Slack for {lead_name} (ts={ts})")
        return ts

    except SlackApiError as e:
        logger.error(f"Slack API error posting draft: {e.response['error']}")
        raise


async def update_message_after_action(
    channel: str,
    ts: str,
    action: str,
    lead_name: str,
    lead_email: str,
    new_draft: Dict[str, str] = None,
):
    """
    Updates the Slack message after an action is taken (approve/reject/edit).
    """
    client = _get_slack_client()

    if action == "approved":
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"✅ *Email sent* to *{lead_name}* (`{lead_email}`)",
                },
            }
        ]
        text = f"✅ Email sent to {lead_name}"

    elif action == "rejected":
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"❌ *Draft rejected* for *{lead_name}* — lead skipped this cycle.",
                },
            }
        ]
        text = f"❌ Draft rejected for {lead_name}"

    elif action == "rewritten" and new_draft:
        subject = new_draft.get("subject", "")
        body = new_draft.get("body", "")
        display_body = body[:2800] + "..." if len(body) > 2800 else body

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"📧 Revised Draft: {lead_name}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Subject:* {subject}"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Email Body:*\n```{display_body}```"},
            },
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Approve & Send", "emoji": True},
                        "style": "primary",
                        "action_id": "approve_email",
                        "confirm": {
                            "title": {"type": "plain_text", "text": "Send this email?"},
                            "text": {"type": "mrkdwn", "text": f"This will send the email to *{lead_name}* at `{lead_email}`."},
                            "confirm": {"type": "plain_text", "text": "Yes, Send It"},
                            "deny": {"type": "plain_text", "text": "Cancel"},
                        },
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✏️ Edit Again", "emoji": True},
                        "action_id": "edit_email",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ Reject", "emoji": True},
                        "style": "danger",
                        "action_id": "reject_email",
                    },
                ],
            },
        ]
        text = f"Revised draft for {lead_name} — awaiting approval."

    else:
        return

    try:
        await client.chat_update(channel=channel, ts=ts, blocks=blocks, text=text)
    except SlackApiError as e:
        logger.error(f"Slack API error updating message: {e.response['error']}")


async def post_thread_message(channel: str, ts: str, text: str):
    """Posts a message in the thread of an existing Slack message."""
    client = _get_slack_client()
    try:
        await client.chat_postMessage(channel=channel, thread_ts=ts, text=text)
    except SlackApiError as e:
        logger.error(f"Slack API error posting thread message: {e.response['error']}")


async def open_edit_modal(trigger_id: str, message_ts: str, channel: str):
    """
    Opens a Slack modal for the user to enter edit instructions.
    """
    client = _get_slack_client()

    modal = {
        "type": "modal",
        "callback_id": "edit_instructions_modal",
        "title": {"type": "plain_text", "text": "Edit Email Draft"},
        "submit": {"type": "plain_text", "text": "Rewrite Email"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": json.dumps({"message_ts": message_ts, "channel": channel}),
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Describe how you'd like the email to be changed. Be as specific as you like.",
                },
            },
            {
                "type": "input",
                "block_id": "edit_instructions_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "edit_instructions_input",
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "e.g. Make it shorter, more casual, reference the pain point about lead gen, add a P.S. line...",
                    },
                },
                "label": {"type": "plain_text", "text": "Edit Instructions"},
            },
        ],
    }

    try:
        await client.views_open(trigger_id=trigger_id, view=modal)
    except SlackApiError as e:
        logger.error(f"Slack API error opening modal: {e.response['error']}")
        raise
