"""
Scheduler — triggers the pipeline every 2 days at the configured hour (default 07:00).
Uses APScheduler IntervalTrigger so the gap is always exactly 48 hours.
"""
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import pytz

from backend.config import SCHEDULE_HOUR, SCHEDULE_MINUTE, TIMEZONE

scheduler = AsyncIOScheduler()
_websocket_broadcast = None


def set_broadcast_callback(callback):
    global _websocket_broadcast
    _websocket_broadcast = callback


async def _scheduled_run():
    from backend.agents.orchestrator import run_pipeline
    print(f"[Scheduler] Triggered every-2-day run at {SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d} {TIMEZONE}")
    try:
        await run_pipeline(trigger="scheduled", websocket_callback=_websocket_broadcast)
    except Exception as e:
        print(f"[Scheduler] Run failed: {e}")
        if _websocket_broadcast:
            await _websocket_broadcast({
                "step": "scheduler", "status": "failed",
                "message": f"Scheduled run failed: {str(e)}",
            })


def start_scheduler():
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)

    # First fire at the next upcoming HH:MM — today if still in the future, tomorrow otherwise
    start = now.replace(hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE, second=0, microsecond=0)
    if start <= now:
        start += timedelta(days=1)

    trigger = IntervalTrigger(days=2, start_date=start, timezone=tz)

    scheduler.add_job(
        _scheduled_run,
        trigger=trigger,
        id="digital_health_brief",
        replace_existing=True,
        name=f"M.LABS Intelligence — every 2 days at {SCHEDULE_HOUR:02d}:{SCHEDULE_MINUTE:02d}",
    )
    scheduler.start()
    print(f"[Scheduler] Started. Next run: {start.strftime('%Y-%m-%d %H:%M %Z')}, then every 48 h.")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)


def get_next_run_time() -> str:
    job = scheduler.get_job("digital_health_brief")
    if job and job.next_run_time:
        return job.next_run_time.strftime("%Y-%m-%d %H:%M %Z")
    return "Not scheduled"
