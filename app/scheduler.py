import asyncio
import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.database import SessionLocal
from app.email_service import send_email_for_user
from app.settings_service import get_settings
from app.models import User

scheduler = AsyncIOScheduler()
_scheduler_started = False


def _get_job_id(user_id: str) -> str:
    return f"email_job_{user_id}"


def _get_interval_hours_for_user(user_id: str) -> float:
    db = SessionLocal()
    try:
        settings = get_settings(db, user_id)
        try:
            return max(1, float(settings.get("schedule_interval_hours", "24")))
        except (ValueError, TypeError):
            return 24
    finally:
        db.close()


def _send_email_for_user_job(user_id: str):
    asyncio.create_task(_do_send(user_id))


async def _do_send(user_id: str):
    db = SessionLocal()
    try:
        success, error = await send_email_for_user(db, user_id)
        if error:
            print(f"Scheduled email failed for user {user_id}: {error}")
    finally:
        db.close()


def reschedule_for_user(user_id: str):
    job_id = _get_job_id(user_id)
    interval = _get_interval_hours_for_user(user_id)
    job = scheduler.get_job(job_id)
    if job:
        job.reschedule(trigger="interval", hours=interval)
    else:
        scheduler.add_job(
            lambda: _send_email_for_user_job(user_id),
            "interval",
            hours=interval,
            id=job_id,
            replace_existing=True,
        )


def start_scheduler():
    global _scheduler_started
    if _scheduler_started:
        return

    scheduler.start()
    _scheduler_started = True

    db = SessionLocal()
    try:
        users = db.query(User).all()
        for user in users:
            reschedule_for_user(user.id)
    finally:
        db.close()
