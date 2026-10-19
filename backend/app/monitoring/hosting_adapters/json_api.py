"""Generic adapter for providers that expose a JSON API for a hosting service.

Configured with a URL template, a dotted path to the expiration/renewal date and optionally a
status field plus a mapping of provider status values to service statuses.
"""

from datetime import date, datetime, timezone

from app.models import ServiceStatus
from app.monitoring import http
from app.monitoring.hosting_adapters import AdapterContext, FieldSpec, HostingAdapter, register
from app.monitoring.types import CheckError, CheckErrorCode, LookupResult

SOURCE = "provider:json_api"


def _dig(payload, path: str):
    current = payload
    for part in [p for p in path.split(".") if p]:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def _to_date(value) -> date | None:
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value, timezone.utc).date()
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return (parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed).date()
    return None


class JsonApiAdapter(HostingAdapter):
    key = "json_api"
    label = "Custom JSON API"
    description = "Calls an authorized JSON endpoint for each hosting account and reads the date/status fields you map."
    auth_method = "Bearer token (optional)"
    supported_fields = ("expiration_date", "service_status")
    config_fields = (
        FieldSpec("url_template", "URL template", help="https://api.example.com/services/{external_ref}"),
        FieldSpec("expiration_path", "Expiration field path", help="Dotted path, e.g. data.next_due_date"),
        FieldSpec("status_path", "Status field path", required=False, help="Dotted path, e.g. data.status"),
        FieldSpec(
            "status_map",
            "Status mapping",
            required=False,
            help='JSON object, e.g. {"running": "active", "suspended": "suspended"}',
        ),
    )
    secret_fields = (FieldSpec("token", "Bearer token", required=False),)

    def _url(self, ctx: AdapterContext, ref: str) -> str:
        url = str(ctx.config["url_template"]).replace("{external_ref}", ref)
        if not url.startswith("https://"):
            raise CheckError(CheckErrorCode.CONFIG_ERROR, "URL template must use https://.", source=SOURCE)
        return url

    def _get(self, ctx: AdapterContext, url: str):
        headers = {"Accept": "application/json"}
        if ctx.secrets.get("token"):
            headers["Authorization"] = f"Bearer {ctx.secrets['token']}"
        response = http.request("GET", url, source=SOURCE, headers=headers)
        if error := http.classify_status(response.status_code, SOURCE):
            raise error
        try:
            return response.json()
        except ValueError:
            raise CheckError(CheckErrorCode.INVALID_RESPONSE, "Endpoint did not return JSON.", source=SOURCE) from None

    def test_connection(self, ctx: AdapterContext) -> str:
        self.validate_config(ctx.config, ctx.secrets)
        if not ctx.external_ref:
            return "Configuration looks valid. It will be exercised on the first hosting check."
        self._get(ctx, self._url(ctx, ctx.external_ref))
        return "Endpoint responded with JSON."

    def check(self, ctx: AdapterContext) -> LookupResult:
        self.validate_config(ctx.config, ctx.secrets)
        if not ctx.external_ref:
            raise CheckError(
                CheckErrorCode.CONFIG_ERROR, "Set the provider service ID on this hosting account.", source=SOURCE
            )
        payload = self._get(ctx, self._url(ctx, ctx.external_ref))
        raw_expiration = _dig(payload, ctx.config["expiration_path"])
        result = LookupResult(source=SOURCE, expiration_date=_to_date(raw_expiration))
        raw_status = None
        if ctx.config.get("status_path"):
            raw_status = _dig(payload, ctx.config["status_path"])
            mapping = ctx.config.get("status_map") or {}
            mapped = mapping.get(str(raw_status).lower()) if raw_status is not None else None
            if mapped in ServiceStatus._value2member_map_:
                result.service_status = ServiceStatus(mapped)
        if result.expiration_date is None:
            result.missing.append("expiration_date")
        if result.service_status is None:
            result.missing.append("service_status")
        result.observed = {
            "expiration_raw": str(raw_expiration)[:64] if raw_expiration is not None else None,
            "status_raw": str(raw_status)[:64] if raw_status is not None else None,
        }
        return result


register(JsonApiAdapter())
