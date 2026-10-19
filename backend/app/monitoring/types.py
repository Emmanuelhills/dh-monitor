from dataclasses import dataclass, field
from datetime import date

from app.models import RenewalStatus, ServiceStatus


class CheckErrorCode:
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    AUTH_FAILED = "auth_failed"
    UNSUPPORTED = "unsupported"
    NOT_FOUND = "not_found"
    INVALID_RESPONSE = "invalid_response"
    PROVIDER_ERROR = "provider_error"  # temporary provider-side failure
    CONFIG_ERROR = "config_error"  # permanent; needs administrator action

    TRANSIENT = {TIMEOUT, RATE_LIMITED, PROVIDER_ERROR}


class CheckError(Exception):
    def __init__(self, code: str, message: str, *, source: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.source = source

    @property
    def transient(self) -> bool:
        return self.code in CheckErrorCode.TRANSIENT


@dataclass
class LookupResult:
    """Validated fields returned by a lookup. A field set to None means "not provided",
    never "clear the saved value"."""

    source: str
    expiration_date: date | None = None
    registration_date: date | None = None
    registrar_name: str | None = None
    registry_statuses: list[str] | None = None
    service_status: ServiceStatus | None = None
    renewal_status: RenewalStatus | None = None
    # Fields the source was asked for but did not return (redacted, unsupported, missing).
    missing: list[str] = field(default_factory=list)
    # Sanitized subset of the response, stored in monitoring history.
    observed: dict = field(default_factory=dict)
