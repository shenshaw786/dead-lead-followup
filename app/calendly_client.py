"""
Calendly API Client
Fetches scheduled event history for a given email to determine if a call was hosted.
"""
import logging
import os
from typing import Dict, Any, List
import httpx

logger = logging.getLogger(__name__)

CALENDLY_API_KEY = os.getenv("CALENDLY_API_KEY")
CALENDLY_ORG_URI = os.getenv("CALENDLY_ORG_URI")
CALENDLY_BASE_URL = "https://api.calendly.com"


async def fetch_calendly_history(email: str) -> Dict[str, Any]:
    """
    Fetches Calendly booking history for a given email.
    
    Returns:
        Dict with keys:
        - has_bookings: bool
        - call_status: str ('completed' | 'booked_but_cancelled' | 'never_booked')
        - events: List[Dict] - up to 10 most recent events
        - summary: str - human-readable summary
    """
    if not CALENDLY_API_KEY or not CALENDLY_ORG_URI:
        logger.warning("Calendly API credentials not configured. Skipping.")
        return {
            "has_bookings": False,
            "call_status": "unknown",
            "events": [],
            "summary": "Calendly not configured.",
        }

    headers = {
        "Authorization": f"Bearer {CALENDLY_API_KEY}",
        "Content-Type": "application/json",
    }

    params = {
        "organization": CALENDLY_ORG_URI,
        "invitee_email": email,
        "count": 10,
        "sort": "start_time:desc",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{CALENDLY_BASE_URL}/scheduled_events",
                headers=headers,
                params=params,
            )

            if resp.status_code != 200:
                logger.error(f"Calendly API error {resp.status_code}: {resp.text}")
                return {
                    "has_bookings": False,
                    "call_status": "error",
                    "events": [],
                    "summary": f"Calendly API error: {resp.status_code}",
                }

            data = resp.json()
            events = data.get("collection", [])

            if not events:
                return {
                    "has_bookings": False,
                    "call_status": "never_booked",
                    "events": [],
                    "summary": "No Calendly bookings found for this email.",
                }

            # Classify call status
            active_events = [e for e in events if e.get("status") == "active"]
            canceled_events = [e for e in events if e.get("status") == "canceled"]

            if active_events:
                call_status = "completed"
                summary = f"✅ {len(active_events)} completed call(s) found."
            elif canceled_events:
                call_status = "booked_but_cancelled"
                summary = f"⚠️ {len(canceled_events)} booking(s) found but all were cancelled."
            else:
                call_status = "never_booked"
                summary = "No completed or cancelled bookings found."

            # Format event list for context
            event_summaries = []
            for event in events[:5]:  # Limit to 5 most recent
                name = event.get("name", "Untitled Event")
                start_time = event.get("start_time", "")
                status = event.get("status", "unknown")
                event_summaries.append({
                    "name": name,
                    "start_time": start_time,
                    "status": status,
                })

            return {
                "has_bookings": True,
                "call_status": call_status,
                "events": event_summaries,
                "summary": summary,
            }

    except Exception as e:
        logger.error(f"Calendly API exception for {email}: {e}", exc_info=True)
        return {
            "has_bookings": False,
            "call_status": "error",
            "events": [],
            "summary": f"Error fetching Calendly data: {str(e)}",
        }
