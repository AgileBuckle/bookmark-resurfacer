import logging
from functools import partial

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import SessionLocal
from app.email_service import send_email_for_user
from app.models import User
from app.settings_service import get_settings

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
_scheduler_started = False

MIN_INTERVAL_HOURS = 1.0
MAX_INTERVAL_HOURS = 8760.0
DEFAULT_INTERVAL_HOURS = 24.0


def _get_job_id(user_id: str) -> str:
    return f"email_job_{user_id}"


def _get_interval_hours_for_user(user_id: str) -> float:
    db = SessionLocal()
    try:
        settings = get_settings(db, user_id)
        try:
            hours = float(settings.get("schedule_interval_hours") or DEFAULT_INTERVAL_HOURS)
        except (ValueError, TypeError):
            return DEFAULT_INTERVAL_HOURS
        # Clamp: a tiny interval turns the scheduler into a mail flood.
        return max(MIN_INTERVAL_HOURS, min(hours, MAX_INTERVAL_HOURS))
    finally:
        db.close()


async def _do_send(user_id: str) -> None:
    db = SessionLocal()
    try:
        _, error = await send_email_for_user(db, user_id)
        if error:
            logger.warning("Scheduled email failed for user %s: %s", user_id, error)
    except Exception:
        logger.exception("Unexpected error sending scheduled email for user %s", user_id)
    finally:
        db.close()


def reschedule_for_user(user_id: str) -> None:
    job_id = _get_job_id(user_id)
    interval = _get_interval_hours_for_user(user_id)
    job = scheduler.get_job(job_id)
    if job:
        job.reschedule(trigger="interval", hours=interval)
    else:
        # The coroutine is scheduled directly (rather than via
        # asyncio.create_task) so the loop keeps a strong reference to it and
        # max_instances can prevent overlapping sends.
        scheduler.add_job(
            partial(_do_send, user_id),
            "interval",
            hours=interval,
            id=job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )


def start_scheduler() -> None:
    global _scheduler_started
    if _scheduler_started:
        return

    scheduler.start()
    _scheduler_started = True

    db = SessionLocal()
    try:
        for user in db.query(User).all():
            reschedule_for_user(user.id)
    finally:
        db.close()
