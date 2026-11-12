"""Tests for the fixed-window rate limiter."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app
from app.ratelimit import RateLimiter, RateLimitExceeded, check_rate_limit
from fastapi import Request


def make_request(path="/api/v1/decisions/evaluate", host="127.0.0.1"):
    return Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "client": (host, 12345),
            "server": ("127.0.0.1", 8000),
            "scheme": "http",
        }
    )


class TestRateLimiter:
    def test_allows_up_to_limit(self):
        limiter = RateLimiter(limit=3, window_seconds=60)
        assert limiter.allow("k")[0] is True
        assert limiter.allow("k")[0] is True
        assert limiter.allow("k")[0] is True
        assert limiter.allow("k")[0] is False

    def test_remaining_decrements(self):
        limiter = RateLimiter(limit=2, window_seconds=60)
        assert limiter.allow("k")[1] == 1
        assert limiter.allow("k")[1] == 0

    def test_keys_are_independent(self):
        limiter = RateLimiter(limit=1, window_seconds=60)
        assert limiter.allow("a")[0] is True
        assert limiter.allow("b")[0] is True
        assert limiter.allow("a")[0] is False

    def test_window_resets(self):
        limiter = RateLimiter(limit=1, window_seconds=0.05)
        assert limiter.allow("k")[0] is True
        assert limiter.allow("k")[0] is False
        time.sleep(0.06)
        assert limiter.allow("k")[0] is True

    def test_retry_after_reported(self):
        limiter = RateLimiter(limit=1, window_seconds=10)
        limiter.allow("k")
        allowed, remaining, retry_after = limiter.allow("k")
        assert allowed is False
        assert remaining == 0
        assert retry_after > 0

    def test_prune_removes_expired(self):
        limiter = RateLimiter(limit=10, window_seconds=0.01)
        limiter.allow("a")
        limiter.allow("b")
        time.sleep(0.02)
        assert limiter.prune() == 2
        assert limiter.prune() == 0

    def test_check_rate_limit_raises(self):
        limiter = RateLimiter(limit=1, window_seconds=60)
        check_rate_limit(limiter, make_request(), identifier="agent:x")
        with pytest.raises(RateLimitExceeded):
            check_rate_limit(limiter, make_request(), identifier="agent:x")


class TestRateLimitApi:
    @pytest.fixture()
    def client(self):
        init_db()
        with TestClient(app) as test_client:
            yield test_client

    @pytest.fixture()
    def key(self, db) -> str:
        from app.models import Agent
        from app.security import generate_agent_key, hash_key

        agent = db.get(Agent, "agent-support")
        api_key = generate_agent_key()
        agent.credential_hash = hash_key(api_key)
        db.commit()
        return api_key

    def test_exceeding_limit_returns_429(self, client, key, monkeypatch):
        from app.config import get_settings

        # Shrink the window so the test does not make 61 requests.
        monkeypatch.setenv("AGENTGUARD_DECISION_RATE_LIMIT", "2")
        get_settings.cache_clear()

        # Rebuild the app state limiter with the patched settings.
        with TestClient(app) as fresh:
            for _ in range(2):
                response = fresh.post(
                    "/api/v1/decisions/evaluate",
                    headers={"X-Agent-Key": key},
                    json={"tool": "search_knowledge_base", "arguments": {"query": "x"}},
                )
                assert response.status_code == 200
            blocked = fresh.post(
                "/api/v1/decisions/evaluate",
                headers={"X-Agent-Key": key},
                json={"tool": "search_knowledge_base", "arguments": {"query": "x"}},
            )
            assert blocked.status_code == 429
            assert blocked.json()["reason_codes"] == ["RATE_LIMIT_EXCEEDED"]
            assert "Retry-After" in blocked.headers
        get_settings.cache_clear()
