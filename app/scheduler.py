import logging
from functools import partial

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database import SessionLocal
from app.email_service import send_email_for_user
from app.models import User
from app.settings_service import get_settings

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
_scheduler_started = False

MIN_INTERVAL_HOURS = 1
MAX_INTERVAL_HOURS = 8760
DEFAULT_INTERVAL_HOURS = 24
DEFAULT_HOUR = 9
DEFAULT_MINUTE = 0


def _get_job_id(user_id: str) -> str:
    return f"email_job_{user_id}"


def _get_schedule_for_user(user_id: str) -> tuple[int, int, int]:
    db = SessionLocal()
    try:
        settings = get_settings(db, user_id)
        try:
            interval = int(float(settings.get("schedule_interval_hours") or DEFAULT_INTERVAL_HOURS))
        except (ValueError, TypeError):
            interval = DEFAULT_INTERVAL_HOURS
        interval = max(MIN_INTERVAL_HOURS, min(interval, MAX_INTERVAL_HOURS))

        try:
            hour = int(float(settings.get("schedule_hour") or DEFAULT_HOUR))
        except (ValueError, TypeError):
            hour = DEFAULT_HOUR
        hour = max(0, min(hour, 23))

        try:
            minute = int(float(settings.get("schedule_minute") or DEFAULT_MINUTE))
        except (ValueError, TypeError):
            minute = DEFAULT_MINUTE
        minute = max(0, min(minute, 59))

        return interval, hour, minute
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
    interval_hours, hour, minute = _get_schedule_for_user(user_id)

    interval_days = max(1, round(interval_hours / 24))
    if interval_days > 1:
        trigger = CronTrigger(hour=hour, minute=minute, day=f"*/{interval_days}")
    else:
        trigger = CronTrigger(hour=hour, minute=minute)

    job = scheduler.get_job(job_id)
    if job:
        job.reschedule(trigger=trigger)
    else:
        scheduler.add_job(
            partial(_do_send, user_id),
            trigger=trigger,
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
