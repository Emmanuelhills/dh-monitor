"""Sends email through the provider chosen in Settings → Email: Amazon SES or Resend."""

from sqlalchemy.orm import Session

from app.models import ApplicationSettings
from app.notifications import resend, ses
from app.notifications.ses import OutgoingEmail, SesError

EmailError = SesError

PROVIDERS = {"ses": "Amazon SES", "resend": "Resend"}


def provider_of(settings: ApplicationSettings) -> str:
    return settings.email_provider if settings.email_provider in PROVIDERS else "ses"


def provider_label(settings: ApplicationSettings) -> str:
    return PROVIDERS[provider_of(settings)]


def sender_of(settings: ApplicationSettings) -> str | None:
    return settings.resend_sender if provider_of(settings) == "resend" else settings.ses_sender


def send_email(db: Session, settings: ApplicationSettings, email: OutgoingEmail) -> str:
    module = resend if provider_of(settings) == "resend" else ses
    return module.send_email(db, settings, email)


def validate_configuration(db: Session, settings: ApplicationSettings) -> dict:
    if provider_of(settings) == "resend":
        return resend.validate_configuration(db, settings)
    return {"provider": "ses", **ses.validate_configuration(db, settings)}


def is_configured(settings: ApplicationSettings) -> bool:
    if provider_of(settings) == "resend":
        return bool(settings.resend_sender)
    return bool(settings.ses_sender and settings.ses_region)
