"""RDAP domain lookups using the IANA bootstrap registry (RFC 9224)."""

import threading
import time
from datetime import date, datetime, timezone

from app.monitoring import http
from app.monitoring.types import CheckError, CheckErrorCode, LookupResult
from app.services.domain_names import tld_of

BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
BOOTSTRAP_TTL_SECONDS = 24 * 3600
SOURCE = "rdap"

_bootstrap: dict[str, str] = {}
_bootstrap_loaded_at = 0.0
_bootstrap_lock = threading.Lock()


def _load_bootstrap() -> dict[str, str]:
    global _bootstrap, _bootstrap_loaded_at
    with _bootstrap_lock:
        if _bootstrap and time.monotonic() - _bootstrap_loaded_at < BOOTSTRAP_TTL_SECONDS:
            return _bootstrap
        response = http.request("GET", BOOTSTRAP_URL, source=SOURCE)
        if error := http.classify_status(response.status_code, SOURCE):
            raise error
        try:
            services = response.json()["services"]
            mapping = {}
            for tlds, urls in services:
                https_urls = [u for u in urls if u.startswith("https://")] or urls
                for tld in tlds:
                    mapping[tld.lower()] = https_urls[0].rstrip("/") + "/"
        except (ValueError, KeyError, TypeError, IndexError):
            raise CheckError(CheckErrorCode.INVALID_RESPONSE, "Invalid RDAP bootstrap file.", source=SOURCE) from None
        _bootstrap, _bootstrap_loaded_at = mapping, time.monotonic()
        return _bootstrap


def rdap_base_url(normalized_domain: str) -> str | None:
    return _load_bootstrap().get(tld_of(normalized_domain))


def _parse_date(value: str | None) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.date()


def _registrar_name(entities: list) -> str | None:
    for entity in entities or []:
        if not isinstance(entity, dict) or "registrar" not in (entity.get("roles") or []):
            continue
        vcard = entity.get("vcardArray")
        if isinstance(vcard, list) and len(vcard) == 2 and isinstance(vcard[1], list):
            for prop in vcard[1]:
                if isinstance(prop, list) and len(prop) >= 4 and prop[0] == "fn" and isinstance(prop[3], str):
                    return prop[3].strip()[:255] or None
        for public_id in entity.get("publicIds") or []:
            if isinstance(public_id, dict) and public_id.get("identifier"):
                return f"IANA ID {public_id['identifier']}"[:255]
    return None


def parse_rdap_domain(payload: dict, normalized_domain: str) -> LookupResult:
    if not isinstance(payload, dict) or payload.get("objectClassName") != "domain":
        raise CheckError(CheckErrorCode.INVALID_RESPONSE, "RDAP response is not a domain object.", source=SOURCE)
    ldh = str(payload.get("ldhName") or "").lower().rstrip(".")
    if ldh != normalized_domain:
        raise CheckError(
            CheckErrorCode.INVALID_RESPONSE,
            f"RDAP response refers to '{ldh or 'unknown'}', not the requested domain.",
            source=SOURCE,
        )

    events = [e for e in payload.get("events") or [] if isinstance(e, dict)]

    def _event(action: str) -> date | None:
        for event in events:
            if str(event.get("eventAction", "")).lower() == action:
                return _parse_date(event.get("eventDate"))
        return None

    statuses = sorted({str(s).lower() for s in payload.get("status") or [] if isinstance(s, str)})
    result = LookupResult(
        source=SOURCE,
        expiration_date=_event("expiration"),
        registration_date=_event("registration"),
        registrar_name=_registrar_name(payload.get("entities") or []),
        registry_statuses=statuses or None,
    )
    for name in ("expiration_date", "registration_date", "registrar_name"):
        if getattr(result, name) is None:
            result.missing.append(name)

    # Only non-personal fields are kept in history.
    result.observed = {
        "ldh_name": ldh,
        "status": statuses,
        "events": [
            {"action": e.get("eventAction"), "date": e.get("eventDate")}
            for e in events
            if e.get("eventAction") in ("registration", "expiration", "last changed", "last update of RDAP database")
        ],
        "registrar": result.registrar_name,
        "nameservers": sorted(
            str(ns.get("ldhName", "")).lower()
            for ns in payload.get("nameservers") or []
            if isinstance(ns, dict) and ns.get("ldhName")
        )[:13],
    }
    return result


def lookup(normalized_domain: str) -> LookupResult:
    base = rdap_base_url(normalized_domain)
    if base is None:
        raise CheckError(CheckErrorCode.UNSUPPORTED, "No RDAP service is registered for this TLD.", source=SOURCE)
    response = http.request(
        "GET", f"{base}domain/{normalized_domain}", source=SOURCE, headers={"Accept": "application/rdap+json"}
    )
    if error := http.classify_status(response.status_code, SOURCE):
        raise error
    try:
        payload = response.json()
    except ValueError:
        raise CheckError(CheckErrorCode.INVALID_RESPONSE, "RDAP response is not valid JSON.", source=SOURCE) from None
    result = parse_rdap_domain(payload, normalized_domain)
    result.source = f"rdap:{base.split('/')[2]}"
    return result
