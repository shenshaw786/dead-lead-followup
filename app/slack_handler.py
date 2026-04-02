"""
Slack Interaction Handler
FastAPI router that handles Slack interactive component payloads:
- Button clicks: approve_email, edit_email, reject_email
- Modal submissions: edit_instructions_modal
"""
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Dict

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import JSONResponse

from app.state import pending_approvals

logger = logging.getLogger(__name__)
router = APIRouter()


def _verify_slack_signature(request_body: bytes, timestamp: str, signature: str) -> bool:
    """
    Verifies the Slack request signature to ensure the request is authentic.
    https://api.slack.com/authentication/verifying-requests-from-slack
    """
    signing_secret = os.getenv("SLACK_SIGNING_SECRET", "")
    if not signing_secret:
        logger.warning("SLACK_SIGNING_SECRET not set — skipping signature verification.")
        return True

    # Reject requests older than 5 minutes
    if abs(time.time() - int(timestamp)) > 300:
        logger.warning("Slack request timestamp too old.")
        return False

    sig_basestring = f"v0:{timestamp}:{request_body.decode('utf-8')}"
    computed_sig = "v0=" + hmac.new(
        signing_secret.encode("utf-8"),
        sig_basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed_sig, signature)


@router.post("/slack/interactions")
async def handle_slack_interaction(request: Request):
    """
    Main endpoint for Slack interactive component payloads.
    Slack sends a form-encoded payload to this URL.
    """
    body_bytes = await request.body()

    # Verify Slack signature
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "0")
    signature = request.headers.get("X-Slack-Signature", "")
    if not _verify_slack_signature(body_bytes, timestamp, signature):
        return Response(status_code=403, content="Invalid signature")

    # Parse the URL-encoded payload
    form_data = await request.form()
    payload_str = form_data.get("payload", "")

    if not payload_str:
        return Response(status_code=400, content="Missing payload")

    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError:
        return Response(status_code=400, content="Invalid JSON payload")

    payload_type = payload.get("type")

    if payload_type == "block_actions":
        return await _handle_block_action(payload)
    elif payload_type == "view_submission":
        return await _handle_modal_submission(payload)
    else:
        logger.warning(f"Unhandled Slack payload type: {payload_type}")
        return Response(status_code=200)


async def _handle_block_action(payload: Dict[str, Any]) -> Response:
    """Handles button click actions from Slack Block Kit messages."""
    from app.slack_client import (
        update_message_after_action,
        post_thread_message,
        open_edit_modal,
    )
    from app.gmail_client import send_email

    actions = payload.get("actions", [])
    if not actions:
        return Response(status_code=200)

    action = actions[0]
    action_id = action.get("action_id")
    message = payload.get("message", {})
    message_ts = message.get("ts")
    channel = payload.get("channel", {}).get("id")
    trigger_id = payload.get("trigger_id")

    logger.info(f"Slack action received: {action_id} for message ts={message_ts}")

    # Look up the pending approval
    approval_data = pending_approvals.get(message_ts)
    if not approval_data:
        logger.warning(f"No pending approval found for ts={message_ts}")
        await post_thread_message(
            channel, message_ts,
            "⚠️ Could not find this draft in memory. The server may have restarted."
        )
        return Response(status_code=200)

    lead = approval_data["lead"]
    draft = approval_data["draft"]
    lead_name = lead.get("name", "Unknown")
    lead_email = lead.get("email", "")

    if action_id == "approve_email":
        # Send the email via Gmail
        try:
            await send_email(
                to_email=lead_email,
                to_name=lead_name,
                subject=draft["subject"],
                body=draft["body"],
            )
            await update_message_after_action(channel, message_ts, "approved", lead_name, lead_email)
            await post_thread_message(
                channel, message_ts,
                f"✅ Email successfully sent to *{lead_name}* (`{lead_email}`)"
            )
            # Remove from pending
            pending_approvals.pop(message_ts, None)
            logger.info(f"Email approved and sent to {lead_email}")

        except Exception as e:
            logger.error(f"Failed to send email to {lead_email}: {e}", exc_info=True)
            await post_thread_message(
                channel, message_ts,
                f"❌ Failed to send email: `{str(e)}`"
            )

    elif action_id == "edit_email":
        # Open a modal for edit instructions
        try:
            await open_edit_modal(trigger_id, message_ts, channel)
        except Exception as e:
            # Fallback: ask for instructions in thread
            await post_thread_message(
                channel, message_ts,
                "✏️ *Edit mode activated.* Reply in this thread with your edit instructions and I'll rewrite the email."
            )

    elif action_id == "reject_email":
        await update_message_after_action(channel, message_ts, "rejected", lead_name, lead_email)
        await post_thread_message(
            channel, message_ts,
            f"❌ Draft rejected for *{lead_name}* — this lead will be skipped this cycle."
        )
        pending_approvals.pop(message_ts, None)
        logger.info(f"Draft rejected for {lead_email}")

    return Response(status_code=200)


async def _handle_modal_submission(payload: Dict[str, Any]) -> Response:
    """Handles modal form submissions (edit instructions)."""
    from app.slack_client import update_message_after_action, post_thread_message
    from app.email_generator import generate_email_draft

    callback_id = payload.get("view", {}).get("callback_id")

    if callback_id != "edit_instructions_modal":
        return Response(status_code=200)

    # Extract private metadata
    private_metadata_str = payload.get("view", {}).get("private_metadata", "{}")
    try:
        private_metadata = json.loads(private_metadata_str)
    except json.JSONDecodeError:
        return Response(status_code=200)

    message_ts = private_metadata.get("message_ts")
    channel = private_metadata.get("channel")

    # Extract edit instructions from modal input
    values = payload.get("view", {}).get("state", {}).get("values", {})
    edit_instructions = (
        values.get("edit_instructions_block", {})
        .get("edit_instructions_input", {})
        .get("value", "")
    )

    logger.info(f"Edit instructions received for ts={message_ts}: {edit_instructions[:100]}")

    # Look up the pending approval
    approval_data = pending_approvals.get(message_ts)
    if not approval_data:
        return Response(status_code=200)

    lead = approval_data["lead"]
    draft = approval_data["draft"]
    transcript_context = approval_data.get("transcript_context", {})
    lead_name = lead.get("name", "Unknown")
    lead_email = lead.get("email", "")

    # Post acknowledgment in thread
    await post_thread_message(
        channel, message_ts,
        f"✏️ Got it! Rewriting the email for *{lead_name}* based on your instructions...\n> _{edit_instructions}_"
    )

    # Rewrite the email
    try:
        new_draft = await generate_email_draft(
            lead=lead,
            transcript_context=transcript_context,
            edit_instructions=edit_instructions,
            previous_draft=draft.get("full_draft", ""),
        )

        # Update the stored draft
        approval_data["draft"] = new_draft
        pending_approvals[message_ts] = approval_data

        # Update the Slack message with the new draft
        await update_message_after_action(
            channel, message_ts, "rewritten", lead_name, lead_email, new_draft
        )

        logger.info(f"Email rewritten for {lead_email}")

    except Exception as e:
        logger.error(f"Failed to rewrite email for {lead_email}: {e}", exc_info=True)
        await post_thread_message(
            channel, message_ts,
            f"❌ Failed to rewrite email: `{str(e)}`"
        )

    # Return empty response to close the modal
    return JSONResponse(content={})
