"""WHOIS (port 43) fallback for TLDs without RDAP.

WHOIS output is unstructured, so only a small set of well-known labels is parsed and any
ambiguity leaves the field unset rather than guessing.
"""

import re
import socket
from datetime import date, timezone

from dateutil import parser as date_parser

from app.config import get_settings
from app.monitoring import http
from app.monitoring.types import CheckError, CheckErrorCode, LookupResult
from app.services.domain_names import tld_of

IANA_WHOIS = "whois.iana.org"
SOURCE = "whois"
MAX_RESPONSE_BYTES = 256 * 1024

_EXPIRY_LABELS = [
    "registry expiry date",
    "registrar registration expiration date",
    "expiration date",
    "expiry date",
    "expire date",
    "expires on",
    "expires",
    "paid-till",
    "renewal date",
    "expiration time",
]
_CREATED_LABELS = ["creation date", "created on", "created", "registered on", "registration time", "registered"]
_REGISTRAR_LABELS = ["registrar", "sponsoring registrar", "registrar name"]
_NOT_FOUND = re.compile(
    r"(no match for|not found|no data found|no entries found|status:\s*free|domain not found|is available)", re.I
)


def _query(server: str, query: str) -> str:
    http.throttle(server)
    try:
        with socket.create_connection((server, 43), timeout=get_settings().http_timeout_seconds) as sock:
            sock.sendall((query + "\r\n").encode("idna"))
            chunks, total = [], 0
            while total < MAX_RESPONSE_BYTES:
                data = sock.recv(4096)
                if not data:
                    break
                chunks.append(data)
                total += len(data)
    except TimeoutError:
        raise CheckError(CheckErrorCode.TIMEOUT, f"WHOIS server {server} timed out.", source=SOURCE) from None
    except OSError as exc:
        raise CheckError(
            CheckErrorCode.PROVIDER_ERROR, f"WHOIS connection to {server} failed: {type(exc).__name__}", source=SOURCE
        ) from None
    return b"".join(chunks).decode("utf-8", errors="replace")


def _fields(text: str) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for line in text.splitlines():
        if ":" not in line or line.lstrip().startswith(("%", "#", ">>>")):
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if value:
            fields.setdefault(key.strip().lower(), []).append(value)
    return fields


def _first_date(fields: dict[str, list[str]], labels: list[str]) -> date | None:
    for label in labels:
        for value in fields.get(label, []):
            try:
                parsed = date_parser.parse(value, dayfirst=False, yearfirst=True, fuzzy=False)
            except (ValueError, OverflowError):
                continue
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc)
            return parsed.date()
    return None


def whois_server_for(normalized_domain: str) -> str | None:
    text = _query(IANA_WHOIS, tld_of(normalized_domain))
    for value in _fields(text).get("whois", []):
        return value.strip()
    return None


def parse_whois(text: str, normalized_domain: str) -> LookupResult:
    if _NOT_FOUND.search(text[:2000]):
        raise CheckError(CheckErrorCode.NOT_FOUND, "WHOIS reports no registration for this domain.", source=SOURCE)
    fields = _fields(text)
    names = [v.lower().rstrip(".") for v in fields.get("domain name", []) + fields.get("domain", [])]
    if names and normalized_domain not in names:
        raise CheckError(
            CheckErrorCode.INVALID_RESPONSE, "WHOIS response refers to a different domain.", source=SOURCE
        )
    registrar = next((v[:255] for label in _REGISTRAR_LABELS for v in fields.get(label, [])), None)
    result = LookupResult(
        source=SOURCE,
        expiration_date=_first_date(fields, _EXPIRY_LABELS),
        registration_date=_first_date(fields, _CREATED_LABELS),
        registrar_name=registrar,
        registry_statuses=sorted(
            {v.split()[0].lower() for v in fields.get("domain status", []) + fields.get("status", []) if v}
        )
        or None,
    )
    for name in ("expiration_date", "registration_date", "registrar_name"):
        if getattr(result, name) is None:
            result.missing.append(name)
    result.observed = {
        "matched_domain": bool(names),
        "expiration_date": result.expiration_date.isoformat() if result.expiration_date else None,
        "registration_date": result.registration_date.isoformat() if result.registration_date else None,
        "registrar": registrar,
        "status": result.registry_statuses or [],
    }
    return result


def lookup(normalized_domain: str) -> LookupResult:
    server = whois_server_for(normalized_domain)
    if not server:
        raise CheckError(CheckErrorCode.UNSUPPORTED, "No WHOIS server is published for this TLD.", source=SOURCE)
    result = parse_whois(_query(server, normalized_domain), normalized_domain)
    result.source = f"whois:{server}"
    return result
