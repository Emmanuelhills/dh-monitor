"""Scrub secrets from strings and structures before they are logged, stored or displayed."""

import logging
import re
from typing import Any

_SENSITIVE_KEYS = re.compile(
    r"(pass(word)?|secret|token|api[_-]?key|access[_-]?key|authorization|cookie|credential|session)",
    re.I,
)

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"), "[REDACTED_AWS_KEY_ID]"),
    (
        re.compile(r"(?i)(aws_secret_access_key|secret_access_key|secretaccesskey)(\W{0,3})[A-Za-z0-9/+=]{40}"),
        r"\1\2[REDACTED]",
    ),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [REDACTED]"),
    (
        re.compile(r"(?i)((?:password|passwd|secret|token|api[_-]?key|accesskey|identifier)\s*[=:]\s*)[^\s&,;\"']+"),
        r"\1[REDACTED]",
    ),
    (re.compile(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@"), r"\1[REDACTED]@"),
]


def redact_text(value: str | None, max_length: int = 2000) -> str | None:
    if value is None:
        return None
    text = str(value)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    if len(text) > max_length:
        text = text[:max_length] + "…"
    return text


def redact_data(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if _SENSITIVE_KEYS.search(str(k)) else redact_data(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_data(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class RedactingFilter(logging.Filter):
    """Logging filter that redacts the rendered message and its arguments."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed log call
            return True
        record.msg = redact_text(message, max_length=10000)
        record.args = None
        return True
