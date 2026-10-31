import uuid
from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import (
    CheckResult,
    DataSource,
    DeliveryStatus,
    MonitoringStatus,
    RecordType,
    RenewalStatus,
    ServiceStatus,
    SesAuthMethod,
    UsageStatus,
)
from app.services.domain_names import InvalidDomainName, normalize_domain_name

T = TypeVar("T")

NotesField = Field(default=None, max_length=10000)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class ExpirationOut(BaseModel):
    days_remaining: int | None
    urgency: str
    label: str


# --------------------------------------------------------------------------- auth


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=512)


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    csrf_token: str


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=12, max_length=512)


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=12, max_length=512)


class TokenCheckIn(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class AdminPasswordIn(BaseModel):
    password: str = Field(min_length=12, max_length=512)


class AdminCreateIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=512)


class AdminOut(ORMModel):
    id: uuid.UUID
    email: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


# --------------------------------------------------------------------------- shared record fields


class RecordWriteBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expiration_date: date | None = None
    usage_status: UsageStatus | None = None
    service_status: ServiceStatus | None = None
    renewal_status: RenewalStatus | None = None
    auto_check_enabled: bool | None = None
    notifications_enabled: bool | None = None
    notes: str | None = NotesField

    @field_validator("expiration_date")
    @classmethod
    def _sane_expiration(cls, v: date | None) -> date | None:
        if v is not None and not (date(1985, 1, 1) <= v <= date(2200, 12, 31)):
            raise ValueError("Expiration date is out of the supported range (1985–2200).")
        return v


class RecordOutBase(ORMModel):
    id: uuid.UUID
    expiration_date: date | None
    expiration_source: DataSource
    expiration_verified_at: datetime | None
    expiration: ExpirationOut
    usage_status: UsageStatus
    service_status: ServiceStatus
    service_status_source: DataSource
    renewal_status: RenewalStatus
    renewal_confirmed_for_date: date | None
    auto_check_enabled: bool
    notifications_enabled: bool
    monitoring_status: MonitoringStatus
    last_checked_at: datetime | None
    last_successful_check_at: datetime | None
    next_check_at: datetime | None
    check_requested_at: datetime | None
    last_check_error: str | None
    is_stale: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


# --------------------------------------------------------------------------- domains


def _validate_domain(v: str) -> str:
    try:
        normalize_domain_name(v)
    except InvalidDomainName as exc:
        raise ValueError(str(exc)) from None
    return v.strip()


class DomainCreate(RecordWriteBase):
    domain_name: str = Field(min_length=1, max_length=300)
    hosting_account_id: uuid.UUID | None = None
    registrar_id: uuid.UUID | None = None
    registration_date: date | None = None
    registrar_name: str | None = Field(default=None, max_length=255)

    @field_validator("domain_name")
    @classmethod
    def _check_domain(cls, v: str) -> str:
        return _validate_domain(v)


class DomainUpdate(RecordWriteBase):
    domain_name: str | None = Field(default=None, min_length=1, max_length=300)
    hosting_account_id: uuid.UUID | None = None
    registrar_id: uuid.UUID | None = None
    registration_date: date | None = None
    registrar_name: str | None = Field(default=None, max_length=255)

    @field_validator("domain_name")
    @classmethod
    def _check_domain(cls, v: str | None) -> str | None:
        return None if v is None else _validate_domain(v)


class RegistrarRef(ORMModel):
    id: uuid.UUID
    name: str


class HostingRef(ORMModel):
    id: uuid.UUID
    name: str
    provider_name: str


class DomainOut(RecordOutBase):
    domain_name: str
    normalized_domain_name: str
    display_name: str
    hosting_account: HostingRef | None
    registrar: RegistrarRef | None
    registration_date: date | None
    registrar_name: str | None
    registry_statuses: list[str]


class DomainSummary(ORMModel):
    id: uuid.UUID
    domain_name: str
    expiration_date: date | None
    expiration: ExpirationOut
    usage_status: UsageStatus
    service_status: ServiceStatus
    monitoring_status: MonitoringStatus


# --------------------------------------------------------------------------- hosting


