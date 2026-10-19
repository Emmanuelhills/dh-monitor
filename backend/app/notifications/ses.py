"""Amazon SES (v2 API) client wrapper with error classification."""

from dataclasses import dataclass

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError, NoCredentialsError
from sqlalchemy.orm import Session

from app.models import ApplicationSettings, SesAuthMethod
from app.services.redaction import redact_text
from app.services.secrets import SES_CREDENTIALS, SecretStoreError, get_secret

TRANSIENT_CODES = {
    "Throttling",
    "ThrottlingException",
    "TooManyRequestsException",
    "LimitExceededException",
    "ServiceUnavailable",
    "InternalFailure",
    "InternalServiceError",
    "RequestTimeout",
}


class SesError(Exception):
    def __init__(self, message: str, *, transient: bool, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.transient = transient
        self.code = code


class SesNotConfigured(SesError):
    def __init__(self, message: str):
        super().__init__(message, transient=False, code="not_configured")


@dataclass
class OutgoingEmail:
    to: str
    subject: str
    text: str
    html: str


def _classify(exc: Exception) -> SesError:
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "ClientError")
        message = exc.response.get("Error", {}).get("Message", "")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        transient = code in TRANSIENT_CODES or status >= 500
        return SesError(redact_text(f"{code}: {message}", 500), transient=transient, code=code)
    if isinstance(exc, NoCredentialsError):
        return SesError("No AWS credentials are available to the application.", transient=False, code="NoCredentials")
    if isinstance(exc, EndpointConnectionError):
        return SesError("Could not reach the Amazon SES endpoint.", transient=True, code="EndpointConnectionError")
    if isinstance(exc, BotoCoreError):
        return SesError(redact_text(f"{type(exc).__name__}: {exc}", 500), transient=True, code=type(exc).__name__)
    return SesError(redact_text(str(exc), 500), transient=False)


def make_client(db: Session, settings: ApplicationSettings):
    if not settings.ses_region:
        raise SesNotConfigured("Choose an AWS region for Amazon SES.")
    kwargs = {
        "region_name": settings.ses_region,
        "config": Config(retries={"max_attempts": 2, "mode": "standard"}, connect_timeout=10, read_timeout=20),
    }
    if settings.ses_auth_method == SesAuthMethod.access_keys:
        try:
            creds = get_secret(db, SES_CREDENTIALS)
        except SecretStoreError as exc:
            raise SesNotConfigured(str(exc)) from None
        if not creds:
            raise SesNotConfigured("AWS access keys are selected but have not been saved.")
        kwargs.update(
            aws_access_key_id=creds["access_key_id"],
            aws_secret_access_key=creds["secret_access_key"],
            aws_session_token=creds.get("session_token") or None,
        )
    return boto3.client("sesv2", **kwargs)


def send_email(db: Session, settings: ApplicationSettings, email: OutgoingEmail) -> str:
    """Submit an email to SES. Returns the SES MessageId (acceptance, not proof of delivery)."""
    if not settings.ses_sender:
        raise SesNotConfigured("Set a verified sender address.")
    client = make_client(db, settings)
    request = {
        "FromEmailAddress": settings.ses_sender,
        "Destination": {"ToAddresses": [email.to]},
        "Content": {
            "Simple": {
                "Subject": {"Data": email.subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": email.text, "Charset": "UTF-8"},
                    "Html": {"Data": email.html, "Charset": "UTF-8"},
                },
            }
        },
    }
    if settings.ses_configuration_set:
        request["ConfigurationSetName"] = settings.ses_configuration_set
    try:
        response = client.send_email(**request)
    except Exception as exc:  # noqa: BLE001 - classified below
        raise _classify(exc) from None
    return response.get("MessageId", "")


def validate_configuration(db: Session, settings: ApplicationSettings) -> dict:
    """Check account sending status and sender identity verification. Never raises."""
    checks: dict = {
        "region": settings.ses_region,
        "sender": settings.ses_sender,
        "credentials": None,
        "sending_enabled": None,
        "production_access": None,
        "sender_verified": None,
        "quota": None,
        "problems": [],
    }
    try:
        client = make_client(db, settings)
        account = client.get_account()
        checks["credentials"] = True
        checks["sending_enabled"] = bool(account.get("SendingEnabled"))
        checks["production_access"] = bool(account.get("ProductionAccessEnabled"))
        quota = account.get("SendQuota") or {}
        checks["quota"] = {
            "max_24_hour_send": quota.get("Max24HourSend"),
            "max_send_rate": quota.get("MaxSendRate"),
            "sent_last_24_hours": quota.get("SentLast24Hours"),
        }
        if not checks["sending_enabled"]:
            checks["problems"].append("Sending is disabled for this SES account.")
        if not checks["production_access"]:
            checks["problems"].append(
                "The SES account is in the sandbox: recipients must also be verified identities."
            )
        if settings.ses_sender:
            checks["sender_verified"] = _identity_verified(client, settings.ses_sender)
            if not checks["sender_verified"]:
                checks["problems"].append("The sender address (or its domain) is not a verified SES identity.")
        else:
            checks["problems"].append("No sender address is configured.")
    except SesError as exc:
        checks["credentials"] = False if exc.code in ("not_configured", "NoCredentials") else checks["credentials"]
        checks["problems"].append(exc.message)
    except Exception as exc:  # noqa: BLE001
        err = _classify(exc)
        if err.code in ("AccessDeniedException", "UnrecognizedClientException", "InvalidClientTokenId",
                        "SignatureDoesNotMatch", "NoCredentials"):
            checks["credentials"] = False
        checks["problems"].append(err.message)
    return checks


def _identity_verified(client, sender: str) -> bool:
    candidates = [sender, sender.rsplit("@", 1)[-1]]
    for identity in candidates:
        try:
            info = client.get_email_identity(EmailIdentity=identity)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "NotFoundException":
                continue
            raise
        if info.get("VerifiedForSendingStatus"):
            return True
    return False
