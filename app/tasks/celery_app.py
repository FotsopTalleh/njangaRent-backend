# ---------------------------------------------------------------------------
# tasks/celery_app.py — Celery application instance + Beat schedule
# ---------------------------------------------------------------------------
import os

from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

load_dotenv()

_raw_redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
if _raw_redis_url and not _raw_redis_url.startswith("redis://") and not _raw_redis_url.startswith("rediss://"):
    REDIS_URL = f"redis://{_raw_redis_url}"
else:
    REDIS_URL = _raw_redis_url

celery_app = Celery(
    "mytenant",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["tasks.rent_reminder"],
)

celery_app.conf.update(
    task_serializer         = "json",
    accept_content          = ["json"],
    result_serializer       = "json",
    timezone                = "UTC",
    enable_utc              = True,
    task_track_started      = True,
    worker_prefetch_multiplier = 1,
    # Beat schedule
    beat_schedule = {
        "send-rent-reminders-daily": {
            "task":     "tasks.rent_reminder.send_rent_reminders",
            "schedule": crontab(hour=8, minute=0),   # 08:00 UTC daily
        },
    },
)
