"""Shared outbound HTTP helpers: timeouts, per-host rate limiting, error classification."""

import threading
import time
from urllib.parse import urlsplit

import httpx

from app.config import get_settings
from app.monitoring.types import CheckError, CheckErrorCode

USER_AGENT = "DomainHostingMonitor/1.0 (+expiration monitoring)"

_last_request: dict[str, float] = {}
_lock = threading.Lock()


def throttle(host: str) -> None:
    """Keep at least ``lookup_min_interval_seconds`` between requests to the same host
    (per worker process)."""
    interval = get_settings().lookup_min_interval_seconds
    with _lock:
        wait = _last_request.get(host, 0) + interval - time.monotonic()
        _last_request[host] = time.monotonic() + max(wait, 0)
    if wait > 0:
        time.sleep(wait)


def classify_status(status_code: int, source: str) -> CheckError | None:
    if status_code < 400:
        return None
    if status_code == 404:
        return CheckError(CheckErrorCode.NOT_FOUND, "The source has no record for this name.", source=source)
    if status_code == 429:
        return CheckError(CheckErrorCode.RATE_LIMITED, "The source rate-limited the request.", source=source)
    if status_code in (401, 403):
        return CheckError(CheckErrorCode.AUTH_FAILED, "The source rejected the credentials.", source=source)
    if status_code >= 500:
        return CheckError(CheckErrorCode.PROVIDER_ERROR, f"The source returned HTTP {status_code}.", source=source)
    return CheckError(CheckErrorCode.INVALID_RESPONSE, f"Unexpected HTTP {status_code}.", source=source)


def request(method: str, url: str, *, source: str, **kwargs) -> httpx.Response:
    throttle(urlsplit(url).hostname or url)
    headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
    try:
        with httpx.Client(timeout=get_settings().http_timeout_seconds, follow_redirects=True) as client:
            return client.request(method, url, headers=headers, **kwargs)
    except httpx.TimeoutException:
        raise CheckError(CheckErrorCode.TIMEOUT, "The request timed out.", source=source) from None
    except httpx.HTTPError as exc:
        raise CheckError(
            CheckErrorCode.PROVIDER_ERROR, f"Network error: {type(exc).__name__}", source=source
        ) from None
