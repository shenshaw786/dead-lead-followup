"""
Dead Lead Follow-Up Automation
Main FastAPI application with APScheduler for timed execution.
Two flows:
  1. Cold leads (GHL + Fireflies + Calendly + Gmail) - Mon/Thu 8AM EST
  2. Typeform no-shows (Typeform + Calendly) - Hourly check
"""
import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

load_dotenv()

from app.ghl_client import fetch_dead_leads
from app.fireflies_client import fetch_transcript_for_lead
from app.calendly_client import fetch_calendly_history
from app.gmail_history_client import fetch_gmail_history
from app.email_generator import generate_email_draft, generate_typeform_nudge
from app.slack_client import post_draft_for_approval
from app.slack_handler import router as slack_router
from app.state import pending_approvals

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# ─── Scheduler ───────────────────────────────────────────────────────────────
scheduler = AsyncIOScheduler(timezone=os.getenv("SCHEDULER_TIMEZONE", "America/New_York"))


# ─── Flow 1: Cold Lead Re-engagement ─────────────────────────────────────────
async def run_cold_lead_job():
    """
    Flow 1: 30-day cold leads from GHL.
    Enriches with Fireflies, Calendly, Gmail context before generating AI email.
    """
    logger.info("=== Starting Flow 1: Cold Lead Re-engagement ===")
    try:
        leads = await fetch_dead_leads()
        logger.info(f"Found {len(leads)} dead leads to process.")

        if not leads:
            logger.info("No dead leads found. Job complete.")
            return

        for lead in leads:
            try:
                logger.info(f"Processing lead: {lead.get('name')} <{lead.get('email')}>")
                email = lead.get("email", "")

                transcript_context = await fetch_transcript_for_lead(email)
                calendly_context = await fetch_calendly_history(email)
                gmail_history = await fetch_gmail_history(email)

                draft = await generate_email_draft(
                    lead,
                    transcript_context,
                    calendly_context=calendly_context,
                    gmail_history=gmail_history,
                    flow="cold_lead",
                )

                await post_draft_for_approval(lead, draft, calendly_context=calendly_context, flow="cold_lead")
                logger.info(f"Draft posted to Slack for: {lead.get('name')}")

            except Exception as e:
                logger.error(f"Error processing lead {lead.get('email')}: {e}", exc_info=True)

    except Exception as e:
        logger.error(f"Fatal error in cold lead job: {e}", exc_info=True)

    logger.info("=== Flow 1 Complete ===")


# ─── Flow 2: Typeform No-Show ─────────────────────────────────────────────────
async def run_typeform_noshowup_job():
    """
    Flow 2: Typeform applicants who filled the form 24h ago but didn't book a Calendly call.
    """
    logger.info("=== Starting Flow 2: Typeform No-Show Check ===")
    try:
        import requests
        from datetime import datetime, timezone, timedelta

        typeform_token = os.getenv("TYPEFORM_API_TOKEN")
        typeform_form_id = os.getenv("TYPEFORM_FORM_ID", "")
        calendly_booking_link = os.getenv("CALENDLY_BOOKING_LINK", "https://calendly.com/viralgrowth")

        if not typeform_token or not typeform_form_id:
            logger.warning("TYPEFORM_API_TOKEN or TYPEFORM_FORM_ID not set - skipping Flow 2")
            return

        # Fetch responses from 24-25 hours ago
        since = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
        resp = requests.get(
            f"https://api.typeform.com/forms/{typeform_form_id}/responses",
            headers={"Authorization": f"Bearer {typeform_token}"},
            params={"since": since, "page_size": 100},
            timeout=15,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])

        for item in items:
            answers = item.get("answers", [])
            name = ""
            email = ""

            for answer in answers:
                if answer.get("type") == "email":
                    email = answer.get("email", "")
                elif answer.get("type") == "text" and not name:
                    name = answer.get("text", "")

            if not email:
                continue

            # Check if they've booked a Calendly call
            calendly_context = await fetch_calendly_history(email)
            if calendly_context.get("call_status") != "never_booked":
                logger.info(f"Typeform lead {email} already booked - skipping")
                continue

            lead = {
                "name": name or email.split("@")[0],
                "email": email,
                "company": "",
                "flow": "typeform_noshowup",
            }

            draft = await generate_typeform_nudge(lead, calendly_booking_link=calendly_booking_link)

            await post_draft_for_approval(lead, draft, calendly_context=calendly_context, flow="typeform_noshowup")
            logger.info(f"Typeform nudge draft posted to Slack for: {email}")

    except Exception as e:
        logger.error(f"Fatal error in Typeform no-show job: {e}", exc_info=True)

    logger.info("=== Flow 2 Complete ===")


# ─── App Lifecycle ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Flow 1: Monday and Thursday at 8:00 AM EST
    scheduler.add_job(
        run_cold_lead_job,
        CronTrigger(day_of_week="mon,thu", hour=8, minute=0),
        id="cold_lead_followup",
        name="Cold Lead Follow-Up",
        replace_existing=True,
    )
    # Flow 2: Every hour (checks for 24h+ old Typeform responses)
    scheduler.add_job(
        run_typeform_noshowup_job,
        CronTrigger(minute=0),
        id="typeform_noshowup",
        name="Typeform No-Show Check",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started. Flow 1: Mon/Thu 8AM EST. Flow 2: Hourly.")
    yield
    scheduler.shutdown()
    logger.info("Scheduler shut down.")


# ─── FastAPI App ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="Dead Lead Follow-Up Automation",
    description="Automates follow-up emails for dead leads via GHL, Fireflies, Calendly, Gmail, Slack.",
    version="3.0.0",
    lifespan=lifespan,
)

app.include_router(slack_router)


@app.get("/")
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "scheduler_running": scheduler.running, "version": "3.0.0"}


@app.post("/run-now")
async def trigger_cold_lead_job():
    """Manually trigger Flow 1 (cold leads)."""
    logger.info("Manual Flow 1 trigger received.")
    import asyncio
    asyncio.create_task(run_cold_lead_job())
    return {"status": "Flow 1 (cold leads) triggered. Check Slack for drafts."}


@app.post("/run-typeform")
async def trigger_typeform_job():
    """Manually trigger Flow 2 (Typeform no-shows)."""
    logger.info("Manual Flow 2 trigger received.")
    import asyncio
    asyncio.create_task(run_typeform_noshowup_job())
    return {"status": "Flow 2 (Typeform no-shows) triggered. Check Slack for drafts."}


@app.post("/typeform/webhook")
async def typeform_webhook(request: Request):
    """Receive Typeform webhook - the hourly job will process it after 24h."""
    try:
        data = await request.json()
        form_response = data.get("form_response", {})
        logger.info(f"Typeform webhook received: token={form_response.get('token', 'unknown')}")
        return {"status": "received", "message": "Will check for Calendly booking in 24 hours"}
    except Exception as e:
        logger.error(f"Typeform webhook error: {e}")
        return {"status": "error"}


@app.get("/pending")
async def get_pending_approvals():
    """View currently pending Slack approvals."""
    return {"pending_count": len(pending_approvals), "leads": list(pending_approvals.keys())}
