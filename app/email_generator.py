"""
AI Email Generator
Uses OpenAI to generate personalized follow-up email drafts based on:
- GHL lead data (name, company, pipeline stage, lead type)
- Fireflies transcript context (call summaries, action items, topics)
- Calendly booking history (did they show up? did they cancel?)
- Gmail correspondence history (what was said in past emails?)
"""
import logging
import os
from typing import Any, Dict, Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_client: Optional[AsyncOpenAI] = None

def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
        _client = AsyncOpenAI(api_key=api_key)
    return _client

SYSTEM_PROMPT = """You are a world-class sales copywriter specializing in re-engagement emails for high-ticket coaching and consulting businesses. 

Your emails are:
- Warm, personal, and human — never robotic or template-sounding
- Brief and punchy (150-250 words max)
- Focused on the prospect's specific situation and last touchpoint
- Written in first person from the sender's perspective
- Ending with a single, low-friction call to action (e.g., "Would you be open to a quick 15-min call?")
- Never pushy, salesy, or desperate

You will be given context about the lead and their history. Use it to craft a highly personalized email that feels like it was written specifically for them."""


def _build_user_prompt(
    lead: Dict[str, Any],
    transcript_context: Dict[str, Any],
    calendly_context: Optional[Dict[str, Any]] = None,
    gmail_history: Optional[Dict[str, Any]] = None,
) -> str:
    """Builds the user prompt for the AI based on all available context sources."""

    lead_type = lead.get("lead_type", "other")
    first_name = lead.get("first_name") or (lead.get("name", "").split()[0] if lead.get("name") else "there")
    company = lead.get("company", "")
    stage = lead.get("pipeline_stage", "")
    notes = lead.get("notes", "")
    tags = ", ".join(lead.get("tags", []))
    last_activity = lead.get("last_activity_date", "")

    # Determine situation and goal based on lead type + Calendly data
    call_status = (calendly_context or {}).get("call_status", "unknown")

    if call_status == "completed":
        situation = f"{first_name} had a call that was completed but did not move forward after the conversation."
        goal = "Re-engage with a warm, personalized check-in that references the call and asks if anything has changed."
    elif call_status == "booked_but_cancelled":
        situation = f"{first_name} booked a call but cancelled before it took place."
        goal = "Reach out gently, acknowledge the missed connection, and make it easy to rebook."
    elif lead_type == "call_no_show":
        situation = f"{first_name} booked a call but did not show up or did not move forward after the call."
        goal = "Re-engage them with a warm, no-pressure check-in that acknowledges the missed connection."
    elif lead_type == "applied_no_book":
        situation = f"{first_name} submitted an application (likely via Typeform) but never booked a discovery call."
        goal = "Acknowledge their interest and make it easy for them to take the next step — booking a call."
    elif lead_type == "closed_lost":
        situation = f"{first_name} was previously in the pipeline but the deal was marked as lost or they expressed disinterest."
        goal = "Reach out with a genuine check-in, acknowledging time has passed, and see if circumstances have changed."
    else:
        situation = f"{first_name} is a lead in the pipeline at stage: {stage}."
        goal = "Re-engage them with a personalized follow-up."

    prompt = f"""Please write a re-engagement follow-up email for the following lead:

LEAD INFORMATION:
- First Name: {first_name}
- Company: {company if company else "Not provided"}
- Pipeline Stage: {stage}
- Lead Type: {lead_type}
- Last Activity: {last_activity if last_activity else "Unknown"}
- Tags: {tags if tags else "None"}
- CRM Notes: {notes if notes else "None"}

SITUATION:
{situation}

YOUR GOAL:
{goal}
"""

    # Add Calendly context
    if calendly_context:
        prompt += f"""
CALENDLY BOOKING HISTORY:
{calendly_context.get('summary', 'No Calendly data available.')}
"""
        if calendly_context.get("events"):
            for event in calendly_context["events"][:3]:
                prompt += f"  - {event.get('name', 'Event')} on {event.get('start_time', '')[:10]} — Status: {event.get('status', 'unknown')}\n"

    # Add Fireflies transcript context
    if transcript_context.get("has_transcript"):
        prompt += f"""
CALL TRANSCRIPTS (Fireflies.ai — {transcript_context['transcript_count']} call(s) found):
{transcript_context['context_summary']}

Use the call history above to make the email feel hyper-personalized. Reference specific topics, pain points, or action items mentioned in the calls where relevant.
"""
    else:
        prompt += """
CALL TRANSCRIPTS: No Fireflies transcripts found.
"""

    # Add Gmail history context
    if gmail_history and gmail_history.get("has_history"):
        prompt += f"""
PREVIOUS EMAIL CORRESPONDENCE ({gmail_history['message_count']} emails found):
{chr(10).join(gmail_history.get('messages', [])[:5])}

Important: Do NOT repeat or contradict anything already said in previous emails. Build on the existing conversation thread naturally.
"""
    else:
        prompt += """
PREVIOUS EMAIL CORRESPONDENCE: No prior emails found with this lead.
"""

    prompt += """
OUTPUT FORMAT:
Return ONLY the email content in this exact format:

SUBJECT: [email subject line]

[email body]

Do not include any explanations, notes, or meta-commentary outside of the email itself."""

    return prompt


