"""Redaction helpers.

Nothing that reaches the audit store or an API response may contain secrets
or configured sensitive fields. Redaction happens before persistence.
"""

import json
import re
from typing import Any

DEFAULT_REDACT_FIELDS = ["password", "token", "api_key", "apikey", "authorization", "secret", "body"]

_SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "[redacted]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[redacted]"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "[redacted]"),
    (re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE), "Bearer [redacted]"),
    (re.compile(r"(?i)\b(?:password|api[_-]?key|secret)\b\s*[:=]\s*\S+"), lambda m: m.group(0).split(":")[0].split("=")[0] + "=[redacted]"),
]

REDACTED = "[redacted]"
REDACTED_WITH_LENGTH = "[redacted — {length} chars]"
_MAX_INLINE_LENGTH = 200


def is_sensitive_key(key: str, redact_fields: list[str]) -> bool:
    lowered = key.lower().replace("-", "_").replace(" ", "_")
    return any(field.lower() in lowered for field in redact_fields)


def redact_string(value: str, enabled: bool = True) -> str:
    if not enabled:
        return value
    result = value
    for pattern, replacement in _SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def redact_value(key: str, value: Any, redact_fields: list[str], enabled: bool = True) -> Any:
    if isinstance(value, dict):
        return redact_dict(value, redact_fields, enabled)
    if isinstance(value, list):
        return [redact_value(key, item, redact_fields, enabled) for item in value]
    if isinstance(value, str):
        if enabled and is_sensitive_key(key, redact_fields):
            return REDACTED
        return redact_string(value, enabled)
    return value


def redact_dict(
    obj: dict[str, Any], redact_fields: list[str] | None = None, enabled: bool = True
) -> dict[str, Any]:
    fields = redact_fields or DEFAULT_REDACT_FIELDS
    return {key: redact_value(key, value, fields, enabled) for key, value in obj.items()}


def summarize_arguments(
    arguments: dict[str, Any], redact_fields: list[str] | None = None, enabled: bool = True
) -> dict[str, Any]:
    """Build the safe, human-readable summary shown on approval records.

    Sensitive fields are replaced with ``[redacted]``; long strings are
    replaced with a length marker so approvers get context without the payload.
    """
    fields = redact_fields or DEFAULT_REDACT_FIELDS
    summary: dict[str, Any] = {}
    for key, value in arguments.items():
        if isinstance(value, dict):
            summary[key] = summarize_arguments(value, fields, enabled)
            continue
        if isinstance(value, str) and enabled and is_sensitive_key(key, fields):
            summary[key] = REDACTED
            continue
        if isinstance(value, str) and len(value) > _MAX_INLINE_LENGTH:
            summary[key] = REDACTED_WITH_LENGTH.format(length=len(value))
            continue
        if isinstance(value, str):
            summary[key] = redact_string(value, enabled)
            continue
        summary[key] = value
    return summary


def payload_size(arguments: dict[str, Any]) -> int:
    return len(json.dumps(arguments, separators=(",", ":"), default=str).encode("utf-8"))
