"""Shared pytest fixtures.

Auth is always enforced, so tests mint their own valid Supabase-style HS256 JWT
with a known test secret (:data:`TEST_JWT_SECRET`) via :func:`make_token`. The
``client`` fixture installs an ``Authorization: Bearer <token>`` header on every
request by default; tests that exercise the 401 path use the bare ``no_auth_client``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from app.config import Settings
from app.domain.world_model import WorldModel
from app.main import create_app
from fastapi.testclient import TestClient

TEST_JWT_SECRET = "test-super-secret-jwt-key-for-pytest-only"
TEST_USER = "test-user"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def make_token(
    sub: str = TEST_USER,
    secret: str = TEST_JWT_SECRET,
    email: str = "test@example.com",
    exp_in: int = 3600,
    aud: str = "authenticated",
) -> str:
    """Mint a valid HS256 JWT signed with the test ``SUPABASE_JWT_SECRET``."""

    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": sub,
        "email": email,
        "role": "authenticated",
        "aud": aud,
        "exp": int(time.time()) + exp_in,
        "iat": int(time.time()),
    }
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url(signature)}"


@pytest.fixture
def settings() -> Settings:
    # LLM disabled => deterministic, offline tests with no key required.
    # Auth enforced with a known test secret; memory persistence backend.
    return Settings(
        enable_llm=False,
        default_scene="default",
        auth_required=True,
        supabase_jwt_secret=TEST_JWT_SECRET,
        persistence_backend="memory",
    )


@pytest.fixture
def token() -> str:
    return make_token()


@pytest.fixture
def world() -> WorldModel:
    w = WorldModel()
    w.reset("default")
    return w


@pytest.fixture
def client(settings: Settings, token: str) -> TestClient:
    """TestClient that sends a valid Bearer token on every request."""

    app = create_app(settings)
    with TestClient(app) as c:
        c.headers.update({"Authorization": f"Bearer {token}"})
        yield c


@pytest.fixture
def no_auth_client(settings: Settings) -> TestClient:
    """TestClient WITHOUT any auth header (for 401 assertions)."""

    app = create_app(settings)
    with TestClient(app) as c:
        yield c
