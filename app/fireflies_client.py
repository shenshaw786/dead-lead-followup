"""
Fireflies.ai GraphQL API Client
Fetches call transcripts and summaries for a given lead email address.
"""
import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

FIREFLIES_API_URL = "https://api.fireflies.ai/graphql"

TRANSCRIPTS_QUERY = """
query GetTranscriptsForParticipant($participants: [String]) {
  transcripts(
    participants: $participants
    limit: 3
  ) {
    id
    title
    date
    duration
    transcript_url
    participants
    summary {
      overview
      action_items
      outline
      short_summary
      keywords
      topics_discussed
    }
    sentences {
      speaker_name
      text
    }
    meeting_attendees {
      displayName
      email
    }
  }
}
"""


async def fetch_transcript_for_lead(email: str) -> Optional[Dict[str, Any]]:
    """
    Fetches the most recent Fireflies transcript(s) for a lead by their email address.

    Returns a dict with:
        has_transcript: bool
        transcripts: list of transcript summaries
        context_summary: str (formatted text for AI prompt)
    """
    api_key = os.getenv("FIREFLIES_API_KEY")

    if not api_key:
        logger.warning("FIREFLIES_API_KEY not set. Skipping transcript fetch.")
        return _empty_context()

    if not email:
        return _empty_context()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "query": TRANSCRIPTS_QUERY,
        "variables": {"participants": [email]},
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(FIREFLIES_API_URL, json=payload, headers=headers)

        if resp.status_code != 200:
            logger.error(f"Fireflies API error {resp.status_code}: {resp.text}")
            return _empty_context()

        data = resp.json()
        errors = data.get("errors")
        if errors:
            logger.error(f"Fireflies GraphQL errors: {errors}")
            return _empty_context()

        transcripts = data.get("data", {}).get("transcripts", [])

        if not transcripts:
            logger.info(f"No Fireflies transcripts found for: {email}")
            return _empty_context()

        logger.info(f"Found {len(transcripts)} Fireflies transcript(s) for: {email}")
        return _build_context(transcripts)

    except Exception as e:
        logger.error(f"Error fetching Fireflies transcript for {email}: {e}", exc_info=True)
        return _empty_context()


def _build_context(transcripts: list) -> Dict[str, Any]:
    """
    Builds a structured context dict from Fireflies transcripts for use in AI email generation.
    """
    context_parts = []
    transcript_summaries = []

    for i, t in enumerate(transcripts, 1):
        summary = t.get("summary", {}) or {}
        title = t.get("title", "Untitled Meeting")
        date = t.get("date", "")
        duration_sec = t.get("duration", 0)
        duration_min = round(duration_sec / 60) if duration_sec else 0

        overview = summary.get("overview") or summary.get("short_summary") or ""
        action_items = summary.get("action_items") or ""
        topics = summary.get("topics_discussed") or summary.get("keywords") or ""

        part = f"--- Call {i}: {title} ({date}, {duration_min} min) ---\n"
        if overview:
            part += f"Overview: {overview}\n"
        if topics:
            part += f"Topics Discussed: {topics}\n"
        if action_items:
            part += f"Action Items / Next Steps: {action_items}\n"

        context_parts.append(part)
        transcript_summaries.append({
            "title": title,
            "date": date,
            "duration_min": duration_min,
            "overview": overview,
            "action_items": action_items,
            "topics": topics,
            "url": t.get("transcript_url", ""),
        })

    context_summary = "\n".join(context_parts)

    return {
        "has_transcript": True,
        "transcript_count": len(transcripts),
        "transcripts": transcript_summaries,
        "context_summary": context_summary,
    }


def _empty_context() -> Dict[str, Any]:
    return {
        "has_transcript": False,
        "transcript_count": 0,
        "transcripts": [],
        "context_summary": "",
    }
