"""Shared helpers: canonical payload hashing and small formatting utilities."""

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def payload_hash(tool: str, target: str | None, arguments: dict[str, Any]) -> str:
    """Bind an action to an exact payload.

    The hash covers tool, target, and arguments so a changed payload cannot
    reuse an approval.
    """
    body = canonical_json({"tool": tool, "target": target or "", "arguments": arguments})
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
