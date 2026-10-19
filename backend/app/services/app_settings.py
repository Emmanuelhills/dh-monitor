from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import ApplicationSettings
from app.notifications.schedule import ScheduleConfig


def get_app_settings(db: Session) -> ApplicationSettings:
    row = db.get(ApplicationSettings, 1)
    if row is None:
        db.execute(insert(ApplicationSettings).values(id=1).on_conflict_do_nothing())
        db.flush()
        row = db.get(ApplicationSettings, 1)
    return row


def schedule_config(settings: ApplicationSettings) -> ScheduleConfig:
    return ScheduleConfig(
        days_before=tuple(int(d) for d in settings.reminder_days_before),
        on_expiration_day=settings.remind_on_expiration_day,
        overdue_days=settings.overdue_reminder_days,
        remind_suspended=settings.remind_suspended,
    )
