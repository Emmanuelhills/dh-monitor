"""Celery application and beat schedule.

Run (separate processes, independent of the web server):
    celery -A app.celery_app worker --loglevel=INFO --pool=solo     # --pool=solo on Windows
    celery -A app.celery_app beat --loglevel=INFO

Every periodic job is idempotent, so a missed or doubled beat tick is harmless.
"""

from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging

from app.config import get_settings

settings = get_settings()

celery = Celery("dhm", broker=settings.broker_url, include=["app.tasks.jobs"])
celery.conf.update(
    task_always_eager=settings.celery_eager,
    task_eager_propagates=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    beat_schedule={
        "dispatch-due-checks": {"task": "dhm.dispatch_due_checks", "schedule": crontab(minute="*/15")},
        "evaluate-expirations": {"task": "dhm.evaluate_expirations", "schedule": crontab(minute=5)},
        "evaluate-reminders": {"task": "dhm.evaluate_reminders", "schedule": crontab(minute=10)},
        "dispatch-notifications": {"task": "dhm.dispatch_notifications", "schedule": crontab(minute="*/5")},
    },
)


@setup_logging.connect
def _configure_logging(**_):
    from app.logging_setup import configure_logging

    configure_logging()
