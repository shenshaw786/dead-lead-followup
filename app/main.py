"""
Dead Lead Follow-Up Automation
Main FastAPI application with APScheduler for timed execution.
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
from app.email_generator import generate_email_draft
from app.slack_client import post_draft_for_approval
from app.slack_handler import router as slack_router
from app.state import pending_approvals

# ─── Logging ─────────────────────────────────────────────────────────────────
# Use stdout logging only (Railway captures stdout natively)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# ─── Scheduler ───────────────────────────────────────────────────────────────
scheduler = AsyncIOScheduler(timezone=os.getenv("SCHEDULER_TIMEZONE", "America/New_York"))


async def run_followup_job():
    """
    Core automation job:
    1. Fetch dead leads from GHL
    2. Enrich with Fireflies transcripts
    3. Cross-reference Calendly booking history
    4. Check Gmail correspondence history
    5. Generate AI email drafts
    6. Post to Slack for approval
    """
    logger.info("=== Starting Dead Lead Follow-Up Job ===")

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

                # Fetch Fireflies transcript context
                transcript_context = await fetch_transcript_for_lead(email)
                logger.info(f"Fireflies: {'found' if transcript_context.get('has_transcript') else 'no'} transcripts for {email}")

                # Cross-reference Calendly booking history
                calendly_context = await fetch_calendly_history(email)
                logger.info(f"Calendly: {calendly_context.get('call_status', 'unknown')} for {email}")

                # Check Gmail correspondence history
                gmail_history = await fetch_gmail_history(email)
                logger.info(f"Gmail: {gmail_history.get('message_count', 0)} past emails found for {email}")

                # Generate AI email draft with all context sources
                draft = await generate_email_draft(
                    lead,
                    transcript_context,
                    calendly_context=calendly_context,
                    gmail_history=gmail_history,
                )

                # Post to Slack for approval
                await post_draft_for_approval(lead, draft, calendly_context=calendly_context)

                logger.info(f"Draft posted to Slack for: {lead.get('name')}")

            except Exception as e:
                logger.error(f"Error processing lead {lead.get('email')}: {e}", exc_info=True)

    except Exception as e:
        logger.error(f"Fatal error in follow-up job: {e}", exc_info=True)

    logger.info("=== Dead Lead Follow-Up Job Complete ===")


# ─── App Lifecycle ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schedule: Monday and Thursday at 8:00 AM EST
    scheduler.add_job(
        run_followup_job,
        CronTrigger(day_of_week="mon,thu", hour=8, minute=0),
        id="dead_lead_followup",
        name="Dead Lead Follow-Up",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started. Jobs: Monday & Thursday at 8:00 AM EST.")
    yield
    scheduler.shutdown()
    logger.info("Scheduler shut down.")


# ─── FastAPI App ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="Dead Lead Follow-Up Automation",
    description="Automates follow-up emails for dead leads via GHL, Fireflies, Calendly, Gmail, Slack.",
    version="2.0.0",
    lifespan=lifespan,
)

# Include Slack interaction handler routes
app.include_router(slack_router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "scheduler_running": scheduler.running}


@app.post("/run-now")
async def trigger_job_manually():
    """Manually trigger the follow-up job (for testing)."""
    logger.info("Manual job trigger received.")
    import asyncio
    asyncio.create_task(run_followup_job())
    return {"status": "Job triggered. Check Slack for drafts."}


@app.get("/pending")
async def get_pending_approvals():
    """View currently pending Slack approvals."""
    return {"pending_count": len(pending_approvals), "leads": list(pending_approvals.keys())}
