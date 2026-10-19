"""WHMCS adapter (many hosting resellers and providers run WHMCS for billing).

Uses the documented WHMCS API (``/includes/api.php``) with API credentials created under
System Settings → API Credentials. ``external_ref`` is the WHMCS service (product) id.
"""

from datetime import date

from app.models import RenewalStatus, ServiceStatus
from app.monitoring import http
from app.monitoring.hosting_adapters import AdapterContext, FieldSpec, HostingAdapter, register
from app.monitoring.types import CheckError, CheckErrorCode, LookupResult

SOURCE = "provider:whmcs"

_STATUS_MAP = {
    "active": (ServiceStatus.active, None),
    "suspended": (ServiceStatus.suspended, None),
    "terminated": (ServiceStatus.expired, RenewalStatus.not_renewed),
    "cancelled": (None, RenewalStatus.not_renewed),
    "pending": (ServiceStatus.unknown, None),
    "fraud": (ServiceStatus.suspended, None),
}


def _parse_date(value) -> date | None:
    if not value or not isinstance(value, str) or value.startswith("0000"):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


class WhmcsAdapter(HostingAdapter):
    key = "whmcs"
    label = "WHMCS"
    description = "Reads next due date and service status from a WHMCS installation's API."
    auth_method = "API identifier + secret"
    supported_fields = ("expiration_date", "service_status", "renewal_status", "purchase_date")
    config_fields = (
        FieldSpec("api_url", "WHMCS URL", help="Base URL, e.g. https://billing.example.com"),
    )
    secret_fields = (
        FieldSpec("identifier", "API identifier"),
        FieldSpec("secret", "API secret"),
        FieldSpec("access_key", "API access key", required=False, help="Only if your WHMCS requires one."),
    )

    def _call(self, ctx: AdapterContext, action: str, **params) -> dict:
        self.validate_config(ctx.config, ctx.secrets)
        url = ctx.config["api_url"].rstrip("/") + "/includes/api.php"
        if not url.startswith("https://"):
            raise CheckError(CheckErrorCode.CONFIG_ERROR, "WHMCS URL must use https://.", source=SOURCE)
        data = {
            "action": action,
            "identifier": ctx.secrets["identifier"],
            "secret": ctx.secrets["secret"],
            "responsetype": "json",
            **params,
        }
        if ctx.secrets.get("access_key"):
            data["accesskey"] = ctx.secrets["access_key"]
        response = http.request("POST", url, source=SOURCE, data=data)
        if error := http.classify_status(response.status_code, SOURCE):
            raise error
        try:
            payload = response.json()
        except ValueError:
            raise CheckError(CheckErrorCode.INVALID_RESPONSE, "WHMCS returned non-JSON output.", source=SOURCE) from None
        if payload.get("result") != "success":
            message = str(payload.get("message") or "WHMCS reported an error.")[:300]
            code = (
                CheckErrorCode.AUTH_FAILED
                if "authentication" in message.lower() or "invalid ip" in message.lower()
                else CheckErrorCode.INVALID_RESPONSE
            )
            raise CheckError(code, f"WHMCS: {message}", source=SOURCE)
        return payload

    def test_connection(self, ctx: AdapterContext) -> str:
        payload = self._call(ctx, "WhmcsDetails")
        version = (payload.get("whmcs") or {}).get("version", "unknown")
        return f"Connected to WHMCS (version {version})."

    def check(self, ctx: AdapterContext) -> LookupResult:
        if not ctx.external_ref:
            raise CheckError(
                CheckErrorCode.CONFIG_ERROR, "Set the provider service ID on this hosting account.", source=SOURCE
            )
        payload = self._call(ctx, "GetClientsProducts", serviceid=ctx.external_ref)
        products = ((payload.get("products") or {}).get("product")) or []
        product = next((p for p in products if str(p.get("id")) == str(ctx.external_ref)), None)
        if product is None:
            raise CheckError(CheckErrorCode.NOT_FOUND, "WHMCS has no service with this ID.", source=SOURCE)

        raw_status = str(product.get("status") or "").lower()
        service_status, renewal_status = _STATUS_MAP.get(raw_status, (None, None))
        result = LookupResult(
            source=SOURCE,
            expiration_date=_parse_date(product.get("nextduedate")),
            registration_date=_parse_date(product.get("regdate")),
            service_status=service_status,
            renewal_status=renewal_status,
        )
        if result.expiration_date is None:
            result.missing.append("expiration_date")
        if service_status is None:
            result.missing.append("service_status")
        result.observed = {
            "service_id": str(product.get("id")),
            "product": str(product.get("name") or product.get("groupname") or "")[:255],
            "status": raw_status,
            "next_due_date": product.get("nextduedate"),
            "billing_cycle": product.get("billingcycle"),
            "registration_date": product.get("regdate"),
        }
        return result


register(WhmcsAdapter())
