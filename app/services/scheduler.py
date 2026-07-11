"""
In-process background scheduler (APScheduler, AsyncIO).

Started/stopped by the FastAPI lifespan. Guarded by SCHEDULER_ENABLED so it can
be turned off (e.g. when running multiple workers — run the scheduler in only
one, or disable it and trigger the jobs externally).

Jobs:
  - appointment reminders   (every REMINDER_JOB_MINUTES)
  - re-engagement           (every REENGAGE_JOB_HOURS)
  - paused-handoff alert    (every HANDOFF_ALERT_JOB_MINUTES)
  - Google Calendar reconcile (every REMINDER_JOB_MINUTES, only if GCal configured)
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.services import followups
from app.services import google_calendar as gcal

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def start_scheduler() -> None:
    global _scheduler
    if not settings.SCHEDULER_ENABLED:
        logger.info("scheduler_disabled")
        return
    if _scheduler is not None:
        return

    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(
        followups.run_appointment_reminders, "interval",
        minutes=settings.REMINDER_JOB_MINUTES,
        id="appointment_reminders", max_instances=1, coalesce=True,
    )
    _scheduler.add_job(
        followups.run_reengagement, "interval",
        hours=settings.REENGAGE_JOB_HOURS,
        id="reengagement", max_instances=1, coalesce=True,
    )
    _scheduler.add_job(
        followups.run_paused_alert, "interval",
        minutes=settings.HANDOFF_ALERT_JOB_MINUTES,
        id="handoff_paused_alert", max_instances=1, coalesce=True,
    )
    if gcal.is_configured():
        _scheduler.add_job(
            gcal.run_google_sync_reconcile, "interval",
            minutes=settings.REMINDER_JOB_MINUTES,
            id="gcal_reconcile", max_instances=1, coalesce=True,
        )
    _scheduler.start()
    logger.info(
        "scheduler_started",
        extra={
            "reminder_minutes": settings.REMINDER_JOB_MINUTES,
            "reengage_hours": settings.REENGAGE_JOB_HOURS,
            "handoff_alert_minutes": settings.HANDOFF_ALERT_JOB_MINUTES,
            "gcal": gcal.is_configured(),
        },
    )


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("scheduler_stopped")
