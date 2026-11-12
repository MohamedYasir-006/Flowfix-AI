"""Credential hashing, token issuance, and role helpers.

Agent API keys are hashed with SHA-256 before storage; the plaintext key is
returned exactly once when the credential is created or rotated. Dashboard
tokens are HMAC-signed, expiring bearer tokens suitable for local development
and behind a real OIDC provider in production.
"""

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone

from .config import get_settings

KEY_PREFIX = "ag_"
TOKEN_TTL_HOURS = 12


def generate_agent_key() -> str:
    return f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def verify_key(key: str | None, credential_hash: str | None) -> bool:
    if not key or not credential_hash:
        return False
    candidate = hash_key(key)
    return hmac.compare_digest(candidate, credential_hash)


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_access_token(user_id: str) -> str:
    """Create an HMAC-signed bearer token for a dashboard user."""
    settings = get_settings()
    payload = {
        "sub": user_id,
        "exp": (datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)).isoformat(),
    }
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(
        settings.auth_secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return f"{body}.{signature}"


def verify_access_token(token: str | None) -> str | None:
    """Return the user id for a valid token, else ``None``."""
    if not token or "." not in token:
        return None
    body, _, signature = token.rpartition(".")
    settings = get_settings()
    expected = hmac.new(
        settings.auth_secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(_b64decode(body))
    except (ValueError, json.JSONDecodeError):
        return None
    try:
        expires = datetime.fromisoformat(payload["exp"])
    except (KeyError, ValueError):
        return None
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        return None
    return payload.get("sub")
