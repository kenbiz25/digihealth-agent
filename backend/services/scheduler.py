"""
Scheduler - Triggers the pipeline every day at 7 AM (configurable timezone).
Uses APScheduler with async support.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from backend.config import SCHEDULE_HOUR, SCHEDULE_MINUTE, SCHEDULE_DAY_OF_WEEK, TIMEZONE
from backend.agents.orchestrator import run_pipeline

scheduler = AsyncIOScheduler()
_websocket_broadcast: callable = None


def set_broadcast_callback(callback):
    """Set a callback to broadcast scheduler events to all WebSocket clients."""
    global _websocket_broadcast
    _websocket_broadcast = callback


async def _scheduled_run():
    """The function called by the scheduler at 7 AM."""
    print(f"[Scheduler] Triggered scheduled run at {SCHEDULE_HOUR}:{SCHEDULE_MINUTE} {TIMEZONE}")
    try:
        await run_pipeline(
            trigger="scheduled",
            websocket_callback=_websocket_broadcast,
        )
    except Exception as e:
        print(f"[Scheduler] Run failed: {e}")
        if _websocket_broadcast:
            await _websocket_broadcast({
                "step": "scheduler",
                "status": "failed",
                "message": f"Scheduled run failed: {str(e)}",
            })


def start_scheduler():
    """Start the APScheduler."""
    tz = pytz.timezone(TIMEZONE)
    is_weekly = SCHEDULE_DAY_OF_WEEK and SCHEDULE_DAY_OF_WEEK != "*"
    trigger = CronTrigger(
        day_of_week=SCHEDULE_DAY_OF_WEEK if is_weekly else "*",
        hour=SCHEDULE_HOUR,
        minute=SCHEDULE_MINUTE,
        timezone=tz,
    )
    cadence = f"every {SCHEDULE_DAY_OF_WEEK.capitalize()}" if is_weekly else "daily"
    scheduler.add_job(
        _scheduled_run,
        trigger=trigger,
        id="digital_health_brief",
        replace_existing=True,
        name=f"Digital Health Africa Brief ({cadence})",
    )
    scheduler.start()
    print(f"[Scheduler] Started. Runs {cadence} at {SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d} {TIMEZONE}")


def stop_scheduler():
    """Stop the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown(wait=False)


def get_next_run_time() -> str:
    """Return the next scheduled run time as a string."""
    job = scheduler.get_job("daily_digital_health_brief")
    if job and job.next_run_time:
        return job.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z")
    return "Not scheduled"