class HostingCreate(RecordWriteBase):
    name: str = Field(min_length=1, max_length=255)
    # Either pick a registrar (hosting company) or type the company name.
    provider_name: str | None = Field(default=None, min_length=1, max_length=255)
    registrar_id: uuid.UUID | None = None
    purchase_date: date | None = None
    admin_url: str | None = Field(default=None, max_length=2048)
    integration_id: uuid.UUID | None = None
    external_ref: str | None = Field(default=None, max_length=255)

    @field_validator("name", "provider_name")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("Must not be blank.")
        return v

    @field_validator("admin_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v is None or v.strip() == "":
            return None
        v = v.strip()
        if not (v.startswith("https://") or v.startswith("http://")):
            raise ValueError("Admin URL must start with http:// or https://.")
        return v


class HostingUpdate(HostingCreate):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    provider_name: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("name", "provider_name")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("Must not be blank.")
        return v


class IntegrationRef(ORMModel):
    id: uuid.UUID
    name: str
    adapter: str


class HostingOut(RecordOutBase):
    name: str
    provider_name: str
    registrar: RegistrarRef | None
    purchase_date: date | None
    has_admin_url: bool
    integration: IntegrationRef | None
    external_ref: str | None
    domain_count: int


class HostingDetailOut(HostingOut):
    domains: list[DomainSummary]


class AdminUrlOut(BaseModel):
    admin_url: str | None


# --------------------------------------------------------------------------- registrars


class RegistrarIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    website: str | None = Field(default=None, max_length=2048)
    notes: str | None = NotesField
    for_domains: bool | None = None
    for_hosting: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("Must not be blank.")
        return v

    @field_validator("website")
    @classmethod
    def _website(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not v.startswith(("https://", "http://")):
            v = "https://" + v
        return v


class RegistrarOut(ORMModel):
    id: uuid.UUID
    name: str
    website: str | None
    notes: str | None
    for_domains: bool
    for_hosting: bool
    domain_count: int
    hosting_count: int
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- monitoring


class MonitoringCheckOut(ORMModel):
    id: uuid.UUID
    record_type: RecordType
    source: str
    result: CheckResult
    checked_at: datetime
    duration_ms: int | None
    observed_data: dict
    changes: dict
    conflicts: dict
    error_code: str | None
    error_message: str | None


class CheckQueuedOut(BaseModel):
    status: Literal["queued", "already_queued", "not_supported", "completed"]
    requested_at: datetime | None
    message: str


class AuditEventOut(ORMModel):
    id: uuid.UUID
    created_at: datetime
    actor: str
    action: str
    record_type: str | None
    record_id: uuid.UUID | None
    details: dict


# --------------------------------------------------------------------------- notifications


class NotificationOut(ORMModel):
    id: uuid.UUID
    is_test: bool
    record_type: RecordType | None
    domain_id: uuid.UUID | None
    hosting_account_id: uuid.UUID | None
    record_name: str | None
    expiration_date_at_send: date | None
    reminder_interval: str
    recipient: str
    subject: str | None
    delivery_status: DeliveryStatus
    attempt_count: int
    next_attempt_at: datetime | None
    last_attempt_at: datetime | None
    provider_message_id: str | None
    sent_at: datetime | None
    last_error: str | None
    created_at: datetime


class NotificationSettingsOut(BaseModel):
    notifications_enabled: bool
    notification_recipients: list[str]
    reminder_days_before: list[int]
    remind_on_expiration_day: bool
    overdue_reminder_days: int
    remind_suspended: bool
    email_provider: Literal["ses", "resend"]
    resend_sender: str | None
    resend_api_key_set: bool
    ses_region: str | None
    ses_sender: str | None
    ses_configuration_set: str | None
    ses_auth_method: SesAuthMethod
    ses_credentials_set: bool
    ses_last_validated_at: datetime | None
    ses_last_validation: dict


class SesCredentialsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_key_id: str = Field(min_length=16, max_length=128, pattern=r"^[A-Z0-9]+$")
    secret_access_key: str = Field(min_length=16, max_length=256)
    session_token: str | None = Field(default=None, max_length=4096)


class NotificationSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notifications_enabled: bool | None = None
    notification_recipients: list[EmailStr] | None = Field(default=None, max_length=20)
    reminder_days_before: list[int] | None = Field(default=None, max_length=20)
    remind_on_expiration_day: bool | None = None
    overdue_reminder_days: int | None = Field(default=None, ge=0, le=60)
    remind_suspended: bool | None = None
    email_provider: Literal["ses", "resend"] | None = None
    resend_sender: EmailStr | None = None
    resend_api_key: str | None = Field(default=None, min_length=8, max_length=256, pattern=r"^\S+$")
    clear_resend_api_key: bool = False
    ses_region: str | None = Field(default=None, pattern=r"^[a-z]{2}(-[a-z]+)+-\d$")
    ses_sender: EmailStr | None = None
    ses_configuration_set: str | None = Field(default=None, max_length=255)
    ses_auth_method: SesAuthMethod | None = None
    ses_credentials: SesCredentialsIn | None = None
    clear_ses_credentials: bool = False

    @field_validator("reminder_days_before")
    @classmethod
    def _days(cls, v: list[int] | None) -> list[int] | None:
        if v is None:
            return None
        if any(d < 1 or d > 365 for d in v):
            raise ValueError("Reminder days must be between 1 and 365.")
        return sorted(set(v), reverse=True)


class TestEmailIn(BaseModel):
    recipient: EmailStr | None = None


class TestEmailOut(BaseModel):
    ok: bool
    accepted: bool
    message: str
    checks: dict
    provider_message_id: str | None = None


# --------------------------------------------------------------------------- general settings


class GeneralSettingsOut(BaseModel):
    timezone: str
    domain_check_interval_hours: int
    hosting_check_interval_hours: int
    stale_after_hours: int
    public_page_enabled: bool


class GeneralSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str | None = Field(default=None, max_length=64)
    domain_check_interval_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    hosting_check_interval_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    stale_after_hours: int | None = Field(default=None, ge=1, le=24 * 90)
    public_page_enabled: bool | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        if v is None:
            return None
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"Unknown timezone '{v}'.") from None
        return v


# --------------------------------------------------------------------------- integrations


class AdapterInfoOut(BaseModel):
    key: str
    label: str
    description: str
    auth_method: str
    supported_fields: list[str]
    config_fields: list[dict]
    secret_fields: list[dict]


class IntegrationOut(ORMModel):
    id: uuid.UUID
    name: str
    adapter: str
    enabled: bool
    config: dict
    secret_set: bool
    last_tested_at: datetime | None
    last_test_ok: bool | None
    last_test_message: str | None
    hosting_account_count: int
    created_at: datetime


class IntegrationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    adapter: str = Field(min_length=1, max_length=64)
    enabled: bool = True
    config: dict = Field(default_factory=dict)
    secrets: dict[str, str] | None = None


class IntegrationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    enabled: bool | None = None
    config: dict | None = None
    secrets: dict[str, str] | None = None


class IntegrationTestOut(BaseModel):
    ok: bool
    message: str
