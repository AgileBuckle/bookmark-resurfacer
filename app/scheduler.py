import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.database import SessionLocal
from app.email_service import send_email
from app.settings_service import get_settings

scheduler = AsyncIOScheduler()
_scheduler_started = False


def _get_interval_hours() -> float:
    db = SessionLocal()
    try:
        settings = get_settings(db)
        try:
            return max(1, float(settings.get("schedule_interval_hours", "24")))
        except (ValueError, TypeError):
            return 24
    finally:
        db.close()


def _send_email_job():
    asyncio.create_task(_do_send())


async def _do_send():
    db = SessionLocal()
    try:
        await send_email(db)
    finally:
        db.close()


def start_scheduler():
    global _scheduler_started
    if _scheduler_started:
        return

    scheduler.add_job(
        _send_email_job,
        "interval",
        hours=_get_interval_hours(),
        id="email_job",
        replace_existing=True,
    )
    scheduler.start()
    _scheduler_started = True


def reschedule():
    job = scheduler.get_job("email_job")
    if job:
        job.reschedule(trigger="interval", hours=_get_interval_hours())