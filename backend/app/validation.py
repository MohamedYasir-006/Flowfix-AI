"""Minimal JSON-Schema validation for tool arguments.

Supports the subset used by registered tools: ``type``, ``required``,
``properties``, ``enum``, ``format`` (email), and numeric bounds. Keeping this
local avoids a dependency and keeps policy checks deterministic.
"""

import re
from typing import Any

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def validate_arguments(schema: dict[str, Any] | None, arguments: dict[str, Any]) -> list[str]:
    """Return a list of human-readable validation errors (empty when valid)."""
    if not schema:
        return []
    if not isinstance(arguments, dict):
        return ["arguments must be a JSON object"]

    errors: list[str] = []
    schema_type = schema.get("type")
    if schema_type == "object" and not isinstance(arguments, dict):
        return ["arguments must be a JSON object"]

    for field_name in schema.get("required", []):
        if field_name not in arguments:
            errors.append(f"missing required field: {field_name}")

    properties = schema.get("properties", {})
    for field_name, value in arguments.items():
        field_schema = properties.get(field_name)
        if field_schema is None:
            continue  # additional properties are allowed
        errors.extend(_validate_field(field_name, value, field_schema))

    return errors


def _validate_field(name: str, value: Any, field_schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected = field_schema.get("type")
    if expected and expected in _TYPE_CHECKS and not _TYPE_CHECKS[expected](value):
        errors.append(f"{name} must be of type {expected}")
        return errors

    enum = field_schema.get("enum")
    if enum is not None and value not in enum:
        errors.append(f"{name} must be one of {enum}")

    field_format = field_schema.get("format")
    if field_format == "email" and isinstance(value, str) and not _EMAIL_RE.match(value):
        errors.append(f"{name} must be a valid email address")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in field_schema and value < field_schema["minimum"]:
            errors.append(f"{name} must be >= {field_schema['minimum']}")
        if "maximum" in field_schema and value > field_schema["maximum"]:
            errors.append(f"{name} must be <= {field_schema['maximum']}")

    if expected == "object" and isinstance(value, dict):
        errors.extend(validate_arguments(field_schema, value))
    if expected == "array" and isinstance(value, list):
        item_schema = field_schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                errors.extend(_validate_field(f"{name}[{index}]", item, item_schema))

    return errors
