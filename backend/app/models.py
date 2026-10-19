"""SQLAlchemy models.

Design notes
------------
* Expiration dates are DATE (calendar) values; all event timestamps are UTC TIMESTAMPTZ.
* History tables (monitoring checks, notification events) reference their subject with two
  typed nullable foreign keys plus a CHECK constraint that exactly one is set, so the
  database enforces referential integrity instead of relying on a polymorphic id.
* Usage, service, renewal and monitoring status are separate columns by design.
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


def _enum(py_enum: type[enum.Enum], name: str) -> Enum:
    return Enum(py_enum, name=name, values_callable=lambda e: [m.value for m in e])


class UsageStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"


class ServiceStatus(str, enum.Enum):
    active = "active"
    suspended = "suspended"
    expired = "expired"
    unknown = "unknown"


class RenewalStatus(str, enum.Enum):
    unknown = "unknown"
    renewed = "renewed"
    not_renewed = "not_renewed"


class MonitoringStatus(str, enum.Enum):
    current = "current"
    due = "due"
    partial = "partial"
    failed = "failed"
    manual = "manual"


class DataSource(str, enum.Enum):
    """Where the currently saved value of a field came from."""

    manual = "manual"
    rdap = "rdap"
    whois = "whois"
    provider = "provider"


class RecordType(str, enum.Enum):
    domain = "domain"
    hosting = "hosting"


class CheckResult(str, enum.Enum):
    success = "success"
    partial = "partial"
    failure = "failure"


class DeliveryStatus(str, enum.Enum):
    queued = "queued"
    sending = "sending"
    sent = "sent"
    failed = "failed"
    cancelled = "cancelled"


class SesAuthMethod(str, enum.Enum):
    # IAM role / instance profile / environment credentials resolved by the AWS SDK.
    default_chain = "default_chain"
    # Encrypted long-lived (or temporary, with session token) keys stored in secret_values.
    access_keys = "access_keys"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


# --------------------------------------------------------------------------- auth


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))

    user: Mapped[User] = relationship()


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_record", "record_type", "record_id", "created_at"),
        Index("ix_audit_events_action_created", "action", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor: Mapped[str] = mapped_column(String(320), nullable=False)  # email or "system"
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    record_type: Mapped[str | None] = mapped_column(String(32))
    record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    details: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64))


# --------------------------------------------------------------------------- integrations


class ProviderIntegration(TimestampMixin, Base):
    __tablename__ = "provider_integrations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    adapter: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Non-secret configuration (API base URL, etc.). Secrets live in secret_values.
    config: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    secret_name: Mapped[str | None] = mapped_column(String(128))
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_test_message: Mapped[str | None] = mapped_column(Text)


class SecretValue(Base):
    """Encrypted secret store (Fernet). Plaintext never leaves the backend."""

    __tablename__ = "secret_values"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


# --------------------------------------------------------------------------- registrars


class Registrar(TimestampMixin, Base):
    """A company that sells domain registrations, hosting plans, or both."""

    __tablename__ = "registrars"
    __table_args__ = (
        CheckConstraint("for_domains OR for_hosting", name="ck_registrars_kind"),
        Index("uq_registrars_name_lower", func.lower(text("name")), unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    website: Mapped[str | None] = mapped_column(String(2048))
    notes: Mapped[str | None] = mapped_column(Text)
    for_domains: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    for_hosting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


# --------------------------------------------------------------------------- inventory


class MonitoredRecordMixin(TimestampMixin):
    expiration_date: Mapped[date | None] = mapped_column(Date)
    expiration_source: Mapped[DataSource] = mapped_column(
        _enum(DataSource, "data_source"), nullable=False, default=DataSource.manual
    )
    expiration_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    usage_status: Mapped[UsageStatus] = mapped_column(
        _enum(UsageStatus, "usage_status"), nullable=False, default=UsageStatus.active
    )
    service_status: Mapped[ServiceStatus] = mapped_column(
        _enum(ServiceStatus, "service_status"), nullable=False, default=ServiceStatus.unknown
    )
    service_status_source: Mapped[DataSource] = mapped_column(
        _enum(DataSource, "data_source"), nullable=False, default=DataSource.manual
    )
    renewal_status: Mapped[RenewalStatus] = mapped_column(
        _enum(RenewalStatus, "renewal_status"), nullable=False, default=RenewalStatus.unknown
    )
    # The expiration date whose renewal `renewal_status` describes. When it equals the current
    # expiration_date and status is "renewed", the renewal is confirmed but the new date is not
    # yet known, so reminders for that date stop.
    renewal_confirmed_for_date: Mapped[date | None] = mapped_column(Date)
    auto_check_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    monitoring_status: Mapped[MonitoringStatus] = mapped_column(
        _enum(MonitoringStatus, "monitoring_status"), nullable=False, default=MonitoringStatus.due
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successful_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_check_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_check_error: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HostingAccount(MonitoredRecordMixin, Base):
    __tablename__ = "hosting_accounts"
    __table_args__ = (
        Index("ix_hosting_accounts_name_lower", func.lower(text("name"))),
        Index("ix_hosting_accounts_provider_lower", func.lower(text("provider_name"))),
        Index("ix_hosting_accounts_expiration", "expiration_date"),
        Index("ix_hosting_accounts_next_check", "next_check_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(255), nullable=False)
    purchase_date: Mapped[date | None] = mapped_column(Date)
    # Private: only exposed through the dedicated admin-url endpoint.
    admin_url: Mapped[str | None] = mapped_column(Text)
    integration_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("provider_integrations.id", ondelete="SET NULL")
    )
    # Identifier of this account/service at the provider (e.g. WHMCS service id).
    external_ref: Mapped[str | None] = mapped_column(String(255))
    # Hosting company from the Registrars list; provider_name mirrors its name.
    registrar_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("registrars.id", ondelete="SET NULL"), index=True
    )

    integration: Mapped[ProviderIntegration | None] = relationship()
    registrar: Mapped[Registrar | None] = relationship()
    domains: Mapped[list["Domain"]] = relationship(back_populates="hosting_account")


class Domain(MonitoredRecordMixin, Base):
    __tablename__ = "domains"
    __table_args__ = (
        # Unique among non-archived records only.
        Index(
            "uq_domains_normalized_active",
            "normalized_domain_name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_domains_expiration", "expiration_date"),
        Index("ix_domains_hosting", "hosting_account_id"),
        Index("ix_domains_next_check", "next_check_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    domain_name: Mapped[str] = mapped_column(String(253), nullable=False)
    normalized_domain_name: Mapped[str] = mapped_column(String(253), nullable=False)
    # SET NULL: deleting a hosting account never deletes its domains.
    hosting_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("hosting_accounts.id", ondelete="SET NULL")
    )
    registration_date: Mapped[date | None] = mapped_column(Date)
    # Registrar chosen by the administrator from the Registrars list.
    registrar_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("registrars.id", ondelete="SET NULL"), index=True
    )
    # Registrar as reported by RDAP/WHOIS (informational; may differ from registrar_id).
    registrar_name: Mapped[str | None] = mapped_column(String(255))
    registry_statuses: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)

    hosting_account: Mapped[HostingAccount | None] = relationship(back_populates="domains")
    registrar: Mapped[Registrar | None] = relationship()


# --------------------------------------------------------------------------- history


class MonitoringCheck(Base):
    __tablename__ = "monitoring_checks"
    __table_args__ = (
        CheckConstraint(
            "(record_type = 'domain' AND domain_id IS NOT NULL AND hosting_account_id IS NULL) OR "
            "(record_type = 'hosting' AND hosting_account_id IS NOT NULL AND domain_id IS NULL)",
            name="ck_monitoring_checks_subject",
        ),
        Index("ix_monitoring_checks_domain", "domain_id", "checked_at"),
        Index("ix_monitoring_checks_hosting", "hosting_account_id", "checked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    record_type: Mapped[RecordType] = mapped_column(_enum(RecordType, "record_type"), nullable=False)
    domain_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"))
    hosting_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("hosting_accounts.id", ondelete="CASCADE")
    )
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    result: Mapped[CheckResult] = mapped_column(_enum(CheckResult, "check_result"), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    observed_data: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    changes: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    conflicts: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)


class NotificationEvent(Base):
    __tablename__ = "notification_events"
    __table_args__ = (
        CheckConstraint(
            "is_test OR "
            "(record_type = 'domain' AND domain_id IS NOT NULL AND hosting_account_id IS NULL) OR "
            "(record_type = 'hosting' AND hosting_account_id IS NOT NULL AND domain_id IS NULL)",
            name="ck_notification_events_subject",
        ),
        Index("ix_notification_events_status_next", "delivery_status", "next_attempt_at"),
        Index("ix_notification_events_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    # record_type + record_id + expiration_date + reminder_interval + recipient
    dedupe_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    is_test: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    record_type: Mapped[RecordType | None] = mapped_column(_enum(RecordType, "record_type"))
    domain_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"))
    hosting_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("hosting_accounts.id", ondelete="CASCADE")
    )
    record_name: Mapped[str | None] = mapped_column(String(255))
    expiration_date_at_send: Mapped[date | None] = mapped_column(Date)
    reminder_interval: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(512))
    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        _enum(DeliveryStatus, "delivery_status"), nullable=False, default=DeliveryStatus.queued
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


# --------------------------------------------------------------------------- settings & ops


DEFAULT_REMINDER_DAYS = [30, 14, 7, 3, 1]


class ApplicationSettings(Base):
    """Single-row table (id = 1) of non-secret settings editable from the dashboard."""

    __tablename__ = "application_settings"
    __table_args__ = (CheckConstraint("id = 1", name="ck_application_settings_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    domain_check_interval_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    hosting_check_interval_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    stale_after_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=72)
    # Read-only overview at "/" for team members without an account.
    public_page_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notification_recipients: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    reminder_days_before: Mapped[list] = mapped_column(
        JSONType, nullable=False, default=lambda: list(DEFAULT_REMINDER_DAYS)
    )
    remind_on_expiration_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    overdue_reminder_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    remind_suspended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    ses_region: Mapped[str | None] = mapped_column(String(32))
    ses_sender: Mapped[str | None] = mapped_column(String(320))
    ses_configuration_set: Mapped[str | None] = mapped_column(String(255))
    ses_auth_method: Mapped[SesAuthMethod] = mapped_column(
        _enum(SesAuthMethod, "ses_auth_method"), nullable=False, default=SesAuthMethod.default_chain
    )
    ses_last_validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ses_last_validation: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class JobRun(Base):
    """Heartbeat of scheduled jobs, used by health checks and the dashboard."""

    __tablename__ = "job_runs"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(32))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_summary: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
