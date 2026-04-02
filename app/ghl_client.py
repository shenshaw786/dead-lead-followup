"""
GoHighLevel (GHL) API Client
Fetches dead leads from the GHL CRM based on configured pipeline stages and inactivity.

Dead lead criteria:
  1. Contacts who booked a call but did NOT move forward (e.g., stage = "No Show", "Closed Lost")
  2. Contacts who submitted a Typeform application but did NOT book (e.g., stage = "Applied - No Book")

The system uses the /opportunities/search endpoint to find these leads.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

GHL_BASE_URL = "https://services.leadconnectorhq.com"
GHL_API_VERSION = "2021-07-28"


def _get_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {os.getenv('GHL_API_KEY')}",
        "Version": GHL_API_VERSION,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


async def fetch_dead_leads() -> List[Dict[str, Any]]:
    """
    Fetches dead leads from GHL based on:
    - Pipeline stage IDs configured in GHL_DEAD_PIPELINE_STAGE_IDS
    - Minimum inactivity period from GHL_INACTIVITY_DAYS
    - Status: 'lost' or 'abandoned'

    Returns a normalized list of lead dicts with keys:
        id, name, email, phone, company, pipeline_stage, last_activity_date,
        lead_type (call_no_show | applied_no_book | other), notes, tags
    """
    location_id = os.getenv("GHL_LOCATION_ID")
    api_key = os.getenv("GHL_API_KEY")
    stage_ids_raw = os.getenv("GHL_DEAD_PIPELINE_STAGE_IDS", "")
    inactivity_days = int(os.getenv("GHL_INACTIVITY_DAYS", "14"))

    if not location_id or not api_key:
        raise ValueError("GHL_LOCATION_ID and GHL_API_KEY must be set in .env")

    stage_ids = [s.strip() for s in stage_ids_raw.split(",") if s.strip()]
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=inactivity_days)

    all_leads = []

    async with httpx.AsyncClient(timeout=30) as client:
        # Fetch opportunities with status 'lost' and 'abandoned'
        for status in ["lost", "abandoned"]:
            page = 1
            while True:
                params = {
                    "location_id": location_id,
                    "status": status,
                    "limit": 100,
                    "page": page,
                    "getNotes": True,
                }

                resp = await client.get(
                    f"{GHL_BASE_URL}/opportunities/search",
                    headers=_get_headers(),
                    params=params,
                )

                if resp.status_code != 200:
                    logger.error(f"GHL API error {resp.status_code}: {resp.text}")
                    break

                data = resp.json()
                opportunities = data.get("opportunities", [])

                if not opportunities:
                    break

                for opp in opportunities:
                    lead = _normalize_opportunity(opp, stage_ids, cutoff_date)
                    if lead:
                        all_leads.append(lead)

                # Pagination
                meta = data.get("meta", {})
                total = meta.get("total", 0)
                if page * 100 >= total:
                    break
                page += 1

    # Deduplicate by contact email
    seen_emails = set()
    unique_leads = []
    for lead in all_leads:
        email = lead.get("email", "").lower()
        if email and email not in seen_emails:
            seen_emails.add(email)
            unique_leads.append(lead)

    logger.info(f"GHL: Found {len(unique_leads)} unique dead leads.")
    return unique_leads


def _normalize_opportunity(
    opp: Dict[str, Any],
    stage_ids: List[str],
    cutoff_date: datetime,
) -> Optional[Dict[str, Any]]:
    """
    Normalizes a GHL opportunity into a lead dict.
    Returns None if the lead does not meet dead lead criteria.
    """
    # Filter by pipeline stage if specific stages are configured
    pipeline_stage_id = opp.get("pipelineStageId", "")
    if stage_ids and pipeline_stage_id not in stage_ids:
        return None

    # Filter by inactivity: check lastActivityDate
    last_activity_str = opp.get("lastActivityDate") or opp.get("dateAdded")
    if last_activity_str:
        try:
            last_activity = datetime.fromisoformat(last_activity_str.replace("Z", "+00:00"))
            if last_activity > cutoff_date:
                return None  # Too recent, not dead yet
        except (ValueError, TypeError):
            pass  # If we can't parse the date, include the lead anyway

    contact = opp.get("contact", {})
    email = contact.get("email", "")

    if not email:
        return None  # Skip leads without an email

    # Determine lead type based on stage name or tags
    stage_name = opp.get("pipelineStage", {}).get("name", "").lower()
    tags = contact.get("tags", [])
    lead_type = _classify_lead_type(stage_name, tags)

    # Extract notes
    notes_list = opp.get("notes", [])
    notes_text = " | ".join(
        [n.get("body", "") for n in notes_list if n.get("body")]
    )[:1000]  # Limit notes length

    return {
        "id": opp.get("id"),
        "contact_id": contact.get("id"),
        "name": contact.get("name") or f"{contact.get('firstName', '')} {contact.get('lastName', '')}".strip(),
        "first_name": contact.get("firstName", ""),
        "email": email,
        "phone": contact.get("phone", ""),
        "company": contact.get("companyName", "") or opp.get("companyName", ""),
        "pipeline_stage": opp.get("pipelineStage", {}).get("name", "Unknown Stage"),
        "pipeline_stage_id": pipeline_stage_id,
        "status": opp.get("status"),
        "last_activity_date": opp.get("lastActivityDate", ""),
        "date_added": opp.get("dateAdded", ""),
        "lead_type": lead_type,
        "notes": notes_text,
        "tags": tags,
        "opportunity_name": opp.get("name", ""),
        "monetary_value": opp.get("monetaryValue", 0),
    }


def _classify_lead_type(stage_name: str, tags: List[str]) -> str:
    """
    Classifies the lead type based on pipeline stage name and tags.
    Returns: 'call_no_show' | 'applied_no_book' | 'closed_lost' | 'other'
    """
    tags_lower = [t.lower() for t in tags]
    stage_lower = stage_name.lower()

    if any(kw in stage_lower for kw in ["no show", "no-show", "noshow", "missed call", "ghosted"]):
        return "call_no_show"
    if any(kw in stage_lower for kw in ["applied", "application", "typeform", "no book", "no-book"]):
        return "applied_no_book"
    if any(kw in stage_lower for kw in ["closed lost", "lost", "not interested"]):
        return "closed_lost"
    if "no_show" in tags_lower or "missed_call" in tags_lower:
        return "call_no_show"
    if "applied" in tags_lower or "no_book" in tags_lower:
        return "applied_no_book"

    return "other"