async def generate_email_draft(
    lead: Dict[str, Any],
    transcript_context: Dict[str, Any],
    edit_instructions: str = "",
    previous_draft: str = "",
    calendly_context: Optional[Dict[str, Any]] = None,
    gmail_history: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """
    Generates an AI email draft for a given lead using all available context.

    Args:
        lead: Normalized lead dict from GHL
        transcript_context: Transcript context from Fireflies
        edit_instructions: Optional user feedback for rewriting
        previous_draft: The previous draft to revise (used with edit_instructions)
        calendly_context: Calendly booking history for this lead
        gmail_history: Gmail correspondence history for this lead

    Returns:
        Dict with keys: subject, body, full_draft
    """
    model = os.getenv("OPENAI_MODEL", "gpt-4o")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if edit_instructions and previous_draft:
        # Rewrite mode — user provided edit instructions
        user_content = f"""Please rewrite the following email draft based on these instructions:

EDIT INSTRUCTIONS:
{edit_instructions}

PREVIOUS DRAFT:
{previous_draft}

Return the revised email in the same format:
SUBJECT: [subject line]

[email body]"""
    else:
        # Fresh generation mode — use all context sources
        user_content = _build_user_prompt(
            lead, transcript_context,
            calendly_context=calendly_context,
            gmail_history=gmail_history,
        )

    messages.append({"role": "user", "content": user_content})

    try:
        response = await _get_client().chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7,
            max_tokens=600,
        )

        raw_output = response.choices[0].message.content.strip()
        return _parse_email_output(raw_output)

    except Exception as e:
        logger.error(f"OpenAI API error: {e}", exc_info=True)
        raise


def _parse_email_output(raw: str) -> Dict[str, str]:
    """Parses the AI output into subject and body components."""
    subject = ""
    body = ""

    lines = raw.strip().split("\n")
    body_lines = []
    found_subject = False

    for line in lines:
        if line.upper().startswith("SUBJECT:"):
            subject = line[len("SUBJECT:"):].strip()
            found_subject = True
        elif found_subject:
            body_lines.append(line)

    if body_lines:
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        body = "\n".join(body_lines).strip()

    if not subject:
        subject = "Following up"
    if not body:
        body = raw

    return {
        "subject": subject,
        "body": body,
        "full_draft": f"Subject: {subject}\n\n{body}",
    }

# ─── Typeform No-Show Email Generator ────────────────────────────────────────
async def generate_typeform_nudge(
    lead: Dict[str, Any],
    calendly_booking_link: str = "https://calendly.com/viralgrowth",
) -> Dict[str, str]:
    """Generate a simple nudge email for Typeform applicants who didn't book."""
    first_name = lead.get("first_name") or (lead.get("name", "").split()[0] if lead.get("name") else "there")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    prompt = f"""You are Simon, a sales professional at Viral Growth, a digital marketing agency.

Write a short, friendly follow-up email to {first_name} who filled out our application form but hasn't booked a discovery call yet.

INSTRUCTIONS:
1. Keep it very short (under 100 words)
2. Be friendly and helpful, not pushy
3. Remind them they can book a call easily
4. Include the booking link: {calendly_booking_link}
5. Sound human and conversational
6. Sign off as Simon

Return ONLY the email in this exact format:
SUBJECT: [subject line]
[email body]"""

    try:
        response = await _get_client().chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300,
        )
        raw_output = response.choices[0].message.content.strip()
        return _parse_email_output(raw_output)
    except Exception as e:
        logger.error(f"OpenAI nudge generation error: {e}")
        return {
            "subject": f"Quick question, {first_name}",
            "body": f"Hi {first_name},\n\nI noticed you filled out our application but haven't booked a call yet. I'd love to connect!\n\nYou can grab a time here: {calendly_booking_link}\n\nLooking forward to chatting!\n\nBest,\nSimon",
            "full_draft": f"Subject: Quick question, {first_name}\n\nHi {first_name},\n\nI noticed you filled out our application but haven't booked a call yet.\n\nGrab a time here: {calendly_booking_link}\n\nBest,\nSimon",
        }
